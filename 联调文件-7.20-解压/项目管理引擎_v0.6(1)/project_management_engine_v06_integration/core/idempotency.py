from __future__ import annotations

import hashlib
import json

from core.errors import BusinessError


def stable_request_hash(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_cached_reply(repository, *, idempotency_key: str, action: str, payload: dict) -> dict | None:
    existing = repository.get_idempotency(idempotency_key)
    if existing is None:
        return None

    request_hash = stable_request_hash(payload)
    if existing["action"] != action or existing["request_hash"] != request_hash:
        raise BusinessError(
            "IDEMPOTENCY_CONFLICT",
            "相同幂等键对应了不同请求",
            http_status=409,
        )
    return json.loads(existing["reply_json"])


def save_reply(repository, *, idempotency_key: str, action: str, payload: dict, reply: dict) -> None:
    repository.save_idempotency(
        idempotency_key=idempotency_key,
        action=action,
        request_hash=stable_request_hash(payload),
        reply=reply,
    )
