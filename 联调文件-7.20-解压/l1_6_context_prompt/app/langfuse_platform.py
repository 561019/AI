from __future__ import annotations

import json
import base64
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from typing import Any

from .audit import write_audit_event
from .config import get_langfuse_config, get_langfuse_credentials
from .db import connect, row_to_dict, rows_to_dicts
from .utils import ApiError, new_id, now_iso


LANGFUSE_PLATFORM = "langfuse"

def get_langfuse_status() -> dict[str, str | bool | None]:
    return get_langfuse_config()


def fetch_langfuse_prompt(name: str, label: str = "production") -> dict[str, Any]:
    credentials = get_langfuse_credentials()
    encoded_name = urllib.parse.quote(name, safe="")
    query = urllib.parse.urlencode({"label": label})
    url = f"{credentials['base_url']}/api/public/v2/prompts/{encoded_name}?{query}"
    token = base64.b64encode(
        f"{credentials['public_key']}:{credentials['secret_key']}".encode("utf-8")
    ).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(exc.code, "Langfuse prompt fetch failed", {"body": body, "prompt": name, "label": label}) from exc
    except urllib.error.URLError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Langfuse is unreachable", {"reason": str(exc.reason)}) from exc
    data = json.loads(raw)
    return {
        "platform": LANGFUSE_PLATFORM,
        "name": name,
        "label": label,
        "base_url": credentials["base_url"],
        "prompt": data,
    }


def bind_prompt_version_to_platform(prompt_version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    platform = payload.get("platform", LANGFUSE_PLATFORM)
    if platform != LANGFUSE_PLATFORM:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Only langfuse platform binding is supported in MVP")
    now = now_iso()
    item = {
        "id": new_id("ppb"),
        "prompt_version_id": prompt_version_id,
        "platform": platform,
        "platform_prompt_id": payload.get("platform_prompt_id"),
        "platform_prompt_name": payload.get("platform_prompt_name"),
        "platform_version": payload.get("platform_version"),
        "platform_url": payload.get("platform_url"),
        "sync_status": payload.get("sync_status", "local_only"),
        "metadata": json.dumps(payload.get("metadata", {}), ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO prompt_platform_binding (
              id, prompt_version_id, platform, platform_prompt_id, platform_prompt_name,
              platform_version, platform_url, sync_status, metadata, created_at, updated_at
            ) VALUES (
              :id, :prompt_version_id, :platform, :platform_prompt_id, :platform_prompt_name,
              :platform_version, :platform_url, :sync_status, :metadata, :created_at, :updated_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=payload.get("actor_id") or payload.get("created_by") or "system",
        action="langfuse.binding.create",
        resource_type="prompt_platform_binding",
        resource_id=item["id"],
        detail={"prompt_version_id": prompt_version_id, "platform": platform},
    )
    return _decode_binding(item)


def list_prompt_platform_bindings(prompt_version_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM prompt_platform_binding
            WHERE prompt_version_id = ?
            ORDER BY created_at DESC
            """,
            (prompt_version_id,),
        ).fetchall()
    return [_decode_binding(row) for row in rows_to_dicts(rows)]


def create_prompt_run_trace(payload: dict[str, Any]) -> dict[str, Any]:
    item = {
        "id": new_id("trace"),
        "platform": payload.get("platform", LANGFUSE_PLATFORM),
        "platform_trace_id": payload.get("platform_trace_id"),
        "prompt_version_id": payload.get("prompt_version_id"),
        "project_id": payload.get("project_id"),
        "session_id": payload.get("session_id"),
        "operation": payload["operation"],
        "input_json": json.dumps(payload.get("input", {}), ensure_ascii=False),
        "output_text": payload.get("output_text"),
        "status": payload.get("status", "success"),
        "score": payload.get("score"),
        "score_reason": payload.get("score_reason"),
        "latency_ms": payload.get("latency_ms"),
        "total_tokens": payload.get("total_tokens"),
        "cost_amount": payload.get("cost_amount"),
        "created_by": payload.get("created_by") or payload.get("actor_id") or "system",
        "created_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO prompt_run_trace (
              id, platform, platform_trace_id, prompt_version_id, project_id, session_id,
              operation, input_json, output_text, status, score, score_reason, latency_ms,
              total_tokens, cost_amount, created_by, created_at
            ) VALUES (
              :id, :platform, :platform_trace_id, :prompt_version_id, :project_id, :session_id,
              :operation, :input_json, :output_text, :status, :score, :score_reason, :latency_ms,
              :total_tokens, :cost_amount, :created_by, :created_at
            )
            """,
            item,
        )
    write_audit_event(
        actor_id=item["created_by"],
        action="langfuse.trace.create",
        resource_type="prompt_run_trace",
        resource_id=item["id"],
        scope_level="project",
        scope_id=item.get("project_id"),
    )
    return _decode_trace(item)


def score_prompt_run_trace(trace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    score = payload.get("score")
    if score is None:
        raise ApiError(HTTPStatus.BAD_REQUEST, "score is required")
    with connect() as conn:
        conn.execute(
            """
            UPDATE prompt_run_trace
            SET score = ?, score_reason = ?
            WHERE id = ?
            """,
            (float(score), payload.get("score_reason"), trace_id),
        )
    item = get_prompt_run_trace(trace_id)
    write_audit_event(
        actor_id=payload.get("actor_id") or "system",
        action="langfuse.trace.score",
        resource_type="prompt_run_trace",
        resource_id=trace_id,
        scope_level="project",
        scope_id=item.get("project_id"),
    )
    return item


def get_prompt_run_trace(trace_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM prompt_run_trace WHERE id = ?", (trace_id,)).fetchone()
    item = row_to_dict(row)
    if not item:
        raise ApiError(HTTPStatus.NOT_FOUND, "Prompt run trace not found")
    return _decode_trace(item)


def list_prompt_run_traces(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    project_id = _first(query, "project_id")
    session_id = _first(query, "session_id")
    operation = _first(query, "operation")
    clauses = ["1 = 1"]
    params: list[Any] = []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if operation:
        clauses.append("operation = ?")
        params.append(operation)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM prompt_run_trace WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 200",
            params,
        ).fetchall()
    return [_decode_trace(row) for row in rows_to_dicts(rows)]


def _decode_binding(item: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(item)
    decoded["metadata"] = json.loads(decoded.get("metadata") or "{}")
    return decoded


def _decode_trace(item: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(item)
    decoded["input"] = json.loads(decoded.pop("input_json") or "{}")
    return decoded


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


