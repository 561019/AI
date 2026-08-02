from __future__ import annotations

import json
import urllib.error
import urllib.request
from time import perf_counter
from typing import Any

from framework.core import record_interface_call


def post_json(url: str, payload: dict[str, Any], timeout: float = 5, caller: dict[str, str] | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "X-Platform-Service": "minimal-framework"},
    )
    started = perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            body = json.loads(raw.decode("utf-8")) if raw else None
            _record(url, payload, response.status, body, started, caller)
            return response.status, body
    except urllib.error.HTTPError as error:
        raw = error.read()
        body = json.loads(raw.decode("utf-8")) if raw else None
        _record(url, payload, error.code, body, started, caller)
        return error.code, body


def _record(url: str, payload: dict[str, Any], status: int, response: Any, started: float, caller: dict[str, str] | None) -> None:
    ports = {
        ":8000": ("business_engine", "intent-adapter"), ":8001": ("foundation", "permission-adapter"),
        ":8002": ("foundation", "model-dispatcher"), ":8010": ("business_engine", "rule-adapter"),
        ":8003": ("business_engine", "intent-analysis-engine-original"),
        ":8011": ("business_engine", "content-adapter"), ":8012": ("business_engine", "rule-calculation-engine-original"),
        ":8013": ("business_engine", "content-production-engine-original"), ":8021": ("business_engine", "workflow-execution-engine-original"),
        ":8036": ("business_engine", "document-table-parsing"),
        ":8030": ("business_engine", "analysis-prediction"), ":8031": ("business_engine", "data-operation"),
        ":8032": ("business_engine", "digital-asset"), ":8033": ("business_engine", "project-management"),
        ":8034": ("business_engine", "monitoring-reminder"), ":8037": ("business_engine", "external-system-integration"),
        ":8038": ("business_engine", "knowledge-qa"), ":8039": ("business_engine", "knowledge-map"),
        ":8035": ("business_engine", "multimedia-generation"),
        ":8020": ("business_engine", "workflow-execution"), ":8100": ("business_application", "application-gateway"),
        ":8200": ("business_engine", "engine-gateway"), ":8300": ("foundation", "foundation-gateway"),
        ":8400": ("foundation", "capability-registry"),
        ":8004": ("foundation", "template-management"),
        ":8059": ("foundation", "context-prompt-management"), ":8060": ("foundation", "foundation-data"),
        ":8050": ("foundation", "account-gateway"), ":8051": ("foundation", "security-compliance"),
        ":8052": ("foundation", "human-collaboration"), ":8053": ("foundation", "execution-sandbox"),
        ":8054": ("foundation", "evolution-mechanism"), ":8061": ("foundation", "control-mechanism"),
        ":8055": ("foundation", "knowledge-base"), ":8062": ("foundation", "memory-management"),
        ":8063": ("foundation", "device-system-interface"), ":8064": ("foundation", "cost-control"),
    }
    inferred_target = next(({"layer": layer, "module": module} for port, (layer, module) in ports.items() if port in url), {})
    source = caller or payload.get("source", {"layer": "external", "module": "http-client"})
    logical_target = payload.get("target", {})
    target = inferred_target or logical_target
    trace_id = str(payload.get("trace_id") or payload.get("envelope", {}).get("trace_id") or "untraced")
    capability = str(logical_target.get("capability") or payload.get("task_type") or payload.get("action") or "http.call")
    record_interface_call(
        trace_id=trace_id,
        source=source,
        target=target,
        capability=capability,
        method="POST",
        url=url,
        request=_compact_audit_payload(payload),
        response=_compact_audit_payload(response),
        status_code=status,
        duration_ms=(perf_counter() - started) * 1000,
    )


def _compact_audit_payload(value: Any, *, string_limit: int = 4000, list_limit: int = 20, depth: int = 0) -> Any:
    if depth > 8:
        return {"_truncated": True, "reason": "max_depth"}
    if isinstance(value, str):
        if len(value) <= string_limit:
            return value
        return {"_truncated": True, "size_chars": len(value), "preview": value[:string_limit]}
    if isinstance(value, list):
        return {
            "count": len(value),
            "sample": [_compact_audit_payload(item, string_limit=string_limit, list_limit=list_limit, depth=depth + 1) for item in value[:list_limit]],
            "truncated": len(value) > list_limit,
        }
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"workflow_prior_outputs", "conversation_context"}:
                compact[key_text] = _compact_audit_payload(item, string_limit=1200, list_limit=8, depth=depth + 1)
            elif key_text in {"items", "records", "rows", "fields", "chunks", "documents"} and isinstance(item, list):
                compact[f"{key_text}_count"] = len(item)
                compact[f"{key_text}_sample"] = [
                    _compact_audit_payload(row, string_limit=1200, list_limit=8, depth=depth + 1)
                    for row in item[: min(list_limit, 8)]
                ]
                compact[f"{key_text}_truncated"] = len(item) > min(list_limit, 8)
            else:
                compact[key_text] = _compact_audit_payload(item, string_limit=string_limit, list_limit=list_limit, depth=depth + 1)
        return compact
    return value
