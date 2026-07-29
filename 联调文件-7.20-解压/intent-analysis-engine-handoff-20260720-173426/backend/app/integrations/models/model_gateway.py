from typing import Any

import httpx

from app.core.config import settings
from app.integrations.models.base import BaseModelGateway


class ModelGatewayError(RuntimeError):
    """Raised when the model gateway cannot complete a model call."""


class ModelGatewayServiceUnavailableError(ModelGatewayError):
    """Raised when the model service cannot be reached or is unavailable."""


class ModelGatewayTimeoutError(ModelGatewayError):
    """Raised when the model service times out."""


class ModelGatewayResponseError(ModelGatewayError):
    """Raised when the model service returns an invalid payload."""


class ModelGateway(BaseModelGateway):
    """HTTP model gateway for OpenAI-compatible and local model services."""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
        rerank_model: str | None = None,
        llm_model: str | None = None,
        timeout: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_url = (api_url or settings.model_api_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.model_api_key
        self.embedding_model = embedding_model or settings.embedding_model
        self.embedding_dimension = embedding_dimension or settings.embedding_dimension
        self.rerank_model = rerank_model or settings.rerank_model
        self.llm_model = llm_model or settings.llm_model
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout)

    def embedding(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = {
            "model": self.embedding_model,
            "input": texts,
        }
        data = self._post("/embeddings", payload)
        return self._parse_embedding_response(data, expected_count=len(texts))

    def rerank(self, query: str, candidates: list[str | dict]) -> list[dict[str, Any]]:
        if not candidates:
            return []

        documents = [self._candidate_to_document(candidate) for candidate in candidates]
        payload = {
            "model": self.rerank_model,
            "query": query,
            "documents": documents,
        }
        data = self._post_with_fallback(["/rerank", "/v1/rerank"], payload)
        return self._parse_rerank_response(data, candidates)

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.llm_model,
            "messages": messages,
        }
        data = self._post_with_fallback(["/chat/completions", "/chat"], payload)
        return self._parse_chat_response(data)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post_with_fallback(self, endpoints: list[str], payload: dict) -> dict:
        last_error: Exception | None = None

        for endpoint in endpoints:
            try:
                return self._post(endpoint, payload)
            except ModelGatewayError as error:
                last_error = error

        raise ModelGatewayError(str(last_error) if last_error else "Model gateway call failed.")

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.api_url}{endpoint}"
        try:
            response = self.client.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as error:
            raise ModelGatewayTimeoutError(
                f"Model gateway request timed out: {endpoint}",
            ) from error
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            if status_code in {502, 503, 504}:
                raise ModelGatewayServiceUnavailableError(
                    f"Model service unavailable: {endpoint} returned {status_code}",
                ) from error
            raise ModelGatewayError(
                f"Model gateway request failed: {endpoint} returned {status_code}",
            ) from error
        except httpx.TransportError as error:
            raise ModelGatewayServiceUnavailableError(
                f"Model service unavailable: {endpoint}",
            ) from error
        except ValueError as error:
            raise ModelGatewayResponseError(
                f"Model gateway returned invalid JSON: {endpoint}",
            ) from error
        except Exception as error:
            raise ModelGatewayError(f"Model gateway request failed: {endpoint}") from error

        if not isinstance(data, dict):
            raise ModelGatewayResponseError(f"Model gateway returned invalid payload: {endpoint}")

        return data

    def _parse_embedding_response(self, data: dict, *, expected_count: int) -> list[list[float]]:
        raw_items = data.get("data")
        if not isinstance(raw_items, list):
            raise ModelGatewayResponseError("Embedding response does not contain data list.")

        embeddings: list[list[float]] = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict) or "embedding" not in item:
                raise ModelGatewayResponseError(
                    f"Embedding response item {index} does not contain embedding.",
                )
            embeddings.append(self._to_float_list(item["embedding"]))

        if len(embeddings) != expected_count:
            raise ModelGatewayResponseError(
                f"Embedding response count mismatch: expected {expected_count}, got {len(embeddings)}.",
            )

        for index, embedding in enumerate(embeddings):
            if self.embedding_dimension and len(embedding) != self.embedding_dimension:
                raise ModelGatewayResponseError(
                    "Embedding dimension mismatch: "
                    f"item {index} expected {self.embedding_dimension}, got {len(embedding)}.",
                )

        return embeddings

    def _parse_rerank_response(
        self,
        data: dict,
        candidates: list[str | dict],
    ) -> list[dict[str, Any]]:
        if "results" in data:
            ranked = []
            for item in data["results"]:
                index = int(item.get("index", item.get("document_index", 0)))
                score = float(item.get("relevance_score", item.get("score", 0)))
                ranked.append(
                    {
                        "index": index,
                        "candidate": candidates[index],
                        "score": score,
                    },
                )
            return sorted(ranked, key=lambda item: item["score"], reverse=True)

        if "scores" in data:
            ranked = [
                {
                    "index": index,
                    "candidate": candidates[index],
                    "score": float(score),
                }
                for index, score in enumerate(data["scores"])
            ]
            return sorted(ranked, key=lambda item: item["score"], reverse=True)

        raise ModelGatewayResponseError("Rerank response does not contain ranking results.")

    def _parse_chat_response(self, data: dict) -> str:
        if "choices" in data and data["choices"]:
            message = data["choices"][0].get("message", {})
            content = message.get("content")
            if content is not None:
                return str(content)

        if "message" in data:
            message = data["message"]
            if isinstance(message, dict):
                return str(message.get("content", ""))
            return str(message)

        if "response" in data:
            return str(data["response"])

        raise ModelGatewayResponseError("Chat response does not contain completion text.")

    def _candidate_to_document(self, candidate: str | dict) -> str:
        if isinstance(candidate, str):
            return candidate

        for key in ["text", "source_text", "description", "function_name"]:
            if candidate.get(key):
                return str(candidate[key])

        return str(candidate)

    def _to_float_list(self, values: list) -> list[float]:
        if not isinstance(values, list):
            raise ModelGatewayResponseError("Embedding value must be a list.")

        try:
            return [float(value) for value in values]
        except (TypeError, ValueError) as error:
            raise ModelGatewayResponseError("Embedding value contains non-numeric items.") from error
