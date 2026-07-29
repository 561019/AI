import os
import shutil
import subprocess
from pathlib import Path

import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
SERVICES = ("ownership-mock", "casdoor", "account-gateway")


@pytest.fixture(autouse=True)
def reset_state() -> None:
    return None


def test_one_command_up_and_down() -> None:
    up_script = PROJECT_ROOT / "scripts" / "up.sh"
    down_script = PROJECT_ROOT / "scripts" / "down.sh"
    command = [*_compose_command(), "-f", str(COMPOSE_FILE)]

    try:
        up = _run(["sh", str(up_script)], timeout=_stack_timeout() + 60)
        assert "READY" in up.stdout

        states = {service: _service_health(command, service) for service in SERVICES}
        assert states == {service: "healthy" for service in SERVICES}

        gateway_response = requests.get(_gateway_url("/health"), timeout=3)
        casdoor_response = requests.get(_casdoor_url("/api/health"), timeout=3)

        assert gateway_response.status_code == 200
        assert casdoor_response.status_code < 500
    finally:
        down = _run(["sh", str(down_script)], check=False, timeout=60)

    assert down.returncode == 0, down.stderr
    assert _compose_container_ids(command) == []

    # Bring the session stack back up so subsequent tests can use it.
    _run(["sh", str(up_script)], check=False, timeout=_stack_timeout() + 60)

    # Bring the session stack back up so subsequent tests can use it.
    _run(["sh", str(up_script)], check=False, timeout=_stack_timeout() + 60)


def _compose_command() -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    pytest.fail("docker-compose or docker compose is required")


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


def _compose_container_ids(command: list[str]) -> list[str]:
    output = _run([*command, "ps", "-q", "-a"], check=False).stdout.strip()
    return [line for line in output.splitlines() if line.strip()]


def _gateway_url(path: str) -> str:
    port = os.environ.get("GATEWAY_PORT", "8080")
    return f"http://127.0.0.1:{port}{path}"


def _casdoor_url(path: str) -> str:
    return f"http://127.0.0.1:8000{path}"


def _stack_timeout() -> int:
    return int(float(os.environ.get("E2E_STACK_TIMEOUT", "180")))


def _run(
    command: list[str],
    *,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=check,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
