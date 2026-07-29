from __future__ import annotations

from typing import Any

from app.services.model_gateway.base import BaseLLMProvider
from app.services.model_gateway.schemas.llm_response import LLMResponse


class MockProvider(BaseLLMProvider):
    """Safe fallback provider that keeps the interface available without external calls."""

    provider_name = "mock"

    def __init__(
        self,
        *,
        model_name: str = "mock-llm",
        response: dict[str, Any] | None = None,
    ) -> None:
        self.model_name = model_name
        default_response = {
            "tasks": [],
            "clarification_required": True,
            "clarification_questions": ["当前大模型服务不可用，请补充更明确的任务信息或稍后重试。"],
        }
        self.response = {
            **(response or default_response),
            "fallback": True,
            "provider": self.provider_name,
        }

    def analyze(
        self,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        content = self._to_json(self.response)
        return LLMResponse(
            provider=self.provider_name,
            model=self.model_name,
            content=content,
            parsed_json=dict(self.response),
            raw_response={
                "mock": True,
                "fallback": True,
                "provider": self.provider_name,
                "messages_count": len(messages),
            },
            fallback_used=True,
            fallback_provider=self.provider_name,
        )

    def _to_json(self, payload: dict[str, Any]) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False)
