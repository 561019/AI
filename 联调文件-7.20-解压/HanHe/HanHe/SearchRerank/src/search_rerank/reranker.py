from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


class Reranker(Protocol):
    model: str

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankResult]: ...

    def close(self) -> None: ...


class SiliconFlowReranker:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        instruction: str,
        timeout_seconds: float,
        max_retries: int,
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key:
            raise ValueError("SiliconFlow API key is required")
        self.model = model
        self.instruction = instruction.strip()
        self.max_retries = max_retries
        self.endpoint = f"{base_url.rstrip('/')}/rerank"
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankResult]:
        if not query.strip() or not documents:
            return []
        if not 0 < top_n <= len(documents):
            raise ValueError("top_n must be between 1 and the number of documents")
        payload: dict[str, object] = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }
        if self.instruction:
            payload["instruction"] = self.instruction
        response = self._post_with_retry(payload)
        raw_results = response.json().get("results")
        if not isinstance(raw_results, list):
            raise RuntimeError("SiliconFlow rerank response does not contain results")
        results: list[RerankResult] = []
        seen: set[int] = set()
        for item in raw_results:
            try:
                index = int(item["index"])
                score = float(item["relevance_score"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("SiliconFlow returned an invalid rerank result") from exc
            if index < 0 or index >= len(documents) or index in seen:
                raise RuntimeError("SiliconFlow returned an invalid rerank document index")
            seen.add(index)
            results.append(RerankResult(index=index, score=score))
        return results

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
        raise RuntimeError("SiliconFlow rerank request did not produce a response")

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            try:
                return min(float(response.headers["Retry-After"]), 30.0)
            except (KeyError, ValueError):
                pass
        return min(2**attempt, 8)
