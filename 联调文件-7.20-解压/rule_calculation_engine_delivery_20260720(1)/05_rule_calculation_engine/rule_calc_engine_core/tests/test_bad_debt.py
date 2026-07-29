from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.contracts import (
    ExecutionRequest,
    HandlingType,
    HumanAction,
    HumanHandlingRequest,
    ProcessingState,
    RuleVersionAction,
    RuleVersionDraftRequest,
    RuleVersionStatus,
    RuleVersionTransitionRequest,
)
from app.database import BAD_DEBT_RULE, connect, initialize_database
from app.engine import RuleEngineService
from app.ports import AdapterDecision, IdentityResolution


class BadDebtProvisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)
        self.engine = RuleEngineService(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def request(self, **overrides: object) -> ExecutionRequest:
        payload = {
            "trace_id": "TRC-BAD-DEBT-0001",
            "request_id": "REQ-BAD-DEBT-0001",
            "identity_context_ref": "ctx-business-operator",
            "business_type": "bad_debt_provision",
            "business_object_id": "ORG-001",
            "period": "2026-Q2",
            "data_reference": "DS-RECEIVABLES-2026Q2",
        }
        payload.update(overrides)
        return ExecutionRequest(**payload)

    def test_published_capability_calculates_and_waits_for_human_confirmation(self) -> None:
        response = self.engine.execute(self.request())

        self.assertEqual(response.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(response.reason_code, "KEY_BUSINESS_RESULT")
        self.assertEqual(response.result["total_provision"], "37200.00")
        self.assertEqual(len(response.result["lines"]), 4)
        self.assertTrue(all(item.passed for item in response.validation))
        self.assertEqual(response.versions.capability_code, "CAP-BAD-DEBT-PY")

    def test_unauthorized_operator_is_blocked_before_data_read_or_calculation(self) -> None:
        response = self.engine.execute(self.request(identity_context_ref="ctx-unauthorized-user"))

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "PERMISSION_DENIED")
        self.assertIsNone(response.result)

    def test_missing_data_reference_is_blocked(self) -> None:
        response = self.engine.execute(self.request(data_reference="DS-UNKNOWN"))

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "DATA_NOT_FOUND")

    def test_execution_record_can_be_queried_by_trace_id(self) -> None:
        response = self.engine.execute(self.request())
        record = self.engine.get_record(response.trace_id)

        self.assertEqual(record["execution_record_id"], response.execution_record_id)
        self.assertEqual(record["state"], ProcessingState.WAITING_HUMAN.value)

    def test_human_confirmation_makes_a_waiting_result_effective(self) -> None:
        execution = self.engine.execute(self.request())
        outcome = self.engine.handle_waiting_result(
            execution.execution_record_id,
            HumanHandlingRequest(
                identity_context_ref="ctx-designated-reviewer",
                action=HumanAction.APPROVE,
                comment="The provision basis and result have been reviewed.",
            ),
        )

        self.assertEqual(outcome.state, ProcessingState.AUTOMATIC_PASS)
        record = self.engine.get_record(execution.trace_id)
        self.assertEqual(record["state"], ProcessingState.AUTOMATIC_PASS.value)

    def test_same_waiting_result_cannot_be_handled_twice(self) -> None:
        execution = self.engine.execute(self.request())
        handling = HumanHandlingRequest(
            identity_context_ref="ctx-designated-reviewer",
            action=HumanAction.APPROVE,
            comment="Confirmed.",
        )
        self.engine.handle_waiting_result(execution.execution_record_id, handling)

        with self.assertRaises(ValueError):
            self.engine.handle_waiting_result(execution.execution_record_id, handling)

    def test_unqualified_handler_cannot_confirm_the_result(self) -> None:
        execution = self.engine.execute(self.request())

        with self.assertRaises(PermissionError):
            self.engine.handle_waiting_result(
                execution.execution_record_id,
                HumanHandlingRequest(
                    identity_context_ref="ctx-business-operator",
                    action=HumanAction.APPROVE,
                    comment="Attempting confirmation without handling permission.",
                ),
            )

    def test_only_a_published_version_is_used_and_old_version_is_retained(self) -> None:
        draft = self.engine.create_rule_version_draft(
            RuleVersionDraftRequest(
                capability_code="CAP-BAD-DEBT-PY",
                rule_version="RULE-BAD-DEBT-1.1",
                parameter_version="PARAM-BAD-DEBT-2026Q2-1.1",
                treatment_rule_version="TREAT-BAD-DEBT-1.1",
                payload=BAD_DEBT_RULE,
                source_basis="Approved bad debt policy revision notice.",
                review_role="designated_reviewer",
                identity_context_ref="ctx-dsm-operator",
            )
        )
        self.assertEqual(draft.status, RuleVersionStatus.DRAFT)
        before_publish = self.engine.execute(self.request())
        self.assertEqual(before_publish.versions.rule_version, "RULE-BAD-DEBT-1.0")

        testing = self.engine.transition_rule_version(
            draft.rule_version_id,
            RuleVersionTransitionRequest(
                identity_context_ref="ctx-rule-engineer", action=RuleVersionAction.START_TESTING, comment="Technical test started.",
            ),
        )
        self.assertEqual(testing.status, RuleVersionStatus.TESTING)
        pending_review = self.engine.transition_rule_version(
            draft.rule_version_id,
            RuleVersionTransitionRequest(
                identity_context_ref="ctx-rule-engineer", action=RuleVersionAction.SUBMIT_REVIEW, comment="Test passed; submitted for review.",
            ),
        )
        self.assertEqual(pending_review.status, RuleVersionStatus.PENDING_REVIEW)
        published = self.engine.transition_rule_version(
            draft.rule_version_id,
            RuleVersionTransitionRequest(
                identity_context_ref="ctx-designated-reviewer", action=RuleVersionAction.APPROVE_PUBLISH,
                comment="Approved under the designated review role.",
            ),
        )
        self.assertEqual(published.status, RuleVersionStatus.PUBLISHED)
        self.assertEqual(published.reviewed_by, "designated_reviewer")

        after_publish = self.engine.execute(self.request(trace_id="TRC-BAD-DEBT-0002", request_id="REQ-BAD-DEBT-0002"))
        self.assertEqual(after_publish.versions.rule_version, "RULE-BAD-DEBT-1.1")
        with connect(self.database_path) as connection:
            old_status = connection.execute(
                "SELECT status FROM rule_versions WHERE rule_version = ?", ("RULE-BAD-DEBT-1.0",)
            ).fetchone()["status"]
        self.assertEqual(old_status, RuleVersionStatus.RETIRED.value)

    def test_unknown_identity_context_is_blocked_and_not_trusted_as_an_actor(self) -> None:
        response = self.engine.execute(self.request(identity_context_ref="ctx-forged-actor"))

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "IDENTITY_CONTEXT_INVALID")
        record = self.engine.get_record(response.trace_id)
        self.assertEqual(record["operator_id"], "unresolved")
        self.assertIsNone(record["identity_verification_id"])

    def test_execution_record_stores_identity_evidence_without_raw_context(self) -> None:
        request = self.request()
        response = self.engine.execute(request)
        record = self.engine.get_record(response.trace_id)

        self.assertEqual(record["operator_id"], "business_operator")
        self.assertTrue(record["identity_verification_id"].startswith("IDV-"))
        self.assertNotEqual(record["identity_context_digest"], request.identity_context_ref)

    def test_platform_ports_can_replace_local_identity_and_permission_adapters(self) -> None:
        class StubIdentityGateway:
            called = False

            def resolve(self, identity_context_ref: str, trace_id: str) -> IdentityResolution:
                self.called = True
                return IdentityResolution(
                    passed=True,
                    detail="Resolved by test identity gateway.",
                    actor_id="business_operator",
                    verification_id="IDV-EXTERNAL-TEST",
                )

        class DenyPermissionGateway:
            def check(
                self,
                operator_id: str,
                action: str,
                data_reference: str,
                data_labels: list[str] | None = None,
                allowed_data_actions: list[str] | None = None,
            ) -> AdapterDecision:
                return AdapterDecision(False, "Denied by test permission gateway.", "EXTERNAL_PERMISSION_DENIED")

        identity = StubIdentityGateway()
        engine = RuleEngineService(
            self.database_path,
            identity=identity,
            permission=DenyPermissionGateway(),
        )
        response = engine.execute(self.request())

        self.assertTrue(identity.called)
        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "EXTERNAL_PERMISSION_DENIED")

    def test_data_labels_and_allowed_actions_reach_permission_gateway(self) -> None:
        class CapturingPermissionGateway:
            labels: list[str] | None = None
            actions: list[str] | None = None

            def check(
                self,
                operator_id: str,
                action: str,
                data_reference: str,
                data_labels: list[str] | None = None,
                allowed_data_actions: list[str] | None = None,
            ) -> AdapterDecision:
                self.labels = data_labels
                self.actions = allowed_data_actions
                return AdapterDecision(True, "Allowed by capturing gateway.")

        permission = CapturingPermissionGateway()
        engine = RuleEngineService(self.database_path, permission=permission)
        response = engine.execute(
            self.request(
                data_labels=["internal", "financial"],
                allowed_data_actions=["read_for_rule_calculation"],
            )
        )

        self.assertEqual(response.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(permission.labels, ["internal", "financial"])
        self.assertEqual(permission.actions, ["read_for_rule_calculation"])


if __name__ == "__main__":
    unittest.main()
