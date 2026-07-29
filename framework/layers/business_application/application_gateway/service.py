from __future__ import annotations

import hashlib
import json
import base64
from pathlib import Path
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from framework.core import create_task, get_latest_task_by_trace, get_task, get_trace_calls, idempotent_get, idempotent_put, record_interface_call, standard_response, update_task, validate_envelope
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_verification import list_cases, run_case
from framework.platform_overview import build_overview

FRAMEWORK_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_ROOT = FRAMEWORK_ROOT / "data" / "foundation_data" / "objects" / "uploads"
UPLOAD_INDEX = UPLOAD_ROOT / "upload_index.json"
GENERATED_ROOT = FRAMEWORK_ROOT / "data" / "foundation_data" / "objects" / "generated"


def get(handler: Any) -> bool:
    clean_path = handler.path.split("?", 1)[0]
    if clean_path in {"/chat", "/chat/", "/monitor", "/monitor/", "/demo", "/demo/", "/cases", "/cases/", "/uploads", "/uploads/", "/modules", "/modules/"}:
        name = (
            "modules.html" if "modules" in handler.path else
            "cases.html" if "cases" in handler.path else
            "uploads.html" if "uploads" in handler.path else
            ("chat.html" if "chat" in handler.path else ("demo.html" if "demo" in handler.path else "monitor.html"))
        )
        page = Path(__file__).resolve().parents[3] / "web" / name
        handler.send_html(200, page.read_text(encoding="utf-8")); return True
    if clean_path == "/api/v1/uploads":
        handler.send(200, {"items": _load_upload_index()}); return True
    if clean_path == "/api/v1/platform/overview":
        handler.send(200, build_overview()); return True
    if clean_path.startswith("/api/v1/generated-files/"):
        _download_generated_file(handler, clean_path.rsplit("/", 1)[-1])
        return True
    if clean_path == "/api/v1/data/catalog":
        tenant_id = (parse_qs(urlparse(handler.path).query).get("tenant_id") or ["web-workbench"])[0]
        status, result = _call_data_engine("data.catalog", {}, tenant_id=tenant_id)
        handler.send(status, result); return True
    if clean_path == "/api/v1/data/records":
        query = parse_qs(urlparse(handler.path).query)
        dataset = (query.get("dataset") or [""])[0]
        tenant_id = (query.get("tenant_id") or ["web-workbench"])[0]
        raw_filters = (query.get("filters") or ["{}"])[0]
        try:
            filters = json.loads(raw_filters)
        except json.JSONDecodeError:
            handler.send(400, {"error": {"code": "INVALID_DATA_FILTERS"}}); return True
        if not isinstance(filters, dict):
            handler.send(400, {"error": {"code": "INVALID_DATA_FILTERS"}}); return True
        compact = (query.get("compact") or ["false"])[0].lower() == "true" or dataset == "conversation_messages"
        if not dataset:
            handler.send(400, {"error": {"code": "DATASET_REQUIRED"}}); return True
        if dataset in {"account_credentials", "account_sessions", "model_secrets", "api_credentials"}:
            handler.send(403, {"error": {"code": "SENSITIVE_DATASET_FORBIDDEN"}}); return True
        trace_id = str(uuid4())
        actor = {"tenant_id": tenant_id, "user_id": "data-verifier", "authenticated": True, "roles": ["platform_data_auditor"]}
        envelope = make_internal_envelope(
            trace_id, actor, str(uuid4()), "data.search", "business_engine", "engine-gateway",
            {"dataset": dataset, "filters": filters, "limit": min(int((query.get("limit") or ["100"])[0]), 500), "compact": compact},
            source_layer="business_application", source_module="application-gateway",
        )
        status, response = post_json(
            "http://127.0.0.1:8200/api/v1/engine/instructions", envelope,
            caller={"layer": "business_application", "module": "application-gateway"},
        )
        if status not in {200, 202} or response.get("status") != "success":
            handler.send(502, {"error": {"code": "DATA_QUERY_FAILED", "details": response}}); return True
        operation = response.get("data") or {}
        storage = operation.get("storage_result") or {}
        handler.send(200, {"trace_id": trace_id, "dataset": dataset, "count": storage.get("count", 0), "items": storage.get("items", [])}); return True
    if clean_path.startswith("/api/v1/runtime/session/"):
        trace_id = clean_path.rsplit("/", 1)[-1]
        tenant_id = (parse_qs(urlparse(handler.path).query).get("tenant_id") or ["web-workbench"])[0]
        _, access = _call_data_engine("data.trace", {"trace_id": trace_id}, tenant_id=tenant_id, trace_id=trace_id)
        workflow_data = {}
        for dataset in ("workflow_instances", "workflow_node_instances", "workflow_events"):
            _, queried = _call_data_engine("data.search", {"dataset": dataset, "filters": {"trace_id": trace_id}, "limit": 500}, tenant_id=tenant_id, trace_id=trace_id)
            workflow_data[dataset] = queried.get("items", []) if isinstance(queried, dict) else []
        task = get_latest_task_by_trace(trace_id)
        handler.send(200, {
            "trace_id": trace_id,
            "task": task,
            "latest_result": (task or {}).get("result_ref"),
            "uploaded_documents": [
                item for item in _load_upload_index()
                if item.get("trace_id") == trace_id
            ],
            "interface_calls": get_trace_calls(trace_id),
            "data_access_decisions": access.get("items", []) if isinstance(access, dict) else [],
            "workflow_data": workflow_data,
        }); return True
    if handler.path == "/api/v1/module-verification/cases":
        handler.send(200, {"items": list_cases()}); return True
    if handler.path.startswith("/api/v1/tasks/"):
        item = get_task(handler.path.rsplit("/", 1)[-1]); handler.send(200, item) if item else handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}}); return True
    if clean_path.startswith("/api/v1/traces/") and clean_path.endswith("/calls"):
        trace_id = clean_path.split("/")[-2]
        query = parse_qs(urlparse(handler.path).query)
        call_id = (query.get("call_id") or [None])[0]
        max_payload_chars = int((query.get("max_payload_chars") or ["20000"])[0])
        handler.send(200, {
            "trace_id": trace_id,
            "items": get_trace_calls(trace_id, call_id=call_id, max_payload_chars=max_payload_chars),
        }); return True
    if clean_path.startswith("/api/v1/traces/") and clean_path.endswith("/data-access"):
        trace_id = clean_path.split("/")[-2]
        tenant_id = (parse_qs(urlparse(handler.path).query).get("tenant_id") or ["web-workbench"])[0]
        status, result = _call_data_engine("data.trace", {"trace_id": trace_id}, tenant_id=tenant_id, trace_id=trace_id)
        handler.send(status, result); return True
    return False


def _call_data_engine(capability: str, payload: dict[str, Any], *, tenant_id: str, trace_id: str | None = None) -> tuple[int, dict[str, Any]]:
    actual_trace = trace_id or str(uuid4())
    actor = {"tenant_id": tenant_id, "user_id": "data-verifier", "authenticated": True, "roles": ["platform_data_auditor"]}
    envelope = make_internal_envelope(
        actual_trace, actor, str(uuid4()), capability, "business_engine", "engine-gateway", payload,
        source_layer="business_application", source_module="application-gateway",
    )
    status, response = post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions", envelope,
        caller={"layer": "business_application", "module": "application-gateway"},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        return 502, {"error": {"code": "DATA_OPERATION_FAILED", "details": response}}
    operation = response.get("data") or {}
    storage = operation.get("storage_result") or {}
    return 200, storage


def _friendly_dependency_error(response: Any) -> dict[str, Any]:
    leaf = _deepest_error(response)
    message = str(leaf.get("message") or "").strip()
    code = str(leaf.get("code") or "DEPENDENCY_UNAVAILABLE")
    if code == "MODEL_UPSTREAM_FAILED":
        message = message or "模型调度服务调用失败，意图分析暂时无法完成"
    elif not message:
        message = "平台处理依赖暂时不可用，请查看调用审计中的下游错误"
    return {
        "code": code,
        "message": message,
        "details": response,
        "retryable": bool(leaf.get("retryable", True)),
    }


def _deepest_error(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    error = value.get("error")
    if isinstance(error, dict):
        details = error.get("details")
        nested = _deepest_error(details)
        return nested or error
    details = value.get("details")
    nested = _deepest_error(details)
    return nested or {}


def _read_data_record(trace_id: str, actor: dict[str, Any], dataset: str, record_id: str) -> dict[str, Any] | None:
    envelope = make_internal_envelope(
        trace_id, actor, str(uuid4()), "data.read", "business_engine", "engine-gateway",
        {"dataset": dataset, "record_id": record_id},
        source_layer="business_application", source_module="application-gateway",
    )
    status, response = post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions", envelope,
        caller={"layer": "business_application", "module": "application-gateway"},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        return None
    return ((response.get("data") or {}).get("storage_result") or {}).get("item")


def _validate_owned_context(trace_id: str, actor: dict[str, Any], project_id: Any, conversation_id: Any = None) -> dict[str, str] | None:
    account_id = str(actor.get("user_id") or actor.get("actor_id") or "")
    project_id = str(project_id or "")
    if not account_id or not project_id:
        return {"code": "PROJECT_CONTEXT_REQUIRED", "message": "account_id and project_id are required"}
    project = _read_data_record(trace_id, actor, "projects", project_id)
    if not project:
        return {"code": "PROJECT_NOT_FOUND", "message": "project does not exist"}
    if str(project.get("owner_account_id") or "") != account_id:
        return {"code": "PROJECT_OWNER_MISMATCH", "message": "project is not owned by the current account"}
    if conversation_id is None:
        return None
    conversation = _read_data_record(trace_id, actor, "conversations", str(conversation_id))
    if not conversation:
        return {"code": "CONVERSATION_NOT_FOUND", "message": "conversation does not exist"}
    if str(conversation.get("owner_account_id") or "") != account_id:
        return {"code": "CONVERSATION_OWNER_MISMATCH", "message": "conversation is not owned by the current account"}
    if str(conversation.get("project_id") or "") != project_id:
        return {"code": "CONVERSATION_PROJECT_MISMATCH", "message": "conversation does not belong to the project"}
    return None


def post_multipart(handler: Any) -> None:
    if handler.path.split("?", 1)[0] != "/api/v1/uploads":
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    try:
        fields, files = _parse_multipart(handler)
    except ValueError as exc:
        handler.send(400, {"error": {"code": "INVALID_MULTIPART_REQUEST", "message": str(exc)}})
        return
    if not files:
        handler.send(400, {"error": {"code": "NO_FILE_UPLOADED"}})
        return
    scenario_id = fields.get("scenario_id") or "manual-upload"
    trace_id = fields.get("trace_id") or str(uuid4())
    actor = {
        "tenant_id": fields.get("tenant_id") or "web-workbench",
        "user_id": fields.get("account_id") or "anonymous",
        "authenticated": fields.get("authenticated", "true").lower() != "false",
    }
    binding_error = _validate_owned_context(trace_id, actor, fields.get("project_id"), fields.get("conversation_id"))
    if binding_error:
        handler.send(403, {"trace_id": trace_id, "error": binding_error})
        return
    saved_items = [_save_uploaded_file(file, scenario_id, trace_id) for file in files]
    persistence = _persist_records(
        trace_id, actor, fields.get("conversation_id") or scenario_id,
        [
            {
                "dataset": "storage_objects",
                "operation": "upsert",
                "records": [{
                    "object_id": item["object_id"],
                    "tenant_id": actor["tenant_id"],
                    "owner_account_id": actor["user_id"],
                    "project_id": fields.get("project_id"),
                    "conversation_id": fields.get("conversation_id"),
                    "original_filename": item["original_name"],
                    "object_key": item["stored_name"],
                    "storage_backend": "local-development",
                    "content_type": item["content_type"],
                    "size_bytes": item["size_bytes"],
                    "sha256": item["sha256"],
                    "virus_scan_status": "not_configured",
                    "state": "available",
                } for item in saved_items],
            },
            {
                "dataset": "uploaded_files",
                "operation": "upsert",
                "records": [{
                    **item,
                    "tenant_id": actor["tenant_id"],
                    "owner_account_id": actor["user_id"],
                    "project_id": fields.get("project_id"),
                    "conversation_id": fields.get("conversation_id"),
                } for item in saved_items],
            },
        ],
    )
    if persistence.get("status") != "success":
        handler.send(503, {"error": {"code": "UPLOAD_METADATA_PERSISTENCE_FAILED", "details": persistence}})
        return
    index = _load_upload_index()
    index.extend(saved_items)
    _save_upload_index(index)
    response = {
        "status": "uploaded",
        "trace_id": fields.get("trace_id"),
        "scenario_id": scenario_id,
        "count": len(saved_items),
        "items": saved_items,
        "platform_payload": {
            "scenario_id": scenario_id,
            "uploaded_documents": [item["platform_ref"] for item in saved_items],
            "next_suggested_capabilities": [
                "document.package.build",
                "document.table.extract",
                "data.persist",
                "workflow.execute",
            ],
        },
    }
    if fields.get("trace_id"):
        record_interface_call(
            trace_id=fields["trace_id"],
            source={"layer": "business_application", "module": fields.get("source_module") or "chat-validation"},
            target={"layer": "business_application", "module": "application-gateway"},
            capability="document.upload",
            method="POST",
            url="http://127.0.0.1:8100/api/v1/uploads",
            request={
                "content_type": "multipart/form-data",
                "scenario_id": scenario_id,
                "files": [
                    {
                        "field": file.get("field"),
                        "filename": file.get("filename"),
                        "content_type": file.get("content_type"),
                        "size_bytes": len(file.get("content") or b""),
                    }
                    for file in files
                ],
            },
            response=response,
            status_code=200,
            duration_ms=0,
        )
    handler.send(200, response)


def post(handler: Any, body: dict[str, Any]) -> None:
    if handler.path == "/api/v1/generated-files":
        _create_generated_file(handler, body)
        return
    if handler.path == "/api/v1/module-verification/run":
        case_id = str(body.get("case_id") or "")
        try:
            handler.send(200, run_case(case_id))
        except KeyError:
            handler.send(404, {"error": {"code": "VERIFICATION_CASE_NOT_FOUND", "case_id": case_id}})
        return
    if handler.path.startswith("/api/v1/confirmations/") and handler.path.endswith("/decisions"):
        _confirm(handler, handler.path.split("/")[-2], body); return
    if handler.path in {
        "/api/application/capability-management/commands",
        "/api/application/knowledge-governance/commands",
        "/api/application/account/commands",
        "/api/application/project/commands",
        "/api/application/conversation/commands",
    }:
        _execute_application_command(handler, body); return
    if handler.path != "/api/v1/application/instructions": handler.send(404); return
    missing = validate_envelope(body)
    if missing: handler.send(400, {"error": {"code": "INVALID_REQUEST", "message": str(missing)}}); return
    if body["source"].get("layer") != "business_application" or body["target"].get("layer") != "business_engine": handler.send(403, {"error": {"code": "SOURCE_LAYER_FORBIDDEN"}}); return
    state, cached = idempotent_get("application", body["idempotency_key"], body)
    if state == "conflict": handler.send(409, {"error": {"code": "IDEMPOTENCY_CONFLICT"}}); return
    if state == "replay": handler.send(202 if cached.get("status") == "accepted" else 200, cached); return
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    binding_error = _validate_owned_context(body["trace_id"], body.get("actor") or {}, context.get("project_id"), context.get("conversation_id"))
    if binding_error:
        handler.send(403, standard_response(body, "failed", error=binding_error))
        return
    persistence = _persist_incoming_instruction(body)
    if persistence.get("status") != "success":
        handler.send(503, standard_response(body, "failed", error={"code": "DATA_PERSISTENCE_FAILED", "message": "用户请求未能写入数据模块", "details": persistence})); return
    task_id = create_task(body["trace_id"], body["request_id"])
    forwarded = json.loads(json.dumps(body)); forwarded["source"] = {"layer": "business_application", "module": "application-gateway"}; forwarded["payload"]["platform_task_id"] = task_id
    forwarded["payload"]["conversation_context"] = _load_recent_conversation_context(body, limit=12)
    status, forwarded_response = post_json("http://127.0.0.1:8200/api/v1/engine/instructions", forwarded, timeout=70, caller={"layer": "business_application", "module": "application-gateway"})
    if status not in {200, 202}:
        error = _friendly_dependency_error(forwarded_response)
        update_task(task_id, state="failed", error=error)
        _persist_task_and_assistant_message(body, task_id, get_task(task_id), "execution_error")
        handler.send(502, standard_response(body, "failed", error=error)); return
    task = get_task(task_id)
    _persist_task_and_assistant_message(body, task_id, task, "intent_analysis")
    response = standard_response(body, "accepted", task_id=task_id, progress=0, status_url=f"http://127.0.0.1:8100/api/v1/tasks/{task_id}")
    idempotent_put("application", body["idempotency_key"], body, response); handler.send(202, response)


def _load_recent_conversation_context(envelope: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    """Load a small, ownership-scoped context window for intent resolution."""
    actor = envelope.get("actor") or {}
    context = envelope.get("context") or {}
    conversation_id = str(context.get("conversation_id") or envelope.get("trace_id") or "")
    if not conversation_id:
        return []
    query = make_internal_envelope(
        envelope.get("trace_id") or str(uuid4()),
        actor,
        str(uuid4()),
        "data.search",
        "business_engine",
        "engine-gateway",
        {
            "dataset": "conversation_messages",
            "filters": {
                "conversation_id": conversation_id,
                "owner_account_id": actor.get("user_id") or actor.get("actor_id"),
                "project_id": context.get("project_id"),
            },
            "limit": max(1, min(limit, 30)),
            "compact": True,
        },
        source_layer="business_application",
        source_module="application-gateway",
        context=context,
    )
    status, response = post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions",
        query,
        timeout=20,
        caller={"layer": "business_application", "module": "application-gateway"},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        return []
    operation = response.get("data") or {}
    storage = operation.get("storage_result") if isinstance(operation.get("storage_result"), dict) else {}
    items = storage.get("items") if isinstance(storage.get("items"), list) else []
    compact: list[dict[str, Any]] = []
    for item in items[-limit:]:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        compact.append({
            "role": str(item.get("role") or "unknown"),
            "content": content[:2000],
            "created_at": item.get("created_at"),
        })
    return compact


def _confirm(handler: Any, confirmation_id: str, decision: dict[str, Any]) -> None:
    task_id = confirmation_id.removeprefix("intent-"); task = get_task(task_id)
    if not task or task.get("confirmation_ref", {}).get("id") != confirmation_id: handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}}); return
    # The endpoint URL identifies the task, so make its audit entry joinable to
    # the original request trace even when the browser did not supply one.
    decision["trace_id"] = task["trace_id"]
    decision["task_id"] = task_id
    choice = decision.get("decision")
    if choice not in {"confirm", "reject"}: handler.send(400, {"error": {"code": "INVALID_DECISION"}}); return
    if task["state"] in {"succeeded", "completed_with_errors"}:
        existing_result = task.get("result_ref") or {}
        handler.send(200, {
            "status": task["state"],
            "task_id": task_id,
            "trace_id": task["trace_id"],
            "data": existing_result,
            "idempotent_replay": True,
        })
        return
    if task["state"] != "waiting_human": handler.send(409, {"error": {"code": "INVALID_TASK_STATE", "message": task["state"]}}); return
    if choice == "reject":
        update_task(task_id, state="failed", progress=100, error={"code": "HUMAN_REJECTED", "message": "用户已驳回意图"})
        rejected_task = get_task(task_id)
        _persist_confirmation_result(task, rejected_task, decision, {"state": "rejected", "reason": "HUMAN_REJECTED"})
        handler.send(200, {"status": "rejected", "task_id": task_id, "trace_id": task["trace_id"]}); return
    actor = decision.get("actor") or {"tenant_id": "demo-tenant", "user_id": "demo-user", "authenticated": True}
    intent_tasks = ((task.get("result_ref") or {}).get("data") or {}).get("tasks") or []
    if not intent_tasks:
        handler.send(422, {"error": {"code": "INTENT_TASK_MISSING"}}); return
    intent_task = intent_tasks[0]
    intent_values = (intent_tasks[0].get("parameters") or {}).get("values") if intent_tasks else None
    execution_values = decision["values"] if "values" in decision else intent_values
    uploaded_documents = decision.get("uploaded_documents")
    if uploaded_documents is None:
        uploaded_documents = (intent_task.get("parameters") or {}).get("uploaded_documents") or ((task.get("result_ref") or {}).get("data") or {}).get("uploaded_documents") or []
    intent_task = {
        **intent_task,
        "parameters": {
            **(intent_task.get("parameters") or {}),
            "values": execution_values or [],
            "uploaded_documents": uploaded_documents,
        },
    }
    workflow_context = {"project_id": decision.get("project_id"), "conversation_id": decision.get("conversation_id"), "locale": "zh-CN"}
    envelope = make_internal_envelope(task["trace_id"], actor, task_id, "workflow.execute", "business_engine", "engine-gateway", {"execution_kind": "intent_driven", "confirmation_id": confirmation_id, "intent_task": intent_task, "uploaded_documents": uploaded_documents, "simulate_permission_denied": bool(decision.get("simulate_permission_denied", False))}, source_layer="business_application", source_module="application-gateway", context=workflow_context)
    update_task(task_id, state="running", progress=50)
    status, response = post_json("http://127.0.0.1:8200/api/v1/engine/instructions", envelope, timeout=70, caller={"layer": "business_application", "module": "application-gateway"})
    result = response.get("data") if isinstance(response, dict) else None
    if status not in {200, 202} or not result:
        failure = {"code": "WORKFLOW_EXECUTION_FAILED", "details": response}
        update_task(task_id, state="failed", progress=100, error=failure)
        _persist_confirmation_result(task, get_task(task_id), decision, {"state": "failed", "error": failure})
        handler.send(502, {"status": "failed", "task_id": task_id, "trace_id": task["trace_id"], "error": {"code": "WORKFLOW_EXECUTION_FAILED"}}); return
    workflow_state = ((result.get("workflow_instance") or {}).get("status"))
    if workflow_state == "completed_with_errors":
        failure = {"code": "WORKFLOW_COMPLETED_WITH_ERRORS", "failed_steps": ((result.get("capability_result") or {}).get("failed_steps") or [])}
        update_task(task_id, state="completed_with_errors", progress=100, result=result, error=failure)
        completed_task = get_task(task_id)
        _persist_confirmation_result(task, completed_task, decision, result)
        handler.send(200, {"status": "completed_with_errors", "task_id": task_id, "trace_id": task["trace_id"], "data": result, "error": failure}); return
    update_task(task_id, state="succeeded", progress=100, result=result, clear_error=True)
    completed_task = get_task(task_id)
    _persist_confirmation_result(task, completed_task, decision, result)
    handler.send(200, {"status": "succeeded", "task_id": task_id, "trace_id": task["trace_id"], "data": result})


def _load_upload_index() -> list[dict[str, Any]]:
    if not UPLOAD_INDEX.exists():
        return []
    try:
        data = json.loads(UPLOAD_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_upload_index(items: list[dict[str, Any]]) -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_INDEX.write_text(json.dumps(items[-200:], ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_multipart(handler: Any) -> tuple[dict[str, str], list[dict[str, Any]]]:
    content_type = handler.headers.get("Content-Type", "")
    boundary = _extract_boundary(content_type)
    if not boundary:
        raise ValueError("multipart boundary missing")
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        raise ValueError("empty upload body")
    raw = handler.rfile.read(length)
    marker = b"--" + boundary.encode("utf-8")
    fields: dict[str, str] = {}
    files: list[dict[str, Any]] = []
    for part in raw.split(marker):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip(b"\r\n")
        if b"\r\n\r\n" not in part:
            continue
        head, content = part.split(b"\r\n\r\n", 1)
        headers = _parse_part_headers(head)
        disposition = headers.get("content-disposition", "")
        attrs = _parse_disposition(disposition)
        name = attrs.get("name")
        filename = attrs.get("filename")
        if not name:
            continue
        if filename:
            files.append({
                "field": name,
                "filename": filename,
                "content_type": headers.get("content-type", "application/octet-stream"),
                "content": content,
            })
        else:
            fields[name] = content.decode("utf-8", "replace")
    return fields, files


def _extract_boundary(content_type: str) -> str | None:
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part.split("=", 1)[1].strip('"')
    return None


def _parse_part_headers(head: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    text = head.decode("utf-8", "replace")
    for line in text.split("\r\n"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def _parse_disposition(value: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        attrs[key.strip().lower()] = raw.strip().strip('"')
    return attrs


def _save_uploaded_file(file: dict[str, Any], scenario_id: str, trace_id: str | None = None) -> dict[str, Any]:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    file_id = f"upl_{uuid4().hex[:16]}"
    object_id = f"obj_{uuid4().hex[:16]}"
    original_name = _safe_filename(str(file.get("filename") or "uploaded.bin"))
    suffix = Path(original_name).suffix
    stored_name = f"{file_id}{suffix}"
    content = bytes(file["content"])
    saved_path = UPLOAD_ROOT / stored_name
    saved_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    uploaded_at = datetime.now(timezone.utc).isoformat()
    document_role = _infer_document_role(original_name)
    platform_ref = {
        "type": "uploaded_document",
        "file_id": file_id,
        "object_id": object_id,
        "document_role": document_role,
        "original_name": original_name,
        "content_type": file.get("content_type") or "application/octet-stream",
        "size_bytes": len(content),
        "sha256": digest,
        "storage_uri": f"local://framework/data/foundation_data/objects/uploads/{stored_name}",
        "saved_path": str(saved_path),
    }
    return {
        "file_id": file_id,
        "object_id": object_id,
        "trace_id": trace_id,
        "scenario_id": scenario_id,
        "document_role": document_role,
        "original_name": original_name,
        "stored_name": stored_name,
        "saved_path": str(saved_path),
        "content_type": platform_ref["content_type"],
        "size_bytes": len(content),
        "sha256": digest,
        "uploaded_at": uploaded_at,
        "platform_ref": platform_ref,
    }


def _create_generated_file(handler: Any, body: dict[str, Any]) -> None:
    actor = body.get("actor") if isinstance(body.get("actor"), dict) else {}
    actor = {
        "tenant_id": actor.get("tenant_id") or body.get("tenant_id") or "web-workbench",
        "user_id": actor.get("user_id") or body.get("account_id") or "anonymous",
        "authenticated": bool(actor.get("authenticated", True)),
        "roles": actor.get("roles") or [],
    }
    trace_id = str(body.get("trace_id") or uuid4())
    binding_error = _validate_owned_context(trace_id, actor, body.get("project_id"), body.get("conversation_id"))
    if binding_error:
        handler.send(403, {"trace_id": trace_id, "error": binding_error})
        return
    encoded = body.get("content_base64")
    if not isinstance(encoded, str) or not encoded:
        handler.send(422, {"error": {"code": "GENERATED_FILE_CONTENT_REQUIRED"}})
        return
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        handler.send(422, {"error": {"code": "GENERATED_FILE_CONTENT_INVALID", "message": str(exc)}})
        return
    if len(content) > 20 * 1024 * 1024:
        handler.send(413, {"error": {"code": "GENERATED_FILE_TOO_LARGE"}})
        return
    file_id = f"gen_{uuid4().hex[:16]}"
    object_id = f"obj_{uuid4().hex[:16]}"
    original_name = _safe_filename(str(body.get("original_name") or "generated.txt"))
    suffix = Path(original_name).suffix or ".txt"
    stored_name = f"{file_id}{suffix}"
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    saved_path = GENERATED_ROOT / stored_name
    saved_path.write_bytes(content)
    timestamp = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(content).hexdigest()
    file_record = {
        "file_id": file_id,
        "record_id": file_id,
        "object_id": object_id,
        "tenant_id": actor["tenant_id"],
        "owner_account_id": actor["user_id"],
        "project_id": body.get("project_id"),
        "conversation_id": body.get("conversation_id"),
        "task_id": body.get("task_id"),
        "trace_id": trace_id,
        "original_name": original_name,
        "content_type": body.get("content_type") or "text/plain;charset=utf-8",
        "size_bytes": len(content),
        "sha256": digest,
        "storage_uri": f"local://framework/data/foundation_data/objects/generated/{stored_name}",
        "saved_path": str(saved_path),
        "status": "available",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    object_record = {
        "object_id": object_id,
        "record_id": object_id,
        "tenant_id": actor["tenant_id"],
        "owner_account_id": actor["user_id"],
        "project_id": body.get("project_id"),
        "conversation_id": body.get("conversation_id"),
        "trace_id": trace_id,
        "object_type": "generated_file",
        "original_name": original_name,
        "content_type": file_record["content_type"],
        "size_bytes": len(content),
        "sha256": digest,
        "storage_uri": file_record["storage_uri"],
        "saved_path": str(saved_path),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    persisted = _persist_records(trace_id, actor, str(uuid4()), [
        {"dataset": "generated_files", "operation": "upsert", "records": [file_record]},
        {"dataset": "storage_objects", "operation": "upsert", "records": [object_record]},
    ])
    if persisted.get("status") != "success":
        saved_path.unlink(missing_ok=True)
        handler.send(502, {"status": "failed", "error": {"code": "GENERATED_FILE_PERSISTENCE_FAILED", "details": persisted}})
        return
    handler.send(200, {"status": "succeeded", "trace_id": trace_id, "data": {
        "file_id": file_id,
        "object_id": object_id,
        "original_name": original_name,
        "download_url": f"/api/v1/generated-files/{file_id}",
        "storage_uri": file_record["storage_uri"],
        "size_bytes": len(content),
    }})


def _download_generated_file(handler: Any, file_id: str) -> None:
    tenant_id = (parse_qs(urlparse(handler.path).query).get("tenant_id") or ["web-workbench"])[0]
    status, result = _call_data_engine("data.read", {"dataset": "generated_files", "record_id": file_id}, tenant_id=tenant_id)
    if status != 200 or not result.get("item"):
        handler.send(404, {"error": {"code": "GENERATED_FILE_NOT_FOUND"}})
        return
    item = result["item"]
    path = Path(str(item.get("saved_path") or ""))
    try:
        path.resolve().relative_to(GENERATED_ROOT.resolve())
    except ValueError:
        handler.send(403, {"error": {"code": "GENERATED_FILE_PATH_FORBIDDEN"}})
        return
    if not path.is_file():
        handler.send(404, {"error": {"code": "GENERATED_FILE_OBJECT_MISSING"}})
        return
    raw = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", item.get("content_type") or "application/octet-stream")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Content-Disposition", f'attachment; filename="{_safe_filename(item.get("original_name") or file_id)}"')
    handler.end_headers()
    handler.wfile.write(raw)


def _execute_application_command(handler: Any, command: dict[str, Any]) -> None:
    route = handler.path
    operation = str(command.get("operation") or "")
    if route == "/api/application/conversation/commands":
        _execute_conversation_command(handler, command)
        return
    if route == "/api/application/project/commands":
        _execute_project_command(handler, command)
        return
    if route == "/api/application/knowledge-governance/commands":
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        actor = command.get("actor") or {
            "tenant_id": "web-workbench",
            "user_id": command.get("accountId") or "anonymous",
            "authenticated": True,
        }
        binding_error = _validate_owned_context(
            str(command.get("trace_id") or command.get("traceId") or uuid4()), actor,
            command.get("projectId") or payload.get("project_id"),
            command.get("conversationId") or payload.get("conversation_id"),
        )
        if binding_error:
            handler.send(403, {"status": "failed", "error": binding_error})
            return
    if route == "/api/application/account/commands" and operation in {"register", "login", "resume", "logout"}:
        _execute_public_account_entry(handler, command, operation)
        return
    capability_map = {
        "/api/application/capability-management/commands": {
            "create": "asset.create",
            "fine_tune": "skill.development.request",
            "upgrade": "asset.update",
            "promote": "asset.update",
            "publish": "asset.update",
            "deactivate": "asset.update",
            "restore": "asset.update",
        },
        "/api/application/knowledge-governance/commands": {
            "create_from_conversation": "knowledge_source.register",
            "supplement": "knowledge_source.register",
            "maintain": "asset.update",
            "assign_steward": "asset.update",
        },
        "/api/application/account/commands": {},
        "/api/application/project/commands": {
            "create": "project.register.simple",
            "update": "project.register.simple",
        },
    }
    capability = capability_map[route].get(operation)
    if not capability:
        handler.send(422, {"error": {"code": "APPLICATION_COMMAND_UNSUPPORTED", "operation": operation}})
        return
    trace_id = str(command.get("trace_id") or command.get("traceId") or uuid4())
    request_id = str(command.get("request_id") or uuid4())
    actor = command.get("actor") or {
        "tenant_id": "web-workbench",
        "user_id": command.get("accountId") or "anonymous",
        "authenticated": operation != "register",
    }
    task_id = create_task(trace_id, request_id)
    intent_task = {
        "task_id": f"command-{task_id}",
        "description": f"前端应用命令：{operation}",
        "capability_code": capability,
        "dependencies": [],
        "parameters": {**(command.get("payload") or {}), "application_command": command},
        "confidence": 1.0,
    }
    envelope = make_internal_envelope(
        trace_id,
        actor,
        task_id,
        "workflow.execute",
        "business_engine",
        "engine-gateway",
        {"execution_kind": "intent_driven", "intent_task": intent_task},
        source_layer="business_application",
        source_module="application-gateway",
    )
    update_task(task_id, state="running", progress=25)
    status, response = post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions",
        envelope,
        timeout=70,
        caller={"layer": "business_application", "module": "application-gateway"},
    )
    result = response.get("data") if isinstance(response, dict) else None
    if status not in {200, 202} or not result:
        error = {"code": "APPLICATION_COMMAND_FAILED", "details": response}
        update_task(task_id, state="failed", progress=100, error=error)
        handler.send(502, {"status": "failed", "trace_id": trace_id, "task_id": task_id, "error": error})
        return
    update_task(task_id, state="succeeded", progress=100, result=result)
    handler.send(200, {"status": "succeeded", "trace_id": trace_id, "task_id": task_id, "data": result})


def _execute_public_account_entry(handler: Any, command: dict[str, Any], operation: str) -> None:
    """Run public account registration and login before an authenticated workflow exists."""
    trace_id = str(command.get("trace_id") or command.get("traceId") or uuid4())
    request_id = str(command.get("request_id") or uuid4())
    actor = command.get("actor") or {
        "tenant_id": "web-workbench",
        "user_id": command.get("accountId") or "anonymous",
        "authenticated": False,
    }
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    envelope = make_internal_envelope(
        trace_id,
        actor,
        request_id,
        {
            "register": "account.create",
            "login": "account.identity.verify",
            "resume": "account.session.resolve",
            "logout": "account.session.close",
        }[operation],
        "foundation",
        "foundation-gateway",
        {**payload, "application_command": command},
        source_layer="business_engine",
        source_module="engine-gateway",
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        envelope,
        timeout=70,
        caller={"layer": "business_application", "module": "application-gateway"},
    )
    result = response.get("data") if isinstance(response, dict) else None
    if status != 200 or not result:
        handler.send(502, {
            "status": "failed",
            "trace_id": trace_id,
            "error": {"code": {
                "register": "ACCOUNT_REGISTRATION_FAILED",
                "login": "ACCOUNT_LOGIN_FAILED",
                "resume": "ACCOUNT_SESSION_RESTORE_FAILED",
                "logout": "ACCOUNT_LOGOUT_FAILED",
            }[operation], "details": response},
        })
        return
    handler.send(200, {
        "status": "succeeded",
        "trace_id": trace_id,
        "data": {"capability_result": result},
    })


def _execute_conversation_command(handler: Any, command: dict[str, Any]) -> None:
    operation = str(command.get("operation") or "create")
    if operation not in {"create", "update", "archive"}:
        handler.send(422, {"error": {"code": "CONVERSATION_COMMAND_UNSUPPORTED", "operation": operation}})
        return
    trace_id = str(command.get("trace_id") or command.get("traceId") or uuid4())
    actor = command.get("actor") or {
        "tenant_id": "web-workbench",
        "user_id": command.get("accountId") or "anonymous",
        "authenticated": True,
    }
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    project_id = command.get("projectId") or payload.get("project_id")
    binding_error = _validate_owned_context(trace_id, actor, project_id)
    if binding_error:
        handler.send(403, {"status": "failed", "trace_id": trace_id, "error": binding_error})
        return
    conversation_id = str(command.get("conversationId") or payload.get("conversation_id") or f"conversation-{uuid4().hex[:12]}")
    timestamp = datetime.now(timezone.utc).isoformat()
    existing = _read_data_record(trace_id, actor, "conversations", conversation_id) if operation in {"update", "archive"} else None
    record = {
        **(existing or {}),
        "conversation_id": conversation_id,
        "record_id": conversation_id,
        "tenant_id": actor.get("tenant_id") or "web-workbench",
        "project_id": project_id or (existing or {}).get("project_id"),
        "project_name": payload.get("project_name") or (existing or {}).get("project_name"),
        "title": payload.get("title") or (existing or {}).get("title") or "未命名对话",
        "owner_account_id": actor.get("user_id") or command.get("accountId") or "anonymous",
        "status": "archived" if operation == "archive" else "active",
        "has_history": payload.get("has_history", (existing or {}).get("has_history", False)),
        "context_usage": payload.get("context_usage", (existing or {}).get("context_usage", 0)),
        "created_at": payload.get("created_at") or (existing or {}).get("created_at") or timestamp,
        "updated_at": timestamp,
    }
    persisted = _persist_records(trace_id, actor, str(uuid4()), [{
        "dataset": "conversations",
        "operation": "upsert",
        "records": [record],
    }])
    if persisted.get("status") != "success":
        handler.send(502, {"status": "failed", "trace_id": trace_id, "error": {"code": "CONVERSATION_PERSISTENCE_FAILED", "details": persisted}})
        return
    handler.send(200, {"status": "succeeded", "trace_id": trace_id, "data": {"conversation": record, "storage": persisted.get("data")}})


def _execute_project_command(handler: Any, command: dict[str, Any]) -> None:
    operation = str(command.get("operation") or "create")
    if operation not in {"create", "update", "archive"}:
        handler.send(422, {"error": {"code": "PROJECT_COMMAND_UNSUPPORTED", "operation": operation}})
        return
    trace_id = str(command.get("trace_id") or command.get("traceId") or uuid4())
    actor = command.get("actor") or {
        "tenant_id": "web-workbench",
        "user_id": command.get("accountId") or "anonymous",
        "authenticated": True,
    }
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    project = payload.get("project") if isinstance(payload.get("project"), dict) else payload
    project_id = str(project.get("project_id") or project.get("id") or f"project-{uuid4().hex[:12]}")
    name = str(project.get("name") or "未命名 Project").strip()
    timestamp = datetime.now(timezone.utc).isoformat()
    record = {
        "project_id": project_id,
        "record_id": project_id,
        "tenant_id": actor.get("tenant_id") or "web-workbench",
        "owner_account_id": actor.get("user_id") or command.get("accountId") or "anonymous",
        "name": name,
        "short": project.get("short") or name[:6],
        "type": project.get("type") or "custom",
        "fixed": False,
        "description": project.get("description") or "由工作台创建的 Project",
        "status": "archived" if operation == "archive" else project.get("status") or "已创建",
        "metrics": project.get("metrics") or [],
        "knowledge": project.get("knowledge") or [],
        "created_at": project.get("created_at") or timestamp,
        "updated_at": timestamp,
    }
    persisted = _persist_records(trace_id, actor, str(uuid4()), [{
        "dataset": "projects",
        "operation": "upsert",
        "records": [record],
    }])
    if persisted.get("status") != "success":
        handler.send(502, {"status": "failed", "trace_id": trace_id, "error": {"code": "PROJECT_PERSISTENCE_FAILED", "details": persisted}})
        return
    handler.send(200, {"status": "succeeded", "trace_id": trace_id, "data": {"project": record, "storage": persisted.get("data")}})


def _persist_incoming_instruction(envelope: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") or {}
    context = envelope.get("context") or {}
    payload = envelope.get("payload") or {}
    conversation_id = str(context.get("conversation_id") or envelope.get("trace_id"))
    project_id = context.get("project_id")
    tenant_id = str(actor.get("tenant_id") or "default")
    account_id = str(actor.get("user_id") or actor.get("actor_id") or "anonymous")
    timestamp = datetime.now(timezone.utc).isoformat()
    writes = [
        {"dataset": "conversations", "operation": "upsert", "records": [{
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "project_name": context.get("project_name"),
            "title": context.get("conversation_title"),
            "owner_account_id": account_id,
            "status": "active",
            "updated_at": timestamp,
        }]},
        {"dataset": "conversation_messages", "operation": "upsert", "records": [{
            "message_id": envelope.get("message_id") or str(uuid4()),
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "owner_account_id": account_id,
            "role": "user",
            "content_type": "text",
            "content": payload.get("utterance") or "",
            "uploaded_file_ids": [item.get("file_id") for item in payload.get("uploaded_documents") or [] if isinstance(item, dict)],
            "trace_id": envelope.get("trace_id"),
            "created_at": timestamp,
        }]},
    ]
    return _persist_records(envelope.get("trace_id"), actor, envelope.get("request_id"), writes)


def _compact_persisted_result(value: Any, *, depth: int = 0) -> Any:
    """Keep user results and audit references without duplicating raw datasets."""
    if depth > 8:
        return "[内容已省略]"
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"request_payload", "workflow_prior_outputs"}:
                continue
            if key in {"items", "records"} and isinstance(item, list):
                compact[f"{key}_count"] = len(item)
                continue
            if key == "uploaded_documents" and isinstance(item, list):
                compact[key] = [
                    {
                        field: document.get(field)
                        for field in ("file_id", "object_id", "original_name", "content_type", "size_bytes")
                        if document.get(field) is not None
                    }
                    for document in item
                    if isinstance(document, dict)
                ]
                continue
            compact[key] = _compact_persisted_result(item, depth=depth + 1)
        return compact
    if isinstance(value, list):
        if len(value) > 80:
            return [_compact_persisted_result(item, depth=depth + 1) for item in value[:80]] + [
                f"[其余 {len(value) - 80} 项已保留在对应数据集]"
            ]
        return [_compact_persisted_result(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 12000:
        return value[:12000] + "\n[内容过长，原始数据保留在对应数据集]"
    return value


def _persist_task_and_assistant_message(envelope: dict[str, Any], task_id: str, task: dict[str, Any] | None, content_type: str) -> None:
    if not task:
        return
    actor = envelope.get("actor") or {}
    context = envelope.get("context") or {}
    conversation_id = str(context.get("conversation_id") or envelope.get("trace_id"))
    account_id = str(actor.get("user_id") or actor.get("actor_id") or "anonymous")
    tenant_id = str(actor.get("tenant_id") or "default")
    timestamp = datetime.now(timezone.utc).isoformat()
    compact_task = {**task, "result_ref": _compact_persisted_result(task.get("result_ref"))}
    _persist_records(envelope.get("trace_id"), actor, task_id, [
        {"dataset": "task_snapshots", "operation": "upsert", "records": [{**compact_task, "record_id": task_id, "tenant_id": tenant_id, "owner_account_id": account_id, "conversation_id": conversation_id, "project_id": context.get("project_id")}]},
        {"dataset": "conversation_messages", "operation": "upsert", "records": [{
            "message_id": f"intent-{task_id}",
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "project_id": context.get("project_id"),
            "owner_account_id": account_id,
            "role": "assistant",
            "content_type": content_type,
            "content": compact_task.get("result_ref"),
            "task_id": task_id,
            "trace_id": envelope.get("trace_id"),
            "created_at": timestamp,
        }]},
    ])


def _persist_confirmation_result(original_task: dict[str, Any], completed_task: dict[str, Any] | None, decision: dict[str, Any], result: dict[str, Any]) -> None:
    if not completed_task:
        return
    actor = decision.get("actor") or {"tenant_id": "demo-tenant", "user_id": "demo-user", "authenticated": True}
    conversation_id = str(decision.get("conversation_id") or original_task.get("trace_id"))
    project_id = decision.get("project_id")
    account_id = str(actor.get("user_id") or actor.get("actor_id") or "anonymous")
    tenant_id = str(actor.get("tenant_id") or "default")
    timestamp = datetime.now(timezone.utc).isoformat()
    compact_result = _compact_persisted_result(result)
    compact_task = {**completed_task, "result_ref": _compact_persisted_result(completed_task.get("result_ref"))}
    _persist_records(original_task.get("trace_id"), actor, completed_task.get("task_id"), [
        {"dataset": "task_snapshots", "operation": "upsert", "records": [{**compact_task, "record_id": completed_task.get("task_id"), "tenant_id": tenant_id, "owner_account_id": account_id, "conversation_id": conversation_id, "project_id": project_id}]},
        {"dataset": "conversation_messages", "operation": "upsert", "records": [{
            "message_id": f"result-{completed_task.get('task_id')}",
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "owner_account_id": account_id,
            "role": "assistant",
            "content_type": "execution_result",
            "content": compact_result,
            "task_id": completed_task.get("task_id"),
            "trace_id": original_task.get("trace_id"),
            "created_at": timestamp,
        }]},
        {"dataset": "confirmations", "operation": "upsert", "records": [{
            "confirmation_id": original_task.get("confirmation_ref", {}).get("id"),
            "record_id": original_task.get("confirmation_ref", {}).get("id"),
            "task_id": completed_task.get("task_id"),
            "decision": decision.get("decision"),
            "state": "rejected" if decision.get("decision") == "reject" else completed_task.get("state"),
            "tenant_id": tenant_id,
            "owner_account_id": account_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "trace_id": original_task.get("trace_id"),
            "decided_at": timestamp,
        }]},
    ])


def _persist_records(trace_id: str, actor: dict[str, Any], task_id: str, writes: list[dict[str, Any]]) -> dict[str, Any]:
    envelope = make_internal_envelope(
        trace_id,
        actor,
        str(task_id),
        "data.persist",
        "business_engine",
        "engine-gateway",
        {"writes": writes, "dataset": writes[0].get("dataset") if writes else "business_records"},
        source_layer="business_application",
        source_module="application-gateway",
    )
    status, response = post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions",
        envelope,
        timeout=20,
        caller={"layer": "business_application", "module": "application-gateway"},
    )
    if status not in {200, 202} or response.get("status") != "success":
        return {"status": "failed", "details": response}
    return {"status": "success", "data": response.get("data")}


def _safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "uploaded.bin"


def _infer_document_role(name: str) -> str:
    lower = name.lower()
    if "合同" in name or "contract" in lower:
        return "contract_ledger"
    if "销售" in name or "对账" in name or "reconciliation" in lower:
        return "sales_reconciliation_data_pack"
    if "发票" in name or "invoice" in lower:
        return "invoice"
    if "回款" in name or "payment" in lower:
        return "payment_flow"
    return "business_document"
