import json
import logging

import httpx
import pytest

from app.services.model_gateway import (
    ModelComplexity,
    ModelGateway,
    ModelGatewayConfigurationError,
    ModelRouter,
)
from app.services.model_gateway.providers import DeepSeekProvider, MockProvider


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def tasklist_payload() -> dict:
    return {
        "tasks": [
            {
                "task_type": "DATA_ANALYSIS_PROBLEM",
                "task_description": "分析销售情况",
                "action": "分析",
                "object": "销售情况",
                "required_inputs": [],
                "missing_inputs": [],
                "dependencies": [],
            },
        ],
        "clarification_required": False,
        "clarification_questions": [],
    }


def test_deepseek_provider_uses_openai_compatible_chat_completion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "deepseek-chat"
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(tasklist_payload(), ensure_ascii=False)}},
                ],
            },
        )

    provider = DeepSeekProvider(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model_name="deepseek-chat",
        client=make_client(handler),
    )

    response = provider.analyze(
        messages=[{"role": "system", "content": "只输出JSON"}],
        response_schema={"type": "object"},
    )

    assert response.provider == "deepseek"
    assert response.model == "deepseek-chat"
    assert response.parsed_json["tasks"][0]["action"] == "分析"


def test_deepseek_provider_requires_api_key() -> None:
    provider = DeepSeekProvider(api_key="", client=make_client(lambda request: httpx.Response(200)))

    with pytest.raises(ModelGatewayConfigurationError):
        provider.analyze(messages=[{"role": "user", "content": "hi"}])


def test_mock_provider_returns_safe_tasklist_json() -> None:
    response = MockProvider().analyze(messages=[{"role": "user", "content": "hi"}])

    assert response.provider == "mock"
    assert response.fallback_used is True
    assert response.parsed_json["fallback"] is True
    assert response.parsed_json["provider"] == "mock"
    assert response.parsed_json["tasks"] == []
    assert response.parsed_json["clarification_required"] is True
    assert json.loads(response.content)["tasks"] == []


def test_model_gateway_switches_provider_without_business_code_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(tasklist_payload(), ensure_ascii=False)}},
                ],
            },
        )

    deepseek_gateway = ModelGateway(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model_name="deepseek-chat",
        client=make_client(handler),
    )
    mock_gateway = ModelGateway(provider="mock", model_name="mock-llm")

    assert deepseek_gateway.analyze([{"role": "user", "content": "分析销售"}]).provider == "deepseek"
    assert mock_gateway.analyze([{"role": "user", "content": "分析销售"}]).provider == "mock"


def test_model_gateway_default_timeout_is_120_seconds() -> None:
    gateway = ModelGateway(provider="mock", model_name="mock-llm")

    assert gateway.timeout == 120


def test_model_gateway_falls_back_to_mock_when_deepseek_fails() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("network down", request=request)

    gateway = ModelGateway(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model_name="deepseek-chat",
        client=make_client(handler),
        sleep=lambda seconds: None,
    )

    response = gateway.analyze([{"role": "user", "content": "分析销售"}])

    assert len(calls) == 4
    assert response.provider == "mock"
    assert response.fallback_used is True
    assert response.fallback_provider == "mock"
    assert response.retry_count == 3
    assert response.debug["provider"] == "mock"
    assert response.debug["model"] == "mock-llm"
    assert response.debug["fallback"] is True
    assert response.debug["fallback_provider"] == "mock"
    assert response.parsed_json["fallback"] is True
    assert response.parsed_json["provider"] == "mock"
    assert "ModelGatewayServiceUnavailableError" in (response.error or "")
    assert response.parsed_json["tasks"] == []


def test_model_gateway_retries_then_returns_primary_response() -> None:
    calls = []
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("temporary network down", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(tasklist_payload(), ensure_ascii=False)}},
                ],
            },
        )

    gateway = ModelGateway(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model_name="deepseek-chat",
        client=make_client(handler),
        sleep=sleeps.append,
    )

    response = gateway.analyze([{"role": "user", "content": "分析销售"}])

    assert len(calls) == 3
    assert sleeps == [2.0, 5.0]
    assert response.provider == "deepseek"
    assert response.retry_count == 2
    assert response.fallback_used is False
    assert response.error is None
    assert response.debug["provider"] == "deepseek"
    assert response.debug["model"] == "deepseek-chat"
    assert response.debug["retry_count"] == 2
    assert response.debug["fallback"] is False
    assert response.request_id
    assert response.elapsed_ms >= 0


def test_model_gateway_debug_logs_do_not_include_api_key(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    caplog.set_level(logging.DEBUG, logger="app.services.model_gateway.gateway")
    gateway = ModelGateway(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret-key-should-not-log",
        model_name="deepseek-chat",
        client=make_client(handler),
        sleep=lambda seconds: None,
    )

    response = gateway.analyze([{"role": "user", "content": "分析销售"}])

    assert response.fallback_used is True
    assert "secret-key-should-not-log" not in caplog.text
    assert "provider=deepseek" in caplog.text
    assert "model=deepseek-chat" in caplog.text
    assert "request_id=" in caplog.text
    assert "retry_count=3" in caplog.text
    assert "fallback=True" in caplog.text


def test_model_router_controls_llm_usage_by_complexity() -> None:
    router = ModelRouter()

    assert router.should_call_llm(complexity=ModelComplexity.LOW) is False
    assert router.should_call_llm(complexity="MEDIUM", semantic_confidence=0.8) is False
    assert router.should_call_llm(complexity="HIGH") is True
