import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import requests

from helpers import base_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("timeout", "per-test timeout, compatible with pytest-timeout")
    parser.addini("timeout_method", "timeout method, compatible with pytest-timeout")


@pytest.fixture(scope="session")
def stack() -> None:
    _prepare_e2e_data_dir()

    if os.environ.get("E2E_STACK_MODE") == "local":
        yield from _local_gateway_stack()
        return

    if os.environ.get("E2E_STACK_MODE") == "external":
        _wait_for_compose_health()
        yield
        return

    compose = _compose_command(required=False)
    compose_file = _compose_file()
    if compose and compose_file:
        command = [*compose, "-f", str(compose_file)]
        try:
                _run([*command, "up", "-d", "--build"])
        except subprocess.CalledProcessError:
            if os.environ.get("E2E_STACK_MODE") == "docker":
                raise
        else:
            try:
                _wait_for_compose_health()
                yield
            finally:
                _run([*command, "down", "-v"], check=False)
            return

    yield from _local_gateway_stack()


@pytest.fixture(autouse=True)
def reset_state(stack: None) -> None:
    reset_command = os.environ.get("E2E_RESET_COMMAND")
    reset_url = os.environ.get("E2E_RESET_URL")

    if reset_command:
        _run(reset_command, shell=True)
    elif reset_url:
        response = requests.post(reset_url, timeout=5)
        response.raise_for_status()


def _compose_command(*, required: bool = True) -> list[str] | None:
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    if not required:
        return None
    pytest.fail("docker compose is required for e2e tests")


def _local_gateway_stack() -> None:
    env = {
        **os.environ,
        "CASDOOR_MOCK_OIDC": os.environ.get("CASDOOR_MOCK_OIDC", "1"),
        "AUDIT_DB_PATH": str(_audit_db_path()),
        "CREDENTIALS_ENCRYPTION_KEY": os.environ.get(
            "CREDENTIALS_ENCRYPTION_KEY", "12345678901234567890123456789012"
        ),
    }
    process = subprocess.Popen(
        ["go", "run", "./cmd/gateway"],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_health()
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _compose_file() -> Path | None:
    configured = os.environ.get("E2E_COMPOSE_FILE")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path

    for name in COMPOSE_FILES:
        path = PROJECT_ROOT / name
        if path.exists():
            return path
    return None


def _prepare_e2e_data_dir() -> None:
    data_dir = PROJECT_ROOT / ".e2e-data"
    data_dir.mkdir(exist_ok=True)
    # Note: we intentionally do NOT delete the audit database file here.
    # The gateway creates it via EnsureSchema on startup. If the gateway is
    # already running (e.g. `scripts/up.sh` started it before pytest), deleting
    # the file would leave a stale SQLite connection pointing at nothing, and
    # the gateway would not recreate the file until it restarts. Tests use
    # max(id) for delta checks, so pre-existing rows do not cause failures.


def _audit_db_path() -> Path:
    return PROJECT_ROOT / ".e2e-data" / "audit.db"


def _wait_for_health() -> None:
    deadline = time.monotonic() + float(os.environ.get("E2E_STACK_TIMEOUT", "25"))
    health_url = f"{base_url()}/health"
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            response = requests.get(health_url, timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.5)

    detail = f": {last_error}" if last_error else ""
    pytest.fail(f"stack did not become healthy at {health_url}{detail}")


def _wait_for_compose_health() -> None:
    endpoints = (
        f"{base_url()}/health",
        os.environ.get("PERMISSION_GATEWAY_BASE_URL", "http://127.0.0.1:8001").rstrip("/") + "/health",
        os.environ.get("L1_LAYER_INTERFACE_BASE_URL", "http://127.0.0.1:8002").rstrip("/") + "/health",
    )
    deadline = time.monotonic() + float(os.environ.get("E2E_STACK_TIMEOUT", "45"))
    pending = set(endpoints)
    last_errors: dict[str, str] = {}
    while pending and time.monotonic() < deadline:
        for endpoint in tuple(pending):
            try:
                response = requests.get(endpoint, timeout=2)
                if response.status_code == 200:
                    pending.remove(endpoint)
                else:
                    last_errors[endpoint] = f"HTTP {response.status_code}"
            except requests.RequestException as error:
                last_errors[endpoint] = str(error)
        if pending:
            time.sleep(0.5)
    if pending:
        detail = "; ".join(f"{endpoint}: {last_errors.get(endpoint, 'not ready')}" for endpoint in pending)
        pytest.fail(f"compose stack did not become healthy: {detail}")


def _run(
    command: list[str] | str,
    *,
    check: bool = True,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=check,
        shell=shell,
        text=True,
        capture_output=True,
    )
