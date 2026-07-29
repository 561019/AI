from __future__ import annotations

import json
import hashlib
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.executors import SandboxExecutor, build_executor
from backend.adhoc_executor import DockerAdhocExecutor
from backend.mock_platform import MockPlatform


class SandboxService:
    def __init__(self, root: Path):
        self.root = root
        self.data_dir = root / "data"
        self.result_dir = self.data_dir / "results"
        self.snapshot_dir = self.data_dir / "snapshots"
        self.task_file = self.data_dir / "tasks.json"
        self.scenario_file = root / "scenario_templates" / "scenarios.json"
        self.config_file = root / "config.example.json"
        self._task_lock = threading.RLock()
        self.config = self._config()
        self.executor: SandboxExecutor = build_executor(self.config, root)
        runtime = self.config.get("runtime", {})
        self.adhoc_executor = DockerAdhocExecutor(root, str(runtime.get("docker_image")), str(runtime.get("browser_image")), list(self.config.get("egress_policy", {}).get("allowed_domains", [])))
        self.mock_platform = MockPlatform()
        self.data_dir.mkdir(exist_ok=True)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if not self.task_file.exists():
            self.task_file.write_text("[]", encoding="utf-8")

    def list_scenarios(self) -> list[dict[str, Any]]:
        return json.loads(self.scenario_file.read_text(encoding="utf-8"))

    def list_tasks(self) -> list[dict[str, Any]]:
        return sorted(self._read_tasks(), key=lambda t: t.get("created_at", ""), reverse=True)

    def policy(self) -> dict[str, Any]:
        return {
            "executor": self.executor.health(),
            "runtime": self.config.get("runtime", {}),
            "egress_policy": self.config.get("egress_policy", {}),
            "integration_placeholders": self.config.get("integration_placeholders", {}),
        }

    def readiness(self) -> dict[str, Any]:
        scenarios = self.list_scenarios()
        checks = [
            {"name": "scenario_templates_loaded", "ok": len(scenarios) == 20, "detail": f"{len(scenarios)} scenarios"},
            {"name": "task_store_available", "ok": self.task_file.exists(), "detail": str(self.task_file)},
            {"name": "result_dir_available", "ok": self.result_dir.exists(), "detail": str(self.result_dir)},
            {"name": "executor_available", "ok": bool(self.executor.health().get("available")), "detail": self.executor.health()},
        ]
        return {"ok": all(item["ok"] for item in checks), "checks": checks}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return next((t for t in self._read_tasks() if t.get("id") == task_id), None)

    def create_task(
        self,
        payload: dict[str, Any],
        progress: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        scenario_id = str(payload.get("scenario_id", "")).strip()
        scenarios = {s["id"]: s for s in self.list_scenarios()}
        if not scenario_id:
            raise ValueError("scenario_id is required")
        if scenario_id not in scenarios:
            raise ValueError(f"unknown scenario_id: {scenario_id}")

        task = {
            "id": uuid.uuid4().hex[:12],
            "scenario_id": scenario_id,
            "kind": "template",
            "scenario_name": scenarios[scenario_id]["name"],
            "status": "queued",
            "created_at": now(),
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "input": payload.get("input", {}),
            "result": None,
            "logs": [],
            "limits": {
                "timeout_seconds": int(payload.get("timeout_seconds", 10)),
                "memory_mb": int(payload.get("memory_mb", 512)),
                "cpu_cores": float(payload.get("cpu_cores", 1)),
            },
            "audit": {
                "actor": payload.get("actor", "demo-user"),
                "agent": payload.get("agent", "demo-agent"),
                "module": "L1.14 execution sandbox",
                "trace_id": payload.get("trace_id"),
                "caller": payload.get("caller", {}),
            },
            "platform_checks": {},
            "egress_policy": self._config().get("egress_policy", {}),
            "executor": self.executor.name,
        }
        self._save(task)
        notify(progress, "task.accepted", "任务记录已创建", {"task_id": task["id"]})
        self._run(task, progress)
        return self.get_task(task["id"]) or task

    def create_code_task(self, payload: dict[str, Any], progress: Callable[[str, str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
        return self._create_adhoc_task("code", payload, progress)

    def create_browser_task(self, payload: dict[str, Any], progress: Callable[[str, str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
        return self._create_adhoc_task("browser", payload, progress)

    def _create_adhoc_task(self, kind: str, payload: dict[str, Any], progress: Callable[[str, str, dict[str, Any]], None] | None) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        company_id = str(payload.get("caller", {}).get("company_id", "hanhe-group"))
        task = {
            "id": task_id, "scenario_id": f"adhoc_{kind}", "scenario_name": "AI 临时代码运行" if kind == "code" else "浏览器网页采集", "kind": kind,
            "status": "queued", "created_at": now(), "started_at": None, "finished_at": None, "duration_ms": None,
            "input": payload.get("input", {}), "code": payload.get("code"), "url": payload.get("url"), "result": None, "logs": [],
            "limits": {"timeout_seconds": int(payload.get("timeout_seconds", 10)), "memory_mb": int(payload.get("memory_mb", 512)), "cpu_cores": float(payload.get("cpu_cores", 1))},
            "audit": {"actor": payload.get("actor", "demo-user"), "agent": payload.get("agent", "demo-agent"), "module": "L1.14 execution sandbox", "trace_id": payload.get("trace_id"), "caller": payload.get("caller", {}), "company_id": company_id},
            "retain_snapshot": bool(payload.get("retain_snapshot", False)), "platform_checks": {}, "egress_policy": self._config().get("egress_policy", {}), "executor": self.adhoc_executor.name,
        }
        self._save(task)
        notify(progress, "task.accepted", "任务记录已创建", {"task_id": task_id})
        self._run(task, progress)
        return self.get_task(task_id) or task

    def _run(
        self,
        task: dict[str, Any],
        progress: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        start = time.perf_counter()
        task["status"] = "running"
        task["started_at"] = now()
        actor_info = self.mock_platform.account.resolve_actor(task["audit"]["actor"])
        notify(
            progress,
            "identity.resolved",
            "发起人身份与岗位已解析",
            {
                "actor": actor_info.get("actor"),
                "department": actor_info.get("department"),
                "role": actor_info.get("role"),
            },
        )
        security_check = self.mock_platform.security.precheck(task["scenario_id"], actor_info, self.mock_platform.account)
        notify(
            progress,
            "permission.checked",
            "场景权限预检已完成",
            {
                "allowed": security_check.get("allowed"),
                "required_permissions": security_check.get("required_permissions", []),
                "missing_permissions": security_check.get("missing_permissions", []),
            },
        )
        task["platform_checks"] = {
            "account_gateway": actor_info,
            "security_compliance": security_check,
            "sandbox_execution": {
                "started": False,
                "reason": "awaiting_permission_precheck",
            },
            "mock_sources": [],
            "cost_control": None,
            "audit_events": [
                self.mock_platform.security.audit("task_received", {"task_id": task["id"], "scenario_id": task["scenario_id"]})
            ],
        }
        task["logs"] += [
            log("sandbox.requested", "L2 engine requested sandbox execution"),
            log("account.resolved", f"Actor resolved as {actor_info['role']} / {actor_info['department']}"),
            log("security.precheck", "Security precheck passed" if security_check["allowed"] else "Security precheck denied", "info" if security_check["allowed"] else "warning"),
        ]
        self._save(task)
        sandbox_started = False
        try:
            if not security_check["allowed"]:
                task["platform_checks"]["sandbox_execution"] = {
                    "started": False,
                    "reason": "permission_precheck_denied",
                }
                task["logs"].append(log("sandbox.not_started", "Permission precheck denied; Docker executor was not called", "warning"))
                raise PermissionError(f"missing permissions: {', '.join(security_check['missing_permissions'])}")
            sandbox_started = True
            task["platform_checks"]["sandbox_execution"] = {
                "started": True,
                "reason": "permission_precheck_passed",
            }
            task["logs"] += [
                log("sandbox.created", "Docker sandbox execution room created"),
                log("sandbox.policy_attached", "Timeout/resource/egress policy attached"),
            ]
            notify(
                progress,
                "sandbox.preparing",
                "权限通过，开始创建受限 Docker 执行环境",
                {"executor": self.executor.name, "limits": task["limits"]},
            )
            enriched_input = self.mock_platform.enrich_input(task["scenario_id"], task["input"]) if task.get("kind") == "template" else task["input"]
            if task.get("kind") == "template" and enriched_input != task["input"]:
                task["platform_checks"]["mock_sources"].append("mock_erp_or_oa")
                task["logs"].append(log("mock.data_loaded", "Mock ERP/OA data loaded for feasibility validation"))
            if task.get("kind") == "code":
                result = self.adhoc_executor.run_code(str(task.get("code", "")), enriched_input, self.result_dir / task["audit"]["company_id"] / task["id"], task["limits"])
            elif task.get("kind") == "browser":
                result = self.adhoc_executor.run_browser(str(task.get("url", "")), self.result_dir / task["audit"]["company_id"] / task["id"], task["limits"])
            else:
                result = self.executor.run(task["scenario_id"], enriched_input, self.result_dir / task["id"], task["limits"])
            task["status"] = "success"
            task["result"] = result
            task["logs"].append(log("sandbox.result_collected", "Result collected"))
            notify(
                progress,
                "sandbox.result_collected",
                "Docker 任务完成，业务结果和文件已取回",
                {"task_id": task["id"], "files": result.get("files", [])},
            )
        except PermissionError as exc:
            task["status"] = "denied"
            task["result"] = {"error": str(exc), "decision": "permission_denied"}
            task["logs"].append(log("sandbox.denied", str(exc), "warning"))
            notify(
                progress,
                "task.rejected",
                "权限不足，任务在 Docker 创建前终止",
                {"missing_permissions": security_check.get("missing_permissions", [])},
            )
        except TimeoutError as exc:
            task["status"] = "timeout"
            task["result"] = {"error": str(exc)}
            task["logs"].append(log("sandbox.timeout", str(exc), "warning"))
            notify(progress, "task.timeout", "任务超过运行时长限制并已停止", {"error": str(exc)})
        except Exception as exc:
            task["status"] = "failed"
            task["result"] = {"error": str(exc)}
            task["logs"].append(log("sandbox.failed", str(exc), "error"))
            notify(progress, "task.failed", "沙箱执行过程发生错误", {"error": str(exc)})
        finally:
            task["duration_ms"] = int((time.perf_counter() - start) * 1000)
            task["finished_at"] = now()
            if sandbox_started:
                task["platform_checks"]["cost_control"] = self.mock_platform.cost.record(task)
            else:
                task["platform_checks"]["cost_control"] = {
                    "meter": "not_applicable_precheck_denied",
                    "duration_ms": task["duration_ms"],
                    "memory_mb": 0,
                    "cpu_cores": 0,
                    "cost_units": 0,
                    "reason": "Docker sandbox was not started",
                }
            task["platform_checks"]["audit_events"].append(
                self.mock_platform.security.audit("task_finished", {"task_id": task["id"], "status": task["status"]})
            )
            if sandbox_started:
                task["logs"].append(log("sandbox.destroyed", "Docker sandbox execution room destroyed"))
                task["logs"].append(log("cost.reported", "Mock usage reported to L1.12 cost control"))
            else:
                task["logs"].append(log("cost.skipped", "No sandbox resource cost recorded because execution was denied before Docker"))
            if task.get("retain_snapshot") and sandbox_started:
                task["snapshot"] = self._write_snapshot(task)
                task["logs"].append(log("sandbox.snapshot_saved", "Immutable execution evidence snapshot saved"))
            self._save(task)
            notify(
                progress,
                "task.finished",
                "任务状态、证据和审计记录已保存",
                {"task_id": task["id"], "status": task["status"], "duration_ms": task["duration_ms"]},
            )

    def _write_snapshot(self, task: dict[str, Any]) -> dict[str, Any]:
        result_root = self.result_dir / task["audit"].get("company_id", "hanhe-group") / task["id"]
        artifacts = []
        if result_root.exists():
            for path in result_root.rglob("*"):
                if path.is_file():
                    artifacts.append({"path": str(path.relative_to(self.result_dir)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
        snapshot = {"snapshot_id": f"snap-{task['id']}", "created_at": now(), "task_id": task["id"], "company_id": task["audit"].get("company_id"), "kind": task.get("kind"), "limits": task.get("limits"), "runtime": (task.get("result") or {}).get("sandbox_runtime", {}), "artifacts": artifacts, "logs": task.get("logs", [])}
        path = self.snapshot_dir / f"snap-{task['id']}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"snapshot_id": snapshot["snapshot_id"], "path": str(path.relative_to(self.data_dir)), "artifact_count": len(artifacts)}

    def _config(self) -> dict[str, Any]:
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def _read_tasks(self) -> list[dict[str, Any]]:
        with self._task_lock:
            try:
                data = json.loads(self.task_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = []
        return data if isinstance(data, list) else []

    def _save(self, task: dict[str, Any]) -> None:
        with self._task_lock:
            tasks = self._read_tasks()
            for idx, old in enumerate(tasks):
                if old.get("id") == task.get("id"):
                    tasks[idx] = task
                    break
            else:
                tasks.append(task)
            tmp = self.task_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.task_file)


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(event: str, message: str, level: str = "info") -> dict[str, str]:
    return {"time": now(), "level": level, "event": event, "message": message}


def notify(
    progress: Callable[[str, str, dict[str, Any]], None] | None,
    kind: str,
    detail: str,
    data: dict[str, Any],
) -> None:
    if not progress:
        return
    try:
        progress(kind, detail, data)
    except Exception:
        # Progress reporting must never change the task execution outcome.
        return
