from app.schemas.semantic import SemanticCandidate, SemanticResult
from app.services.context_provider import MockContextProvider
from app.services.context_provider.schemas import ContextInput
from app.services.conversation_understanding import ConversationUnderstandingLayer
from app.services.intent_analysis_engine import EllipsisResolver, FunctionRegistryCatalog, StandardIntentAnalyzer


def make_layer(context: dict | None = None, semantic_matcher=None) -> ConversationUnderstandingLayer:
    analyzer = StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=semantic_matcher,
        llm_analyzer=None,
        intent_record_service=None,
    )
    return ConversationUnderstandingLayer(
        analyzer,
        context_provider=MockContextProvider(default_context=context or {}),
    )


def test_recalculate_omitted_expression_recovers_previous_commission_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CALC-001",
                    "task_type": "RULE_CALCULATION_COMMISSION",
                    "task_description": "计算2025年销售提成",
                    "source_text": "计算2025年销售提成",
                    "action": "计算",
                    "object": "销售提成",
                    "required_inputs": [
                        "calculation_policy:2025销售提成政策",
                        "calculation_basis:2025销售数据",
                        "sales_data_source:ERP",
                        "statistical_range:2025年",
                    ],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="帮我再算一遍",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = analysis.result.tasks[0]
    assert task.task_id == "TASK-CALC-001"
    assert task.task_type == "RULE_CALCULATION_COMMISSION"
    assert task.action == "计算"
    assert task.object == "销售提成"
    assert "calculation_policy:2025销售提成政策" in task.required_inputs
    assert "sales_data_source:ERP" in task.required_inputs
    assert analysis.debug["context_resolution"]["scope"] == "conversation"
    assert analysis.debug["context_resolution"]["task_recovery"]["task_id_preserved"] is True


def test_continue_edit_recovers_previous_report_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-REPORT-001",
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成销售分析报告",
                    "source_text": "生成销售分析报告",
                    "action": "生成",
                    "object": "销售分析报告",
                    "required_inputs": ["topic:销售分析", "content_type:报告"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    result = layer.analyze(
        text="接着改",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = result.tasks[0]
    assert task.task_id == "TASK-REPORT-001"
    assert task.task_type == "DOCUMENT_GENERATE"
    assert task.action == "生成"
    assert task.object == "销售分析报告"
    assert "topic:销售分析" in task.required_inputs


def test_dimension_change_recovers_previous_analysis_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-ANALYSIS-001",
                    "task_type": "DATA_ANALYSIS_PROBLEM",
                    "task_description": "销售下降原因分析",
                    "source_text": "销售下降原因分析",
                    "action": "分析",
                    "object": "销售下降原因",
                    "required_inputs": ["analysis_object:销售", "analysis_method:原因分析"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    result = layer.analyze(
        text="换个维度看看",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = result.tasks[0]
    assert task.task_id == "TASK-ANALYSIS-001"
    assert task.task_type == "DATA_ANALYSIS_PROBLEM"
    assert task.action == "分析"
    assert task.object == "销售下降原因"
    assert "analysis_object:销售" in task.required_inputs


def test_recalculate_without_context_requires_clarification() -> None:
    result = make_layer().analyze(
        text="重新计算",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks == []
    assert result.clarification_required is True
    assert result.clarification_questions == ["请明确要继续处理的上一轮任务或业务对象。"]


def test_continue_analysis_recovers_recent_related_conversation_task_first() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CONV-ANALYSIS",
                    "task_type": "DATA_ANALYSIS_PROBLEM",
                    "task_description": "分析华东销售下降原因",
                    "action": "分析",
                    "object": "华东销售下降原因",
                    "required_inputs": ["analysis_object:华东销售", "analysis_method:原因分析"],
                }
            ],
            "project_context": [
                {
                    "task_id": "TASK-PROJECT-ANALYSIS",
                    "task_type": "DATA_ANALYSIS_PROBLEM",
                    "task_description": "分析全国销售趋势",
                    "action": "分析",
                    "object": "全国销售趋势",
                    "required_inputs": ["analysis_object:全国销售", "analysis_method:趋势分析"],
                }
            ],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="继续分析",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert analysis.result.tasks[0].task_id == "TASK-CONV-ANALYSIS"
    assert analysis.debug["context_resolution"]["scope"] == "conversation"


def test_same_method_request_recovers_previous_task_without_guessing_extra_tasks() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-SAME-001",
                    "task_type": "DATA_SORT",
                    "task_description": "排序销售数据",
                    "action": "排序",
                    "object": "销售数据",
                    "required_inputs": ["data_source:销售数据", "operation:排序"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    result = layer.analyze(
        text="按刚才的方式处理",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_id for task in result.tasks] == ["TASK-SAME-001"]
    assert [task.task_type for task in result.tasks] == ["DATA_SORT"]


def test_context_reference_basis_recovers_single_previous_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-FEEDBACK-REPORT",
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成客户反馈分析报告",
                    "source_text": "生成客户反馈分析报告",
                    "action": "生成",
                    "object": "客户反馈分析报告",
                    "required_inputs": ["document_type:报告", "topic:客户反馈"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="根据客户反馈",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = analysis.result.tasks[0]
    assert task.task_id == "TASK-FEEDBACK-REPORT"
    assert task.task_type == "DOCUMENT_GENERATE"
    assert task.missing_inputs == []
    assert analysis.debug["context_resolution"]["family"] == "context_reference"
    assert analysis.debug["final_decision"]["selected_by"] == "context_recovery"


def test_context_reference_to_prior_material_recovers_analysis_task() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-FEEDBACK-ANALYSIS",
                    "task_type": "DATA_ANALYSIS_PROBLEM",
                    "task_description": "分析客户反馈中的主要问题",
                    "source_text": "分析客户反馈中的主要问题",
                    "action": "分析",
                    "object": "客户反馈主要问题",
                    "required_inputs": ["analysis_object:客户反馈", "analysis_method:问题分析"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="基于上文材料",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["DATA_ANALYSIS_PROBLEM"]
    assert analysis.result.tasks[0].task_id == "TASK-FEEDBACK-ANALYSIS"
    assert analysis.debug["context_resolution"]["family"] == "context_reference"


def test_context_reference_without_context_requires_clarification() -> None:
    result = make_layer().analyze(
        text="根据客户反馈",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks == []
    assert result.clarification_required is True


def test_context_reference_multiple_candidates_require_clarification() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-FEEDBACK-REPORT",
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成客户反馈分析报告",
                },
                {
                    "task_id": "TASK-FEEDBACK-ANALYSIS",
                    "task_type": "DATA_ANALYSIS_PROBLEM",
                    "task_description": "分析客户反馈中的主要问题",
                },
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="根据客户反馈",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert analysis.result.tasks == []
    assert analysis.result.clarification_required is True
    assert analysis.debug["context_resolution"]["ambiguous"] is True
    assert analysis.debug["context_resolution"]["family"] == "context_reference"


def test_explicit_task_with_context_basis_is_not_overridden_by_previous_context() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CALC-CONTEXT",
                    "task_type": "RULE_CALCULATION_COMMISSION",
                    "task_description": "计算销售提成",
                    "action": "计算",
                    "object": "销售提成",
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="根据客户反馈生成报告",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["DOCUMENT_GENERATE"]
    assert analysis.result.tasks[0].task_id != "TASK-CALC-CONTEXT"
    assert analysis.debug["context_resolution"]["requires_context"] is False


def test_ellipsis_resolver_returns_context_task_type_for_short_repeat() -> None:
    resolver = EllipsisResolver()
    resolution = resolver.resolve(
        "再算一遍",
        ContextInput.model_validate(
            {
                "conversation_context": [
                    {
                        "task_type": "RULE_CALCULATION_COMMISSION",
                        "task_description": "计算销售提成",
                    }
                ]
            }
        ),
    )

    assert resolution.resolved is True
    assert resolution.context_item is not None
    assert resolution.context_item["task_type"] == "RULE_CALCULATION_COMMISSION"
    assert resolution.context_recovery_confidence == 0.95
    assert resolution.semantic_matching_weight == 0.0


def test_short_ellipsis_context_recovery_suppresses_semantic_override() -> None:
    class MisleadingSemanticMatcher:
        def __init__(self) -> None:
            self.calls = []

        def analyze(self, payload):
            self.calls.append(payload)
            return SemanticResult.matched_result(
                candidates=[
                    SemanticCandidate(
                        function_code="FUNC_REPORT_GENERATION",
                        task_type="DOCUMENT_GENERATE",
                        task_name="生成业务文档",
                        confidence=0.99,
                        similarity_score=0.99,
                    )
                ]
            )

    semantic_matcher = MisleadingSemanticMatcher()
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CALC-SEMANTIC-GUARD",
                    "task_type": "RULE_CALCULATION_COMMISSION",
                    "task_description": "计算销售提成",
                    "action": "计算",
                    "object": "销售提成",
                    "required_inputs": [
                        "calculation_policy:销售提成政策",
                        "sales_data_source:ERP",
                        "statistical_range:本月",
                    ],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        },
        semantic_matcher=semantic_matcher,
    )

    analysis = layer.analyze_with_debug(
        text="继续处理",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert semantic_matcher.calls == []
    assert [task.task_type for task in analysis.result.tasks] == ["RULE_CALCULATION_COMMISSION"]
    assert analysis.debug["context_resolution"]["semantic_matching_weight"] == 0.0
    assert analysis.debug["context_resolution"]["task_recovery"]["semantic_matching_suppressed"] is True


def test_multiple_matching_context_candidates_require_clarification() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CALC-001",
                    "task_type": "RULE_CALCULATION_COMMISSION",
                    "task_description": "计算销售提成",
                },
                {
                    "task_id": "TASK-REPORT-001",
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成经营报告",
                },
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="继续处理",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert analysis.result.tasks == []
    assert analysis.result.clarification_required is True
    assert analysis.debug["context_resolution"]["ambiguous"] is True
    assert analysis.debug["context_resolution"]["clarification_reason"] == "ambiguous_context"


def test_explicit_current_task_is_not_overridden_by_context() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CALC-001",
                    "task_type": "RULE_CALCULATION_COMMISSION",
                    "task_description": "计算销售提成",
                    "action": "计算",
                    "object": "销售提成",
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="生成经营报告",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert analysis.result.tasks[0].task_type == "DOCUMENT_GENERATE"
    assert analysis.debug["context_resolution"]["requires_context"] is False


def test_filter_repeat_with_colloquial_action_recovers_filter_context() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-FILTER-001",
                    "task_type": "DATA_FILTER",
                    "task_description": "筛选高风险订单",
                    "source_text": "筛选高风险订单",
                    "action": "筛选",
                    "object": "高风险订单",
                    "required_inputs": ["operation:筛选"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="沿用上次条件再挑一组",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["DATA_FILTER"]
    assert analysis.result.tasks[0].task_id == "TASK-FILTER-001"
    assert analysis.debug["context_resolution"]["family"] == "filter"
    assert analysis.debug["context_resolution"]["semantic_matching_weight"] == 0.0


def test_process_progress_followup_recovers_process_context_inputs() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-PROCESS-001",
                    "task_type": "PROCESS_HANDLE",
                    "task_description": "办理供应商准入流程",
                    "source_text": "办理供应商准入流程",
                    "action": "办理",
                    "object": "供应商准入流程",
                    "required_inputs": ["process_name:供应商准入流程"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    result = layer.analyze(
        text="继续确认办理进展",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = result.tasks[0]
    assert task.task_type == "PROCESS_HANDLE"
    assert task.missing_inputs == []
    assert "process_name:供应商准入流程" in task.required_inputs


def test_equivalent_provider_and_history_context_do_not_create_ambiguity() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CALC-PROVIDER",
                    "task_type": "RULE_CALCULATION_COMMISSION",
                    "task_description": "计算销售提成",
                    "source_text": "计算销售提成",
                    "action": "计算",
                    "object": "销售提成",
                    "required_inputs": [
                        "calculation_policy:销售提成政策",
                        "sales_data_source:ERP",
                    ],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="再算一次",
        user_id="user-001",
        conversation_id="conversation-001",
        history=[{"role": "user", "text": "计算销售提成"}],
    )

    task = analysis.result.tasks[0]
    assert task.task_id == "TASK-CALC-PROVIDER"
    assert task.task_type == "RULE_CALCULATION_COMMISSION"
    assert analysis.result.clarification_required is False
    assert analysis.debug["context_resolution"]["candidate_count"] == 1
    assert analysis.debug["context_resolution"]["ambiguous"] is False


def test_document_field_followup_preserves_table_parse_context_task_type() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-DOC-PARSE",
                    "task_type": "DOCUMENT_TABLE_PARSE",
                    "task_description": "解析供应商报价Excel",
                    "source_text": "解析供应商报价Excel",
                    "action": "解析",
                    "object": "供应商报价Excel",
                    "required_inputs": ["file:供应商报价Excel"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="继续确认表格列结构",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = analysis.result.tasks[0]
    assert task.task_id == "TASK-DOC-PARSE"
    assert task.task_type == "DOCUMENT_TABLE_PARSE"
    assert analysis.debug["context_resolution"]["task_type_override"] is None
    assert analysis.debug["context_resolution"]["task_recovery"]["task_type_preserved"] is True


def test_field_followup_without_context_clarifies_before_semantic_guess() -> None:
    result = make_layer().analyze(
        text="继续确认字段",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks == []
    assert result.clarification_required is True


def test_generic_pronoun_organize_without_context_does_not_guess_task() -> None:
    result = make_layer().analyze(
        text="把这些整理掉",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks == []
    assert result.clarification_required is True


def test_electronic_sheet_field_structure_survives_conversation_normalization() -> None:
    result = make_layer().analyze(
        text="这份电子表字段组成看一下",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = result.tasks[0]
    assert task.task_type == "FILE_STRUCTURE_EXTRACT"
    assert task.missing_inputs == []
    assert result.clarification_required is False


def test_negated_reminder_does_not_add_forbidden_monitoring_task() -> None:
    result = make_layer().analyze(
        text="本轮不做提醒，先生成活动海报",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in result.tasks] == ["MULTIMEDIA_GENERATE"]
    assert result.clarification_required is False


def test_change_policy_recalculate_recovers_previous_calculation_context() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-CALC-POLICY-001",
                    "task_type": "RULE_CALCULATION_COMMISSION",
                    "task_description": "计算销售提成",
                    "source_text": "计算销售提成",
                    "action": "计算",
                    "object": "销售提成",
                    "required_inputs": ["calculation_policy:现行提成口径"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="换个口径再算一遍",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["RULE_CALCULATION_COMMISSION"]
    assert analysis.result.tasks[0].task_id == "TASK-CALC-POLICY-001"
    assert analysis.result.clarification_required is True
    assert analysis.result.tasks[0].missing_inputs == ["calculation_policy"]
    assert analysis.debug["context_resolution"]["family"] == "calculate"
    assert analysis.debug["final_decision"]["selected_by"] == "context_recovery"


def test_polish_followup_recovers_previous_document_context() -> None:
    layer = make_layer(
        {
            "conversation_context": [
                {
                    "task_id": "TASK-DOC-POLISH-001",
                    "task_type": "DOCUMENT_GENERATE",
                    "task_description": "生成渠道经营复盘报告",
                    "source_text": "生成渠道经营复盘报告",
                    "action": "生成",
                    "object": "渠道经营复盘报告",
                    "required_inputs": ["document_type:报告", "topic:渠道经营"],
                }
            ],
            "project_context": [],
            "user_project_context": [],
        }
    )

    analysis = layer.analyze_with_debug(
        text="接着润色一下",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["DOCUMENT_GENERATE"]
    assert analysis.result.tasks[0].task_id == "TASK-DOC-POLISH-001"
    assert analysis.debug["context_resolution"]["family"] == "content_edit"
    assert analysis.debug["final_decision"]["selected_by"] == "context_recovery"
