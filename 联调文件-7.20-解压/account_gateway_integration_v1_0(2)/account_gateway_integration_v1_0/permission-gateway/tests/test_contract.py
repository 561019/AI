from __future__ import annotations


def seed_position_permission(client, headers, command, *, valid_to=None):
    assert command(
        client,
        headers,
        "/api/org/commands",
        "create_position",
        {"id": "position-1", "title": "内容专员", "department_id": "content"},
    ).status_code == 201
    assert command(
        client,
        headers,
        "/api/org/commands",
        "assign_person_position",
        {
            "person_id": "u-1",
            "user_id": "u-1",
            "position_id": "position-1",
        },
    ).status_code == 201
    payload = {
        "position_id": "position-1",
        "action": "content.generate",
        "data_label": "normal",
        "data_states": ["active"],
        "source_service": "intent_engine",
        "target_service": "content_engine",
    }
    if valid_to:
        payload["valid_to"] = valid_to
    return command(
        client,
        headers,
        "/api/permissions/commands",
        "create_position_standard_resource",
        payload,
    )


def test_health_contract(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "permission_gateway"
    assert body["version"] == "1.0.0"
    assert body["database"] == "ok"
    assert "+08:00" in body["timestamp"]


def test_allow_response_echoes_ids_and_writes_audit(
    client, admin_headers, command_fn, check_payload
):
    assert seed_position_permission(client, admin_headers, command_fn).status_code == 201
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == check_payload["trace_id"]
    assert body["request_id"] == check_payload["request_id"]
    assert body["decision_id"].startswith("decision_")
    assert body["allowed"] is True
    assert body["result"] == "allow"
    assert body["reason_code"] == "PERMISSION_GRANTED"
    assert body["four_factors"] == {
        "data_label": "normal",
        "action": "content.generate",
        "actor_id": "u-1",
        "data_state": "active",
    }

    audit = client.get("/api/permission/audits?trace_id=trace-1")
    assert audit.status_code == 200
    rows = audit.json()["audits"]
    assert len(rows) == 1
    assert rows[0]["decision_id"] == body["decision_id"]
    assert rows[0]["result"] == "allow"
    assert rows[0]["transfer_id"] == "transfer-1"
    assert rows[0]["ingress_mode"] == "mechanism_direct"


def test_business_deny_is_http_200(client, admin_headers, command_fn, check_payload):
    assert command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "create_position",
        {"id": "position-1", "title": "无权限岗位"},
    ).status_code == 201
    assert command_fn(
        client,
        admin_headers,
        "/api/org/commands",
        "assign_person_position",
        {"person_id": "u-1", "user_id": "u-1", "position_id": "position-1"},
    ).status_code == 201
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert response.json()["result"] == "deny"
    assert response.json()["reason_code"] == "ACTION_NOT_GRANTED"


def test_missing_field_returns_field_level_422_and_error_audit(client, check_payload):
    check_payload.pop("trace_id")
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 422
    body = response.json()
    assert body["allowed"] is False
    assert body["result"] == "error"
    assert body["reason_code"] == "INVALID_REQUEST"
    assert body["error"]["details"]["fields"]
    audit = client.get("/api/permission/audits?result=error")
    assert audit.status_code == 200
    assert audit.json()["audits"][0]["reason_code"] == "INVALID_REQUEST"


def test_service_relationship_deny_is_audited(client, check_payload):
    check_payload["source_service"] = "unknown-source"
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 200
    assert response.json()["reason_code"] == "SERVICE_CALL_DENIED"
    audit = client.get("/api/permission/audits?trace_id=trace-1").json()["audits"]
    assert audit[0]["result"] == "deny"


def test_unregistered_action_is_business_field_400(client, check_payload):
    check_payload["action"] = "unregistered.action"
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 400
    assert response.json()["allowed"] is False
    assert response.json()["result"] == "error"
    assert response.json()["reason_code"] == "INVALID_REQUEST"
    audit = client.get("/api/permission/audits?trace_id=trace-1").json()["audits"]
    assert audit[0]["result"] == "error"


def test_check_rejects_separate_person_and_account_ids(client, check_payload):
    check_payload["person_id"] = "different-person"
    response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 400
    assert response.json()["reason_code"] == "INVALID_REQUEST"
    assert response.json()["allowed"] is False


def test_check_rejects_untrusted_direct_ingress(app, check_payload):
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.post("/api/permission/check", json=check_payload)
    assert response.status_code == 403
    assert response.json()["reason_code"] == "UNTRUSTED_INGRESS"
