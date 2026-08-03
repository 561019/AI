"""L1.6 context lifecycle service.

Normal conversations remain isolated.  This service only prepares explicitly
imported material for intent analysis, owns the 80/85% lifecycle, and records
the three handoff artefacts.  It never reads SQLite directly: all records go
through the foundation gateway and foundation-data service.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from framework.core import standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json


CAPABILITIES = {
    "context.intent.prepare", "context.capacity.evaluate", "context.handoff.generate",
    "context.handoff.import", "context.project.search", "context.account.search",
    "context.reference.import", "context.control_center.query",
}
WARNING_RATIO = 0.80
HANDOFF_RATIO = 0.85


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in sorted(CAPABILITIES)]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/context-prompts/instructions":
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = str((envelope.get("target") or {}).get("capability") or envelope.get("action") or "")
    if capability not in CAPABILITIES:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_SUPPORTED", "capability": capability}))
        return
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    try:
        if capability == "context.intent.prepare":
            data = _prepare_intent_context(envelope, payload)
        elif capability == "context.capacity.evaluate":
            data = _evaluate_capacity(envelope, payload)
        elif capability == "context.handoff.generate":
            data = _generate_handoff(envelope, payload)
        elif capability == "context.handoff.import":
            data = _import_material(envelope, payload, cross_project=False)
        elif capability == "context.reference.import":
            data = _import_material(envelope, payload, cross_project=True)
        elif capability == "context.project.search":
            data = _search(envelope, payload, account_scope=False)
        elif capability == "context.control_center.query":
            data = _control_center_query(envelope, payload)
        else:
            data = _search(envelope, payload, account_scope=True)
    except ContextError as exc:
        handler.send(exc.status, standard_response(envelope, "failed", error={"code": exc.code, "message": exc.message, "retryable": exc.retryable}))
        return
    handler.send(200, standard_response(envelope, "success", data=data))


class ContextError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 422, retryable: bool = False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


def _identity(envelope: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str, str, str]:
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    tenant_id = str(actor.get("tenant_id") or "")
    owner = str(actor.get("user_id") or actor.get("actor_id") or "")
    project_id = str(payload.get("project_id") or context.get("project_id") or "")
    conversation_id = str(payload.get("conversation_id") or context.get("conversation_id") or "")
    if not tenant_id or not owner:
        raise ContextError("ACCOUNT_CONTEXT_REQUIRED", "上下文操作需要当前员工的真实账号身份", status=403)
    return tenant_id, owner, project_id, conversation_id


def _foundation(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    task_id = str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4())
    inner = make_internal_envelope(
        str(envelope.get("trace_id") or uuid4()), actor, task_id, capability,
        "foundation", "foundation-gateway", payload,
        source_layer="foundation", source_module="context-prompt-management",
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else {},
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions", inner, timeout=120 if capability == "foundation_data.write" else 45,
        caller={"layer": "foundation", "module": "context-prompt-management"},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        raise ContextError("CONTEXT_FOUNDATION_CALL_FAILED", f"上下文模块调用 {capability} 失败", status=502, retryable=True)
    return response.get("data") if isinstance(response.get("data"), dict) else {}


def _query(envelope: dict[str, Any], dataset: str, filters: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    data = _foundation(envelope, "foundation_data.query", {"dataset": dataset, "filters": filters, "limit": limit, "compact": dataset == "conversation_messages"})
    return data.get("items") if isinstance(data.get("items"), list) else []


def _write(envelope: dict[str, Any], dataset: str, record: dict[str, Any]) -> None:
    _foundation(envelope, "foundation_data.write", {"dataset": dataset, "operation": "upsert", "records": [record]})


def _prepare_intent_context(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    _, owner, project_id, conversation_id = _identity(envelope, payload)
    if not project_id or not conversation_id:
        raise ContextError("CONVERSATION_CONTEXT_REQUIRED", "intent analysis requires current project and conversation")
    utterance = str(payload.get("utterance") or payload.get("text") or "").strip()
    imports = _query(envelope, "context_imports", {"target_conversation_id": conversation_id, "owner_account_id": owner}, 100)
    materials = [
        {key: item.get(key) for key in ("source_record_type", "source_record_id", "title", "content", "source_project_id", "imported_at")}
        for item in imports if str(item.get("target_project_id") or project_id) == project_id
    ]
    messages = _query(
        envelope,
        "conversation_messages",
        {"conversation_id": conversation_id, "owner_account_id": owner, "project_id": project_id},
        300,
    )
    selected_messages = _select_relevant_conversation_context(
        messages,
        utterance=utterance,
        current_trace_id=str(envelope.get("trace_id") or ""),
        fallback_items=payload.get("conversation_context") if isinstance(payload.get("conversation_context"), list) else [],
        limit=12,
    )
    imported_context = _compact_imported_materials(materials, limit=8)
    return {
        "scope": "conversation",
        "conversation_id": conversation_id,
        "project_id": project_id,
        "materials": materials,
        "conversation_context": imported_context + selected_messages,
        "context_ref": f"ctx-intent:{conversation_id}",
        "selection": {
            "strategy": "relevance_filtered",
            "candidate_message_count": len(messages),
            "selected_message_count": len(selected_messages),
            "imported_material_count": len(imported_context),
        },
    }


def _compact_imported_materials(materials: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in materials[: max(0, limit)]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        title = str(item.get("title") or item.get("source_record_type") or "导入上下文材料").strip()
        compact.append({
            "role": "context",
            "content_type": "context_import",
            "title": title,
            "content": f"{title}\n{content}"[:2000],
            "created_at": item.get("imported_at"),
            "source_record_id": item.get("source_record_id"),
            "source_project_id": item.get("source_project_id"),
        })
    return compact


def _select_relevant_conversation_context(
    messages: list[dict[str, Any]],
    *,
    utterance: str,
    current_trace_id: str,
    fallback_items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    terms = _context_terms(utterance)
    follow_up = _is_follow_up_question(utterance)
    ordered = sorted(
        [item for item in messages if isinstance(item, dict)],
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )
    for index, item in enumerate(ordered):
        compact_item = _compact_conversation_context_item(item)
        content = compact_item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if current_trace_id and str(compact_item.get("trace_id") or "") == current_trace_id:
            continue
        if utterance and compact_item.get("role") == "user" and content.strip() == utterance:
            continue
        dedupe_key = (str(compact_item.get("role") or ""), content)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        score = _conversation_context_score(
            compact_item,
            terms=terms,
            current_text=utterance,
            follow_up=follow_up,
            recency_rank=index,
        )
        if score > 0:
            candidates.append((score, str(compact_item.get("created_at") or ""), compact_item))
    if not candidates and fallback_items:
        for index, item in enumerate(fallback_items):
            if not isinstance(item, dict):
                continue
            compact_item = _compact_conversation_context_item(item)
            content = compact_item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            score = _conversation_context_score(
                compact_item,
                terms=terms,
                current_text=utterance,
                follow_up=follow_up,
                recency_rank=index,
            )
            if score > 0:
                candidates.append((score, str(compact_item.get("created_at") or ""), compact_item))
    candidates.sort(key=lambda row: (-row[0], row[1]))
    selected = [item for _, _, item in candidates[: max(1, limit)]]
    selected.sort(key=lambda item: str(item.get("created_at") or ""))
    return selected


def _compact_conversation_context_item(item: dict[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or "unknown")
    content_type = str(item.get("content_type") or "")
    content_text = item.get("content_text")
    content = item.get("content")
    text = ""
    if isinstance(content_text, str) and content_text.strip():
        text = content_text.strip()
    elif isinstance(content, str) and content.strip():
        text = content.strip()
    elif isinstance(content, dict):
        text = _extract_user_visible_text(content)
    if content_type == "execution_error":
        text = ""
    if content_type == "intent_analysis" and role == "assistant":
        text = ""
    return {
        "role": role,
        "content": text[:2000],
        "content_type": content_type,
        "created_at": item.get("created_at"),
        "trace_id": item.get("trace_id"),
    }


def _extract_user_visible_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result or "").strip()
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    capability_result = data.get("capability_result") if isinstance(data.get("capability_result"), dict) else {}
    user_result = capability_result.get("user_result") if isinstance(capability_result.get("user_result"), dict) else {}
    for value in (
        user_result.get("summary"),
        user_result.get("answer"),
        capability_result.get("summary_cn"),
        capability_result.get("summary"),
        capability_result.get("answer"),
        capability_result.get("user_answer"),
        data.get("summary_cn"),
        data.get("summary"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    content = capability_result.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return ""


def _is_follow_up_question(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    follow_up_markers = (
        "它", "这个", "这条", "该", "上述", "上面", "前面", "上一轮", "刚才",
        "那个", "这些", "那些", "属于哪个", "还有呢", "继续",
    )
    return any(marker in value for marker in follow_up_markers) and len(value) <= 80


def _context_terms(text: str) -> set[str]:
    value = text or ""
    terms: set[str] = set()
    for quoted in re.findall(r"《([^》]{2,80})》", value):
        terms.add(quoted.strip())
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,80}", value):
        terms.add(token.lower())
    important_terms = (
        "个人知识库", "知识库", "当前上传文件", "上传文件", "综合联调测试主数据",
        "项目编号", "项目名称", "项目", "区域", "地区", "产品名称", "产品",
        "需求数量", "需求", "最近一个月", "今年下半年", "下半年", "预测",
        "盈亏平衡", "预算风险", "预算", "风险", "桂中",
    )
    for term in important_terms:
        if term in value:
            terms.add(term)
    for chunk in re.split(r"[，。！？；：、\s\[\]\(\)（）{}<>《》\"'“”‘’]+", value):
        chunk = chunk.strip()
        if 2 <= len(chunk) <= 24:
            chunk = re.sub(r"^(请|帮我|告诉我|根据|基于|当前|本次|这个|那个|它|那|的|把)", "", chunk)
            chunk = re.sub(r"(是什么|有哪些|怎么|为什么|多少|一下|呢|吗|吧|呀)$", "", chunk)
            if 2 <= len(chunk) <= 24:
                terms.add(chunk)
    return {term for term in terms if term}


def _conversation_context_score(
    item: dict[str, Any],
    *,
    terms: set[str],
    current_text: str,
    follow_up: bool,
    recency_rank: int,
) -> int:
    text = str(item.get("content") or "")
    if not text:
        return 0
    role = str(item.get("role") or "")
    content_type = str(item.get("content_type") or "")
    if current_text and role == "user" and text.strip() == current_text.strip():
        return 0
    score = 0
    lowered = text.lower()
    asks_about_failure = any(marker in current_text for marker in ("为什么", "哪里", "报错", "失败", "不行", "不能", "问题"))
    negative_result_markers = (
        "未能查询到", "无法给出", "无法直接给出", "数据不足", "当前数据还不足",
        "没有返回", "模型网关", "请检查", "建议您补充", "查不到",
    )
    if content_type == "execution_result" and not asks_about_failure:
        if any(marker in text for marker in negative_result_markers):
            return 0
    for term in terms:
        if term and term.lower() in lowered:
            score += 12 if len(term) >= 4 else 6
    if role == "assistant" and content_type == "execution_result":
        score += 20
        if follow_up:
            score += 25
        score += max(0, 8 - recency_rank)
    if role == "user" and follow_up:
        score += 5 if score > 0 else 0
    if content_type in {"execution_error", "intent_analysis"}:
        score -= 50
    return score if score >= 12 else 0


def _evaluate_capacity(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id, owner, project_id, conversation_id = _identity(envelope, payload)
    if not project_id or not conversation_id:
        raise ContextError("CONVERSATION_CONTEXT_REQUIRED", "容量评估需要当前 Project 和普通对话框")
    ratio = payload.get("capacity_ratio")
    if ratio is None:
        messages = _query(envelope, "conversation_messages", {"conversation_id": conversation_id}, 500)
        used = sum(max(1, len(str(item.get("content_text") or item.get("text") or "")) // 4) for item in messages)
        limit = max(int(payload.get("capacity_limit") or 8000), 1)
        ratio = min(used / limit, 1.0)
    try:
        ratio = max(0.0, float(ratio))
    except (TypeError, ValueError) as exc:
        raise ContextError("CAPACITY_RATIO_INVALID", "容量占用必须是数字") from exc
    state = "normal" if ratio < WARNING_RATIO else "warning" if ratio < HANDOFF_RATIO else "handoff_required"
    event = {
        "event_id": f"ctx-cap-{uuid4().hex[:16]}", "record_id": f"ctx-cap-{uuid4().hex[:16]}",
        "tenant_id": tenant_id, "owner_account_id": owner, "project_id": project_id, "conversation_id": conversation_id,
        "state": state, "capacity_ratio": ratio, "threshold_warning": WARNING_RATIO, "threshold_handoff": HANDOFF_RATIO,
        "created_at": _now(), "storage_class": "temporary", "retention_policy": "session-lifecycle",
    }
    _write(envelope, "context_capacity_events", event)
    return {"conversation_id": conversation_id, "capacity_ratio": ratio, "state": state, "next_action": "generate_handoff" if state == "handoff_required" else "warn" if state == "warning" else "continue"}


def _generate_handoff(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id, owner, project_id, conversation_id = _identity(envelope, payload)
    if not project_id or not conversation_id:
        raise ContextError("CONVERSATION_CONTEXT_REQUIRED", "生成三件套需要当前 Project 和普通对话框")
    messages = _query(envelope, "conversation_messages", {"conversation_id": conversation_id}, 500)
    old_packages = _query(envelope, "context_inheritance_packages", {"project_id": project_id, "owner_account_id": owner}, 10)
    source = {"project_id": project_id, "conversation_id": conversation_id, "messages": messages[-120:], "previous_package": old_packages[0] if old_packages else None}
    report = _generate_artifact(envelope, "work_report", source)
    handoff = _generate_artifact(envelope, "handoff_file", source)
    package = _generate_artifact(envelope, "inheritance_package", {**source, "work_report": report, "handoff_file": handoff})
    version = max([int(item.get("version_no") or 0) for item in old_packages] or [0]) + 1
    bundle_id = f"handoff-bundle-{uuid4().hex[:16]}"
    records = [
        ("context_work_reports", {"report_id": f"report-{uuid4().hex[:16]}", "content": report, "title": "工作汇报", "source_record_type": "work_report"}),
        ("context_handoff_files", {"handoff_id": f"handoff-{uuid4().hex[:16]}", "content": handoff, "title": "工作交接文件", "source_record_type": "handoff_file"}),
        ("context_inheritance_packages", {"package_id": f"package-{uuid4().hex[:16]}", "content": package, "title": f"继承包 v{version}", "version_no": version, "source_record_type": "inheritance_package"}),
    ]
    generated = []
    for dataset, item in records:
        item.update({
            "record_id": item.get("report_id") or item.get("handoff_id") or item.get("package_id"),
            "tenant_id": tenant_id,
            "owner_account_id": owner,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "source_conversation_id": conversation_id,
            "handoff_version": version,
            "bundle_id": bundle_id,
            "artifact_type": item["source_record_type"],
            "state": "active",
            "deleted": False,
            "created_at": _now(),
            "storage_class": "fixed",
            "retention_policy": "context-handoff-history",
        })
        _write(envelope, dataset, item)
        generated.append({
            "type": item["source_record_type"],
            "artifact_type": item["artifact_type"],
            "record_id": item["record_id"],
            "title": item["title"],
            "content": item["content"],
            "project_id": project_id,
            "conversation_id": conversation_id,
            "handoff_version": version,
            "bundle_id": bundle_id,
        })
    return {
        "conversation_id": conversation_id,
        "project_id": project_id,
        "handoff_version": version,
        "bundle_id": bundle_id,
        "generated_files": generated,
        "next_action": "create_or_switch_next_session",
    }


def _generate_artifact(envelope: dict[str, Any], kind: str, source: dict[str, Any]) -> str:
    instructions = {
        "work_report": "生成工作汇报。只保留已完成事项、关键结论、产出、风险和建议写入传承包事项。返回 JSON: {content:string}。",
        "handoff_file": "生成工作交接文件。只保留未完成事项、下一步、必读文件、风险和必要背景。返回 JSON: {content:string}。",
        "inheritance_package": "升级 Project 传承包。合并旧传承包和本轮工作汇报，保留项目主线、关键结论、文件索引、待办和风险。返回 JSON: {content:string}。",
    }
    request = {"task_type": "context_handoff_generation", "messages": [{"role": "system", "content": instructions[kind]}, {"role": "user", "content": json.dumps(source, ensure_ascii=False)}], "model_policy": {"temperature": 0.1, "max_output_tokens": 2500, "allow_fallback": False}}
    data = _foundation(envelope, "model.respond", request)
    if str(data.get("provider") or "") == "local-mock":
        raise ContextError("MODEL_UNAVAILABLE_FOR_CONTEXT_HANDOFF", "模型未就绪，不能生成可信的收口材料", status=503, retryable=True)
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    content = str(output.get("content") or "").strip()
    if not content:
        raise ContextError("CONTEXT_ARTIFACT_GENERATION_FAILED", "模型没有返回有效的收口材料", status=502, retryable=True)
    return content


def _import_material(envelope: dict[str, Any], payload: dict[str, Any], *, cross_project: bool) -> dict[str, Any]:
    tenant_id, owner, project_id, _ = _identity(envelope, payload)
    target_conversation_id = str(payload.get("target_conversation_id") or "")
    source_record_id = str(payload.get("source_record_id") or "")
    source_record_type = str(payload.get("source_record_type") or "")
    source_project_id = str(payload.get("source_project_id") or project_id)
    if not project_id or not target_conversation_id or not source_record_id or not source_record_type:
        raise ContextError("CONTEXT_IMPORT_FIELDS_REQUIRED", "导入需要目标对话、来源记录和来源类型")
    if not cross_project and source_project_id != project_id:
        raise ContextError("CROSS_PROJECT_IMPORT_REQUIRES_REFERENCE", "跨 Project 材料必须先在总指挥中心确认引用", status=403)
    dataset = "context_cross_project_references" if cross_project else "context_imports"
    record_id = f"ctx-import-{uuid4().hex[:16]}"
    record = {"record_id": record_id, "import_id": record_id, "reference_id": record_id, "tenant_id": tenant_id, "owner_account_id": owner, "project_id": project_id, "target_project_id": project_id, "target_conversation_id": target_conversation_id, "source_project_id": source_project_id, "source_record_id": source_record_id, "source_record_type": source_record_type, "title": str(payload.get("title") or source_record_type), "content": str(payload.get("content") or ""), "imported_at": _now(), "storage_class": "fixed", "retention_policy": "context-import-history"}
    _write(envelope, dataset, record)
    if cross_project:
        _write(envelope, "context_imports", record)
    return {"import_id": record_id, "target_conversation_id": target_conversation_id, "source_record_id": source_record_id, "state": "imported"}


def _search(envelope: dict[str, Any], payload: dict[str, Any], *, account_scope: bool) -> dict[str, Any]:
    _, owner, project_id, _ = _identity(envelope, payload)
    visible = payload.get("visible_project_ids") if isinstance(payload.get("visible_project_ids"), list) else [project_id]
    allowed_projects = {str(item) for item in visible if str(item)} if account_scope else {project_id}
    datasets = ("conversation_messages", "context_work_reports", "context_handoff_files", "context_inheritance_packages")
    query = str(payload.get("query") or "").strip().lower()
    matches: list[dict[str, Any]] = []
    for dataset in datasets:
        for item in _query(envelope, dataset, {"owner_account_id": owner}, 500):
            if str(item.get("project_id") or "") not in allowed_projects:
                continue
            text = " ".join(str(item.get(key) or "") for key in ("title", "content", "content_text", "text"))
            if query and query not in text.lower():
                continue
            record_id = str(item.get("record_id") or item.get("message_id") or "")
            matches.append({"dataset": dataset, "record_id": record_id, "project_id": item.get("project_id"), "conversation_id": item.get("conversation_id"), "message_id": item.get("message_id"), "title": item.get("title") or item.get("original_name") or dataset, "snippet": text[:240], "jump_target": {"project_id": item.get("project_id"), "conversation_id": item.get("conversation_id"), "message_id": item.get("message_id")}})
    return {"scope": "account" if account_scope else "project", "matches": matches[:50], "count": min(len(matches), 50)}


def _control_center_query(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    _, owner, project_id, conversation_id = _identity(envelope, payload)
    scope = str(payload.get("scope") or "conversation")
    if scope not in {"conversation", "project", "account"}:
        raise ContextError("CONTEXT_SCOPE_INVALID", "上下文指挥中心范围无效")
    if scope == "conversation" and not conversation_id:
        raise ContextError("CONVERSATION_CONTEXT_REQUIRED", "对话指挥中心需要当前 conversation")
    if scope in {"conversation", "project"} and not project_id:
        raise ContextError("PROJECT_CONTEXT_REQUIRED", "Project 指挥中心需要当前 Project")

    filters = {"owner_account_id": owner}
    if scope in {"conversation", "project"}:
        filters["project_id"] = project_id
    if scope == "conversation":
        filters["conversation_id"] = conversation_id

    records: list[dict[str, Any]] = []
    for dataset in ("context_work_reports", "context_handoff_files", "context_inheritance_packages"):
        records.extend(_query(envelope, dataset, filters, 500))

    bundles: dict[str, dict[str, Any]] = {}
    for item in records:
        if str(item.get("state") or "active") == "deleted" or item.get("deleted") is True:
            continue
        bundle_id = str(item.get("bundle_id") or f"legacy-{item.get('record_id')}")
        bundle = bundles.setdefault(bundle_id, {
            "bundle_id": bundle_id,
            "project_id": item.get("project_id"),
            "conversation_id": item.get("conversation_id"),
            "handoff_version": int(item.get("handoff_version") or item.get("version_no") or 1),
            "created_at": item.get("created_at"),
            "artifacts": [],
        })
        bundle["handoff_version"] = max(bundle["handoff_version"], int(item.get("handoff_version") or item.get("version_no") or 1))
        bundle["created_at"] = max(str(bundle.get("created_at") or ""), str(item.get("created_at") or ""))
        bundle["artifacts"].append({
            "artifact_type": item.get("artifact_type") or item.get("source_record_type"),
            "record_id": item.get("record_id"),
            "title": item.get("title"),
            "content": item.get("content") or "",
            "state": item.get("state") or "active",
        })

    packages = sorted(
        bundles.values(),
        key=lambda item: (str(item.get("project_id") or ""), str(item.get("created_at") or "")),
        reverse=True,
    )
    return {"scope": scope, "owner_account_id": owner, "packages": packages[:100], "count": min(len(packages), 100)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
