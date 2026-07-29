from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModelComplexity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class ModelRouteDecision:
    complexity: ModelComplexity
    use_llm: bool
    reason: str


class ModelRouter:
    """Controls when expensive LLM calls are allowed."""

    def route(self, *, complexity: ModelComplexity | str, semantic_confidence: float | None = None) -> ModelRouteDecision:
        raw_value = complexity.value if isinstance(complexity, ModelComplexity) else str(complexity)
        normalized = ModelComplexity(raw_value.upper())
        if normalized is ModelComplexity.LOW:
            return ModelRouteDecision(
                complexity=normalized,
                use_llm=False,
                reason="LOW complexity uses deterministic rules only.",
            )
        if normalized is ModelComplexity.MEDIUM:
            if semantic_confidence is not None and semantic_confidence >= 0.50:
                return ModelRouteDecision(
                    complexity=normalized,
                    use_llm=False,
                    reason="MEDIUM complexity is handled by BGE semantic matching.",
                )
            return ModelRouteDecision(
                complexity=normalized,
                use_llm=False,
                reason="MEDIUM complexity should try BGE before LLM.",
            )
        return ModelRouteDecision(
            complexity=normalized,
            use_llm=True,
            reason="HIGH complexity allows LLM task understanding.",
        )

    def should_call_llm(self, *, complexity: ModelComplexity | str, semantic_confidence: float | None = None) -> bool:
        return self.route(complexity=complexity, semantic_confidence=semantic_confidence).use_llm
