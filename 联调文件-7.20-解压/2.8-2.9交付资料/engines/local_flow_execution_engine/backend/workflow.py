from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .clients import DependencyCallError, get_json, post_json
from .config import ROOT, read_env
from .models import FlowCallbackRequest, FlowStartRequest, HumanDecisionRequest
from .store import JsonStore


STATE_PATH = ROOT / "data" / "flow_instances.json"
store = JsonStore(STATE_PATH)

REAL_PERSON_IDS = {
    "U001": "RP-0001",
    "U002": "RP-0002",
    "U003": "RP-0003",
    "U004": "RP-0004",
    "U005": "RP-0005",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _dump_model(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _event(step: str, status: str, detail: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"time": now_iso(), "step": step, "status": status, "detail": detail, "data": data or {}}


def _node(node_id: str, name: str, target_service: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "name": name,
        "target_service": target_service,
        "action": action,
        "status": "pending",
        "payload": payload,
        "result": None,
        "started_at": "",
        "completed_at": "",
    }


def health() -> dict[str, Any]:
    cfg = read_env()
    media_health = None
    content_health = None
    try:
        media_health = get_json(cfg["MEDIA_BASE"].rstrip("/") + "/api/health", timeout=2)
        media_ok = bool(media_health.get("ok"))
    except Exception as exc:
        media_ok = False
        media_health = {"error": str(exc)}
    try:
        content_health = get_json(cfg["CONTENT_BASE"].rstrip("/") + "/api/health", timeout=2)
        content_ok = bool(content_health.get("ok"))
    except Exception as exc:
        content_ok = False
        content_health = {"error": str(exc)}
    return {
        "ok": True,
        "module": "本地简化流程执行引擎",
        "version": "0.1.0",
        "media_base": cfg["MEDIA_BASE"],
        "content_base": cfg["CONTENT_BASE"],
        "media_connected": media_ok,
        "content_connected": content_ok,
        "media_health": media_health,
        "content_health": content_health,
        "truth_note": "本地版实现面向内容产出/多媒体联调的流程登记、子任务派发、结果接收和人工确认模拟。",
    }


def capabilities() -> dict[str, Any]:
    return {
        "service_code": "l2.workflow_execution.local_minimal",
        "actions": [
            "flow.start",
            "flow.get",
            "flow.list",
            "flow.decide_human",
            "flow.callback",
            "flow.reset",
        ],
        "supported_workflows": [
            {"workflow_type": "media_only", "description": "直接派发多媒体生成引擎 v1.1。"},
            {"workflow_type": "content_then_media", "description": "先派发内容产出生成文字初稿，再派发多媒体生成画面方案。"},
            {"workflow_type": "hot_case_batch", "description": "批量派发爆款案例复用任务：每个批次先内容产出，再多媒体生成方案。"},
            {"workflow_type": "hot_case_sample_then_batch", "description": "先派发爆款打样并等待真人确认，通过后再按同一模式批量生成。"},
            {"workflow_type": "expert_agent_plan", "description": "从共享池取专家分身，再派发内容产出生成专家方案。"},
            {"workflow_type": "skill_promotion_authorization", "description": "技能效果核对、关键授权确认、开放范围更新与推广记录接口位。"},
        ],
        "external_interface_slots": _case_one_external_interface_slots(),
        "ports": {"default": 8020, "content_default": 8011, "multimedia_default": 8013},
    }


def list_instances() -> dict[str, Any]:
    data = store.read()
    items = sorted(data.values(), key=lambda item: item.get("created_at", ""), reverse=True)
    return {"count": len(items), "items": items}


def get_instance(instance_id: str) -> dict[str, Any]:
    data = store.read()
    if instance_id not in data:
        raise KeyError("instance_not_found")
    return data[instance_id]


def reset_instances() -> dict[str, Any]:
    store.write({})
    return {"ok": True, "message": "本地流程实例已清空。"}


def _case_one_external_interface_slots() -> list[dict[str, Any]]:
    return [
        {
            "slot_id": "intent_analyze",
            "target_service": "l2.intent_analysis_engine",
            "expected_path": "POST /api/intent/analyze",
            "purpose": "把自然语言拆成能力编号与参数；本地未实现。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "capability_registry_resolve",
            "target_service": "platform.capability_registry",
            "expected_path": "POST /api/capability-registry/resolve",
            "purpose": "按能力编号确定承办引擎与顺序；本地仍用固定流程替代。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "expert_agent_resolve",
            "target_service": "l2.digital_asset_engine",
            "expected_path": "POST /api/digital-assets/expert-agents/resolve",
            "purpose": "从共享池取用专家分身，不新建不修改。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "skill_detail_get",
            "target_service": "l2.digital_asset_engine",
            "expected_path": "GET /api/digital-assets/skills/{skill_id}",
            "purpose": "读取专家分身装配的技能详情、版本、开放范围。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "rule_calculate",
            "target_service": "l1.rule_calculation_engine",
            "expected_path": "POST /api/rules/calculate",
            "purpose": "确定性计算施肥用量、采纳率等数字，不交给大模型估算。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "data_operation_document_export",
            "target_service": "l1.data_operation_engine",
            "expected_path": "POST /api/data/documents/export",
            "purpose": "生成可下载正式文档；存档是另一次确认后的数据写入动作。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "usage_stats_read",
            "target_service": "l1.data_operation_engine",
            "expected_path": "POST /api/data/statistics/read",
            "purpose": "读取调用次数、采纳数量等硬数据。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "permission_share_scope_update",
            "target_service": "l1.permission_management",
            "expected_path": "POST /api/permissions/share-scope/update",
            "purpose": "判断推广官权限并修改技能开放范围，留痕可回退。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "monitor_recommendation_notify",
            "target_service": "l2.monitoring_alert_engine",
            "expected_path": "POST /api/monitoring/recommendations/notify",
            "purpose": "把待推广推荐异步推给大区经理。",
            "status": "reserved_interface",
        },
        {
            "slot_id": "app_information_dispatch",
            "target_service": "business_application_layer",
            "expected_path": "POST /api/app/messages/dispatch",
            "purpose": "把右栏信息、确认卡片、结果路由到指定人的屏幕。",
            "status": "reserved_interface",
        },
    ]


def start_flow(req: FlowStartRequest) -> dict[str, Any]:
    payload = _dump_model(req)
    cfg = read_env()
    instance_id = "FLOW-" + uuid4().hex[:8].upper()
    trace_id = "TRACE-" + uuid4().hex[:10].upper()
    media_payload = {
        "message_id": "MSG-" + uuid4().hex[:8].upper(),
        "workflow_instance_id": instance_id,
        "node_id": "media_generate",
        "task_id": "TASK-MEDIA-" + uuid4().hex[:6].upper(),
        "idempotency_key": f"{instance_id}-media_generate-v1",
        "caller": {"service_code": "l2.workflow_execution.local_minimal", "service_name": "本地简化流程执行引擎"},
        "actor": {"actor_id": req.actor_id, "real_person_id": REAL_PERSON_IDS.get(req.actor_id, "RP-0001")},
        "capability": {"capability_id": req.capability_id, "capability_version": "0.9.0", "schema_version": "0.1.0"},
        "request_type": "execute",
        "input": {
            "requirement": req.requirement,
            "task_type": req.task_type,
            "capability_id": req.capability_id,
            "output_type": req.output_type,
            "model_dispatch_interface_slot": _model_dispatch_interface_slot(),
        },
        "expected_return": {"return_mode": "accepted_then_callback", "output_type": req.output_type},
        "policy": {"review_policy": req.review_policy, "allow_mock": True, "timeout_seconds": int(cfg.get("REQUEST_TIMEOUT_SECONDS") or "90")},
        "actor_id": req.actor_id,
        "task_type": req.task_type,
        "capability_id": req.capability_id,
        "output_type": req.output_type,
        "requirement": req.requirement,
        "top_k": req.top_k,
        "use_llm": req.use_llm,
        "source_engine": "local_workflow_engine",
        "source_engine_name": "本地简化流程执行引擎",
        "parent_flow_id": instance_id,
        "trace_id": trace_id,
        "model_dispatch_interface_slot": _model_dispatch_interface_slot(),
    }
    nodes = []
    if req.workflow_type == "hot_case_batch":
        batch_count = max(1, min(req.batch_count, 5))
        nodes.extend(_build_hot_case_batch_nodes(req, instance_id, trace_id, media_payload, batch_count, stage="batch"))
    elif req.workflow_type == "hot_case_sample_then_batch":
        nodes.extend(_build_hot_case_sample_nodes(req, instance_id, trace_id, media_payload))
    elif req.workflow_type == "expert_agent_plan":
        nodes.extend(_build_expert_agent_plan_nodes(req, instance_id, trace_id))
    elif req.workflow_type == "skill_promotion_authorization":
        nodes.extend(_build_skill_promotion_nodes(req, instance_id, trace_id))
    else:
        if req.workflow_type == "content_then_media":
            nodes.append(
                _node(
                    "content_prepare",
                    "内容产出文字节点",
                    "l2.content_generation",
                    "content.generate",
                    _build_content_payload(req, instance_id, trace_id),
                )
            )
        nodes.append(
            _node("media_generate", "多媒体生成方案节点", "l2.multimedia_generation", "media.generate", media_payload)
        )
    instance = {
        "instance_id": instance_id,
        "trace_id": trace_id,
        "source_module": req.source_module,
        "actor_id": req.actor_id,
        "workflow_type": req.workflow_type,
        "status": "accepted",
        "exit_type": "accepted",
        "request": payload,
        "nodes": nodes,
        "human_tasks": [],
        "artifacts": {
            "base_media_payload": media_payload,
            "digital_asset_interface_slot": _digital_asset_interface_slot(req)
            if req.workflow_type in {"hot_case_batch", "hot_case_sample_then_batch"}
            else {},
            "case_one_interface_slots": _case_one_external_interface_slots()
            if req.workflow_type in {"expert_agent_plan", "skill_promotion_authorization"}
            else [],
        },
        "events": [_event("flow.start", "ok", "流程实例已创建，准备派发承办节点。")],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "truth_note": "流程状态、节点派发和人工确认为本地真实逻辑；内容产出节点调用 v0.2 真实接口；多媒体节点调用 v1.1 真实接口；权限、安全与工作台待办仍为本地模拟。",
    }
    _save_instance(instance)
    return _run_instance(instance, cfg)


def _build_hot_case_sample_nodes(
    req: FlowStartRequest,
    instance_id: str,
    trace_id: str,
    media_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    return _build_hot_case_pair_nodes(
        req,
        instance_id,
        trace_id,
        media_payload,
        content_node_id="hot_content_sample",
        media_node_id="hot_media_sample",
        index=0,
        batch_count=req.batch_count,
        stage="sample",
    )


def _build_expert_agent_plan_nodes(req: FlowStartRequest, instance_id: str, trace_id: str) -> list[dict[str, Any]]:
    return [
        _node(
            "expert_agent_resolve",
            "数字资产取专家分身",
            "l2.digital_asset_engine",
            "digital_asset.expert_agent.resolve",
            _expert_agent_resolve_payload(req, instance_id, trace_id),
        ),
        _node(
            "content_expert_plan",
            "内容产出专家方案",
            "l2.content_generation",
            "content.generate",
            _build_expert_content_payload(req, instance_id, trace_id),
        ),
    ]


def _build_skill_promotion_nodes(req: FlowStartRequest, instance_id: str, trace_id: str) -> list[dict[str, Any]]:
    return [
        _node("skill_usage_stats", "读取技能调用统计", "l1.data_operation_engine", "data.statistics.read", _placeholder_payload(req, instance_id, trace_id, "usage_stats_read")),
        _node("skill_adoption_rate", "规则计算采纳率", "l1.rule_calculation_engine", "rule.calculate", _placeholder_payload(req, instance_id, trace_id, "rule_calculate")),
        _node("promotion_confirm_card", "关键授权确认卡", "business_application_layer", "app.confirmation_card.create", _placeholder_payload(req, instance_id, trace_id, "app_information_dispatch")),
        _node("permission_share_update", "权限开放范围更新", "l1.permission_management", "permission.share_scope.update", _placeholder_payload(req, instance_id, trace_id, "permission_share_scope_update")),
        _node("digital_asset_registry_update", "数字资产登记更新", "l2.digital_asset_engine", "digital_asset.skill_registry.update", _placeholder_payload(req, instance_id, trace_id, "skill_detail_get")),
        _node("promotion_record_dispatch", "推广结果分发", "business_application_layer", "app.messages.dispatch", _placeholder_payload(req, instance_id, trace_id, "app_information_dispatch")),
    ]


def _expert_agent_resolve_payload(req: FlowStartRequest, instance_id: str, trace_id: str) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "workflow_instance_id": instance_id,
        "actor": {"actor_id": req.actor_id, "real_person_id": REAL_PERSON_IDS.get(req.actor_id, "RP-0001")},
        "expert_agent_ref": req.expert_agent_ref,
        "shared_pool": "group_shared_pool",
        "required_action": "expert_agents.resolve",
        "expected_path": "POST /api/digital-assets/expert-agents/resolve",
        "status": "reserved_interface",
        "permission_check": {
            "target_service": "l1.permission_management",
            "expected_path": "POST /api/permissions/check",
            "action": "use_shared_expert_agent",
        },
        "note": "本地未实现数字资产引擎；该节点模拟从共享池取用作物营养专家分身。",
    }


def _case_one_skill_refs(req: FlowStartRequest) -> list[str]:
    hot_case_default = ["SKILL-HOT-CASE-PATTERN-001", "SKILL-HOT-CASE-STANDARD-001"]
    if req.skill_refs and req.skill_refs != hot_case_default:
        return req.skill_refs
    return ["SKILL-CROP-NUTRITION-STANDARD-001", "SKILL-SUGARCANE-FERTILIZATION-001"]


def _build_expert_content_payload(req: FlowStartRequest, instance_id: str, trace_id: str) -> dict[str, Any]:
    skill_refs = _case_one_skill_refs(req)
    return {
        "trace_id": trace_id,
        "message_id": "MSG-" + uuid4().hex[:8].upper(),
        "workflow_instance_id": instance_id,
        "node_id": "content_expert_plan",
        "task_id": "TASK-CONTENT-" + uuid4().hex[:6].upper(),
        "idempotency_key": f"{instance_id}-content_expert_plan-v1",
        "caller": {"service_code": "l2.workflow_execution.local_minimal", "service_name": "本地简化流程执行引擎"},
        "actor": {"actor_id": req.actor_id, "real_person_id": REAL_PERSON_IDS.get(req.actor_id, "RP-0001")},
        "capability": {"capability_id": "content_agronomy_fertilization_plan", "capability_version": "0.1.0", "schema_version": "0.1.0"},
        "request_type": "execute",
        "input": {
            "requirement": req.requirement,
            "content_type": "expert_plan",
            "template_id": "TPL-EXPERT-PLAN",
            "expert_agent_ref": req.expert_agent_ref,
            "skill_refs": skill_refs,
            "project_id": req.project_id,
            "rule_calculation_interface_slot": _rule_calculation_interface_slot(),
            "context_prompt_interface_slot": _context_prompt_interface_slot(),
            "model_dispatch_interface_slot": _model_dispatch_interface_slot(),
            "data_operation_interface_slot": _data_operation_interface_slot(),
        },
        "expected_return": {"return_mode": "accepted_then_callback", "output_type": "downloadable_document"},
        "policy": {"review_policy": "direct_delivery_draft", "allow_mock": True},
        "operator_real_person_id": REAL_PERSON_IDS.get(req.actor_id, "RP-0001"),
        "requested_service": "基于共享池专家分身生成施肥方案",
        "content_type": "expert_plan",
        "input_brief": req.requirement,
        "source_material_refs": [req.expert_agent_ref, *skill_refs],
        "template_id": "TPL-EXPERT-PLAN",
        "expected_output": "可下载的专家方案文档，含阶段、配方、用量、注意事项和计算说明",
        "review_policy": "direct_delivery_draft",
        "scenario_id": "REQ-EXPERT-PLAN",
    }


def _placeholder_payload(req: FlowStartRequest, instance_id: str, trace_id: str, slot_id: str) -> dict[str, Any]:
    slot = next((item for item in _case_one_external_interface_slots() if item["slot_id"] == slot_id), {})
    return {
        "trace_id": trace_id,
        "workflow_instance_id": instance_id,
        "actor": {"actor_id": req.actor_id, "real_person_id": REAL_PERSON_IDS.get(req.actor_id, "RP-0001")},
        "project_id": req.project_id,
        "expert_agent_ref": req.expert_agent_ref,
        "skill_refs": _case_one_skill_refs(req),
        "share_scope": req.share_scope,
        "interface_slot": slot,
        "status": "reserved_interface",
    }


def _rule_calculation_interface_slot() -> dict[str, str]:
    return {"target_service": "l1.rule_calculation_engine", "expected_path": "POST /api/rules/calculate", "status": "reserved_interface"}


def _context_prompt_interface_slot() -> dict[str, str]:
    return {"target_service": "l1.context_prompt_management", "expected_path": "POST /api/context-prompts/resolve", "status": "reserved_interface"}


def _model_dispatch_interface_slot() -> dict[str, str]:
    return {"target_service": "l1.model_dispatch", "expected_path": "POST /api/model-dispatch/tasks", "status": "reserved_interface"}


def _data_operation_interface_slot() -> dict[str, str]:
    return {"target_service": "l1.data_operation_engine", "expected_path": "POST /api/data/documents/export", "status": "reserved_interface"}


def _build_hot_case_batch_nodes(
    req: FlowStartRequest,
    instance_id: str,
    trace_id: str,
    media_payload: dict[str, Any],
    batch_count: int,
    stage: str = "batch",
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for index in range(1, batch_count + 1):
        content_node_id = f"hot_content_{index:02d}" if stage == "batch" else f"hot_content_after_sample_{index:02d}"
        media_node_id = f"hot_media_{index:02d}" if stage == "batch" else f"hot_media_after_sample_{index:02d}"
        nodes.extend(
            _build_hot_case_pair_nodes(
                req,
                instance_id,
                trace_id,
                media_payload,
                content_node_id=content_node_id,
                media_node_id=media_node_id,
                index=index,
                batch_count=batch_count,
                stage=stage,
            )
        )
    return nodes


def _build_hot_case_pair_nodes(
    req: FlowStartRequest,
    instance_id: str,
    trace_id: str,
    media_payload: dict[str, Any],
    content_node_id: str,
    media_node_id: str,
    index: int,
    batch_count: int,
    stage: str,
) -> list[dict[str, Any]]:
    if stage == "sample":
        variant_note = "爆款复用打样：先验证爆款模式、制作标准、素材取用和多媒体方案，等待真人确认后再批量生成。"
        content_name = "爆款打样文案节点"
        media_name = "爆款打样多媒体节点"
        batch_index = 0
        reuse_mode = "hot_case_sample"
    else:
        variant_note = f"爆款复用批量生成第 {index} 版：基于已确认打样模式，输出差异化标题、卖点、视觉方案和提示词。"
        content_name = f"爆款复用文案节点 {index}"
        media_name = f"爆款多媒体方案节点 {index}"
        batch_index = index
        reuse_mode = "hot_case_batch"

    content_payload = _build_content_payload(
        req,
        instance_id,
        trace_id,
        node_id=content_node_id,
        hot_case=True,
        batch_index=batch_index,
        hot_case_stage=stage,
    )
    hot_media_payload = {
        **media_payload,
        "message_id": "MSG-" + uuid4().hex[:8].upper(),
        "node_id": media_node_id,
        "task_id": "TASK-MEDIA-" + uuid4().hex[:6].upper(),
        "idempotency_key": f"{instance_id}-{media_node_id}-v1",
        "task_type": "hot_case_reuse",
        "output_type": req.output_type,
        "requirement": f"{req.requirement}\n\n【爆款流程要求】{variant_note}",
        "batch_index": batch_index,
        "batch_count": batch_count,
        "hot_case_refs": req.hot_case_refs,
        "skill_refs": req.skill_refs,
        "skill_requirements": _hot_case_skill_requirements(req),
        "digital_asset_interface_slot": _digital_asset_interface_slot(req),
        "upstream_content_node_id": content_node_id,
    }
    hot_media_payload["input"] = {
        **media_payload["input"],
        "requirement": hot_media_payload["requirement"],
        "task_type": "hot_case_reuse",
        "output_type": req.output_type,
        "batch_index": batch_index,
        "batch_count": batch_count,
        "hot_case_refs": req.hot_case_refs,
        "reuse_mode": reuse_mode,
        "hot_case_stage": stage,
        "skill_refs": req.skill_refs,
        "skill_requirements": _hot_case_skill_requirements(req),
        "digital_asset_interface_slot": _digital_asset_interface_slot(req),
    }
    hot_media_payload["expected_return"] = {
        **media_payload["expected_return"],
        "output_type": req.output_type,
        "batch_index": batch_index,
    }
    return [
        _node(content_node_id, content_name, "l2.content_generation", "content.generate", content_payload),
        _node(media_node_id, media_name, "l2.multimedia_generation", "media.generate", hot_media_payload),
    ]


def _hot_case_skill_requirements(req: FlowStartRequest) -> list[dict[str, Any]]:
    return [
        {
            "skill_type": "hot_case_pattern",
            "skill_ref": req.skill_refs[0] if req.skill_refs else "SKILL-HOT-CASE-PATTERN-001",
            "required_from": "l2.digital_asset_engine",
            "purpose": "取用爆款模式：版式节奏、标题结构、卖点组织方式。",
        },
        {
            "skill_type": "production_standard",
            "skill_ref": req.skill_refs[1] if len(req.skill_refs) > 1 else "SKILL-HOT-CASE-STANDARD-001",
            "required_from": "l2.digital_asset_engine",
            "purpose": "取用制作标准：尺寸、清晰度、标识、合规核查和真人确认要求。",
        },
    ]


def _digital_asset_interface_slot(req: FlowStartRequest) -> dict[str, Any]:
    return {
        "target_service": "l2.digital_asset_engine",
        "target_engine": "数字资产引擎",
        "required_action": "skills.resolve",
        "expected_path": "POST /api/digital-assets/skills/resolve",
        "status": "reserved_interface",
        "skill_refs": req.skill_refs,
        "note": "本地暂未实现数字资产引擎；当前只把爆款模式和制作标准技能作为接口位传给多媒体生成引擎。",
    }


def decide_human(req: HumanDecisionRequest) -> dict[str, Any]:
    data = store.read()
    if req.instance_id not in data:
        raise KeyError("instance_not_found")
    instance = data[req.instance_id]
    pending = None
    for task in instance.get("human_tasks", []):
        if task.get("task_id") == req.task_id:
            pending = task
            break
    if not pending:
        raise KeyError("human_task_not_found")
    if pending.get("status") != "pending":
        raise ValueError("human_task_already_decided")
    if req.decision not in {"approved", "rejected"}:
        raise ValueError("decision_must_be_approved_or_rejected")
    pending["status"] = "done"
    pending["decision"] = req.decision
    pending["comment"] = req.comment
    pending["decided_by"] = req.decided_by
    pending["decided_at"] = now_iso()
    if req.decision == "approved":
        if pending.get("after_approval") == "dispatch_hot_case_batch":
            instance.setdefault("artifacts", {})["hot_case_sample_approved"] = True
            instance["events"].append(
                _event(
                    "flow.decide_human",
                    "ok",
                    "爆款打样已确认，通过后开始按同一模式批量派发。",
                    {"task_id": req.task_id},
                )
            )
            req_model = FlowStartRequest(**instance["request"])
            batch_count = max(1, min(req_model.batch_count, 5))
            base_media_payload = instance.get("artifacts", {}).get("base_media_payload")
            if not base_media_payload:
                sample_media = next((node for node in instance.get("nodes", []) if node.get("node_id") == "hot_media_sample"), None)
                base_media_payload = (sample_media or {}).get("payload") or {}
            instance["nodes"].extend(
                _build_hot_case_batch_nodes(
                    req_model,
                    instance["instance_id"],
                    instance["trace_id"],
                    base_media_payload,
                    batch_count,
                    stage="after_sample_batch",
                )
            )
            instance["status"] = "running"
            instance["exit_type"] = "running_after_sample_approval"
            instance["updated_at"] = now_iso()
            data[req.instance_id] = instance
            store.write(data)
            return _run_instance(instance, read_env())
        instance["status"] = "completed"
        instance["exit_type"] = "direct_delivery_after_human_approval"
        instance["events"].append(_event("flow.decide_human", "ok", "真人确认通过，流程完成。", {"task_id": req.task_id}))
    else:
        instance["status"] = "failed"
        instance["exit_type"] = "rejected_by_human"
        instance["events"].append(_event("flow.decide_human", "failed", "真人驳回，流程结束。", {"task_id": req.task_id}))
    instance["updated_at"] = now_iso()
    data[req.instance_id] = instance
    store.write(data)
    return instance


def apply_flow_callback(req: FlowCallbackRequest) -> dict[str, Any]:
    payload = _dump_model(req)
    data = store.read()
    instance_id = req.workflow_instance_id
    instance = data.get(instance_id or "")
    if instance is None and req.trace_id:
        for item in data.values():
            if item.get("trace_id") == req.trace_id:
                instance = item
                instance_id = item.get("instance_id")
                break
    if instance is None or not instance_id:
        raise KeyError("workflow_instance_not_found")

    matched_node = None
    for node in instance.get("nodes", []):
        result_task_id = (node.get("result") or {}).get("task_id")
        if node.get("node_id") == req.node_id or result_task_id == req.task_id:
            matched_node = node
            break

    callback_status = _map_callback_status(req.status)
    if matched_node is not None:
        matched_node["status"] = callback_status
        matched_node["callback"] = payload
        matched_node["completed_at"] = req.completed_at or now_iso()
        if req.result:
            matched_node["result"] = req.result

    callbacks = instance.setdefault("artifacts", {}).setdefault("callbacks", [])
    callbacks.append(payload)
    instance["events"].append(
        _event(
            "flow.callback",
            "ok" if callback_status == "completed" else callback_status,
            "已接收承办引擎回调。",
            {"task_id": req.task_id, "node_id": req.node_id, "source_service": req.source_service},
        )
    )
    instance["updated_at"] = now_iso()
    data[instance_id] = instance
    store.write(data)
    return {"ok": True, "instance": instance}


def _map_callback_status(status: str) -> str:
    if status in {"completed", "success"}:
        return "completed"
    if status in {"failed", "error", "llm_failed", "unable_to_handle"}:
        return "failed"
    if status in {"accepted", "running", "waiting_human_confirmation"}:
        return status
    return "running"


def _run_instance(instance: dict[str, Any], cfg: dict[str, str]) -> dict[str, Any]:
    instance["status"] = "running"
    instance["exit_type"] = "running"
    instance["events"].append(_event("flow.dispatch", "ok", "流程执行引擎开始按节点派发。"))
    for node in instance["nodes"]:
        if node.get("status") == "completed":
            continue
        if node["action"] in {
            "digital_asset.expert_agent.resolve",
            "data.statistics.read",
            "rule.calculate",
            "app.confirmation_card.create",
            "permission.share_scope.update",
            "digital_asset.skill_registry.update",
            "app.messages.dispatch",
        }:
            _complete_placeholder_node(instance, node)
            continue
        if node["node_id"] in {"content_prepare", "content_expert_plan"} or node["node_id"].startswith("hot_content_"):
            _dispatch_content_node(instance, node, cfg)
            if node["status"] != "completed":
                instance["status"] = "failed"
                instance["exit_type"] = "failed_dependency"
                instance["events"].append(_event("flow.end", "failed", "内容产出承办节点未完成，流程无法继续派发多媒体。"))
                instance["updated_at"] = now_iso()
                _save_instance(instance)
                return instance
            continue
        if node["node_id"] == "media_generate" or node["node_id"].startswith("hot_media_"):
            _augment_media_payload_from_content(instance, node)
            _dispatch_media_node(instance, node, cfg)
            if node["status"] != "completed":
                instance["status"] = "failed"
                instance["exit_type"] = "failed_dependency"
                instance["events"].append(_event("flow.end", "failed", "多媒体承办节点未完成，流程无法继续。"))
                instance["updated_at"] = now_iso()
                _save_instance(instance)
                return instance
    if instance["request"].get("workflow_type") == "expert_agent_plan":
        instance["status"] = "completed"
        instance["exit_type"] = "direct_delivery_downloadable_document"
        instance["events"].append(_event("flow.end", "ok", "专家分身已取用，专家方案已生成，可下载文档接口位已返回。"))
    elif instance["request"].get("workflow_type") == "skill_promotion_authorization":
        instance["status"] = "completed"
        instance["exit_type"] = "skill_promoted_reserved_interface"
        instance["events"].append(_event("flow.end", "ok", "技能推广授权链路已按接口位走完；真实授权和推广记录待外部模块接入。"))
    elif (
        instance["request"].get("workflow_type") == "hot_case_sample_then_batch"
        and not instance.get("artifacts", {}).get("hot_case_sample_approved")
    ):
        task_id = "HUMAN-" + uuid4().hex[:8].upper()
        instance["human_tasks"].append(
            {
                "task_id": task_id,
                "status": "pending",
                "title": "确认爆款打样方案",
                "assignee_id": instance["actor_id"],
                "summary": "爆款打样方案已生成；确认通过后，流程执行引擎才会按同一模式批量派发后续生成任务。",
                "after_approval": "dispatch_hot_case_batch",
                "created_at": now_iso(),
            }
        )
        instance["status"] = "waiting_human"
        instance["exit_type"] = "waiting_hot_case_sample_confirmation"
        instance["events"].append(_event("flow.wait_human", "ok", "已生成爆款打样确认待办；通过后再批量生成。", {"task_id": task_id}))
    elif (
        instance["request"].get("workflow_type") == "hot_case_sample_then_batch"
        and instance.get("artifacts", {}).get("hot_case_sample_approved")
    ):
        instance["status"] = "completed"
        instance["exit_type"] = "batch_delivery_after_sample_approval"
        instance["events"].append(_event("flow.end", "ok", "爆款打样已确认，批量生成任务已完成并返回。"))
    elif instance["request"].get("review_policy") == "none":
        instance["status"] = "completed"
        instance["exit_type"] = "direct_delivery"
        instance["events"].append(_event("flow.end", "ok", "流程完成，结果可直接返回发起人。"))
    else:
        task_id = "HUMAN-" + uuid4().hex[:8].upper()
        is_hot_batch = instance["request"].get("workflow_type") == "hot_case_batch"
        batch_count = instance["request"].get("batch_count") or len([node for node in instance.get("nodes", []) if node.get("node_id", "").startswith("hot_media_")])
        instance["human_tasks"].append(
            {
                "task_id": task_id,
                "status": "pending",
                "title": "确认批量爆款生成方案" if is_hot_batch else "确认多媒体生成方案",
                "assignee_id": instance["actor_id"],
                "summary": f"{batch_count} 组爆款复用方案已生成，等待真人确认后作为正式结果返回。" if is_hot_batch else "多媒体方案已生成，等待真人确认后作为正式结果返回。",
                "created_at": now_iso(),
            }
        )
        instance["status"] = "waiting_human"
        instance["exit_type"] = "waiting_human_confirmation"
        instance["events"].append(_event("flow.wait_human", "ok", "已生成真人确认待办。", {"task_id": task_id}))
    instance["updated_at"] = now_iso()
    _save_instance(instance)
    return instance


def _build_content_payload(
    req: FlowStartRequest,
    instance_id: str,
    trace_id: str,
    node_id: str = "content_prepare",
    hot_case: bool = False,
    batch_index: int | None = None,
    hot_case_stage: str = "batch",
) -> dict[str, Any]:
    capability_id = "content_hot_case_reuse" if hot_case else "content_marketing_copy"
    requirement = req.requirement
    if hot_case:
        requirement = (
            f"{req.requirement}\n\n"
            f"【爆款复用要求】第 {batch_index or 1} 版：参考爆款案例结构，生成可交给多媒体生成引擎承接的标题、卖点、正文骨架和视觉提示。"
        )
    return {
        "trace_id": trace_id,
        "message_id": "MSG-" + uuid4().hex[:8].upper(),
        "workflow_instance_id": instance_id,
        "node_id": node_id,
        "task_id": "TASK-CONTENT-" + uuid4().hex[:6].upper(),
        "idempotency_key": f"{instance_id}-{node_id}-v1",
        "caller": {"service_code": "l2.workflow_execution.local_minimal", "service_name": "本地简化流程执行引擎"},
        "actor": {"actor_id": req.actor_id, "real_person_id": REAL_PERSON_IDS.get(req.actor_id, "RP-0001")},
        "capability": {"capability_id": capability_id, "capability_version": "0.1.0", "schema_version": "0.1.0"},
        "request_type": "execute",
        "input": {
            "requirement": requirement,
            "content_type": "marketing_bundle",
            "template_id": "TPL-MARKETING-BUNDLE",
            "hot_case_refs": req.hot_case_refs if hot_case else [],
            "batch_index": batch_index,
            "hot_case_stage": hot_case_stage if hot_case else "",
            "reuse_mode": "hot_case_batch" if hot_case else "",
            "skill_refs": req.skill_refs if hot_case else [],
            "skill_requirements": _hot_case_skill_requirements(req) if hot_case else [],
            "digital_asset_interface_slot": _digital_asset_interface_slot(req) if hot_case else {},
        },
        "expected_return": {"return_mode": "accepted_then_callback", "output_type": "draft_text"},
        "policy": {"review_policy": "direct_delivery_draft", "allow_mock": True},
        "parent_task_id": instance_id,
        "caller_engine": "本地简化流程执行引擎",
        "operator_real_person_id": REAL_PERSON_IDS.get(req.actor_id, "RP-0001"),
        "requested_service": "生成爆款案例复用文字初稿" if hot_case else "生成图文任务所需文字初稿",
        "content_type": "marketing_bundle",
        "input_brief": requirement,
        "source_material_refs": ["HOT-CASE-001", "DATA-PRODUCT-001", "KB-BRAND-STYLE-001"] if hot_case else ["DATA-PRODUCT-001", "KB-BRAND-STYLE-001"],
        "template_id": "TPL-MARKETING-BUNDLE",
        "expected_output": "用于批量爆款复用的标题结构、卖点结构、正文骨架和多媒体承接提示" if hot_case else "用于图文任务的标题、海报文案、卖点文案和说明文字初稿",
        "review_policy": "direct_delivery_draft",
        "scenario_id": "REQ-115",
        "hot_case_refs": req.hot_case_refs if hot_case else [],
        "batch_index": batch_index,
        "batch_count": req.batch_count if hot_case else None,
        "skill_refs": req.skill_refs if hot_case else [],
        "digital_asset_interface_slot": _digital_asset_interface_slot(req) if hot_case else {},
        "security_context": {
            "boundary": "内容产出引擎只负责文字初稿；图片、视频、音频和画面方案由多媒体生成引擎承办。",
            "handoff": "文字初稿作为多媒体输入，不要求多媒体重新创作正文。",
        },
    }


def _dispatch_content_node(instance: dict[str, Any], node: dict[str, Any], cfg: dict[str, str]) -> None:
    node["status"] = "running"
    node["started_at"] = now_iso()
    base = cfg["CONTENT_BASE"].rstrip("/")
    timeout = int(cfg.get("REQUEST_TIMEOUT_SECONDS") or "90")
    instance["events"].append(_event("content.generate", "ok", "正在调用内容产出引擎 v0.2。", {"content_base": cfg["CONTENT_BASE"]}))
    try:
        accepted = post_json(base + "/api/content-production/subtasks", node["payload"], timeout=timeout)
        content_task_id = accepted.get("content_task_id")
        if not content_task_id:
            raise DependencyCallError("dependency_failed", "内容产出接口未返回 content_task_id", accepted)
        result = post_json(base + f"/api/tasks/{content_task_id}/run-auto", {}, timeout=timeout)
    except DependencyCallError as exc:
        node["status"] = "failed"
        node["completed_at"] = now_iso()
        node["result"] = {"ok": False, "error_code": exc.code, "message": str(exc), "detail": exc.detail}
        instance["events"].append(_event("content.generate", "failed", f"内容产出接口调用失败：{exc}", {"code": exc.code}))
        return
    node["completed_at"] = now_iso()
    node["result"] = result
    instance["artifacts"]["content_result"] = result
    instance["artifacts"]["content_task_id"] = result.get("task_id")
    instance["artifacts"]["content_draft_text"] = _extract_content_draft_text(result)
    instance["artifacts"].setdefault("content_results_by_node", {})[node["node_id"]] = result
    instance["artifacts"].setdefault("content_task_ids", {})[node["node_id"]] = result.get("task_id")
    instance["artifacts"].setdefault("content_draft_texts", {})[node["node_id"]] = instance["artifacts"]["content_draft_text"]
    if result.get("status") in {"completed", "pending_human_confirmation"} and result.get("drafts"):
        node["status"] = "completed"
        instance["events"].append(
            _event(
                "content.generate",
                "ok",
                "内容产出承办节点已完成文字初稿，准备把文字结果交给多媒体节点。",
                {"content_task_id": result.get("task_id"), "content_status": result.get("status")},
            )
        )
    else:
        node["status"] = "failed"
        instance["events"].append(
            _event(
                "content.generate",
                "failed",
                f"内容产出返回非可用状态：{result.get('status')}",
                {"content_task_id": result.get("task_id")},
            )
        )


def _extract_content_draft_text(result: dict[str, Any]) -> str:
    lines = []
    for draft in result.get("drafts", []):
        lines.append(f"【{draft.get('title', '文字初稿')}】")
        for section in draft.get("sections", []):
            heading = section.get("heading", "段落")
            body = section.get("body", "")
            lines.append(f"{heading}：{body}")
        unresolved = draft.get("unresolved_questions") or []
        if unresolved:
            lines.append("待确认：" + "；".join(unresolved))
    return "\n".join(lines).strip()


def _augment_media_payload_from_content(instance: dict[str, Any], node: dict[str, Any]) -> None:
    artifacts = instance.get("artifacts", {})
    content_node_id = node["payload"].get("upstream_content_node_id")
    if content_node_id:
        content_text = artifacts.get("content_draft_texts", {}).get(content_node_id)
        content_task_id = artifacts.get("content_task_ids", {}).get(content_node_id)
    else:
        content_text = artifacts.get("content_draft_text")
        content_task_id = artifacts.get("content_task_id")
    if not content_text:
        return
    original = node["payload"].get("requirement", "")
    node["payload"]["requirement"] = (
        f"{original}\n\n"
        "【流程执行引擎传入的内容产出结果】\n"
        f"内容产出任务：{content_task_id}\n"
        f"{content_text}\n\n"
        "【多媒体承办边界】\n"
        "以上文字初稿由内容产出引擎负责，多媒体生成引擎不要重新创作正文；"
        "请围绕这些已产出的文字，生成画面方案、版式建议、视觉提示词和素材引用说明。"
    )
    node["payload"]["upstream_content_task_id"] = content_task_id
    node["payload"]["upstream_content_summary"] = content_text[:800]
    node["payload"]["content_artifact_ref"] = f"ARTIFACT-CONTENT-{content_task_id}"
    node["payload"]["artifact_refs"] = [f"ARTIFACT-TEXT-{content_task_id}"]


def _dispatch_media_node(instance: dict[str, Any], node: dict[str, Any], cfg: dict[str, str]) -> None:
    node["status"] = "running"
    node["started_at"] = now_iso()
    instance["events"].append(_event("media.generate", "ok", "正在调用多媒体生成引擎 v1.1。", {"media_base": cfg["MEDIA_BASE"]}))
    timeout = int(cfg.get("REQUEST_TIMEOUT_SECONDS") or "90")
    try:
        result = post_json(cfg["MEDIA_BASE"].rstrip("/") + "/api/multimedia/subtasks", node["payload"], timeout=timeout)
    except DependencyCallError as exc:
        node["status"] = "failed"
        node["completed_at"] = now_iso()
        node["result"] = {"ok": False, "error_code": exc.code, "message": str(exc), "detail": exc.detail}
        instance["events"].append(_event("media.generate", "failed", f"多媒体接口调用失败：{exc}", {"code": exc.code}))
        return
    node["completed_at"] = now_iso()
    node["result"] = result
    instance["artifacts"]["media_result"] = result
    instance["artifacts"]["media_task_id"] = result.get("task_id")
    instance["artifacts"]["references"] = result.get("references", [])
    instance["artifacts"]["truth_note"] = result.get("truth_note", "")
    instance["artifacts"].setdefault("media_results_by_node", {})[node["node_id"]] = result
    instance["artifacts"].setdefault("media_task_ids", {})[node["node_id"]] = result.get("task_id")
    if result.get("references"):
        refs_by_node = instance["artifacts"].setdefault("references_by_node", {})
        refs_by_node[node["node_id"]] = result.get("references", [])
    if result.get("status") == "completed":
        node["status"] = "completed"
        instance["events"].append(_event("media.generate", "ok", "多媒体承办节点已完成。", {"media_task_id": result.get("task_id")}))
    elif result.get("status") == "llm_failed":
        node["status"] = "failed"
        instance["events"].append(_event("media.generate", "failed", "多媒体已完成知识库取材，但 LLM 调用失败。", {"media_task_id": result.get("task_id")}))
    else:
        node["status"] = "failed"
        instance["events"].append(_event("media.generate", "failed", f"多媒体返回非完成状态：{result.get('status')}", {"media_task_id": result.get("task_id")}))


def _complete_placeholder_node(instance: dict[str, Any], node: dict[str, Any]) -> None:
    node["status"] = "running"
    node["started_at"] = now_iso()
    payload = node.get("payload") or {}
    interface_slot = payload.get("interface_slot") or {
        "slot_id": node.get("action"),
        "target_service": node.get("target_service"),
        "expected_path": payload.get("expected_path"),
        "status": "reserved_interface",
    }
    result = {
        "ok": True,
        "status": "completed",
        "mode": "local_reserved_interface",
        "node_id": node["node_id"],
        "action": node["action"],
        "interface_slot": interface_slot,
        "trace_id": instance.get("trace_id"),
        "truth_note": "本地只完成流程占位和字段传递，没有调用真实外部引擎。",
    }
    if node["node_id"] == "expert_agent_resolve":
        result.update(
            {
                "expert_agent_ref": payload.get("expert_agent_ref"),
                "expert_agent_name": "作物营养专家分身",
                "shared_pool": payload.get("shared_pool"),
                "skill_refs": ["SKILL-CROP-NUTRITION-STANDARD-001", "SKILL-SUGARCANE-FERTILIZATION-001"],
                "permission_result": {
                    "mode": "reserved_interface",
                    "target_service": "l1.permission_management",
                    "expected_action": "use_shared_expert_agent",
                    "allowed": True,
                },
            }
        )
        instance.setdefault("artifacts", {})["expert_agent"] = result
    if node["node_id"] == "skill_adoption_rate":
        result["calculated_metrics"] = {"adoption_rate": "reserved_rule_result", "formula": "accepted_count / generated_count"}
        instance.setdefault("artifacts", {})["promotion_metrics"] = result["calculated_metrics"]
    if node["node_id"] == "permission_share_update":
        result["permission_authorization"] = {
            "share_scope": payload.get("share_scope"),
            "audit_ref": f"AUDIT-{instance['instance_id']}-SHARE",
            "rollback_supported": True,
        }
    node["completed_at"] = now_iso()
    node["result"] = result
    node["status"] = "completed"
    instance["events"].append(_event(node["action"], "ok", f"{node['name']} 已按接口位完成。", {"node_id": node["node_id"]}))


def _save_instance(instance: dict[str, Any]) -> None:
    data = store.read()
    data[instance["instance_id"]] = instance
    store.write(data)
