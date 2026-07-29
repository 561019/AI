"""Guardrail scanner pipeline (in_house backend only for standalone module)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.engines.guardrails.base import ScannerResult
from app.engines.guardrails.scanners import BannedWordsScanner, BusinessComplianceScanner, PromptInjectionScanner
from app.repositories.json_store import JsonStore

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass
class GuardrailPipelineResult:
    passed: bool = True
    risk_level: str = "low"
    need_output_check: bool = False
    scanner_results: List[Dict[str, Any]] = field(default_factory=list)
    hit_rules: List[Dict[str, Any]] = field(default_factory=list)


class GuardrailPipeline:
    """In-house scanner pipeline for the standalone security check module."""

    def __init__(self, store: JsonStore, custom_banned_words: list[str] | None = None) -> None:
        self.store = store
        self.custom_banned_words = custom_banned_words or []

    def _build_scanners(self) -> list:
        rules = list(self.store.list("security_policy_rule"))

        from app.engines.guardrails.lexicon import clear_lexicon_cache, load_lexicon_rules
        clear_lexicon_cache()
        lexicon_rules = load_lexicon_rules()
        if lexicon_rules:
            rules = rules + lexicon_rules
            logger.info("Merged %d lexicon rules — total rules now %d", len(lexicon_rules), len(rules))
        else:
            logger.warning("Sensitive lexicon is EMPTY — no lexicon keywords will be checked!")

        return [
            PromptInjectionScanner(),
            BannedWordsScanner(rules, custom_banned_words=self.custom_banned_words),
            BusinessComplianceScanner(),
        ]

    def run(self, *, input_text: str, output_text: str, stage: str) -> GuardrailPipelineResult:
        scanners = self._build_scanners()
        raw: list[ScannerResult] = []
        for scanner in scanners:
            raw.extend(scanner.scan(input_text=input_text, output_text=output_text, stage=stage))

        result = GuardrailPipelineResult()
        for item in raw:
            result.scanner_results.append({
                "scanner": item.scanner,
                "passed": item.passed,
                "severity": item.severity,
                "risk_type": item.risk_type,
                "evidence": item.evidence,
                "suggestion": item.suggestion,
                "rule_id": item.rule_id,
                "rule_name": item.rule_name,
            })
            result.hit_rules.append(item.to_hit_rule())
            result.need_output_check = True
            if not item.passed:
                result.passed = False
            if SEVERITY_ORDER.get(item.severity, 0) > SEVERITY_ORDER.get(result.risk_level, 0):
                result.risk_level = item.severity
        return result
