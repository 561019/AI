from __future__ import annotations

from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audit_log import get_logs, write_log
from .callback_client import build_callback_options, send_callback
from .mock_data import (
    ACTION_CATALOG,
    ERROR_CODES,
    INTERFACE_CONTRACTS,
    L1_MODULES,
    SCENARIOS,
    SOURCE_MATERIALS,
    STATUS_SPEC,
    SUBTASK_REQUIRED_FIELDS,
    TEMPLATES,
    USERS,
    WORKFLOW_STEPS,
)
from .models import FreezeRequest, IntegrationSubtaskRequest, ReviewResultRequest, TaskCreateRequest
from .registry import update_registry_status
from .store import audit_store, registry_store, tasks_store
from .task_adapter import CONTENT_ENGINE_BOUNDARY, adapt_content_subtask
from .workflow_engine import approve_current_node, freeze_task, new_task, run_all_steps, run_next_step

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

app = FastAPI(title="内容产出引擎 v0.2 任务适配版", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


CONTENT_CAPABILITIES = [
    {
        "capability_id": "content_marketing_copy",
        "name": "营销文案生成",
        "batch": "首批",
        "implementation_status": "local_mock_ready",
        "capability_version": "0.1.0",
        "schema_version": "0.1.0",
        "input": ["产品资料", "品牌规范", "模板", "任务要求"],
        "output": ["标题", "卖点", "正文", "说明文案", "text_artifact_ref"],
    },
    {
        "capability_id": "content_report_draft",
        "name": "报告初稿生成",
        "batch": "首批",
        "implementation_status": "local_mock_ready",
        "capability_version": "0.1.0",
        "schema_version": "0.1.0",
        "input": ["资料引用", "分析结果引用", "报告模板", "任务要求"],
        "output": ["报告结构", "文字初稿", "text_artifact_ref"],
    },
    {
        "capability_id": "content_article_draft",
        "name": "文章初稿生成",
        "batch": "首批",
        "implementation_status": "local_mock_ready",
        "capability_version": "0.1.0",
        "schema_version": "0.1.0",
        "input": ["主题", "资料引用", "风格要求"],
        "output": ["文章标题", "正文段落", "text_artifact_ref"],
    },
    {
        "capability_id": "content_meeting_summary",
        "name": "会议纪要/汇报稿整理",
        "batch": "任务适配",
        "implementation_status": "local_generic_draft_ready",
        "capability_version": "0.2.0",
        "schema_version": "0.1.0",
        "input": ["会议记录", "项目资料", "汇报要求"],
        "output": ["汇报稿", "纪要", "待办清单", "text_artifact_ref"],
    },
    {
        "capability_id": "content_hot_case_reuse",
        "name": "爆款案例复用文案",
        "batch": "首批联调",
        "implementation_status": "local_hot_case_flow_ready",
        "capability_version": "0.1.0",
        "schema_version": "0.1.0",
        "input": ["爆款案例引用", "产品资料", "品牌规范"],
        "output": ["复用标题结构", "卖点结构", "正文结构", "text_artifact_ref"],
    },
    {
        "capability_id": "content_agronomy_fertilization_plan",
        "name": "专家分身施肥方案生成",
        "batch": "案例一接口位联调",
        "implementation_status": "local_expert_plan_mock_ready",
        "capability_version": "0.1.0",
        "schema_version": "0.1.0",
        "input": ["expert_agent_ref", "skill_refs", "project_id", "规则计算接口位", "资料/上下文"],
        "output": ["专家方案结构化初稿", "downloadable_document_ref", "document_export_ref", "text_artifact_ref"],
    },
    {
        "capability_id": "content_script_draft",
        "name": "话术/脚本初稿生成",
        "batch": "任务适配",
        "implementation_status": "local_generic_draft_ready",
        "capability_version": "0.2.0",
        "schema_version": "0.1.0",
        "input": ["场景", "目标对象", "表达口吻", "资料引用"],
        "output": ["话术", "脚本段落", "注意事项", "text_artifact_ref"],
    },
    {
        "capability_id": "content_notice_document",
        "name": "通知/公文草稿生成",
        "batch": "任务适配",
        "implementation_status": "local_generic_draft_ready",
        "capability_version": "0.2.0",
        "schema_version": "0.1.0",
        "input": ["事实", "依据", "要求", "期限"],
        "output": ["通知/公文草稿", "待确认项", "text_artifact_ref"],
    },
    {
        "capability_id": "content_legal_draft",
        "name": "法律文书草稿生成",
        "batch": "任务适配",
        "implementation_status": "local_mock_ready",
        "capability_version": "0.2.0",
        "schema_version": "0.1.0",
        "input": ["案件事实", "法律结构", "诉求或答辩方向"],
        "output": ["法律文书草稿", "律师审核提示", "text_artifact_ref"],
    },
    {
        "capability_id": "content_generic_draft",
        "name": "通用文字初稿兜底",
        "batch": "任务适配",
        "implementation_status": "local_generic_draft_ready",
        "capability_version": "0.2.0",
        "schema_version": "0.1.0",
        "input": ["任务描述", "目标读者", "资料引用"],
        "output": ["通用文字初稿", "待补充信息", "text_artifact_ref"],
    },
]


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "prototype": "content-production-engine-v0.2-task-adapter", "mode": "local-fastapi-mock"}


@app.get("/api/content-production/capabilities")
def content_capabilities():
    return {
        "service_code": "l2.content_production.local_v0_2",
        "standard": "内容产出能力清单（任务适配版）",
        "count": len(CONTENT_CAPABILITIES),
        "items": CONTENT_CAPABILITIES,
        "engine_boundary": CONTENT_ENGINE_BOUNDARY,
        "truth_note": "本接口用于流程执行引擎读取内容产出可承办能力；v0.2 增加本引擎边界内的任务归一、缺项提示和通用模板兜底。",
    }


@app.get("/api/bootstrap")
def bootstrap():
    return {
        "users": USERS,
        "scenarios": SCENARIOS,
        "templates": TEMPLATES,
        "source_materials": SOURCE_MATERIALS,
        "workflow_steps": WORKFLOW_STEPS,
        "l1_modules": L1_MODULES,
        "actions": ACTION_CATALOG,
        "subtask_required_fields": SUBTASK_REQUIRED_FIELDS,
        "interface_contracts": INTERFACE_CONTRACTS,
        "status_spec": STATUS_SPEC,
        "error_codes": ERROR_CODES,
        "engine_boundary": CONTENT_ENGINE_BOUNDARY,
    }


@app.post("/api/content-production/adapt-preview")
def adapt_preview(req: IntegrationSubtaskRequest):
    return adapt_content_subtask(req)


@app.post("/api/tasks")
def create_task(req: TaskCreateRequest):
    try:
        task = new_task(req.actor_id, req.scenario_id, req.requirement)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    data = tasks_store.read()
    data[task["task_id"]] = task
    tasks_store.write(data)
    return task


@app.get("/api/tasks")
def list_tasks():
    return tasks_store.read()


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = tasks_store.read().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在"})
    return _enrich_content_task(task)


@app.post("/api/tasks/{task_id}/run-step")
def run_step(task_id: str):
    data = tasks_store.read()
    task = data.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在"})
    task = run_next_step(task)
    data[task_id] = task
    tasks_store.write(data)
    return _enrich_content_task(task)


@app.post("/api/tasks/{task_id}/run-auto")
def run_auto(task_id: str):
    data = tasks_store.read()
    task = data.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在"})
    task = run_all_steps(task)
    data[task_id] = task
    tasks_store.write(data)
    return _enrich_content_task(task)


@app.get("/api/tasks/{task_id}/logs")
def task_logs(task_id: str):
    return get_logs(task_id)


@app.get("/api/tasks/{task_id}/registry")
def task_registry(task_id: str):
    task = tasks_store.read().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在"})
    if not task.get("registry_id"):
        return None
    return registry_store.read().get(task["registry_id"])


@app.post("/api/tasks/{task_id}/review-result")
def review_result(task_id: str, req: ReviewResultRequest):
    data = tasks_store.read()
    task = data.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在"})
    try:
        task = approve_current_node(task, req.approver_id, req.decision, req.reason)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "CP_003_PERMISSION_DENIED", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "CP_400_BAD_REVIEW_STATE", "message": str(exc)})
    data[task_id] = task
    tasks_store.write(data)
    return task


@app.post("/api/tasks/{task_id}/freeze")
def freeze(task_id: str, req: FreezeRequest):
    data = tasks_store.read()
    task = data.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在"})
    try:
        task = freeze_task(task, req.actor_id, req.reason)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "CP_003_PERMISSION_DENIED", "message": str(exc)})
    data[task_id] = task
    tasks_store.write(data)
    return task


@app.get("/api/tasks/{task_id}/report")
def task_report(task_id: str):
    task = tasks_store.read().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在"})
    registry = registry_store.read().get(task.get("registry_id")) if task.get("registry_id") else None
    return {
        "prototype": "内容产出引擎 v0.2 任务适配版",
        "task": task,
        "registry": registry,
        "logs": get_logs(task_id),
        "conclusion": "该报告用于演示内容产出引擎的字段校验、权限判定、文字初稿生成、真人审核和成果登记链路。",
    }


@app.post("/api/content-production/subtasks")
def receive_integration_subtask(req: IntegrationSubtaskRequest, background_tasks: BackgroundTasks):
    adapter_result = adapt_content_subtask(req)
    if not adapter_result["accepted"]:
        raise HTTPException(status_code=422, detail=adapter_result)
    normalized = adapter_result["normalized"]
    content_type = normalized["content_type"]
    template_id = normalized["template_id"]
    input_brief = adapter_result["requirement"] or _request_input_brief(req)
    if not input_brief:
        raise HTTPException(status_code=400, detail={"code": "CP_001_MISSING_FIELD", "message": "缺少 input_brief 或 input.requirement"})
    scenario_id = req.scenario_id or normalized["scenario_id"] or _match_scenario(content_type, template_id)
    actor_id = _actor_from_real_person(_request_real_person_id(req))
    if not actor_id:
        raise HTTPException(status_code=400, detail={"code": "CP_400_UNKNOWN_OPERATOR", "message": "无法根据真人编号匹配演示用户"})
    try:
        task = new_task(actor_id, scenario_id, input_brief)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if req.trace_id:
        task["trace_id"] = req.trace_id
    subtask_payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    subtask_payload.update(
        {
            "caller_engine": subtask_payload.get("caller_engine") or (req.caller or {}).get("service_name") or "流程执行引擎",
            "requested_service": req.requested_service or normalized["label"],
            "content_type": content_type,
            "input_brief": input_brief,
            "expected_output": req.expected_output or f"{normalized['label']}文字初稿",
            "template_id": template_id,
            "scenario_id": scenario_id,
            "trace_id": task["trace_id"],
        }
    )
    task["subtask"] = subtask_payload
    task["task_adapter_result"] = adapter_result
    task["interface_context"] = _interface_context(req, task, adapter_result)
    callback_options = build_callback_options(req, "l2.content_production.local_v0_2")
    task["callback_options"] = _public_callback_options(callback_options)
    task["callback_delivery"] = []
    data = tasks_store.read()
    data[task["task_id"]] = task
    tasks_store.write(data)
    if callback_options.get("enabled"):
        background_tasks.add_task(_run_content_task_and_callback, task["task_id"], callback_options)
    return {
        "ok": True,
        "content_task_id": task["task_id"],
        "task_id": task["task_id"],
        "trace_id": task["trace_id"],
        "status": "accepted" if callback_options.get("enabled") else task["status"],
        "accepted_receipt": {
            "status": "accepted",
            "workflow_instance_id": req.workflow_instance_id or req.parent_task_id,
            "node_id": req.node_id,
            "idempotency_key": req.idempotency_key,
        },
        "task_adapter_result": adapter_result,
        "callback": _public_callback_options(callback_options),
        "result_refs": _content_result_refs(task),
        "permission_result": _permission_result(task),
        "audit_ref": f"AUDIT-{task['task_id']}",
    }


@app.get("/api/content-production/tasks/{content_task_id}")
def content_task_status(content_task_id: str):
    return get_task(content_task_id)


@app.post("/api/content-production/tasks/{content_task_id}/review-result")
def content_review_result(content_task_id: str, req: ReviewResultRequest):
    return review_result(content_task_id, req)


@app.get("/api/content-production/tasks/{content_task_id}/registry")
def content_registry(content_task_id: str):
    return task_registry(content_task_id)


@app.get("/api/contracts")
def contracts():
    return {
        "interface_contracts": INTERFACE_CONTRACTS,
        "status_spec": STATUS_SPEC,
        "error_codes": ERROR_CODES,
        "data_registry_fields": ["file_store", "structured_catalog", "semantic_store", "ai_labels", "audit_refs"],
    }


@app.post("/api/reset")
def reset():
    tasks_store.write({})
    registry_store.write({})
    audit_store.write([])
    write_log(None, None, "system:reset", "local-json-store", "allow", "内容产出引擎 v0.2 任务适配版任务、登记、日志已重置。")
    return {"ok": True, "message": "任务、登记、日志已重置"}


def _actor_from_real_person(real_person_id: str) -> str | None:
    if real_person_id in USERS:
        return real_person_id
    for actor_id, user in USERS.items():
        if user["real_person_id"] == real_person_id:
            return actor_id
    return None


def _match_scenario(content_type: str, template_id: str | None) -> str:
    for scenario_id, scenario in SCENARIOS.items():
        if scenario["content_type"] == content_type or scenario["template_id"] == template_id:
            return scenario_id
    raise HTTPException(status_code=400, detail={"code": "CP_002_UNSUPPORTED_CONTENT_TYPE", "message": "无法匹配内容产出场景"})


def _request_real_person_id(req: IntegrationSubtaskRequest) -> str:
    actor = req.actor or {}
    return (
        req.operator_real_person_id
        or actor.get("real_person_id")
        or actor.get("actor_id")
        or actor.get("id")
        or "RP-0001"
    )


def _request_content_type(req: IntegrationSubtaskRequest) -> str:
    input_payload = req.input or {}
    capability = req.capability or {}
    capability_id = capability.get("capability_id") or input_payload.get("capability_id")
    if req.content_type:
        return req.content_type
    if input_payload.get("content_type"):
        return input_payload["content_type"]
    if capability_id == "content_agronomy_fertilization_plan":
        return "expert_plan"
    if capability_id in {"content_marketing_copy", "content_hot_case_reuse"}:
        return "marketing_bundle"
    if capability_id == "content_report_draft":
        return "marketing_bundle"
    if capability_id == "content_article_draft":
        return "marketing_bundle"
    return "marketing_bundle"


def _request_template_id(req: IntegrationSubtaskRequest) -> str | None:
    input_payload = req.input or {}
    capability = req.capability or {}
    capability_id = capability.get("capability_id") or input_payload.get("capability_id")
    if capability_id == "content_agronomy_fertilization_plan":
        return req.template_id or input_payload.get("template_id") or "TPL-EXPERT-PLAN"
    return req.template_id or input_payload.get("template_id") or "TPL-MARKETING-BUNDLE"


def _request_input_brief(req: IntegrationSubtaskRequest) -> str:
    input_payload = req.input or {}
    return (
        req.input_brief
        or input_payload.get("requirement")
        or input_payload.get("input_brief")
        or input_payload.get("brief")
        or input_payload.get("text")
        or input_payload.get("original_text")
        or ""
    )


def _interface_context(req: IntegrationSubtaskRequest, task: dict, adapter_result: dict | None = None) -> dict:
    capability = req.capability or {}
    input_payload = req.input or {}
    expected_return = req.expected_return or {}
    policy = req.policy or {}
    normalized = (adapter_result or {}).get("normalized") or {}
    capability_id = normalized.get("capability_id") or capability.get("capability_id") or input_payload.get("capability_id") or "content_marketing_copy"
    hot_case_refs = input_payload.get("hot_case_refs") or []
    if not hot_case_refs and capability_id == "content_hot_case_reuse":
        hot_case_refs = getattr(req, "source_material_refs", []) or []
    return {
        "message_id": req.message_id,
        "parent_message_id": req.parent_message_id,
        "workflow_instance_id": req.workflow_instance_id or req.parent_task_id,
        "node_id": req.node_id,
        "upstream_task_id": req.task_id,
        "idempotency_key": req.idempotency_key,
        "capability_id": capability_id,
        "capability_version": capability.get("capability_version") or "0.1.0",
        "schema_version": capability.get("schema_version") or "0.1.0",
        "expected_return": expected_return,
        "policy": policy,
        "content_artifact_ref": f"ARTIFACT-CONTENT-{task['task_id']}",
        "hot_case_refs": hot_case_refs,
        "batch_index": input_payload.get("batch_index"),
        "batch_count": input_payload.get("batch_count"),
        "reuse_mode": input_payload.get("reuse_mode"),
        "hot_case_stage": input_payload.get("hot_case_stage"),
        "skill_refs": input_payload.get("skill_refs") or [],
        "skill_requirements": input_payload.get("skill_requirements") or [],
        "digital_asset_interface_slot": input_payload.get("digital_asset_interface_slot") or {},
        "expert_agent_ref": input_payload.get("expert_agent_ref"),
        "project_id": input_payload.get("project_id"),
        "rule_calculation_interface_slot": input_payload.get("rule_calculation_interface_slot") or {},
        "context_prompt_interface_slot": input_payload.get("context_prompt_interface_slot") or {},
        "model_dispatch_interface_slot": input_payload.get("model_dispatch_interface_slot") or {},
        "data_operation_interface_slot": input_payload.get("data_operation_interface_slot") or {},
        "task_adapter_result": adapter_result or {},
    }


def _content_result_refs(task: dict) -> dict:
    task_id = task["task_id"]
    context = task.get("interface_context") or {}
    refs = {
        "content_artifact_ref": f"ARTIFACT-CONTENT-{task_id}",
        "text_artifact_ref": f"ARTIFACT-TEXT-{task_id}",
        "artifact_refs": [f"ARTIFACT-TEXT-{task_id}"],
        "hot_case_refs": context.get("hot_case_refs") or [],
        "batch_index": context.get("batch_index"),
        "reuse_mode": context.get("reuse_mode"),
        "skill_refs": context.get("skill_refs") or [],
        "expert_agent_ref": context.get("expert_agent_ref"),
        "artifact_status": "reserved_local_ref",
        "note": "本地联调版先返回引用占位；正式接 L1.7 后由产物库生成真实 artifact_ref。",
    }
    if context.get("capability_id") == "content_agronomy_fertilization_plan":
        refs.update(
            {
                "downloadable_document_ref": f"DOC-EXPERT-PLAN-{task_id}",
                "document_export_ref": f"EXPORT-DOC-{task_id}",
                "data_operation_interface_slot": context.get("data_operation_interface_slot") or {},
                "rule_calculation_interface_slot": context.get("rule_calculation_interface_slot") or {},
            }
        )
    return refs


def _permission_result(task: dict) -> dict:
    return {
        "mode": "local_mock",
        "decision_id": f"DECISION-{task['task_id']}",
        "allowed": task.get("status") != "blocked_permission",
        "audit_ref": f"AUDIT-{task['task_id']}",
    }


def _run_content_task_and_callback(task_id: str, callback_options: dict) -> None:
    data = tasks_store.read()
    task = data.get(task_id)
    if not task:
        delivery = send_callback(
            callback_options,
            task_id=task_id,
            status="failed",
            result={},
            error={"code": "CP_404_TASK_NOT_FOUND", "message": "任务不存在，无法执行后台回调。"},
            audit_ref=f"AUDIT-{task_id}",
            sequence=1,
        )
        _record_callback_delivery(task_id, delivery)
        return

    in_progress = send_callback(
        callback_options,
        task_id=task_id,
        status="in_progress",
        result={"content_task_id": task_id, "phase": "content_production_running"},
        audit_ref=f"AUDIT-{task_id}",
        sequence=1,
    )
    task.setdefault("callback_delivery", []).append(in_progress)
    data[task_id] = task
    tasks_store.write(data)

    try:
        task = run_all_steps(task)
        data = tasks_store.read()
        data[task_id] = task
        tasks_store.write(data)
        enriched = _enrich_content_task(task)
        final_status = _platform_task_status_content(enriched.get("status"))
        final_error = None
        if final_status == "failed":
            final_error = {
                "code": "CP_TASK_NOT_COMPLETED",
                "message": f"内容产出任务未完成，当前状态：{enriched.get('status')}",
            }
        final_delivery = send_callback(
            callback_options,
            task_id=task_id,
            status=final_status,
            result={
                "content_task_id": task_id,
                "result_refs": enriched.get("result_refs", {}),
                "permission_result": enriched.get("permission_result", {}),
                "content_type": (enriched.get("interface_context") or {}).get("content_type"),
                "task_status": enriched.get("status"),
                "draft": enriched.get("draft"),
                "truth_note": "本地内容产出回调返回文字成果引用和结构化摘要；真实文件入库由后续 L1.7/产物库接口承接。",
            },
            error=final_error,
            audit_ref=enriched.get("audit_ref"),
            sequence=2,
        )
        _record_callback_delivery(task_id, final_delivery)
    except Exception as exc:
        failed_delivery = send_callback(
            callback_options,
            task_id=task_id,
            status="failed",
            result={"content_task_id": task_id},
            error={"code": "CP_BACKGROUND_RUN_FAILED", "message": str(exc)},
            audit_ref=f"AUDIT-{task_id}",
            sequence=2,
        )
        _record_callback_delivery(task_id, failed_delivery)


def _record_callback_delivery(task_id: str, delivery: dict) -> None:
    data = tasks_store.read()
    task = data.get(task_id)
    if not task:
        return
    task.setdefault("callback_delivery", []).append(delivery)
    data[task_id] = task
    tasks_store.write(data)


def _platform_task_status_content(status: str | None) -> str:
    if status == "completed":
        return "completed"
    if status == "pending_human_confirmation":
        return "waiting_human"
    if status in {"created", "running", "preparing_context", "dispatching_model", "drafting", "checking"}:
        return "in_progress"
    return "failed"


def _public_callback_options(callback_options: dict) -> dict:
    return {
        "enabled": bool(callback_options.get("enabled")),
        "protocol": callback_options.get("callback_protocol"),
        "url": callback_options.get("callback_url"),
        "source_service": callback_options.get("source_service"),
    }


def _callback_preview(task: dict) -> dict:
    context = task.get("interface_context") or {}
    return {
        "callback_type": "flow.callback",
        "workflow_instance_id": context.get("workflow_instance_id"),
        "node_id": context.get("node_id"),
        "task_id": task["task_id"],
        "trace_id": task.get("trace_id"),
        "idempotency_key": f"{context.get('idempotency_key') or task['task_id']}-callback",
        "status": task.get("status"),
        "result": _content_result_refs(task),
        "error": None,
        "audit_ref": f"AUDIT-{task['task_id']}",
    }


def _enrich_content_task(task: dict) -> dict:
    enriched = dict(task)
    enriched["result_refs"] = _content_result_refs(task)
    enriched["permission_result"] = _permission_result(task)
    enriched["audit_ref"] = f"AUDIT-{task['task_id']}"
    enriched["flow_callback_preview"] = _callback_preview(task)
    enriched["task_adapter_result"] = task.get("task_adapter_result") or (task.get("interface_context") or {}).get("task_adapter_result") or {}
    context = task.get("interface_context") or {}
    if context.get("capability_id") == "content_hot_case_reuse":
        enriched["hot_case_reuse"] = {
            "enabled": True,
            "reuse_mode": context.get("reuse_mode") or "hot_case_reuse",
            "hot_case_refs": context.get("hot_case_refs") or [],
            "batch_index": context.get("batch_index"),
            "hot_case_stage": context.get("hot_case_stage"),
            "skill_refs": context.get("skill_refs") or [],
            "digital_asset_interface_slot": context.get("digital_asset_interface_slot") or {},
            "text_boundary": "内容产出只生成爆款复用文字初稿；画面方案、图片、视频和提示词由多媒体生成引擎承办。",
        }
    if context.get("capability_id") == "content_agronomy_fertilization_plan":
        enriched["expert_plan"] = {
            "enabled": True,
            "expert_agent_ref": context.get("expert_agent_ref"),
            "skill_refs": context.get("skill_refs") or [],
            "project_id": context.get("project_id"),
            "downloadable_document_ref": enriched["result_refs"].get("downloadable_document_ref"),
            "document_export_ref": enriched["result_refs"].get("document_export_ref"),
            "reserved_interfaces": {
                "rule_calculation": context.get("rule_calculation_interface_slot") or {},
                "context_prompt": context.get("context_prompt_interface_slot") or {},
                "model_dispatch": context.get("model_dispatch_interface_slot") or {},
                "data_operation": context.get("data_operation_interface_slot") or {},
            },
            "truth_note": "本地内容产出只生成专家方案结构化初稿；专家分身解析、规则计算、文档导出和存档均为接口位。",
        }
    return enriched
