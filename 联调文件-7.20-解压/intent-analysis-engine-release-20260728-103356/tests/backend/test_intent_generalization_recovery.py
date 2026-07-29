import json
from datetime import UTC, datetime
from uuid import uuid4

from evaluation_runner import build_analyzer
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer


class FakeModelGateway:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def analyze(self, *, messages: list[dict[str, str]], response_schema: dict | None = None):
        self.prompts.append(messages[0]["content"])

        class Response:
            def __init__(self, payload: dict) -> None:
                self.content = json.dumps(payload, ensure_ascii=False)

        return Response(self.responses.pop(0))


class RawFakeModelGateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def analyze(self, *, messages: list[dict[str, str]], response_schema: dict | None = None):
        self.prompts.append(messages[0]["content"])

        class Response:
            def __init__(self, content: str) -> None:
                self.content = content

        return Response(self.responses.pop(0))


def task_payload(task_type: str, task_name: str, *, confidence: float = 0.86) -> dict:
    return {
        "task_id": str(uuid4()),
        "task_type": task_type,
        "task_description": task_name,
        "required_inputs": [],
        "missing_inputs": [],
        "dependencies": [],
        "confidence": confidence,
    }


def envelope(text: str, tasks: list[dict], evidence: list[str] | None = None) -> dict:
    return {
        "result": {
            "request_id": str(uuid4()),
            "original_text": text,
            "intent_category": "复合任务型" if tasks else "待澄清",
            "tasks": tasks,
            "clarification_required": not tasks,
            "clarification_questions": ["请明确要处理的业务对象和具体动作。"] if not tasks else [],
            "analysis_level": 3,
            "overall_confidence": min((task.get("confidence", 0.86) for task in tasks), default=0),
            "created_at": datetime.now(UTC).isoformat(),
        },
        "evidence_spans": [
            {"task_index": index, "evidence_span": span}
            for index, span in enumerate(evidence if evidence is not None else [text])
        ],
    }


def make_rule_only_analyzer() -> StandardIntentAnalyzer:
    return StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )


def make_llm_analyzer(gateway: FakeModelGateway) -> StandardIntentAnalyzer:
    registry = FunctionRegistryCatalog()
    return StandardIntentAnalyzer(
        registry=registry,
        semantic_matcher=None,
        llm_analyzer=LLMTaskAnalyzer(model_gateway=gateway, registry=registry),
        intent_record_service=None,
    )


def test_reason_analysis_sentence_is_not_over_decomposed() -> None:
    analyzer = make_rule_only_analyzer()

    analysis = analyzer.analyze_with_debug(
        text="分析华北退款量突然增加的原因",
        user_id="generalization-test",
        conversation_id="reason-analysis",
    )

    assert analysis.debug["level1_rule_result"]["rule"] == "problem_analysis"
    assert [task.task_type for task in analysis.result.tasks] == ["DATA_ANALYSIS_PROBLEM"]
    assert analysis.result.clarification_required is False


def test_natural_sort_and_previous_period_comparison_hit_rules() -> None:
    analyzer = make_rule_only_analyzer()

    sort_result = analyzer.analyze_with_debug(
        text="按风险分从高到低排一下客户",
        user_id="generalization-test",
        conversation_id="sort-rule",
    )
    yoy_result = analyzer.analyze_with_debug(
        text="跟去年同期对比一下本月收入",
        user_id="generalization-test",
        conversation_id="yoy-rule",
    )
    mom_result = analyzer.analyze_with_debug(
        text="和上个月比一下本周订单量变化",
        user_id="generalization-test",
        conversation_id="mom-rule",
    )

    assert [task.task_type for task in sort_result.result.tasks] == ["DATA_SORT"]
    assert sort_result.debug["level1_rule_result"]["rule"] == "sort"
    assert [task.task_type for task in yoy_result.result.tasks] == ["DATA_ANALYSIS_YOY"]
    assert yoy_result.debug["level1_rule_result"]["rule"] == "period_comparison"
    assert [task.task_type for task in mom_result.result.tasks] == ["DATA_ANALYSIS_MOM"]
    assert mom_result.debug["level1_rule_result"]["rule"] == "period_comparison"


def test_semantic_business_short_phrases_generalize_without_unnecessary_clarification() -> None:
    analyzer = build_analyzer(semantic_mode="local", llm_mode="off", semantic_threshold=0.50)

    cases = [
        ("区域销售周报", "DOCUMENT_GENERATE"),
        ("经营复盘材料", "DOCUMENT_GENERATE"),
        ("高风险客户名单", "DATA_FILTER"),
        ("渠道投入产出复盘", "DATA_ANALYSIS_PROBLEM"),
        ("供应链周转情况", "DATA_ANALYSIS_PROBLEM"),
    ]

    for text, expected_task_type in cases:
        analysis = analyzer.analyze_with_debug(
            text=text,
            user_id="generalization-test",
            conversation_id=f"semantic-{expected_task_type}",
        )

        assert [task.task_type for task in analysis.result.tasks] == [expected_task_type], text
        assert analysis.result.clarification_required is False, text


def test_chinese_improvement_plan_output_phrase_hits_content_rule() -> None:
    analyzer = make_rule_only_analyzer()

    analysis = analyzer.analyze_with_debug(
        text="结合客户意见出整改方案",
        user_id="generalization-test",
        conversation_id="improvement-plan",
    )

    assert analysis.debug["level1_rule_result"]["rule"] == "content_output"
    assert [task.task_type for task in analysis.result.tasks] == ["IMPROVEMENT_PLAN_GENERATE"]
    assert analysis.result.tasks[0].missing_inputs == []
    assert analysis.result.clarification_required is False


def test_data_object_does_not_satisfy_query_data_source_for_list_requests() -> None:
    analyzer = make_rule_only_analyzer()

    result = analyzer.analyze(
        text="客户清单帮我调出来看看",
        user_id="generalization-test",
        conversation_id="query-source",
    )

    assert [task.task_type for task in result.tasks] == ["DATA_QUERY_FETCH"]
    assert result.tasks[0].missing_inputs == ["data_source"]
    assert result.clarification_required is True


def test_l3_empty_clarification_can_recover_supported_business_judgment_task() -> None:
    gateway = FakeModelGateway([envelope("对这批回款线索给一个经营处置判断", [], [])])
    analyzer = make_llm_analyzer(gateway)

    analysis = analyzer.analyze_with_debug(
        text="对这批回款线索给一个经营处置判断",
        user_id="generalization-test",
        conversation_id="l3-judgment",
    )

    assert len(gateway.prompts) == 1
    assert analysis.debug["final_decision"]["selected_by"] == "llm_guardrail_recovery"
    assert [task.task_type for task in analysis.result.tasks] == ["DATA_ANALYSIS_PROBLEM"]
    assert analysis.result.clarification_required is False


def test_l3_invalid_response_can_recover_supported_business_investment_decision() -> None:
    gateway = RawFakeModelGateway(["not-json"])
    analyzer = make_llm_analyzer(gateway)

    analysis = analyzer.analyze_with_debug(
        text="\u76d8\u4e00\u4e0b\u6e20\u9053\u6295\u5165\u662f\u5426\u503c\u5f97\u7ee7\u7eed\u52a0\u7801",
        user_id="generalization-test",
        conversation_id="l3-investment-decision",
    )

    assert len(gateway.prompts) == 1
    assert analysis.debug["final_decision"]["selected_by"] == "llm_guardrail_recovery"
    assert [task.task_type for task in analysis.result.tasks] == ["DATA_ANALYSIS_PROBLEM"]
    assert analysis.result.clarification_required is False


def test_l3_empty_clarification_can_recover_supported_english_document_task() -> None:
    gateway = FakeModelGateway(
        [
            envelope("Create a regional operating review memo", [], []),
            envelope("Turn renewal notes into a manager review memo", [], []),
        ]
    )
    analyzer = make_llm_analyzer(gateway)

    analysis = analyzer.analyze_with_debug(
        text="Create a regional operating review memo",
        user_id="generalization-test",
        conversation_id="l3-english-document",
    )
    transform_analysis = analyzer.analyze_with_debug(
        text="Turn renewal notes into a manager review memo",
        user_id="generalization-test",
        conversation_id="l3-english-document-transform",
    )

    assert len(gateway.prompts) == 2
    assert analysis.debug["final_decision"]["selected_by"] == "llm_guardrail_recovery"
    assert [task.task_type for task in analysis.result.tasks] == ["DOCUMENT_GENERATE"]
    assert analysis.result.clarification_required is False
    assert [task.task_type for task in transform_analysis.result.tasks] == ["DOCUMENT_GENERATE"]
    assert transform_analysis.result.clarification_required is False


def test_l3_empty_clarification_can_recover_supported_english_compound_tasklist() -> None:
    gateway = FakeModelGateway([envelope("Need tasks: retrieve CRM accounts, rank risk, draft remediation plan", [], [])])
    analyzer = make_llm_analyzer(gateway)

    analysis = analyzer.analyze_with_debug(
        text="Need tasks: retrieve CRM accounts, rank risk, draft remediation plan",
        user_id="generalization-test",
        conversation_id="l3-english-compound",
    )

    assert len(gateway.prompts) == 1
    assert analysis.debug["final_decision"]["selected_by"] == "llm_guardrail_recovery"
    assert [task.task_type for task in analysis.result.tasks] == [
        "EXTERNAL_DATA_FETCH",
        "DATA_SORT",
        "IMPROVEMENT_PLAN_GENERATE",
    ]
    assert analysis.result.clarification_required is False


def test_partial_coverage_recovers_english_rank_and_summary_fragments_after_l3_call() -> None:
    gateway = FakeModelGateway(
        [
            envelope("rank risk", [], []),
            envelope("summarized by risk tier", [], []),
        ]
    )
    analyzer = make_llm_analyzer(gateway)

    rank_analysis = analyzer.analyze_with_debug(
        text="从CRM获取客户数据, rank risk",
        user_id="generalization-test",
        conversation_id="partial-rank",
    )
    summary_analysis = analyzer.analyze_with_debug(
        text="从CRM获取客户数据, summarized by risk tier",
        user_id="generalization-test",
        conversation_id="partial-summary",
    )

    assert len(gateway.prompts) == 2
    assert [task.task_type for task in rank_analysis.result.tasks] == ["EXTERNAL_DATA_FETCH", "DATA_SORT"]
    assert rank_analysis.result.clarification_required is False
    assert [task.task_type for task in summary_analysis.result.tasks] == [
        "EXTERNAL_DATA_FETCH",
        "DATA_AGGREGATION_SUMMARY",
    ]
    assert summary_analysis.result.clarification_required is False
