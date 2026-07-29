from __future__ import annotations

import json
from pathlib import Path

from core.errors import BusinessError


class CapabilityRouter:
    def __init__(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "capability_registry.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        self.registry = {
            item["action"]: item
            for item in config["capabilities"]
            if item.get("enabled", True)
        }

    def validate(self, *, action: str, capability_id: str) -> None:
        item = self.registry.get(action)
        if item is None:
            raise BusinessError(
                "INVALID_CAPABILITY",
                f"未登记的项目管理能力：{action}",
                http_status=404,
            )
        if item["capability_id"] != capability_id:
            raise BusinessError(
                "CAPABILITY_MISMATCH",
                "action 与 capability_id 不匹配",
                http_status=400,
            )
