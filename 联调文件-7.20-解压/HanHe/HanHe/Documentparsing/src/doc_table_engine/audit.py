from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


class HashChainAuditLog:
    """追加式 JSONL 审计日志；事件包含前序哈希以便检测篡改。"""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, event_type: str, payload: dict[str, Any]) -> str:
        with self._lock:
            previous = self._last_hash()
            event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "event_type": event_type,
                "payload": payload,
                "previous_hash": previous,
            }
            canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            event["event_hash"] = event_hash
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            return event_hash

    def verify(self) -> bool:
        previous = "0" * 64
        if not self.path.exists():
            return True
        for line in self.path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            stored_hash = event.pop("event_hash")
            if event["previous_hash"] != previous:
                return False
            canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != stored_hash:
                return False
            previous = stored_hash
        return True

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "0" * 64
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1])["event_hash"]

