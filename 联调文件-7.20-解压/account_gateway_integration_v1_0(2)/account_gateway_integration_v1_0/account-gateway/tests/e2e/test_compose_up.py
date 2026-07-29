import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
SERVICES = ("casdoor", "account-gateway")


def test_compose_up_exposes_healthy_services(stack):
    command = [*_compose_command(), "-f", str(COMPOSE_FILE)]
    _wait_for_services_healthy(command)

    gateway_response = requests.get(_gateway_url("/health"), timeout=3)
    casdoor_response = requests.get(_casdoor_url("/api/health"), timeout=3)

    assert gateway_response.status_code == 200
    # Casdoor may return 403/404 for anonymous /api/health; any HTTP response means the server is up.
    assert casdoor_response.status_code < 500


def _compose_command() -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    pytest.fail("docker-compose or docker compose is required")


def _wait_for_services_healthy(command: list[str]) -> None:
    deadline = time.monotonic() + float(os.environ.get("E2E_STACK_TIMEOUT", "120"))
    last_status = ""

    while time.monotonic() < deadline:
        states = {service: _service_health(command, service) for service in SERVICES}
        if all(state == "healthy" for state in states.values()):
            return
        last_status = ", ".join(f"{service}={state}" for service, state in states.items())
        time.sleep(2)

    logs = _run([*command, "logs", "--no-color", *SERVICES], check=False).stdout
    pytest.fail(f"compose services did not become healthy: {last_status}\n{logs}")


def _service_health(command: list[str], service: str) -> str:
    container_id = _run([*command, "ps", "-q", service]).stdout.strip()
    if not container_id:
        return "missing"

    inspect = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            container_id,
        ],
        check=False,
    )
    return inspect.stdout.strip() or "unknown"


def _gateway_url(path: str) -> str:
    port = os.environ.get("GATEWAY_PORT", "8080")
    return f"http://127.0.0.1:{port}{path}"


def _casdoor_url(path: str) -> str:
    return f"http://127.0.0.1:8000{path}"


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=check,
        text=True,
        capture_output=True,
    )
