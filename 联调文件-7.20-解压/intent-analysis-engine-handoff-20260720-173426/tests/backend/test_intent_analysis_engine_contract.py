from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer


def make_analyzer() -> StandardIntentAnalyzer:
    return StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )


def test_decomposes_sales_commission_and_accrual_voucher_into_three_tasks() -> None:
    analyzer = make_analyzer()

    analysis = analyzer.analyze_with_debug(
        text="把上个月各区域销售提成算出来，生成计提凭证",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    result = analysis.result
    assert result.clarification_required is False
    assert result.intent_category == "规则计算型"
    assert [task.task_name for task in result.tasks] == [
        "获取销售明细",
        "根据政策计算销售提成",
        "生成计提凭证",
    ]
    assert [(task.action, task.object) for task in result.tasks] == [
        ("获取", "销售明细"),
        ("计算", "销售提成"),
        ("生成", "计提凭证"),
    ]
    assert result.tasks[1].dependencies == [result.tasks[0].task_id]
    assert result.tasks[2].dependencies == [result.tasks[1].task_id]
    assert "period:上个月" in result.tasks[0].required_inputs
    assert "business_execution" not in analysis.debug


def test_returns_clarification_when_statistics_request_misses_dimension_and_range() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="统计销售金额",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.clarification_required is True
    assert result.tasks[0].task_type == "DATA_AGGREGATION_SUMMARY"
    assert result.tasks[0].missing_inputs == ["classification_field", "statistical_range"]
    assert result.clarification_questions == [
        "请确认统计维度（例如区域、产品、客户）。",
        "请确认统计范围（例如时间范围、组织范围）。",
    ]


def test_short_sales_commission_phrase_requires_clarification() -> None:
    analyzer = make_analyzer()

    analysis = analyzer.analyze_with_debug(
        text="销售提成",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    result = analysis.result
    assert result.analysis_level == 1
    assert result.intent_category == "规则计算型"
    assert result.tasks[0].task_type == "RULE_CALCULATION_COMMISSION"
    assert result.tasks[0].action == "计算"
    assert result.tasks[0].object == "销售提成"
    assert result.tasks[0].missing_inputs == [
        "calculation_policy",
        "sales_data_source",
        "statistical_range",
    ]
    assert result.clarification_required is True
    assert analysis.debug["level1_result"]["source"] == "OperationRuleMatcher"
    assert analysis.debug["level2_result"] is None
    assert analysis.debug["level3_result"] is None
    assert analysis.debug["level1_rule_result"] == {
        "matched": True,
        "rule": "rule_calculation",
        "rule_priority": 70,
    }
    assert analysis.debug["level2_semantic_result"]["skipped_reason"] == "level1_rule_matched"
    assert analysis.debug["final_decision"]["selected_by"] == "rule"
    assert "rule_calculation" in analysis.debug["final_decision"]["reason"]
    assert analysis.debug["input_validator"]["missing_inputs"] == [
        "calculation_policy",
        "sales_data_source",
        "statistical_range",
    ]
    assert analysis.debug["input_validator"]["rules"][0]["validator_rule"] == "required_input_missing"
    assert analysis.debug["input_validator"]["rules"][0]["source"] == "semantic_capabilities.yaml.required_inputs"


def test_rule_hit_for_sales_pivot_table_stays_at_level1_without_llm() -> None:
    analyzer = make_analyzer()

    analysis = analyzer.analyze_with_debug(
        text="生成销售数据透视表",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    result = analysis.result
    assert result.analysis_level == 1
    assert result.clarification_required is False
    assert result.tasks[0].task_type == "DATA_ANALYSIS_PIVOT"
    assert result.tasks[0].action == "生成"
    assert result.tasks[0].object == "数据透视表"
    assert analysis.debug["level1_result"]["source"] == "OperationRuleMatcher"
    assert analysis.debug["level3_result"] is None


def test_simple_reimbursement_policy_question_uses_question_fast_path() -> None:
    analyzer = make_analyzer()

    analysis = analyzer.analyze_with_debug(
        text="公司的报销政策是什么？",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    result = analysis.result
    assert result.analysis_level == 1
    assert result.intent_category == "智能问答型"
    assert result.tasks[0].task_type == "QUESTION_ANSWER"
    assert result.tasks[0].task_description == "智能问答"
    assert analysis.debug["fast_path"] == {"matched": True, "type": "question_fast_path"}
    assert analysis.debug["level2_result"] is None
    assert analysis.debug["level3_result"] is None


def test_decomposes_customer_complaints_into_registered_task_types() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="整理客户投诉并生成改进方案",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.clarification_required is False
    assert [task.task_name for task in result.tasks] == [
        "投诉信息整理",
        "问题分析",
        "方案生成",
    ]
    assert [task.task_type for task in result.tasks] == [
        "COMPLAINT_INFORMATION_ORGANIZE",
        "DATA_ANALYSIS_PROBLEM",
        "IMPROVEMENT_PLAN_GENERATE",
    ]


def test_monitoring_reminder_requires_threshold_when_comparator_is_incomplete() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="库存低于 提醒我",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks[0].task_type == "MONITORING_REMINDER"
    assert result.tasks[0].action == "创建"
    assert result.tasks[0].missing_inputs == ["trigger_condition"]
    assert result.clarification_required is True
    assert result.clarification_questions == ["请确认触发提醒的条件。"]


def test_monitoring_reminder_accepts_comparator_with_threshold() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="库存低于100时提醒我",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks[0].task_type == "MONITORING_REMINDER"
    assert result.tasks[0].missing_inputs == []
    assert result.clarification_required is False


def test_future_scope_exclusion_does_not_create_monitoring_task_on_rule_path() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="以后希望自动提醒异常情况，但本次不考虑。",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks == []


def test_level1_rules_cover_all_registered_task_types() -> None:
    analyzer = make_analyzer()
    cases = [
        ("解析上传的销售明细Excel表格", "DOCUMENT_TABLE_PARSE"),
        ("从CRM系统获取客户资料", "EXTERNAL_DATA_FETCH"),
        ("按区域汇总本月销售金额", "DATA_AGGREGATION_SUMMARY"),
        ("根据销售提成政策计算上个月销售提成", "RULE_CALCULATION_COMMISSION"),
        ("预测下季度销售额趋势", "DATA_ANALYSIS_FORECAST"),
        ("公司的报销政策是什么？", "QUESTION_ANSWER"),
        ("写一份会议通知", "CONTENT_GENERATE"),
        ("生成一张新品发布海报", "MULTIMEDIA_GENERATE"),
        ("发起采购审批流程", "WORKFLOW_START"),
        ("库存低于100时提醒我", "MONITORING_REMINDER"),
        ("根据本月提成计算结果生成计提凭证", "DIGITAL_ASSET_ACCRUAL_VOUCHER"),
    ]

    for text, task_type in cases:
        analysis = analyzer.analyze_with_debug(
            text=text,
            user_id="user-001",
            conversation_id="conversation-001",
        )

        assert analysis.result.tasks, text
        assert analysis.result.tasks[0].task_type == task_type
        assert analysis.result.analysis_level == 1
        assert "business_execution" not in analysis.debug
        assert analysis.debug["level2_result"] is None
        assert analysis.debug["level3_result"] is None
