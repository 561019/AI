import json
from pathlib import Path

from app.services.conversation_understanding import ConversationUnderstandingLayer
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer


CASE_PATH = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "long_text_regression"
    / "sales_operating_review.json"
)
LEGACY_DATASET_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "long_text_dataset.json"


def make_layer() -> ConversationUnderstandingLayer:
    return ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=FunctionRegistryCatalog(),
            semantic_matcher=None,
            llm_analyzer=None,
            intent_record_service=None,
        )
    )


def test_sales_operating_review_long_text_regression() -> None:
    case = json.loads(CASE_PATH.read_text(encoding="utf-8"))[0]
    analysis = make_layer().analyze_with_debug(
        text=case["text"],
        user_id="regression-user",
        conversation_id=case["id"],
    )
    result = analysis.result

    assert len(result.tasks) <= case["max_task_count"]
    assert {task.task_name for task in result.tasks} == set(case["required_task_names"])
    assert [task.task_type for task in result.tasks] == case["expected_tasks"]
    assert not ({task.task_type for task in result.tasks} & set(case["forbidden_task_types"]))
    assert result.clarification_questions == case["expected_questions"]

    extraction = analysis.debug["long_context_extraction"]
    assert [candidate["action"] for candidate in extraction["merged_candidates"]] == case["expected_actions"]
    assert [candidate["action"] for candidate in extraction["negated_candidates"]] == ["monitor"]
    reason_candidate = next(
        candidate
        for candidate in extraction["merged_candidates"]
        if candidate["normalized_text"] == "分析销售下降原因"
    )
    assert len(reason_candidate["merged_sources"]) == 3

    state_details = [
        detail
        for segment in analysis.debug["segment_analyses"]
        for detail in segment["debug"]["input_validation_result"]["input_state_details"]
    ]
    states = {detail["input_name"]: detail["state"] for detail in state_details}
    assert states["calculation_policy"] == "uncertain"
    assert states["data_source"] == "conflict"
    assert "calculation_object" not in states
    assert "statistical_range" not in states

    unresolved_questions = {
        detail["question"]
        for detail in state_details
        if detail["state"] in {"missing", "uncertain", "conflict"}
    }
    assert set(result.clarification_questions) <= unresolved_questions


def test_long_text_complaint_plan_keeps_complaint_organize_task() -> None:
    case = _legacy_case("long-009")
    result = make_layer().analyze(
        text=case["text"],
        user_id="regression-user",
        conversation_id=case["id"],
    )

    assert [task.task_type for task in result.tasks] == case["expected_tasks"]


def test_long_text_document_parse_keeps_structure_extraction_task() -> None:
    case = _legacy_case("long-014")
    result = make_layer().analyze(
        text=case["text"],
        user_id="regression-user",
        conversation_id=case["id"],
    )

    assert [task.task_type for task in result.tasks] == case["expected_tasks"]


def _legacy_case(case_id: str) -> dict:
    return next(
        case
        for case in json.loads(LEGACY_DATASET_PATH.read_text(encoding="utf-8"))
        if case["id"] == case_id
    )
