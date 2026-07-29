from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


class JsonStore:
    def __init__(self, name: str, default: Any):
        self.path = DATA_DIR / name
        self.default = default
        if not self.path.exists():
            self.write(default)

    def read(self) -> Any:
        if not self.path.exists():
            return self.default.copy() if isinstance(self.default, dict) else list(self.default)
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, data: Any) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


tasks_store = JsonStore("tasks.json", {})
registry_store = JsonStore("registry.json", {})
audit_store = JsonStore("audit_logs.json", [])
