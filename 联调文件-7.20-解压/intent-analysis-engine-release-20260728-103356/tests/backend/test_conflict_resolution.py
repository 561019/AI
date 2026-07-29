from __future__ import annotations

from app.services.context_provider import MockContextProvider
from app.services.conversation_understanding import ConversationUnderstandingLayer
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer


def make_layer(context: dict) -> ConversationUnderstandingLayer:
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


def analyze(text: str, context: dict):
    return make_layer(context).analyze_with_debug(
        text=text,
        user_id="conflict-user",
        conversation_id="conflict-conversation",
        project_id="conflict-project",
    )


def conflict_payloads(analysis) -> list[dict]:
    return [
        conflict
        for task in analysis.result.tasks
        for conflict in task.conflicts
    ]


def conflict_types(analysis) -> list[str]:
    return [conflict["conflict_type"] for conflict in conflict_payloads(analysis)]


def test_data_source_conflict_requires_task_level_clarification() -> None:
    analysis = analyze(
        "使用ERP生成销售报表",
        {
            "conversation_context": [
                {
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成销售报表",
                    "source_text": "之前使用CRM生成销售报表",
                    "data_source": "CRM",
                }
            ],
            "project_context": [],
            "user_project_context": [],
        },
    )

    assert "DATA_SOURCE_CONFLICT" in conflict_types(analysis)
    task = analysis.result.tasks[0]
    assert task.status == "needs_clarification"
    assert task.clarification_required is True
    assert "conflict:DATA_SOURCE_CONFLICT" in task.missing_inputs
    assert any(
        conflict["resolution_status"] == "needs_clarification"
        for conflict in conflict_payloads(analysis)
        if conflict["conflict_type"] == "DATA_SOURCE_CONFLICT"
    )
    assert analysis.debug["conflict_resolution"]["has_blocking_conflict"] is True


def test_time_range_conflict_requires_clarification() -> None:
    analysis = analyze(
        "分析2026销售",
        {
            "conversation_context": [
                {
                    "task_type": "DATA_ANALYSIS_PROBLEM",
                    "task_description": "分析2025销售",
                    "source_text": "分析2025销售",
                    "time_range": "2025年",
                }
            ],
            "project_context": [],
            "user_project_context": [],
        },
    )

    assert "TIME_RANGE_CONFLICT" in conflict_types(analysis)
    assert analysis.result.tasks[0].status == "needs_clarification"
    assert "conflict:TIME_RANGE_CONFLICT" in analysis.result.tasks[0].missing_inputs


def test_statistical_definition_conflict_requires_clarification() -> None:
    analysis = analyze(
        "按回款金额分析销售",
        {
            "conversation_context": [
                {
                    "task_type": "DATA_ANALYSIS_PROBLEM",
                    "task_description": "按订单金额分析销售",
                    "source_text": "按订单金额分析销售",
                    "statistical_definition": "订单金额",
                }
            ],
            "project_context": [],
            "user_project_context": [],
        },
    )

    assert "STATISTICAL_DEFINITION_CONFLICT" in conflict_types(analysis)
    task = analysis.result.tasks[0]
    assert task.status == "needs_clarification"
    assert "conflict:STATISTICAL_DEFINITION_CONFLICT" in task.missing_inputs


def test_current_input_overrides_history_task_but_records_conflict() -> None:
    analysis = analyze(
        "只整理销售数据",
        {
            "conversation_context": [
                {
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成销售下降原因分析报告",
                    "source_text": "生成销售下降原因分析报告",
                }
            ],
            "project_context": [],
            "user_project_context": [],
        },
    )

    assert "CURRENT_CONTEXT_CONFLICT" in conflict_types(analysis)
    assert analysis.result.tasks[0].task_type == "DATA_QUERY_FETCH"
    assert all(
        conflict["resolution_status"] != "needs_clarification"
        for conflict in conflict_payloads(analysis)
        if conflict["conflict_type"] == "CURRENT_CONTEXT_CONFLICT"
    )
    assert "conflict:CURRENT_CONTEXT_CONFLICT" not in analysis.result.tasks[0].missing_inputs


def test_project_context_overrides_historical_project_context_and_records_conflict() -> None:
    analysis = analyze(
        "生成销售报表",
        {
            "conversation_context": [],
            "project_context": [
                {
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成销售报表",
                    "source_text": "项目统一使用ERP销售数据",
                    "data_source": "ERP",
                }
            ],
            "user_project_context": [
                {
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成销售报表",
                    "source_text": "历史项目使用CRM数据",
                    "data_source": "CRM",
                }
            ],
        },
    )

    assert "PROJECT_USER_CONTEXT_CONFLICT" in conflict_types(analysis)
    project_conflicts = [
        conflict
        for conflict in conflict_payloads(analysis)
        if conflict["conflict_type"] == "PROJECT_USER_CONTEXT_CONFLICT"
    ]
    assert project_conflicts[0]["resolution_status"] == "resolved"
    assert project_conflicts[0]["source_left"] == "project_context"
    assert project_conflicts[0]["source_right"] == "historical_projects"
    assert "conflict:PROJECT_USER_CONTEXT_CONFLICT" not in analysis.result.tasks[0].missing_inputs
