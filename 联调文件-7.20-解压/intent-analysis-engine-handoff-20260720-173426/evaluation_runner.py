from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_DATASET = PROJECT_ROOT / "evaluation" / "dataset" / "intent_test_dataset.json"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer  # noqa: E402
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer  # noqa: E402
from app.services.semantic import (  # noqa: E402
    BGEProvider,
    EmbeddingService,
    IntentCapabilityVectorRepository,
    SemanticCapability,
    SemanticCapabilityCatalog,
    SemanticMatcher,
)


@dataclass(frozen=True)
class ExpectedTask:
    task_type: str


@dataclass(frozen=True)
class EvaluationCase:
    index: int
    case_id: str
    case_type: str
    text: str
    expected_engine_code: str | None
    expected_task_type: str | None
    should_clarify: bool
    expected_tasks: list[ExpectedTask]
    expected_source: str | None = None


class LocalEvaluationEmbeddingService:
    """Evaluation-only embedding stub that lets the local repository read the query text."""

    def __init__(self) -> None:
        self.last_text = ""

    def embed_query(self, text: str) -> list[float]:
        self.last_text = text
        return [1.0]


class LocalCapabilityVectorRepository:
    """Deterministic local substitute for Milvus in offline evaluation runs."""

    def __init__(
        self,
        *,
        embedding_service: LocalEvaluationEmbeddingService,
        capability_catalog: SemanticCapabilityCatalog,
        threshold_floor: float = 0.2,
    ) -> None:
        self.embedding_service = embedding_service
        self.capability_catalog = capability_catalog
        self.threshold_floor = threshold_floor

    def search(self, vector: list[float], *, top_k: int = 5) -> list[dict[str, Any]]:
        query = self.embedding_service.last_text
        scored = [
            (self._score(query, capability), capability)
            for capability in self.capability_catalog.list_capabilities()
        ]
        return [
            {
                "engine_code": capability.engine_code,
                "task_type": capability.task_type,
                "intent_description": capability.description,
                "examples": capability.examples,
                "keywords": capability.keywords,
                "similarity_score": round(score, 4),
            }
            for score, capability in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
            if score >= self.threshold_floor
        ]

    def _score(self, query: str, capability: SemanticCapability) -> float:
        normalized_query = self._normalize(query)
        if not normalized_query:
            return 0

        score = 0.0
        candidate_texts = [
            capability.task_name,
            capability.description,
            *capability.examples,
            *capability.keywords,
        ]

        keyword_texts = {self._normalize(keyword) for keyword in capability.keywords}
        for candidate_text in candidate_texts:
            normalized_candidate = self._normalize(candidate_text)
            if not normalized_candidate:
                continue
            minimum_substring_length = 2 if normalized_candidate in keyword_texts else 3
            if normalized_candidate == normalized_query:
                score = max(score, 0.99)
            elif len(normalized_candidate) >= minimum_substring_length and normalized_candidate in normalized_query:
                score = max(score, 0.92)
            elif len(normalized_query) >= minimum_substring_length and normalized_query in normalized_candidate:
                score = max(score, 0.88)
            else:
                score = max(score, self._ngram_similarity(normalized_query, normalized_candidate))

        return min(score, 1.0)

    def _ngram_similarity(self, left: str, right: str) -> float:
        left_grams = self._ngrams(left)
        right_grams = self._ngrams(right)
        if not left_grams or not right_grams:
            return 0

        overlap = len(left_grams & right_grams)
        union = len(left_grams | right_grams)
        if union == 0:
            return 0

        jaccard = overlap / union
        if jaccard < 0.18:
            return 0
        return min(0.84, 0.45 + jaccard * 0.75)

    def _ngrams(self, text: str, size: int = 2) -> set[str]:
        if len(text) <= size:
            return {text}
        return {text[index : index + size] for index in range(len(text) - size + 1)}

    def _normalize(self, text: str) -> str:
        return "".join(str(text).lower().split())


def main() -> int:
    args = parse_args()
    cases = load_dataset(args.dataset)
    analyzer = build_analyzer(
        semantic_mode=args.semantic_mode,
        llm_mode=args.llm_mode,
        semantic_threshold=args.semantic_threshold,
    )
    report = evaluate_cases(analyzer, cases)
    print_report(
        report,
        dataset_path=args.dataset,
        semantic_mode=args.semantic_mode,
        llm_mode=args.llm_mode,
        max_errors=args.max_errors,
    )

    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.fail_under is not None and min(
        report["task_type_accuracy"],
        report["clarification_accuracy"],
    ) < args.fail_under:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Intent Analysis Engine natural-language evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--semantic-mode", choices=["local", "milvus", "off"], default="local")
    parser.add_argument("--llm-mode", choices=["off", "live"], default="off")
    parser.add_argument("--semantic-threshold", type=float, default=0.50)
    parser.add_argument("--max-errors", type=int, default=30)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-under", type=float, default=None, help="Fail if any main accuracy is below this ratio.")
    return parser.parse_args()


def build_analyzer(*, semantic_mode: str, llm_mode: str, semantic_threshold: float) -> StandardIntentAnalyzer:
    registry = FunctionRegistryCatalog()
    capability_catalog = SemanticCapabilityCatalog.from_default_file()

    semantic_matcher = None
    if semantic_mode == "local":
        embedding_service = LocalEvaluationEmbeddingService()
        semantic_matcher = SemanticMatcher(
            embedding_service=embedding_service,
            vector_repository=LocalCapabilityVectorRepository(
                embedding_service=embedding_service,
                capability_catalog=capability_catalog,
            ),
            registry=registry,
            capability_catalog=capability_catalog,
            match_threshold=semantic_threshold,
        )
    elif semantic_mode == "milvus":
        semantic_matcher = SemanticMatcher(
            embedding_service=EmbeddingService(provider=BGEProvider()),
            vector_repository=IntentCapabilityVectorRepository(),
            registry=registry,
            capability_catalog=capability_catalog,
            match_threshold=semantic_threshold,
        )

    llm_analyzer = None
    if llm_mode == "live":
        from app.integrations.models import ModelGateway

        llm_analyzer = LLMTaskAnalyzer(model_gateway=ModelGateway(), registry=registry)

    return StandardIntentAnalyzer(
        registry=registry,
        semantic_matcher=semantic_matcher,
        llm_analyzer=llm_analyzer,
        intent_record_service=None,
        semantic_threshold=semantic_threshold,
    )


def load_dataset(path: Path) -> list[EvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Evaluation dataset must be a JSON array.")

    cases = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Evaluation case #{index} must be an object.")
        cases.append(parse_case(index, item))
    return cases


def parse_case(index: int, item: dict[str, Any]) -> EvaluationCase:
    required_fields = ["text", "expected_engine_code", "expected_task_type", "should_clarify"]
    missing_fields = [field for field in required_fields if field not in item]
    if missing_fields:
        raise ValueError(f"Evaluation case #{index} misses fields: {missing_fields}")

    expected_tasks = item.get("expected_tasks")
    if expected_tasks is None:
        if item["expected_engine_code"] is None and item["expected_task_type"] is None:
            parsed_tasks = []
        else:
            parsed_tasks = [
                ExpectedTask(
                    task_type=str(item["expected_task_type"]),
                ),
            ]
    else:
        if not isinstance(expected_tasks, list):
            raise ValueError(f"Evaluation case #{index} expected_tasks must be a list.")
        parsed_tasks = [
            ExpectedTask(
                task_type=str(task["task_type"]),
            )
            for task in expected_tasks
        ]

    return EvaluationCase(
        index=index,
        case_id=str(item.get("id") or index),
        case_type=str(item.get("case_type") or "uncategorized"),
        text=str(item["text"]),
        expected_engine_code=item["expected_engine_code"],
        expected_task_type=item["expected_task_type"],
        should_clarify=bool(item["should_clarify"]),
        expected_tasks=parsed_tasks,
        expected_source=item.get("expected_source"),
    )


def evaluate_cases(analyzer: StandardIntentAnalyzer, cases: list[EvaluationCase]) -> dict[str, Any]:
    rows = []
    for case in cases:
        analysis = analyzer.analyze_with_debug(
            text=case.text,
            user_id="evaluation",
            conversation_id=f"evaluation-{case.index}",
        )
        result = analysis.result
        actual_tasks = [
            {"task_type": task.task_type, "action": task.action, "object": task.object}
            for task in result.tasks
        ]
        expected_tasks = [
            {"task_type": task.task_type}
            for task in case.expected_tasks
        ]
        actual_source = infer_source(analysis.debug)

        rows.append(
            {
                "index": case.index,
                "id": case.case_id,
                "case_type": case.case_type,
                "text": case.text,
                "expected_tasks": expected_tasks,
                "actual_tasks": actual_tasks,
                "expected_clarification": case.should_clarify,
                "actual_clarification": result.clarification_required,
                "expected_source": case.expected_source,
                "actual_source": actual_source,
                "missing_inputs": [task.missing_inputs for task in result.tasks],
                "analysis_level": result.analysis_level,
            },
        )

    return summarize_rows(rows)


def infer_source(debug: dict[str, Any]) -> str:
    if debug.get("fast_path"):
        return "fast_path"

    level1_result = debug.get("level1_result")
    if level1_result:
        return "level1_rule"

    level2_result = debug.get("level2_result")
    if isinstance(level2_result, dict) and level2_result.get("matched") is True:
        return "level2_semantic"

    level3_result = debug.get("level3_result")
    if isinstance(level3_result, dict) and level3_result.get("source") == "TaskDecomposer":
        return "task_decomposer"
    if level3_result:
        return "level3_llm"

    return "fallback"


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    for row in rows:
        row["task_type_pass"] = expected_task_types(row) == actual_task_types(row)
        row["clarification_pass"] = row["expected_clarification"] == row["actual_clarification"]
        row["decomposition_pass"] = len(row["expected_tasks"]) == len(row["actual_tasks"])
        row["source_pass"] = row["expected_source"] is None or row["expected_source"] == row["actual_source"]
        row["passed"] = all(
            [
                row["task_type_pass"],
                row["clarification_pass"],
                row["decomposition_pass"],
                row["source_pass"],
            ],
        )

    return {
        "total": total,
        "task_type_accuracy": ratio(rows, "task_type_pass"),
        "clarification_accuracy": ratio(rows, "clarification_pass"),
        "task_decomposition_accuracy": ratio(rows, "decomposition_pass"),
        "source_accuracy": ratio(rows, "source_pass"),
        "passed_cases": sum(1 for row in rows if row["passed"]),
        "failed_cases": [row for row in rows if not row["passed"]],
        "by_case_type": summarize_by_case_type(rows),
    }


def expected_task_types(row: dict[str, Any]) -> list[str]:
    return [task["task_type"] for task in row["expected_tasks"]]


def actual_task_types(row: dict[str, Any]) -> list[str]:
    return [task["task_type"] for task in row["actual_tasks"]]


def ratio(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0
    return sum(1 for row in rows if row[field]) / len(rows)


def summarize_by_case_type(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["case_type"], []).append(row)

    return {
        case_type: {
            "total": len(items),
            "task_type_accuracy": ratio(items, "task_type_pass"),
            "clarification_accuracy": ratio(items, "clarification_pass"),
            "passed_cases": sum(1 for item in items if item["passed"]),
        }
        for case_type, items in sorted(grouped.items())
    }


def print_report(
    report: dict[str, Any],
    *,
    dataset_path: Path,
    semantic_mode: str,
    llm_mode: str,
    max_errors: int,
) -> None:
    total = report["total"]
    print(f"Dataset: {dataset_path}")
    print(f"Semantic mode: {semantic_mode}")
    print(f"LLM mode: {llm_mode}")
    print(f"Total cases: {total}")
    print(f"task_type准确率: {format_accuracy(report['task_type_accuracy'], total)}")
    print(f"clarification准确率: {format_accuracy(report['clarification_accuracy'], total)}")
    print(f"任务拆解准确率: {format_accuracy(report['task_decomposition_accuracy'], total)}")
    print(f"匹配层级准确率: {format_accuracy(report['source_accuracy'], total)}")
    print("")
    print("By case_type:")
    for case_type, summary in report["by_case_type"].items():
        print(
            f"- {case_type}: passed {summary['passed_cases']}/{summary['total']}, "
            f"task {summary['task_type_accuracy']:.2%}, "
            f"clarification {summary['clarification_accuracy']:.2%}",
        )

    failed_cases = report["failed_cases"]
    print("")
    print(f"错误案例列表: {len(failed_cases)}")
    for row in failed_cases[:max_errors]:
        failed_metrics = [
            metric
            for metric in ["task_type", "clarification", "decomposition", "source"]
            if not row[f"{metric}_pass"]
        ]
        print(f"- [{row['index']}] {row['id']} ({row['case_type']}): {row['text']}")
        print(f"  failed={','.join(failed_metrics)}")
        print(f"  expected_tasks={row['expected_tasks']}")
        print(f"  actual_tasks={row['actual_tasks']}")
        print(
            f"  expected_clarification={row['expected_clarification']} "
            f"actual_clarification={row['actual_clarification']}",
        )
        print(f"  expected_source={row['expected_source']} actual_source={row['actual_source']}")


def format_accuracy(value: float, total: int) -> str:
    return f"{value:.2%} ({round(value * total)}/{total})"


if __name__ == "__main__":
    raise SystemExit(main())
