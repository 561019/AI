from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import initialize_database
from app.platform_instruction import PUBLIC_PLATFORM_ACTIONS, SERVICE_CODE, PlatformInstructionService


FLOW_ARCHITECTURE_ROOT = Path(__file__).resolve().parents[3] / "流程执行引擎" / "架构"
FLOW_REFERENCE_AVAILABLE = FLOW_ARCHITECTURE_ROOT.exists()

if FLOW_REFERENCE_AVAILABLE:
    if str(FLOW_ARCHITECTURE_ROOT) not in sys.path:
        sys.path.insert(0, str(FLOW_ARCHITECTURE_ROOT))

    from platform_framework.common.platform_contract import (  # noqa: E402
        LayerInterfaceController,
        RequestType,
        ServiceRegistration,
        ServiceRegistry,
        build_instruction,
    )
    from platform_framework.common.platform_contract.audit import InMemoryAuditStore  # noqa: E402
    from platform_framework.common.platform_contract.permission import DemoPermissionGateway  # noqa: E402


@unittest.skipUnless(
    FLOW_REFERENCE_AVAILABLE,
    "Flow Execution Engine reference framework is not included in the standalone delivery package.",
)
class FlowExecutionIntegrationTests(unittest.TestCase):
    """Runs the Rule Engine through the Flow Engine team's real reference controller."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rule_engine.db"
        initialize_database(self.database_path)
        self.registry = ServiceRegistry()
        self.controller = LayerInterfaceController(
            layer="L2",
            service_code="interface.l2",
            registry=self.registry,
            permission_gateway=DemoPermissionGateway(),
            audit_store=InMemoryAuditStore(),
            allowed_source_layers={"L2"},
        )
        self.service = PlatformInstructionService(self.database_path)
        self.registry.register(
            ServiceRegistration(
                service_code=SERVICE_CODE,
                layer="L2",
                actions={action: RequestType.EXECUTE.value for action in PUBLIC_PLATFORM_ACTIONS},
                allowed_callers=["l2.workflow_execution"],
                handler=self.service.handle,
                async_supported=True,
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_flow_dispatches_standard_rule_evaluate_instruction(self) -> None:
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        instruction = build_instruction(
            source_layer="L2",
            source_service="l2.workflow_execution",
            target_layer="L2",
            target_service=SERVICE_CODE,
            channel="l2_internal",
            action="rule.evaluate",
            request_type=RequestType.EXECUTE,
            actor={"person_id": "business_operator", "position_ids": ["position_finance"]},
            context={
                "task_id": "flow-rule-task-001",
                "data_refs": [
                    {
                        "ref_id": "DS-RECEIVABLES-2026Q2",
                        "purpose": "calculation_input",
                        "version": "snapshot-1",
                        "data_labels": ["internal", "financial"],
                        "allowed_actions": ["read_for_rule_calculation"],
                    }
                ],
            },
            payload={"business_type": "bad_debt_provision"},
            trace_id="trace-flow-rule-001",
            request_id="request-flow-rule-001",
            idempotency_key="flow-rule-evaluate-001",
            deadline_at=deadline,
        )

        reply = self.controller.dispatch(instruction)

        self.assertEqual(reply["reply_type"], "accepted")
        self.assertEqual(reply["trace_id"], "trace-flow-rule-001")
        self.assertEqual(reply["request_id"], "request-flow-rule-001")
        self.assertEqual(reply["result"]["handling_type"], "confirm_effective")
        self.assertTrue(reply["audit"]["event_id"])


if __name__ == "__main__":
    unittest.main()
