from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.contracts import ExecutionPath, ExecutionRequest, ProcessingState
from app.database import connect, initialize_database
from app.engine import RuleEngineService


class DeclarativeRuleExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)
        self.engine = RuleEngineService(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def request(**overrides: object) -> ExecutionRequest:
        payload = {
            "trace_id": "TRC-DECL-0001",
            "request_id": "REQ-DECL-0001",
            "identity_context_ref": "ctx-business-operator",
            "business_type": "policy_allowance_calculation",
            "business_object_id": "ORG-001",
            "period": "2026-07",
            "data_reference": "DS-ALLOWANCE-2026-07",
        }
        payload.update(overrides)
        return ExecutionRequest(**payload)

    def test_lookup_formula_condition_and_sum_are_configuration_driven(self) -> None:
        response = self.engine.execute(self.request())

        self.assertEqual(response.execution_path, ExecutionPath.DETERMINISTIC)
        self.assertEqual(response.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(
            response.versions.capability_code, "CAP-POLICY-ALLOWANCE-DECL"
        )
        self.assertEqual(response.result["total_count"], 3)
        self.assertEqual(response.result["passed_count"], 2)
        self.assertEqual(response.result["requires_handling_count"], 1)
        self.assertEqual(response.result["total_allowance"], "3200.00")
        self.assertTrue(all(check.passed for check in response.validation))

        first = response.result["lines"][0]
        self.assertEqual(first["daily_rate"], "100.00")
        self.assertEqual(first["allowance_amount"], "2000.00")
        self.assertEqual(first["decision"], "passed")
        self.assertTrue(first["lookup_evidence"][0]["matched"])
        self.assertEqual(
            first["calculation_evidence"][0]["operator"], "multiply"
        )

        exception = response.result["lines"][2]
        self.assertEqual(exception["decision"], "requires_handling")
        self.assertEqual(
            exception["reason_codes"], ["MAX_ELIGIBLE_DAYS_EXCEEDED"]
        )
        self.assertFalse(exception["condition_evidence"][0]["passed"])

    def test_unknown_lookup_value_has_a_deterministic_reason(self) -> None:
        with connect(self.database_path) as connection:
            dataset = connection.execute(
                "SELECT payload_json FROM business_datasets WHERE data_reference = ?",
                ("DS-ALLOWANCE-2026-07",),
            ).fetchone()
            rows = json.loads(dataset["payload_json"])
            rows[0]["grade"] = "unregistered_grade"
            connection.execute(
                "UPDATE business_datasets SET payload_json = ? WHERE data_reference = ?",
                (json.dumps(rows), "DS-ALLOWANCE-2026-07"),
            )

        response = self.engine.execute(self.request())

        first = response.result["lines"][0]
        self.assertEqual(first["decision"], "requires_handling")
        self.assertEqual(first["reason_codes"], ["GRADE_RULE_NOT_FOUND"])
        self.assertIsNone(first["daily_rate"])
        self.assertIsNone(first["allowance_amount"])
        self.assertEqual(
            first["calculation_evidence"][0]["status"], "skipped"
        )
        self.assertTrue(all(check.passed for check in response.validation))

    def test_unsupported_operator_is_blocked_before_business_result(self) -> None:
        with connect(self.database_path) as connection:
            rule = connection.execute(
                """SELECT payload_json FROM rule_versions
                   WHERE capability_code = ? AND status = 'published'""",
                ("CAP-POLICY-ALLOWANCE-DECL",),
            ).fetchone()
            payload = json.loads(rule["payload_json"])
            payload["operations"]["formulas"][0]["operator"] = "python_eval"
            connection.execute(
                """UPDATE rule_versions SET payload_json = ?
                   WHERE capability_code = ? AND status = 'published'""",
                (json.dumps(payload), "CAP-POLICY-ALLOWANCE-DECL"),
            )

        response = self.engine.execute(self.request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "EXECUTION_CONFIGURATION_INVALID")
        self.assertIn("Unsupported declarative formula operator", response.message)
        self.assertIsNone(response.result)


if __name__ == "__main__":
    unittest.main()
