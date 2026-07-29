from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest

from app.core.config import settings
from app.integrations.models import ModelGateway
from app.repositories.vector_repository import VectorRepository
from app.services.semantic_engine import SemanticMatcher


REPORT_DIR = Path(__file__).parent / "reports"
REPORT_JSON = REPORT_DIR / "semantic_engine_real_report.json"
REPORT_MD = REPORT_DIR / "semantic_engine_real_report.md"
TOP_K = 5
REPORT_FUNCTION_CODES = {
    "FUNC_REPORT_GENERATION",
    "REPORT_CREATE",
}

CASES = [
    {
        "case_id": "REAL-SEM-001",
        "category": "target",
        "text": "帮我整理经营情况",
        "expected_match": True,
        "expected_functions": REPORT_FUNCTION_CODES,
    },
    {
        "case_id": "REAL-SEM-002",
        "category": "synonym",
        "text": "帮我看看业务情况",
        "expected_match": True,
        "expected_functions": REPORT_FUNCTION_CODES,
    },
    {
        "case_id": "REAL-SEM-003",
        "category": "weak_expression",
        "text": "最近公司表现怎么样",
        "expected_match": True,
        "expected_functions": REPORT_FUNCTION_CODES,
    },
    {
        "case_id": "REAL-SEM-004",
        "category": "wrong_expression",
        "text": "明天天气如何",
        "expected_match": False,
        "expected_functions": set(),
    },
]

RESULTS: list[dict[str, Any]] = []


@pytest.fixture(scope="module", autouse=True)
def semantic_real_report_writer():
    yield
    write_reports(RESULTS)


def build_real_matcher() -> SemanticMatcher:
    return SemanticMatcher(
        model_gateway=ModelGateway(),
        vector_repository=VectorRepository(),
        top_k=TOP_K,
        match_threshold=settings.semantic_threshold,
    )


@pytest.mark.parametrize("case", CASES, ids=[case["case_id"] for case in CASES])
def test_real_semantic_matcher_matches_business_intent(case: dict[str, Any]) -> None:
    matcher = build_real_matcher()
    started_at = perf_counter()

    try:
        result = matcher.analyze(case["text"])
    except Exception as error:
        elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
        RESULTS.append(
            build_blocked_result(
                case=case,
                elapsed_ms=elapsed_ms,
                error=error,
            ),
        )
        pytest.skip(f"Real Level2 dependencies unavailable: {error}")

    elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
    actual = build_actual_result(case=case, result=result, elapsed_ms=elapsed_ms)
    RESULTS.append(actual)

    assert result.level == 2
    assert len(result.candidates) <= TOP_K
    for candidate in result.candidates:
        assert 0 <= candidate.similarity_score <= 1
        assert 0 <= candidate.confidence <= 1

    if case["expected_match"]:
        assert result.matched is True
        assert result.function_code in case["expected_functions"]
        assert result.confidence >= settings.semantic_threshold
        assert result.similarity_score >= settings.semantic_threshold
        assert result.candidates
    else:
        assert result.matched is False
        assert result.function_code is None
        assert result.confidence == 0
        assert result.similarity_score == 0
        if result.candidates:
            assert result.candidates[0].confidence < settings.semantic_threshold


def build_actual_result(*, case: dict[str, Any], result, elapsed_ms: float) -> dict[str, Any]:
    top_candidate = result.candidates[0] if result.candidates else None
    expected_functions = sorted(case["expected_functions"])
    passed = (
        result.matched is True
        and result.function_code in case["expected_functions"]
        and result.confidence >= settings.semantic_threshold
        if case["expected_match"]
        else result.matched is False
    )

    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "text": case["text"],
        "status": "passed" if passed else "failed",
        "expected_match": case["expected_match"],
        "expected_functions": expected_functions,
        "actual_level": result.level,
        "actual_matched": result.matched,
        "actual_function": result.function_code,
        "confidence": result.confidence,
        "similarity_score": result.similarity_score,
        "top_candidate": serialize_candidate(top_candidate),
        "top_k_candidates": [serialize_candidate(candidate) for candidate in result.candidates],
        "elapsed_ms": elapsed_ms,
        "error": None,
    }


def build_blocked_result(*, case: dict[str, Any], elapsed_ms: float, error: Exception) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "text": case["text"],
        "status": "blocked",
        "expected_match": case["expected_match"],
        "expected_functions": sorted(case["expected_functions"]),
        "actual_level": None,
        "actual_matched": None,
        "actual_function": None,
        "confidence": None,
        "similarity_score": None,
        "top_candidate": None,
        "top_k_candidates": [],
        "elapsed_ms": elapsed_ms,
        "error": str(error),
    }


def serialize_candidate(candidate) -> dict[str, Any] | None:
    if candidate is None:
        return None

    return {
        "function_code": candidate.function_code,
        "function_name": candidate.function_name,
        "intent_category": candidate.intent_category,
        "target_engine": candidate.target_engine,
        "confidence": candidate.confidence,
        "similarity_score": candidate.similarity_score,
    }


def write_reports(results: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model_api_url": settings.model_api_url,
        "embedding_model": settings.embedding_model,
        "milvus_collection": settings.milvus_collection,
        "semantic_threshold": settings.semantic_threshold,
        "top_k": TOP_K,
        "summary": build_summary(results),
        "cases": results,
    }
    REPORT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    REPORT_MD.write_text(
        build_markdown_report(payload),
        encoding="utf-8",
    )


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result["status"] == "passed")
    failed = sum(1 for result in results if result["status"] == "failed")
    blocked = sum(1 for result in results if result["status"] == "blocked")
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "pass_rate": round(passed / total, 4) if total else 0,
        "average_elapsed_ms": round(
            sum(result["elapsed_ms"] for result in results) / total,
            3,
        )
        if total
        else 0,
    }


def build_markdown_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Real Semantic Engine Test Report",
        "",
        f"- Generated At: `{payload['generated_at']}`",
        f"- MODEL_API_URL: `{payload['model_api_url']}`",
        f"- EMBEDDING_MODEL: `{payload['embedding_model']}`",
        f"- Milvus Collection: `{payload['milvus_collection']}`",
        f"- Semantic Threshold: `{payload['semantic_threshold']}`",
        f"- TopK: `{payload['top_k']}`",
        f"- Total: `{summary['total']}`",
        f"- Passed: `{summary['passed']}`",
        f"- Failed: `{summary['failed']}`",
        f"- Blocked: `{summary['blocked']}`",
        f"- Pass Rate: `{summary['pass_rate'] * 100:.2f}%`",
        f"- Average Elapsed: `{summary['average_elapsed_ms']} ms`",
        "",
        "## Case Details",
        "",
        "| Case | Category | Text | Expected Match | Actual Match | Actual Function | Confidence | Similarity | Status | Elapsed ms | Error |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | ---: | --- |",
    ]

    for result in payload["cases"]:
        lines.append(
            "| {case_id} | {category} | {text} | {expected_match} | {actual_matched} | "
            "{actual_function} | {confidence} | {similarity_score} | {status} | {elapsed_ms} | {error} |".format(
                case_id=result["case_id"],
                category=result["category"],
                text=result["text"],
                expected_match=result["expected_match"],
                actual_matched=result["actual_matched"],
                actual_function=result["actual_function"] or "-",
                confidence=format_number(result["confidence"]),
                similarity_score=format_number(result["similarity_score"]),
                status=result["status"],
                elapsed_ms=result["elapsed_ms"],
                error=(result["error"] or "-").replace("|", "\\|"),
            ),
        )

    lines.extend(["", "## TopK Candidates", ""])
    for result in payload["cases"]:
        lines.append(f"### {result['case_id']} `{result['text']}`")
        lines.append("")
        if not result["top_k_candidates"]:
            lines.append("- No candidates.")
            lines.append("")
            continue
        lines.extend(
            [
                "| Rank | Function | Name | Confidence | Similarity |",
                "| ---: | --- | --- | ---: | ---: |",
            ],
        )
        for index, candidate in enumerate(result["top_k_candidates"], start=1):
            lines.append(
                f"| {index} | {candidate['function_code']} | {candidate['function_name'] or '-'} | "
                f"{format_number(candidate['confidence'])} | {format_number(candidate['similarity_score'])} |",
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def format_number(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"
