from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.contracts import (
    CandidateImplementationReference,
    CandidateSkillTrialRequest,
    ExecutionPath,
    ExecutionRequest,
    HandlingType,
    HumanAction,
    HumanHandlingRequest,
    ProcessingState,
)
from app.adapters import LocalDigitalAssetAdapter, LocalSandboxAdapter
from app.database import connect, initialize_database
from app.engine import RuleEngineService
from app.ports import DigitalAssetCandidateRequest, SandboxRunRequest


class GenericCapabilityExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)
        self.engine = RuleEngineService(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def order_request(**overrides: object) -> ExecutionRequest:
        payload = {
            "trace_id": "TRC-ORDER-0001",
            "request_id": "REQ-ORDER-0001",
            "identity_context_ref": "ctx-business-operator",
            "business_type": "order_range_audit",
            "business_object_id": "ORG-001",
            "period": "2026-Q2",
            "data_reference": "DS-ORDERS-2026Q2",
        }
        payload.update(overrides)
        return ExecutionRequest(**payload)

    def test_order_sample_uses_registered_capability_without_engine_scenario_branch(self) -> None:
        response = self.engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(response.versions.capability_code, "CAP-ORDER-RANGE-PY")
        self.assertEqual(response.result["total_count"], 4)
        self.assertEqual(response.result["passed_count"], 2)
        self.assertEqual(response.result["requires_handling_count"], 2)
        self.assertTrue(all(check.passed for check in response.validation))
        exception_reasons = {
            reason
            for line in response.result["lines"]
            for reason in line["reason_codes"]
        }
        self.assertEqual(exception_reasons, {"PRICE_OUT_OF_RANGE", "RULE_NOT_FOUND"})

    def test_request_can_lock_an_explicit_registered_capability(self) -> None:
        response = self.engine.execute(
            self.order_request(requested_capability_code="CAP-ORDER-RANGE-PY")
        )

        self.assertEqual(response.versions.capability_code, "CAP-ORDER-RANGE-PY")

    def test_multiple_published_capabilities_require_explicit_selection(self) -> None:
        self._insert_order_capability("CAP-ORDER-RANGE-ALTERNATE", "published")

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "AMBIGUOUS_CAPABILITY_MATCH")

    def test_explicit_capability_remains_deterministic_when_multiple_candidates_exist(self) -> None:
        self._insert_order_capability("CAP-ORDER-RANGE-ALTERNATE", "published")

        response = self.engine.execute(
            self.order_request(requested_capability_code="CAP-ORDER-RANGE-PY")
        )

        self.assertEqual(response.versions.capability_code, "CAP-ORDER-RANGE-PY")

    def test_unpublished_capability_is_not_an_execution_candidate(self) -> None:
        self._insert_order_capability("CAP-ORDER-RANGE-DRAFT", "draft")

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.versions.capability_code, "CAP-ORDER-RANGE-PY")

    def test_multiple_published_rule_versions_are_blocked(self) -> None:
        with connect(self.database_path) as connection:
            current = connection.execute(
                "SELECT payload_json FROM rule_versions WHERE capability_code = ? AND status = 'published'",
                ("CAP-ORDER-RANGE-PY",),
            ).fetchone()
            connection.execute(
                """INSERT INTO rule_versions
                   (capability_code, rule_version, parameter_version, treatment_rule_version, status, payload_json)
                   VALUES (?, ?, ?, ?, 'published', ?)""",
                (
                    "CAP-ORDER-RANGE-PY",
                    "RULE-ORDER-RANGE-CONFLICT",
                    "PARAM-ORDER-RANGE-CONFLICT",
                    "TREAT-ORDER-RANGE-CONFLICT",
                    current["payload_json"],
                ),
            )

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "PUBLISHED_VERSION_CONFLICT")

    def test_rule_must_be_effective_at_calculation_reference_time(self) -> None:
        response = self.engine.execute(
            self.order_request(
                calculation_as_of=datetime(2026, 7, 14, 23, 59, tzinfo=timezone.utc)
            )
        )

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "RULE_NOT_EFFECTIVE_AT_CALCULATION_TIME")

    def test_published_rule_without_effective_time_is_blocked(self) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE rule_version_governance SET effective_at = NULL
                   WHERE rule_version_id = (
                       SELECT id FROM rule_versions
                       WHERE capability_code = ? AND status = 'published'
                   )""",
                ("CAP-ORDER-RANGE-PY",),
            )

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "RULE_EFFECTIVE_TIME_MISSING")

    def test_missing_formal_capability_waits_for_ai_generation_authorization(self) -> None:
        response = self.engine.execute(
            self.order_request(
                business_type="uncovered_temporary_analysis",
                requested_capability_code=None,
                data_reference="DS-MARGIN-TEST",
                temporary_analysis_spec={
                    "objective": "Calculate a temporary margin scenario.",
                    "input_schema": {"required_fields": ["baseline_revenue"]},
                    "output_schema": {"required_fields": ["adjusted_revenue"]},
                },
            )
        )

        self.assertEqual(response.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(response.execution_path, ExecutionPath.SANDBOX)
        self.assertEqual(response.handling_type, HandlingType.AUTHORIZE_AI_GENERATION)
        self.assertEqual(response.reason_code, "AI_GENERATION_AUTHORIZATION_REQUIRED")

    def test_unauthorized_request_without_capability_is_denied_before_ai_option(self) -> None:
        response = self.engine.execute(
            self.order_request(
                identity_context_ref="ctx-unauthorized-user",
                business_type="uncovered_temporary_analysis",
                requested_capability_code=None,
            )
        )

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "PERMISSION_DENIED")
        self.assertNotEqual(response.handling_type, HandlingType.AUTHORIZE_AI_GENERATION)

    def test_ai_generation_authorization_is_recorded_before_candidate_creation(self) -> None:
        execution = self.engine.execute(
            self.order_request(
                business_type="uncovered_temporary_analysis",
                requested_capability_code=None,
                data_reference="DS-MARGIN-TEST",
                temporary_analysis_spec={
                    "objective": "Calculate the temporary margin impact of an approved scenario.",
                    "input_schema": {"required_fields": ["baseline_revenue"]},
                    "output_schema": {
                        "required_fields": ["adjusted_revenue", "gross_profit_change"]
                    },
                    "assumptions": ["The scenario parameters were confirmed by the requester."],
                },
            )
        )

        outcome = self.engine.handle_waiting_result(
            execution.execution_record_id,
            HumanHandlingRequest(
                identity_context_ref="ctx-business-operator",
                action=HumanAction.APPROVE,
                comment="The temporary AI generation and sandbox risk were explained and accepted.",
            ),
        )

        self.assertEqual(outcome.state, ProcessingState.AUTOMATIC_PASS)
        self.assertEqual(outcome.reason_code, "AI_GENERATION_AUTHORIZED")
        self.assertIsNone(outcome.next_execution_record_id)
        self.assertIsNotNone(outcome.candidate_skill_creation_request)
        creation = outcome.candidate_skill_creation_request
        self.assertEqual(creation.authorization_execution_record_id, execution.execution_record_id)
        self.assertEqual(creation.candidate_request_id, f"CSR-{execution.execution_record_id}")
        self.assertEqual(creation.data_references[0].reference_id, "DS-MARGIN-TEST")
        self.assertEqual(creation.temporary_analysis_spec.objective, "Calculate the temporary margin impact of an approved scenario.")

        with self.assertRaisesRegex(ValueError, "does not match"):
            self.engine.resume_candidate_skill_trial(
                execution.execution_record_id,
                CandidateSkillTrialRequest(
                    identity_context_ref="ctx-business-operator",
                    candidate_implementation=CandidateImplementationReference(
                        candidate_request_id="CSR-ANOTHER-AUTHORIZATION",
                        artifact_ref="asset://candidate-skill/WRONG-REQUEST",
                        artifact_version="candidate-1",
                        source="digital-asset-engine:integration-simulator",
                        code_digest="wrong-candidate-digest",
                        entrypoint="calculate",
                        generation_id="GEN-WRONG-REQUEST",
                        candidate_only=True,
                    ),
                ),
            )

        trial = self.engine.resume_candidate_skill_trial(
            execution.execution_record_id,
            CandidateSkillTrialRequest(
                identity_context_ref="ctx-business-operator",
                candidate_implementation=CandidateImplementationReference(
                    candidate_request_id=creation.candidate_request_id,
                    artifact_ref="asset://candidate-skill/TRC-TEST-001",
                    artifact_version="candidate-1",
                    source="digital-asset-engine:integration-simulator",
                    code_digest="test-candidate-digest",
                    entrypoint="calculate",
                    generation_id="GEN-TEST-001",
                    candidate_only=True,
                ),
            ),
        )
        self.assertEqual(trial.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(trial.reason_code, "SANDBOX_RESULT_REVIEW_REQUIRED")
        self.assertEqual(trial.execution_path, ExecutionPath.SANDBOX)
        self.assertEqual(trial.candidate_asset_reference.artifact_ref, "asset://candidate-skill/TRC-TEST-001")
        child = self.engine.execution_records.get_by_id(trial.execution_record_id)
        self.assertEqual(child["parent_execution_record_id"], execution.execution_record_id)
        self.assertEqual(child["handling_type"], HandlingType.REVIEW_SANDBOX_RESULT.value)

        review = self.engine.handle_waiting_result(
            trial.execution_record_id,
            HumanHandlingRequest(
                identity_context_ref="ctx-business-operator",
                action=HumanAction.APPROVE,
                comment="The requester reviewed the temporary result for reference use only.",
            ),
        )
        self.assertEqual(review.state, ProcessingState.AUTOMATIC_PASS)
        self.assertEqual(
            review.reason_code, "SANDBOX_RESULT_REVIEWED_REFERENCE_ONLY"
        )
        self.assertIn("reference-only", review.message)

    def test_ai_generation_authorization_must_be_confirmed_by_original_requester(self) -> None:
        execution = self.engine.execute(
            self.order_request(
                business_type="uncovered_temporary_analysis",
                requested_capability_code=None,
                data_reference="DS-MARGIN-TEST",
                temporary_analysis_spec={
                    "objective": "Calculate a temporary margin scenario.",
                    "input_schema": {"required_fields": ["baseline_revenue"]},
                    "output_schema": {"required_fields": ["adjusted_revenue"]},
                },
            )
        )

        with self.assertRaisesRegex(PermissionError, "original calculation requester"):
            self.engine.handle_waiting_result(
                execution.execution_record_id,
                HumanHandlingRequest(
                    identity_context_ref="ctx-business-manager",
                    action=HumanAction.APPROVE,
                    comment="Attempted authorization on behalf of another requester.",
                ),
            )

        self.assertFalse(self.engine.execution_records.has_human_handling(execution.execution_record_id))

    def test_ai_authorization_requires_analysis_spec_before_human_authorization(self) -> None:
        execution = self.engine.execute(
            self.order_request(
                business_type="uncovered_temporary_analysis",
                requested_capability_code=None,
            )
        )

        self.assertEqual(execution.state, ProcessingState.BLOCKED)
        self.assertEqual(execution.reason_code, "TEMPORARY_ANALYSIS_SPEC_REQUIRED")

    def test_order_result_automatically_passes_when_all_rows_are_within_range(self) -> None:
        with connect(self.database_path) as connection:
            dataset = connection.execute(
                "SELECT payload_json FROM business_datasets WHERE data_reference = ?",
                ("DS-ORDERS-2026Q2",),
            ).fetchone()
            rows = json.loads(dataset["payload_json"])
            rows = rows[:2]
            connection.execute(
                "UPDATE business_datasets SET payload_json = ? WHERE data_reference = ?",
                (json.dumps(rows), "DS-ORDERS-2026Q2"),
            )

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.AUTOMATIC_PASS)
        self.assertIsNone(response.handling_type)

    def test_execution_digest_changes_when_actual_business_data_changes(self) -> None:
        first = self.engine.execute(self.order_request())
        with connect(self.database_path) as connection:
            dataset = connection.execute(
                "SELECT payload_json FROM business_datasets WHERE data_reference = ?",
                ("DS-ORDERS-2026Q2",),
            ).fetchone()
            rows = json.loads(dataset["payload_json"])
            rows[0]["quantity"] = 201
            connection.execute(
                "UPDATE business_datasets SET payload_json = ? WHERE data_reference = ?",
                (json.dumps(rows), "DS-ORDERS-2026Q2"),
            )
        second = self.engine.execute(
            self.order_request(trace_id="TRC-ORDER-0002", request_id="REQ-ORDER-0002")
        )
        with connect(self.database_path) as connection:
            first_digest = connection.execute(
                "SELECT input_digest FROM execution_records WHERE execution_record_id = ?",
                (first.execution_record_id,),
            ).fetchone()["input_digest"]
            second_digest = connection.execute(
                "SELECT input_digest FROM execution_records WHERE execution_record_id = ?",
                (second.execution_record_id,),
            ).fetchone()["input_digest"]

        self.assertNotEqual(first.data_references[0].data_digest, second.data_references[0].data_digest)
        self.assertNotEqual(first_digest, second_digest)

    def test_path_three_adapters_are_explicit_contract_simulators(self) -> None:
        artifact = LocalDigitalAssetAdapter().request_candidate_code(
            DigitalAssetCandidateRequest(
                trace_id="TRC-SANDBOX-0001",
                request_id="REQ-SANDBOX-0001",
                candidate_request_id="CSR-SANDBOX-0001",
                business_type="temporary_margin_analysis",
                objective="Calculate a temporary margin scenario.",
                input_schema={"required_fields": ["baseline_revenue"]},
                output_schema={"required_fields": ["adjusted_revenue"]},
                assumptions=[],
            )
        )
        run = LocalSandboxAdapter().run(
            SandboxRunRequest(
                trace_id="TRC-SANDBOX-0001",
                artifact=artifact,
                data_reference="DS-MARGIN-TEST",
                validation_requirements=["Output must match the temporary contract."],
                resource_limits={"timeout_seconds": 3, "network_access": False},
            )
        )

        self.assertTrue(artifact.candidate_only)
        self.assertTrue(artifact.artifact_ref.startswith("asset://candidate-python/"))
        self.assertTrue(run.result["simulation"])

    def test_missing_required_input_field_is_blocked_before_execution(self) -> None:
        with connect(self.database_path) as connection:
            dataset = connection.execute(
                "SELECT payload_json FROM business_datasets WHERE data_reference = ?",
                ("DS-ORDERS-2026Q2",),
            ).fetchone()
            rows = json.loads(dataset["payload_json"])
            del rows[0]["unit_price"]
            connection.execute(
                "UPDATE business_datasets SET payload_json = ? WHERE data_reference = ?",
                (json.dumps(rows), "DS-ORDERS-2026Q2"),
            )

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "EXECUTION_CONFIGURATION_INVALID")
        self.assertIn("unit_price", response.message)

    def test_unavailable_registered_implementation_is_blocked_and_traced(self) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                "UPDATE capabilities SET implementation_ref = ? WHERE capability_code = ?",
                ("company.unavailable.Executor", "CAP-ORDER-RANGE-PY"),
            )

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "EXECUTION_CONFIGURATION_INVALID")
        self.assertIsNotNone(self.engine.get_record(response.trace_id))

    def test_local_l1_7_seed_initialization_is_idempotent(self) -> None:
        initialize_database(self.database_path)
        initialize_database(self.database_path)

        response = self.engine.execute(self.order_request())

        self.assertEqual(response.versions.capability_code, "CAP-ORDER-RANGE-PY")

    def _insert_order_capability(self, capability_code: str, status: str) -> None:
        with connect(self.database_path) as connection:
            connection.execute(
                """INSERT INTO capabilities
                   (capability_code, scenario, capability_type, implementation_ref, capability_version,
                    status, owner, required_action, validation_ref, input_schema_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    capability_code,
                    "order_range_audit",
                    "fixed_python",
                    "app.executors.OrderRangeAuditExecutor",
                    "1.0.0",
                    status,
                    "business-rule-owner",
                    "rule.calculate.order_range",
                    "order_range_audit_v1",
                    json.dumps({"required_fields": ["order_id", "product_type", "unit_price", "quantity"]}),
                ),
            )


if __name__ == "__main__":
    unittest.main()
