from __future__ import annotations

import math

from app.services.embedding.base import EmbeddingProvider
from app.services.embedding.bge_provider import BGEProvider


class EmbeddingService:
    """Creates normalized embeddings through a swappable provider."""

    def __init__(self, *, provider: EmbeddingProvider | None = None, normalize: bool = True) -> None:
        self.provider = provider or BGEProvider()
        self.normalize = normalize

    @property
    def model_name(self) -> str:
        return self.provider.model_name

    @property
    def dimension(self) -> int | None:
        return self.provider.dimension

    def embed_query(self, text: str) -> list[float]:
        embeddings = self.embed_documents([text])
        return embeddings[0] if embeddings else []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.provider.embed(texts)
        if not self.normalize:
            return embeddings
        return [self._normalize(embedding) for embedding in embeddings]

    def _normalize(self, embedding: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in embedding))
        if norm == 0:
            return embedding
        return [value / norm for value in embedding]
