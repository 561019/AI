import json
from datetime import UTC, datetime
from uuid import uuid4

from app.services.conversation_understanding import ConversationUnderstandingLayer
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer


class FakeModelGateway:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.prompts.append(messages[0]["content"])
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def task_payload(
    *,
    task_type: str,
    engine_code: str,
    target_engine: str,
    task_name: str = "模型识别任务",
    confidence: float = 0.86,
) -> dict:
    return {
        "task_id": str(uuid4()),
        "task_name": task_name,
        "task_type": task_type,
        "target_engine": target_engine,
        "engine_code": engine_code,
        "required_inputs": [],
        "missing_inputs": [],
        "dependencies": [],
        "execution_order": 1,
        "confidence": confidence,
    }


def result_payload(text: str, tasks: list[dict], *, confidence: float = 0.86) -> dict:
    return {
        "request_id": str(uuid4()),
        "original_text": text,
        "intent_category": "流程办理型" if tasks else "待澄清",
        "tasks": tasks,
        "clarification_required": not tasks,
        "clarification_questions": ["当前请求不属于已注册能力，请确认具体业务操作。"] if not tasks else [],
        "analysis_level": 3,
        "overall_confidence": confidence if tasks else 0,
        "created_at": datetime.now(UTC).isoformat(),
    }


def envelope(text: str, tasks: list[dict], evidence: list[str]) -> dict:
    return {
        "result": result_payload(text, tasks),
        "evidence_spans": [
            {"task_index": index, "evidence_span": value}
            for index, value in enumerate(evidence)
        ],
    }


def make_standard_analyzer(response: dict) -> StandardIntentAnalyzer:
    registry = FunctionRegistryCatalog()
    llm = LLMTaskAnalyzer(
        model_gateway=FakeModelGateway([response]),
        registry=registry,
    )
    return StandardIntentAnalyzer(
        registry=registry,
        semantic_matcher=None,
        llm_analyzer=llm,
        intent_record_service=None,
    )


def test_missing_implicit_evidence_position_is_kept_unknown() -> None:
    registry = FunctionRegistryCatalog()
    layer = ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=registry,
            semantic_matcher=None,
            llm_analyzer=None,
            intent_record_service=None,
        )
    )
    source_text = "known source text"

    assert layer._source_start_for_evidence(source_text, "missing span") is None
    assert layer._source_order_key(source_text, "missing span") == len(source_text)


def test_level3_accepts_registered_task_with_exact_source_evidence() -> None:
    text = "把采购审批跑起来"
    task = task_payload(
        task_type="WORKFLOW_START",
        engine_code="ENG_WORKFLOW_EXECUTION",
        target_engine="流程执行引擎",
    )
    analyzer = make_standard_analyzer(envelope(text, [task], [text]))

    analysis = analyzer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-valid-001",
    )

    assert analysis.result.tasks[0].task_type == "WORKFLOW_START"
    assert analysis.result.analysis_level == 3
    assert analysis.debug["level3_result"]["validation"]["accepted"] is True
    assert analysis.debug["final_decision"]["selected_by"] == "llm"


def test_level3_maps_unregistered_task_type_to_general_task() -> None:
    text = "把这个特殊事项办妥"
    task = task_payload(
        task_type="HOTEL_BOOKING",
        engine_code="ENG_TRAVEL",
        target_engine="差旅引擎",
        task_name="预订酒店",
    )
    analyzer = make_standard_analyzer(envelope(text, [task], [text]))

    analysis = analyzer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-invalid-task-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["GENERAL_TASK"]
    assert analysis.result.clarification_required is False
    assert analysis.debug["level3_result"]["validation"]["rejection_reasons"] == []
    assert (
        "unregistered_task_type_mapped_to_general_task:0:HOTEL_BOOKING"
        in analysis.debug["level3_result"]["validation"]["contract_corrections"]
    )
    assert analysis.debug["final_decision"]["selected_by"] == "llm"


def test_level3_prompt_allows_general_task_for_unknown_chinese_tasks() -> None:
    text = "帮我预订明天去上海的酒店"
    analyzer = make_standard_analyzer(envelope(text, [], []))

    analyzer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-general-prompt-001",
    )

    prompt = analyzer.llm_analyzer.model_gateway.prompts[0]
    assert "GENERAL_TASK" in prompt
    assert "clear current Chinese task outside the specialized task_type list" in prompt


def test_contract_confirmation_message_reaches_l3_general_task_instead_of_document_parse() -> None:
    text = "给李经理发一条确认合同已收到的短信"
    task = task_payload(
        task_type="GENERAL_TASK",
        engine_code="TASKLIST_GENERAL",
        target_engine="通用任务清单",
        task_name="发送确认合同已收到的短信",
    )
    analyzer = make_standard_analyzer(envelope(text, [task], [text]))

    analysis = analyzer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-general-message-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["GENERAL_TASK"]
    assert analysis.debug["final_decision"]["selected_by"] == "llm"
    assert analysis.debug["level1_rule_result"]["matched"] is False


def test_cancel_future_meeting_is_current_general_task_not_scope_exclusion() -> None:
    text = "把明天的采购评审会议取消掉"
    task = task_payload(
        task_type="GENERAL_TASK",
        engine_code="TASKLIST_GENERAL",
        target_engine="通用任务清单",
        task_name="取消明天的采购评审会议",
    )
    analyzer = make_standard_analyzer(envelope(text, [task], [text]))

    analysis = analyzer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-general-cancel-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == ["GENERAL_TASK"]
    assert analysis.debug["final_decision"]["selected_by"] == "llm"
    assert analysis.debug["scope_filter"]["current_scope_empty"] is False


def test_level3_ignores_obsolete_engine_fields_when_task_type_is_registered() -> None:
    text = "把采购审批跑起来"
    task = task_payload(
        task_type="WORKFLOW_START",
        engine_code="ENG_CONTENT_OUTPUT",
        target_engine="内容产出引擎",
    )
    analyzer = make_standard_analyzer(envelope(text, [task], [text]))

    analysis = analyzer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-engine-mismatch-001",
    )

    assert analysis.result.tasks[0].task_type == "WORKFLOW_START"
    assert analysis.debug["level3_result"]["validation"]["accepted"] is True
    assert analysis.debug["level3_result"]["validation"]["rejection_reasons"] == []


def test_level3_rejects_missing_or_fabricated_evidence() -> None:
    text = "把采购审批跑起来"
    task = task_payload(
        task_type="WORKFLOW_START",
        engine_code="ENG_WORKFLOW_EXECUTION",
        target_engine="流程执行引擎",
    )
    missing = make_standard_analyzer(envelope(text, [task], []))
    fabricated = make_standard_analyzer(envelope(text, [task], ["用户没有说过的内容"]))

    missing_analysis = missing.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-missing-evidence-001",
    )
    fabricated_analysis = fabricated.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-fabricated-evidence-001",
    )

    assert missing_analysis.result.tasks == []
    assert "evidence_count_mismatch" in missing_analysis.debug["level3_result"]["validation"]["rejection_reasons"]
    assert fabricated_analysis.result.tasks == []
    fabricated_reasons = fabricated_analysis.debug["level3_result"]["validation"]["rejection_reasons"]
    assert "evidence_not_in_source:0" in fabricated_reasons


def test_level3_accepts_explicit_unsupported_rejection() -> None:
    text = "帮我预订明天去上海的酒店"
    analyzer = make_standard_analyzer(envelope(text, [], []))

    analysis = analyzer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="llm-unsupported-001",
    )

    assert analysis.result.tasks == []
    assert analysis.result.clarification_required is True
    assert analysis.debug["level3_result"]["validation"]["accepted"] is True
    assert analysis.debug["final_decision"]["selected_by"] == "llm_safe_rejection"


def test_long_context_zero_candidate_uses_implicit_semantic_fallback() -> None:
    implicit_text = "领导明天要一份能看出华东为什么下滑的材料"
    text = (
        "公司近期一直在讨论年度规划，前面的组织安排和沟通经过都只是背景。"
        "现有材料记录了历史表现，没有提出需要重复执行的动作。"
        "参与人员和会议时间已经另行记录，这些信息不构成新的任务。"
        "历史沟通内容只用于解释事情经过，不应被当成当前操作要求。"
        + implicit_text
    )
    implicit_response = {
        "candidates": [
            {
                "normalized_text": "分析华东销售下降原因",
                "evidence_span": implicit_text,
                "confidence": 0.88,
                "depends_on_previous": False,
            },
            {
                "normalized_text": "生成管理层分析报告",
                "evidence_span": implicit_text,
                "confidence": 0.85,
                "depends_on_previous": True,
            },
        ],
        "unsupported": False,
        "reason": None,
    }
    registry = FunctionRegistryCatalog()
    llm = LLMTaskAnalyzer(
        model_gateway=FakeModelGateway([implicit_response]),
        registry=registry,
    )
    layer = ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=registry,
            semantic_matcher=None,
            llm_analyzer=llm,
            intent_record_service=None,
        )
    )

    analysis = layer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="implicit-long-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == [
        "DATA_ANALYSIS_PROBLEM",
        "DOCUMENT_GENERATE",
    ]
    assert analysis.result.tasks[1].dependencies == [analysis.result.tasks[0].task_id]
    assert analysis.debug["implicit_task_fallback"]["attempted"] is True
    assert len(analysis.debug["implicit_task_fallback"]["accepted_candidates"]) == 2
    assert all(
        segment["selected_by"] == "llm_implicit_fallback"
        for segment in analysis.debug["conversation_understanding"]["segments"]
    )


def test_implicit_fallback_rejects_candidate_without_source_evidence() -> None:
    text = (
        "这是一段较长的业务背景，内容主要介绍组织关系和过去的沟通过程。"
        "参与人员和会议安排已经记录，不需要再次处理。"
        "此前留存的历史资料只用于说明情况，不构成当前任务。"
        "领导明天要一份能说明现状的材料，但原文没有提出预订酒店。"
    )
    response = {
        "candidates": [
            {
                "normalized_text": "预订酒店",
                "evidence_span": "请预订酒店",
                "confidence": 0.91,
                "depends_on_previous": False,
            }
        ],
        "unsupported": False,
        "reason": None,
    }
    registry = FunctionRegistryCatalog()
    llm = LLMTaskAnalyzer(model_gateway=FakeModelGateway([response]), registry=registry)
    layer = ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=registry,
            semantic_matcher=None,
            llm_analyzer=llm,
            intent_record_service=None,
        )
    )

    analysis = layer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="implicit-invalid-evidence-001",
    )

    assert analysis.result.tasks == []
    assert analysis.result.clarification_required is True
    assert "implicit_evidence_not_in_source:0" in analysis.debug["implicit_task_fallback"]["rejection_reasons"]


def test_implicit_fallback_keeps_unsupported_request_as_empty_task_list() -> None:
    text = (
        "前面是活动背景和参会人员介绍，不包含任何业务执行要求。"
        "历史材料已经由其他团队保管，这一段也不构成当前任务。"
        "会议日期和地点只是说明信息，不要求系统进行任何操作。"
        "实际诉求是希望系统替我预订明天去上海的酒店，这不属于当前业务能力。"
    )
    response = {
        "candidates": [],
        "unsupported": True,
        "reason": "no_registered_capability",
    }
    registry = FunctionRegistryCatalog()
    llm = LLMTaskAnalyzer(model_gateway=FakeModelGateway([response]), registry=registry)
    layer = ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=registry,
            semantic_matcher=None,
            llm_analyzer=llm,
            intent_record_service=None,
        )
    )

    analysis = layer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="implicit-unsupported-001",
    )

    assert analysis.result.tasks == []
    assert analysis.result.clarification_required is True
    assert analysis.debug["implicit_task_fallback"]["unsupported_reasons"] == [
        "no_registered_capability"
    ]


def test_implicit_fallback_adds_uncovered_task_beside_explicit_task() -> None:
    implicit_text = "拿到这些以后，领导要一份能看出华东为什么下滑的材料"
    text = (
        "年度复盘的组织安排和参会信息只是背景，不构成任务。"
        "请查询今年各区域销售数据。"
        "历史沟通经过已经留档，不需要再次处理。"
        + implicit_text
    )
    response = {
        "candidates": [
            {
                "normalized_text": "分析华东销售下降原因",
                "evidence_span": implicit_text,
                "confidence": 0.88,
                "depends_on_previous": True,
            },
            {
                "normalized_text": "生成管理层分析报告",
                "evidence_span": implicit_text,
                "confidence": 0.85,
                "depends_on_previous": True,
            },
        ],
        "unsupported": False,
        "reason": None,
    }
    registry = FunctionRegistryCatalog()
    llm = LLMTaskAnalyzer(model_gateway=FakeModelGateway([response]), registry=registry)
    layer = ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=registry,
            semantic_matcher=None,
            llm_analyzer=llm,
            intent_record_service=None,
        )
    )

    analysis = layer.analyze_with_debug(
        text=text,
        user_id="user-001",
        conversation_id="implicit-mixed-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == [
        "DATA_QUERY_FETCH",
        "DATA_ANALYSIS_PROBLEM",
        "DOCUMENT_GENERATE",
    ]
    assert analysis.result.tasks[1].dependencies == [analysis.result.tasks[0].task_id]
    assert analysis.result.tasks[2].dependencies == [analysis.result.tasks[1].task_id]
    assert [
        segment["selected_by"]
        for segment in analysis.debug["conversation_understanding"]["segments"]
    ] == [
        "deterministic_extractor",
        "llm_implicit_fallback",
        "llm_implicit_fallback",
    ]
