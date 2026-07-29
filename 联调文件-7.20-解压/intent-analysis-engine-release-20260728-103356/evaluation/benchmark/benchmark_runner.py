from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_DATASET_ROOT = PROJECT_ROOT / "evaluation" / "benchmark" / "datasets"

for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation_runner import build_analyzer  # noqa: E402
from evaluation.benchmark.metrics import aggregate_case_metrics, evaluate_case_metrics  # noqa: E402

from app.services.context_provider import MockContextProvider  # noqa: E402
from app.services.conversation_understanding import ConversationUnderstandingLayer  # noqa: E402
from app.services.intent_analysis_engine.clarification import ClarificationSessionManager  # noqa: E402


REQUIRED_FIELDS = {
    "id": str,
    "text": str,
    "intent_category": str,
    "expected_tasks": list,
    "expected_task_types": list,
    "required_clarification": bool,
    "missing_inputs": list,
    "forbidden_tasks": list,
}
SPLITS = ("train", "validation", "blind_test")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run production-style Intent Analysis benchmark.")
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--dataset", type=Path, default=None, help="Optional single JSON/JSONL dataset file.")
    parser.add_argument("--split", choices=[*SPLITS, "all"], default="validation")
    parser.add_argument("--allow-blind-test", action="store_true")
    parser.add_argument("--semantic-mode", choices=["local", "milvus", "off"], default="local")
    parser.add_argument("--llm-mode", choices=["off", "live"], default="off")
    parser.add_argument("--semantic-threshold", type=float, default=0.50)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--max-errors", type=int, default=30)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--failure-report",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "error_analysis" / "failure_report.json",
    )
    parser.add_argument("--fail-under-f1", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(
        dataset_root=args.dataset_root,
        dataset=args.dataset,
        split=args.split,
        allow_blind_test=args.allow_blind_test,
    )
    if args.validate_only:
        report = validation_report(cases)
        print_validation_report(report)
        if args.output:
            write_json(args.output, report)
        return 0

    analyzer = build_analyzer(
        semantic_mode=args.semantic_mode,
        llm_mode=args.llm_mode,
        semantic_threshold=args.semantic_threshold,
    )
    metrics = []
    for case in cases:
        metrics.append(evaluate_case(analyzer=analyzer, case=case))

    report = aggregate_case_metrics(metrics)
    print_report(report, max_errors=args.max_errors)
    if args.output:
        write_json(args.output, report)
    if args.failure_report:
        from evaluation.error_analysis.report_generator import generate_failure_report

        benchmark_report_path = args.output or args.failure_report.with_name("benchmark_report_current.json")
        if not args.output:
            write_json(benchmark_report_path, report)
        failure_report = generate_failure_report(
            benchmark_report_path=benchmark_report_path,
            dataset_root=args.dataset_root,
            split=args.split,
            allow_blind_test=args.allow_blind_test,
        )
        write_json(args.failure_report, failure_report)
    if args.fail_under_f1 is not None and report["macro_f1"] < args.fail_under_f1:
        return 1
    return 0


def load_cases(
    *,
    dataset_root: Path,
    dataset: Path | None,
    split: str,
    allow_blind_test: bool,
) -> list[dict[str, Any]]:
    if dataset is not None:
        cases = _load_file(dataset)
        return [_validate_case(case, source=str(dataset), split=_split_from_path(dataset)) for case in cases]

    if split in {"blind_test", "all"} and not allow_blind_test:
        raise SystemExit(
            "blind_test is protected. Re-run with --allow-blind-test only for final benchmark reporting, "
            "not for rule development."
        )

    split_names = SPLITS if split == "all" else (split,)
    cases: list[dict[str, Any]] = []
    for split_name in split_names:
        split_dir = dataset_root / split_name
        if not split_dir.exists():
            raise FileNotFoundError(f"Dataset split not found: {split_dir}")
        for path in sorted([*split_dir.glob("*.json"), *split_dir.glob("*.jsonl")]):
            for case in _load_file(path):
                cases.append(_validate_case(case, source=str(path), split=split_name))
    return cases


def validation_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_split: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for case in cases:
        by_split[case["_split"]] = by_split.get(case["_split"], 0) + 1
        by_category[case["intent_category"]] = by_category.get(case["intent_category"], 0) + 1
    return {
        "total": len(cases),
        "by_split": dict(sorted(by_split.items())),
        "by_intent_category": dict(sorted(by_category.items())),
        "ids_are_unique": len({case["id"] for case in cases}) == len(cases),
    }


def evaluate_case(*, analyzer: Any, case: dict[str, Any]) -> Any:
    context_provider = (
        MockContextProvider(default_context=case["context"])
        if "context" in case
        else None
    )
    layer = ConversationUnderstandingLayer(analyzer, context_provider=context_provider)
    analysis = layer.analyze_with_debug(
        text=case["text"],
        user_id=case.get("user_id", "benchmark-user"),
        conversation_id=case["id"],
        project_id=case.get("project_id"),
        history=case.get("history", []),
    )
    result = analysis.result
    actual_task_types = [task.task_type for task in result.tasks]
    actual_descriptions = [task.task_description for task in result.tasks]
    actual_clarification_questions = _clarification_questions(result)
    actual_missing_inputs = sorted(
        {
            value
            for task in result.tasks
            for value in task.missing_inputs
        }
    )
    actual_conflicts = [
        conflict.model_dump(mode="json") if hasattr(conflict, "model_dump") else dict(conflict)
        for task in result.tasks
        for conflict in getattr(task, "conflicts", [])
    ]
    actual_conflict_types = sorted(
        {
            conflict["conflict_type"]
            for conflict in actual_conflicts
        }
    )
    partial_coverage = _partial_coverage_debug(analysis.debug)
    clarification_recovery = _evaluate_clarification_recovery(
        analyzer=analyzer,
        result=result,
        case=case,
    )

    return evaluate_case_metrics(
        case_id=case["id"],
        text=case["text"],
        split=case["_split"],
        intent_category=case["intent_category"],
        expected_task_types=case["expected_task_types"],
        actual_task_types=actual_task_types,
        expected_missing_inputs=case["missing_inputs"],
        actual_missing_inputs=actual_missing_inputs,
        required_clarification=case["required_clarification"],
        actual_clarification=result.clarification_required,
        expected_clarification_questions=case.get("expected_clarification_questions"),
        actual_clarification_questions=actual_clarification_questions,
        max_extra_clarification_questions=case.get("max_extra_clarification_questions"),
        forbidden_tasks=case["forbidden_tasks"],
        actual_task_descriptions=actual_descriptions,
        partial_coverage_rate=partial_coverage["coverage_rate"],
        uncovered_segment_count=partial_coverage["uncovered_segment_count"],
        l3_compensation_attempted=partial_coverage["llm_called"],
        l3_compensation_success=partial_coverage["l3_compensation_success"],
        expected_conflict_types=case.get("expected_conflict_types", []),
        actual_conflict_types=actual_conflict_types,
        actual_conflicts=actual_conflicts,
        expected_conflict_clarification=case.get("expected_conflict_clarification"),
        clarification_recovery=clarification_recovery,
    )


def _load_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Dataset file must contain a JSON array: {path}")
    return payload


def _validate_case(case: Any, *, source: str, split: str) -> dict[str, Any]:
    if not isinstance(case, dict):
        raise ValueError(f"Case in {source} must be an object.")
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in case:
            raise ValueError(f"Case {case.get('id')} in {source} misses required field: {field}")
        if not isinstance(case[field], expected_type):
            raise ValueError(
                f"Case {case.get('id')} in {source} field {field} must be {expected_type.__name__}."
            )
    if not case["id"].strip():
        raise ValueError(f"Case in {source} has empty id.")
    if not case["text"].strip():
        raise ValueError(f"Case {case['id']} in {source} has empty text.")
    if any(not isinstance(value, str) for value in case["expected_task_types"]):
        raise ValueError(f"Case {case['id']} in {source} expected_task_types must be strings.")
    if any(not isinstance(value, str) for value in case["missing_inputs"]):
        raise ValueError(f"Case {case['id']} in {source} missing_inputs must be strings.")
    if any(not isinstance(value, str) for value in case["forbidden_tasks"]):
        raise ValueError(f"Case {case['id']} in {source} forbidden_tasks must be strings.")
    if "expected_conflict_types" in case and (
        not isinstance(case["expected_conflict_types"], list)
        or any(not isinstance(value, str) for value in case["expected_conflict_types"])
    ):
        raise ValueError(f"Case {case['id']} in {source} expected_conflict_types must be strings.")
    if "expected_conflict_clarification" in case and not isinstance(
        case["expected_conflict_clarification"],
        bool,
    ):
        raise ValueError(f"Case {case['id']} in {source} expected_conflict_clarification must be boolean.")
    if "expected_clarification_questions" in case and (
        not isinstance(case["expected_clarification_questions"], list)
        or any(not isinstance(value, str) for value in case["expected_clarification_questions"])
    ):
        raise ValueError(f"Case {case['id']} in {source} expected_clarification_questions must be strings.")
    if "max_extra_clarification_questions" in case and not isinstance(
        case["max_extra_clarification_questions"],
        int,
    ):
        raise ValueError(f"Case {case['id']} in {source} max_extra_clarification_questions must be integer.")
    if "clarification_answer" in case and not isinstance(case["clarification_answer"], str):
        raise ValueError(f"Case {case['id']} in {source} clarification_answer must be string.")
    if "clarification_task_index" in case and not isinstance(case["clarification_task_index"], int):
        raise ValueError(f"Case {case['id']} in {source} clarification_task_index must be integer.")
    if "expected_recovery_status" in case and not isinstance(case["expected_recovery_status"], str):
        raise ValueError(f"Case {case['id']} in {source} expected_recovery_status must be string.")
    if "expected_recovery_missing_inputs" in case and (
        not isinstance(case["expected_recovery_missing_inputs"], list)
        or any(not isinstance(value, str) for value in case["expected_recovery_missing_inputs"])
    ):
        raise ValueError(f"Case {case['id']} in {source} expected_recovery_missing_inputs must be strings.")
    if "expected_recovery_final_inputs" in case and (
        not isinstance(case["expected_recovery_final_inputs"], dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in case["expected_recovery_final_inputs"].items())
    ):
        raise ValueError(f"Case {case['id']} in {source} expected_recovery_final_inputs must be string map.")
    return {**case, "_source": source, "_split": split}


def _clarification_questions(result: Any) -> list[str]:
    questions: list[str] = []
    for task in getattr(result, "tasks", []):
        for question in getattr(task, "clarification_questions", []):
            if question not in questions:
                questions.append(question)
    for question in getattr(result, "clarification_questions", []):
        if question not in questions:
            questions.append(question)
    return questions


def _evaluate_clarification_recovery(
    *,
    analyzer: Any,
    result: Any,
    case: dict[str, Any],
) -> dict[str, Any]:
    answer = case.get("clarification_answer")
    if not answer:
        return {"attempted": False, "passed": True}

    validator = getattr(analyzer, "input_validator", None)
    if validator is None:
        return {
            "attempted": True,
            "passed": False,
            "reason": "input_validator_not_available",
        }

    manager = ClarificationSessionManager()
    result_with_sessions = manager.create_sessions_for_result(result)
    tasks = list(getattr(result_with_sessions, "tasks", []))
    requested_index = case.get("clarification_task_index")
    if requested_index is not None and 0 <= requested_index < len(tasks):
        task = tasks[requested_index]
    else:
        task = next((item for item in tasks if item.clarification_session_id), None)
    if task is None or not task.clarification_session_id:
        return {
            "attempted": True,
            "passed": False,
            "reason": "clarification_session_missing",
        }

    recovered = manager.answer(
        clarification_session_id=task.clarification_session_id,
        answer=answer,
        validator=validator,
    )
    expected_status = case.get("expected_recovery_status", "ready")
    expected_missing_inputs = case.get("expected_recovery_missing_inputs", [])
    expected_final_inputs = case.get("expected_recovery_final_inputs", {})
    expected_task_type = case.get("expected_recovery_task_type")
    final_inputs = recovered.final_inputs
    final_inputs_pass = all(
        final_inputs.get(key) == value
        for key, value in expected_final_inputs.items()
    )
    task_type_pass = (
        True
        if expected_task_type is None
        else recovered.task.task_type == expected_task_type
    )
    passed = all(
        (
            recovered.task_id == task.task_id,
            recovered.status == expected_status,
            set(recovered.missing_inputs) == set(expected_missing_inputs),
            final_inputs_pass,
            task_type_pass,
        )
    )
    return {
        "attempted": True,
        "passed": passed,
        "task_id_preserved": recovered.task_id == task.task_id,
        "expected_status": expected_status,
        "actual_status": recovered.status,
        "expected_missing_inputs": expected_missing_inputs,
        "actual_missing_inputs": recovered.missing_inputs,
        "expected_final_inputs": expected_final_inputs,
        "actual_final_inputs": final_inputs,
        "expected_task_type": expected_task_type,
        "actual_task_type": recovered.task.task_type,
    }


def _split_from_path(path: Path) -> str:
    for split in SPLITS:
        if split in path.parts:
            return split
    return "custom"


def _partial_coverage_debug(debug: dict[str, Any]) -> dict[str, Any]:
    payload = debug.get("partial_coverage")
    if not isinstance(payload, dict):
        return {
            "coverage_rate": 1.0,
            "uncovered_segment_count": 0,
            "llm_called": False,
            "l3_compensation_success": False,
        }
    return {
        "coverage_rate": float(payload.get("coverage_rate", 1.0)),
        "uncovered_segment_count": int(payload.get("uncovered_segment_count", 0)),
        "llm_called": bool(payload.get("llm_called", False)),
        "l3_compensation_success": bool(payload.get("l3_compensation_success", False)),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def print_validation_report(report: dict[str, Any]) -> None:
    print(f"Benchmark dataset validation: {report['total']} cases")
    print(f"IDs unique: {report['ids_are_unique']}")
    print("By split:")
    for split, count in report["by_split"].items():
        print(f"- {split}: {count}")
    print("By intent category:")
    for category, count in report["by_intent_category"].items():
        print(f"- {category}: {count}")


def print_report(report: dict[str, Any], *, max_errors: int) -> None:
    print(f"Benchmark: {report['passed']}/{report['total']} full-pass")
    print(f"task_type_exact_accuracy: {report['task_type_exact_accuracy']:.2%}")
    print(f"task_count_accuracy: {report['task_count_accuracy']:.2%}")
    print(f"clarification_accuracy: {report['clarification_accuracy']:.2%}")
    print(f"clarification_decision_accuracy: {report['clarification_decision_accuracy']:.2%}")
    print(f"clarification_field_accuracy: {report['clarification_field_accuracy']:.2%}")
    print(f"clarification_question_accuracy: {report['clarification_question_accuracy']:.2%}")
    print(
        "no_unnecessary_clarification_question_accuracy: "
        f"{report['no_unnecessary_clarification_question_accuracy']:.2%}"
    )
    print(
        "unnecessary_clarification_question_rate: "
        f"{report['unnecessary_clarification_question_rate']:.2%}"
    )
    print(f"clarification_recovery_accuracy: {report['clarification_recovery_accuracy']:.2%}")
    print(f"context_recovery_accuracy: {report['context_recovery_accuracy']:.2%}")
    print(f"missing_inputs_accuracy: {report['missing_inputs_accuracy']:.2%}")
    print(f"missing_input_precision: {report['missing_input_precision']:.2%}")
    print(f"missing_input_recall: {report['missing_input_recall']:.2%}")
    print(f"over_clarification_rate: {report['over_clarification_rate']:.2%}")
    print(f"forbidden_pass_rate: {report['forbidden_pass_rate']:.2%}")
    print(f"false_positive_rate: {report['false_positive_rate']:.2%}")
    print(f"future_scope_false_positive_rate: {report['future_scope_false_positive_rate']:.2%}")
    print(f"negation_false_positive_rate: {report['negation_false_positive_rate']:.2%}")
    print(f"macro_f1: {report['macro_f1']:.2%}")
    print(f"partial_coverage_rate: {report['partial_coverage_rate']:.2%}")
    print(f"uncovered_segment_count: {report['uncovered_segment_count']}")
    print(f"L3 compensation success rate: {report['l3_compensation_success_rate']:.2%}")
    print(f"conflict_detection_accuracy: {report['conflict_detection_accuracy']:.2%}")
    print(f"conflict_clarification_accuracy: {report['conflict_clarification_accuracy']:.2%}")
    print(f"false_resolution_rate: {report['false_resolution_rate']:.2%}")
    print("By intent category:")
    for category, item in report["by_intent_category"].items():
        print(
            f"- {category}: {item['passed']}/{item['total']}, "
            f"task={item['task_type_exact_accuracy']:.2%}, "
            f"clarify={item['clarification_accuracy']:.2%}, "
            f"f1={item['macro_f1']:.2%}"
        )
    print(f"Failed cases: {len(report['failed_cases'])}")
    for row in report["failed_cases"][:max_errors]:
        print(f"- {row['id']} [{row['intent_category']}]")
        print(f"  expected={row['expected_task_types']}")
        print(f"  actual={row['actual_task_types']}")
        print(f"  missing={row['expected_missing_inputs']} -> {row['actual_missing_inputs']}")
        print(f"  clarification={row['required_clarification']} -> {row['actual_clarification']}")


if __name__ == "__main__":
    raise SystemExit(main())
