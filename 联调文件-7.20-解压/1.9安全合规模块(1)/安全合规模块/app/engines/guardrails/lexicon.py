"""Sensitive lexicon loader (simplified — no LLM Guard / NeMo).

Loads a categorized sensitive-word lexicon from JSON and converts each
category into a ``security_policy_rule``-shaped dictionary.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_LEXICON_CACHE: List[Dict[str, Any]] | None = None
_LEXICON_RAW_CACHE: dict | None = None


def _default_lexicon_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "sensitive_lexicon.json"


def load_lexicon_rules(path: Path | str | None = None, *, reload_: bool = False) -> List[Dict[str, Any]]:
    global _LEXICON_CACHE
    if _LEXICON_CACHE is not None and not reload_:
        return _LEXICON_CACHE

    lexicon_path = Path(path) if path else _default_lexicon_path()
    raw = _load_raw_lexicon(path, reload_=reload_)
    if raw is None:
        _LEXICON_CACHE = []
        return []

    rules: List[Dict[str, Any]] = []
    for cat in raw.get("categories", []):
        keywords = [kw.strip() for kw in cat.get("keywords", []) if kw and kw.strip()]
        if not keywords:
            continue
        rules.append({
            "rule_id": cat["rule_id"],
            "rule_name": cat.get("rule_name", cat["rule_id"]),
            "rule_type": cat.get("rule_type", "output_guard"),
            "risk_level": cat.get("risk_level", "high"),
            "enabled": cat.get("enabled", True),
            "condition_json": {"keywords": keywords},
            "obligation_json": {
                "need_output_check": True,
                "deny": True,
                "suggestion": cat.get("suggestion", f"内容涉及「{cat.get('rule_name', cat.get('rule_id'))}」相关违规表述。"),
            },
        })

    logger.info("Loaded %d sensitive lexicon rules from %s", len(rules), lexicon_path)
    _LEXICON_CACHE = rules
    return rules


def get_all_lexicon_keywords(path: Path | str | None = None) -> List[str]:
    rules = load_lexicon_rules(path)
    seen: set[str] = set()
    keywords: List[str] = []
    for rule in rules:
        for kw in rule.get("condition_json", {}).get("keywords", []):
            kw = kw.strip()
            if kw and kw not in seen:
                seen.add(kw)
                keywords.append(kw)
    return keywords


def get_category_descriptions(path: Path | str | None = None) -> list[dict[str, str]]:
    raw = _load_raw_lexicon(path)
    if raw is None:
        return []
    return [
        {"rule_id": cat.get("rule_id", ""), "rule_name": cat.get("rule_name", ""), "description": cat.get("description", "")}
        for cat in raw.get("categories", [])
        if cat.get("description")
    ]


def _load_raw_lexicon(path: Path | str | None = None, *, reload_: bool = False) -> dict | None:
    global _LEXICON_RAW_CACHE
    lexicon_path = Path(path) if path else _default_lexicon_path()
    if _LEXICON_RAW_CACHE is not None and not reload_:
        return _LEXICON_RAW_CACHE
    try:
        _LEXICON_RAW_CACHE = json.loads(lexicon_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Sensitive lexicon file not found: %s", lexicon_path)
        _LEXICON_RAW_CACHE = None
    except json.JSONDecodeError:
        logger.exception("Failed to parse sensitive lexicon: %s", lexicon_path)
        _LEXICON_RAW_CACHE = None
    return _LEXICON_RAW_CACHE


def clear_lexicon_cache() -> None:
    global _LEXICON_CACHE, _LEXICON_RAW_CACHE
    _LEXICON_CACHE = None
    _LEXICON_RAW_CACHE = None
