from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.llm import NeedConfirmationResult
from app.schemas.semantic import SemanticCandidate, SemanticResult
from app.schemas.task import TaskItem, TaskList
from app.services.intent_analyzer import IntentAnalyzer


USER_ID = "user-001"
CONVERSATION_ID = "conversation-001"


def make_task(
    function_code: str,
    *,
    function_name: str | None = None,
    intent_category: str = "report_generation",
    target_engine: str = "report_engine",
    parameters: dict | None = None,
    dependency: list[str] | None = None,
    priority: int = 1,
    confidence: float = 0.9,
) -> TaskItem:
    return TaskItem(
        function_code=function_code,
        function_name=function_name or function_code.replace("_", " ").title(),
        intent_category=intent_category,
        target_engine=target_engine,
        parameters=parameters or {},
        dependency=dependency or [],
        priority=priority,
        confidence=confidence,
    )


def make_task_list(
    *,
    level: int,
    tasks: list[TaskItem] | None = None,
    user_id: str = USER_ID,
    request_id: str = "draft-request",
    overall_confidence: float | None = None,
) -> TaskList:
    resolved_tasks = tasks or []
    confidence = (
        overall_confidence
        if overall_confidence is not None
        else min((task.confidence for task in resolved_tasks), default=0)
    )
    return TaskList(
        request_id=request_id,
        user_id=user_id,
        tasks=resolved_tasks,
        analysis_level=level,
        overall_confidence=confidence,
    )


def make_semantic_result(
    function_code: str,
    *,
    function_name: str | None = None,
    intent_category: str = "report_generation",
    target_engine: str = "report_engine",
    confidence: float = 0.82,
) -> SemanticResult:
    return SemanticResult.matched_result(
        candidates=[
            SemanticCandidate(
                function_code=function_code,
                function_name=function_name or function_code.replace("_", " ").title(),
                intent_category=intent_category,
                target_engine=target_engine,
                confidence=confidence,
                similarity_score=confidence,
            ),
            SemanticCandidate(
                function_code="LOWER_PRIORITY",
                function_name="Lower Priority",
                intent_category="noise",
                target_engine="noise_engine",
                confidence=max(confidence - 0.1, 0),
                similarity_score=max(confidence - 0.1, 0),
            ),
        ],
    )


def make_low_semantic_result(score: float = 0.4) -> SemanticResult:
    return SemanticResult.unmatched(
        candidates=[
            SemanticCandidate(
                function_code="LOW_CONFIDENCE",
                function_name="Low Confidence",
                intent_category="noise",
                target_engine="noise_engine",
                confidence=score,
                similarity_score=score,
            ),
        ],
    )


def build_analyzer(
    *,
    level1_result: TaskList,
    semantic_result: SemanticResult | None = None,
    llm_result: TaskList | NeedConfirmationResult | None = None,
    record_id: str = "record-final",
    rule_threshold: float = 0.9,
    semantic_threshold: float = 0.75,
) -> tuple[IntentAnalyzer, MagicMock, MagicMock, MagicMock, MagicMock]:
    level1_analyzer = MagicMock()
    level1_analyzer.analyze.return_value = level1_result

    semantic_matcher = MagicMock()
    semantic_matcher.analyze.return_value = semantic_result or SemanticResult.unmatched()

    llm_analyzer = MagicMock()
    llm_analyzer.analyze.return_value = llm_result or make_task_list(
        level=3,
        tasks=[
            make_task(
                "CONTENT_CREATE",
                function_name="Content Create",
                intent_category="content_creation",
                target_engine="content_engine",
                confidence=0.81,
            ),
        ],
    )

    intent_record_service = MagicMock()
    intent_record_service.record_intent_result.return_value = SimpleNamespace(id=record_id)

    analyzer = IntentAnalyzer(
        level1_analyzer=level1_analyzer,
        semantic_matcher=semantic_matcher,
        llm_analyzer=llm_analyzer,
        intent_record_service=intent_record_service,
        rule_threshold=rule_threshold,
        semantic_threshold=semantic_threshold,
    )
    return analyzer, level1_analyzer, semantic_matcher, llm_analyzer, intent_record_service


RULE_HIT_CASES = [
    ("create sales report", "REPORT_CREATE", "Report Create", "report_generation", "report_engine", 1.0),
    ("generate monthly report", "REPORT_CREATE", "Report Create", "report_generation", "report_engine", 0.98),
    ("query sales data", "DATA_QUERY", "Data Query", "intelligent_qa", "knowledge_qa_engine", 0.96),
    ("calculate commission", "CALCULATION", "Calculation", "rule_calculation", "rule_engine", 0.97),
    ("summarize product rows", "DATA_SUMMARY", "Data Summary", "data_processing", "data_engine", 0.95),
    ("draft customer notice", "CONTENT_CREATE", "Content Create", "content_creation", "content_engine", 0.94),
    ("create finance report", "REPORT_CREATE", "Report Create", "report_generation", "report_engine", 0.99),
    ("query payment data", "DATA_QUERY", "Data Query", "intelligent_qa", "knowledge_qa_engine", 0.93),
    ("calculate regional bonus", "CALCULATION", "Calculation", "rule_calculation", "rule_engine", 0.92),
    ("summarize order data", "DATA_SUMMARY", "Data Summary", "data_processing", "data_engine", 0.91),
    ("generate operations report", "REPORT_CREATE", "Report Create", "report_generation", "report_engine", 0.9),
    ("write meeting summary", "CONTENT_CREATE", "Content Create", "content_creation", "content_engine", 0.97),
    ("check reimbursement policy", "KNOWLEDGE_QA", "Knowledge QA", "intelligent_qa", "knowledge_qa_engine", 0.96),
    ("identify invoice image", "IMAGE_RECOGNITION", "Image Recognition", "image_recognition", "media_engine", 0.95),
    ("start approval workflow", "WORKFLOW_AGENT", "Workflow Agent", "workflow_agent", "workflow_engine", 0.94),
    ("parse uploaded document", "DOCUMENT_PARSE", "Document Parse", "data_processing", "document_engine", 0.93),
    ("generate risk report", "REPORT_CREATE", "Report Create", "report_generation", "report_engine", 0.92),
    ("query customer profile", "DATA_QUERY", "Data Query", "intelligent_qa", "knowledge_qa_engine", 0.91),
    ("calculate service fee", "CALCULATION", "Calculation", "rule_calculation", "rule_engine", 0.98),
    ("summarize daily metrics", "DATA_SUMMARY", "Data Summary", "data_processing", "data_engine", 0.97),
]


@pytest.mark.parametrize(
    ("text", "function_code", "function_name", "intent_category", "target_engine", "confidence"),
    RULE_HIT_CASES,
)
def test_intent_analyzer_returns_level1_task_list_for_confident_rule_hits(
    text: str,
    function_code: str,
    function_name: str,
    intent_category: str,
    target_engine: str,
    confidence: float,
) -> None:
    level1_result = make_task_list(
        level=1,
        tasks=[
            make_task(
                function_code,
                function_name=function_name,
                intent_category=intent_category,
                target_engine=target_engine,
                confidence=confidence,
            ),
        ],
        overall_confidence=confidence,
    )
    analyzer, level1_analyzer, semantic_matcher, llm_analyzer, record_service = build_analyzer(
        level1_result=level1_result,
        record_id=f"record-{function_code.lower()}",
    )

    result = analyzer.analyze(
        text=text,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(result, TaskList)
    assert result.request_id == f"record-{function_code.lower()}"
    assert result.analysis_level == 1
    assert result.overall_confidence == confidence
    assert result.tasks[0].function_code == function_code
    assert result.tasks[0].function_name == function_name
    assert result.tasks[0].intent_category == intent_category
    assert result.tasks[0].target_engine == target_engine
    level1_analyzer.analyze.assert_called_once_with(
        text=text,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        record=False,
    )
    semantic_matcher.analyze.assert_not_called()
    llm_analyzer.analyze.assert_not_called()
    record_kwargs = record_service.record_intent_result.call_args.kwargs
    assert record_kwargs["analysis_level"] == 1
    assert record_kwargs["matched_function"] == function_code
    assert record_kwargs["confidence"] == confidence
    assert record_kwargs["result"] == "success"


SEMANTIC_HIT_CASES = [
    ("organize business situation", "REPORT_CREATE", "Report Create", "report_generation", "report_engine", 0.89),
    ("show me receivable progress", "DATA_QUERY", "Data Query", "intelligent_qa", "knowledge_qa_engine", 0.88),
    ("work out this commission", "CALCULATION", "Calculation", "rule_calculation", "rule_engine", 0.87),
    ("combine table contents", "DATA_SUMMARY", "Data Summary", "data_processing", "data_engine", 0.86),
    ("prepare external explanation", "CONTENT_CREATE", "Content Create", "content_creation", "content_engine", 0.85),
    ("recognize image problem", "IMAGE_RECOGNITION", "Image Recognition", "image_recognition", "media_engine", 0.84),
    ("explain reimbursement rule", "KNOWLEDGE_QA", "Knowledge QA", "intelligent_qa", "knowledge_qa_engine", 0.83),
    ("arrange automatic handling", "WORKFLOW_AGENT", "Workflow Agent", "workflow_agent", "workflow_engine", 0.82),
    ("read spreadsheet fields", "DOCUMENT_PARSE", "Document Parse", "data_processing", "document_engine", 0.81),
    ("review sales performance", "REPORT_CREATE", "Report Create", "report_generation", "report_engine", 0.8),
    ("where is customer follow up", "DATA_QUERY", "Data Query", "intelligent_qa", "knowledge_qa_engine", 0.79),
    ("check regional amount", "CALCULATION", "Calculation", "rule_calculation", "rule_engine", 0.78),
    ("collect category amount", "DATA_SUMMARY", "Data Summary", "data_processing", "data_engine", 0.77),
    ("draft material wording", "CONTENT_CREATE", "Content Create", "content_creation", "content_engine", 0.76),
    ("understand the policy question", "KNOWLEDGE_QA", "Knowledge QA", "intelligent_qa", "knowledge_qa_engine", 0.75),
]


@pytest.mark.parametrize(
    ("text", "function_code", "function_name", "intent_category", "target_engine", "confidence"),
    SEMANTIC_HIT_CASES,
)
def test_intent_analyzer_returns_level2_task_list_for_confident_semantic_hits(
    text: str,
    function_code: str,
    function_name: str,
    intent_category: str,
    target_engine: str,
    confidence: float,
) -> None:
    semantic_result = make_semantic_result(
        function_code,
        function_name=function_name,
        intent_category=intent_category,
        target_engine=target_engine,
        confidence=confidence,
    )
    analyzer, level1_analyzer, semantic_matcher, llm_analyzer, record_service = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=semantic_result,
        record_id=f"record-level2-{function_code.lower()}",
    )

    result = analyzer.analyze(
        text=text,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(result, TaskList)
    assert result.request_id == f"record-level2-{function_code.lower()}"
    assert result.analysis_level == 2
    assert result.overall_confidence == confidence
    assert result.tasks[0].function_code == function_code
    assert result.tasks[0].function_name == function_name
    assert result.tasks[0].intent_category == intent_category
    assert result.tasks[0].target_engine == target_engine
    level1_analyzer.analyze.assert_called_once()
    semantic_matcher.analyze.assert_called_once_with(text)
    llm_analyzer.analyze.assert_not_called()
    record_kwargs = record_service.record_intent_result.call_args.kwargs
    assert record_kwargs["analysis_level"] == 2
    assert record_kwargs["matched_function"] == function_code
    assert record_kwargs["confidence"] == confidence
    assert record_kwargs["result"] == "success"


LLM_FALLBACK_CASES = [
    ("prepare a board pack from several unclear files", "REPORT_CREATE", "Report Create"),
    ("compare data and write a short conclusion", "CONTENT_CREATE", "Content Create"),
    ("read the file and calculate missing totals", "CALCULATION", "Calculation"),
    ("handle this reimbursement question end to end", "KNOWLEDGE_QA", "Knowledge QA"),
    ("make sense of these mixed operation notes", "DATA_SUMMARY", "Data Summary"),
    ("turn this rough request into an approval plan", "WORKFLOW_AGENT", "Workflow Agent"),
    ("inspect media and summarize findings", "IMAGE_RECOGNITION", "Image Recognition"),
    ("parse the document then answer question", "DOCUMENT_PARSE", "Document Parse"),
    ("draft a response after checking policy", "CONTENT_CREATE", "Content Create"),
    ("produce analysis after organizing source data", "REPORT_CREATE", "Report Create"),
]


@pytest.mark.parametrize(("text", "function_code", "function_name"), LLM_FALLBACK_CASES)
def test_intent_analyzer_uses_level3_when_rule_and_semantic_are_not_confident(
    text: str,
    function_code: str,
    function_name: str,
) -> None:
    llm_task_list = make_task_list(
        level=3,
        tasks=[
            make_task(
                function_code,
                function_name=function_name,
                intent_category="llm_resolved",
                target_engine="llm_selected_engine",
                confidence=0.8,
            ),
        ],
        overall_confidence=0.8,
    )
    analyzer, level1_analyzer, semantic_matcher, llm_analyzer, record_service = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=make_low_semantic_result(),
        llm_result=llm_task_list,
        record_id=f"record-level3-{function_code.lower()}",
    )

    result = analyzer.analyze(
        text=text,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(result, TaskList)
    assert result.request_id == f"record-level3-{function_code.lower()}"
    assert result.analysis_level == 3
    assert result.tasks[0].function_code == function_code
    assert result.tasks[0].function_name == function_name
    level1_analyzer.analyze.assert_called_once()
    semantic_matcher.analyze.assert_called_once_with(text)
    llm_analyzer.analyze.assert_called_once_with(text, user_id=USER_ID)
    record_kwargs = record_service.record_intent_result.call_args.kwargs
    assert record_kwargs["analysis_level"] == 3
    assert record_kwargs["matched_function"] == function_code
    assert record_kwargs["confidence"] == 0.8
    assert record_kwargs["result"] == "success"


COMPLEX_LLM_CASES = [
    (
        "summarize sales then create a monthly report",
        [
            make_task("DATA_SUMMARY", function_name="Data Summary", target_engine="data_engine", priority=1, confidence=0.84),
            make_task("REPORT_CREATE", function_name="Report Create", dependency=["DATA_SUMMARY"], priority=2, confidence=0.82),
        ],
    ),
    (
        "query policy then draft a customer reply",
        [
            make_task("KNOWLEDGE_QA", function_name="Knowledge QA", intent_category="intelligent_qa", target_engine="knowledge_qa_engine", priority=1, confidence=0.85),
            make_task("CONTENT_CREATE", function_name="Content Create", intent_category="content_creation", target_engine="content_engine", dependency=["KNOWLEDGE_QA"], priority=2, confidence=0.83),
        ],
    ),
    (
        "parse spreadsheet and calculate commission",
        [
            make_task("DOCUMENT_PARSE", function_name="Document Parse", intent_category="data_processing", target_engine="document_engine", priority=1, confidence=0.86),
            make_task("CALCULATION", function_name="Calculation", intent_category="rule_calculation", target_engine="rule_engine", dependency=["DOCUMENT_PARSE"], priority=2, confidence=0.82),
        ],
    ),
    (
        "inspect image and write a finding note",
        [
            make_task("IMAGE_RECOGNITION", function_name="Image Recognition", intent_category="image_recognition", target_engine="media_engine", priority=1, confidence=0.84),
            make_task("CONTENT_CREATE", function_name="Content Create", intent_category="content_creation", target_engine="content_engine", dependency=["IMAGE_RECOGNITION"], priority=2, confidence=0.81),
        ],
    ),
    (
        "create report and start follow up workflow",
        [
            make_task("REPORT_CREATE", function_name="Report Create", priority=1, confidence=0.87),
            make_task("WORKFLOW_AGENT", function_name="Workflow Agent", intent_category="workflow_agent", target_engine="workflow_engine", dependency=["REPORT_CREATE"], priority=2, confidence=0.8),
        ],
    ),
]


@pytest.mark.parametrize(("text", "tasks"), COMPLEX_LLM_CASES)
def test_intent_analyzer_preserves_complex_level3_task_lists(
    text: str,
    tasks: list[TaskItem],
) -> None:
    llm_task_list = make_task_list(level=3, tasks=tasks)
    analyzer, _, _, llm_analyzer, record_service = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=make_low_semantic_result(),
        llm_result=llm_task_list,
        record_id="record-complex",
    )

    result = analyzer.analyze(
        text=text,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(result, TaskList)
    assert result.request_id == "record-complex"
    assert result.analysis_level == 3
    assert [task.function_code for task in result.tasks] == [task.function_code for task in tasks]
    assert [task.dependency for task in result.tasks] == [task.dependency for task in tasks]
    assert result.overall_confidence == min(task.confidence for task in tasks)
    llm_analyzer.analyze.assert_called_once_with(text, user_id=USER_ID)
    record_kwargs = record_service.record_intent_result.call_args.kwargs
    assert record_kwargs["analysis_level"] == 3
    assert record_kwargs["matched_function"] == tasks[0].function_code
    assert record_kwargs["confidence"] == result.overall_confidence


def test_intent_analyzer_falls_through_when_rule_confidence_is_below_threshold() -> None:
    low_rule_result = make_task_list(
        level=1,
        tasks=[make_task("REPORT_CREATE", function_name="Report Create", confidence=0.89)],
        overall_confidence=0.89,
    )
    analyzer, _, semantic_matcher, llm_analyzer, _ = build_analyzer(
        level1_result=low_rule_result,
        semantic_result=make_semantic_result("DATA_SUMMARY", function_name="Data Summary", confidence=0.86),
        record_id="record-semantic-after-rule",
    )

    result = analyzer.analyze(
        text="organize operating situation",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(result, TaskList)
    assert result.analysis_level == 2
    assert result.tasks[0].function_code == "DATA_SUMMARY"
    semantic_matcher.analyze.assert_called_once_with("organize operating situation")
    llm_analyzer.analyze.assert_not_called()


def test_intent_analyzer_falls_through_when_semantic_confidence_is_below_threshold() -> None:
    llm_task_list = make_task_list(
        level=3,
        tasks=[make_task("CONTENT_CREATE", function_name="Content Create", confidence=0.82)],
    )
    analyzer, _, _, llm_analyzer, _ = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=make_semantic_result("REPORT_CREATE", function_name="Report Create", confidence=0.74),
        llm_result=llm_task_list,
        record_id="record-llm-after-semantic",
    )

    result = analyzer.analyze(
        text="produce a nuanced response",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(result, TaskList)
    assert result.analysis_level == 3
    assert result.tasks[0].function_code == "CONTENT_CREATE"
    llm_analyzer.analyze.assert_called_once_with("produce a nuanced response", user_id=USER_ID)


def test_intent_analyzer_falls_through_when_semantic_result_has_no_candidates() -> None:
    malformed_semantic_result = SemanticResult(
        matched=True,
        candidates=[],
        function_code="REPORT_CREATE",
        confidence=0.95,
        similarity_score=0.95,
    )
    llm_task_list = make_task_list(
        level=3,
        tasks=[make_task("REPORT_CREATE", function_name="Report Create", confidence=0.83)],
    )
    analyzer, _, _, llm_analyzer, _ = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=malformed_semantic_result,
        llm_result=llm_task_list,
        record_id="record-llm-after-empty-semantic",
    )

    result = analyzer.analyze(
        text="semantic service returned no candidates",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(result, TaskList)
    assert result.analysis_level == 3
    assert result.tasks[0].function_code == "REPORT_CREATE"
    llm_analyzer.analyze.assert_called_once_with("semantic service returned no candidates", user_id=USER_ID)


def test_intent_analyzer_records_need_confirmation_from_level3() -> None:
    need_confirmation = NeedConfirmationResult(
        reason="invalid_task_list_json",
        raw_response="not json",
    )
    analyzer, _, _, llm_analyzer, record_service = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=make_low_semantic_result(),
        llm_result=need_confirmation,
        record_id="record-need-confirmation",
    )

    result = analyzer.analyze(
        text="complex unclear request",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert result == need_confirmation
    llm_analyzer.analyze.assert_called_once_with("complex unclear request", user_id=USER_ID)
    record_kwargs = record_service.record_intent_result.call_args.kwargs
    assert record_kwargs["analysis_level"] == 3
    assert record_kwargs["matched_function"] is None
    assert record_kwargs["confidence"] == 0
    assert record_kwargs["result"] == "need_confirmation"


def test_intent_analyzer_debug_for_level1_hit() -> None:
    level1_result = make_task_list(
        level=1,
        tasks=[make_task("REPORT_CREATE", function_name="Report Create", confidence=0.96)],
        overall_confidence=0.96,
    )
    analyzer, _, semantic_matcher, llm_analyzer, _ = build_analyzer(
        level1_result=level1_result,
        record_id="record-level1-debug",
    )

    analysis = analyzer.analyze_with_debug(
        text="create sales report",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(analysis.result, TaskList)
    assert analysis.result.analysis_level == 1
    assert analysis.debug["level1_result"]["tasks"][0]["function_code"] == "REPORT_CREATE"
    assert analysis.debug["level2_result"] is None
    assert analysis.debug["level3_result"] is None
    assert analysis.debug["final_tasklist"]["request_id"] == "record-level1-debug"
    semantic_matcher.analyze.assert_not_called()
    llm_analyzer.analyze.assert_not_called()


def test_intent_analyzer_debug_for_level2_hit() -> None:
    semantic_result = make_semantic_result(
        "REPORT_CREATE",
        function_name="Report Create",
        confidence=0.84,
    )
    analyzer, _, _, llm_analyzer, _ = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=semantic_result,
        record_id="record-level2-debug",
    )

    analysis = analyzer.analyze_with_debug(
        text="organize business situation",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(analysis.result, TaskList)
    assert analysis.result.analysis_level == 2
    assert analysis.debug["level1_result"]["tasks"] == []
    assert analysis.debug["level2_result"]["function_code"] == "REPORT_CREATE"
    assert analysis.debug["level3_result"] is None
    assert analysis.debug["final_tasklist"]["analysis_level"] == 2
    assert analysis.debug["final_tasklist"]["tasks"][0]["function_code"] == "REPORT_CREATE"
    llm_analyzer.analyze.assert_not_called()


def test_intent_analyzer_debug_for_level3_fallback() -> None:
    llm_task_list = make_task_list(
        level=3,
        tasks=[make_task("CONTENT_CREATE", function_name="Content Create", confidence=0.82)],
        overall_confidence=0.82,
    )
    analyzer, _, _, llm_analyzer, _ = build_analyzer(
        level1_result=make_task_list(level=1),
        semantic_result=make_low_semantic_result(),
        llm_result=llm_task_list,
        record_id="record-level3-debug",
    )

    analysis = analyzer.analyze_with_debug(
        text="make sense of these notes",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
    )

    assert isinstance(analysis.result, TaskList)
    assert analysis.result.analysis_level == 3
    assert analysis.debug["level1_result"]["tasks"] == []
    assert analysis.debug["level2_result"]["matched"] is False
    assert analysis.debug["level3_result"]["tasks"][0]["function_code"] == "CONTENT_CREATE"
    assert analysis.debug["final_tasklist"]["request_id"] == "record-level3-debug"
    llm_analyzer.analyze.assert_called_once_with("make sense of these notes", user_id=USER_ID)
