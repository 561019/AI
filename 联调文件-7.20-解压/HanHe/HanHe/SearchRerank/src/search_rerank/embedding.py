from __future__ import annotations

import time
from typing import Protocol

import httpx


class QueryEmbedder(Protocol):
    model: str
    dimensions: int

    def embed_query(self, query: str) -> list[float]: ...

    def close(self) -> None: ...


class SiliconFlowQueryEmbedder:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: float,
        max_retries: int,
        query_instruction: str,
        transport: httpx.BaseTransport | None = None,
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
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def embed_query(self, query: str) -> list[float]:
        query = query.strip()
        if not query:
            raise ValueError("query cannot be empty")
        text = f"Instruct: {self.query_instruction}\nQuery: {query}" if self.query_instruction else query
        payload = {
            "model": self.model,
            "input": [text],
            "encoding_format": "float",
            "dimensions": self.dimensions,
        }
        response = self._post_with_retry(payload)
        data = response.json().get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise RuntimeError("SiliconFlow returned an unexpected number of query embeddings")
        vector = data[0].get("embedding")
        if not isinstance(vector, list) or len(vector) != self.dimensions:
            actual = len(vector) if isinstance(vector, list) else "invalid"
            raise RuntimeError(f"embedding dimension mismatch: expected {self.dimensions}, got {actual}")
        return [float(value) for value in vector]

    def _post_with_retry(self, payload: dict[str, object]) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(self.endpoint, json=payload)
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                retryable = response is None or response.status_code in {408, 409, 429} or response.status_code >= 500
                if attempt >= self.max_retries or not retryable:
                    raise
                time.sleep(self._retry_delay(response, attempt))
        raise RuntimeError("SiliconFlow embedding request did not produce a response")

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            try:
                return min(float(response.headers["Retry-After"]), 30.0)
            except (KeyError, ValueError):
                pass
        return min(2**attempt, 8)
