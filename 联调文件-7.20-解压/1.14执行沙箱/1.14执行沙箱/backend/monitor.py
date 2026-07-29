from __future__ import annotations

from typing import Any


def build_monitor_snapshot(tasks: list[dict[str, Any]], policy: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    instances = [task_to_instance(task) for task in tasks]
    summary = {
        "total": len(instances),
        "success": count_status(instances, "success"),
        "failed": count_status(instances, "failed"),
        "denied": count_status(instances, "denied"),
        "timeout": count_status(instances, "timeout"),
        "running": count_status(instances, "running"),
        "queued": count_status(instances, "queued"),
    }
    latest = instances[0] if instances else None
    recent_audit = []
    for task in tasks[:5]:
        recent_audit.extend(task.get("platform_checks", {}).get("audit_events", [])[-2:])
    recent_audit = recent_audit[-10:]
    return {
        "summary": summary,
        "latest_instance": latest,
        "instances": instances,
        "recent_audit": recent_audit,
        "policy": {
            "executor": policy.get("executor", {}),
            "runtime": policy.get("runtime", {}),
            "egress_policy": policy.get("egress_policy", {}),
        },
        "readiness": readiness,
    }


def task_to_instance(task: dict[str, Any]) -> dict[str, Any]:
    checks = task.get("platform_checks", {})
    security = checks.get("security_compliance", {})
    cost = checks.get("cost_control") or {}
    logs = task.get("logs", [])
    return {
        "id": task.get("id"),
        "scenario_id": task.get("scenario_id"),
        "scenario_name": task.get("scenario_name"),
        "actor": (checks.get("account_gateway") or {}).get("actor") or task.get("audit", {}).get("actor"),
        "role": (checks.get("account_gateway") or {}).get("role"),
        "status": task.get("status"),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "duration_ms": task.get("duration_ms"),
        "timeout_seconds": task.get("limits", {}).get("timeout_seconds"),
        "memory_mb": task.get("limits", {}).get("memory_mb"),
        "cpu_cores": task.get("limits", {}).get("cpu_cores"),
        "permission_ok": security.get("allowed"),
        "required_permissions": security.get("required_permissions", []),
        "missing_permissions": security.get("missing_permissions", []),
        "egress_policy": security.get("egress_policy"),
        "cost_units": cost.get("cost_units"),
        "audit_count": len(checks.get("audit_events", [])),
        "log_count": len(logs),
        "last_event": logs[-1] if logs else None,
        "artifacts": extract_artifacts(task),
    }


def extract_artifacts(task: dict[str, Any]) -> list[dict[str, Any]]:
    result = task.get("result") or {}
    files = []
    if isinstance(result, dict):
        payload = result.get("payload") or {}
        if isinstance(payload, dict) and "files" in payload and isinstance(payload["files"], list):
            files.extend({"type": "result_file", "path": str(path)} for path in payload["files"])
    return files


def count_status(instances: list[dict[str, Any]], status: str) -> int:
    return sum(1 for item in instances if item.get("status") == status)
