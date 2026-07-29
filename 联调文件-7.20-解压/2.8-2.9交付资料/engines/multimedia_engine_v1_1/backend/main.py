from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .callback_client import build_callback_options, send_callback
from .config import get_config, public_config, save_config
from .llm_client import test_llm_connection
from .models import ConfigUpdateRequest, IntegrationRunRequest, MultimediaSubtaskRequest
from .store import tasks_store
from .task_adapter import MULTIMEDIA_ENGINE_BOUNDARY, adapt_multimedia_subtask
from .workflow import CAPABILITY_INTERFACES, run_integration

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

app = FastAPI(title="多媒体生成引擎 v1.1 任务适配版", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "prototype": "multimedia-engine-v1.1-task-adapter",
        "note": "在知识库 LLM 联调基础上，增加本引擎边界内的任务归一、缺项提示和任务类型修正。",
    }


@app.get("/api/config")
def config():
    return public_config()


@app.get("/api/capabilities")
def capabilities():
    return {
        "standard": "生成能力接口位（七项 + 预留）",
        "count": len(CAPABILITY_INTERFACES),
        "items": [
            {"capability_id": capability_id, **profile}
            for capability_id, profile in CAPABILITY_INTERFACES.items()
        ],
        "engine_boundary": MULTIMEDIA_ENGINE_BOUNDARY,
        "external_interface_slots": [
            {
                "slot_id": "digital_asset_skill_resolve",
                "target_service": "l2.digital_asset_engine",
                "target_engine": "数字资产引擎",
                "expected_path": "POST /api/digital-assets/skills/resolve",
                "purpose": "取用爆款模式、制作标准、风格编排等已登记技能；本引擎只取用，不创建、不修改。",
                "local_status": "reserved_interface",
            }
        ],
    }


@app.get("/api/multimedia/capabilities")
def multimedia_capabilities():
    return capabilities()


@app.post("/api/multimedia/adapt-preview")
def adapt_preview(req: MultimediaSubtaskRequest):
    return adapt_multimedia_subtask(req)


@app.post("/api/config")
def update_config(req: ConfigUpdateRequest):
    save_config(req.model_dump() if hasattr(req, "model_dump") else req.dict())
    return public_config()


@app.post("/api/llm/test")
def test_llm():
    try:
        return test_llm_connection(get_config())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/integration/run")
def run(req: IntegrationRunRequest):
    def save_progress(partial_result: dict):
        _save_multimedia_progress(partial_result)

    result = run_integration(req, progress_writer=save_progress)
    _save_multimedia_progress(result)
    if result["status"] == "failed":
        raise HTTPException(status_code=502, detail=result)
    return result


@app.post("/api/multimedia/subtasks")
def receive_multimedia_subtask(req: MultimediaSubtaskRequest, background_tasks: BackgroundTasks):
    normalized = _normalize_multimedia_subtask(req)
    callback_options = build_callback_options(req, "l2.multimedia_generation.local_v1_1")

    if callback_options.get("enabled"):
        if not normalized.task_id:
            normalized.task_id = "MM-CB-" + uuid4().hex[:8].upper()
        receipt = _accepted_multimedia_receipt(normalized, callback_options)
        _save_multimedia_progress(receipt)
        background_tasks.add_task(_run_multimedia_task_and_callback, normalized, callback_options)
        return receipt

    result = run_integration(normalized, progress_writer=_save_multimedia_progress)
    result = _decorate_multimedia_result(result, normalized, callback_options)
    _save_multimedia_progress(result)
    return result


@app.get("/api/tasks")
def tasks():
    return tasks_store.read()


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str):
    task = tasks_store.read().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/multimedia/tasks/{task_id}")
def multimedia_task_detail(task_id: str):
    return task_detail(task_id)


@app.post("/api/reset")
def reset():
    tasks_store.write({})
    return {"ok": True, "message": "联调任务记录已清空"}


def _normalize_multimedia_subtask(req: MultimediaSubtaskRequest) -> IntegrationRunRequest:
    input_payload = req.input or {}
    expected_return = req.expected_return or {}
    capability_payload = req.capability or {}
    actor_payload = req.actor or {}
    adapter_result = adapt_multimedia_subtask(req)
    if not adapter_result["accepted"]:
        raise HTTPException(status_code=422, detail=adapter_result)
    normalized = adapter_result["normalized"]
    capability_id = normalized["capability_id"]
    profile = CAPABILITY_INTERFACES.get(capability_id, {})
    output_type = normalized["output_type"] or profile.get("default_output_type") or "poster_plan"
    requirement = (
        req.requirement
        or input_payload.get("requirement")
        or input_payload.get("brief")
        or input_payload.get("text")
        or input_payload.get("original_text")
        or input_payload.get("task_description")
    )
    if not requirement:
        raise HTTPException(status_code=400, detail={"code": "MM_001_MISSING_REQUIREMENT", "message": "缺少 requirement 或 input.requirement"})
    return IntegrationRunRequest(
        trace_id=req.trace_id,
        message_id=req.message_id,
        parent_message_id=req.parent_message_id,
        workflow_instance_id=req.workflow_instance_id or req.parent_flow_id,
        node_id=req.node_id,
        task_id=req.task_id,
        idempotency_key=req.idempotency_key,
        caller=req.caller,
        actor=req.actor,
        capability=req.capability,
        request_type=req.request_type,
        input=req.input,
        expected_return=req.expected_return,
        policy=req.policy,
        actor_id=req.actor_id or actor_payload.get("actor_id") or actor_payload.get("id") or "U001",
        task_type=normalized["task_type"],
        capability_id=capability_id,
        output_type=output_type,
        requirement=requirement,
        top_k=req.top_k,
        use_llm=req.use_llm,
        source_engine=req.source_engine or (req.caller or {}).get("service_code"),
        source_engine_name=req.source_engine_name or (req.caller or {}).get("service_name"),
        parent_flow_id=req.parent_flow_id or req.workflow_instance_id,
        upstream_content_task_id=req.upstream_content_task_id or input_payload.get("upstream_content_task_id"),
        upstream_content_summary=req.upstream_content_summary or input_payload.get("upstream_content_summary"),
        content_artifact_ref=req.content_artifact_ref or input_payload.get("content_artifact_ref"),
        artifact_refs=req.artifact_refs or input_payload.get("artifact_refs") or [],
        skill_refs=req.skill_refs or input_payload.get("skill_refs") or [],
        skill_requirements=req.skill_requirements or input_payload.get("skill_requirements") or [],
        digital_asset_interface_slot=req.digital_asset_interface_slot or input_payload.get("digital_asset_interface_slot") or {},
        model_dispatch_interface_slot=req.model_dispatch_interface_slot or input_payload.get("model_dispatch_interface_slot") or {},
        task_adaptation=adapter_result,
        decision_id=req.decision_id,
        audit_ref=req.audit_ref,
    )


def _run_multimedia_task_and_callback(req: IntegrationRunRequest, callback_options: dict) -> None:
    task_id = req.task_id or "MM-CB-" + uuid4().hex[:8].upper()
    req.task_id = task_id
    in_progress = send_callback(
        callback_options,
        task_id=task_id,
        status="in_progress",
        result={
            "multimedia_task_id": task_id,
            "capability_id": req.capability_id,
            "output_type": req.output_type,
            "phase": "multimedia_generation_running",
        },
        audit_ref=req.audit_ref or f"AUDIT-{task_id}",
        sequence=1,
    )
    _record_multimedia_callback_delivery(task_id, in_progress)

    try:
        result = run_integration(req, progress_writer=_save_multimedia_progress)
        result = _decorate_multimedia_result(result, req, callback_options)
        _save_multimedia_progress(result)
        final_status = _platform_task_status_multimedia(result.get("status"))
        final_delivery = send_callback(
            callback_options,
            task_id=task_id,
            status=final_status,
            result=_callback_result_payload(result),
            error=result.get("error") if final_status == "failed" else None,
            audit_ref=result.get("audit_ref"),
            sequence=2,
        )
        _record_multimedia_callback_delivery(task_id, final_delivery)
    except Exception as exc:
        failed_delivery = send_callback(
            callback_options,
            task_id=task_id,
            status="failed",
            result={"multimedia_task_id": task_id, "capability_id": req.capability_id},
            error={"code": "MM_BACKGROUND_RUN_FAILED", "message": str(exc)},
            audit_ref=req.audit_ref or f"AUDIT-{task_id}",
            sequence=2,
        )
        _record_multimedia_callback_delivery(task_id, failed_delivery)


def _accepted_multimedia_receipt(req: IntegrationRunRequest, callback_options: dict) -> dict:
    task_id = req.task_id or "MM-CB-" + uuid4().hex[:8].upper()
    req.task_id = task_id
    return {
        "ok": True,
        "task_id": task_id,
        "multimedia_task_id": task_id,
        "status": "accepted",
        "interface": "POST /api/multimedia/subtasks",
        "trace_id": req.trace_id,
        "workflow_instance_id": req.workflow_instance_id or req.parent_flow_id,
        "node_id": req.node_id,
        "accepted_receipt": _accepted_receipt_body(req, task_id),
        "callback": _public_callback_options(callback_options),
        "task_adapter_result": req.task_adaptation,
        "result_refs": {
            "artifact_refs": [],
            "note": "任务已接收，完成后通过 callback 返回多媒体方案/提示词和引用。",
        },
        "truth_note": "异步联调模式：本接口先返回 accepted，后台完成知识库取材、上下文渲染和 LLM/Mock 方案生成后回调流程执行引擎。",
        "callback_delivery": [],
    }


def _decorate_multimedia_result(result: dict, req: IntegrationRunRequest, callback_options: dict | None = None) -> dict:
    result["interface"] = "POST /api/multimedia/subtasks"
    result["accepted_receipt"] = _accepted_receipt_body(req, result["task_id"])
    result["flow_callback_preview"] = _callback_preview(result, req)
    if callback_options is not None:
        result["callback"] = _public_callback_options(callback_options)
    return result


def _accepted_receipt_body(req: IntegrationRunRequest, task_id: str) -> dict:
    return {
        "status": "accepted",
        "workflow_instance_id": req.workflow_instance_id or req.parent_flow_id,
        "node_id": req.node_id,
        "task_id": task_id,
        "trace_id": req.trace_id,
        "idempotency_key": req.idempotency_key,
    }


def _save_multimedia_progress(partial_result: dict) -> None:
    data = tasks_store.read()
    previous = data.get(partial_result["task_id"], {})
    if previous.get("callback_delivery") and not partial_result.get("callback_delivery"):
        partial_result["callback_delivery"] = previous["callback_delivery"]
    if previous.get("callback") and not partial_result.get("callback"):
        partial_result["callback"] = previous["callback"]
    data[partial_result["task_id"]] = partial_result
    tasks_store.write(data)


def _record_multimedia_callback_delivery(task_id: str, delivery: dict) -> None:
    data = tasks_store.read()
    task = data.get(task_id, {"task_id": task_id, "status": "callback_delivery_only"})
    task.setdefault("callback_delivery", []).append(delivery)
    data[task_id] = task
    tasks_store.write(data)


def _platform_task_status_multimedia(status: str | None) -> str:
    if status == "completed":
        return "completed"
    if status in {"received", "running"}:
        return "in_progress"
    return "failed"


def _public_callback_options(callback_options: dict) -> dict:
    return {
        "enabled": bool(callback_options.get("enabled")),
        "protocol": callback_options.get("callback_protocol"),
        "url": callback_options.get("callback_url"),
        "source_service": callback_options.get("source_service"),
    }


def _callback_result_payload(result: dict) -> dict:
    return {
        "multimedia_task_id": result.get("task_id"),
        "output_type": result.get("output_type"),
        "capability_id": result.get("capability_id"),
        "artifact_refs": result.get("artifact_refs", []),
        "media_outputs": result.get("media_outputs", {}),
        "hot_case_reuse": result.get("hot_case_reuse", {}),
        "digital_asset_skill_usage": result.get("digital_asset_skill_usage", {}),
        "references": result.get("references", []),
        "truth_note": result.get("truth_note"),
    }


def _callback_preview(result: dict, req: IntegrationRunRequest) -> dict:
    task_id = result["task_id"]
    return {
        "callback_type": "flow.callback",
        "workflow_instance_id": req.workflow_instance_id or req.parent_flow_id,
        "node_id": req.node_id,
        "task_id": task_id,
        "trace_id": req.trace_id,
        "idempotency_key": f"{req.idempotency_key or task_id}-callback",
        "source_service": "l2.multimedia_generation.local_v1_1",
        "status": result.get("status"),
        "result": _callback_result_payload(result),
        "error": result.get("error"),
        "audit_ref": result.get("audit_ref"),
    }
