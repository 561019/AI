import requests

from helpers import (
    E2E_TENANT_ID,
    layer_dispatch,
    permission_url,
)
from l1_support import prepare_identity, prepare_identity_runtime_contract, unique


def test_l2_layer_permission_allow_calls_registered_identity_service():
    account_id, position_id = unique("e2e-account"), unique("e2e-position")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=True)

    response = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["actor_id"] == account_id
    assert body["permission_decision_id"].startswith("decision_")

    audit = requests.get(
        f"{permission_url()}/api/permission/audits",
        params={"trace_id": body["trace_id"]},
        timeout=2,
    )
    assert audit.status_code == 200
    row = audit.json()["audits"][0]
    assert row["result"] == "allow"
    assert row["transfer_id"] == body["transfer_id"]
    assert row["responsible_actor_id"] == account_id
    assert row["original_caller_service_id"] == "e2e_business_engine"


def test_l2_layer_permission_deny_does_not_execute_target_service():
    account_id, position_id = unique("e2e-deny-account"), unique("e2e-deny-position")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=False)

    response = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
    )
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["status"] == "deny"
    assert body["permission_decision_id"].startswith("decision_")
    assert body["error"]["code"] == "ACTION_NOT_GRANTED"


def test_l2_layer_rejects_replayed_transfer_before_second_execution():
    account_id, position_id = unique("e2e-replay-account"), unique("e2e-replay-position")
    prepare_identity(account_id, position_id)
    prepare_identity_runtime_contract(position_id, grant=True)
    transfer_id = unique("transfer-replay")
    first = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
        transfer_id=transfer_id,
    )
    assert first.status_code == 200, first.text
    second = layer_dispatch(
        account_id=account_id,
        action="identity.context.read_self",
        resource_type="identity_context",
        resource_id=account_id,
        transfer_id=transfer_id,
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "TRANSFER_REPLAY"
