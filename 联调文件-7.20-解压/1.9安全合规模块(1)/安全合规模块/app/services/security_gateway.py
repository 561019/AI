"""安全合规网关 —— 简化版，仅包含 check() 方法。

六层安全检查：
  第零层：海外大模型直接拦截
  第一层：网络环境 + 数据密级
  第二层：违规词检查
  第三层：敏感词脱敏
  第四层：数据不出域
  第五层：权限管理
"""
import json as _json
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories.audit_repository import AuditRepository
from app.repositories.json_store import JsonStore
from app.services.audit_trace_center import AuditTraceCenter
from app.services.context_builder import RuntimeContextBuilder
from app.services.io_compliance_guard import IOComplianceGuard
from app.services.masking_engine import DataMaskingEngine
from app.services.model_boundary_guard import ModelBoundaryGuard


def _build_data_domain_result(model_result) -> dict:
    return {
        "can_use_external_model": model_result.allow_external_model,
        "model_scope": model_result.model_scope.value,
        "allowed_model_tags": model_result.allowed_model_tags,
        "forbidden_model_tags": model_result.forbidden_model_tags,
        "hit_rules": model_result.hit_rules,
        "reason": "核心机密不允许上公网、不允许进入海外大模型" if not model_result.allow_external_model else "数据出域检查通过",
    }


class SecurityGateway:
    def __init__(self) -> None:
        self.store = JsonStore()
        self.context_builder = RuntimeContextBuilder(self.store)
        self.io_guard = IOComplianceGuard(self.store)
        self.masking_engine = DataMaskingEngine(self.store)
        self.model_guard = ModelBoundaryGuard(self.store)
        self.audit_repo = AuditRepository()
        self.audit_center = AuditTraceCenter(self.audit_repo)

    # ═══════════════════════════════════════════════════════════════
    # 简化安全检查接口
    # ═══════════════════════════════════════════════════════════════

    def check(self, input_text: str, real_person_id: str, is_emergency: bool = False,
              data_classification: str = "public", network: str = "intranet",
              model_type: str = "domestic", output_files: list[dict] | None = None,
              output_text: str = "") -> dict:
        """六层安全检查。"""
        output_files = output_files or []

        request_id = f"req_{uuid4().hex[:8]}"
        trace_id = f"trace_{uuid4().hex[:12]}"
        audit_id = f"audit_{uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()
        is_confidential = (data_classification == "confidential")
        is_public_data = (data_classification == "public")

        _account_records = self.store.find("accounts", person_id=real_person_id)
        account_id = _account_records[0].get("account_id", f"acc_{real_person_id}") if _account_records else f"acc_{real_person_id}"

        _empty_model = {"passed": True, "model_type": model_type, "reason": "", "checked": False}
        _empty_check = {"passed": True, "risk_level": "low", "hit_words": [], "hit_rules": [], "suggestion": "", "checked": False}
        _empty_mask = {"need_masking": False, "masked_text": input_text, "findings": [], "checked": False}
        _empty_domain = {"can_use_external_model": True, "model_scope": "external_allowed", "allowed_model_tags": ["external", "private", "local"], "forbidden_model_tags": [], "hit_rules": [], "reason": "", "checked": False}
        _empty_perm = {"has_permission": True, "deny_reason": "", "matched_role": "", "matched_domain": "", "checked": False}

        # 跟踪已完成检查的层
        _checked_model: dict | None = None
        _checked_network: dict | None = None

        def _quick_deny(code, reason, **overrides):
            result = {
                "request_id": request_id, "audit_id": audit_id, "trace_id": trace_id,
                "model_check": _empty_model, "network_check": _empty_check,
                "violation": _empty_check, "masking": _empty_mask,
                "data_domain": _empty_domain, "permission": _empty_perm,
                "decision": "deny", "decision_reason": reason,
            }
            result.update(overrides)
            return result

        # ── 构建上下文 ──
        from app.schemas.security import SecurityCheckRequest
        req = SecurityCheckRequest(
            input_text=input_text, real_person_id=real_person_id,
            is_emergency=is_emergency, data_classification=data_classification,
            network=network, model_type=model_type,
            output_files=output_files, output_text=output_text,
        )
        ctx = self.context_builder.build_from_check(req, account_id)

        # ═══════════════════════════════════════════════════════════
        # 第零层：海外大模型直接拦截
        # ═══════════════════════════════════════════════════════════
        if model_type == "overseas":
            self._write_check_audit(
                audit_id=audit_id, trace_id=trace_id, request_id=request_id,
                account_id=account_id, real_person_id=real_person_id,
                input_text=input_text, decision="deny", code="SEC_DENY_OVERSEAS_MODEL",
                reason="海外大模型不允许使用，请选择国内大模型",
                violation_result=None, masking_result=None, permission_result=None,
                created_at=created_at, output_text=output_text,
            )
            self._write_check_spans(trace_id, audit_id, "deny", "SEC_DENY_OVERSEAS_MODEL",
                                    violation_result=None, masking_result=None, permission_result=None,
                                    created_at=created_at,
                                    model_result={"passed": False, "model_type": "overseas", "reason": "海外大模型直接拦截", "checked": True})
            return _quick_deny("SEC_DENY_OVERSEAS_MODEL", "海外大模型不允许使用，请选择国内大模型。",
                               model_check={"passed": False, "model_type": "overseas", "reason": "海外大模型直接拦截，优先级最高", "checked": True})

        _checked_model = {"passed": True, "model_type": model_type, "reason": "", "checked": True}

        # ═══════════════════════════════════════════════════════════
        # 第一层：网络环境 + 数据密级
        # ═══════════════════════════════════════════════════════════
        if is_confidential and network == "public":
            self._write_check_audit(
                audit_id=audit_id, trace_id=trace_id, request_id=request_id,
                account_id=account_id, real_person_id=real_person_id,
                input_text=input_text, decision="deny", code="SEC_DENY_CONFIDENTIAL_PUBLIC_NET",
                reason="核心机密不允许在公网操作", violation_result=None, masking_result=None,
                permission_result=None, created_at=created_at, output_text=output_text,
            )
            self._write_check_spans(trace_id, audit_id, "deny", "SEC_DENY_CONFIDENTIAL_PUBLIC_NET",
                                    violation_result=None, masking_result=None, permission_result=None,
                                    created_at=created_at,
                                    model_result=_checked_model,
                                    network_result={"passed": False, "risk_level": "critical", "hit_words": ["核心机密+公网"], "hit_rules": [], "suggestion": "请切换至内网环境或选择公开数据。", "checked": True})
            return _quick_deny("SEC_DENY_CONFIDENTIAL_PUBLIC_NET", "核心机密不允许在公网操作，请切换至内网。",
                               model_check=_checked_model,
                               network_check={"passed": False, "risk_level": "critical", "hit_words": ["核心机密+公网"], "hit_rules": [], "suggestion": "请切换至内网环境或选择公开数据。", "checked": True})

        _checked_network = {"passed": True, "risk_level": "low", "hit_words": [], "hit_rules": [], "suggestion": "", "checked": True}

        # ═══════════════════════════════════════════════════════════
        # 第二层：违规词检查
        # ═══════════════════════════════════════════════════════════
        io_result = self.io_guard.check(ctx)
        vio_passed = io_result.passed
        vio_risk = io_result.risk_level
        vio_words: list[str] = []
        vio_rules: list[dict] = []
        vio_hint = ""
        for hit in io_result.scanner_results:
            vio_words.append(str(hit.get("evidence", "")))
            vio_rules.append(hit)
            if not hit.get("passed") and hit.get("suggestion"):
                vio_hint = str(hit.get("suggestion"))

        if not vio_passed and vio_risk in ("high", "critical"):
            self._write_check_audit(
                audit_id=audit_id, trace_id=trace_id, request_id=request_id,
                account_id=account_id, real_person_id=real_person_id,
                input_text=input_text, decision="deny", code="SEC_DENY_VIOLATION",
                reason="命中违规词/平台红线，已拦截",
                violation_result={"passed": False, "risk_level": vio_risk, "hit_words": vio_words},
                masking_result=None, permission_result=None, created_at=created_at,
                output_text=output_text,
            )
            self._write_check_spans(trace_id, audit_id, "deny", "SEC_DENY_VIOLATION",
                                    violation_result={"passed": False, "risk_level": vio_risk, "hit_rules": vio_rules, "checked": True},
                                    masking_result=None, permission_result=None,
                                    created_at=created_at, model_result=_checked_model, network_result=_checked_network)
            return _quick_deny("SEC_DENY_VIOLATION", "违规词拦截：输入包含违法或平台红线内容。",
                               model_check=_checked_model, network_check=_checked_network,
                               violation={"passed": False, "risk_level": vio_risk, "hit_words": vio_words, "hit_rules": vio_rules, "suggestion": vio_hint or "输入包含违规内容，请修改后重新提交。", "checked": True})

        # ═══════════════════════════════════════════════════════════
        # 第三层：敏感词脱敏
        # ═══════════════════════════════════════════════════════════
        masking_result = self.masking_engine.mask(input_text=input_text, output_text=output_text)
        masked_text = masking_result.masked_payload.get("input_text", input_text)

        # ═══════════════════════════════════════════════════════════
        # 第四层：数据不出域
        # ═══════════════════════════════════════════════════════════
        model_result = self.model_guard.check(ctx, masking_hit=masking_result.need_masking)
        data_domain = _build_data_domain_result(model_result)
        if is_confidential:
            if model_type == "local":
                data_domain["can_use_external_model"] = False
                data_domain["model_scope"] = "local_only"
                data_domain["allowed_model_tags"] = ["local"]
                data_domain["forbidden_model_tags"] = ["external", "oversea", "domestic_cloud"]
                data_domain["reason"] = "核心机密使用本地模型处理，数据不离开内网，通过。"
            elif model_type == "domestic":
                data_domain["can_use_external_model"] = False
                data_domain["model_scope"] = "local_only"
                data_domain["allowed_model_tags"] = ["local"]
                data_domain["forbidden_model_tags"] = ["external", "oversea", "domestic_cloud"]
                data_domain["reason"] = "核心机密不允许上国内云端大模型，请切换至本地模型（local）处理。当前选择为国内大模型（domestic），数据出域检查不通过。"
            else:
                data_domain["can_use_external_model"] = False
                data_domain["model_scope"] = "private_only"
                data_domain["forbidden_model_tags"] = ["external", "oversea"]
                data_domain["reason"] = "核心机密不允许上公网、不允许进入海外大模型"
        else:
            data_domain["can_use_external_model"] = True
            data_domain["model_scope"] = "external_allowed"
            data_domain["allowed_model_tags"] = ["external", "private", "local"]
            data_domain["forbidden_model_tags"] = []
            data_domain["reason"] = "公开数据不受数据出域限制，所有模型可用。"
        data_domain["checked"] = True

        # 第四层拦截
        if "不通过" in data_domain.get("reason", ""):
            self._write_check_audit(
                audit_id=audit_id, trace_id=trace_id, request_id=request_id,
                account_id=account_id, real_person_id=real_person_id,
                input_text=input_text, decision="deny", code="SEC_DENY_DATA_DOMAIN",
                reason=data_domain["reason"],
                violation_result={"passed": vio_passed, "risk_level": vio_risk, "hit_words": vio_words},
                masking_result={"need_masking": masking_result.need_masking, "findings_count": len(masking_result.findings)},
                permission_result=None, created_at=created_at, output_text=output_text,
            )
            self._write_check_spans(trace_id, audit_id, "deny", "SEC_DENY_DATA_DOMAIN",
                                    violation_result={"passed": vio_passed, "risk_level": vio_risk, "hit_rules": vio_rules, "checked": True},
                                    masking_result=masking_result, permission_result=None,
                                    created_at=created_at, model_result=_checked_model, network_result=_checked_network,
                                    data_domain_result=data_domain)
            return _quick_deny("SEC_DENY_DATA_DOMAIN", data_domain["reason"],
                               model_check=_checked_model, network_check=_checked_network,
                               violation={"passed": vio_passed, "risk_level": vio_risk, "hit_words": vio_words, "hit_rules": vio_rules, "suggestion": vio_hint, "checked": True},
                               masking={"need_masking": masking_result.need_masking, "masked_text": masked_text if masking_result.need_masking else input_text, "findings": masking_result.findings, "checked": True},
                               data_domain=data_domain)

        # ═══════════════════════════════════════════════════════════
        # 第五层：权限管理
        # ═══════════════════════════════════════════════════════════
        if is_public_data:
            perm_result = {"has_permission": True, "deny_reason": "", "matched_role": real_person_id, "matched_domain": "", "checked": True}
        elif is_emergency or ctx.is_emergency_account:
            perm_result = {"has_permission": True, "deny_reason": "", "matched_role": "emergency_account", "matched_domain": ctx.domain_id or "", "checked": True}
        else:
            perm_result = {"has_permission": False, "deny_reason": "仅应急监察账号拥有操作权限，当前账号无权限。", "matched_role": "", "matched_domain": "", "checked": True}

        if not perm_result["has_permission"]:
            self._write_check_audit(
                audit_id=audit_id, trace_id=trace_id, request_id=request_id,
                account_id=account_id, real_person_id=real_person_id,
                input_text=input_text, decision="deny", code="SEC_DENY_NO_PERMISSION",
                reason=perm_result["deny_reason"] or "超出权责范围，已拦截",
                violation_result={"passed": vio_passed, "risk_level": vio_risk, "hit_words": vio_words},
                masking_result={"need_masking": masking_result.need_masking, "findings_count": len(masking_result.findings)},
                permission_result={"has_permission": False, "deny_reason": perm_result["deny_reason"]},
                created_at=created_at, output_text=output_text,
            )
            self._write_check_spans(trace_id, audit_id, "deny", "SEC_DENY_NO_PERMISSION",
                                    violation_result={"passed": vio_passed, "risk_level": vio_risk, "hit_rules": vio_rules, "checked": True},
                                    masking_result=masking_result,
                                    permission_result={"has_permission": False, "deny_reason": perm_result["deny_reason"], "checked": True},
                                    created_at=created_at, model_result=_checked_model, network_result=_checked_network,
                                    data_domain_result=data_domain)
            return _quick_deny("SEC_DENY_NO_PERMISSION", f"权限不足：{perm_result['deny_reason'] or '无权限执行此操作'}。",
                               model_check=_checked_model, network_check=_checked_network,
                               violation={"passed": vio_passed, "risk_level": vio_risk, "hit_words": vio_words, "hit_rules": vio_rules, "suggestion": vio_hint, "checked": True},
                               masking={"need_masking": masking_result.need_masking, "masked_text": masked_text if masking_result.need_masking else input_text, "findings": masking_result.findings, "checked": True},
                               data_domain=data_domain, permission=perm_result)

        # ═══════════════════════════════════════════════════════════
        # 全部通过
        # ═══════════════════════════════════════════════════════════
        self._write_check_audit(
            audit_id=audit_id, trace_id=trace_id, request_id=request_id,
            account_id=account_id, real_person_id=real_person_id,
            input_text=input_text, decision="allow", code="SEC_ALLOW",
            reason="安全检查通过",
            violation_result={"passed": True, "risk_level": "low", "hit_words": []},
            masking_result={"need_masking": masking_result.need_masking, "findings_count": len(masking_result.findings)},
            permission_result={"has_permission": True, "deny_reason": ""},
            created_at=created_at, output_text=output_text,
        )
        self._write_check_spans(trace_id, audit_id, "allow", "SEC_ALLOW",
                                violation_result={"passed": True, "risk_level": "low", "hit_rules": [], "checked": True},
                                masking_result=masking_result,
                                permission_result={"has_permission": True, "deny_reason": "", "checked": True},
                                created_at=created_at, model_result=_checked_model, network_result=_checked_network,
                                data_domain_result=data_domain, output_files=output_files, output_text=output_text)
        return {
            "request_id": request_id, "audit_id": audit_id, "trace_id": trace_id,
            "model_check": _checked_model,
            "network_check": _checked_network,
            "violation": {"passed": True, "risk_level": "low", "hit_words": [], "hit_rules": [], "suggestion": "", "checked": True},
            "masking": {"need_masking": masking_result.need_masking, "masked_text": masked_text if masking_result.need_masking else input_text, "findings": masking_result.findings, "checked": True},
            "data_domain": data_domain,
            "permission": perm_result,
            "decision": "allow",
            "decision_reason": "安全检查通过。" + (" 公开数据，跳过权限检查。" if is_public_data else ""),
        }

    # ── 审计日志 ──
    def _write_check_audit(self, *, audit_id: str, trace_id: str, request_id: str,
                           account_id: str, real_person_id: str, input_text: str,
                           decision: str, code: str, reason: str,
                           violation_result: dict | None,
                           masking_result: dict | None,
                           permission_result: dict | None,
                           created_at: str, output_text: str = "") -> None:
        audit_record = {
            "audit_id": audit_id, "request_id": request_id, "trace_id": trace_id,
            "idempotency_key": None, "callback_url": None,
            "stage": "check", "caller_module": "1.9", "scene_code": "check",
            "account_id": account_id, "real_person_id": real_person_id,
            "active_position_id": None, "domain_id": None,
            "agent_id": None, "responsible_person_id": None,
            "action_type": "check", "operation": "check", "target_system": None,
            "decision": decision, "code": code, "reason": reason,
            "hit_policy_ids": _json.dumps({"violation": violation_result, "masking": masking_result, "permission": permission_result}, ensure_ascii=False),
            "need_masking": 1 if (masking_result and masking_result.get("need_masking")) else 0,
            "need_human_confirm": 0,
            "audit_level": "strong" if decision == "deny" else "normal",
            "risk_level": (violation_result.get("risk_level", "low") if violation_result and not violation_result.get("passed") else "low"),
            "input_text": input_text,
            "output_text": output_text,
            "created_at": created_at,
        }
        try:
            self.audit_repo.insert_audit_log(audit_record)
        except Exception:
            pass

    # ── 操作留痕 ──
    def _write_check_spans(self, trace_id: str, audit_id: str, decision: str, code: str,
                           violation_result: dict | None, masking_result: dict | None,
                           permission_result: dict | None, created_at: str,
                           model_result: dict | None = None, network_result: dict | None = None,
                           data_domain_result: dict | None = None,
                           output_files: list[dict] | None = None, output_text: str = "") -> None:
        import json as _json

        def _checked(r: dict | None) -> bool:
            if r is None:
                return False
            if isinstance(r, dict):
                return bool(r.get("checked", False))
            return True

        def _write_one(span_type: str, label: str, result: dict | None,
                       denier: str, denier_code: str, obs_fn=None) -> None:
            span_id = f"span_{uuid4().hex[:12]}"
            if _checked(result):
                if result:
                    passed = result.get("passed", True) if isinstance(result, dict) else True
                    if span_type == "data_domain_check":
                        passed = "不通过" not in (result.get("reason", "") if isinstance(result, dict) else "")
                    if span_type == "permission_check":
                        passed = result.get("has_permission", True) if isinstance(result, dict) else True
                    span_decision = "allow" if passed else "deny"
                    span_code = "SEC_ALLOW" if passed else denier_code
                else:
                    span_decision = "allow"
                    span_code = "SEC_ALLOW"
            else:
                span_decision = "none"
                span_code = ""
            self._insert_span(span_id, trace_id, audit_id, span_type, label,
                              span_decision, span_code,
                              _json.dumps({"check_type": span_type}, ensure_ascii=False),
                              _json.dumps(result if isinstance(result, dict) else {}, ensure_ascii=False),
                              created_at)
            if obs_fn and _checked(result):
                obs_fn(span_id)

        # 0: 模型选择
        _write_one("model_check", "模型选择检查", model_result, "海外大模型", "SEC_DENY_OVERSEAS_MODEL")
        # 1: 网络+密级
        _write_one("network_check", "网络环境+数据密级检查", network_result, "核心机密+公网", "SEC_DENY_CONFIDENTIAL_PUBLIC_NET")
        # 2: 违规词
        def _obs_violation(span_id: str):
            if violation_result:
                for rule in (violation_result.get("hit_rules") or []):
                    self._insert_observation(trace_id, audit_id, span_id, "violation_hit", rule.get("rule_name", ""), rule.get("severity", "low"), _json.dumps(rule, ensure_ascii=False), created_at)
        _write_one("violation_check", "违规词输入检查", violation_result, "违规词", code, obs_fn=_obs_violation)
        # 3: 脱敏
        def _obs_masking(span_id: str):
            if masking_result is not None:
                findings_list = masking_result.get("findings") if isinstance(masking_result, dict) else (masking_result.findings if hasattr(masking_result, 'findings') else [])
                for finding in (findings_list or []):
                    self._insert_observation(trace_id, audit_id, span_id, "masking_finding", finding.get("entity_type", ""), "medium", _json.dumps(finding, ensure_ascii=False), created_at)
        _write_one("masking_check", "敏感词脱敏处理", masking_result, "脱敏", "SEC_NEED_MASKING", obs_fn=_obs_masking)
        # 4: 数据出域
        _write_one("data_domain_check", "数据出域检查", data_domain_result, "数据出域", "SEC_DENY_DATA_DOMAIN")
        # 5: 权限
        def _obs_permission(span_id: str):
            if permission_result:
                has_p = permission_result.get("has_permission") if isinstance(permission_result, dict) else permission_result.has_permission
                if not has_p:
                    deny_r = permission_result.get("deny_reason") if isinstance(permission_result, dict) else permission_result.deny_reason
                    self._insert_observation(trace_id, audit_id, span_id, "permission_deny", "权限拒绝", "high", _json.dumps({"deny_reason": deny_r}, ensure_ascii=False), created_at)
        _write_one("permission_check", "权限管理校验", permission_result, "权限", "SEC_DENY_NO_PERMISSION", obs_fn=_obs_permission)

        # AI 返回文件
        if output_files:
            for file_info in output_files:
                if isinstance(file_info, dict):
                    name = file_info.get("name", "unknown")
                    file_type = file_info.get("type", "unknown")
                else:
                    name = str(file_info)
                    file_type = "unknown"
                if not name or name == "unknown":
                    continue
                self._insert_observation(trace_id, audit_id, "", "ai_output_file", name, "info",
                                         _json.dumps({"file_name": name, "file_type": file_type}, ensure_ascii=False), created_at)

        # AI 返回语句
        if output_text and output_text.strip():
            self._insert_observation(trace_id, audit_id, "", "ai_output_text", "AI返回语句", "info",
                                     _json.dumps({"output_text": output_text}, ensure_ascii=False), created_at)

    def _insert_span(self, span_id: str, trace_id: str, audit_id: str, span_type: str,
                     span_name: str, decision: str, code: str, input_json: str, output_json: str, created_at: str) -> None:
        try:
            self.audit_repo.insert_trace_span({
                "span_id": span_id, "trace_id": trace_id, "audit_id": audit_id,
                "parent_span_id": None, "span_type": span_type, "module": "1.9",
                "stage": "check", "decision": decision, "code": code,
                "latency_ms": 0, "input_json": input_json, "output_json": output_json,
                "created_at": created_at,
            })
        except Exception:
            pass

    def _insert_observation(self, trace_id: str, audit_id: str, span_id: str,
                            obs_type: str, name: str, level: str, payload: str, created_at: str) -> None:
        try:
            self.audit_repo.insert_observation({
                "observation_id": f"obs_{uuid4().hex[:12]}",
                "span_id": span_id, "trace_id": trace_id, "audit_id": audit_id,
                "observation_type": obs_type, "name": name, "level": level,
                "payload_json": payload, "created_at": created_at,
            })
        except Exception:
            pass
