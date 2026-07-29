import sys
import time
from pathlib import Path

import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOCKS_DIR = PROJECT_ROOT / "tests" / "mocks"
sys.path.insert(0, str(MOCKS_DIR))

from mock_server import DEFAULT_PORTS, serve_ports  # noqa: E402


MAX_RESPONSE_SECONDS = 0.050


@pytest.fixture(autouse=True)
def reset_state():
    return None


@pytest.fixture(scope="module")
def mock_servers():
    servers = serve_ports(DEFAULT_PORTS)
    sessions = {port: requests.Session() for port in DEFAULT_PORTS}
    for port, session in sessions.items():
        session.get(f"http://127.0.0.1:{port}/ownership/dataset_001", timeout=2)
    try:
        yield sessions
    finally:
        for session in sessions.values():
            session.close()
        for server in servers:
            server.shutdown()
            server.server_close()


@pytest.mark.parametrize(
    ("resource_id", "owner_id"),
    [
        ("dataset_001", "user_li"),
        ("dataset_002", "user_fu"),
        ("dataset_003", "user_huang"),
    ],
)
def test_ownership_fixture_responses_are_fast(mock_servers, resource_id, owner_id):
    for port, session in mock_servers.items():
        response, elapsed = get_with_elapsed(session, f"http://127.0.0.1:{port}/ownership/{resource_id}")

        assert response.status_code == 200
        assert response.json() == {"resource_id": resource_id, "owner_id": owner_id}
        assert elapsed < MAX_RESPONSE_SECONDS


def test_unknown_ownership_returns_404_fast(mock_servers):
    for port, session in mock_servers.items():
        response, elapsed = get_with_elapsed(session, f"http://127.0.0.1:{port}/ownership/missing_dataset")

        assert response.status_code == 404
        assert response.json() == {"error": "resource_not_found", "resource_id": "missing_dataset"}
        assert elapsed < MAX_RESPONSE_SECONDS


def test_mock_only_allows_get(mock_servers):
    port, session = next(iter(mock_servers.items()))
    response, elapsed = post_with_elapsed(session, f"http://127.0.0.1:{port}/ownership/dataset_001")

    assert response.status_code == 405
    assert response.json() == {"error": "method_not_allowed"}
    assert elapsed < MAX_RESPONSE_SECONDS


def get_with_elapsed(session, url):
    start = time.perf_counter()
    response = session.get(url, timeout=2)
    return response, time.perf_counter() - start


def post_with_elapsed(session, url):
    start = time.perf_counter()
    response = session.post(url, timeout=2)
    return response, time.perf_counter() - start
