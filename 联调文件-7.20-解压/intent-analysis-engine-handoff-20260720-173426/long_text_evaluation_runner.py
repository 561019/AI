from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation_runner import build_analyzer

from app.services.conversation_understanding import ConversationUnderstandingLayer


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = PROJECT_ROOT / "evaluation" / "long_text_dataset.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run long-context task extraction evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--semantic-mode", choices=["local", "milvus", "off"], default="local")
    parser.add_argument("--llm-mode", choices=["off", "live"], default="off")
    parser.add_argument("--semantic-threshold", type=float, default=0.50)
    parser.add_argument("--max-errors", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Long-text dataset must be a JSON array.")
    return payload


def _ordered_recall(expected: list[str], actual: list[str]) -> float:
    if not expected:
        return 1.0
    remaining = Counter(actual)
    matched = 0
    for value in expected:
        if remaining[value] > 0:
            matched += 1
            remaining[value] -= 1
    return matched / len(expected)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    analyzer = build_analyzer(
        semantic_mode=args.semantic_mode,
        llm_mode=args.llm_mode,
        semantic_threshold=args.semantic_threshold,
    )
    layer = ConversationUnderstandingLayer(analyzer)
    rows: list[dict[str, Any]] = []

    for case in load_cases(args.dataset):
        analysis = layer.analyze_with_debug(
            text=case["text"],
            user_id="long-text-evaluation",
            conversation_id=case["id"],
        )
        result = analysis.result
        extraction = analysis.debug.get("long_context_extraction") or {}
        candidates = extraction.get("merged_candidates", [])
        actual_actions = [candidate["action"] for candidate in candidates]
        actual_tasks = [task.task_type for task in result.tasks]
        candidate_recall = _ordered_recall(case["expected_actions"], actual_actions)
        row = {
            "id": case["id"],
            "category": case["category"],
            "text_length": len(case["text"]),
            "expected_actions": case["expected_actions"],
            "actual_actions": actual_actions,
            "candidate_recall": candidate_recall,
            "expected_tasks": case["expected_tasks"],
            "actual_tasks": actual_tasks,
            "expected_clarification": case["should_clarify"],
            "actual_clarification": result.clarification_required,
            "missing_inputs": [task.missing_inputs for task in result.tasks],
            "task_type_pass": actual_tasks == case["expected_tasks"],
            "clarification_pass": result.clarification_required == case["should_clarify"],
            "decomposition_pass": len(actual_tasks) == len(case["expected_tasks"]),
            "candidate_pass": candidate_recall == 1.0,
        }
        row["passed"] = all(
            row[field]
            for field in (
                "task_type_pass",
                "clarification_pass",
                "decomposition_pass",
                "candidate_pass",
            )
        )
        rows.append(row)

    return {
        "total": len(rows),
        "passed_cases": sum(row["passed"] for row in rows),
        "task_type_accuracy": _ratio(rows, "task_type_pass"),
        "clarification_accuracy": _ratio(rows, "clarification_pass"),
        "decomposition_accuracy": _ratio(rows, "decomposition_pass"),
        "candidate_recall": (
            sum(row["candidate_recall"] for row in rows) / len(rows) if rows else 0.0
        ),
        "failed_cases": [row for row in rows if not row["passed"]],
        "by_category": _by_category(rows),
    }


def _ratio(rows: list[dict[str, Any]], field: str) -> float:
    return sum(bool(row[field]) for row in rows) / len(rows) if rows else 0.0


def _by_category(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    categories: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        categories.setdefault(row["category"], []).append(row)
    return {
        category: {
            "total": len(items),
            "passed": sum(item["passed"] for item in items),
            "task_type_accuracy": _ratio(items, "task_type_pass"),
            "clarification_accuracy": _ratio(items, "clarification_pass"),
            "decomposition_accuracy": _ratio(items, "decomposition_pass"),
            "candidate_recall": sum(item["candidate_recall"] for item in items) / len(items),
        }
        for category, items in sorted(categories.items())
    }


def print_report(report: dict[str, Any], *, max_errors: int) -> None:
    print(f"长文本评测: {report['passed_cases']}/{report['total']} 完全通过")
    print(f"task_type准确率: {report['task_type_accuracy']:.2%}")
    print(f"clarification准确率: {report['clarification_accuracy']:.2%}")
    print(f"任务拆解准确率: {report['decomposition_accuracy']:.2%}")
    print(f"任务候选召回率: {report['candidate_recall']:.2%}")
    print("按场景分类:")
    for category, summary in report["by_category"].items():
        print(
            f"- {category}: {summary['passed']}/{summary['total']}, "
            f"task={summary['task_type_accuracy']:.2%}, "
            f"clarification={summary['clarification_accuracy']:.2%}, "
            f"decomposition={summary['decomposition_accuracy']:.2%}, "
            f"candidate_recall={summary['candidate_recall']:.2%}"
        )
    print(f"错误案例列表: {len(report['failed_cases'])}")
    for row in report["failed_cases"][:max_errors]:
        print(f"- {row['id']} [{row['category']}] length={row['text_length']}")
        print(f"  actions={row['expected_actions']} -> {row['actual_actions']}")
        print(f"  tasks={row['expected_tasks']} -> {row['actual_tasks']}")
        print(
            "  clarification="
            f"{row['expected_clarification']} -> {row['actual_clarification']}"
        )
        print(f"  missing_inputs={row['missing_inputs']}")


def main() -> int:
    args = parse_args()
    report = evaluate(args)
    print_report(report, max_errors=args.max_errors)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
