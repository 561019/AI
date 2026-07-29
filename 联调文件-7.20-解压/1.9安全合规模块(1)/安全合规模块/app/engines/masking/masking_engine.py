from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from app.engines.masking.base import RecognizerFinding
from app.engines.masking.operators import MaskingOperator
from app.engines.masking.recognizers import BusinessKeywordRecognizer, PresidioAdapterRecognizer, RegexRecognizer
from app.repositories.json_store import JsonStore


@dataclass
class ProductizedMaskingResult:
    need_masking: bool
    masked_payload: Dict[str, str] = field(default_factory=dict)
    hit_rules: List[Dict[str, Any]] = field(default_factory=list)
    masking_fields: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)


class ProductizedMaskingEngine:
    """Recognizer + Operator 架构的脱敏引擎。"""

    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self.operator = MaskingOperator()

    def mask(self, input_text: str = "", output_text: str = "") -> ProductizedMaskingResult:
        masked_input, input_findings = self._mask_text(input_text)
        masked_output, output_findings = self._mask_text(output_text)
        all_findings = input_findings + output_findings
        hit_rules = self._findings_to_hit_rules(all_findings)
        fields = sorted({f.entity_type.lower() for f in all_findings})
        return ProductizedMaskingResult(
            need_masking=bool(all_findings),
            masked_payload={"input_text": masked_input, "output_text": masked_output},
            hit_rules=hit_rules,
            masking_fields=fields,
            findings=[f.to_dict() for f in all_findings],
        )

    def _mask_text(self, text: str) -> tuple[str, list[RecognizerFinding]]:
        if not text:
            return text, []
        recognizers = [
            RegexRecognizer(),
            BusinessKeywordRecognizer(self.store.list("security_policy_rule")),
            PresidioAdapterRecognizer(),
        ]
        findings: list[RecognizerFinding] = []
        for recognizer in recognizers:
            findings.extend(recognizer.analyze(text))
        findings = self._deduplicate(findings)
        return self.operator.apply(text, findings), findings

    def _deduplicate(self, findings: list[RecognizerFinding]) -> list[RecognizerFinding]:
        sorted_findings = sorted(findings, key=lambda f: (f.start, -(f.end - f.start), -f.score))
        accepted: list[RecognizerFinding] = []
        for f in sorted_findings:
            overlaps = any(not (f.end <= a.start or f.start >= a.end) for a in accepted)
            if not overlaps:
                accepted.append(f)
        return sorted(accepted, key=lambda f: f.start)

    def _findings_to_hit_rules(self, findings: list[RecognizerFinding]) -> list[dict[str, Any]]:
        rules = []
        seen = set()
        for f in findings:
            rule_id = f.metadata.get("rule_id") or f"mask_{f.entity_type.lower()}"
            if rule_id in seen:
                continue
            seen.add(rule_id)
            rules.append({
                "rule_id": rule_id,
                "rule_name": f.metadata.get("rule_name") or f"敏感信息识别：{f.entity_type}",
                "risk_level": f.metadata.get("risk_level", "medium"),
                "reason": f"{f.source} 命中 {f.entity_type}",
                "field": f.entity_type.lower(),
            })
        return rules
