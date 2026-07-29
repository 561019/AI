from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from db import get_conn


def get_idempotency_record(
    idempotency_key: str,
) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT * FROM layer_idempotency_record
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def begin_idempotent_request(
    *,
    idempotency_key: str,
    request_hash: str,
    message_id: str,
    trace_id: str,
    action: str,
) -> tuple[str, dict[str, Any] | None]:
    existing = get_idempotency_record(idempotency_key)
    if existing:
        if existing["request_hash"] != request_hash:
            return "conflict", existing
        if existing["status"] == "completed":
            return "replay", existing
        return "processing", existing

    conn = get_conn()
    try:
        try:
            conn.execute(
                """
                INSERT INTO layer_idempotency_record (
                    idempotency_key, request_hash, message_id,
                    trace_id, action, status, response_code,
                    response_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    request_hash,
                    message_id,
                    trace_id,
                    action,
                    "processing",
                    0,
                    "",
                    datetime.now().isoformat(timespec="seconds"),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
            return "new", None
        except sqlite3.IntegrityError:
            existing = get_idempotency_record(idempotency_key)
            if existing and existing["request_hash"] == request_hash:
                return (
                    "replay"
                    if existing["status"] == "completed"
                    else "processing"
                ), existing
            return "conflict", existing
    finally:
        conn.close()


def complete_idempotent_request(
    *,
    idempotency_key: str,
    response_code: int,
    response_data: dict[str, Any],
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE layer_idempotency_record
            SET status = ?, response_code = ?, response_json = ?,
                updated_at = ?
            WHERE idempotency_key = ?
            """,
            (
                "completed",
                response_code,
                json.dumps(response_data, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
                idempotency_key,
            ),
        )
        conn.commit()
    finally:
        conn.close()
