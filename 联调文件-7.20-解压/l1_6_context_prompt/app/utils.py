from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def json_dumps(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ApiError(Exception):
    def __init__(self, status: int | HTTPStatus, message: str, details: Any = None):
        self.status = int(status)
        self.message = message
        self.details = details
        super().__init__(message)


def require_fields(payload: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if payload.get(field) in (None, "")]
    if missing:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Missing required fields", {"fields": missing})

