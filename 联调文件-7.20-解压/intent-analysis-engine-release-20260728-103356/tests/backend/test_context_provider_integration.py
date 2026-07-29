import json

from app.services.context_provider import (
    ContextInput,
    ContextProviderClient,
    ContextProviderResponse,
    MockContextProvider,
)
from app.services.conversation_understanding import ConversationUnderstandingLayer
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer


def make_layer(context: ContextProviderResponse | dict | None = None) -> ConversationUnderstandingLayer:
    analyzer = StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )
    return ConversationUnderstandingLayer(
        analyzer,
        context_provider=MockContextProvider(default_context=context),
    )


def task_context(
    task_description: str,
    *,
    task_type: str,
    action: str,
    object_value: str,
) -> dict:
    return {
        "task_type": task_type,
        "task_description": task_description,
        "action": action,
        "object": object_value,
    }


def test_mock_context_provider_returns_three_context_scopes() -> None:
    provider = MockContextProvider(
        default_context={
            "conversation_context": [{"text": "上一轮"}],
            "project_context": [{"text": "当前项目"}],
            "user_project_context": [{"text": "历史项目"}],
        }
    )

    response = provider.get_context(
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert response.model_dump(mode="json") == {
        "conversation_context": [{"text": "上一轮"}],
        "project_context": [{"text": "当前项目"}],
        "user_project_context": [{"text": "历史项目"}],
    }
    assert provider.calls == [
        {
            "user_id": "user-001",
            "conversation_id": "conversation-001",
            "project_id": "project-001",
        }
    ]


def test_engine_calls_mock_external_context_module_and_consumes_context() -> None:
    analyzer = StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )
    external_context = {
        "conversation_context": [
            {
                "task_type": "RULE_CALCULATION_COMMISSION",
                "task_description": "计算销售提成",
                "source_text": "计算2025年销售提成",
                "action": "计算",
                "object": "销售提成",
            }
        ],
        "project_context": [],
        "user_project_context": [],
    }
    mock_external_module = MockContextProvider(
        contexts={
            ("user-001", "conversation-001", "project-001"): external_context,
        }
    )
    layer = ConversationUnderstandingLayer(
        analyzer,
        context_provider=ContextProviderClient(provider=mock_external_module),
    )

    analysis = layer.analyze_with_debug(
        text="帮我再算一遍",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert mock_external_module.calls == [
        {
            "user_id": "user-001",
            "conversation_id": "conversation-001",
            "project_id": "project-001",
        }
    ]
    assert analysis.debug["external_context"] == {
        "enabled": True,
        "project_id": "project-001",
        "error": None,
        "context": external_context,
        "history_context_items": [],
    }
    assert analysis.debug["context_resolution"]["resolved"] is True
    assert analysis.debug["context_resolution"]["resolved_text"] == "重新计算2025年销售提成"
    assert analysis.debug["context_resolution"]["scope"] == "conversation"
    assert analysis.debug["contextual_input"] == {
        "user_input": "重新计算2025年销售提成",
        "context": {
            "current_conversation": {"items": external_context["conversation_context"]},
            "current_project": {"items": []},
            "historical_projects": {"items": []},
        },
    }
    assert analysis.result.tasks[0].task_type == "RULE_CALCULATION_COMMISSION"


def test_context_resolves_repeat_sales_commission_calculation() -> None:
    first = make_layer().analyze(
        text="计算2025年销售提成",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )
    first_task_context = first.tasks[0].model_dump(mode="json")
    first_task_context["source_text"] = "计算2025年销售提成"
    layer = make_layer(
        ContextProviderResponse(
            conversation_context=[first_task_context],
        )
    )

    analysis = layer.analyze_with_debug(
        text="帮我再算一遍",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert analysis.result.tasks[0].task_type == "RULE_CALCULATION_COMMISSION"
    assert analysis.result.tasks[0].action == "计算"
    assert "重新计算2025年销售提成" in analysis.debug["context_resolution"]["resolved_text"]
    assert analysis.debug["context_resolution"]["scope"] == "conversation"


def test_context_resolves_continue_edit_to_previous_report_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                task_context(
                    "生成经营分析报告",
                    task_type="DOCUMENT_GENERATE",
                    action="生成",
                    object_value="经营分析报告",
                )
            ],
        }
    )

    analysis = layer.analyze_with_debug(
        text="接着改",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert analysis.result.tasks[0].task_type == "DOCUMENT_GENERATE"
    assert analysis.debug["context_resolution"]["resolved_text"] == "生成经营分析报告修改稿"
    assert analysis.debug["context_resolution"]["scope"] == "conversation"


def test_context_resolves_dimension_change_to_previous_analysis_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                task_context(
                    "分析销售趋势",
                    task_type="DATA_ANALYSIS_PROBLEM",
                    action="分析",
                    object_value="销售趋势",
                )
            ],
        }
    )

    analysis = layer.analyze_with_debug(
        text="换个维度看看",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert analysis.result.tasks[0].task_type == "DATA_ANALYSIS_PROBLEM"
    assert analysis.debug["context_resolution"]["resolved_text"] == "换个维度分析销售趋势"


def test_context_resolves_recalculate_to_previous_calculation_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                task_context(
                    "计算销售提成",
                    task_type="RULE_CALCULATION_COMMISSION",
                    action="计算",
                    object_value="销售提成",
                )
            ],
        }
    )

    analysis = layer.analyze_with_debug(
        text="重新计算",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert analysis.result.tasks[0].task_type == "RULE_CALCULATION_COMMISSION"
    assert analysis.debug["context_resolution"]["resolved_text"] == "重新计算销售提成"


def test_context_priority_prefers_conversation_over_project_and_history() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                task_context(
                    "计算华东销售提成",
                    task_type="RULE_CALCULATION_COMMISSION",
                    action="计算",
                    object_value="华东销售提成",
                )
            ],
            "project_context": [
                task_context(
                    "计算全国销售提成",
                    task_type="RULE_CALCULATION_COMMISSION",
                    action="计算",
                    object_value="全国销售提成",
                )
            ],
            "user_project_context": [
                task_context(
                    "计算历史项目销售提成",
                    task_type="RULE_CALCULATION_COMMISSION",
                    action="计算",
                    object_value="历史项目销售提成",
                )
            ],
        }
    )

    analysis = layer.analyze_with_debug(
        text="重新计算",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert analysis.debug["context_resolution"]["scope"] == "conversation"
    assert analysis.debug["context_resolution"]["resolved_text"] == "重新计算华东销售提成"


def test_omitted_expression_requires_clarification_when_context_is_insufficient() -> None:
    result = make_layer().analyze(
        text="重新计算",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert result.tasks == []
    assert result.clarification_required is True
    assert result.clarification_questions == ["请明确要继续处理的上一轮任务或业务对象。"]


def test_contextual_input_format_is_exposed_in_debug() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                task_context(
                    "分析销售趋势",
                    task_type="DATA_ANALYSIS_PROBLEM",
                    action="分析",
                    object_value="销售趋势",
                )
            ],
        }
    )

    analysis = layer.analyze_with_debug(
        text="换个维度看看",
        user_id="user-001",
        conversation_id="conversation-001",
        project_id="project-001",
    )

    assert analysis.debug["contextual_input"] == {
        "user_input": "换个维度分析销售趋势",
        "context": {
            "current_conversation": {
                "items": [
                    {
                        "task_type": "DATA_ANALYSIS_PROBLEM",
                        "task_description": "分析销售趋势",
                        "action": "分析",
                        "object": "销售趋势",
                    }
                ]
            },
            "current_project": {"items": []},
            "historical_projects": {"items": []},
        },
    }


def test_llm_prompt_includes_context_field() -> None:
    captured_messages = []

    class FakeGateway:
        def analyze(self, messages, response_schema=None):
            captured_messages.extend(messages)

            class Response:
                content = json.dumps(
                    {
                        "result": {
                            "tasks": [],
                            "clarification_required": True,
                            "clarification_questions": ["请明确要处理的具体任务。"],
                        },
                        "evidence_spans": [],
                    },
                    ensure_ascii=False,
                )

            return Response()

    context = ContextInput(
        current_conversation={
            "items": [
                task_context(
                    "计算2025年销售提成",
                    task_type="RULE_CALCULATION_COMMISSION",
                    action="计算",
                    object_value="销售提成",
                )
            ]
        }
    )

    LLMTaskAnalyzer(
        model_gateway=FakeGateway(),
        registry=FunctionRegistryCatalog(),
    ).analyze_with_validation("帮我再算一遍", user_id="user-001", context=context)

    prompt = captured_messages[0]["content"]
    assert "Context:" in prompt
    assert "current_conversation" in prompt
    assert "计算2025年销售提成" in prompt
