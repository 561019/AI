from __future__ import annotations

import time
from typing import Protocol

import httpx


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, query: str) -> list[float]: ...


class SiliconFlowEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        model: str = "Qwen/Qwen3-Embedding-8B",
        dimensions: int = 1024,
        timeout_seconds: float = 120,
        max_retries: int = 3,
        query_instruction: str = "Given a user query, retrieve relevant document passages that answer it",
    ):
        if not api_key:
            raise ValueError("SiliconFlow API key is required")
        self.model = model
        self.dimensions = dimensions
        self.max_retries = max_retries
        self.query_instruction = query_instruction.strip()
        self.endpoint = f"{base_url.rstrip('/')}/embeddings"
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        self.client.close()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, query: str) -> list[float]:
        query = query.strip()
        if not query:
            raise ValueError("query cannot be empty")
        text = f"Instruct: {self.query_instruction}\nQuery: {query}" if self.query_instruction else query
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding inputs must contain non-empty text")
        payload = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
            "dimensions": self.dimensions,
        }
        response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(self.endpoint, json=payload)
                if response.status_code not in {408, 409, 429} and response.status_code < 500:
                    response.raise_for_status()
                    break
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt >= self.max_retries:
                    raise
                retry_after = self._retry_after(response)
                time.sleep(retry_after if retry_after is not None else min(2**attempt, 8))
        if response is None:
            raise RuntimeError("SiliconFlow embedding request did not produce a response")
        body = response.json()
        data = body.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise RuntimeError("SiliconFlow returned an unexpected number of embeddings")
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                actual = len(vector) if isinstance(vector, list) else "invalid"
                raise RuntimeError(f"embedding dimension mismatch: expected {self.dimensions}, got {actual}")
            vectors.append([float(value) for value in vector])
        return vectors

    @staticmethod
    def _retry_after(response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        try:
            return min(float(value), 30.0) if value is not None else None
        except ValueError:
            return None

