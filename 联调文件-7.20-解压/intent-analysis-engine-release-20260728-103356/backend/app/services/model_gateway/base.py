from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.model_gateway.schemas.llm_response import LLMResponse


class ModelGatewayError(RuntimeError):
    """Base error raised by the model gateway layer."""


class ModelGatewayConfigurationError(ModelGatewayError):
    """Raised when a provider is missing required configuration."""


class ModelGatewayServiceUnavailableError(ModelGatewayError):
    """Raised when a provider cannot be reached or is unavailable."""


class ModelGatewayTimeoutError(ModelGatewayError):
    """Raised when a provider call times out."""


class ModelGatewayResponseError(ModelGatewayError):
    """Raised when a provider returns malformed or non-JSON content."""


class BaseLLMProvider(ABC):
    """Unified contract for all large-language-model providers.

    Business code must depend on ModelGateway instead of concrete providers.
    New providers only need to implement this interface.
    """

    provider_name: str

    @abstractmethod
    def analyze(
        self,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Analyze messages and return a strict JSON response."""
