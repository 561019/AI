from __future__ import annotations


def test_platform_capabilities_cover_all_platform_layers(client):
    response = client.get("/api/integrations/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["identity_contract"]["rule"] == "user_id = actor_id = person_id"

    channels = {item["id"]: item for item in body["channels"]}
    assert channels["runtime_permission_check"]["status"] == "active_mechanism_direct_only"
    assert channels["permission_fact_sync"]["status"] == "active_via_account_gateway"
    assert channels["integration_event_inbox"]["status"] == "reserved"
    assert channels["integration_event_inbox"]["path"] == "/api/integrations/events"

    profiles = {item["source_service"]: item for item in body["module_profiles"]}
    assert len(profiles) == 25
    for source_service in (
        "workflow_control",
        "model_orchestrator",
        "data_platform",
        "security_compliance",
        "agent_sandbox",
        "document_table_parser",
        "content_generation",
        "data_visualization",
        "business_application",
    ):
        assert profiles[source_service]["fact_sync_channel"] == "permission_fact_sync"


def test_reserved_event_endpoint_validates_envelope_then_refuses_write(client):
    response = client.post(
        "/api/integrations/events",
        json={
            "event_id": "event-001",
            "event_type": "workflow.instance.completed",
            "occurred_at": "2026-07-15T00:00:00Z",
            "source_service": "workflow_control",
            "tenant_id": "tenant-a",
            "actor_id": "u-1",
            "resource_type": "workflow",
            "resource_id": "workflow-001",
            "payload": {"state": "completed"},
        },
    )
    assert response.status_code == 501
    body = response.json()
    assert body["error"] == "INTEGRATION_EVENT_NOT_ENABLED"
    assert body["event_id"] == "event-001"
    assert "idempotency store" in body["activation_prerequisites"]


def test_reserved_event_rejects_incomplete_envelope(client):
    response = client.post("/api/integrations/events", json={"event_id": "event-001"})
    assert response.status_code == 422
