from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from backend.service import SandboxService


class DockerE2BAdapter:
    """Small E2B-like adapter backed by the existing Docker task service.

    This is not a full E2B SDK implementation. It gives L2 engines a familiar
    create/run/query/destroy shape while preserving the current Docker sandbox
    controls and task evidence.
    """

    def __init__(self, root: Path, service: SandboxService):
        self.root = root
        self.service = service
        self.session_file = root / "data" / "e2b_sessions.json"
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.session_file.exists():
            self.session_file.write_text("[]", encoding="utf-8")

    def capability(self) -> dict[str, Any]:
        return {
            "adapter": "DockerE2BAdapter",
            "compatibility": "e2b_like_not_full_sdk",
            "runtime": "docker",
            "executor": self.service.executor.health(),
            "supported_operations": [
                "create_sandbox",
                "run_template",
                "get_sandbox",
                "destroy_sandbox",
            ],
            "notes": [
                "Backed by DockerTemplateExecutor, not Cube native E2B.",
                "Current adapter runs registered scenario templates and returns task evidence.",
                "Full arbitrary-code E2B SDK compatibility is a future enhancement.",
            ],
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        return sorted(self._read(), key=lambda item: item.get("created_at", ""), reverse=True)

    def get_session(self, sandbox_id: str) -> dict[str, Any] | None:
        return next((item for item in self._read() if item.get("id") == sandbox_id), None)

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = {
            "id": "sbx_" + uuid.uuid4().hex[:12],
            "status": "running",
            "runtime": "docker",
            "adapter": "DockerE2BAdapter",
            "created_at": now(),
            "destroyed_at": None,
            "actor": payload.get("actor", "demo-user"),
            "agent": payload.get("agent", "e2b-like-agent"),
            "limits": {
                "timeout_seconds": int(payload.get("timeout_seconds", 10)),
                "memory_mb": int(payload.get("memory_mb", 512)),
                "cpu_cores": float(payload.get("cpu_cores", 1)),
            },
            "tasks": [],
            "metadata": payload.get("metadata", {}),
        }
        sessions = self._read()
        sessions.append(session)
        self._write(sessions)
        return session

    def destroy_session(self, sandbox_id: str) -> dict[str, Any]:
        sessions = self._read()
        for session in sessions:
            if session.get("id") == sandbox_id:
                session["status"] = "destroyed"
                session["destroyed_at"] = now()
                self._write(sessions)
                return session
        raise ValueError(f"unknown sandbox_id: {sandbox_id}")

    def run_template(self, sandbox_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sessions = self._read()
        session = next((item for item in sessions if item.get("id") == sandbox_id), None)
        if not session:
            raise ValueError(f"unknown sandbox_id: {sandbox_id}")
        if session.get("status") != "running":
            raise ValueError(f"sandbox is not running: {sandbox_id}")

        scenario_id = str(payload.get("scenario_id", "")).strip()
        if not scenario_id:
            raise ValueError("scenario_id is required")
        task_payload = {
            "scenario_id": scenario_id,
            "actor": payload.get("actor", session.get("actor", "demo-user")),
            "agent": payload.get("agent", session.get("agent", "e2b-like-agent")),
            "timeout_seconds": int(payload.get("timeout_seconds", session.get("limits", {}).get("timeout_seconds", 10))),
            "memory_mb": int(payload.get("memory_mb", session.get("limits", {}).get("memory_mb", 512))),
            "cpu_cores": float(payload.get("cpu_cores", session.get("limits", {}).get("cpu_cores", 1))),
            "input": payload.get("input", {}),
        }
        task = self.service.create_task(task_payload)
        run_record = {
            "task_id": task.get("id"),
            "scenario_id": scenario_id,
            "status": task.get("status"),
            "created_at": task.get("created_at"),
            "finished_at": task.get("finished_at"),
            "executor": task.get("executor"),
        }
        session["tasks"].append(run_record)
        self._write(sessions)
        return {
            "sandbox_id": sandbox_id,
            "run": run_record,
            "task": task,
        }

    def _read(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def _write(self, sessions: list[dict[str, Any]]) -> None:
        self.session_file.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
