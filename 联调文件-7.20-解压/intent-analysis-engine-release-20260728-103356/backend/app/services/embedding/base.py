from __future__ import annotations

from typing import Protocol, runtime_checkable


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot return vectors."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Provider interface for swappable embedding models."""

    model_name: str

    @property
    def dimension(self) -> int | None:
        """Return vector dimension when known."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
