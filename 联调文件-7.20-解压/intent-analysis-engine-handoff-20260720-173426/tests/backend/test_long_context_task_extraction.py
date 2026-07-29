from app.services.conversation_understanding import ConversationUnderstandingLayer
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.task_extraction import (
    GlobalNegationResolver,
    IntentExtractor,
    LongContextTaskExtractionLayer,
    LongTextParser,
    TaskMerger,
    TaskCandidate,
    TaskSegmenter,
)


SAMPLE_TEXT = (
    "公司今年准备调整销售策略，领导希望先了解去年各区域销售表现。"
    "我整理了一些数据，但是发现华东区域下降比较明显，需要分析原因，并形成一份给管理层看的报告。"
    "另外，请帮我计算相关人员的销售奖励。"
)


def make_analyzer() -> ConversationUnderstandingLayer:
    return ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=FunctionRegistryCatalog(),
            semantic_matcher=None,
            llm_analyzer=None,
            intent_record_service=None,
        )
    )


def test_long_text_parser_classifies_short_medium_and_long_documents() -> None:
    parser = LongTextParser(chunk_size=500, chunk_overlap=50)

    assert parser.parse("背景说明。需要分析销售情况。").length_category == "short"
    assert parser.parse("背景。" * 400).length_category == "medium"
    assert parser.parse("背景。" * 4000).length_category == "long"


def test_long_text_parser_chunks_without_dropping_end_task() -> None:
    text = ("这是一段没有任务的背景说明。" * 1000) + "最后，请分析今年销售情况。"
    document = LongTextParser(chunk_size=800, chunk_overlap=100).parse(text)

    assert len(document.chunks) > 10
    assert document.length_category == "long"
    assert document.chunks[-1].end == len(text)
    assert "分析今年销售情况" in document.chunks[-1].text


def test_semantic_segmenter_separates_background_and_actions() -> None:
    document = LongTextParser().parse(SAMPLE_TEXT)
    segments = TaskSegmenter().segment_chunk(document.chunks[0])
    by_text = {segment.text: segment.kind for segment in segments}

    assert by_text["公司今年准备调整销售策略"] == "background"
    assert by_text["我整理了一些数据"] == "background"
    assert by_text["但是发现华东区域下降比较明显"] == "background"
    assert by_text["需要分析原因"] == "goal"
    assert by_text["并形成一份给管理层看的报告。"] == "action"


def test_business_topic_without_action_does_not_become_candidate() -> None:
    layer = LongContextTaskExtractionLayer(activation_length=1)
    result = layer.extract("去年销售数据下降明显。华东区域表现偏弱。以上是会议背景说明。")

    assert result.merged_candidates == []


def test_explicit_action_and_object_become_candidate() -> None:
    layer = LongContextTaskExtractionLayer(activation_length=1)
    result = layer.extract("会议提到销售下降。下一步需要分析销售下降原因。")

    assert len(result.merged_candidates) == 1
    assert result.merged_candidates[0].action == "analyze"
    assert "销售下降原因" in result.merged_candidates[0].normalized_text


def test_repeated_analysis_request_is_merged_with_supplement() -> None:
    layer = LongContextTaskExtractionLayer(activation_length=1)
    result = layer.extract("请分析销售情况。后续再重点看看下降区域，但不需要重复生成任务。")

    assert len(result.merged_candidates) == 1
    assert result.merged_candidates[0].action == "analyze"
    assert len(result.merged_candidates[0].merged_sources) == 2


def test_query_analysis_report_dependencies_are_sequential() -> None:
    layer = LongContextTaskExtractionLayer(activation_length=1)
    result = layer.extract("请获取销售数据，然后分析销售趋势，最后生成销售报告。")
    candidates = result.merged_candidates

    assert [candidate.action for candidate in candidates] == ["query", "analyze", "generate"]
    assert [candidate.depends_on_previous for candidate in candidates] == [False, True, True]


def test_additional_calculation_is_independent_from_report_chain() -> None:
    result = LongContextTaskExtractionLayer(activation_length=1).extract(SAMPLE_TEXT)

    assert [candidate.action for candidate in result.merged_candidates] == [
        "analyze",
        "analyze",
        "generate",
        "calculate",
    ]
    assert result.merged_candidates[2].depends_on_previous is True
    assert result.merged_candidates[3].depends_on_previous is False


def test_full_layer_outputs_four_standard_tasks_for_reference_sample() -> None:
    analysis = make_analyzer().analyze_with_debug(
        text=SAMPLE_TEXT,
        user_id="user-001",
        conversation_id="long-context-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == [
        "DATA_ANALYSIS_PROBLEM",
        "DATA_ANALYSIS_PROBLEM",
        "DOCUMENT_GENERATE",
        "RULE_CALCULATION_COMMISSION",
    ]
    assert [(task.action, task.object) for task in analysis.result.tasks] == [
        ("分析", "销售经营情况"),
        ("分析", "销售下降原因"),
        ("生成", "经营分析报告"),
        ("计算", "销售提成"),
    ]
    assert analysis.result.tasks[2].dependencies == [analysis.result.tasks[1].task_id]
    assert analysis.result.tasks[3].dependencies == []
    assert analysis.result.tasks[3].missing_inputs == [
        "calculation_policy",
        "sales_data_source",
    ]
    assert analysis.result.clarification_required is True
    assert analysis.debug["long_context_extraction"] is not None


def test_short_single_sentence_uses_existing_path() -> None:
    analysis = make_analyzer().analyze_with_debug(
        text="分析销售情况",
        user_id="user-001",
        conversation_id="short-001",
    )

    assert analysis.debug["long_context_extraction"] is None
    assert analysis.result.tasks[0].task_type == "DATA_ANALYSIS_PROBLEM"


def test_task_merger_keeps_reason_analysis_separate_from_overall_analysis() -> None:
    parser = LongTextParser()
    segmenter = TaskSegmenter()
    extractor = IntentExtractor()
    document = parser.parse("需要分析销售表现，并分析销售下降原因。")
    candidates = []
    for segment in segmenter.segment_chunk(document.chunks[0]):
        candidates.extend(extractor.extract(segment, inherited_object="销售"))

    merged = TaskMerger().merge(candidates, original_text=document.original_text)
    assert len(merged) == 2


def test_action_object_binding_keeps_sales_commission_together() -> None:
    result = LongContextTaskExtractionLayer(activation_length=1).extract(
        "财务希望顺便把销售人员的提成计算出来。"
    )

    assert len(result.merged_candidates) == 1
    assert result.merged_candidates[0].action == "calculate"
    assert result.merged_candidates[0].business_object == "销售提成"
    assert result.merged_candidates[0].normalized_text == "计算销售提成"


def test_global_negation_resolver_cancels_earlier_task_across_sentences() -> None:
    text = "以后希望监控销售异常并提醒相关人员。但是目前不用考虑自动提醒功能。"
    candidate = TaskCandidate(
        source_text="以后希望监控销售异常并提醒相关人员",
        normalized_text="监控销售异常并提醒相关人员",
        action="monitor",
        business_object="销售",
        start=0,
        end=17,
        confidence=0.9,
        source_kind="goal",
        merged_sources=["以后希望监控销售异常并提醒相关人员"],
    )

    resolution = GlobalNegationResolver().resolve([candidate], original_text=text)

    assert resolution.active_candidates == []
    assert [item.normalized_text for item in resolution.removed_candidates] == [
        "监控销售异常并提醒相关人员"
    ]
    assert resolution.directives[0].marker == "不用考虑"


def test_future_scope_filter_removes_future_monitoring_when_current_scope_excludes_it() -> None:
    result = LongContextTaskExtractionLayer(activation_length=1).extract(
        "以后希望自动提醒异常情况，但本次不考虑。"
    )

    assert [candidate.action for candidate in result.raw_candidates] == ["monitor"]
    assert [candidate.action for candidate in result.negated_candidates] == ["monitor"]
    assert result.merged_candidates == []


def test_future_scope_filter_matches_later_scope_exclusion_targets() -> None:
    result = LongContextTaskExtractionLayer(activation_length=1).extract(
        "未来规划里面希望系统主动提醒负责人。本次任务范围里面不包含异常监控和主动提醒功能。"
    )

    assert [candidate.action for candidate in result.negated_candidates] == ["monitor"]
    assert result.merged_candidates == []


def test_task_consolidation_preserves_analysis_subgoals_without_duplicates() -> None:
    result = LongContextTaskExtractionLayer(activation_length=1).extract(
        "请分析销售情况。还要分析经营情况。并分析销售下降原因。"
    )

    assert [candidate.normalized_text for candidate in result.merged_candidates] == [
        "分析销售经营情况",
        "分析销售下降原因",
    ]
    assert len(result.merged_candidates[0].merged_sources) == 2


def test_tasks_at_start_middle_and_end_survive_more_than_10000_characters() -> None:
    background = "本段仅用于说明历史情况，不包含需要执行的动作。"
    text = (
        "请查询今年销售数据。"
        + background * 250
        + "中间需要分析销售趋势。"
        + background * 250
        + "最后生成销售分析报告。"
    )
    result = LongContextTaskExtractionLayer(
        parser=LongTextParser(chunk_size=1000, chunk_overlap=120),
        activation_length=1,
    ).extract(text)

    assert len(text) > 10000
    assert [candidate.action for candidate in result.merged_candidates] == ["query", "analyze", "generate"]


def test_meeting_action_label_does_not_override_requested_action() -> None:
    text = (
        "会议纪要：此前团队已经整理了背景材料，不需要重复处理。"
        "会议形成的明确行动项是：请分析今年各区域销售表现。"
    )

    result = LongContextTaskExtractionLayer(activation_length=1).extract(text)

    assert [candidate.action for candidate in result.merged_candidates] == ["analyze"]


def test_project_started_in_background_is_not_a_workflow_task() -> None:
    background = (
        "项目启动以来，团队持续讨论组织安排和历史材料。"
        "这些内容只是背景，不包含新的执行动作。"
    )
    text = background * 20 + "全文唯一明确要求：请预测明年销售额趋势。"

    result = LongContextTaskExtractionLayer(activation_length=1).extract(text)

    assert [candidate.action for candidate in result.merged_candidates] == ["forecast"]


def test_historical_generated_material_is_not_a_generation_task() -> None:
    text = (
        "此前形成的历史材料只用于说明情况，不构成当前任务。"
        "团队已经完成相关沟通，现阶段没有新的操作要求。"
        "以上均为背景信息。"
    )

    result = LongContextTaskExtractionLayer(activation_length=1).extract(text)

    assert result.merged_candidates == []


def test_external_system_source_survives_normalization() -> None:
    analysis = make_analyzer().analyze_with_debug(
        text="这是项目背景说明，不需要执行。明确要求：请从CRM获取本季度客户资料。",
        user_id="user-001",
        conversation_id="long-external-001",
    )

    assert analysis.result.tasks[0].task_type == "EXTERNAL_DATA_FETCH"
    assert analysis.result.tasks[0].action == "获取"


def test_threshold_filter_is_not_misclassified_as_monitoring() -> None:
    analysis = make_analyzer().analyze_with_debug(
        text="前面都是背景信息，不需要处理。现在请筛选回款逾期超过三十天的客户。",
        user_id="user-001",
        conversation_id="long-filter-001",
    )

    assert analysis.result.tasks[0].task_type == "DATA_FILTER"


def test_explicit_sales_data_and_policy_support_calculation_dependency() -> None:
    analysis = make_analyzer().analyze_with_debug(
        text=(
            "月末关账需要准备资料。请查询上个月销售明细，"
            "根据现行提成政策计算销售提成，再生成计提凭证。"
        ),
        user_id="user-001",
        conversation_id="long-calculation-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == [
        "DATA_QUERY_FETCH",
        "RULE_CALCULATION_COMMISSION",
        "DIGITAL_ASSET_ACCRUAL_VOUCHER",
    ]
    assert analysis.result.tasks[1].missing_inputs == []
    assert analysis.result.tasks[2].missing_inputs == []
    assert analysis.result.tasks[2].dependencies == [analysis.result.tasks[1].task_id]
    assert analysis.result.clarification_required is False
