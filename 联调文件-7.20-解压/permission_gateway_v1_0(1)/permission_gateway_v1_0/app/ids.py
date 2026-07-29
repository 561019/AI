from __future__ import annotations

import secrets
import time


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_base32(value: int, length: int) -> str:
    chars = ["0"] * length
    for index in range(length - 1, -1, -1):
        chars[index] = _CROCKFORD[value & 31]
        value >>= 5
    return "".join(chars)


def new_decision_id() -> str:
    timestamp_ms = int(time.time() * 1000)
    randomness = int.from_bytes(secrets.token_bytes(10), "big")
    return f"decision_{_encode_base32(timestamp_ms, 10)}{_encode_base32(randomness, 16)}"
