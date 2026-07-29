from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.semantic import SemanticMatcher


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [1.0, 0.0, 0.0]


class FakeCapabilityRepository:
    def __init__(self, responses: dict[str, list[dict]]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def search(self, vector: list[float], *, top_k: int = 5) -> list[dict]:
        self.calls.append({"vector": vector, "top_k": top_k})
        return self.responses.get("default", [])


def make_bge_matcher(candidates: list[dict]) -> tuple[SemanticMatcher, FakeEmbeddingService, FakeCapabilityRepository]:
    embedding_service = FakeEmbeddingService()
    vector_repository = FakeCapabilityRepository({"default": candidates})
    matcher = SemanticMatcher(
        embedding_service=embedding_service,
        vector_repository=vector_repository,
        registry=FunctionRegistryCatalog(),
        match_threshold=0.75,
    )
    return matcher, embedding_service, vector_repository


def make_analyzer(candidates: list[dict]) -> tuple[StandardIntentAnalyzer, FakeEmbeddingService, FakeCapabilityRepository]:
    registry = FunctionRegistryCatalog()
    embedding_service = FakeEmbeddingService()
    vector_repository = FakeCapabilityRepository({"default": candidates})
    semantic_matcher = SemanticMatcher(
        embedding_service=embedding_service,
        vector_repository=vector_repository,
        registry=registry,
        match_threshold=0.75,
    )
    return (
        StandardIntentAnalyzer(
            registry=registry,
            semantic_matcher=semantic_matcher,
            llm_analyzer=None,
            intent_record_service=None,
            semantic_threshold=0.75,
        ),
        embedding_service,
        vector_repository,
    )


def capability_candidate(engine_code: str, task_type: str, score: float) -> dict:
    return {
        "engine_code": engine_code,
        "task_type": task_type,
        "intent_description": "semantic capability",
        "examples": ["example"],
        "similarity_score": score,
    }


def test_bge_semantic_matcher_matches_sales_bonus_to_commission_calculation() -> None:
    matcher, embedding_service, vector_repository = make_bge_matcher(
        [
            capability_candidate("ENG_RULE_CALCULATION", "RULE_CALCULATION_COMMISSION", 0.89),
            capability_candidate("ENG_CONTENT_OUTPUT", "CONTENT_GENERATE", 0.51),
        ],
    )

    result = matcher.analyze("帮我看看销售人员奖金怎么算")

    assert result.matched is True
    assert result.function_code == "ENG_RULE_CALCULATION"
    assert result.confidence == 0.89
    assert result.candidates[0].engine_code == "ENG_RULE_CALCULATION"
    assert result.candidates[0].task_type == "RULE_CALCULATION_COMMISSION"
    assert result.candidates[0].task_name == "计算销售提成"
    assert embedding_service.calls == ["帮我看看销售人员奖金怎么算"]
    assert vector_repository.calls[0]["top_k"] == 5


def test_level2_bge_runs_after_level1_miss_and_still_requires_missing_inputs() -> None:
    analyzer, embedding_service, _ = make_analyzer(
        [
            capability_candidate("ENG_RULE_CALCULATION", "RULE_CALCULATION_COMMISSION", 0.88),
        ],
    )

    analysis = analyzer.analyze_with_debug(
        text="帮我看看销售人员奖金怎么算",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    result = analysis.result
    assert result.analysis_level == 2
    assert result.intent_category == "规则计算型"
    assert result.tasks[0].task_type == "RULE_CALCULATION_COMMISSION"
    assert result.tasks[0].action == "计算"
    assert result.tasks[0].missing_inputs == ["calculation_policy"]
    assert result.clarification_required is True
    assert result.clarification_questions == [
        "请提供计算规则或适用政策。",
    ]
    assert analysis.debug["level1_result"] is None
    assert analysis.debug["level2_result"]["matched"] is True
    assert analysis.debug["level3_result"] is None
    assert analysis.debug["level1_rule_result"] == {"matched": False, "rule": None}
    assert analysis.debug["level2_semantic_result"]["matched"] is True
    assert analysis.debug["level2_semantic_result"]["top_candidates"][0] == {
        "task_type": "RULE_CALCULATION_COMMISSION",
        "confidence": 0.88,
        "similarity_score": 0.88,
    }
    assert analysis.debug["final_decision"]["selected_by"] == "semantic"
    assert analysis.debug["input_validator"]["missing_inputs"] == ["calculation_policy"]
    assert embedding_service.calls == ["帮我看看销售人员奖金怎么算"]


def test_level2_bge_matches_operating_status_to_business_analysis() -> None:
    analyzer, _, _ = make_analyzer(
        [
            capability_candidate("ENG_ANALYTICS_FORECASTING", "DATA_ANALYSIS_PROBLEM", 0.86),
        ],
    )

    analysis = analyzer.analyze_with_debug(
        text="最近经营情况怎么样",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    result = analysis.result
    assert result.analysis_level == 2
    assert result.intent_category == "数据分析型"
    assert result.tasks[0].task_name == "经营分析"
    assert result.tasks[0].task_type == "DATA_ANALYSIS_PROBLEM"
    assert result.tasks[0].missing_inputs == []
    assert result.clarification_required is False
    assert analysis.debug["level2_result"]["matched"] is True


def test_level1_sales_commission_phrase_keeps_priority_over_bge() -> None:
    analyzer, embedding_service, vector_repository = make_analyzer(
        [
            capability_candidate("ENG_RULE_CALCULATION", "RULE_CALCULATION_COMMISSION", 0.95),
        ],
    )

    analysis = analyzer.analyze_with_debug(
        text="销售提成",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    result = analysis.result
    assert result.analysis_level == 1
    assert result.tasks[0].task_type == "RULE_CALCULATION_COMMISSION"
    assert result.clarification_required is True
    assert result.tasks[0].missing_inputs == ["calculation_policy"]
    assert analysis.debug["level1_result"]["source"] == "OperationRuleMatcher"
    assert analysis.debug["level2_result"] is None
    assert embedding_service.calls == []
    assert vector_repository.calls == []
