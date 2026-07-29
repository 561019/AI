"""资源发布的授权事实必须由权限模块控制面生成和撤销。"""

from helpers import get, layer_dispatch, permission_command
from l1_support import prepare_identity, prepare_probe_contract, unique


def _use(account_id: str, resource_id: str):
    return layer_dispatch(
        account_id=account_id, action="use", resource_type="skill", resource_id=resource_id,
        target_service_id="test.permission_probe.v1", command="permission.probe.execute",
    )


def test_resource_publication_and_revocation_change_runtime_l1_decision():
    owner, consumer = unique("resource-owner"), unique("resource-consumer")
    owner_position, consumer_position = unique("resource-owner-pos"), unique("resource-consumer-pos")
    resource_id = unique("resource-skill")
    prepare_identity(owner, owner_position)
    prepare_identity(consumer, consumer_position)
    prepare_probe_contract(consumer_position, action="use", resource_type="skill", resource_id=resource_id, grant=False)
    assert permission_command("create_resource", {
        "id": resource_id, "name": resource_id, "resource_type": "skill",
        "owner_actor_id": owner, "owner_person_id": owner, "owner_position_id": owner_position,
    }).status_code == 201
    assert _use(consumer, resource_id).status_code == 403

    requested = permission_command("request_resource_publication", {
        "resource_id": resource_id, "target_level": "department_public", "reason": "share skill",
    })
    assert requested.status_code == 201
    publication_id = requested.json()["resource_publication"]["id"]
    assert permission_command("approve_resource_publication", {
        "id": publication_id, "position_ids": [consumer_position], "actions": ["use"],
        "source_service": "l1_internal_channel", "target_service": "test.permission_probe.v1",
    }).status_code == 200
    assert _use(consumer, resource_id).status_code == 200
    assert permission_command("revoke_resource_publication", {"id": publication_id}).status_code == 200
    assert _use(consumer, resource_id).status_code == 403

    for path in ("/api/resources", "/api/resource-publications"):
        retired = get(path)
        assert retired.status_code == 410
        assert retired.json()["error"] == "permission_capability_moved"
