from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.models import Person, PersonPositionAssignment
from tests.test_contract import seed_position_permission


def test_verified_identity_positions_do_not_require_permission_side_person_copy(
    app, client, admin_headers, command_fn, check_payload
):
    assert seed_position_permission(client, admin_headers, command_fn).status_code == 201
    with app.state.database.session() as session:
        session.execute(delete(PersonPositionAssignment))
        session.execute(delete(Person))
        session.commit()
    check_payload["identity_position_ids"] = ["position-1"]
    check_payload["responsible_actor_id"] = "u-1"
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_institution_deny_overrides_position_allow(
    client, admin_headers, command_fn, check_payload
):
    seed_position_permission(client, admin_headers, command_fn)
    response = command_fn(
        client,
        admin_headers,
        "/api/permissions/commands",
        "create_institution_policy",
        {
            "name": "禁止内容生成",
            "subject_type": "any",
            "action": "content.generate",
            "data_label": "normal",
            "data_states": ["active"],
            "source_service": "intent_engine",
            "target_service": "content_engine",
            "effect": "deny",
            "priority": 1000,
            "basis": "测试制度",
        },
    )
    assert response.status_code == 201
    result = client.post("/api/permission/check", json=check_payload).json()
    assert result["allowed"] is False
    assert result["reason_code"] == "ACTION_NOT_GRANTED"


def test_expired_permission_is_distinguished(
    client, admin_headers, command_fn, check_payload
):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    seed_position_permission(
        client, admin_headers, command_fn, valid_to=yesterday
    )
    result = client.post("/api/permission/check", json=check_payload).json()
    assert result["allowed"] is False
    assert result["reason_code"] == "PERMISSION_EXPIRED"


def test_data_state_constraint_precedes_owner_permission(
    client, admin_headers, command_fn, check_payload
):
    assert command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "create_position",
        {"id": "position-1", "title": "数据责任人"},
    ).status_code == 201
    assert command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "assign_person_position",
        {"person_id": "u-1", "user_id": "u-1", "position_id": "position-1"},
    ).status_code == 201
    assert command_fn(
        client,
        admin_headers,
        "/api/permissions/commands",
        "register_data_record",
        {
            "id": "data-1",
            "title": "冻结数据",
            "source_type": "test",
            "owner_person_id": "u-1",
            "owner_user_id": "u-1",
            "data_label": "normal",
            "status": "frozen",
            "allowed_actions": ["read"],
            "basis": "测试登记",
        },
    ).status_code == 201
    check_payload.update(
        {
            "action": "read",
            "resource_type": "data",
            "resource_id": "data-1",
            "data_state": "frozen",
        }
    )
    result = client.post("/api/permission/check", json=check_payload).json()
    assert result["allowed"] is False
    assert result["reason_code"] == "DATA_STATE_DENIED"


def test_delegation_grants_registered_data(
    client, admin_headers, command_fn, check_payload
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
                "person_id": f"u-{index}",
                "user_id": f"u-{index}",
                "position_id": f"position-{index}",
            },
        ).status_code == 201
    command_fn(
        client,
        admin_headers,
        "/api/permissions/commands",
        "register_data_record",
        {
            "id": "data-1",
            "title": "授权数据",
            "source_type": "test",
            "owner_person_id": "u-1",
            "owner_user_id": "u-1",
            "data_label": "normal",
            "status": "active",
            "allowed_actions": ["read"],
            "basis": "测试登记",
        },
    )
    command_fn(
        client,
        admin_headers,
        "/api/permissions/commands",
        "create_delegation",
        {
            "from_person_id": "u-1",
            "to_person_id": "u-2",
            "resource_type": "data",
            "resource_id": "data-1",
            "action": "read",
            "data_label": "normal",
            "data_states": ["active"],
            "basis": "责任人转授",
        },
    )
    check_payload.update(
        {
            "actor_id": "u-2",
            "action": "read",
            "resource_type": "data",
            "resource_id": "data-1",
        }
    )
    result = client.post("/api/permission/check", json=check_payload).json()
    assert result["allowed"] is True
    assert result["reason_code"] == "PERMISSION_GRANTED"
