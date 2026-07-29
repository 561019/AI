import httpx
import pytest

from app.integrations.models.model_gateway import (
    ModelGateway,
    ModelGatewayError,
    ModelGatewayResponseError,
    ModelGatewayServiceUnavailableError,
    ModelGatewayTimeoutError,
)


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_model_gateway_embedding_openai_compatible_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = request.read().decode()
        assert "embedding-test" in payload
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ],
            },
        )

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        api_key="test-key",
        embedding_model="embedding-test",
        embedding_dimension=2,
        client=make_client(handler),
    )

    assert gateway.embedding(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_model_gateway_embedding_uses_only_openai_compatible_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [1, 2, 3]},
                ],
            },
        )

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        embedding_model="bge-m3",
        embedding_dimension=3,
        client=make_client(handler),
    )

    assert gateway.embedding(["local text"]) == [[1.0, 2.0, 3.0]]


def test_model_gateway_rerank_results_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/rerank"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.55},
                ],
            },
        )

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        rerank_model="rerank-test",
        client=make_client(handler),
    )

    result = gateway.rerank("query", ["first", "second"])

    assert result == [
        {"index": 1, "candidate": "second", "score": 0.91},
        {"index": 0, "candidate": "first", "score": 0.55},
    ]


def test_model_gateway_rerank_scores_response() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/rerank":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"scores": [0.3, 0.8]})

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        client=make_client(handler),
    )

    result = gateway.rerank("query", [{"text": "a"}, {"text": "b"}])

    assert result[0]["candidate"] == {"text": "b"}
    assert result[0]["score"] == 0.8
    assert calls == ["/v1/rerank", "/v1/v1/rerank"]


def test_model_gateway_chat_openai_compatible_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "hello"}},
                ],
            },
        )

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        llm_model="chat-test",
        client=make_client(handler),
    )

    assert gateway.chat([{"role": "user", "content": "hi"}]) == "hello"


def test_model_gateway_chat_local_response() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"response": "local hello"})

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        client=make_client(handler),
    )

    assert gateway.chat([{"role": "user", "content": "hi"}]) == "local hello"
    assert calls == ["/v1/chat/completions", "/v1/chat"]


def test_model_gateway_raises_on_invalid_embedding_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": []})

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayResponseError):
        gateway.embedding(["bad"])


def test_model_gateway_embedding_raises_on_service_unavailable_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayServiceUnavailableError, match="503"):
        gateway.embedding(["hello"])


def test_model_gateway_embedding_raises_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayServiceUnavailableError):
        gateway.embedding(["hello"])


def test_model_gateway_embedding_raises_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayTimeoutError):
        gateway.embedding(["hello"])


def test_model_gateway_embedding_raises_on_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayResponseError, match="invalid JSON"):
        gateway.embedding(["hello"])


def test_model_gateway_embedding_raises_on_count_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2]},
                ],
            },
        )

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        embedding_dimension=2,
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayResponseError, match="count mismatch"):
        gateway.embedding(["a", "b"])


def test_model_gateway_embedding_raises_on_dimension_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2]},
                ],
            },
        )

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        embedding_dimension=3,
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayResponseError, match="dimension mismatch"):
        gateway.embedding(["hello"])


def test_model_gateway_embedding_raises_on_non_numeric_vector_item() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, "bad"]},
                ],
            },
        )

    gateway = ModelGateway(
        api_url="http://model.local/v1",
        embedding_dimension=2,
        client=make_client(handler),
    )

    with pytest.raises(ModelGatewayResponseError, match="non-numeric"):
        gateway.embedding(["hello"])
