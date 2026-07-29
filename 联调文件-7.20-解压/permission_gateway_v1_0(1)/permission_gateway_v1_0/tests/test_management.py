from __future__ import annotations


def test_delegation_does_not_require_permission_side_account_replica(
    client, admin_headers, command_fn
):
    response = command_fn(
        client,
        admin_headers,
        "/api/permissions/commands",
        "create_delegation",
        {
            "from_person_id": "account-owner",
            "to_person_id": "account-recipient",
            "resource_type": "data",
            "resource_id": "data-001",
            "action": "read",
            "basis": "账号网关已核验身份",
        },
    )
    assert response.status_code == 201
    assert response.json()["delegation"]["to_person_id"] == "account-recipient"


def test_approved_resource_publication_creates_effective_position_grant(
    client, admin_headers, command_fn
):
    assert command_fn(client, admin_headers, "/api/org/commands", "create_position", {"id": "published-position", "title": "使用岗位"}).status_code == 201
    assert command_fn(client, admin_headers, "/api/permissions/commands", "create_resource", {
        "id": "skill-001", "name": "文案技能", "resource_type": "skill",
        "owner_person_id": "owner", "owner_user_id": "owner", "owner_position_id": "published-position",
    }).status_code == 201
    request = command_fn(client, admin_headers, "/api/permissions/commands", "request_resource_publication", {
        "resource_id": "skill-001", "target_level": "department", "reason": "统一使用",
    })
    assert request.status_code == 201
    approval = command_fn(client, admin_headers, "/api/permissions/commands", "approve_resource_publication", {
        "id": request.json()["resource_publication"]["id"], "position_ids": ["published-position"], "actions": ["use"],
    })
    assert approval.status_code == 200
    assert len(approval.json()["position_permission_ids"]) == 1
    revoke = command_fn(client, admin_headers, "/api/permissions/commands", "revoke_resource_publication", {
        "id": request.json()["resource_publication"]["id"],
    })
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["resource_publication"]["status"] == "revoked"
    assert revoke.json()["revoked_position_permission_ids"] == approval.json()["position_permission_ids"]


def test_one_person_can_hold_multiple_positions_but_seat_is_unique(
    client, admin_headers, command_fn
):
    for index in (1, 2):
        assert command_fn(
            client,
            admin_headers,
            "/api/org/commands",
            "create_position",
            {"id": f"position-{index}", "title": f"岗位 {index}"},
        ).status_code == 201
        assert command_fn(
            client,
            admin_headers,
            "/api/org/commands",
            "assign_person_position",
            {
                "person_id": "u-1",
                "user_id": "u-1",
                "position_id": f"position-{index}",
            },
        ).status_code == 201
    conflict = command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "assign_person_position",
        {
            "person_id": "u-2",
            "user_id": "u-2",
            "position_id": "position-1",
        },
    )
    assert conflict.status_code == 409


def test_manager_relationship_rejects_cycles(client, admin_headers, command_fn):
    for index in (1, 2):
        command_fn(
            client,
            admin_headers,
            "/api/org/commands",
            "create_position",
            {"id": f"position-{index}", "title": f"岗位 {index}"},
        )
        command_fn(
            client,
            admin_headers,
            "/api/org/commands",
            "assign_person_position",
            {
                "person_id": f"u-{index}",
                "user_id": f"u-{index}",
                "position_id": f"position-{index}",
            },
        )
    first = command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "upsert_manager_edge",
        {
            "person_id": "u-2",
            "manager_person_id": "u-1",
            "domain_id": "domain-1",
        },
    )
    assert first.status_code == 201
    cycle = command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "upsert_manager_edge",
        {
            "person_id": "u-1",
            "manager_person_id": "u-2",
            "domain_id": "domain-1",
        },
    )
    assert cycle.status_code == 409
    assert cycle.json() == {"error": "manager_cycle"}


def test_snapshots_are_tenant_scoped(client, admin_headers, command_fn):
    command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "create_position",
        {"id": "position-1", "title": "岗位"},
    )
    snapshot = client.get("/api/org/snapshot", headers=admin_headers)
    assert snapshot.status_code == 200
    assert [item["id"] for item in snapshot.json()["positions"]] == ["position-1"]
    forbidden = client.get(
        "/api/org/snapshot?tenant_id=tenant-b", headers=admin_headers
    )
    assert forbidden.status_code == 403


def test_assignment_rejects_distinct_person_and_account_ids(
    client, admin_headers, command_fn
):
    command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "create_position",
        {"id": "position-identity", "title": "实名岗位"},
    )
    response = command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "assign_person_position",
        {
            "person_id": "separate-person",
            "user_id": "account-1",
            "position_id": "position-identity",
        },
    )
    assert response.status_code == 400
    assert response.json() == {"error": "account_person_mismatch"}
