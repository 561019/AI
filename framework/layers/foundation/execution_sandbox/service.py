from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from time import perf_counter, sleep
from typing import Any
from uuid import uuid4

from framework.core import record_interface_call, standard_response
from framework.module_catalog import MODULE_BY_CODE


MODULE_CODE = "execution-sandbox"
MODULE = MODULE_BY_CODE[MODULE_CODE]
DEFAULT_UPSTREAM = "http://127.0.0.1:8765"
DEFAULT_TOKEN = "hanhe-basic-layer-demo-token-change-before-production"
DEFAULT_SANDBOX_PERSON_ID = "demo-user"
DEFAULT_SANDBOX_TENANT_ID = "hanhe-group"

CAPABILITY_TO_STANDARD = {
    "sandbox.run_task": ("CAP.SANDBOX.TASK.RUN", "sandbox.template.run"),
    "sandbox.run_code": ("CAP.SANDBOX.CODE.RUN", "sandbox.code.run"),
    "sandbox.run_browser": ("CAP.SANDBOX.BROWSER.RUN", "sandbox.browser.run"),
}


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in MODULE.capabilities]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != MODULE.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return

    capability = (
        envelope.get("target", {}).get("capability")
        or envelope.get("action")
        or envelope.get("payload", {}).get("action")
        or "sandbox.run_task"
    )
    if capability not in MODULE.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={
            "code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE",
            "capability": capability,
            "provider_module": MODULE.code,
        }))
        return

    if capability == "sandbox.result.query":
        _query_result(handler, envelope)
        return

    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    standard_message = _build_standard_message(envelope, capability, payload)
    headers = _sandbox_headers(envelope, payload)
    submit_url = _upstream_base(payload) + "/api/v1/layer-interface/messages"
    status, response, duration_ms = _request_json("POST", submit_url, standard_message, headers, timeout=_timeout(payload))

    if status == 202 and payload.get("wait_for_result"):
        status, response, duration_ms = _poll_result(envelope, payload, response, headers, duration_ms)

    record_interface_call(
        trace_id=str(envelope.get("trace_id") or "untraced"),
        source=envelope.get("source") or {"layer": "foundation", "module": MODULE.code},
        target={"layer": "foundation", "module": MODULE.code, "kind": "delivered_upstream"},
        capability=str(capability),
        method="POST",
        url=submit_url,
        request=standard_message,
        response=response,
        status_code=status,
        duration_ms=duration_ms,
    )

    if not (200 <= status < 300):
        handler.send(502 if status in {0, 503} else status, standard_response(envelope, "failed", error={
            "code": "EXECUTION_SANDBOX_UPSTREAM_FAILED",
            "message": "执行沙箱真实上游未完成本次调用。",
            "upstream_status": status,
            "details": response,
            "retryable": status in {0, 408, 429, 500, 502, 503, 504},
        }))
        return

    data = _normalize_success(capability, payload, response)
    handler.send(200, standard_response(envelope, "success", data=data))


def _query_result(handler: Any, envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    request_id = str(payload.get("sandbox_request_id") or payload.get("request_id") or payload.get("task_id") or "").strip()
    if not request_id:
        handler.send(422, standard_response(envelope, "failed", error={
            "code": "SANDBOX_REQUEST_ID_REQUIRED",
            "message": "查询执行沙箱结果需要 sandbox_request_id 或 request_id。",
        }))
        return
    url = _upstream_base(payload) + f"/api/v1/layer-interface/messages/{request_id}"
    status, response, duration_ms = _request_json("GET", url, None, _sandbox_headers(envelope, payload), timeout=_timeout(payload))
    record_interface_call(
        trace_id=str(envelope.get("trace_id") or "untraced"),
        source=envelope.get("source") or {"layer": "foundation", "module": MODULE.code},
        target={"layer": "foundation", "module": MODULE.code, "kind": "delivered_upstream"},
        capability="sandbox.result.query",
        method="GET",
        url=url,
        request={"sandbox_request_id": request_id},
        response=response,
        status_code=status,
        duration_ms=duration_ms,
    )
    if not (200 <= status < 300):
        handler.send(502 if status in {0, 503} else status, standard_response(envelope, "failed", error={
            "code": "EXECUTION_SANDBOX_RESULT_QUERY_FAILED",
            "upstream_status": status,
            "details": response,
        }))
        return
    handler.send(200, standard_response(envelope, "success", data=_normalize_success("sandbox.result.query", payload, response)))


def _build_standard_message(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    capability_id, action = CAPABILITY_TO_STANDARD[capability]
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    platform_tenant_id = str(actor.get("tenant_id") or payload.get("tenant_id") or "demo-tenant")
    platform_person_id = str(actor.get("actor_id") or actor.get("user_id") or actor.get("person_id") or payload.get("actor_id") or "demo-user")
    tenant_id = _sandbox_tenant_id(actor, payload)
    person_id = _sandbox_person_id(actor, payload)
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    context = {
        **context,
        "platform_actor": {
            "person_id": platform_person_id,
            "tenant_id": platform_tenant_id,
        },
        "sandbox_actor_mapping": {
            "mode": "adapter_identity_bridge",
            "reason": "delivered sandbox currently resolves its own account gateway identities",
        },
    }
    return {
        "protocol_version": "1.0",
        "message_id": str(uuid4()),
        "trace_id": str(envelope.get("trace_id") or uuid4()),
        "request_id": str(envelope.get("request_id") or uuid4()),
        "parent_message_id": envelope.get("message_id"),
        "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
        "target": {"layer": "L1", "service_code": "l1.execution_sandbox"},
        "channel": "internal.workflow",
        "route_type": "task.dispatch",
        "action": action,
        "capability_id": capability_id,
        "capability_dictionary_version": str(payload.get("capability_dictionary_version") or "v4.0"),
        "registry_version": str(payload.get("registry_version") or "platform-local"),
        "actor": {"person_id": person_id, "tenant_id": tenant_id},
        "context": context,
        "idempotency_key": str(envelope.get("idempotency_key") or f"sandbox-{capability}-{uuid4()}"),
        "deadline_at": (datetime.now(timezone.utc) + timedelta(seconds=int(_timeout(payload)))).isoformat(),
        "payload": _sandbox_payload(capability, payload),
    }


def _sandbox_payload(capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    base = {
        "agent": str(payload.get("agent") or "flow-execution-engine"),
        "limits": {
            "timeout_seconds": int(limits.get("timeout_seconds") or payload.get("timeout_seconds") or 10),
            "memory_mb": int(limits.get("memory_mb") or payload.get("memory_mb") or 512),
            "cpu_cores": float(limits.get("cpu_cores") or payload.get("cpu_cores") or 1),
        },
        "input": payload.get("input") if isinstance(payload.get("input"), dict) else {
            "user_goal": payload.get("user_goal") or payload.get("description") or "",
            "workflow_prior_outputs": payload.get("workflow_prior_outputs") or {},
        },
        "retain_snapshot": bool(payload.get("retain_snapshot", True)),
    }
    if capability == "sandbox.run_browser":
        base["url"] = str(payload.get("url") or payload.get("target_url") or "http://sandbox-allow.test/")
        return base
    if capability == "sandbox.run_code":
        base["language"] = "python"
        base["code"] = str(payload.get("code") or "import json\nprint(json.dumps({'ok': True, 'source': 'platform_sandbox_verification'}))")
        return base
    base["scenario_id"] = str(payload.get("scenario_id") or "s20_purchase_plan")
    return base


def _sandbox_headers(envelope: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, str]:
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    tenant_id = _sandbox_tenant_id(actor, payload if isinstance(payload, dict) else {})
    token = os.getenv("SANDBOX_PLATFORM_API_TOKEN") or DEFAULT_TOKEN
    return {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
        "X-Caller-Layer": "business_engine",
        "X-Engine-Id": "flow-execution-engine",
        "X-Company-Id": tenant_id,
        "X-Trace-Id": str(envelope.get("trace_id") or ""),
    }


def _sandbox_person_id(actor: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(
        payload.get("sandbox_person_id")
        or os.getenv("EXECUTION_SANDBOX_PERSON_ID")
        or DEFAULT_SANDBOX_PERSON_ID
    )


def _sandbox_tenant_id(actor: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(
        payload.get("sandbox_tenant_id")
        or os.getenv("EXECUTION_SANDBOX_TENANT_ID")
        or DEFAULT_SANDBOX_TENANT_ID
    )


def _upstream_base(payload: dict[str, Any]) -> str:
    return str(payload.get("upstream_base_url") or os.getenv("EXECUTION_SANDBOX_UPSTREAM_URL") or DEFAULT_UPSTREAM).rstrip("/")


def _timeout(payload: dict[str, Any]) -> float:
    try:
        return max(1.0, min(float(payload.get("adapter_timeout_seconds") or payload.get("timeout_seconds") or 20), 300.0))
    except (TypeError, ValueError):
        return 20.0


def _poll_result(envelope: dict[str, Any], payload: dict[str, Any], submit_response: Any, headers: dict[str, str], duration_ms: float) -> tuple[int, Any, float]:
    data = submit_response.get("data") if isinstance(submit_response, dict) else {}
    request_id = str((data or {}).get("task_id") or submit_response.get("request_id") or "").strip() if isinstance(submit_response, dict) else ""
    if not request_id:
        return 202, submit_response, duration_ms
    deadline = perf_counter() + min(_timeout(payload), 60.0)
    interval = 0.5
    last_status, last_response = 202, submit_response
    url = _upstream_base(payload) + f"/api/v1/layer-interface/messages/{request_id}"
    while perf_counter() < deadline:
        sleep(interval)
        status, response, query_ms = _request_json("GET", url, None, headers, timeout=min(5.0, _timeout(payload)))
        duration_ms += query_ms
        last_status, last_response = status, response
        if status == 200 and isinstance(response, dict) and response.get("reply_type") in {"success", "failed"}:
            return status, response, duration_ms
    return last_status, last_response, duration_ms


def _request_json(method: str, url: str, payload: dict[str, Any] | None, headers: dict[str, str], *, timeout: float) -> tuple[int, Any, float]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    started = perf_counter()
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            body = json.loads(raw.decode("utf-8")) if raw else None
            return response.status, body, (perf_counter() - started) * 1000
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except json.JSONDecodeError:
            body = {"raw": raw.decode("utf-8", errors="replace")}
        return error.code, body, (perf_counter() - started) * 1000
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        return 503, {
            "error": {
                "code": "UPSTREAM_UNAVAILABLE",
                "message": "执行沙箱真实上游未启动或地址不可达。",
                "url": url,
                "set_upstream_env": "EXECUTION_SANDBOX_UPSTREAM_URL",
                "detail": str(error),
            }
        }, (perf_counter() - started) * 1000


def _normalize_success(capability: str, payload: dict[str, Any], response: Any) -> dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else None
    return {
        "state": "completed" if isinstance(response, dict) and response.get("reply_type") == "success" else "accepted",
        "module": MODULE.code,
        "module_name_cn": "执行沙箱",
        "platform_capability": capability,
        "integration_status": MODULE.integration_status,
        "delivery_root": MODULE.delivery_root,
        "sandbox_request_id": (data or {}).get("task_id") if isinstance(data, dict) else None,
        "sandbox_reply": response,
        "normalized_task": {
            "capability_code": capability,
            "scenario_id": payload.get("scenario_id"),
            "wait_for_result": bool(payload.get("wait_for_result")),
        },
    }
