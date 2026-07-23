from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class CaptureHandler:
    def __init__(self) -> None:
        self.path = "/api/v1/foundation-data/instructions"
        self.status = 0
        self.body = None

    def send(self, status: int, body=None) -> None:
        self.status = status
        self.body = body


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="framework-data-security-", ignore_cleanup_errors=True) as temp_dir:
        os.environ["PLATFORM_DB_PATH"] = str(Path(temp_dir) / "platform_data.db")

        from framework.core import get_trace_calls, initialize, record_interface_call
        from framework.envelope import make_internal_envelope
        from framework.layers.foundation.foundation_data import service
        from framework.layers.foundation.permission import service as permission_service

        initialize()
        actor = {
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "authenticated": True,
            "allowed_project_ids": ["project-a"],
        }

        def call(capability: str, payload: dict, trace_id: str = "trace-security", source_module: str = "data-operation") -> CaptureHandler:
            envelope = make_internal_envelope(
                trace_id, actor, "task-security", capability, "foundation", "foundation-data", payload,
                source_layer="business_engine", source_module=source_module,
            )
            handler = CaptureHandler()
            service.post(handler, envelope)
            return handler

        created = call("foundation_data.write", {
            "dataset": "conversation_messages",
            "operation": "insert",
            "records": [{
                "message_id": "msg-001",
                "conversation_id": "conv-001",
                "project_id": "project-a",
                "content": "data security validation",
            }],
        })
        assert created.status == 200, created.body
        assert created.body["data"]["items"][0]["record_version"] == 1

        tenant_denied = call("foundation_data.query", {
            "dataset": "conversation_messages", "tenant_id": "tenant-b",
        }, "trace-tenant-denied")
        assert tenant_denied.status == 403, tenant_denied.body
        assert "TENANT_SCOPE_MISMATCH" in tenant_denied.body["error"]["message"]

        project_denied = call("foundation_data.write", {
            "dataset": "conversation_messages",
            "records": [{"message_id": "msg-002", "conversation_id": "conv-001", "project_id": "project-b"}],
        }, "trace-project-denied")
        assert project_denied.status == 403, project_denied.body
        assert "PROJECT_SCOPE_DENIED" in project_denied.body["error"]["message"]

        unknown_denied = call("foundation_data.query", {"dataset": "arbitrary_runtime_dataset"}, "trace-dataset-denied")
        assert unknown_denied.status == 403, unknown_denied.body
        assert "DATASET_NOT_REGISTERED" in unknown_denied.body["error"]["message"]

        sensitive_denied = call("foundation_data.query", {"dataset": "account_credentials"}, "trace-sensitive-denied")
        assert sensitive_denied.status == 403, sensitive_denied.body
        assert "SOURCE_MODULE_NOT_ALLOWED" in sensitive_denied.body["error"]["message"]

        version_conflict = call("foundation_data.write", {
            "dataset": "conversation_messages",
            "operation": "update",
            "records": [{"message_id": "msg-001", "expected_record_version": 99, "content": "conflict"}],
        })
        assert version_conflict.status == 422, version_conflict.body
        assert "record version conflict" in version_conflict.body["error"]["message"]

        catalog = call("foundation_data.catalog.list", {})
        assert catalog.status == 200, catalog.body
        assert any(item["dataset"] == "conversation_messages" for item in catalog.body["data"]["items"])

        access_trace = call("foundation_data.access.trace", {"trace_id": "trace-tenant-denied"})
        assert access_trace.status == 200, access_trace.body
        assert access_trace.body["data"]["items"][0]["effect"] == "deny"

        record_interface_call(
            trace_id="trace-redaction",
            source={"layer": "test", "module": "security-test"},
            target={"layer": "foundation", "module": "account-gateway"},
            capability="account.identity.verify",
            method="POST",
            url="http://local/test",
            request={"password": "never-store-this", "nested": {"api_key": "secret-key"}},
            response={"token": "secret-token"},
            status_code=200,
            duration_ms=1,
        )
        logged = get_trace_calls("trace-redaction")[0]
        assert logged["request"]["password"] == "***REDACTED***"
        assert logged["request"]["nested"]["api_key"] == "***REDACTED***"
        assert logged["response"]["token"] == "***REDACTED***"

        permission_handler = CaptureHandler()
        permission_handler.path = "/api/v1/permissions/check"
        permission_service.post(permission_handler, {
            "actor": actor,
            "action": "read",
            "resource": {"dataset": "conversation_messages", "tenant_id": "tenant-a", "project_id": "project-b"},
            "scope": {"requested_fields": ["message_id", "content"]},
        })
        assert permission_handler.status == 200
        assert permission_handler.body["decision"] == "deny"
        assert permission_handler.body["reason_code"] == "PROJECT_SCOPE_DENIED"

        workflow_persisted = call("foundation_data.write", {
            "_requesting_module": "workflow-execution",
            "writes": [
                {"dataset": "workflow_instances", "records": [{"workflow_instance_id": "wf-001", "state": "completed"}]},
                {"dataset": "workflow_node_instances", "records": [{"node_instance_id": "node-001", "workflow_instance_id": "wf-001", "state": "completed"}]},
                {"dataset": "workflow_events", "operation": "insert", "records": [{"event_id": "evt-001", "workflow_instance_id": "wf-001", "event_type": "workflow_completed"}]},
            ],
        }, "trace-workflow-persistence")
        assert workflow_persisted.status == 200, workflow_persisted.body
        assert workflow_persisted.body["data"]["count"] == 3

        print({
            "status": "passed",
            "dataset_catalog": len(catalog.body["data"]["items"]),
            "tenant_denied": True,
            "project_denied": True,
            "unknown_dataset_denied": True,
            "sensitive_dataset_denied": True,
            "optimistic_lock_checked": True,
            "interface_log_redaction": True,
            "central_abac_policy": True,
            "workflow_state_persistence": True,
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
