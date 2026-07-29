from dataclasses import dataclass, field
from typing import Dict, List

from app.core.config import get_settings
from app.engines.guardrails.pipeline import GuardrailPipeline
from app.repositories.json_store import JsonStore
from app.services.context_builder import RuntimeContext


@dataclass
class IOComplianceResult:
    passed: bool = True
    risk_level: str = "low"
    need_output_check: bool = False
    hit_rules: List[Dict] = field(default_factory=list)
    scanner_results: List[Dict] = field(default_factory=list)


class IOComplianceGuard:
    """输入输出合规护栏 —— 简化版，仅 in_house 后端。"""

    def __init__(self, store: JsonStore) -> None:
        settings = get_settings()
        custom_words = settings.llm_guard_custom_banned_list
        self.pipeline = GuardrailPipeline(store, custom_banned_words=custom_words)

    def check(self, ctx: RuntimeContext) -> IOComplianceResult:
        result = self.pipeline.run(
            input_text=ctx.input_text or "",
            output_text="",
            stage="before_model_call",
        )
        return IOComplianceResult(
            passed=result.passed,
            risk_level=result.risk_level,
            need_output_check=result.need_output_check,
            hit_rules=result.hit_rules,
            scanner_results=result.scanner_results,
        )
