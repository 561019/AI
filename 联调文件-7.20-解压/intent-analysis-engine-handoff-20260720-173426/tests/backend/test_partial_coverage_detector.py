import json
from datetime import UTC, datetime
from uuid import uuid4

from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer
from app.services.intent_analysis_engine.partial_coverage_detector import (
    MatchedTaskBinding,
    PartialCoverageDetector,
)


class FakeModelGateway:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def analyze(self, *, messages: list[dict[str, str]], response_schema: dict | None = None) -> str:
        self.prompts.append(messages[0]["content"])
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


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


def make_analyzer(gateway: FakeModelGateway) -> StandardIntentAnalyzer:
    registry = FunctionRegistryCatalog()
    return StandardIntentAnalyzer(
        registry=registry,
        semantic_matcher=None,
        llm_analyzer=LLMTaskAnalyzer(model_gateway=gateway, registry=registry),
        intent_record_service=None,
    )


def test_partial_coverage_sends_only_uncovered_segments_to_l3_and_merges_tasks() -> None:
    gateway = FakeModelGateway(
        [
            envelope(
                "整理销售数据",
                [task_payload("DATA_QUERY_FETCH", "获取业务数据")],
                ["整理销售数据"],
            ),
            envelope(
                "分析下降原因",
                [task_payload("DATA_ANALYSIS_PROBLEM", "问题分析")],
                ["分析下降原因"],
            ),
        ]
    )
    analyzer = make_analyzer(gateway)

    analysis = analyzer.analyze_with_debug(
        text="整理销售数据，分析下降原因，生成报告",
        user_id="user-001",
        conversation_id="partial-001",
    )

    assert [task.task_type for task in analysis.result.tasks] == [
        "DATA_QUERY_FETCH",
        "DATA_ANALYSIS_PROBLEM",
        "DOCUMENT_GENERATE",
    ]
    partial_debug = analysis.debug["partial_coverage"]
    assert partial_debug["coverage_rate"] == 1 / 3
    assert [segment["text"] for segment in partial_debug["uncovered_segments"]] == [
        "整理销售数据",
        "分析下降原因",
    ]
    assert partial_debug["llm_called"] is True
    assert partial_debug["l3_compensation_success"] is True
    assert len(gateway.prompts) == 2
    assert "User input:\n整理销售数据" in gateway.prompts[0]
    assert "User input:\n分析下降原因" in gateway.prompts[1]
    assert "User input:\n整理销售数据，分析下降原因，生成报告" not in "\n".join(gateway.prompts)


def test_full_level1_coverage_does_not_call_l3() -> None:
    gateway = FakeModelGateway([])
    analyzer = make_analyzer(gateway)

    analysis = analyzer.analyze_with_debug(
        text="生成销售报表",
        user_id="user-001",
        conversation_id="partial-002",
    )

    assert analysis.result.tasks[0].task_type == "DOCUMENT_GENERATE"
    assert analysis.debug["partial_coverage"]["coverage_rate"] == 1.0
    assert analysis.debug["partial_coverage"]["uncovered_segments"] == []
    assert analysis.debug["partial_coverage"]["llm_called"] is False
    assert analysis.debug["level3_result"] is None
    assert gateway.prompts == []


def test_unsplittable_unmatched_request_enters_l3_clarification() -> None:
    gateway = FakeModelGateway([envelope("帮我看看销售情况", [], [])])
    analyzer = make_analyzer(gateway)

    analysis = analyzer.analyze_with_debug(
        text="帮我看看销售情况",
        user_id="user-001",
        conversation_id="partial-003",
    )

    assert analysis.result.tasks == []
    assert analysis.result.clarification_required is True
    assert analysis.debug["level3_result"]["validation"]["accepted"] is True
    assert analysis.debug["final_decision"]["selected_by"] == "llm_safe_rejection"
    assert len(gateway.prompts) == 1


def test_detector_requires_explicit_task_to_segment_binding() -> None:
    detector = PartialCoverageDetector()
    segments = detector.segment("生成销售报表")
    invalid_binding = MatchedTaskBinding(
        task_id="task-001",
        task_type="DOCUMENT_GENERATE",
        task_description="生成业务文档",
        segment_index=0,
        segment_text="销售报表",
        source="rule",
    )

    result = detector.detect(
        original_text="生成销售报表",
        segments=segments,
        matched_tasks=[invalid_binding],
    )

    assert result.coverage_rate == 0
    assert [segment.text for segment in result.uncovered_segments] == ["生成销售报表"]
    assert result.need_llm is True
