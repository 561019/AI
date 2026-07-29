from __future__ import annotations

from typing import Any, Dict, Iterable, List
from app.engines.guardrails.base import ScannerResult


class PromptInjectionScanner:
    name = "prompt_injection_scanner"

    def __init__(self) -> None:
        self.keywords = [
            "忽略以上规则", "绕过权限", "不要审计", "不要记录",
            "不要管之前的", "别管", "泄露", "导出所有客户",
            "越过1.9", "禁用安全检查",
        ]

    def scan(self, *, input_text: str, output_text: str, stage: str) -> List[ScannerResult]:
        text = input_text or ""
        results = []
        for kw in self.keywords:
            if kw in text:
                results.append(ScannerResult(
                    scanner=self.name,
                    passed=False,
                    severity="critical",
                    risk_type="prompt_injection",
                    evidence=kw,
                    suggestion="拒绝执行，并要求用户按制度化路径重新发起请求。",
                    rule_id="builtin_prompt_injection",
                    rule_name="疑似提示词注入/越权请求",
                ))
        return results


class BannedWordsScanner:
    name = "banned_words_scanner"

    def __init__(self, rules: Iterable[Dict[str, Any]], custom_banned_words: list[str] | None = None) -> None:
        self.rules = [r for r in rules if r.get("enabled", True) and r.get("rule_type") in ("input_guard", "output_guard")]
        if custom_banned_words:
            self.rules = list(self.rules)
            self.rules.append({
                "rule_id": "custom_banned_words",
                "rule_name": "自定义违规词",
                "rule_type": "input_guard",
                "risk_level": "high",
                "enabled": True,
                "condition_json": {"keywords": [w.strip() for w in custom_banned_words if w.strip()]},
                "obligation_json": {"suggestion": "输入包含自定义违规词。"},
            })

    def scan(self, *, input_text: str, output_text: str, stage: str) -> List[ScannerResult]:
        if stage in ("after_model_output", "before_external_output", "before_action_execute"):
            text = f"{output_text or ''}\n{input_text or ''}"
        else:
            text = input_text or ""
        results: list[ScannerResult] = []
        for rule in self.rules:
            if stage in ("after_model_output", "before_external_output") and rule.get("rule_type") == "input_guard":
                continue
            keywords = rule.get("condition_json", {}).get("keywords", [])
            for kw in keywords:
                if kw and len(kw) >= 2 and kw in text:
                    level = rule.get("risk_level", "medium")
                    results.append(ScannerResult(
                        scanner=self.name,
                        passed=level not in ("high", "critical"),
                        severity=level,
                        risk_type="banned_word",
                        evidence=kw,
                        suggestion=rule.get("obligation_json", {}).get("suggestion") or "删除或替换命中的高风险表达。",
                        rule_id=rule.get("rule_id"),
                        rule_name=rule.get("rule_name"),
                    ))
        return results


class BusinessComplianceScanner:
    name = "business_compliance_scanner"

    def __init__(self) -> None:
        self.exaggerated_claims = ["最强", "第一", "永久有效", "彻底解决", "保证", "百分百", "100%", "根治"]

    def scan(self, *, input_text: str, output_text: str, stage: str) -> List[ScannerResult]:
        if stage not in ("after_model_output", "before_external_output", "before_action_execute"):
            return []
        text = f"{output_text or ''}\n{input_text or ''}"
        results = []
        for kw in self.exaggerated_claims:
            if kw in text:
                results.append(ScannerResult(
                    scanner=self.name,
                    passed=False,
                    severity="high",
                    risk_type="exaggerated_claim",
                    evidence=kw,
                    suggestion="将绝对化/保证性表述改为保守描述。",
                    rule_id="business_exaggerated_claim",
                    rule_name="业务宣传夸大表述检查",
                ))
        return results
