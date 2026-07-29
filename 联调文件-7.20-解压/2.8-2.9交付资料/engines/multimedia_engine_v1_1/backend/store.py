from __future__ import annotations

from pathlib import Path
from typing import Any
import json

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
        return json.loads(self.path.read_text(encoding="utf-8-sig"))

    def write(self, data: Any) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


tasks_store = JsonStore("integration_tasks.json", {})
