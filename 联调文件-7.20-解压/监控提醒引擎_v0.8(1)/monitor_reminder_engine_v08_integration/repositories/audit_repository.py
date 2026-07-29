from __future__ import annotations

from datetime import datetime
from typing import Any

from db import get_conn


def write_api_audit(
    *,
    request_id: str,
    trace_id: str,
    source_module: str,
    operator_id: str,
    request_method: str,
    request_path: str,
    response_code: int,
    business_status: str,
    error_message: str,
    permission_name: str,
    permission_mode: str,
    permission_allowed: int | None,
    permission_decision_id: str = "",
    security_audit_ref: str = "",
    duration_ms: int = 0,
    client_ip: str = "",
) -> int:
    conn = get_conn()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO api_request_record (
                request_id,
                trace_id,
                source_module,
                operator_id,
                request_method,
                request_path,
                response_code,
                business_status,
                error_message,
                permission_name,
                permission_mode,
                permission_allowed,
                permission_decision_id,
                security_audit_ref,
                duration_ms,
                client_ip,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                trace_id,
                source_module,
                operator_id,
                request_method,
                request_path,
                response_code,
                business_status,
                error_message,
                permission_name,
                permission_mode,
                permission_allowed,
                permission_decision_id,
                security_audit_ref,
                duration_ms,
                client_ip,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_api_audits(
    *,
    request_id: str = "",
    trace_id: str = "",
    source_module: str = "",
    response_code: int | None = None,
    permission_name: str = "",
    permission_allowed: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    conditions: list[str] = []
    params: list[Any] = []

    if request_id:
        conditions.append("request_id = ?")
        params.append(request_id)

    if trace_id:
        conditions.append("trace_id = ?")
        params.append(trace_id)

    if source_module:
        conditions.append("source_module = ?")
        params.append(source_module)

    if response_code is not None:
        conditions.append("response_code = ?")
        params.append(response_code)

    if permission_name:
        conditions.append("permission_name = ?")
        params.append(permission_name)

    if permission_allowed is not None:
        conditions.append("permission_allowed = ?")
        params.append(permission_allowed)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    conn = get_conn()

    try:
        cur = conn.cursor()

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM api_request_record
            {where_clause}
            """,
            params,
        )
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT *
            FROM api_request_record
            {where_clause}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )

        records = [dict(row) for row in cur.fetchall()]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "records": records,
        }
    finally:
        conn.close()
