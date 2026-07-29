from __future__ import annotations

import json
from typing import Any

import httpx

from app.services.model_gateway.base import (
    BaseLLMProvider,
    ModelGatewayConfigurationError,
    ModelGatewayResponseError,
    ModelGatewayServiceUnavailableError,
    ModelGatewayTimeoutError,
)
from app.services.model_gateway.schemas.llm_response import LLMResponse


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek provider implemented through the OpenAI-compatible API."""

    provider_name = "deepseek"

    def __init__(
        self,
        *,
        base_url: str = "https://api.deepseek.com",
        api_key: str = "",
        model_name: str = "deepseek-chat",
        timeout: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout)

    def analyze(
        self,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise ModelGatewayConfigurationError("DeepSeek API key is not configured.")

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

        data = self._post_chat_completion(payload)
        content = self._extract_content(data)
        parsed = self._parse_json_content(content)
        return LLMResponse(
            provider=self.provider_name,
            model=self.model_name,
            content=content,
            parsed_json=parsed,
            raw_response=data,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as error:
            raise ModelGatewayTimeoutError("DeepSeek request timed out.") from error
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            if status_code in {502, 503, 504}:
                raise ModelGatewayServiceUnavailableError(
                    f"DeepSeek service unavailable: {status_code}",
                ) from error
            raise ModelGatewayServiceUnavailableError(
                f"DeepSeek request failed: {status_code}",
            ) from error
        except httpx.TransportError as error:
            raise ModelGatewayServiceUnavailableError("DeepSeek service unavailable.") from error
        except ValueError as error:
            raise ModelGatewayResponseError("DeepSeek returned invalid JSON.") from error

        if not isinstance(data, dict):
            raise ModelGatewayResponseError("DeepSeek returned a non-object response.")
        return data

    def _extract_content(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelGatewayResponseError("DeepSeek response does not contain choices.")
        first = choices[0]
        if not isinstance(first, dict):
            raise ModelGatewayResponseError("DeepSeek choice item is invalid.")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ModelGatewayResponseError("DeepSeek choice does not contain a message.")
        content = message.get("content")
        if content is None:
            raise ModelGatewayResponseError("DeepSeek message does not contain content.")
        return str(content)

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(self._strip_markdown_fence(content))
        except json.JSONDecodeError as error:
            raise ModelGatewayResponseError("DeepSeek content is not strict JSON.") from error
        if not isinstance(parsed, dict):
            raise ModelGatewayResponseError("DeepSeek JSON content must be an object.")
        return parsed

    def _strip_markdown_fence(self, content: str) -> str:
        text = content.strip()
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
