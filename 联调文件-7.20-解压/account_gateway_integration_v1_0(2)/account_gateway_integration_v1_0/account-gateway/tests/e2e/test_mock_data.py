import json
import sys
from pathlib import Path

import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOCKS_DIR = PROJECT_ROOT / "tests" / "mocks"
FIXTURES_DIR = MOCKS_DIR / "fixtures"
sys.path.insert(0, str(MOCKS_DIR))

from mock_server import DEFAULT_PORTS, serve_ports  # noqa: E402


FIXTURE_ROUTES = {
    "org_structure.json": "/org/structure",
    "policy_seed.json": "/policy/seed",
    "hr_source.json": "/hr/source",
}


@pytest.fixture(autouse=True)
def reset_state():
    return None


@pytest.fixture(scope="module")
def mock_servers():
    servers = serve_ports(DEFAULT_PORTS)
    sessions = {port: requests.Session() for port in DEFAULT_PORTS}
    for port, session in sessions.items():
        session.get(f"http://127.0.0.1:{port}/org/structure", timeout=2)
    try:
        yield sessions
    finally:
        for session in sessions.values():
            session.close()
        for server in servers:
            server.shutdown()
            server.server_close()


@pytest.fixture(scope="module")
def fixtures():
    return {name: load_json(name) for name in FIXTURE_ROUTES}


def test_org_structure_fixture_is_complete(fixtures):
    org = fixtures["org_structure.json"]["organization"]

    assert org["id"] == "hanhe"
    assert {department["id"] for department in org["departments"]} >= {
        "dept_platform",
        "dept_sales_huazhong",
        "dept_hr",
    }
    assert {position["label"] for position in org["positions"]} >= {"admin", "manager", "staff"}
    assert {position["id"] for position in org["positions"]} >= {
        "hanhe_admin",
        "huazhong_region_manager",
        "huazhong_sales",
    }
    assert {
        (line["position_id"], line["reports_to"])
        for line in org["reporting_lines"]
    } >= {
        ("huazhong_region_manager", "hanhe_admin"),
        ("huazhong_sales", "huazhong_region_manager"),
    }


def test_policy_seed_fixture_is_complete(fixtures):
    policies = fixtures["policy_seed.json"]["policies"]
    by_position = {policy["position_id"]: policy for policy in policies}

    assert set(by_position) >= {
        "hanhe_admin",
        "huazhong_region_manager",
        "huazhong_sales",
        "hr_source",
        "data_owner",
        "asset_pool",
    }
    assert any(
        permission["resource"] == "/admin/:resource" and permission["effect"] == "allow"
        for permission in by_position["hanhe_admin"]["standing_permissions"]
    )
    assert any(
        permission["resource"] == "/sales/huazhong/opportunities"
        and {"read", "write"} <= set(permission["actions"])
        for permission in by_position["huazhong_sales"]["standing_permissions"]
    )


def test_hr_source_fixture_is_complete(fixtures):
    users = fixtures["hr_source.json"]["users"]
    by_user = {user["user_id"]: user for user in users}

    assert set(by_user) >= {"user_li", "user_fu", "user_huang"}
    assert all(by_user[user_id]["employment_status"] == "active" for user_id in by_user)
    assert by_user["user_li"]["position_id"] == "huazhong_region_manager"
    assert by_user["user_fu"]["position_id"] == "huazhong_sales"
    assert by_user["user_huang"]["position_id"] == "hr_source"


@pytest.mark.parametrize(("fixture_name", "route"), FIXTURE_ROUTES.items())
def test_mock_ports_return_fixture_data(mock_servers, fixtures, fixture_name, route):
    for port, session in mock_servers.items():
        response = session.get(f"http://127.0.0.1:{port}{route}", timeout=2)

        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/json"
        assert response.json() == fixtures[fixture_name]


def load_json(name):
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as fixture_file:
        return json.load(fixture_file)
