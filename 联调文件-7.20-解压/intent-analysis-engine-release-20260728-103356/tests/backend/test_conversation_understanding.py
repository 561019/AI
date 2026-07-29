from app.services.conversation_understanding import (
    ConversationParser,
    ConversationUnderstandingLayer,
    NaturalLanguageNormalizer,
    NoiseFilter,
    ReferenceResolver,
)
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.context_provider import MockContextProvider


def make_layer() -> ConversationUnderstandingLayer:
    analyzer = StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )
    return ConversationUnderstandingLayer(analyzer)


def make_layer_with_context(default_context: dict) -> ConversationUnderstandingLayer:
    analyzer = StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )
    return ConversationUnderstandingLayer(
        analyzer,
        context_provider=MockContextProvider(default_context=default_context),
    )


def test_normalizer_keeps_original_separate_from_normalized_text() -> None:
    parser = ConversationParser()
    parsed = parser.parse("帮我瞅瞅今年销售情况")

    assert parsed.original_text == "帮我瞅瞅今年销售情况"
    assert parsed.normalized_text == "分析今年销售情况"


def test_normalizer_maps_common_spoken_actions() -> None:
    normalizer = NaturalLanguageNormalizer()

    assert normalizer.normalize("算一下销售奖金") == "计算销售奖金"
    assert normalizer.normalize("弄一份经营报告") == "生成一份经营报告"
    assert normalizer.normalize("看看有没有问题") == "检查分析"


def test_noise_filter_removes_politeness_emotion_and_urgency() -> None:
    result = NoiseFilter().filter("麻烦帮我看一下，最近事情比较多，老板催得比较急，想了解一下今年销售情况")

    assert result.filtered_text == "看一下，想了解一下今年销售情况"
    assert "麻烦帮我" in result.removed_fragments
    assert "最近事情比较多" in result.removed_fragments
    assert "老板催得比较急" in result.removed_fragments


def test_reference_resolver_uses_last_explicit_business_object() -> None:
    result = ReferenceResolver().resolve(
        "继续",
        [{"role": "user", "text": "帮我分析销售数据"}],
    )

    assert result.resolved_text == "继续分析销售数据"
    assert result.resolved_references[0]["resolved_to"] == "销售数据"


def test_new_explicit_object_takes_precedence_over_previous_context() -> None:
    parsed = ConversationParser().parse(
        "那再看看利润情况",
        history=[{"role": "user", "content": "帮我分析销售数据"}],
    )

    assert parsed.normalized_text == "分析利润情况"
    assert parsed.context.business_objects[0] == "利润情况"
    assert parsed.context.business_objects[1] == "销售数据"


def test_complex_sales_request_decomposes_into_four_validated_tasks() -> None:
    text = "帮我把去年各区域销售数据整理出来，看一下哪些区域下降比较明显，分析原因，然后生成给领导看的汇报PPT"
    analysis = make_layer().analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="conversation-001",
    )
    result = analysis.result

    assert result.original_text == text
    assert [task.task_name for task in result.tasks] == [
        "整理销售数据",
        "销售趋势分析",
        "销售下降原因分析",
        "生成汇报材料",
    ]
    assert [task.task_type for task in result.tasks] == [
        "DATA_QUERY_FETCH",
        "DATA_ANALYSIS_PROBLEM",
        "DATA_ANALYSIS_PROBLEM",
        "DOCUMENT_GENERATE",
    ]
    assert [(task.action, task.object) for task in result.tasks] == [
        ("整理", "销售数据"),
        ("分析", "销售趋势"),
        ("分析", "销售下降原因"),
        ("生成", "汇报材料"),
    ]
    assert result.tasks[0].dependencies == []
    assert result.tasks[1].dependencies == [result.tasks[0].task_id]
    assert result.tasks[2].dependencies == [result.tasks[1].task_id]
    assert result.tasks[3].dependencies == [result.tasks[2].task_id]
    assert all(task.required_inputs for task in result.tasks)
    assert result.clarification_required is False
    assert "business_execution" not in analysis.debug


def test_background_heavy_request_keeps_only_three_explicit_tasks() -> None:
    text = "最近领导让我看一下销售情况，因为月底要开经营分析会，上个月华东区域销售下降比较明显，能不能帮我整理一下原因，再做一份汇报材料？"
    analysis = make_layer().analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_name for task in analysis.result.tasks] == [
        "销售趋势分析",
        "销售下降原因分析",
        "生成汇报材料",
    ]
    conversation_debug = analysis.debug["conversation_understanding"]
    assert "因为月底要开经营分析会" in conversation_debug["removed_noise"]
    assert conversation_debug["context"]["time_ranges"] == ["上个月"]
    assert "华东区域" in conversation_debug["context"]["data_scopes"]


def test_missing_inputs_still_clarify_after_conversation_preprocessing() -> None:
    result = make_layer().analyze(
        text="麻烦了，帮我算一下销售提成",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks[0].task_type == "RULE_CALCULATION_COMMISSION"
    assert result.clarification_required is True
    assert result.tasks[0].missing_inputs == ["calculation_policy"]


def test_multi_task_clarification_stays_bound_to_each_task() -> None:
    analysis = make_layer().analyze_with_debug(
        text="整理销售数据，计算销售提成，生成经营报告",
        user_id="user-001",
        conversation_id="conversation-001",
    )
    result = analysis.result
    task1, task2, task3 = result.tasks

    assert [task.task_type for task in result.tasks] == [
        "DATA_QUERY_FETCH",
        "RULE_CALCULATION_COMMISSION",
        "DOCUMENT_GENERATE",
    ]

    assert task1.status == "ready"
    assert task1.missing_inputs == []
    assert task1.clarification_required is False
    assert task1.clarification_questions == []

    assert task2.status == "needs_clarification"
    assert task2.missing_inputs == ["calculation_policy"]
    assert task2.clarification_required is True
    assert task2.clarification_questions == ["请提供计算规则或适用政策。"]

    assert task3.dependencies == [task2.task_id]
    assert task3.status == "waiting_dependency"
    assert task3.missing_inputs == []
    assert task3.clarification_required is False
    assert task3.blocked_reason == f"waiting_for_dependency:{task2.task_id}"

    assert result.global_clarification_required is True
    assert result.clarification_required is True
    assert result.clarification_questions == ["请提供计算规则或适用政策。"]
    assert analysis.debug["final_tasklist"]["tasks"][1]["clarification_questions"] == [
        "请提供计算规则或适用政策。"
    ]
    assert analysis.debug["final_tasklist"]["tasks"][2]["blocked_reason"] == (
        f"waiting_for_dependency:{task2.task_id}"
    )


def test_reference_only_followup_is_resolved_before_existing_analyzer() -> None:
    analysis = make_layer().analyze_with_debug(
        text="继续",
        user_id="user-001",
        conversation_id="conversation-001",
        history=[{"role": "user", "text": "帮我分析销售数据"}],
    )

    assert analysis.debug["conversation_understanding"]["resolved_text"] == "继续分析销售数据"
    assert analysis.result.tasks[0].task_type == "DATA_ANALYSIS_PROBLEM"
    assert analysis.result.tasks[0].action == "分析"


def test_decomposer_inferred_policy_is_removed_when_user_did_not_provide_it() -> None:
    result = make_layer().analyze(
        text="获取上月销售数据，核算提成，生成凭证",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    calculation_task = result.tasks[1]
    assert calculation_task.task_type == "RULE_CALCULATION_COMMISSION"
    assert "calculation_policy" not in {
        value.split(":", 1)[0] for value in calculation_task.required_inputs
    }
    assert calculation_task.missing_inputs == ["calculation_policy"]
    assert result.clarification_required is True


def test_negated_file_reference_does_not_count_as_provided_input() -> None:
    result = make_layer().analyze(
        text="我不确定有没有文件，帮我解析",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.clarification_required is True
    assert result.tasks[0].missing_inputs == ["file"]


def test_colloquial_workflow_status_followup_recovers_query_context() -> None:
    layer = make_layer_with_context(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-WORKFLOW-STATUS-001",
                    "task_type": "WORKFLOW_START",
                    "task_description": "发起合同评审流程",
                    "source_text": "发起合同评审流程",
                    "action": "发起",
                    "object": "合同评审流程",
                    "required_inputs": ["process_name:合同评审流程"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="也帮我看下办理进度",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["DATA_QUERY_FETCH"]
    assert analysis.result.tasks[0].missing_inputs == ["data_source"]
    assert analysis.debug["context_resolution"]["semantic_matching_weight"] == 0.0


def test_compact_group_sum_filter_and_content_request_decomposes() -> None:
    result = make_layer().analyze(
        text="按门店合计回款金额，筛选超期客户，写一份催收话术",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in result.tasks] == [
        "DATA_ANALYSIS_GROUP_SUM",
        "DATA_FILTER",
        "CONTENT_GENERATE",
    ]
    assert result.tasks[0].missing_inputs == ["statistical_range"]
    assert result.clarification_required is True


def test_policy_lookup_segment_does_not_satisfy_commission_policy() -> None:
    result = make_layer().analyze(
        text="了解返利政策，计算经销商佣金，生成入账凭证",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in result.tasks] == [
        "QUESTION_ANSWER",
        "RULE_CALCULATION_COMMISSION",
        "DIGITAL_ASSET_ACCRUAL_VOUCHER",
    ]
    assert result.tasks[1].missing_inputs == ["calculation_policy"]


def test_chained_business_object_can_feed_downstream_without_single_query_regression() -> None:
    chained = make_layer().analyze(
        text="获取供应商档案，做等级排序，生成跟进话术",
        user_id="user-001",
        conversation_id="conversation-001",
    )
    single = make_layer().analyze(
        text="客户资料取出来",
        user_id="user-001",
        conversation_id="conversation-002",
    )

    assert [task.task_type for task in chained.tasks] == [
        "DATA_QUERY_FETCH",
        "DATA_SORT",
        "CONTENT_GENERATE",
    ]
    assert chained.clarification_required is False
    assert single.tasks[0].missing_inputs == ["data_source"]


def test_future_scope_exclusion_does_not_create_monitoring_task_after_preprocessing() -> None:
    result = make_layer().analyze(
        text="以后希望自动提醒异常情况，但本次不考虑。",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks == []
    assert result.clarification_required is False


def test_negated_generation_is_removed_before_conversation_segmentation() -> None:
    result = make_layer().analyze(
        text="不要生成报告，只分析销售提成",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in result.tasks] == ["DATA_ANALYSIS_PROBLEM"]
    assert "DOCUMENT_GENERATE" not in [task.task_type for task in result.tasks]


def test_unknown_followup_without_history_requires_clarification() -> None:
    result = make_layer().analyze(
        text="继续上面的",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks == []
    assert result.clarification_required is True
    assert result.clarification_questions == ["请明确需要处理的业务对象和具体动作。"]
