from __future__ import annotations

import tempfile
import unittest
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import connect, initialize_database
from app.contracts import (
    CandidateImplementationReference,
    CandidateSkillTrialRequest,
    HumanAction,
    HumanHandlingRequest,
    ProcessingState,
)
from app.engine import RuleEngineService
from app.platform_instruction import PlatformInstructionService
from app.ports import ModelAnalysisRequest, ModelAnalysisResult


class PlatformInstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)
        self.service = PlatformInstructionService(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def instruction() -> dict:
        now = datetime.now(timezone.utc)
        return {
            "protocol_version": "1.0",
            "message_id": "msg-rule-001",
            "trace_id": "trace-rule-001",
            "request_id": "request-rule-001",
            "parent_message_id": "msg-flow-001",
            "occurred_at": now.isoformat(),
            "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
            "target": {"layer": "L2", "service_code": "l2.rule_calculation"},
            "channel": "l2_internal",
            "action": "rule.calculate",
            "request_type": "execute",
            "actor": {
                "person_id": "business_operator",
                "position_ids": ["position_finance"],
                "tenant_id": "tenant-test",
            },
            "context": {
                "identity_context_ref": "ctx-business-operator",
                "task_id": "task-rule-001",
                "data_refs": [
                    {
                        "ref_id": "DS-RECEIVABLES-2026Q2",
                        "source_system": "platform-test-data",
                        "resource_type": "receivables",
                        "resource_ids": ["2026-Q2"],
                        "version": "snapshot-1",
                        "data_labels": ["internal", "financial"],
                        "allowed_actions": ["read_for_rule_calculation"],
                    }
                ],
            },
            "idempotency_key": "idem-rule-001",
            "deadline_at": (now + timedelta(minutes=1)).isoformat(),
            "payload": {"business_type": "bad_debt_provision"},
        }

    def test_standard_instruction_is_converted_and_accepted(self) -> None:
        reply = self.service.handle(self.instruction())

        self.assertEqual(reply["reply_type"], "accepted")
        self.assertEqual(reply["result"]["state"], "waiting_human")
        self.assertEqual(reply["result"]["handling_type"], "confirm_effective")
        self.assertTrue(reply["result"]["task_id"].startswith("EXE-"))

    def test_flow_standard_action_uses_verified_actor_when_no_private_identity_ref_is_present(self) -> None:
        instruction = self.instruction()
        instruction["action"] = "rule.evaluate"
        del instruction["context"]["identity_context_ref"]

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "accepted")
        self.assertEqual(reply["result"]["handling_type"], "confirm_effective")

    def test_initial_evaluation_returns_bounded_query_requirements_before_data_is_ready(self) -> None:
        instruction = self.instruction()
        instruction["action"] = "rule.evaluate"
        instruction["message_id"] = "msg-precondition-001"
        instruction["idempotency_key"] = "idem-precondition-001"
        instruction["context"].pop("identity_context_ref")
        instruction["context"]["data_refs"] = []

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "success")
        assessment = reply["result"]["data"]
        self.assertEqual(assessment["state"], "precondition_query_required")
        self.assertEqual(
            {item["query_type"] for item in assessment["query_requirements"]},
            {
                "formal_calculation_basis",
                "published_calculation_capability",
                "authorized_business_data",
            },
        )
        with connect(self.database_path) as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM execution_records").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_flow_can_apply_for_candidate_skill_and_resume_candidate_trial(self) -> None:
        instruction = self.instruction()
        instruction.update(
            {
                "action": "rule.evaluate",
                "message_id": "msg-flow-sandbox-001",
                "trace_id": "trace-flow-sandbox-001",
                "request_id": "request-flow-sandbox-001",
                "idempotency_key": "idem-flow-sandbox-001",
            }
        )
        instruction["context"].pop("identity_context_ref")
        instruction["context"]["data_refs"][0]["ref_id"] = "DS-MARGIN-TEST"
        instruction["payload"] = {
            "business_type": "temporary_margin_analysis",
            "temporary_analysis_spec": {
                "objective": "Calculate temporary revenue and gross-profit impact.",
                "input_schema": {"required_fields": ["baseline_revenue"]},
                "output_schema": {
                    "required_fields": ["adjusted_revenue", "gross_profit_change"]
                },
                "assumptions": ["The requester confirmed the scenario variables."],
            },
        }
        authorization = self.service.handle(instruction)
        authorization_id = authorization["result"]["task_id"]

        application = deepcopy(instruction)
        application.update(
            {
                "action": "rule.candidate_skill_apply",
                "message_id": "msg-flow-apply-001",
                "idempotency_key": "idem-flow-apply-001",
            }
        )
        application["payload"] = {
            "execution_record_id": authorization_id,
            "human_action": "approve",
            "comment": "The requester authorizes a candidate Skill application.",
        }
        application["context"]["data_refs"] = []
        applied = self.service.handle(application)

        self.assertEqual(applied["reply_type"], "success")
        creation = applied["result"]["data"]["candidate_skill_creation_request"]
        self.assertEqual(creation["authorization_execution_record_id"], authorization_id)
        self.assertEqual(creation["candidate_request_id"], f"CSR-{authorization_id}")

        trial = deepcopy(application)
        trial.update(
            {
                "action": "rule.candidate_trial",
                "message_id": "msg-flow-trial-001",
                "idempotency_key": "idem-flow-trial-001",
            }
        )
        trial["payload"] = {
            "execution_record_id": authorization_id,
            "candidate_implementation": {
                "candidate_request_id": creation["candidate_request_id"],
                "artifact_ref": "asset://candidate-skill/FLOW-001",
                "artifact_version": "candidate-1",
                "source": "digital-asset-engine:integration-simulator",
                "code_digest": "flow-test-candidate-digest",
                "entrypoint": "calculate",
                "generation_id": "GEN-FLOW-001",
                "candidate_only": True,
            },
        }
        resumed = self.service.handle(trial)

        self.assertEqual(resumed["reply_type"], "accepted")
        self.assertEqual(resumed["result"]["handling_type"], "review_sandbox_result")

    def test_flow_task_fields_reach_model_without_business_type(self) -> None:
        class CapturingAnalyzer:
            def __init__(self) -> None:
                self.received: list[ModelAnalysisRequest] = []

            def analyze(self, request: ModelAnalysisRequest) -> ModelAnalysisResult:
                self.received.append(request)
                return ModelAnalysisResult(
                    analysis_id="MRA-PLATFORM-001",
                    model_service="model-test-double",
                    model_version="test-1",
                    recommended_path="deterministic",
                    candidate_capability_code="CAP-BAD-DEBT-PY",
                    extracted_parameters={},
                    missing_items=[],
                    rationale="The task matches the registered bad-debt capability.",
                    confidence=0.9,
                )

        analyzer = CapturingAnalyzer()
        service = PlatformInstructionService(
            self.database_path,
            engine=RuleEngineService(
                self.database_path, model_analysis_gateway=analyzer
            ),
        )
        instruction = self.instruction()
        instruction["context"].update(
            {
                "subtask_id": "subtask-rule-001",
                "requester_id": "business_operator",
            }
        )
        instruction["payload"] = {
            "node_name": "Bad debt provision calculation",
            "task": "Calculate bad debt provision for the referenced receivables.",
            "service_ref": "L2.rule_engine.bad_debt_provision",
        }

        reply = service.handle(instruction)

        self.assertEqual(reply["reply_type"], "accepted")
        received = analyzer.received[0]
        self.assertEqual(received.task_id, "task-rule-001")
        self.assertEqual(received.subtask_id, "subtask-rule-001")
        self.assertEqual(received.requester_id, "business_operator")
        self.assertEqual(received.node_name, "Bad debt provision calculation")
        self.assertEqual(
            received.task,
            "Calculate bad debt provision for the referenced receivables.",
        )
        self.assertEqual(
            received.service_ref, "L2.rule_engine.bad_debt_provision"
        )
        self.assertIsNone(received.legacy_business_type)

    def test_standard_instruction_can_reach_existing_system_path(self) -> None:
        instruction = self.instruction()
        instruction["message_id"] = "msg-external-payroll-001"
        instruction["trace_id"] = "trace-external-payroll-001"
        instruction["request_id"] = "request-external-payroll-001"
        instruction["idempotency_key"] = "idem-external-payroll-001"
        instruction["payload"] = {
            "business_type": "external_payroll_calculation",
            "business_object_ref": "ORG-001",
            "period": "2026-06",
        }
        instruction["context"]["data_refs"] = [
            {
                "ref_id": "FIN-PAYROLL-2026-06",
                "source_system": "finance-system",
                "resource_type": "payroll_input",
                "resource_ids": ["2026-06"],
                "version": "payroll-data-2026-06-v1",
                "data_labels": ["internal", "financial"],
                "allowed_actions": ["read_for_rule_calculation"],
            }
        ]

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "success")
        data = reply["result"]["data"]
        self.assertEqual(data["execution_path"], "existing_system")
        self.assertEqual(data["existing_system_reference"]["system_code"], "finance-system")
        self.assertEqual(data["result"]["net_payroll"], "30800.00")

    def test_standard_instruction_preserves_path_three_analysis_spec(self) -> None:
        instruction = self.instruction()
        instruction["message_id"] = "msg-sandbox-001"
        instruction["trace_id"] = "trace-sandbox-001"
        instruction["request_id"] = "request-sandbox-001"
        instruction["idempotency_key"] = "idem-sandbox-001"
        instruction["payload"] = {
            "business_type": "temporary_margin_analysis",
            "temporary_analysis_spec": {
                "objective": "Calculate temporary revenue and gross-profit impact.",
                "input_schema": {"required_fields": ["baseline_revenue"]},
                "output_schema": {
                    "required_fields": ["adjusted_revenue", "gross_profit_change"]
                },
                "assumptions": ["The requester confirmed the scenario variables."],
            },
        }
        instruction["context"]["data_refs"][0]["ref_id"] = "DS-MARGIN-TEST"

        reply = self.service.handle(instruction)
        authorization_id = reply["result"]["task_id"]
        outcome = RuleEngineService(self.database_path).handle_waiting_result(
            authorization_id,
            HumanHandlingRequest(
                identity_context_ref="ctx-business-operator",
                action=HumanAction.APPROVE,
                comment="Temporary AI generation and controlled execution are authorized.",
            ),
        )

        self.assertEqual(outcome.state, ProcessingState.AUTOMATIC_PASS)
        self.assertEqual(outcome.reason_code, "AI_GENERATION_AUTHORIZED")
        self.assertIsNotNone(outcome.candidate_skill_creation_request)
        creation = outcome.candidate_skill_creation_request

        trial = RuleEngineService(self.database_path).resume_candidate_skill_trial(
            authorization_id,
            CandidateSkillTrialRequest(
                identity_context_ref="ctx-business-operator",
                candidate_implementation=CandidateImplementationReference(
                    candidate_request_id=creation.candidate_request_id,
                    artifact_ref="asset://candidate-skill/PLATFORM-001",
                    artifact_version="candidate-1",
                    source="digital-asset-engine:integration-simulator",
                    code_digest="platform-test-candidate-digest",
                    entrypoint="calculate",
                    generation_id="GEN-PLATFORM-001",
                    candidate_only=True,
                ),
            ),
        )
        self.assertEqual(trial.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(trial.reason_code, "SANDBOX_RESULT_REVIEW_REQUIRED")

    def test_idempotent_replay_returns_same_execution_without_recalculation(self) -> None:
        first_request = self.instruction()
        first = self.service.handle(first_request)
        replay_request = deepcopy(first_request)
        replay_request["message_id"] = "msg-rule-replay-002"
        second = self.service.handle(replay_request)

        self.assertEqual(first["result"]["task_id"], second["result"]["task_id"])
        self.assertEqual(second["in_reply_to"], "msg-rule-replay-002")
        with connect(self.database_path) as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM execution_records").fetchone()["count"]
        self.assertEqual(count, 1)

    def test_same_idempotency_key_with_changed_payload_is_rejected(self) -> None:
        first_request = self.instruction()
        self.service.handle(first_request)
        changed = deepcopy(first_request)
        changed["message_id"] = "msg-rule-conflict-002"
        changed["payload"]["business_type"] = "order_range_audit"

        reply = self.service.handle(changed)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "idempotency_conflict")

    def test_expired_deadline_returns_timeout_without_creating_execution(self) -> None:
        instruction = self.instruction()
        instruction["deadline_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "timeout")
        with connect(self.database_path) as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM execution_records").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_calculation_reference_time_requires_timezone(self) -> None:
        instruction = self.instruction()
        instruction["payload"]["calculation_as_of"] = "2026-07-15T00:00:00"

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "invalid_message")

    def test_platform_calculation_time_reaches_rule_effectiveness_check(self) -> None:
        instruction = self.instruction()
        instruction["payload"]["calculation_as_of"] = "2026-07-14T23:59:00+00:00"

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "RULE_NOT_EFFECTIVE_AT_CALCULATION_TIME")

    def test_business_object_and_period_can_be_resolved_from_data_reference(self) -> None:
        instruction = self.instruction()
        self.assertNotIn("business_object_ref", instruction["payload"])
        self.assertNotIn("period", instruction["payload"])

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "accepted")

    def test_declared_actor_must_match_l1_8_identity_resolution(self) -> None:
        instruction = self.instruction()
        instruction["actor"]["person_id"] = "forged_person"

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "ACTOR_IDENTITY_MISMATCH")
        with connect(self.database_path) as connection:
            record = connection.execute(
                "SELECT claimed_actor_id, operator_id FROM execution_records"
            ).fetchone()
        self.assertEqual(record["claimed_actor_id"], "forged_person")
        self.assertEqual(record["operator_id"], "business_operator")

    def test_multiple_data_refs_select_explicit_calculation_input_and_trace_all_refs(self) -> None:
        instruction = self.instruction()
        calculation_input = instruction["context"]["data_refs"][0]
        calculation_input["purpose"] = "calculation_input"
        instruction["context"]["data_refs"] = [
            {
                "ref_id": "RULE-PARAMETERS-001",
                "purpose": "rule_parameter",
                "version": "PARAM-BAD-DEBT-2026Q2-1.0",
                "data_labels": ["internal"],
                "allowed_actions": ["read_rule_parameters"],
            },
            calculation_input,
        ]

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "accepted")
        with connect(self.database_path) as connection:
            record = connection.execute(
                "SELECT data_reference, request_data_references_json FROM execution_records"
            ).fetchone()
        self.assertEqual(record["data_reference"], "DS-RECEIVABLES-2026Q2")
        references = json.loads(record["request_data_references_json"])
        self.assertEqual({item["reference_id"] for item in references}, {"RULE-PARAMETERS-001", "DS-RECEIVABLES-2026Q2"})

    def test_rule_parameter_reference_cannot_override_locked_parameter_version(self) -> None:
        instruction = self.instruction()
        instruction["context"]["data_refs"][0]["purpose"] = "calculation_input"
        instruction["context"]["data_refs"].append(
            {
                "ref_id": "RULE-PARAMETERS-UNAPPROVED",
                "purpose": "rule_parameter",
                "version": "PARAM-UNAPPROVED-9.9",
            }
        )

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "PARAMETER_VERSION_MISMATCH")

    def test_rule_parameter_reference_requires_version(self) -> None:
        instruction = self.instruction()
        instruction["context"]["data_refs"][0]["purpose"] = "calculation_input"
        instruction["context"]["data_refs"].append(
            {"ref_id": "RULE-PARAMETERS-NO-VERSION", "purpose": "rule_parameter"}
        )

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "PARAMETER_REFERENCE_VERSION_REQUIRED")

    def test_multiple_rule_parameter_references_are_rejected(self) -> None:
        instruction = self.instruction()
        instruction["context"]["data_refs"][0]["purpose"] = "calculation_input"
        instruction["context"]["data_refs"].extend(
            [
                {
                    "ref_id": "RULE-PARAMETERS-001",
                    "purpose": "rule_parameter",
                    "version": "PARAM-BAD-DEBT-2026Q2-1.0",
                },
                {
                    "ref_id": "RULE-PARAMETERS-002",
                    "purpose": "rule_parameter",
                    "version": "PARAM-BAD-DEBT-2026Q2-1.0",
                },
            ]
        )

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "AMBIGUOUS_PARAMETER_REFERENCE")

    def test_multiple_data_refs_without_explicit_calculation_input_are_rejected(self) -> None:
        instruction = self.instruction()
        instruction["context"]["data_refs"].append(
            {"ref_id": "VALIDATION-001", "purpose": "validation_reference"}
        )

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "invalid_message")

    def test_multiple_calculation_inputs_are_rejected(self) -> None:
        instruction = self.instruction()
        instruction["context"]["data_refs"][0]["purpose"] = "calculation_input"
        instruction["context"]["data_refs"].append(
            {"ref_id": "DATASET-SECOND", "purpose": "calculation_input"}
        )

        reply = self.service.handle(instruction)

        self.assertEqual(reply["reply_type"], "failed")
        self.assertEqual(reply["error"]["code"], "invalid_message")


if __name__ == "__main__":
    unittest.main()
