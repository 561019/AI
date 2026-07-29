"""Cross-module E2E coverage for identity facts and permission control facts.

These scenarios intentionally never call the retired gateway permission APIs.
The test probe is a registered L1 target; it only runs after the L1 interface
obtains an allow decision from the permission gateway.
"""

import time

import requests

from helpers import E2E_TENANT_ID, auth_headers, layer_dispatch, permission_command, post
from l1_support import prepare_identity, prepare_probe_contract, unique


def _dispatch(
    account_id: str,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    data_label: str = "normal",
    data_state: str = "active",
    tenant_id: str = E2E_TENANT_ID,
) -> requests.Response:
    return layer_dispatch(
        account_id=account_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        data_label=data_label,
        data_state=data_state,
        tenant_id=tenant_id,
        target_service_id="test.permission_probe.v1",
        command="permission.probe.execute",
    )


def _create_domain(domain_id: str, tenant_id: str = E2E_TENANT_ID) -> None:
    response = post(
        "/api/domains",
        headers=auth_headers({"user_id": "e2e-domain-admin", "org_id": tenant_id, "role_list": ["hanhe_admin"]}),
        json={"id": domain_id, "name": domain_id, "dsm_user_id": "e2e-domain-admin"},
    )
    assert response.status_code == 201, response.text


def _set_manager(person_id: str, manager_id: str, domain_id: str, tenant_id: str = E2E_TENANT_ID) -> None:
    response = post(
        "/api/person-manager-edges",
        headers=auth_headers({"user_id": "e2e-dsm", "org_id": tenant_id, "role_list": ["hanhe_dsm"]}),
        json={"person_id": person_id, "manager_person_id": manager_id, "domain_id": domain_id},
    )
    assert response.status_code == 201, response.text


def test_resource_publication_grants_registered_position_via_l1_channel():
    owner, reader = unique("resource-owner"), unique("resource-reader")
    owner_position, reader_position = unique("resource-owner-pos"), unique("resource-reader-pos")
    resource_id = unique("published-skill")
    prepare_identity(owner, owner_position)
    prepare_identity(reader, reader_position)
    prepare_probe_contract(reader_position, action="use", resource_type="skill", resource_id=resource_id, grant=False)

    created = permission_command("create_resource", {
        "id": resource_id, "name": resource_id, "resource_type": "skill",
        "owner_actor_id": owner, "owner_person_id": owner,
        "owner_position_id": owner_position, "department_id": "e2e",
    })
    assert created.status_code == 201, created.text
    denied = _dispatch(reader, action="use", resource_type="skill", resource_id=resource_id)
    assert denied.status_code == 403

    publication = permission_command("request_resource_publication", {
        "resource_id": resource_id, "target_level": "department_public", "reason": "E2E publication",
    })
    assert publication.status_code == 201, publication.text
    publication_id = publication.json()["resource_publication"]["id"]
    approved = permission_command("approve_resource_publication", {
        "id": publication_id, "position_ids": [reader_position], "actions": ["use"],
        "source_service": "l1_internal_channel", "target_service": "test.permission_probe.v1",
    })
    assert approved.status_code == 200, approved.text
    allowed = _dispatch(reader, action="use", resource_type="skill", resource_id=resource_id)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["result"]["actor_id"] == reader


def test_one_real_account_can_hold_multiple_positions_with_union_permissions():
    account_id = unique("multi-account")
    primary, secondary = unique("multi-primary"), unique("multi-secondary")
    resource_id = unique("multi-data")
    prepare_identity(account_id, primary)
    prepare_identity(account_id, secondary)
    prepare_probe_contract(secondary, action="fetch", resource_type="data", resource_id=resource_id)

    response = _dispatch(account_id, action="fetch", resource_type="data", resource_id=resource_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"


def test_tenant_scoped_identity_and_permission_grants_cannot_cross():
    tenant_a, tenant_b = E2E_TENANT_ID, f"{E2E_TENANT_ID}-other"
    account_a, account_b = unique("tenant-a-account"), unique("tenant-b-account")
    position_a, position_b = unique("tenant-a-pos"), unique("tenant-b-pos")
    resource_a, resource_b = unique("tenant-a-resource"), unique("tenant-b-resource")
    prepare_identity(account_a, position_a, tenant_id=tenant_a)
    prepare_identity(account_b, position_b, tenant_id=tenant_b)
    prepare_probe_contract(position_a, action="tenant.read", resource_type="data", resource_id=resource_a, tenant_id=tenant_a)
    prepare_probe_contract(position_b, action="tenant.read", resource_type="data", resource_id=resource_b, tenant_id=tenant_b)

    assert _dispatch(account_a, action="tenant.read", resource_type="data", resource_id=resource_a, tenant_id=tenant_a).status_code == 200
    assert _dispatch(account_b, action="tenant.read", resource_type="data", resource_id=resource_b, tenant_id=tenant_b).status_code == 200
    cross = _dispatch(account_a, action="tenant.read", resource_type="data", resource_id=resource_b, tenant_id=tenant_a)
    assert cross.status_code == 403
    assert cross.json()["error"]["code"] == "ACTION_NOT_GRANTED"


def test_manager_scope_uses_current_gateway_reporting_tree():
    manager, owner = unique("manager-account"), unique("owner-account")
    manager_position, owner_position = unique("manager-pos"), unique("owner-pos")
    domain_id, resource_id = unique("manager-domain"), unique("manager-data")
    prepare_identity(manager, manager_position)
    prepare_identity(owner, owner_position)
    _create_domain(domain_id)
    _set_manager(owner, manager, domain_id)
    prepare_probe_contract(manager_position, action="fetch", resource_type="data", resource_id=resource_id, grant=False)
    registered = permission_command("register_data", {
        "id": resource_id, "title": resource_id, "source_type": "report",
        "owner_actor_id": owner, "owner_person_id": owner, "allowed_actions": ["fetch"], "basis": "manager scope",
    })
    assert registered.status_code == 201, registered.text

    response = _dispatch(manager, action="fetch", resource_type="data", resource_id=resource_id)
    assert response.status_code == 200, response.text


def test_data_delegation_is_a_permission_control_fact_not_gateway_policy():
    owner, recipient = unique("delegator"), unique("delegatee")
    owner_position, recipient_position = unique("delegator-pos"), unique("delegatee-pos")
    resource_id = unique("delegated-data")
    prepare_identity(owner, owner_position)
    prepare_identity(recipient, recipient_position)
    prepare_probe_contract(recipient_position, action="fetch", resource_type="data", resource_id=resource_id, grant=False)
    delegation = permission_command("create_delegation", {
        "from_person_id": owner, "to_person_id": recipient, "resource_id": resource_id,
        "resource_type": "data", "action": "fetch", "basis": "E2E delegation",
    })
    assert delegation.status_code == 201, delegation.text
    assert _dispatch(recipient, action="fetch", resource_type="data", resource_id=resource_id).status_code == 200


def test_data_label_state_and_action_constraints_precede_grants():
    account_id, position_id, resource_id = unique("data-account"), unique("data-pos"), unique("registered-data")
    prepare_identity(account_id, position_id)
    prepare_probe_contract(position_id, action="fetch", resource_type="data", resource_id=resource_id)
    record = permission_command("register_data", {
        "id": resource_id, "title": resource_id, "source_type": "report",
        "owner_actor_id": account_id, "owner_person_id": account_id,
        "allowed_actions": ["fetch"], "data_label": "normal", "state": "active", "basis": "E2E data constraints",
    })
    assert record.status_code == 201, record.text
    assert _dispatch(account_id, action="fetch", resource_type="data", resource_id=resource_id).status_code == 200
    frozen = permission_command("set_data_status", {"id": resource_id, "state": "frozen"})
    assert frozen.status_code == 200, frozen.text
    denied = _dispatch(account_id, action="fetch", resource_type="data", resource_id=resource_id)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "DATA_STATE_DENIED"


def test_custom_data_action_requires_catalog_registration():
    account_id, position_id, resource_id = unique("action-account"), unique("action-pos"), unique("action-data")
    allowed_action, unknown_action = unique("archive-review"), unique("not-registered")
    prepare_identity(account_id, position_id)
    prepare_probe_contract(position_id, action=allowed_action, resource_type="data", resource_id=resource_id)
    assert _dispatch(account_id, action=allowed_action, resource_type="data", resource_id=resource_id).status_code == 200
    relation = permission_command("create_service_call_rule", {
        "source_service": "l1_internal_channel", "target_service": "test.permission_probe.v1", "action": unknown_action,
    })
    assert relation.status_code == 201, relation.text
    denied = _dispatch(account_id, action=unknown_action, resource_type="data", resource_id=resource_id)
    assert denied.status_code == 400
    assert denied.json()["status"] == "error"
    assert denied.json()["error"]["code"] == "INVALID_REQUEST"


def test_data_owner_participant_manager_and_peer_are_calculated_at_runtime():
    owner, participant, manager, peer = (unique("initial-owner"), unique("initial-participant"), unique("initial-manager"), unique("initial-peer"))
    owner_position, participant_position, manager_position, peer_position = (unique("initial-owner-pos"), unique("initial-participant-pos"), unique("initial-manager-pos"), unique("initial-peer-pos"))
    domain_id, resource_id = unique("initial-domain"), unique("initial-data")
    for account_id, position_id in ((owner, owner_position), (participant, participant_position), (manager, manager_position), (peer, peer_position)):
        prepare_identity(account_id, position_id)
    _create_domain(domain_id)
    _set_manager(owner, manager, domain_id)
    for position_id in (owner_position, participant_position, manager_position, peer_position):
        prepare_probe_contract(position_id, action="fetch", resource_type="data", resource_id=resource_id, grant=False)
        prepare_probe_contract(position_id, action="update", resource_type="data", resource_id=resource_id, grant=False)
    record = permission_command("register_data", {
        "id": resource_id, "title": resource_id, "source_type": "conversation",
        "owner_actor_id": owner, "owner_person_id": owner, "allowed_actions": ["fetch", "update"],
        "initial_person_ids": [participant], "basis": "initial participants",
    })
    assert record.status_code == 201, record.text
    assert _dispatch(owner, action="update", resource_type="data", resource_id=resource_id).status_code == 200
    assert _dispatch(participant, action="fetch", resource_type="data", resource_id=resource_id).status_code == 200
    assert _dispatch(manager, action="fetch", resource_type="data", resource_id=resource_id).status_code == 200
    assert _dispatch(participant, action="update", resource_type="data", resource_id=resource_id).status_code == 403
    assert _dispatch(peer, action="fetch", resource_type="data", resource_id=resource_id).status_code == 403
