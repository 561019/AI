from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def new_trace_id(prefix: str = "TRACE_PROJECT") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}_{uuid4().hex[:8].upper()}"
