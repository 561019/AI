"""The gateway must not provide a UI permission decision surface."""

import pytest

from helpers import get, sign_jwt


JWT_SECRET = "change-me"
ORG_ID = "casdoor-e2e-org"


def _token(roles: list[str]) -> str:
    return sign_jwt({"user_id": "ui-test-user", "org_id": ORG_ID, "role_list": roles}, secret=JWT_SECRET)


@pytest.mark.parametrize("authorization", [
    f"Bearer {_token(['staff'])}",
    f"Bearer {_token(['data_owner'])}",
    f"Bearer {_token(['hanhe_im', 'hanhe_dsm', 'hanhe_admin'])}",
    "Bearer invalid-token",
    "",
])
def test_ui_permission_endpoint_is_retired_for_every_caller(authorization: str):
    headers = {"Authorization": authorization} if authorization else {}
    response = get("/api/ui-permissions", headers=headers)
    assert response.status_code == 410
    assert response.json()["error"] == "permission_capability_moved"
