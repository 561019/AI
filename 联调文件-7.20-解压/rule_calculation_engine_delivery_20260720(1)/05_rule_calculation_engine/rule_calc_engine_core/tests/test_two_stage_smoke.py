from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import initialize_database
from app.platform_instruction import PlatformInstructionService


class TwoStagePlatformInstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)
        self.service = PlatformInstructionService(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _instruction(*, message_id: str, idempotency_key: str, data_refs: list[dict]) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "protocol_version": "1.0",
            "message_id": message_id,
            "trace_id": "trace-two-stage-test",
            "request_id": "request-two-stage-test",
            "occurred_at": now.isoformat(),
            "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
            "target": {"layer": "L2", "service_code": "l2.rule_calculation"},
            "channel": "l2_internal",
            "action": "rule.evaluate",
            "request_type": "execute",
            "actor": {"person_id": "business_operator"},
            "context": {"task_id": "task-two-stage-test", "data_refs": data_refs},
            "idempotency_key": idempotency_key,
            "deadline_at": (now + timedelta(minutes=1)).isoformat(),
            "payload": {
                "task": "Calculate bad debt provision for the authorized 2026 Q2 receivables.",
                "business_type": "bad_debt_provision",
                "business_object_ref": "ORG-001",
                "period": "2026-Q2",
            },
        }

    def test_assessment_then_reference_completion_reaches_deterministic_result(self) -> None:
        assessment_reply = self.service.handle(
            self._instruction(
                message_id="msg-two-stage-assessment",
                idempotency_key="idem-two-stage-assessment",
                data_refs=[],
            )
        )
        assessment = assessment_reply["result"]["data"]
        self.assertEqual(assessment_reply["reply_type"], "success")
        self.assertEqual(assessment["state"], "precondition_query_required")
        self.assertEqual(
            {item["query_type"] for item in assessment["query_requirements"]},
            {
                "formal_calculation_basis",
                "published_calculation_capability",
                "authorized_business_data",
            },
        )

        execution_reply = self.service.handle(
            self._instruction(
                message_id="msg-two-stage-execution",
                idempotency_key="idem-two-stage-execution",
                data_refs=[
                    {
                        "ref_id": "RULE-PARAMETERS-001",
                        "purpose": "rule_parameter",
                        "version": "PARAM-BAD-DEBT-2026Q2-1.0",
                    },
                    {
                        "ref_id": "DS-RECEIVABLES-2026Q2",
                        "purpose": "calculation_input",
                        "data_labels": ["internal", "financial"],
                        "allowed_actions": ["read_for_rule_calculation"],
                    },
                ],
            )
        )
        self.assertEqual(execution_reply["reply_type"], "accepted")
        self.assertEqual(execution_reply["result"]["state"], "waiting_human")
        self.assertEqual(execution_reply["result"]["handling_type"], "confirm_effective")
        self.assertEqual(execution_reply["trace_id"], "trace-two-stage-test")


if __name__ == "__main__":
    unittest.main()
