from __future__ import annotations

import hashlib
import json
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

FRAMEWORK_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_ROOT = FRAMEWORK_ROOT / "data" / "foundation_data" / "objects" / "uploads"
UPLOAD_INDEX = UPLOAD_ROOT / "upload_index.json"


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
    if clean_path == "/api/v1/data/records":
        query = parse_qs(urlparse(handler.path).query)
        dataset = (query.get("dataset") or [""])[0]
        tenant_id = (query.get("tenant_id") or ["web-workbench"])[0]
        if not dataset:
            handler.send(400, {"error": {"code": "DATASET_REQUIRED"}}); return True
        if dataset in {"account_credentials", "account_sessions", "model_secrets", "api_credentials"}:
            handler.send(403, {"error": {"code": "SENSITIVE_DATASET_FORBIDDEN"}}); return True
        trace_id = str(uuid4())
        actor = {"tenant_id": tenant_id, "user_id": "data-verifier", "authenticated": True, "roles": ["platform_data_auditor"]}
        envelope = make_internal_envelope(
            trace_id, actor, str(uuid4()), "data.search", "business_engine", "engine-gateway",
            {"dataset": dataset, "filters": {}, "limit": min(int((query.get("limit") or ["100"])[0]), 500)},
            source_layer="business_application", source_module="application-gateway",
        )
        status, response = post_json(
            "http://127.0.0.1:8200/api/v1/engine/instructions", envelope,
            caller={"layer": "business_application", "module": "application-gateway"},
        )
        if status != 200 or response.get("status") != "success":
            handler.send(502, {"error": {"code": "DATA_QUERY_FAILED", "details": response}}); return True
        operation = response.get("data") or {}
        storage = operation.get("storage_result") or {}
        handler.send(200, {"trace_id": trace_id, "dataset": dataset, "count": storage.get("count", 0), "items": storage.get("items", [])}); return True
    if clean_path.startswith("/api/v1/runtime/session/"):
        trace_id = clean_path.rsplit("/", 1)[-1]
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
        }); return True
    if handler.path == "/api/v1/module-verification/cases":
        handler.send(200, {"items": list_cases()}); return True
    if handler.path.startswith("/api/v1/tasks/"):
        item = get_task(handler.path.rsplit("/", 1)[-1]); handler.send(200, item) if item else handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}}); return True
    if handler.path.startswith("/api/v1/traces/") and handler.path.endswith("/calls"):
        trace_id = handler.path.split("/")[-2]; handler.send(200, {"trace_id": trace_id, "items": get_trace_calls(trace_id)}); return True
    return False


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
    trace_id = fields.get("trace_id")
    saved_items = [_save_uploaded_file(file, scenario_id, trace_id) for file in files]
    actor = {
        "tenant_id": fields.get("tenant_id") or "web-workbench",
        "user_id": fields.get("account_id") or "anonymous",
        "authenticated": fields.get("authenticated", "true").lower() != "false",
    }
    persistence = _persist_records(
        trace_id or str(uuid4()), actor, fields.get("conversation_id") or scenario_id,
        [{
            "dataset": "uploaded_files",
            "operation": "upsert",
            "records": [{
                **item,
                "tenant_id": actor["tenant_id"],
                "owner_account_id": actor["user_id"],
                "project_id": fields.get("project_id"),
                "conversation_id": fields.get("conversation_id"),
            } for item in saved_items],
        }],
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
    }:
        _execute_application_command(handler, body); return
    if handler.path != "/api/v1/application/instructions": handler.send(404); return
    missing = validate_envelope(body)
    if missing: handler.send(400, {"error": {"code": "INVALID_REQUEST", "message": str(missing)}}); return
    if body["source"].get("layer") != "business_application" or body["target"].get("layer") != "business_engine": handler.send(403, {"error": {"code": "SOURCE_LAYER_FORBIDDEN"}}); return
    state, cached = idempotent_get("application", body["idempotency_key"], body)
    if state == "conflict": handler.send(409, {"error": {"code": "IDEMPOTENCY_CONFLICT"}}); return
    if state == "replay": handler.send(202 if cached.get("status") == "accepted" else 200, cached); return
    persistence = _persist_incoming_instruction(body)
    if persistence.get("status") != "success":
        handler.send(503, standard_response(body, "failed", error={"code": "DATA_PERSISTENCE_FAILED", "message": "用户请求未能写入数据模块", "details": persistence})); return
    task_id = create_task(body["trace_id"], body["request_id"])
    forwarded = json.loads(json.dumps(body)); forwarded["source"] = {"layer": "business_application", "module": "application-gateway"}; forwarded["payload"]["platform_task_id"] = task_id
    status, _ = post_json("http://127.0.0.1:8200/api/v1/engine/instructions", forwarded, timeout=70, caller={"layer": "business_application", "module": "application-gateway"})
    if status not in {200, 202}:
        update_task(task_id, state="failed", error={"code": "DEPENDENCY_UNAVAILABLE"})
        _persist_task_and_assistant_message(body, task_id, get_task(task_id), "execution_error")
        handler.send(502, standard_response(body, "failed", error={"code": "DEPENDENCY_UNAVAILABLE", "message": "engine gateway unavailable", "retryable": True})); return
    task = get_task(task_id)
    _persist_task_and_assistant_message(body, task_id, task, "intent_analysis")
    response = standard_response(body, "accepted", task_id=task_id, progress=0, status_url=f"http://127.0.0.1:8100/api/v1/tasks/{task_id}")
    idempotent_put("application", body["idempotency_key"], body, response); handler.send(202, response)


def _confirm(handler: Any, confirmation_id: str, decision: dict[str, Any]) -> None:
    task_id = confirmation_id.removeprefix("intent-"); task = get_task(task_id)
    if not task or task.get("confirmation_ref", {}).get("id") != confirmation_id: handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}}); return
    choice = decision.get("decision")
    if choice not in {"confirm", "reject"}: handler.send(400, {"error": {"code": "INVALID_DECISION"}}); return
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
    envelope = make_internal_envelope(task["trace_id"], actor, task_id, "workflow.execute", "business_engine", "engine-gateway", {"execution_kind": "intent_driven", "confirmation_id": confirmation_id, "intent_task": intent_task, "uploaded_documents": uploaded_documents, "simulate_permission_denied": bool(decision.get("simulate_permission_denied", False))}, source_layer="business_application", source_module="application-gateway")
    update_task(task_id, state="running", progress=50)
    status, response = post_json("http://127.0.0.1:8200/api/v1/engine/instructions", envelope, timeout=70, caller={"layer": "business_application", "module": "application-gateway"})
    result = response.get("data") if isinstance(response, dict) else None
    if status not in {200, 202} or not result:
        failure = {"code": "WORKFLOW_EXECUTION_FAILED", "details": response}
        update_task(task_id, state="failed", progress=100, error=failure)
        _persist_confirmation_result(task, get_task(task_id), decision, {"state": "failed", "error": failure})
        handler.send(502, {"status": "failed", "task_id": task_id, "trace_id": task["trace_id"], "error": {"code": "WORKFLOW_EXECUTION_FAILED"}}); return
    update_task(task_id, state="succeeded", progress=100, result=result)
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


def _execute_application_command(handler: Any, command: dict[str, Any]) -> None:
    route = handler.path
    operation = str(command.get("operation") or "")
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
        "/api/application/account/commands": {
            "login": "account.identity.verify",
            "register": "account.create",
            "logout": "account.identity.resolve",
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


def _persist_task_and_assistant_message(envelope: dict[str, Any], task_id: str, task: dict[str, Any] | None, content_type: str) -> None:
    if not task:
        return
    actor = envelope.get("actor") or {}
    context = envelope.get("context") or {}
    conversation_id = str(context.get("conversation_id") or envelope.get("trace_id"))
    timestamp = datetime.now(timezone.utc).isoformat()
    _persist_records(envelope.get("trace_id"), actor, task_id, [
        {"dataset": "task_snapshots", "operation": "upsert", "records": [{**task, "record_id": task_id, "conversation_id": conversation_id, "project_id": context.get("project_id")}]},
        {"dataset": "conversation_messages", "operation": "upsert", "records": [{
            "message_id": f"intent-{task_id}",
            "conversation_id": conversation_id,
            "project_id": context.get("project_id"),
            "role": "assistant",
            "content_type": content_type,
            "content": task.get("result_ref"),
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
    timestamp = datetime.now(timezone.utc).isoformat()
    _persist_records(original_task.get("trace_id"), actor, completed_task.get("task_id"), [
        {"dataset": "task_snapshots", "operation": "upsert", "records": [{**completed_task, "record_id": completed_task.get("task_id"), "conversation_id": conversation_id, "project_id": project_id}]},
        {"dataset": "conversation_messages", "operation": "upsert", "records": [{
            "message_id": f"result-{completed_task.get('task_id')}",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "role": "assistant",
            "content_type": "execution_result",
            "content": result,
            "task_id": completed_task.get("task_id"),
            "trace_id": original_task.get("trace_id"),
            "created_at": timestamp,
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
    if status != 200 or response.get("status") != "success":
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
