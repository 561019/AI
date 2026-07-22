from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from time import perf_counter
from typing import Any

from framework.adapter_specs import AdapterSpec, get_adapter_spec
from framework.core import ROOT, record_interface_call


_ENV_LOADED = False


def invoke_adapter(module_code: str, capability: str, envelope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    _load_env_once()
    spec = get_adapter_spec(capability)
    if spec is None or spec.module_code != module_code:
        return 404, {
            "state": "adapter_spec_missing",
            "error": {
                "code": "ADAPTER_SPEC_NOT_FOUND",
                "module": module_code,
                "capability": capability,
            },
        }

    url = _build_url(spec, envelope)
    payload = _build_payload(spec, envelope)
    headers = _headers(spec, envelope)

    started = perf_counter()
    timeout = _timeout_seconds(envelope)
    try:
        status, body = _http_request(spec.method, url, payload, headers, timeout)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        body = _upstream_unavailable(spec, url, error)
        status = 503

    record_interface_call(
        trace_id=str(envelope.get("trace_id") or "untraced"),
        source=envelope.get("source") or {"layer": "unknown", "module": "unknown"},
        target={"layer": spec.layer, "module": spec.module_code, "kind": "delivered_upstream"},
        capability=spec.capability,
        method=spec.method,
        url=url,
        request=payload if payload is not None else {"query": urllib.parse.urlparse(url).query},
        response=body,
        status_code=status,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return status, {
        "state": "proxied" if 200 <= status < 300 else "upstream_failed",
        "module": spec.module_code,
        "platform_capability": spec.capability,
        "adapter": {
            "method": spec.method,
            "url": url,
            "payload_mode": spec.payload_mode,
            "upstream_env": spec.upstream_env,
            "default_base_url": spec.default_base_url,
            "description_cn": spec.description_cn,
        },
        "upstream_status": status,
        "upstream_response": body,
    }


def _load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    for candidate in (
        ROOT / "framework" / "config" / "module.env",
        ROOT / "framework" / "config" / "model.env",
    ):
        _load_env_file(candidate)
    _ENV_LOADED = True


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _build_url(spec: AdapterSpec, envelope: dict[str, Any]) -> str:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    base_url = (payload.get("upstream_base_url") or os.getenv(spec.upstream_env) or spec.default_base_url).rstrip("/")
    path = spec.path
    name = _account_name(payload, envelope)
    if "{name}" in path:
        path = path.replace("{name}", urllib.parse.quote(name, safe=""))
    url = base_url + path
    query: dict[str, str] = {}
    if spec.payload_mode == "account_lifecycle":
        if spec.method in {"GET", "PATCH", "DELETE"} and "{name}" not in spec.path and name:
            query["name"] = name
    if query:
        separator = "&" if "?" in url else "?"
        url = url + separator + urllib.parse.urlencode(query)
    return url


def _build_payload(spec: AdapterSpec, envelope: dict[str, Any]) -> dict[str, Any] | None:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    if spec.method == "GET":
        return None
    if spec.payload_mode == "platform_envelope":
        return envelope
    if spec.payload_mode == "account_lifecycle":
        return _account_payload(spec, payload)
    return {
        "protocol_version": "1.0",
        "message_id": envelope.get("message_id"),
        "request_id": envelope.get("request_id"),
        "trace_id": envelope.get("trace_id"),
        "source_module": (envelope.get("source") or {}).get("module", "platform"),
        "source_layer": (envelope.get("source") or {}).get("layer", "platform"),
        "operator_id": (envelope.get("actor") or {}).get("person_id") or payload.get("actor_id") or "anonymous",
        "actor_id": (envelope.get("actor") or {}).get("person_id") or payload.get("actor_id") or "anonymous",
        "route_type": "capability.invoke",
        "action": spec.action or spec.capability,
        "action_id": spec.action or spec.capability,
        "capability_id": spec.capability,
        "target_capability": spec.capability,
        "context": envelope.get("context") or {},
        "payload": payload,
        "expected_response": envelope.get("expected_response") or {},
        "idempotency_key": envelope.get("idempotency_key"),
    }


def _account_payload(spec: AdapterSpec, payload: dict[str, Any]) -> dict[str, Any] | None:
    if spec.capability in {"account.delete", "account.list", "account.offboarding_assets.query"}:
        return None if spec.method in {"GET", "DELETE"} else payload
    account = payload.get("account") if isinstance(payload.get("account"), dict) else payload
    if spec.capability == "account.create":
        return {
            "name": account.get("name") or account.get("user_id") or account.get("actor_id"),
            "password": account.get("password"),
            "displayName": account.get("displayName") or account.get("display_name") or account.get("name"),
            "email": account.get("email"),
            "roles": account.get("roles") or ["staff"],
            "properties": account.get("properties") or {},
        }
    if spec.capability == "account.update":
        allowed = {"displayName", "display_name", "email", "roles", "status", "properties"}
        result = {key: value for key, value in account.items() if key in allowed and value is not None}
        if "display_name" in result and "displayName" not in result:
            result["displayName"] = result.pop("display_name")
        return result
    if spec.capability == "account.freeze":
        return {"reason": payload.get("reason") or "platform_request"}
    if spec.capability == "account.handover_confirm":
        return {
            "handover_to_user_id": payload.get("handover_to_user_id") or payload.get("handoverToUserID"),
            "note": payload.get("note") or "",
        }
    return payload


def _headers(spec: AdapterSpec, envelope: dict[str, Any]) -> dict[str, str]:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Platform-Service": "minimal-framework",
        "X-Trace-ID": str(envelope.get("trace_id") or ""),
        "X-Request-ID": str(envelope.get("request_id") or ""),
    }
    caller_headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    authorization = caller_headers.get("Authorization") or caller_headers.get("authorization") or payload.get("authorization")
    token = os.getenv(spec.auth_token_env or "") if spec.auth_token_env else None
    if authorization:
        headers["Authorization"] = str(authorization)
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_request(method: str, url: str, payload: dict[str, Any] | None, headers: dict[str, str], timeout: float = 5) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, _decode_body(raw)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, _decode_body(raw)


def _decode_body(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _timeout_seconds(envelope: dict[str, Any]) -> float:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    try:
        value = float(payload.get("adapter_timeout_seconds", 5))
    except (TypeError, ValueError):
        value = 5
    return max(0.2, min(value, 30))


def _account_name(payload: dict[str, Any], envelope: dict[str, Any]) -> str:
    account = payload.get("account") if isinstance(payload.get("account"), dict) else payload
    return str(
        account.get("name")
        or payload.get("name")
        or account.get("user_id")
        or account.get("actor_id")
        or (envelope.get("actor") or {}).get("person_id")
        or ""
    )


def _upstream_unavailable(spec: AdapterSpec, url: str, error: BaseException) -> dict[str, Any]:
    return {
        "error": {
            "code": "UPSTREAM_UNAVAILABLE",
            "message": "真实交付模块未启动或上游地址不可达",
            "module": spec.module_code,
            "capability": spec.capability,
            "method": spec.method,
            "url": url,
            "set_upstream_env": spec.upstream_env,
            "default_base_url": spec.default_base_url,
            "detail": str(error),
        }
    }
