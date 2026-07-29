import json

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.intent_analysis_engine import FunctionRegistryCatalog
from app.services.intent_analysis_engine.input_validator import QUESTION_BY_INPUT
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer
from app.services.model_gateway.contract_validator import LLMResponseContractValidator


def make_result(tasks: list[TaskItem], *, clarification_required: bool = False) -> IntentAnalysisResult:
    return IntentAnalysisResult(
        tasks=tasks,
        clarification_required=clarification_required,
        clarification_questions=[],
        analysis_level=3,
        overall_confidence=min((task.confidence for task in tasks), default=0.9),
    )


def test_contract_enables_clarification_when_missing_inputs_exist() -> None:
    task = TaskItem(
        task_type="RULE_CALCULATION_COMMISSION",
        task_description="计算销售提成",
        action="计算",
        object="销售提成",
        required_inputs=["calculation_basis:销售业绩"],
        missing_inputs=["calculation_policy"],
        dependencies=[],
        confidence=0.92,
    )

    validated = LLMResponseContractValidator().validate(make_result([task])).result

    assert validated.clarification_required is True
    assert "请确认销售提成适用的政策版本（去年版或今年调整版）。" in validated.clarification_questions


def test_contract_recomputes_missing_inputs_from_task_schema() -> None:
    task = TaskItem(
        task_type="DATA_ANALYSIS_PROBLEM",
        task_description="Analyze business operation problem",
        action="analyze",
        object="business operation problem",
        required_inputs=["analysis_object", "analysis_method"],
        missing_inputs=["analysis_object", "analysis_method"],
        clarification_required=True,
        clarification_questions=[
            "What specific business operation problem do you want to analyze?",
            "What analysis method should be used?",
        ],
        dependencies=[],
        confidence=0.7,
    )

    outcome = LLMResponseContractValidator().validate(make_result([task]))
    validated = outcome.result.tasks[0]

    assert validated.missing_inputs == ["analysis_object"]
    assert validated.clarification_required is True
    assert validated.clarification_questions == [QUESTION_BY_INPUT["analysis_object"]]
    assert "analysis_method" not in outcome.result.clarification_questions
    assert "missing_inputs_recomputed_from_task_type_schema:0" in outcome.corrections


def test_contract_adds_report_dependency_on_analysis_task() -> None:
    analysis = TaskItem(
        task_type="DATA_ANALYSIS_PROBLEM",
        task_description="分析销售下降原因",
        action="分析",
        object="销售下降原因",
        required_inputs=[],
        missing_inputs=[],
        dependencies=[],
        confidence=0.95,
    )
    report = TaskItem(
        task_type="DOCUMENT_GENERATE",
        task_description="生成经营分析报告",
        action="生成",
        object="经营分析报告",
        required_inputs=[],
        missing_inputs=[],
        dependencies=[],
        confidence=0.95,
    )

    outcome = LLMResponseContractValidator().validate(make_result([analysis, report]))

    assert outcome.result.tasks[1].dependencies == [analysis.task_id]
    assert "report_dependencies_added:1" in outcome.corrections


def test_contract_splits_merged_data_preparation_and_analysis_task() -> None:
    merged = TaskItem(
        task_type="DATA_ANALYSIS_PROBLEM",
        task_description="整理并分析销售数据",
        action="分析",
        object="销售数据",
        required_inputs=[],
        missing_inputs=[],
        dependencies=[],
        confidence=0.94,
    )

    outcome = LLMResponseContractValidator().validate(
        make_result([merged]),
        source_text="请先整理今年和去年同期的销售数据，然后分析销售数据。",
    )

    assert [task.task_description for task in outcome.result.tasks] == [
        "整理销售数据",
        "分析销售数据",
    ]
    assert outcome.result.tasks[0].task_type == "DATA_QUERY_FETCH"
    assert outcome.result.tasks[1].dependencies == [outcome.result.tasks[0].task_id]
    assert "data_preparation_task_inserted" in outcome.corrections
    assert outcome.evidence_spans_by_task_id[outcome.result.tasks[0].task_id] in (
        "整理今年和去年同期的销售数据",
        "整理今年和去年同期的销售数据",
    )


def test_contract_cleans_invalid_dependency_and_flags_empty_required_fields() -> None:
    task = TaskItem(
        task_type="",
        task_description="",
        action="分析",
        object="销售数据",
        required_inputs=["", "analysis_object:销售"],
        missing_inputs=[],
        dependencies=["missing-task-id"],
        confidence=0.8,
    )

    outcome = LLMResponseContractValidator().validate(make_result([task]))

    assert "empty_task_type:0" in outcome.errors
    assert "empty_task_description:0" in outcome.errors
    assert outcome.result.tasks[0].required_inputs == ["analysis_object:销售"]
    assert outcome.result.tasks[0].dependencies == []
    assert "unknown_dependency_removed:0" in outcome.corrections


def test_llm_analyzer_applies_contract_and_rebuilds_evidence_for_inserted_task() -> None:
    source_text = "请先整理今年和去年同期的销售数据，然后分析销售数据。"
    merged_task = {
        "task_type": "DATA_ANALYSIS_PROBLEM",
        "task_description": "整理并分析销售数据",
        "action": "分析",
        "object": "销售数据",
        "required_inputs": [],
        "missing_inputs": [],
        "dependencies": [],
        "confidence": 0.94,
    }

    class FakeGateway:
        def analyze(self, messages, response_schema=None):
            class Response:
                content = json.dumps(
                    {
                        "result": {
                            "tasks": [merged_task],
                            "clarification_required": False,
                            "clarification_questions": [],
                        },
                        "evidence_spans": [
                            {"task_index": 0, "evidence_span": "分析销售数据"},
                        ],
                    },
                    ensure_ascii=False,
                )

            return Response()

    outcome = LLMTaskAnalyzer(
        model_gateway=FakeGateway(),
        registry=FunctionRegistryCatalog(),
    ).analyze_with_validation(source_text, user_id="user-001")

    assert outcome.rejection_reasons == []
    assert [task.task_description for task in outcome.result.tasks] == [
        "整理销售数据",
        "分析销售数据",
    ]
    assert len(outcome.evidence_spans) == 2
    assert "data_preparation_task_inserted" in outcome.contract_corrections
