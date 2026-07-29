from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "capability_manifest.json"
)


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_capability(
    capability_id: str,
    action: str,
) -> dict[str, Any] | None:
    manifest = load_manifest()
    for capability in manifest.get("capabilities", []):
        if (
            capability.get("capability_id") == capability_id
            and capability.get("action") == action
        ):
            return capability
    return None


def list_capabilities() -> list[dict[str, Any]]:
    return list(load_manifest().get("capabilities", []))
