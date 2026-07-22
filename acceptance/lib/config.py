from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def load_config(path: str | None) -> dict[str, Any] | None:
    configured = path or os.getenv("ACCEPTANCE_CONFIG")
    if not configured:
        return None
    config_path = Path(configured)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["_path"] = str(config_path)
    return data


def load_scenario(name: str) -> dict[str, Any]:
    path = ROOT / "acceptance" / "scenarios" / name
    return json.loads(path.read_text(encoding="utf-8"))


def token_from_env(config: dict[str, Any], key: str) -> str | None:
    env_name = config.get(key)
    return os.getenv(str(env_name)) if env_name else None
