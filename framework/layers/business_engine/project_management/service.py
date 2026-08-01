from __future__ import annotations

from typing import Any
from uuid import uuid4

from framework.core import now, standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.layers.business_engine.generic_module_adapter import get_for, post_for


MODULE_CODE = "project-management"


def get(handler: Any) -> bool:
    return get_for(MODULE_CODE, handler)


def post(handler: Any, envelope: dict[str, Any]) -> None:
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability in {"project.register.simple", "project.register.major"}:
        try:
            _register_project(handler, envelope, capability)
        except RuntimeError as exc:
            handler.send(502, standard_response(envelope, "failed", error={
                "code": "PROJECT_PERSISTENCE_FAILED",
                "message": str(exc),
            }))
        return
    post_for(MODULE_CODE, handler, envelope)


def _register_project(handler: Any, envelope: dict[str, Any], capability: str) -> None:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    command = payload.get("application_command") if isinstance(payload.get("application_command"), dict) else {}
    command_payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    actor = envelope.get("actor") or {}
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    project = _project_from_payload(payload, command_payload)

    project_id = str(project.get("project_id") or project.get("id") or f"project-{uuid4().hex[:12]}")
    name = str(project.get("name") or "流程登记项目").strip()
    owner_id = (
        actor.get("user_id")
        or actor.get("actor_id")
        or command.get("accountId")
        or payload.get("owner_account_id")
        or "anonymous"
    )
    record = {
        "project_id": project_id,
        "record_id": project_id,
        "tenant_id": actor.get("tenant_id") or "web-workbench",
        "owner_account_id": owner_id,
        "name": name,
        "short": project.get("short") or name[:6],
        "type": project.get("type") or "workflow_project",
        "fixed": False,
        "description": project.get("description") or "由工作台或流程执行引擎创建的 Project",
        "status": project.get("status") or ("approval_pending" if _needs_approval(payload) else "created"),
        "metrics": project.get("metrics") or [],
        "knowledge": project.get("knowledge") or [],
        "project_context": payload.get("project_context"),
        "input_data_refs": payload.get("input_data_refs") if isinstance(payload.get("input_data_refs"), list) else [],
        "workflow_task_id": payload.get("platform_task_id"),
        "source_capability": capability,
        "project_id_from_context": context.get("project_id"),
        "conversation_id": payload.get("conversation_id") or context.get("conversation_id"),
        "created_at": project.get("created_at") or now(),
        "updated_at": now(),
    }
    storage = _data_call(envelope, "foundation_data.write", {
        "dataset": "projects",
        "operation": "upsert",
        "records": [record],
    })
    handler.send(200, standard_response(envelope, "success", data={
        "state": "persisted",
        "module": MODULE_CODE,
        "platform_capability": capability,
        "project": record,
        "project_tasks": _project_tasks_from_payload(payload, project_id),
        "storage": storage,
    }))


def _project_from_payload(payload: dict[str, Any], command_payload: dict[str, Any]) -> dict[str, Any]:
    command_project = command_payload.get("project") if isinstance(command_payload.get("project"), dict) else command_payload
    if command_project:
        return dict(command_project)

    project_context = payload.get("project_context")
    if isinstance(project_context, dict):
        source = project_context
    else:
        source = {"description": str(project_context or payload.get("user_goal") or "")}

    name = (
        source.get("project_name")
        or source.get("name")
        or payload.get("project_name")
        or _infer_project_name(str(source.get("description") or payload.get("user_goal") or ""))
    )
    return {
        "project_id": payload.get("project_id"),
        "name": name,
        "description": source.get("description") or payload.get("user_goal") or "",
        "status": "approval_pending" if _needs_approval(payload) else "created",
        "type": source.get("type") or "workflow_project",
    }


def _infer_project_name(text: str) -> str:
    compact = " ".join(str(text or "").split())
    if not compact:
        return "流程登记项目"
    for marker in ("项目", "推广", "立项"):
        index = compact.find(marker)
        if index >= 0:
            start = max(0, index - 24)
            end = min(len(compact), index + 12)
            return compact[start:end].strip(" ，。；;:")
    return compact[:32]


def _needs_approval(payload: dict[str, Any]) -> bool:
    text = str(payload.get("user_goal") or payload.get("project_context") or "")
    return any(token in text for token in ("审批", "立项", "确认", "待办"))


def _project_tasks_from_payload(payload: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    text = str(payload.get("user_goal") or payload.get("project_context") or "")
    tasks: list[dict[str, Any]] = []
    if any(token in text for token in ("立项", "审批")):
        tasks.append({
            "task_id": f"{project_id}-approval",
            "title": "立项审批待办",
            "state": "pending_human_confirmation",
        })
    if any(token in text for token in ("登记", "项目")):
        tasks.append({
            "task_id": f"{project_id}-registration",
            "title": "项目登记信息核对",
            "state": "created",
        })
    return tasks


def _data_call(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    inner = make_internal_envelope(
        envelope.get("trace_id") or str(uuid4()),
        envelope.get("actor") or {"tenant_id": "web-workbench", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4()),
        capability,
        "foundation",
        "foundation-gateway",
        payload,
        source_layer="business_engine",
        source_module=MODULE_CODE,
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else None,
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=30,
        caller={"layer": "business_engine", "module": MODULE_CODE},
    )
    if status != 200 or not isinstance(response, dict) or response.get("status") != "success":
        raise RuntimeError(str(response))
    return response.get("data") or {}
