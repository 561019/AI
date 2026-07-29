from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "governance_policy_library.json"


@lru_cache(maxsize=1)
def load_policy_library() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _resolve(
    group: str,
    ref: str,
) -> dict[str, Any]:
    library = load_policy_library()
    for policy in library.get(group, []):
        if policy.get("rule_ref") == ref:
            return dict(policy)
    raise ValueError(f"治理制度引用不存在：{ref}")


def resolve_dnd_policy(ref: str | None) -> dict[str, Any]:
    return _resolve("dnd_policies", ref or "DND_NONE")


def resolve_escalation_policy(ref: str | None) -> dict[str, Any]:
    return _resolve("escalation_policies", ref or "ESC_NONE")
