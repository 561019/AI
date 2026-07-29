from zlib import crc32

import pytest

from app.repositories.vector_repository import VectorRepository
from app.schemas.semantic import SemanticCandidate, SemanticResult
from app.services.semantic_engine import SemanticMatcher


def text_embedding(text: str) -> list[float]:
    return [float(crc32(text.encode("utf-8")) % 100_000)]


def candidate(
    function_code: str,
    score: float,
    *,
    function_name: str | None = None,
    intent_category: str | None = None,
    target_engine: str | None = None,
) -> dict:
    return {
        "function_code": function_code,
        "function_name": function_name or function_code.replace("_", " ").title(),
        "intent_category": intent_category or "general",
        "target_engine": target_engine or "general_engine",
        "similarity_score": score,
    }


class FakeModelGateway:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embedding(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [text_embedding(text) for text in texts]

    def rerank(self, query: str, candidates: list[str | dict]) -> list[dict]:
        return []

    def chat(self, messages: list[dict[str, str]]) -> str:
        return ""


class FakeVectorRepository:
    def __init__(self, responses: dict[str, list[dict]]) -> None:
        self.responses_by_embedding = {
            tuple(text_embedding(text)): candidates
            for text, candidates in responses.items()
        }
        self.search_calls: list[tuple[list[float], int]] = []

    def search(self, vector: list[float], *, top_k: int = 5) -> list[dict]:
        self.search_calls.append((vector, top_k))
        return self.responses_by_embedding.get(tuple(vector), [])[:top_k]


def build_matcher(
    responses: dict[str, list[dict]],
    *,
    top_k: int = 5,
    threshold: float = 0.75,
) -> tuple[SemanticMatcher, FakeModelGateway, FakeVectorRepository]:
    model_gateway = FakeModelGateway()
    vector_repository = FakeVectorRepository(responses)
    matcher = SemanticMatcher(
        model_gateway=model_gateway,
        vector_repository=vector_repository,
        top_k=top_k,
        match_threshold=threshold,
    )
    return matcher, model_gateway, vector_repository


SUCCESS_CASES = [
    ("帮我整理经营情况", "REPORT_CREATE", 0.93),
    ("把经营状况归纳一下", "REPORT_CREATE", 0.91),
    ("做一份业务表现总结", "REPORT_CREATE", 0.9),
    ("我想了解销售完成情况", "DATA_QUERY", 0.89),
    ("查一下本月回款进度", "DATA_QUERY", 0.88),
    ("看下客户数据", "DATA_QUERY", 0.86),
    ("帮我算一算提成", "CALCULATION", 0.92),
    ("核一下各区域提成", "CALCULATION", 0.9),
    ("估一下这批费用", "CALCULATION", 0.84),
    ("把表格内容归并一下", "DATA_SUMMARY", 0.91),
    ("整理一下产品分类金额", "DATA_SUMMARY", 0.9),
    ("做个数据合计", "DATA_SUMMARY", 0.88),
    ("写一段通知说明", "CONTENT_CREATE", 0.87),
    ("帮我起草材料", "CONTENT_CREATE", 0.89),
    ("生成一份对外说明", "CONTENT_CREATE", 0.86),
    ("把图片里的问题识别出来", "IMAGE_RECOGNITION", 0.83),
    ("识别视频里的虫口指数", "IMAGE_RECOGNITION", 0.82),
    ("帮我处理报销问题咨询", "KNOWLEDGE_QA", 0.88),
    ("这个制度该怎么理解", "KNOWLEDGE_QA", 0.87),
    ("帮我安排一次自动办理", "WORKFLOW_AGENT", 0.85),
]


@pytest.mark.parametrize(("text", "expected_code", "score"), SUCCESS_CASES)
def test_semantic_matcher_handles_rule_miss_but_semantic_correct(
    text: str,
    expected_code: str,
    score: float,
) -> None:
    matcher, model_gateway, vector_repository = build_matcher(
        {
            text: [
                candidate(expected_code, score),
                candidate("OTHER_FUNCTION", 0.61),
            ],
        },
    )

    result = matcher.analyze(text)

    assert result.level == 2
    assert result.matched is True
    assert result.function_code == expected_code
    assert result.confidence == score
    assert result.similarity_score == score
    assert len(result.candidates) == 2
    assert model_gateway.calls == [[text]]
    assert vector_repository.search_calls[0][1] == 5


SYNONYM_CASES = [
    ("经营情况总结", "REPORT_CREATE"),
    ("经营表现复盘", "REPORT_CREATE"),
    ("业务情况梳理", "REPORT_CREATE"),
    ("历史销售怎么看", "DATA_QUERY"),
    ("回款做到哪里了", "DATA_QUERY"),
    ("客户跟进状态给我看下", "DATA_QUERY"),
    ("提成核出来", "CALCULATION"),
    ("费用金额过一遍", "CALCULATION"),
    ("把数据拢一拢", "DATA_SUMMARY"),
    ("表格按类别收一下", "DATA_SUMMARY"),
    ("写个说明稿", "CONTENT_CREATE"),
    ("起草通知文本", "CONTENT_CREATE"),
    ("制度问题答一下", "KNOWLEDGE_QA"),
    ("报销规则能不能解释下", "KNOWLEDGE_QA"),
    ("自动帮我办这个流程", "WORKFLOW_AGENT"),
]


@pytest.mark.parametrize(("text", "expected_code"), SYNONYM_CASES)
def test_semantic_matcher_supports_synonym_expressions(text: str, expected_code: str) -> None:
    matcher, _, _ = build_matcher(
        {
            text: [
                candidate(expected_code, 0.87),
                candidate("NOISE_FUNCTION", 0.54),
            ],
        },
    )

    result = matcher.analyze(text)

    assert result.matched is True
    assert result.function_code == expected_code
    assert result.candidates[0].function_code == expected_code


CONFUSION_CASES = [
    ("销售分析总结", "REPORT_CREATE", "DATA_QUERY", 0.88, 0.86),
    ("销售数据说明", "DATA_QUERY", "CONTENT_CREATE", 0.87, 0.84),
    ("费用核算说明", "CALCULATION", "CONTENT_CREATE", 0.89, 0.85),
    ("分类汇总报告", "DATA_SUMMARY", "REPORT_CREATE", 0.9, 0.88),
    ("报销制度问答", "KNOWLEDGE_QA", "CONTENT_CREATE", 0.91, 0.79),
    ("自动生成报告流程", "REPORT_CREATE", "WORKFLOW_AGENT", 0.86, 0.82),
    ("图片统计结果报告", "IMAGE_RECOGNITION", "REPORT_CREATE", 0.85, 0.83),
    ("客户回款总结", "DATA_QUERY", "REPORT_CREATE", 0.89, 0.86),
    ("提成数据汇总", "CALCULATION", "DATA_SUMMARY", 0.9, 0.88),
    ("流程办理说明", "WORKFLOW_AGENT", "CONTENT_CREATE", 0.86, 0.8),
]


@pytest.mark.parametrize(
    ("text", "expected_code", "confused_code", "expected_score", "confused_score"),
    CONFUSION_CASES,
)
def test_semantic_matcher_ranks_similar_function_conflicts(
    text: str,
    expected_code: str,
    confused_code: str,
    expected_score: float,
    confused_score: float,
) -> None:
    matcher, _, _ = build_matcher(
        {
            text: [
                candidate(confused_code, confused_score),
                candidate(expected_code, expected_score),
            ],
        },
    )

    result = matcher.analyze(text)

    assert result.matched is True
    assert result.function_code == expected_code
    assert result.candidates[0].function_code == expected_code
    assert result.candidates[1].function_code == confused_code


LOW_CONFIDENCE_CASES = [
    ("今天天气怎么样", 0.2),
    ("播放音乐", 0.18),
    ("订一杯咖啡", 0.31),
    ("买彩票", 0.12),
    ("讲个笑话", 0.24),
    ("明天放假吗", 0.45),
    ("帮我写诗", 0.5),
    ("随便聊聊", 0.38),
    ("打开电影", 0.33),
    ("桌面背景换一下", 0.29),
]


@pytest.mark.parametrize(("text", "score"), LOW_CONFIDENCE_CASES)
def test_semantic_matcher_returns_unmatched_for_low_confidence(text: str, score: float) -> None:
    matcher, _, _ = build_matcher(
        {
            text: [
                candidate("LOW_CONFIDENCE_FUNCTION", score),
                candidate("OTHER_FUNCTION", score - 0.01),
            ],
        },
    )

    result = matcher.analyze(text)

    assert result.matched is False
    assert result.function_code is None
    assert result.confidence == 0
    assert result.similarity_score == 0
    assert result.candidates[0].similarity_score == score


def test_semantic_matcher_returns_top_k_candidates() -> None:
    text = "帮我整理经营情况"
    matcher, _, vector_repository = build_matcher(
        {
            text: [
                candidate("A", 0.95),
                candidate("B", 0.94),
                candidate("C", 0.93),
                candidate("D", 0.92),
                candidate("E", 0.91),
            ],
        },
        top_k=3,
    )

    result = matcher.analyze(text)

    assert [item.function_code for item in result.candidates] == ["A", "B", "C"]
    assert vector_repository.search_calls[0][1] == 3


def test_semantic_matcher_deduplicates_candidates_by_best_score() -> None:
    text = "经营总结"
    matcher, _, _ = build_matcher(
        {
            text: [
                candidate("REPORT_CREATE", 0.8),
                candidate("REPORT_CREATE", 0.93),
                candidate("DATA_QUERY", 0.82),
            ],
        },
    )

    result = matcher.analyze(text)

    assert [item.function_code for item in result.candidates] == ["REPORT_CREATE", "DATA_QUERY"]
    assert result.candidates[0].similarity_score == 0.93


def test_semantic_matcher_ignores_candidates_without_function_code() -> None:
    text = "经营总结"
    matcher, _, _ = build_matcher(
        {
            text: [
                {"similarity_score": 0.99},
                candidate("REPORT_CREATE", 0.9),
            ],
        },
    )

    result = matcher.analyze(text)

    assert result.matched is True
    assert result.function_code == "REPORT_CREATE"
    assert len(result.candidates) == 1


def test_semantic_matcher_handles_blank_text_without_gateway_call() -> None:
    matcher, model_gateway, vector_repository = build_matcher({})

    result = matcher.analyze(" ")

    assert result == SemanticResult.unmatched()
    assert model_gateway.calls == []
    assert vector_repository.search_calls == []


def test_semantic_result_schema_matched_shape() -> None:
    result = SemanticResult.matched_result(
        candidates=[
            SemanticCandidate(
                function_code="REPORT_CREATE",
                function_name="Report",
                intent_category="report_generation",
                target_engine="report_engine",
                confidence=0.91,
                similarity_score=0.91,
            ),
        ],
    )

    assert result.model_dump(exclude_none=True) == {
        "level": 2,
        "matched": True,
        "candidates": [
            {
                "function_code": "REPORT_CREATE",
                "function_name": "Report",
                "intent_category": "report_generation",
                "target_engine": "report_engine",
                "confidence": 0.91,
                "similarity_score": 0.91,
            },
        ],
        "function_code": "REPORT_CREATE",
        "confidence": 0.91,
        "similarity_score": 0.91,
    }


def test_semantic_result_schema_unmatched_shape() -> None:
    assert SemanticResult.unmatched().model_dump(exclude_none=True) == {
        "level": 2,
        "matched": False,
        "candidates": [],
        "confidence": 0.0,
        "similarity_score": 0.0,
    }
