from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class CaptureHandler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.status = 0
        self.body = None

    def send(self, status: int, body=None) -> None:
        self.status = status
        self.body = body


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="framework-data-validation-", ignore_cleanup_errors=True) as temp_dir:
        os.environ["PLATFORM_DB_PATH"] = str(Path(temp_dir) / "platform_data.db")

        from framework.core import initialize
        from framework.envelope import make_internal_envelope
        from framework.layers.business_engine.data_operation import service as data_operation
        from framework.layers.foundation.account_gateway import service as account_gateway
        from framework.layers.foundation.foundation_data import service as foundation_data

        initialize()

        def route_foundation(_url, envelope, **_kwargs):
            handler = CaptureHandler("/api/v1/foundation-data/instructions")
            foundation_data.post(handler, envelope)
            return handler.status, handler.body

        data_operation.post_json = route_foundation
        account_gateway.post_json = route_foundation

        actor = {"tenant_id": "validation-tenant", "user_id": "validation-user", "authenticated": True}
        message_envelope = make_internal_envelope(
            "trace-data-validation",
            actor,
            "task-data-validation",
            "data.persist",
            "business_engine",
            "data-operation",
            {
                "dataset": "conversation_messages",
                "operation": "upsert",
                "records": [{
                    "message_id": "msg-validation-001",
                    "conversation_id": "conv-validation-001",
                    "project_id": "project-validation",
                    "owner_account_id": "validation-user",
                    "role": "user",
                    "content": "验证对话持久化",
                }],
            },
        )
        message_handler = CaptureHandler("/api/v1/data/instructions")
        data_operation.post(message_handler, message_envelope)
        assert message_handler.status == 200, message_handler.body

        register_envelope = make_internal_envelope(
            "trace-account-validation",
            {"tenant_id": "validation-tenant", "user_id": "anonymous", "authenticated": False},
            "task-account-register",
            "account.create",
            "foundation",
            "account-gateway",
            {
                "account": {"name": "validation-account", "department": "测试部", "role": "测试用户"},
                "password": "12345678",
                "application_command": {"accountId": "acc-validation-001", "payload": {}},
            },
        )
        register_handler = CaptureHandler("/api/v1/accounts/instructions")
        account_gateway.post(register_handler, register_envelope)
        assert register_handler.status == 200, register_handler.body

        verify_envelope = make_internal_envelope(
            "trace-account-verify",
            actor,
            "task-account-verify",
            "account.identity.verify",
            "foundation",
            "account-gateway",
            {"identifier": "validation-account", "password": "12345678"},
        )
        verify_handler = CaptureHandler("/api/v1/accounts/instructions")
        account_gateway.post(verify_handler, verify_envelope)
        assert verify_handler.status == 200, verify_handler.body

        query_envelope = make_internal_envelope(
            "trace-query-validation",
            actor,
            "task-query-validation",
            "foundation_data.query",
            "foundation",
            "foundation-data",
            {"dataset": "conversation_messages", "filters": {"conversation_id": "conv-validation-001"}},
        )
        query_handler = CaptureHandler("/api/v1/foundation-data/instructions")
        foundation_data.post(query_handler, query_envelope)
        assert query_handler.status == 200, query_handler.body

        result = {
            "status": "passed",
            "data_operation": message_handler.body["data"]["storage_result"]["state"],
            "account_create": register_handler.body["data"]["state"],
            "account_verify": verify_handler.body["data"]["state"],
            "conversation_messages": query_handler.body["data"]["count"],
            "temporary_database_cleanup": "best_effort",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
