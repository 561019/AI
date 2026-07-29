from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class DockerAdhocExecutor:
    """Runs generated code and browser retrieval with fixed sandbox controls."""

    name = "DockerAdhocExecutor"

    def __init__(self, project_root: Path, code_image: str, browser_image: str, allowed_domains: list[str]) -> None:
        self.project_root = project_root
        self.code_image = code_image
        self.browser_image = browser_image
        self.allowed_domains = set(allowed_domains)

    def run_code(self, code: str, task_input: dict[str, Any], result_dir: Path, limits: dict[str, Any]) -> dict[str, Any]:
        workspace = self._workspace(result_dir)
        (workspace / "main.py").write_text(code, encoding="utf-8")
        (workspace / "input.json").write_text(json.dumps(task_input, ensure_ascii=False), encoding="utf-8")
        proc = self._run_container(
            self.code_image,
            workspace,
            limits,
            ["python", "-I", "/workspace/main.py"],
            network="none",
        )
        stdout = redact(proc.stdout)
        stderr = redact(proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError(stderr or stdout or "generated Python program failed")
        artifacts = self._artifacts(workspace, {"main.py", "input.json"})
        result = {
            "payload": {"stdout": stdout, "stderr": stderr, "exit_code": proc.returncode},
            "files": artifacts,
            "sandbox_runtime": self._runtime(limits, "none", {"outbound_requests": 0, "policy": "network_none"}),
        }
        (workspace / "execution_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def run_browser(self, url: str, result_dir: Path, limits: dict[str, Any]) -> dict[str, Any]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or host not in self.allowed_domains:
            raise ValueError("browser URL must use http(s) and an allowlisted domain")
        docker = self._docker()
        workspace = self._workspace(result_dir)
        suffix = uuid.uuid4().hex[:10]
        network = f"sandbox-browser-{suffix}"
        proxy = f"sandbox-browser-proxy-{suffix}"
        proxy_log = ""
        try:
            self._checked([docker, "network", "create", "--internal", network], timeout=15)
            self._checked([
                docker, "run", "-d", "--rm", "--name", proxy, "--network", network,
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "64", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
                "-v", f"{self.project_root}:/app:ro", "-w", "/app", self.code_image,
                "python", "backend/egress_gateway.py", "--allow", host,
            ] + (["--serve-local", host] if host == "sandbox-allow.test" else []) + [
            ], timeout=20)
            chrome = (
                "mkdir -p /tmp/chrome/crash; chromium --headless --no-sandbox --disable-gpu "
                "--disable-dev-shm-usage --disable-background-networking --disable-crash-reporter "
                "--disable-breakpad --disable-sync --disable-default-apps --metrics-recording-only "
                "--safebrowsing-disable-auto-update --crash-dumps-dir=/tmp/chrome/crash --no-first-run "
                "--user-data-dir=/tmp/chrome --proxy-server=http://%s:18080 --dump-dom %s"
            ) % (proxy, url)
            proc = self._run_container(self.browser_image, workspace, limits, ["/bin/bash", "-lc", chrome], network=network, cap_drop=False, no_new_privileges=False, pids_limit=256, mount_workspace=False)
            proxy_log = self._checked([docker, "logs", proxy], timeout=10).stdout
            if proc.returncode != 0:
                raise RuntimeError(redact(proc.stderr or proc.stdout or "browser task failed"))
            dom = proc.stdout
            (workspace / "page.html").write_text(dom, encoding="utf-8")
            audit = parse_proxy_log(proxy_log)
            result = {
                "payload": {
                    "url": url,
                    "host": host,
                    "dom_sha256": hashlib.sha256(dom.encode("utf-8")).hexdigest(),
                    "dom_preview": redact(dom[:800]),
                    "outbound_requests": len(audit),
                },
                "files": self._artifacts(workspace, set()),
                "sandbox_runtime": self._runtime(limits, "egress_proxy", {"outbound_audit": audit, "policy": "allowlist_only"}, capabilities="default_for_chromium", no_new_privileges=False, pids_limit=256),
            }
            (workspace / "execution_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            subprocess.run([docker, "rm", "-f", proxy], capture_output=True, text=True, timeout=10)
            subprocess.run([docker, "network", "rm", network], capture_output=True, text=True, timeout=10)

    def _run_container(self, image: str, workspace: Path, limits: dict[str, Any], command: list[str], network: str, cap_drop: bool = True, no_new_privileges: bool = True, pids_limit: int = 64, mount_workspace: bool = True) -> subprocess.CompletedProcess[str]:
        docker = self._docker()
        timeout = int(limits["timeout_seconds"])
        proc = subprocess.run(
            [
                docker, "run", "--rm", "--network", network, "--cpus", str(limits["cpu_cores"]),
                "--memory", f"{int(limits['memory_mb'])}m", "--pids-limit", str(pids_limit), "--read-only",
            ] + (["--cap-drop", "ALL"] if cap_drop else []) + (["--security-opt", "no-new-privileges"] if no_new_privileges else []) + [
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m", "--tmpfs", "/run:rw,nosuid,size=64m", "--tmpfs", "/root:rw,nosuid,size=64m", "--tmpfs", "/var/tmp:rw,nosuid,size=64m",
            ] + (["-v", f"{workspace}:/workspace:rw", "-w", "/workspace"] if mount_workspace else []) + [image,
            ] + command,
            capture_output=True, text=True, timeout=timeout,
        )
        return proc

    def _workspace(self, result_dir: Path) -> Path:
        result_dir.mkdir(parents=True, exist_ok=True)
        result_dir.chmod(0o777)
        return result_dir

    def _runtime(self, limits: dict[str, Any], network: str, egress: dict[str, Any], capabilities: str = "dropped", no_new_privileges: bool = True, pids_limit: int = 64) -> dict[str, Any]:
        return {
            "executor": self.name, "isolation": "docker_container", "network": network,
            "read_only_rootfs": True, "capabilities": capabilities, "no_new_privileges": no_new_privileges,
            "pids_limit": pids_limit, "memory_mb": int(limits["memory_mb"]), "cpu_cores": limits["cpu_cores"],
            "egress": egress,
        }

    def _artifacts(self, workspace: Path, excluded: set[str]) -> list[str]:
        return [str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file() and path.name not in excluded]

    def _docker(self) -> str:
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("docker command not found")
        return docker

    def _checked(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(redact(proc.stderr or proc.stdout or "docker command failed"))
        return proc


def parse_proxy_log(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append({key: item.get(key) for key in ("time", "method", "host", "url", "allowed", "status", "duration_ms", "body_bytes", "body_sha256", "content_type")})
    return rows


def redact(text: str) -> str:
    return text.replace("Authorization:", "Authorization:[REDACTED]")[:12000]
