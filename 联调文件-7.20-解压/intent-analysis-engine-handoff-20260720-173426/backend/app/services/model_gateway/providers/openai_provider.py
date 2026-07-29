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


class OpenAIProvider(BaseLLMProvider):
    """OpenAI-compatible provider for future model replacement."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model_name: str = "gpt-4.1-mini",
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
            raise ModelGatewayConfigurationError("OpenAI API key is not configured.")

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0,
        }
        if response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "task_list",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}

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

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as error:
            raise ModelGatewayTimeoutError("OpenAI request timed out.") from error
        except httpx.HTTPStatusError as error:
            raise ModelGatewayServiceUnavailableError(
                f"OpenAI request failed: {error.response.status_code}",
            ) from error
        except httpx.TransportError as error:
            raise ModelGatewayServiceUnavailableError("OpenAI service unavailable.") from error
        except ValueError as error:
            raise ModelGatewayResponseError("OpenAI returned invalid JSON.") from error

        if not isinstance(data, dict):
            raise ModelGatewayResponseError("OpenAI returned a non-object response.")
        return data

    def _extract_content(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelGatewayResponseError("OpenAI response does not contain choices.")
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if content is None:
            raise ModelGatewayResponseError("OpenAI message does not contain content.")
        return str(content)

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content.strip())
        except json.JSONDecodeError as error:
            raise ModelGatewayResponseError("OpenAI content is not strict JSON.") from error
        if not isinstance(parsed, dict):
            raise ModelGatewayResponseError("OpenAI JSON content must be an object.")
        return parsed
