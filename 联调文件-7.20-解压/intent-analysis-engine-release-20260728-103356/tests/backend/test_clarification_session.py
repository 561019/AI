from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.clarification import ClarificationSessionManager


def make_analyzer() -> StandardIntentAnalyzer:
    return StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )


def test_clarification_answer_recovers_original_task_without_new_task_id() -> None:
    analyzer = make_analyzer()
    manager = ClarificationSessionManager()
    initial = analyzer.analyze(
        text="计算销售提成",
        user_id="user-001",
        conversation_id="clarification-001",
    )
    initial = manager.create_sessions_for_result(initial)
    original_task = initial.tasks[0]

    assert original_task.clarification_required is True
    assert original_task.clarification_session_id

    recovered = manager.answer(
        clarification_session_id=original_task.clarification_session_id,
        answer="使用2026规则，华东区域，ERP数据",
        validator=analyzer.input_validator,
    )

    assert recovered.task_id == original_task.task_id
    assert recovered.task.task_id == original_task.task_id
    assert recovered.status == "ready"
    assert recovered.missing_inputs == []
    assert recovered.final_inputs["calculation_policy"] == "2026规则"
    assert "data_scope" not in recovered.final_inputs
    assert "data_source" not in recovered.final_inputs
