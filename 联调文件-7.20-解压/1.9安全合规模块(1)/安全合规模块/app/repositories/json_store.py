import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.core.config import get_settings


class JsonStore:
    """MVP 数据源 —— 简化版，仅用于 check 流程。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or get_settings().data_path
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def reload(self) -> None:
        self._data = self._load()

    def list(self, name: str) -> List[Dict[str, Any]]:
        return self._data.get(name, [])

    def get_one(self, name: str, key: str, value: Any) -> Optional[Dict[str, Any]]:
        for item in self.list(name):
            if item.get(key) == value:
                return item
        return None

    def find(self, name: str, **conditions: Any) -> List[Dict[str, Any]]:
        results = []
        for item in self.list(name):
            if all(item.get(k) == v for k, v in conditions.items()):
                results.append(item)
        return results
