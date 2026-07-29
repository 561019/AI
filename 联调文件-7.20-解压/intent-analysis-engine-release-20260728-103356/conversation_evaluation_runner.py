from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluation_runner import build_analyzer

from app.services.conversation_understanding import ConversationUnderstandingLayer


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = PROJECT_ROOT / "evaluation" / "conversation_dataset.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run complex conversation evaluation.")
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
        raise ValueError("Conversation dataset must be a JSON array.")
    return payload


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    analyzer = build_analyzer(
        semantic_mode=args.semantic_mode,
        llm_mode=args.llm_mode,
        semantic_threshold=args.semantic_threshold,
    )
    layer = ConversationUnderstandingLayer(analyzer)
    rows: list[dict[str, Any]] = []

    for case in load_cases(args.dataset):
        messages = case["conversation"]
        current_index = max(
            index for index, message in enumerate(messages) if message["role"] == "user"
        )
        current = messages[current_index]
        history = messages[:current_index]
        analysis = layer.analyze_with_debug(
            text=current["text"],
            user_id="conversation-evaluation",
            conversation_id=case["id"],
            history=history,
        )
        result = analysis.result
        actual_tasks = [task.task_type for task in result.tasks]
        rows.append(
            {
                "id": case["id"],
                "category": case["category"],
                "text": current["text"],
                "expected_tasks": case["expected_tasks"],
                "actual_tasks": actual_tasks,
                "expected_clarification": case["should_clarify"],
                "actual_clarification": result.clarification_required,
                "missing_inputs": [task.missing_inputs for task in result.tasks],
                "clarification_questions": result.clarification_questions,
                "task_type_pass": actual_tasks == case["expected_tasks"],
                "clarification_pass": result.clarification_required == case["should_clarify"],
                "decomposition_pass": len(actual_tasks) == len(case["expected_tasks"]),
            }
        )

    for row in rows:
        row["passed"] = all(
            row[field]
            for field in ("task_type_pass", "clarification_pass", "decomposition_pass")
        )

    return {
        "total": len(rows),
        "task_type_accuracy": _ratio(rows, "task_type_pass"),
        "clarification_accuracy": _ratio(rows, "clarification_pass"),
        "decomposition_accuracy": _ratio(rows, "decomposition_pass"),
        "passed_cases": sum(row["passed"] for row in rows),
        "failed_cases": [row for row in rows if not row["passed"]],
        "by_category": _by_category(rows),
    }


def _ratio(rows: list[dict[str, Any]], field: str) -> float:
    return sum(row[field] for row in rows) / len(rows) if rows else 0.0


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
        }
        for category, items in sorted(categories.items())
    }


def print_report(report: dict[str, Any], *, max_errors: int) -> None:
    print(f"复杂对话评测: {report['passed_cases']}/{report['total']} 完全通过")
    print(f"task_type准确率: {report['task_type_accuracy']:.2%}")
    print(f"clarification准确率: {report['clarification_accuracy']:.2%}")
    print(f"任务拆解准确率: {report['decomposition_accuracy']:.2%}")
    print("按场景分类:")
    for category, summary in report["by_category"].items():
        print(
            f"- {category}: {summary['passed']}/{summary['total']}, "
            f"task={summary['task_type_accuracy']:.2%}, "
            f"clarification={summary['clarification_accuracy']:.2%}"
        )
    print(f"错误案例列表: {len(report['failed_cases'])}")
    for row in report["failed_cases"][:max_errors]:
        print(f"- {row['id']} [{row['category']}] {row['text']}")
        print(f"  expected={row['expected_tasks']}")
        print(f"  actual={row['actual_tasks']}")
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
