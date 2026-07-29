from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import initialize_database
from app.platform_instruction import PlatformInstructionService


def instruction(now: datetime, *, message_id: str, idempotency_key: str, data_refs: list[dict]) -> dict:
    return {
        "protocol_version": "1.0",
        "message_id": message_id,
        "trace_id": "trace-two-stage-smoke",
        "request_id": "request-two-stage-smoke",
        "parent_message_id": "msg-flow-two-stage-smoke",
        "occurred_at": now.isoformat(),
        "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
        "target": {"layer": "L2", "service_code": "l2.rule_calculation"},
        "channel": "l2_internal",
        "action": "rule.evaluate",
        "request_type": "execute",
        "actor": {"person_id": "business_operator", "position_ids": ["position_finance"]},
        "context": {
            "task_id": "task-two-stage-smoke",
            "subtask_id": "subtask-two-stage-smoke",
            "data_refs": data_refs,
        },
        "idempotency_key": idempotency_key,
        "deadline_at": (now + timedelta(minutes=1)).isoformat(),
        "payload": {
            "task": "Calculate bad debt provision for the authorized 2026 Q2 receivables.",
            "business_type": "bad_debt_provision",
            "business_object_ref": "ORG-001",
            "period": "2026-Q2",
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = Path(temp_dir) / "rule_engine.db"
        initialize_database(database_path)
        service = PlatformInstructionService(database_path)
        now = datetime.now(timezone.utc)

        assessment_reply = service.handle(
            instruction(
                now,
                message_id="msg-two-stage-assessment",
                idempotency_key="idem-two-stage-assessment",
                data_refs=[],
            )
        )
        assessment = assessment_reply.get("result", {}).get("data", {})
        if (
            assessment_reply.get("reply_type") != "success"
            or assessment.get("state") != "precondition_query_required"
        ):
            raise SystemExit(f"Initial assessment did not return query requirements: {assessment_reply}")

        execution_reply = service.handle(
            instruction(
                now,
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
                        "source_system": "platform-test-data",
                        "resource_type": "receivables",
                        "resource_ids": ["2026-Q2"],
                        "version": "snapshot-1",
                        "data_labels": ["internal", "financial"],
                        "allowed_actions": ["read_for_rule_calculation"],
                    },
                ],
            )
        )
        result = execution_reply.get("result", {})
        if (
            execution_reply.get("reply_type") != "accepted"
            or result.get("state") != "waiting_human"
            or result.get("handling_type") != "confirm_effective"
        ):
            raise SystemExit(f"Second-stage execution did not reach governed result handling: {execution_reply}")

        print(
            json.dumps(
                {
                    "assessment_state": assessment["state"],
                    "query_types": [item["query_type"] for item in assessment["query_requirements"]],
                    "execution_state": result["state"],
                    "handling_type": result["handling_type"],
                    "execution_record_id": result["task_id"],
                    "trace_id": execution_reply["trace_id"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
