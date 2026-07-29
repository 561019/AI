from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.services.model_gateway.base import BaseLLMProvider, ModelGatewayConfigurationError, ModelGatewayError
from app.services.model_gateway.providers import DeepSeekProvider, MockProvider, OpenAIProvider
from app.services.model_gateway.schemas.llm_response import LLMResponse

logger = logging.getLogger(__name__)


class ModelGateway:
    """Facade used by business code for all LLM calls."""

    DEFAULT_RETRY_BACKOFF_SECONDS = (2.0, 5.0, 10.0)

    def __init__(
        self,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout: float | None = None,
        primary_provider: BaseLLMProvider | None = None,
        fallback_provider: BaseLLMProvider | None = None,
        client: httpx.Client | None = None,
        retry_backoff_seconds: Sequence[float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.provider_name = (provider or settings.llm_provider).lower()
        self.base_url = base_url if base_url is not None else settings.llm_base_url
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model_name = model_name if model_name is not None else settings.llm_model
        self.timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        self.primary_provider = primary_provider or self._build_provider(
            self.provider_name,
            base_url=self.base_url,
            api_key=self.api_key,
            model_name=self.model_name,
            timeout=self.timeout,
            client=client,
        )
        self.fallback_provider = fallback_provider or MockProvider()
        self.retry_backoff_seconds = tuple(
            retry_backoff_seconds
            if retry_backoff_seconds is not None
            else self.DEFAULT_RETRY_BACKOFF_SECONDS
        )
        self.sleep = sleep or time.sleep
        self.last_error: str | None = None

    def analyze(
        self,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        request_id = str(uuid4())
        started_at = perf_counter()
        retry_count = 0
        last_error: str | None = None

        for attempt_index in range(len(self.retry_backoff_seconds) + 1):
            try:
                response = self.primary_provider.analyze(messages, response_schema)
                self.last_error = None
                return self._finalize_response(
                    response,
                    request_id=request_id,
                    started_at=started_at,
                    retry_count=retry_count,
                    fallback_used=False,
                    fallback_provider=None,
                    error=None,
                )
            except ModelGatewayConfigurationError as error:
                last_error = f"{type(error).__name__}: {error}"
                break
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                if attempt_index >= len(self.retry_backoff_seconds):
                    break
                delay = self.retry_backoff_seconds[attempt_index]
                retry_count += 1
                logger.debug(
                    "LLM provider attempt failed; provider=%s model=%s request_id=%s retry_count=%s next_delay_seconds=%s error_type=%s",
                    self._provider_name(self.primary_provider),
                    self._provider_model(self.primary_provider),
                    request_id,
                    retry_count,
                    delay,
                    type(error).__name__,
                )
                self.sleep(delay)

        self.last_error = last_error
        logger.warning(
            "LLM provider failed; falling back to mock provider. provider=%s model=%s request_id=%s retry_count=%s error=%s",
            self._provider_name(self.primary_provider),
            self._provider_model(self.primary_provider),
            request_id,
            retry_count,
            last_error,
        )
        fallback = self.fallback_provider.analyze(messages, response_schema)
        return self._finalize_response(
            fallback,
            request_id=request_id,
            started_at=started_at,
            retry_count=retry_count,
            fallback_used=True,
            fallback_provider=self._provider_name(self.fallback_provider),
            error=last_error,
        )

    def _finalize_response(
        self,
        response: LLMResponse,
        *,
        request_id: str,
        started_at: float,
        retry_count: int,
        fallback_used: bool,
        fallback_provider: str | None,
        error: str | None,
    ) -> LLMResponse:
        elapsed_ms = max(0, round((perf_counter() - started_at) * 1000))
        debug = {
            "provider": response.provider,
            "model": response.model,
            "request_id": request_id,
            "elapsed_ms": elapsed_ms,
            "retry_count": retry_count,
            "fallback": fallback_used,
            "fallback_provider": fallback_provider,
        }
        logger.debug(
            "LLM gateway response; provider=%s model=%s request_id=%s elapsed_ms=%s retry_count=%s fallback=%s fallback_provider=%s",
            debug["provider"],
            debug["model"],
            request_id,
            elapsed_ms,
            retry_count,
            fallback_used,
            fallback_provider,
        )
        return response.model_copy(
            update={
                "request_id": request_id,
                "elapsed_ms": elapsed_ms,
                "retry_count": retry_count,
                "fallback_used": fallback_used,
                "fallback_provider": fallback_provider,
                "error": error,
                "debug": debug,
            },
        )

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Compatibility method for older LLM analyzers."""

        return self.analyze(messages=messages, response_schema=None).content

    def _build_provider(
        self,
        provider: str,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout: float,
        client: httpx.Client | None,
    ) -> BaseLLMProvider:
        if provider == "deepseek":
            return DeepSeekProvider(
                base_url=base_url or "https://api.deepseek.com",
                api_key=api_key,
                model_name=model_name or "deepseek-chat",
                timeout=timeout,
                client=client,
            )
        if provider == "openai":
            return OpenAIProvider(
                base_url=base_url or "https://api.openai.com/v1",
                api_key=api_key,
                model_name=model_name or "gpt-4.1-mini",
                timeout=timeout,
                client=client,
            )
        if provider == "mock":
            return MockProvider(model_name=model_name or "mock-llm")
        raise ModelGatewayError(f"Unsupported LLM provider: {provider}")

    def _provider_name(self, provider: BaseLLMProvider) -> str:
        return str(getattr(provider, "provider_name", provider.__class__.__name__)).lower()

    def _provider_model(self, provider: BaseLLMProvider) -> str:
        return str(getattr(provider, "model_name", "unknown"))
