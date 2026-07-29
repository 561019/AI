"""岗位标准和转授由权限控制面管理，运行期仅经 L1 通道。"""

from helpers import get, layer_dispatch, permission_command, post
from l1_support import prepare_identity, prepare_probe_contract, unique


def _dispatch(account_id: str, resource_id: str):
    return layer_dispatch(
        account_id=account_id, action="fetch", resource_type="data", resource_id=resource_id,
        target_service_id="test.permission_probe.v1", command="permission.probe.execute",
    )


def test_position_standard_and_delegation_use_permission_control_plane():
    analyst, reviewer = unique("ppm-analyst"), unique("ppm-reviewer")
    analyst_position, reviewer_position = unique("ppm-analyst-pos"), unique("ppm-reviewer-pos")
    resource_id = unique("ppm-data")
    prepare_identity(analyst, analyst_position)
    prepare_identity(reviewer, reviewer_position)
    prepare_probe_contract(analyst_position, action="fetch", resource_type="data", resource_id=resource_id)
    prepare_probe_contract(reviewer_position, action="fetch", resource_type="data", resource_id=resource_id, grant=False)

    allowed = _dispatch(analyst, resource_id)
    assert allowed.status_code == 200, allowed.text
    denied = _dispatch(reviewer, resource_id)
    assert denied.status_code == 403

    delegation = permission_command("create_delegation", {
        "from_person_id": analyst, "to_person_id": reviewer, "resource_type": "data",
        "resource_id": resource_id, "action": "fetch", "basis": "temporary review",
    })
    assert delegation.status_code == 201, delegation.text
    assert _dispatch(reviewer, resource_id).status_code == 200

    for path in ("/api/position-standard-resources", "/api/delegations"):
        retired = get(path)
        assert retired.status_code == 410
        assert retired.json()["error"] == "permission_capability_moved"
