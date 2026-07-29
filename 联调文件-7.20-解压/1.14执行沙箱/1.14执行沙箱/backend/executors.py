from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from backend.templates import run_template


class ExecutionResult(dict):
    pass


class SandboxExecutor(ABC):
    name: str

    @abstractmethod
    def run(
        self,
        scenario_id: str,
        task_input: dict[str, Any],
        result_dir: Path,
        limits: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "available": True}


class LocalTemplateExecutor(SandboxExecutor):
    name = "LocalTemplateExecutor"

    def run(
        self,
        scenario_id: str,
        task_input: dict[str, Any],
        result_dir: Path,
        limits: dict[str, Any],
    ) -> dict[str, Any]:
        result = run_template(
            scenario_id,
            task_input,
            result_dir,
            int(limits.get("timeout_seconds", 10)),
        )
        result["sandbox_runtime"] = {
            "executor": self.name,
            "isolation": "local_process_fallback",
            "note": "Fallback mode only. Use Docker/Cube for real isolation.",
        }
        return result


class DockerTemplateExecutor(SandboxExecutor):
    name = "DockerTemplateExecutor"

    def __init__(self, project_root: Path, image: str = "python:3.12-slim"):
        self.project_root = project_root
        self.image = image

    def health(self) -> dict[str, Any]:
        docker_path = shutil.which("docker")
        if not docker_path:
            return {"name": self.name, "available": False, "reason": "docker command not found"}
        try:
            proc = subprocess.run(
                [docker_path, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as exc:
            return {"name": self.name, "available": False, "reason": str(exc)}
        if proc.returncode != 0:
            return {"name": self.name, "available": False, "reason": (proc.stderr or proc.stdout).strip()}
        return {"name": self.name, "available": True, "server_version": proc.stdout.strip(), "image": self.image}

    def run(
        self,
        scenario_id: str,
        task_input: dict[str, Any],
        result_dir: Path,
        limits: dict[str, Any],
    ) -> dict[str, Any]:
        docker_path = shutil.which("docker")
        if not docker_path:
            raise RuntimeError("Docker is not installed or not in PATH")

        result_dir.mkdir(parents=True, exist_ok=True)
        input_file = result_dir / "input.json"
        output_file = result_dir / "docker_result.json"
        input_file.write_text(json.dumps(task_input, ensure_ascii=False), encoding="utf-8")

        memory_mb = int(limits.get("memory_mb", 512))
        cpu_cores = str(limits.get("cpu_cores", 1))
        timeout_seconds = int(limits.get("timeout_seconds", 10))
        container_name = f"agent-sandbox-{uuid.uuid4().hex[:12]}"

        command = [
            docker_path,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--cpus",
            cpu_cores,
            "--memory",
            f"{memory_mb}m",
            "--pids-limit",
            "128",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "-v",
            f"{self.project_root}:/app:ro",
            "-v",
            f"{result_dir}:/results:rw",
            "-w",
            "/app",
            self.image,
            "python",
            "backend/template_cli.py",
            scenario_id,
            "/results/input.json",
            "/results",
            str(timeout_seconds),
        ]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            subprocess.run([docker_path, "rm", "-f", container_name], capture_output=True, text=True, timeout=5)
            raise TimeoutError(f"Docker sandbox exceeded {timeout_seconds} seconds and was stopped") from exc
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip() or "Docker sandbox execution failed")
        if not output_file.exists():
            raise RuntimeError("Docker sandbox finished but did not produce docker_result.json")
        result = json.loads(output_file.read_text(encoding="utf-8"))
        result["sandbox_runtime"] = {
            "executor": self.name,
            "isolation": "docker_container",
            "image": self.image,
            "network": "none",
            "read_only_rootfs": True,
            "memory_mb": memory_mb,
            "cpu_cores": cpu_cores,
        }
        return result


def build_executor(config: dict[str, Any], project_root: Path) -> SandboxExecutor:
    runtime = config.get("runtime", {})
    selected = str(runtime.get("executor", runtime.get("default_executor", "local"))).lower()
    if selected in {"docker", "dockertemplateexecutor"}:
        return DockerTemplateExecutor(project_root, str(runtime.get("docker_image", "python:3.12-slim")))
    if selected == "auto":
        docker = DockerTemplateExecutor(project_root, str(runtime.get("docker_image", "python:3.12-slim")))
        if docker.health().get("available"):
            return docker
    return LocalTemplateExecutor()
