from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_REPORT = PROJECT_ROOT / "evaluation" / "benchmark" / "blind_test_benchmark_raw.json"
DEFAULT_FAILURE_REPORT = (
    PROJECT_ROOT / "evaluation" / "error_analysis" / "failure_report_blind_test_current.json"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation" / "benchmark" / "blind_test_report.json"
DEFAULT_MANIFEST_OUTPUT = (
    PROJECT_ROOT / "evaluation" / "benchmark" / "blind_test_version_manifest.json"
)

FROZEN_ARTIFACTS = (
    "backend/app/schemas/intent_analysis.py",
    "backend/app/services/intent_analysis_engine/task_schema/task_type_schema.py",
    "backend/app/services/intent_analysis_engine/task_schema/required_inputs.py",
    "backend/app/services/intent_analysis_engine/task_schema/validator.py",
    "backend/app/prompts/intent_analysis_prompt.txt",
    "backend/app/prompts/implicit_task_extraction_prompt.txt",
    "backend/app/services/intent_analysis_engine/operation_rules.py",
    "backend/app/services/intent_analysis_engine/analyzer.py",
    "backend/app/services/intent_analysis_engine/decomposer.py",
    "backend/app/services/intent_analysis_engine/context_recovery.py",
    "backend/app/services/task_extraction/future_scope_filter.py",
    "backend/app/config/semantic_capabilities.yaml",
    "evaluation_runner.py",
    "evaluation/benchmark/benchmark_runner.py",
)

VERSION_ARTIFACTS = (
    *FROZEN_ARTIFACTS,
    "evaluation/benchmark/datasets/manifest.json",
    "evaluation/benchmark/datasets/blind_test/blind_test_v1.jsonl",
    "evaluation/benchmark/blind_test_benchmark_raw.json",
    "evaluation/error_analysis/failure_report_blind_test_current.json",
    "evaluation/benchmark/blind_test_run.log",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the sealed blind benchmark report.")
    parser.add_argument("--raw-report", type=Path, default=DEFAULT_RAW_REPORT)
    parser.add_argument("--failure-report", type=Path, default=DEFAULT_FAILURE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_report = read_json(args.raw_report)
    failure_report = read_json(args.failure_report)
    report = build_report(
        raw_report=raw_report,
        failure_report=failure_report,
        raw_report_path=args.raw_report,
        failure_report_path=args.failure_report,
    )
    write_json(args.output, report)
    manifest = build_manifest(
        raw_report_path=args.raw_report,
        failure_report_path=args.failure_report,
        report_path=args.output,
        manifest_path=args.manifest_output,
    )
    write_json(args.manifest_output, manifest)
    print(f"Sealed report written: {args.output}")
    print(f"Version manifest written: {args.manifest_output}")
    print(f"Full-pass: {report['summary']['full_pass']}")
    print(f"Acceptance status: {report['acceptance']['status']}")
    for failure_type, count in report["failure_type_distribution"].items():
        print(f"- {failure_type}: {count}")
    return 0


def build_report(
    *,
    raw_report: dict[str, Any],
    failure_report: dict[str, Any],
    raw_report_path: Path,
    failure_report_path: Path,
) -> dict[str, Any]:
    failures = []
    failure_rows = {
        str(row.get("id")): row
        for row in raw_report.get("failed_cases", [])
        if row.get("id")
    }
    classified_rows = {
        str(row.get("id")): row
        for row in failure_report.get("failures", [])
        if row.get("id")
    }

    for case_id, row in failure_rows.items():
        failure_type = classify_failure_type(row)
        classified = classified_rows.get(case_id, {})
        failures.append(
            {
                "case_id": case_id,
                "input": row.get("text", ""),
                "predicted_result": {
                    "task_types": row.get("actual_task_types", []),
                    "missing_inputs": row.get("actual_missing_inputs", []),
                    "clarification_required": row.get("actual_clarification", False),
                    "clarification_questions": row.get("actual_clarification_questions", []),
                },
                "expected_result": {
                    "task_types": row.get("expected_task_types", []),
                    "missing_inputs": row.get("expected_missing_inputs", []),
                    "clarification_required": row.get("required_clarification", False),
                    "clarification_questions": row.get("expected_clarification_questions"),
                },
                "failure_type": failure_type,
                "failure_types": failure_types(row, failure_type),
                "intent_category": row.get("intent_category", ""),
                "raw_failure_flags": {
                    "task_type_exact": row.get("task_type_exact", False),
                    "clarification_decision_pass": row.get("clarification_decision_pass", False),
                    "missing_inputs_pass": row.get("missing_inputs_pass", False),
                    "forbidden_violations": row.get("forbidden_violations", []),
                },
                "classifier": {
                    "error_type": classified.get("error_type"),
                    "confidence": classified.get("confidence"),
                    "reason": classified.get("reason"),
                    "suggested_action": classified.get("suggested_action"),
                },
            }
        )

    failures.sort(key=lambda row: row["case_id"])
    metrics = {
        key: value
        for key, value in raw_report.items()
        if key not in {"failed_cases"}
    }
    summary = {
        "total": int(raw_report.get("total", 0)),
        "passed": int(raw_report.get("passed", 0)),
        "full_pass": f"{raw_report.get('passed', 0)}/{raw_report.get('total', 0)}",
        "full_pass_rate": ratio(raw_report.get("passed", 0), raw_report.get("total", 0)),
    }
    distribution = count_values(row["failure_type"] for row in failures)
    acceptance = acceptance_result(raw_report, failure_report)
    return {
        "report_type": "blind_sealed_benchmark",
        "split": "blind_test",
        "sealed": True,
        "development_use": False,
        "source_report": str(raw_report_path),
        "source_failure_report": str(failure_report_path),
        "summary": summary,
        "metrics": metrics,
        "failure_type_distribution": distribution,
        "acceptance": acceptance,
        "failures": failures,
    }


def classify_failure_type(row: dict[str, Any]) -> str:
    category = str(row.get("intent_category") or "")
    forbidden_violations = row.get("forbidden_violations") or []
    expected = row.get("expected_task_types") or []
    actual = row.get("actual_task_types") or []
    task_type_exact = bool(row.get("task_type_exact", actual == expected))
    clarification_pass = bool(
        row.get(
            "clarification_decision_pass",
            row.get("required_clarification", False)
            == row.get("actual_clarification", False),
        )
    )
    missing_pass = bool(
        row.get(
            "missing_inputs_pass",
            set(row.get("expected_missing_inputs", []))
            == set(row.get("actual_missing_inputs", [])),
        )
    )

    if category == "negation_expression":
        return "NEGATION_ERROR"
    if category == "future_scope":
        return "FUTURE_SCOPE_ERROR"
    if category in {"context_dependency", "omitted_expression"}:
        return "CONTEXT_RECOVERY_ERROR"
    if forbidden_violations:
        return "FALSE_POSITIVE"
    if category in {"ambiguous_request", "insufficient_information"} and not clarification_pass:
        return "CLARIFICATION_ERROR"
    if not task_type_exact:
        return "TASK_TYPE_ERROR"
    if not missing_pass:
        return "MISSING_INPUT_ERROR"
    if not clarification_pass:
        return "CLARIFICATION_ERROR"
    return "FALSE_POSITIVE"


def failure_types(row: dict[str, Any], primary: str) -> list[str]:
    types = [primary]
    if not bool(row.get("task_type_exact", True)) and "TASK_TYPE_ERROR" not in types:
        types.append("TASK_TYPE_ERROR")
    if not bool(row.get("missing_inputs_pass", True)) and "MISSING_INPUT_ERROR" not in types:
        types.append("MISSING_INPUT_ERROR")
    if not bool(row.get("clarification_decision_pass", True)) and "CLARIFICATION_ERROR" not in types:
        types.append("CLARIFICATION_ERROR")
    if row.get("forbidden_violations") and "FALSE_POSITIVE" not in types:
        types.append("FALSE_POSITIVE")
    return types


def acceptance_result(raw_report: dict[str, Any], failure_report: dict[str, Any]) -> dict[str, Any]:
    full_pass_rate = ratio(raw_report.get("passed", 0), raw_report.get("total", 0))
    false_positive_rate = float(raw_report.get("false_positive_rate", 0.0))
    negation_rate = float(raw_report.get("negation_false_positive_rate", 0.0))
    future_rate = float(raw_report.get("future_scope_false_positive_rate", 0.0))
    classified_counts = failure_report.get("by_error_type", {})
    schema_error_count = (
        int(classified_counts.get("MISSING_SCHEMA_FIELD", 0))
        + int(classified_counts.get("UNNECESSARY_REQUIRED_INPUT", 0))
        + int(classified_counts.get("WRONG_OPTIONAL_REQUIRED", 0))
    )
    criteria = {
        "full_pass_rate": {
            "actual": full_pass_rate,
            "threshold": 0.75,
            "passed": full_pass_rate >= 0.75,
        },
        "false_positive_rate": {
            "actual": false_positive_rate,
            "threshold": 0.01,
            "passed": false_positive_rate <= 0.01,
        },
        "negation_false_positive_rate": {
            "actual": negation_rate,
            "target": "near_zero",
            "passed": negation_rate <= 0.01,
        },
        "future_scope_false_positive_rate": {
            "actual": future_rate,
            "target": "near_zero",
            "passed": future_rate <= 0.01,
        },
        "serious_schema_output_errors": {
            "actual": schema_error_count,
            "threshold": 0,
            "passed": schema_error_count == 0,
        },
    }
    status = "PASS" if all(item["passed"] for item in criteria.values()) else "FAIL"
    return {
        "status": status,
        "enterprise_stage_acceptance": status == "PASS",
        "criteria": criteria,
        "note": (
            "Blind results are acceptance-only and must not be used to change rules, "
            "prompts, thresholds, schemas, or validation data."
        ),
    }


def build_manifest(
    *,
    raw_report_path: Path,
    failure_report_path: Path,
    report_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    dataset_manifest_path = PROJECT_ROOT / "evaluation" / "benchmark" / "datasets" / "manifest.json"
    dataset_manifest = read_json(dataset_manifest_path)
    revision = git_revision()
    revision_source = "git" if revision else "snapshot"
    if revision is None:
        revision = snapshot_revision(FROZEN_ARTIFACTS)
    command = (
        "$env:PYTHONPATH='backend'; "
        ".\\.venv\\Scripts\\python.exe evaluation\\benchmark\\benchmark_runner.py "
        "--split blind_test --allow-blind-test --semantic-mode local "
        "--llm-mode off --output evaluation\\benchmark\\blind_test_benchmark_raw.json"
    )
    return {
        "manifest_type": "blind_sealed_benchmark_version",
        "sealed": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "code_revision": revision,
        "code_revision_source": revision_source,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "benchmark_config": {
            "split": "blind_test",
            "semantic_mode": "local",
            "llm_mode": "off",
            "semantic_threshold": 0.50,
            "model": "LocalEvaluationEmbeddingService + LocalCapabilityVectorRepository",
            "llm_invoked": False,
            "command": command,
        },
        "dataset": {
            "manifest": str(dataset_manifest_path),
            "version": dataset_manifest.get("version"),
            "declared_split_counts": dataset_manifest.get("splits"),
        },
        "frozen_artifacts": file_inventory(FROZEN_ARTIFACTS),
        "run_artifacts": file_inventory(
            (
                _relative(raw_report_path),
                _relative(failure_report_path),
                _relative(report_path),
                _relative(manifest_path),
                "evaluation/benchmark/blind_test_run.log",
            )
        ),
        "dataset_artifacts": file_inventory(
            (
                "evaluation/benchmark/datasets/manifest.json",
                "evaluation/benchmark/datasets/blind_test/blind_test_v1.jsonl",
            )
        ),
        "freeze_assertions": {
            "tasklist_schema_frozen": True,
            "task_type_schema_frozen": True,
            "required_inputs_schema_frozen": True,
            "llm_prompt_frozen": True,
            "l1_l2_rules_frozen": True,
            "validation_optimization_code_frozen": True,
            "blind_test_used_for_development": False,
            "blind_test_added_to_validation": False,
        },
    }


def file_inventory(paths: tuple[str, ...]) -> list[dict[str, Any]]:
    inventory = []
    for relative in paths:
        path = PROJECT_ROOT / relative
        item: dict[str, Any] = {
            "path": relative,
            "exists": path.exists(),
        }
        if path.exists():
            item["sha256"] = sha256(path)
            item["size_bytes"] = path.stat().st_size
        inventory.append(item)
    return inventory


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision() -> str | None:
    head = PROJECT_ROOT / ".git" / "HEAD"
    if not head.exists():
        return None
    try:
        content = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if content.startswith("ref:"):
        ref_path = PROJECT_ROOT / ".git" / content.split(" ", 1)[1]
        if ref_path.exists():
            try:
                return ref_path.read_text(encoding="utf-8").strip() or None
            except OSError:
                return None
        packed_refs = PROJECT_ROOT / ".git" / "packed-refs"
        if packed_refs.exists():
            try:
                for line in packed_refs.read_text(encoding="utf-8").splitlines():
                    if line.startswith("#") or not line.strip():
                        continue
                    sha, ref = line.split(" ", 1)
                    if ref.strip() == content.split(" ", 1)[1]:
                        return sha.strip() or None
            except OSError:
                return None
        return None
    return content or None


def snapshot_revision(paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(paths):
        path = PROJECT_ROOT / relative
        digest.update(relative.encode("utf-8"))
        if path.exists():
            digest.update(sha256(path).encode("utf-8"))
    return f"snapshot:{digest.hexdigest()}"


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def ratio(numerator: Any, denominator: Any) -> float:
    denominator = int(denominator or 0)
    return float(numerator or 0) / denominator if denominator else 0.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
