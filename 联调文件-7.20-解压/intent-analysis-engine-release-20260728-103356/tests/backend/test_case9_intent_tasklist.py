from app.services.conversation_understanding import ConversationUnderstandingLayer
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer


def make_layer() -> ConversationUnderstandingLayer:
    return ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=FunctionRegistryCatalog(),
            semantic_matcher=None,
            llm_analyzer=None,
            intent_record_service=None,
        )
    )


def test_metric_decline_question_becomes_diagnostic_task_chain() -> None:
    result = make_layer().analyze(
        text="为什么本季度前十名经销商复购率环比下降两个点？",
        user_id="user-001",
        conversation_id="case9-diagnostic",
    )

    assert [task.task_type for task in result.tasks] == [
        "DATA_QUERY_FETCH",
        "DATA_ANALYSIS_MOM",
        "DATA_ANALYSIS_GROUP_SUM",
        "DATA_ANALYSIS_PROBLEM",
    ]
    assert [(task.action, task.object) for task in result.tasks] == [
        ("查询", "前十名经销商复购率数据"),
        ("分析", "复购率变化"),
        ("汇总", "复购率下降贡献"),
        ("分析", "复购率下降原因"),
    ]
    assert result.clarification_required is False


def test_regional_demand_forecast_provides_analysis_object() -> None:
    result = make_layer().analyze(
        text="按现在的走势，预测下季度桂中的需求。",
        user_id="user-001",
        conversation_id="case9-forecast",
    )

    assert [task.task_type for task in result.tasks] == ["DATA_ANALYSIS_FORECAST"]
    assert result.tasks[0].missing_inputs == []
    assert result.clarification_required is False
    assert any(value.startswith("analysis_object:") for value in result.tasks[0].required_inputs)


def test_case_style_document_extracts_only_user_requests() -> None:
    text = (
        "案例说明：系统会解析报表、调用提醒能力、检查权限，这些都是背景说明。"
        "业务经理在工作台问一句：为什么本季度重点经销商复购率环比下降？"
        "后续文档继续解释各类引擎如何协作。"
        "接着业务经理说：按当前走势预测下季度西南区域需求。"
    )

    analysis = make_layer().analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="case9-document",
    )
    task_types = [task.task_type for task in analysis.result.tasks]

    assert task_types == [
        "DATA_QUERY_FETCH",
        "DATA_ANALYSIS_MOM",
        "DATA_ANALYSIS_GROUP_SUM",
        "DATA_ANALYSIS_PROBLEM",
        "DATA_ANALYSIS_FORECAST",
    ]
    assert "DOCUMENT_TABLE_PARSE" not in task_types
    assert "MONITORING_REMINDER" not in task_types
    assert analysis.result.clarification_required is False
    assert [
        segment["text"]
        for segment in analysis.debug["conversation_understanding"]["segments"]
    ] == [
        "分析本季度重点经销商复购率环比下降原因",
        "预测下季度西南区域需求",
    ]
