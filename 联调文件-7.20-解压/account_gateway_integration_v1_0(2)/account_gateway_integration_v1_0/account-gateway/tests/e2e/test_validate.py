from helpers import E2E_TENANT_ID, auth_headers, layer_dispatch, post
from l1_support import prepare_identity, prepare_identity_runtime_contract, unique


def test_registered_l2_with_current_position_is_allowed():
    account_id, position_id = unique("validate-allow-account"), unique("validate-allow-position")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=True)

    response = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"


def test_registered_l2_without_position_standard_is_denied():
    account_id, position_id = unique("validate-deny-account"), unique("validate-deny-position")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=False)

    response = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "ACTION_NOT_GRANTED"


def test_legacy_validate_never_falls_back_to_local_allow():
    account_id = unique("legacy-validate-account")
    response = post(
        "/auth/validate",
        headers={
            **auth_headers(
                {"user_id": account_id, "org_id": E2E_TENANT_ID, "role_list": ["hanhe_admin"]}
            ),
            "X-User-ID": account_id,
            "X-Resource-Type": "tool",
            "X-Resource-Owner-ID": account_id,
            "X-Action": "create",
        },
    )

    assert response.status_code in (403, 503)
    assert response.json()["allow"] is False


def test_legacy_validate_still_rejects_malformed_request_before_any_allow():
    account_id = unique("legacy-malformed-account")
    response = post(
        "/auth/validate",
        headers=auth_headers(
            {"user_id": account_id, "org_id": E2E_TENANT_ID, "role_list": ["hanhe_admin"]}
        ),
    )

    assert response.status_code == 400
    assert response.json() == {"allow": False, "reason": "missing_header"}
