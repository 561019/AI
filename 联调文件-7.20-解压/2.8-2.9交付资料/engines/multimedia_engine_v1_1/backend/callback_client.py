from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
import json
import urllib.error
import urllib.request


def build_callback_options(req: Any, default_source_service: str) -> dict[str, Any]:
    input_payload = getattr(req, "input", {}) or {}
    expected_return = getattr(req, "expected_return", {}) or {}
    policy = getattr(req, "policy", {}) or {}
    caller = getattr(req, "caller", {}) or {}
    callback_envelope_url = (
        getattr(req, "callback_envelope_url", None)
        or expected_return.get("callback_envelope_url")
        or policy.get("callback_envelope_url")
        or caller.get("callback_envelope_url")
    )
    callback_url = (
        callback_envelope_url
        or getattr(req, "callback_url", None)
        or expected_return.get("callback_url")
        or policy.get("callback_url")
        or caller.get("callback_url")
        or input_payload.get("callback_url")
    )
    protocol = (
        getattr(req, "callback_protocol", None)
        or expected_return.get("callback_protocol")
        or policy.get("callback_protocol")
        or ("platform_v1" if callback_envelope_url else "simple")
    )
    return {
        "enabled": bool(callback_url),
        "callback_url": callback_url,
        "callback_protocol": protocol,
        "callback_headers": getattr(req, "callback_headers", None) or policy.get("callback_headers") or {},
        "callback_timeout_seconds": int(getattr(req, "callback_timeout_seconds", None) or policy.get("callback_timeout_seconds") or 8),
        "source_service": default_source_service,
        "workflow_instance_id": getattr(req, "workflow_instance_id", None) or getattr(req, "parent_flow_id", None) or input_payload.get("workflow_instance_id"),
        "node_id": getattr(req, "node_id", None) or input_payload.get("node_id"),
        "upstream_task_id": getattr(req, "task_id", None) or input_payload.get("task_id"),
        "trace_id": getattr(req, "trace_id", None) or input_payload.get("trace_id") or f"TRACE-{uuid4().hex[:10].upper()}",
        "request_message_id": getattr(req, "message_id", None) or input_payload.get("message_id"),
        "idempotency_key": getattr(req, "idempotency_key", None) or input_payload.get("idempotency_key") or "",
        "actor_id": _actor_id(req),
    }


def send_callback(options: dict[str, Any], *, task_id: str, status: str, result: dict[str, Any], error: Any = None, audit_ref: str | None = None, sequence: int = 1) -> dict[str, Any]:
    if not options.get("enabled"):
        return {"enabled": False, "status": "skipped"}
    payload = _platform_payload(options, task_id, status, result, error, audit_ref, sequence) if options.get("callback_protocol") == "platform_v1" else _simple_payload(options, task_id, status, result, error, audit_ref, sequence)
    try:
        response = _post_json(options["callback_url"], payload, options.get("callback_headers") or {}, int(options.get("callback_timeout_seconds") or 8))
        return {"enabled": True, "ok": True, "url": options["callback_url"], "protocol": options.get("callback_protocol"), "payload": payload, "response": response}
    except Exception as exc:
        return {"enabled": True, "ok": False, "url": options["callback_url"], "protocol": options.get("callback_protocol"), "payload": payload, "error": str(exc)}


def _simple_payload(options: dict[str, Any], task_id: str, status: str, result: dict[str, Any], error: Any, audit_ref: str | None, sequence: int) -> dict[str, Any]:
    callback_id = f"CB-{task_id}-{sequence}"
    return {
        "callback_id": callback_id,
        "trace_id": options.get("trace_id"),
        "workflow_instance_id": options.get("workflow_instance_id"),
        "instance_id": options.get("workflow_instance_id"),
        "node_id": options.get("node_id"),
        "task_id": task_id,
        "subtask_id": options.get("upstream_task_id") or task_id,
        "idempotency_key": f"{options.get('idempotency_key') or task_id}-callback-{sequence}",
        "source_service": options.get("source_service"),
        "status": status,
        "result": result,
        "error": error,
        "audit_ref": audit_ref,
        "callback_sequence": sequence,
        "completed_at": _now_iso(),
    }


def _platform_payload(options: dict[str, Any], task_id: str, status: str, result: dict[str, Any], error: Any, audit_ref: str | None, sequence: int) -> dict[str, Any]:
    trace_id = options.get("trace_id") or f"trace_{uuid4().hex}"
    request_id = f"req_{task_id}_{sequence}"
    message_id = f"msg_{uuid4().hex}"
    return {
        "protocol_version": "1.0",
        "message_id": message_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "parent_message_id": options.get("request_message_id") or "",
        "occurred_at": _now_iso(),
        "source": {"layer": "L2", "service_code": options.get("source_service")},
        "target": {"layer": "L2", "service_code": "l2.workflow_execution"},
        "channel": "callback",
        "action": "flow.callback",
        "request_type": "execute",
        "actor": {"person_id": options.get("actor_id") or "system"},
        "context": {"workflow_instance_id": options.get("workflow_instance_id"), "node_id": options.get("node_id")},
        "idempotency_key": f"{options.get('idempotency_key') or task_id}-platform-callback-{sequence}",
        "deadline_at": (datetime.now(timezone.utc).astimezone() + timedelta(minutes=10)).isoformat(),
        "payload": {
            "callback_id": f"CB-{task_id}-{sequence}",
            "instance_id": options.get("workflow_instance_id"),
            "subtask_id": options.get("upstream_task_id") or task_id,
            "status": status,
            "result": result,
            "error": error,
            "audit_ref": audit_ref,
            "callback_sequence": sequence,
        },
    }


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8-sig")
            return json.loads(body) if body else {"ok": True, "status": response.status}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"callback HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"callback unavailable: {exc.reason}") from exc


def _actor_id(req: Any) -> str:
    actor = getattr(req, "actor", {}) or {}
    return getattr(req, "actor_id", None) or actor.get("real_person_id") or actor.get("actor_id") or actor.get("id") or "system"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()
