from abc import ABC, abstractmethod
from typing import Any


class BaseModelGateway(ABC):
    """Unified model gateway contract for all AI model calls."""

    @abstractmethod
    def embedding(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for input texts."""

    @abstractmethod
    def rerank(self, query: str, candidates: list[str | dict]) -> list[dict[str, Any]]:
        """Return reranked candidates for a query."""

    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> str:
        """Return chat completion text."""
