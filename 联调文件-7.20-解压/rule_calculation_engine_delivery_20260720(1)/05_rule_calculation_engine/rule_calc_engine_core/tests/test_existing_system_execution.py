from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.contracts import ExecutionPath, ExecutionRequest, ProcessingState
from app.database import initialize_database
from app.engine import RuleEngineService
from app.ports import ExistingSystemCallRequest, ExistingSystemCallResult


class ExistingSystemExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def request(**overrides: object) -> ExecutionRequest:
        payload = {
            "trace_id": "TRC-EXTERNAL-PAYROLL-0001",
            "request_id": "REQ-EXTERNAL-PAYROLL-0001",
            "identity_context_ref": "ctx-business-operator",
            "business_type": "external_payroll_calculation",
            "business_object_id": "ORG-001",
            "period": "2026-06",
            "data_reference": "FIN-PAYROLL-2026-06",
        }
        payload.update(overrides)
        return ExecutionRequest(**payload)

    def test_registered_existing_system_capability_uses_second_path(self) -> None:
        engine = RuleEngineService(self.database_path)

        response = engine.execute(self.request())

        self.assertEqual(response.state, ProcessingState.AUTOMATIC_PASS)
        self.assertEqual(response.execution_path, ExecutionPath.EXISTING_SYSTEM)
        self.assertEqual(response.versions.capability_code, "CAP-EXTERNAL-PAYROLL")
        self.assertEqual(response.result["gross_payroll"], "36000.00")
        self.assertEqual(response.result["net_payroll"], "30800.00")
        self.assertEqual(response.existing_system_reference.system_code, "finance-system")
        self.assertEqual(response.existing_system_reference.service_version, "payroll-api-2.1")
        self.assertTrue(all(check.passed for check in response.validation))

    def test_internal_call_contract_is_passed_to_replaceable_adapter(self) -> None:
        class CapturingGateway:
            received: ExistingSystemCallRequest | None = None

            def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
                self.received = request
                return successful_result(request)

        gateway = CapturingGateway()
        engine = RuleEngineService(self.database_path, existing_system_gateway=gateway)

        response = engine.execute(self.request())

        self.assertEqual(response.state, ProcessingState.AUTOMATIC_PASS)
        self.assertIsNotNone(gateway.received)
        self.assertEqual(gateway.received.operation_ref, "finance-system.payroll.calculate")
        self.assertEqual(gateway.received.business_object_id, "ORG-001")
        self.assertEqual(gateway.received.period, "2026-06")
        self.assertEqual(gateway.received.invocation_config["contract_version"], "1.0")

    def test_required_call_context_is_checked_before_adapter_invocation(self) -> None:
        class UnexpectedGateway:
            def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
                raise AssertionError("The adapter must not be called for an invalid internal request.")

        engine = RuleEngineService(
            self.database_path, existing_system_gateway=UnexpectedGateway()
        )

        response = engine.execute(self.request(period=None))

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.execution_path, ExecutionPath.EXISTING_SYSTEM)
        self.assertEqual(response.reason_code, "EXISTING_SYSTEM_REQUEST_INVALID")

    def test_external_failure_is_blocked_with_adapter_reason(self) -> None:
        class FailedGateway:
            def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
                result = successful_result(request)
                return ExistingSystemCallResult(
                    succeeded=False,
                    detail="The external service rejected the call.",
                    reason_code="EXTERNAL_SERVICE_REJECTED",
                    invocation_id=result.invocation_id,
                    system_code=result.system_code,
                    operation_ref=result.operation_ref,
                    service_version=result.service_version,
                    returned_at=result.returned_at,
                    result={},
                    data_reference={},
                )

        engine = RuleEngineService(self.database_path, existing_system_gateway=FailedGateway())

        response = engine.execute(self.request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "EXTERNAL_SERVICE_REJECTED")
        self.assertEqual(response.execution_path, ExecutionPath.EXISTING_SYSTEM)
        self.assertIsNotNone(response.existing_system_reference)

    def test_invalid_external_result_is_blocked_by_registered_validator(self) -> None:
        class InvalidResultGateway:
            def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
                result = successful_result(request)
                return ExistingSystemCallResult(
                    succeeded=True,
                    detail=result.detail,
                    invocation_id=result.invocation_id,
                    system_code=result.system_code,
                    operation_ref=result.operation_ref,
                    service_version=result.service_version,
                    returned_at=result.returned_at,
                    result={"employee_count": 3},
                    data_reference=result.data_reference,
                )

        engine = RuleEngineService(
            self.database_path, existing_system_gateway=InvalidResultGateway()
        )

        response = engine.execute(self.request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "RESULT_VALIDATION_FAILED")
        self.assertFalse(all(check.passed for check in response.validation))

    def test_response_from_unregistered_system_is_blocked(self) -> None:
        class WrongSystemGateway:
            def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
                result = successful_result(request)
                return ExistingSystemCallResult(
                    succeeded=True,
                    detail=result.detail,
                    invocation_id=result.invocation_id,
                    system_code="unregistered-system",
                    operation_ref=result.operation_ref,
                    service_version=result.service_version,
                    returned_at=result.returned_at,
                    result=result.result,
                    data_reference=result.data_reference,
                )

        response = RuleEngineService(
            self.database_path, existing_system_gateway=WrongSystemGateway()
        ).execute(self.request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "EXISTING_SYSTEM_SOURCE_MISMATCH")

    def test_response_for_another_data_reference_is_blocked(self) -> None:
        class WrongDataGateway:
            def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
                result = successful_result(request)
                data_reference = dict(result.data_reference)
                data_reference["reference_id"] = "FIN-PAYROLL-ANOTHER-PERIOD"
                return ExistingSystemCallResult(
                    succeeded=True,
                    detail=result.detail,
                    invocation_id=result.invocation_id,
                    system_code=result.system_code,
                    operation_ref=result.operation_ref,
                    service_version=result.service_version,
                    returned_at=result.returned_at,
                    result=result.result,
                    data_reference=data_reference,
                )

        response = RuleEngineService(
            self.database_path, existing_system_gateway=WrongDataGateway()
        ).execute(self.request())

        self.assertEqual(response.state, ProcessingState.BLOCKED)
        self.assertEqual(response.reason_code, "EXISTING_SYSTEM_DATA_REFERENCE_MISMATCH")

    def test_external_call_reference_is_persisted_separately_from_business_result(self) -> None:
        engine = RuleEngineService(self.database_path)
        response = engine.execute(self.request())

        record = engine.get_record(response.trace_id)
        system_reference = json.loads(record["existing_system_reference_json"])
        business_result = json.loads(record["result_json"])

        self.assertEqual(system_reference["system_code"], "finance-system")
        self.assertTrue(system_reference["invocation_id"].startswith("EXT-"))
        self.assertEqual(business_result["net_payroll"], "30800.00")


def successful_result(request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
    returned_at = datetime.now(timezone.utc).isoformat()
    return ExistingSystemCallResult(
        succeeded=True,
        detail="Returned by a test translation adapter.",
        invocation_id="EXT-TEST-0001",
        system_code="finance-system",
        operation_ref=request.operation_ref,
        service_version="payroll-api-test",
        returned_at=returned_at,
        result={
            "employee_count": 1,
            "gross_payroll": "100.00",
            "deductions": "10.00",
            "net_payroll": "90.00",
        },
        data_reference={
            "reference_id": request.data_reference,
            "source_system": "finance-system",
            "source_description": "Test external payroll input.",
            "source_version": "test-v1",
            "data_digest": "test-digest",
            "retrieved_at": returned_at,
            "row_count": 1,
        },
    )


if __name__ == "__main__":
    unittest.main()
