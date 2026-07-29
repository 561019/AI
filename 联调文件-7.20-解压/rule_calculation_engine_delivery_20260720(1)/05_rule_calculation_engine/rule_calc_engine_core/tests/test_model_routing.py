from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.contracts import ExecutionPath, ExecutionRequest, ProcessingState
from app.database import initialize_database
from app.engine import RuleEngineService
from app.ports import ModelAnalysisRequest, ModelAnalysisResult


class FixedModelAnalyzer:
    def __init__(
        self,
        *,
        candidate_capability_code: str | None,
        recommended_path: str,
        extracted_parameters: dict | None = None,
        missing_items: list[str] | None = None,
    ) -> None:
        self.candidate_capability_code = candidate_capability_code
        self.recommended_path = recommended_path
        self.extracted_parameters = extracted_parameters or {}
        self.missing_items = missing_items or []
        self.received: list[ModelAnalysisRequest] = []

    def analyze(self, request: ModelAnalysisRequest) -> ModelAnalysisResult:
        self.received.append(request)
        return ModelAnalysisResult(
            analysis_id="MRA-TEST-0001",
            model_service="l1.5-test-double",
            model_version="test-1",
            recommended_path=self.recommended_path,
            candidate_capability_code=self.candidate_capability_code,
            extracted_parameters={"task": request.task, **self.extracted_parameters},
            missing_items=list(self.missing_items),
            rationale="Test routing recommendation.",
            confidence=0.88,
        )


class ModelAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def order_request(**overrides: object) -> ExecutionRequest:
        payload = {
            "trace_id": "TRC-MODEL-ROUTING-0001",
            "request_id": "REQ-MODEL-ROUTING-0001",
            "identity_context_ref": "ctx-business-operator",
            "business_type": "order_range_audit",
            "requested_capability_code": "CAP-ORDER-RANGE-PY",
            "business_object_id": "ORG-001",
            "period": "2026-Q2",
            "data_reference": "DS-ORDERS-2026Q2",
        }
        payload.update(overrides)
        return ExecutionRequest(**payload)

    def test_every_valid_request_calls_model_router_and_persists_decision(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code="CAP-ORDER-RANGE-PY",
            recommended_path="deterministic",
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(self.order_request())

        self.assertEqual(len(analyzer.received), 1)
        self.assertEqual(
            analyzer.received[0].requested_capability_code, "CAP-ORDER-RANGE-PY"
        )
        self.assertGreater(len(analyzer.received[0].candidate_capabilities), 0)
        self.assertEqual(response.execution_path, ExecutionPath.DETERMINISTIC)
        self.assertTrue(response.routing_decision.accepted_model_recommendation)
        self.assertEqual(
            response.routing_decision.decision_code,
            "MODEL_RECOMMENDATION_VALIDATED",
        )

        record = engine.execution_records.get_by_id(response.execution_record_id)
        persisted_analysis = json.loads(record["model_analysis_json"])
        persisted_decision = json.loads(record["routing_decision_json"])
        self.assertEqual(persisted_analysis["analysis_id"], "MRA-TEST-0001")
        self.assertEqual(
            persisted_decision["selected_capability_code"], "CAP-ORDER-RANGE-PY"
        )

    def test_model_router_unavailable_blocks_before_calculation(self) -> None:
        class UnavailableRouter:
            def analyze(self, request: ModelAnalysisRequest) -> ModelAnalysisResult:
                raise TimeoutError("L1.5 timeout")

        engine = RuleEngineService(
            self.database_path, model_analysis_gateway=UnavailableRouter()
        )

        response = engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "MODEL_ANALYSIS_UNAVAILABLE")
        self.assertIsNone(response.result)
        self.assertFalse(response.routing_decision.accepted_model_recommendation)

    def test_invalid_model_response_blocks_before_calculation(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code="CAP-ORDER-RANGE-PY",
            recommended_path="model_calculated_result",
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "MODEL_ANALYSIS_UNAVAILABLE")
        self.assertIsNone(response.result)
        self.assertFalse(response.routing_decision.accepted_model_recommendation)

    def test_local_simulator_does_not_guess_an_unclassified_task(self) -> None:
        engine = RuleEngineService(self.database_path)

        response = engine.execute(
            self.order_request(
                business_type=None,
                requested_capability_code=None,
                task="Calculate the requested value using the applicable company rule.",
            )
        )

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "MODEL_ANALYSIS_UNAVAILABLE")
        self.assertIsNone(response.result)

    def test_unregistered_model_candidate_is_rejected_by_catalogue(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code="CAP-MODEL-HALLUCINATION",
            recommended_path="deterministic",
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(
            response.reason_code, "MODEL_RECOMMENDED_CAPABILITY_NOT_REGISTERED"
        )
        self.assertFalse(response.routing_decision.accepted_model_recommendation)

    def test_model_path_conflict_is_rejected_by_registered_capability_type(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code="CAP-ORDER-RANGE-PY",
            recommended_path="sandbox",
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(self.order_request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "MODEL_PATH_CAPABILITY_CONFLICT")
        self.assertEqual(
            response.routing_decision.selected_path, ExecutionPath.DETERMINISTIC
        )
        self.assertFalse(response.routing_decision.accepted_model_recommendation)

    def test_raw_flow_task_fields_reach_model_without_business_type(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code="CAP-ORDER-RANGE-PY",
            recommended_path="deterministic",
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(
            self.order_request(
                business_type=None,
                task_id="FLOW-TASK-001",
                subtask_id="FLOW-SUBTASK-003",
                requester_id="business_operator",
                node_name="订单价格与数量审核",
                task="检查本批订单价格和数量是否符合公司现行规则。",
                service_ref="L2.rule_engine.order_range_audit",
            )
        )

        self.assertEqual(response.execution_path, ExecutionPath.DETERMINISTIC)
        received = analyzer.received[0]
        self.assertEqual(received.task_id, "FLOW-TASK-001")
        self.assertEqual(received.subtask_id, "FLOW-SUBTASK-003")
        self.assertEqual(received.requester_id, "business_operator")
        self.assertEqual(received.node_name, "订单价格与数量审核")
        self.assertEqual(received.task, "检查本批订单价格和数量是否符合公司现行规则。")
        self.assertEqual(
            received.service_ref, "L2.rule_engine.order_range_audit"
        )
        self.assertIsNone(received.legacy_business_type)
        record = engine.execution_records.get_by_id(response.execution_record_id)
        request_context = json.loads(record["request_context_json"])
        persisted_analysis = json.loads(record["model_analysis_json"])
        persisted_decision = json.loads(record["routing_decision_json"])
        self.assertEqual(request_context["task"], received.task)
        self.assertEqual(persisted_analysis["analysis_id"], "MRA-TEST-0001")
        self.assertEqual(
            persisted_decision["selected_capability_code"],
            "CAP-ORDER-RANGE-PY",
        )

    def test_existing_system_path_does_not_require_business_type(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code="CAP-EXTERNAL-PAYROLL",
            recommended_path="existing_system",
            extracted_parameters={"period": "2026-06"},
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)
        request = ExecutionRequest(
            trace_id="TRC-MODEL-EXTERNAL-0001",
            request_id="REQ-MODEL-EXTERNAL-0001",
            task_id="FLOW-TASK-EXTERNAL-001",
            subtask_id="FLOW-SUBTASK-EXTERNAL-001",
            requester_id="business_operator",
            node_name="Obtain existing payroll calculation",
            task="Obtain the June payroll result already calculated by the existing system.",
            service_ref="L2.rule_engine.existing_payroll_result",
            identity_context_ref="ctx-business-operator",
            business_object_id="ORG-001",
            period="2026-06",
            data_reference="FIN-PAYROLL-2026-06",
        )

        response = engine.execute(request)

        self.assertEqual(response.state, ProcessingState.AUTOMATIC_PASS)
        self.assertEqual(response.execution_path, ExecutionPath.EXISTING_SYSTEM)
        self.assertEqual(
            response.routing_decision.selected_capability_code,
            "CAP-EXTERNAL-PAYROLL",
        )
        self.assertEqual(response.result["net_payroll"], "30800.00")

    def test_sandbox_path_does_not_require_business_type(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code=None,
            recommended_path="sandbox",
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(
            ExecutionRequest(
                trace_id="TRC-MODEL-SANDBOX-0001",
                request_id="REQ-MODEL-SANDBOX-0001",
                task_id="FLOW-TASK-SANDBOX-001",
                subtask_id="FLOW-SUBTASK-SANDBOX-001",
                requester_id="business_operator",
                node_name="Temporary margin analysis",
                task="Analyze a temporary margin scenario not covered by a formal capability.",
                service_ref="L2.rule_engine.temporary_analysis",
                identity_context_ref="ctx-business-operator",
                data_reference="DS-MARGIN-TEST",
                temporary_analysis_spec={
                    "objective": "Calculate temporary margin impact.",
                    "input_schema": {"required_fields": ["baseline_revenue"]},
                    "output_schema": {
                        "required_fields": [
                            "adjusted_revenue",
                            "gross_profit_change",
                        ]
                    },
                },
            )
        )

        self.assertEqual(response.state, ProcessingState.WAITING_HUMAN)
        self.assertEqual(response.execution_path, ExecutionPath.SANDBOX)
        self.assertEqual(response.reason_code, "AI_GENERATION_AUTHORIZATION_REQUIRED")
        self.assertEqual(
            response.routing_decision.decision_code,
            "NO_FORMAL_CAPABILITY_CONFIRMED",
        )

    def test_model_reported_missing_items_block_before_execution(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code="CAP-ORDER-RANGE-PY",
            recommended_path="deterministic",
            missing_items=["calculation_period"],
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(
            self.order_request(
                business_type=None,
                task="Audit order prices and quantities for the requested period.",
            )
        )

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "MODEL_ANALYSIS_INCOMPLETE")
        self.assertIsNone(response.result)
        self.assertEqual(response.model_analysis.missing_items, ["calculation_period"])

    def test_model_cannot_ignore_explicit_published_capability(self) -> None:
        analyzer = FixedModelAnalyzer(
            candidate_capability_code=None,
            recommended_path="sandbox",
        )
        engine = RuleEngineService(self.database_path, model_analysis_gateway=analyzer)

        response = engine.execute(
            self.order_request(
                business_type=None,
                task="Audit order prices and quantities with the requested capability.",
            )
        )

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(
            response.reason_code,
            "MODEL_IGNORED_EXPLICIT_CAPABILITY",
        )
        self.assertIsNone(response.result)


if __name__ == "__main__":
    unittest.main()
