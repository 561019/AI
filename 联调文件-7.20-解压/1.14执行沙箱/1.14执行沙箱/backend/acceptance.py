from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from backend.service import SandboxService
from backend.verification import verify_browser_sandbox, verify_credential_injection, verify_e2b_like_adapter, verify_egress_allowlist_gateway, verify_hanhe_finance_invoice_e2e, verify_hanhe_purchase_plan_e2e, verify_hanhe_role_scenario_e2e


def run_acceptance_checks(project_root: Path) -> dict[str, Any]:
    checks = [
        check_lifecycle(project_root),
        check_result_files(project_root),
        check_docker_available(),
        check_host_file_isolation(project_root),
        check_resource_timeout(project_root),
        check_egress_allowlist(project_root),
        check_browser_sandbox(project_root),
        check_credential_injection(project_root),
        check_e2b_like_adapter(project_root),
        check_hanhe_role_scenario(project_root),
        check_hanhe_finance_scenario(project_root),
        check_hanhe_purchase_scenario(project_root),
        check_cube_ready(),
    ]
    summary = {"passed": 0, "partial": 0, "failed": 0, "blocked": 0, "future": 0}
    for item in checks:
        summary[item["status"]] += 1
    return {
        "overall": "docker_based_current_delivery_ready_cube_future_enhancement",
        "runtime_decision": "Docker is the accepted runtime for current L1 capability-package delivery; Cube Sandbox is tracked as a future stronger isolation option.",
        "summary": summary,
        "checks": checks,
    }


def check_lifecycle(project_root: Path) -> dict[str, Any]:
    task_file = project_root / "data" / "tasks.json"
    if not task_file.exists():
        return blocked("sandbox lifecycle", "No task file exists yet. Submit a task first.")
    try:
        tasks = json.loads(task_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return failed("sandbox lifecycle", "Task file is not valid JSON.")
    if not tasks:
        return blocked("sandbox lifecycle", "No task has been submitted yet.")
    latest = next((task for task in reversed(tasks) if task.get("status") == "success"), tasks[-1])
    events = [item.get("event") for item in latest.get("logs", [])]
    required = ["sandbox.requested", "sandbox.created", "sandbox.result_collected", "sandbox.destroyed"]
    missing = [event for event in required if event not in events]
    if missing:
        return partial("sandbox lifecycle", f"Lifecycle exists but missing events: {missing}")
    return passed("sandbox lifecycle", "Task lifecycle has request/create/result/destroy logs.")


def check_result_files(project_root: Path) -> dict[str, Any]:
    result_dir = project_root / "data" / "results"
    files = list(result_dir.rglob("*.*")) if result_dir.exists() else []
    if not files:
        return blocked("result collection", "No result files exist yet.")
    return passed("result collection", f"Found {len(files)} result files.")


def check_docker_available() -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return blocked("real container isolation", "Docker command not found. Real container isolation is not active.")
    try:
        proc = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=8)
    except Exception as exc:
        return blocked("real container isolation", f"Docker exists but is not usable: {exc}")
    if proc.returncode != 0:
        return blocked("real container isolation", (proc.stderr or proc.stdout).strip())
    return passed("real container isolation", f"Docker server version {proc.stdout.strip()} is available.")


def check_host_file_isolation(project_root: Path) -> dict[str, Any]:
    docker_status = check_docker_available()
    if docker_status["status"] != "passed":
        return blocked("host file isolation", "Cannot prove host-file isolation until Docker/Cube/VM sandbox is running.")
    docker = shutil.which("docker")
    image = docker_image(project_root)
    sentinel = project_root.parent / "host_secret_should_not_leak.txt"
    sentinel.write_text("sandbox must not read this host file", encoding="utf-8")
    code = (
        "from pathlib import Path\n"
        f"if Path({str(sentinel)!r}).exists(): raise SystemExit('host secret leaked')\n"
        "try:\n"
        "    Path('/app/host_write_probe.txt').write_text('bad')\n"
        "    raise SystemExit('read-only mount was writable')\n"
        "except OSError:\n"
        "    pass\n"
        "print('isolated')\n"
    )
    try:
        proc = subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m",
                "-v",
                f"{project_root}:/app:ro",
                "-w",
                "/app",
                image,
                "python",
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        sentinel.unlink(missing_ok=True)
    if proc.returncode == 0:
        return passed("host file isolation", "Container could not read an unmounted host file and could not write to the read-only app mount.")
    return failed("host file isolation", (proc.stderr or proc.stdout).strip())


def check_resource_timeout(project_root: Path) -> dict[str, Any]:
    docker_status = check_docker_available()
    if docker_status["status"] != "passed":
        return partial("resource timeout", "App-layer timeout exists; Docker/Cube runtime is needed for container-level stop.")
    docker = shutil.which("docker")
    image = docker_image(project_root)
    container_name = f"acceptance-timeout-{uuid.uuid4().hex[:10]}"
    try:
        subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "--name",
                container_name,
                "--network",
                "none",
                "--cpus",
                "0.5",
                "--memory",
                "64m",
                image,
                "python",
                "-c",
                "while True: pass",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "rm", "-f", container_name], capture_output=True, text=True, timeout=5)
        return passed("resource timeout", "Runaway Docker container was stopped after timeout with CPU/memory limits attached.")
    return failed("resource timeout", "Timeout test did not stop runaway process.")


def check_egress_allowlist(project_root: Path) -> dict[str, Any]:
    config_file = project_root / "config.example.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    policy = config.get("egress_policy", {})
    docker_status = check_docker_available()
    if policy.get("default") == "deny" and policy.get("allowed_domains") and docker_status["status"] == "passed":
        result = verify_egress_allowlist_gateway(project_root)
        if result["status"] == "passed":
            return passed("egress allowlist", "Docker egress gateway allows a controlled allowlisted test domain, blocks non-allowlisted domains, and prevents direct bypass.")
        return failed("egress allowlist", result["detail"])
    if policy.get("default") == "deny" and policy.get("allowed_domains"):
        return partial("egress allowlist", "Allowlist policy exists, but real network-level enforcement requires Docker/Cube/CubeEgress.")
    return failed("egress allowlist", "Allowlist policy is missing.")


def check_browser_sandbox(project_root: Path) -> dict[str, Any]:
    docker_status = check_docker_available()
    if docker_status["status"] != "passed":
        return blocked("browser sandbox", "Docker is required before browser sandbox can be verified.")
    result = verify_browser_sandbox(project_root)
    if result["status"] == "passed":
        return passed("browser sandbox", "Headless Chromium ran in a read-only Docker browser container, used the egress gateway, and failed direct bypass.")
    return failed("browser sandbox", result["detail"])


def check_credential_injection(project_root: Path) -> dict[str, Any]:
    docker_status = check_docker_available()
    if docker_status["status"] != "passed":
        return blocked("credential injection", "Docker is required before credential injection can be verified.")
    result = verify_credential_injection(project_root)
    if result["status"] == "passed":
        return passed("credential injection", "Task container used a short-lived credential handle through a broker without receiving plaintext secret.")
    return failed("credential injection", result["detail"])


def check_e2b_like_adapter(project_root: Path) -> dict[str, Any]:
    docker_status = check_docker_available()
    if docker_status["status"] != "passed":
        return blocked("E2B-like adapter", "Docker is required before the E2B-like adapter can be verified.")
    result = verify_e2b_like_adapter(project_root, SandboxService(project_root))
    if result["status"] == "passed":
        return passed("E2B-like adapter", "Docker-backed create/run/query/destroy sandbox-session workflow is available.")
    return failed("E2B-like adapter", result["detail"])


def check_hanhe_role_scenario(project_root: Path) -> dict[str, Any]:
    result = verify_hanhe_role_scenario_e2e(SandboxService(project_root))
    if result["status"] == "passed":
        return passed("Hanhe role scenario E2E", "Sales/supply-chain over-stock scenario runs end to end with Docker runtime and platform-chain evidence.")
    return failed("Hanhe role scenario E2E", result["detail"])


def check_hanhe_finance_scenario(project_root: Path) -> dict[str, Any]:
    result = verify_hanhe_finance_invoice_e2e(SandboxService(project_root))
    if result["status"] == "passed":
        return passed("Hanhe finance invoice E2E", "Finance invoice matching scenario runs end to end with Docker runtime, mock ERP data, permissions, cost, and audit evidence.")
    return failed("Hanhe finance invoice E2E", result["detail"])


def check_hanhe_purchase_scenario(project_root: Path) -> dict[str, Any]:
    result = verify_hanhe_purchase_plan_e2e(SandboxService(project_root))
    if result["status"] == "passed":
        return passed("Hanhe purchase plan E2E", "Purchase planning scenario runs end to end with Docker runtime, mock ERP data, permissions, cost, and audit evidence.")
    return failed("Hanhe purchase plan E2E", result["detail"])


def check_cube_ready() -> dict[str, Any]:
    toolbox = Path("/usr/local/services/cubetoolbox")
    btf_ready = Path("/sys/kernel/btf/vmlinux").exists()
    kvm_ready = Path("/dev/kvm").exists()
    service_names = [
        "cube-sandbox-cube-api.service",
        "cube-sandbox-webui.service",
        "cube-sandbox-cubelet.service",
        "cube-sandbox-cubemaster.service",
        "cube-sandbox-network-agent.service",
        "cube-sandbox-compute.target",
    ]
    services = {name: systemd_is_active(name) for name in service_names}
    api_ready = http_probe("http://127.0.0.1:3000")
    webui_ready = http_probe("http://127.0.0.1:12088")

    if kvm_ready and btf_ready and all(services.values()) and api_ready and webui_ready:
        return passed("Cube Sandbox", "Cube Sandbox control plane and compute services are active, KVM/BTF are available, and local API/WebUI respond.")

    if toolbox.exists():
        inactive = [name for name, ok in services.items() if not ok]
        blockers = []
        if not btf_ready:
            blockers.append("current kernel lacks /sys/kernel/btf/vmlinux, so Cube network-agent cannot load eBPF CO-RE programs")
        if inactive:
            blockers.append(f"inactive services: {', '.join(inactive)}")
        if not api_ready:
            blockers.append("Cube API on 127.0.0.1:3000 is not responding")
        if not webui_ready:
            blockers.append("Cube WebUI on 127.0.0.1:12088 is not responding")
        return future("Cube Sandbox", "Future stronger-isolation runtime option. Cube is partially installed, but not required for current Docker-based delivery: " + "; ".join(blockers))

    if kvm_ready:
        return future("Cube Sandbox", "Future stronger-isolation runtime option. KVM device exists on this Linux server, but Cube Sandbox is not connected for current delivery.")
    return future("Cube Sandbox", "Future stronger-isolation runtime option. Cube Sandbox needs Linux/KVM or suitable server environment; KVM is not available here.")


def docker_image(project_root: Path) -> str:
    config_file = project_root / "config.example.json"
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        config = {}
    return str(config.get("runtime", {}).get("docker_image", "python:3.12-slim"))


def systemd_is_active(name: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    try:
        proc = subprocess.run(["systemctl", "is-active", "--quiet", name], capture_output=True, text=True, timeout=3)
    except Exception:
        return False
    return proc.returncode == 0


def http_probe(url: str) -> bool:
    try:
        proc = subprocess.run(["curl", "-sS", "-I", "--max-time", "2", url], capture_output=True, text=True, timeout=4)
    except Exception:
        return False
    return proc.returncode == 0 and proc.stdout.startswith("HTTP/")


def passed(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "passed", "detail": detail}


def partial(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "partial", "detail": detail}


def failed(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "failed", "detail": detail}


def blocked(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "blocked", "detail": detail}


def future(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "future", "detail": detail}
