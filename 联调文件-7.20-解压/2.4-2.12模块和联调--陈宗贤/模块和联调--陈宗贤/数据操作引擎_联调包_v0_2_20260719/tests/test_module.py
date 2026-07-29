from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from service import PlatformAdapter  # noqa: E402


def standard_envelope(action: str, payload: dict, *, mode: str = "sync") -> dict:
    trace_id = f"trace-test-{action.replace('.', '-')}-{abs(hash(json.dumps(payload, sort_keys=True))) % 1000000}"
    return {
        "protocol_version": "1.0",
        "message_id": f"msg-{trace_id}",
        "request_id": f"req-{trace_id}",
        "trace_id": trace_id,
        "parent_request_id": "req-workflow-parent-001",
        "source": {"layer": "business_engine", "module": "workflow-execution"},
        "target": {"layer": "business_engine", "module": "data-operation", "capability": action},
        "actor": {"tenant_id": "tenant-test", "user_id": "manager_all", "authenticated": True},
        "context": {"account_id": "manager_all", "project_id": "project-test", "conversation_id": "conversation-test", "file_id": None, "object_id": None, "workflow_instance_id": "workflow-test"},
        "request_type": "task.dispatch",
        "action": action,
        "payload": payload,
        "expected_response": {"mode": mode},
        **({"idempotency_key": f"idem-{trace_id}"} if action in {"data.collect", "data.consolidate", "data.persist", "data.update", "data.delete"} else {}),
    }


class PlatformAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.adapter = PlatformAdapter(Path(self.temp.name) / "module.db")

    def tearDown(self) -> None:
        self.adapter.close()
        self.temp.cleanup()

    def test_persist_sync_returns_standard_success_and_data_ref(self) -> None:
        envelope = standard_envelope("data.persist", {
            "business_type": "business_note",
            "data_labels": ["test", "business-data"],
            "company_codes": ["TEST-A"],
            "storage_class": "fixed",
            "retention_policy_ref": "retention-test-v1",
            "content": {"title": "测试", "body": "标准接口存档"},
        })
        status, body = self.adapter.handle_instruction(envelope)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertTrue(body["data"]["data_ref"].startswith("data-"))
        self.assertEqual(body["data"]["business_context"]["tenant_id"], "tenant-test")
        self.assertEqual(body["data"]["business_context"]["project_id"], "project-test")

    def test_search_async_returns_standard_accepted_with_status_url(self) -> None:
        envelope = standard_envelope("data.search", {
            "company_codes": ["TEST-A"],
            "business_context": {"permission_decision_id": "perm-test-001"},
            "query_spec": {
                "operation": "detail_records", "business_object": "sales_record",
                "resource_types": ["sales_record"], "fields": ["record_id"],
                "filters": {"tenant_id": "tenant-test"}, "group_by": [], "aggregations": [], "sort": [], "limit": 100,
            },
        }, mode="async")
        status, body = self.adapter.handle_instruction(envelope)
        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["task_id"], envelope["trace_id"])
        self.assertIn(envelope["trace_id"], body["status_url"])

    def test_search_sync_returns_business_result_not_raw_field_sample(self) -> None:
        persist = standard_envelope("data.persist", {
            "business_type": "business_record_table",
            "data_labels": ["sales", "test"],
            "company_codes": ["TEST-A"],
            "storage_class": "fixed",
            "retention_policy_ref": "retention-test-v1",
            "content": {
                "resource_type": "sales_record",
                "records": [
                    {"record_id": "S-001", "dealer_name": "经销商一", "tenant_id": "tenant-test", "amount": 1200},
                    {"record_id": "S-002", "dealer_name": "经销商二", "tenant_id": "tenant-test", "amount": 800}
                ]
            },
        })
        status, persisted = self.adapter.handle_instruction(persist)
        self.assertEqual(status, 200)
        self.assertTrue(persisted["data"]["data_ref"].startswith("data-"))

        search = standard_envelope("data.search", {
            "company_codes": ["TEST-A"],
            "business_context": {"permission_decision_id": "perm-test-002"},
            "query_spec": {
                "operation": "list_entity", "business_object": {"code": "dealer", "name": "经销商"},
                "resource_types": ["sales_record"], "fields": ["record_id", "dealer_name"],
                "filters": {"tenant_id": "tenant-test"}, "group_by": [], "aggregations": [], "sort": [], "limit": 100,
            },
        })
        status, result = self.adapter.handle_instruction(search)
        self.assertEqual(status, 200)
        self.assertEqual(result["data"]["contract_version"], "business-result.v1")
        self.assertEqual(result["data"]["business_result"]["business_object"]["code"], "dealer")
        self.assertEqual(len(result["data"]["business_result"]["items"]), 2)
        self.assertIn("evidence", result["data"])
        self.assertIn("raw_access", result["data"])

    def test_frontend_direct_source_is_rejected(self) -> None:
        envelope = standard_envelope("data.persist", {
            "business_type": "business_note", "data_labels": ["test"], "company_codes": ["TEST-A"],
            "storage_class": "fixed", "retention_policy_ref": "retention-test-v1", "content": {"title": "x"},
        })
        envelope["source"] = {"layer": "application", "module": "l4-workbench"}
        status, body = self.adapter.handle_instruction(envelope)
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["error"]["code"], "WORKFLOW_SOURCE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
