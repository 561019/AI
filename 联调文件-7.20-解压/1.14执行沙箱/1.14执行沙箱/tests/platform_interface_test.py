from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.mock_platform import MockPlatform
from backend.platform_interface import PlatformInterface, PlatformInterfaceError


TOKEN = "platform-interface-test-token"
ENGINE_ID = "flow-execution-engine"


class FakeExecutor:
    name = "DockerTemplateExecutor"


class FakeService:
    def __init__(self) -> None:
        self.config = {
            "platform_interface": {
                "allowed_caller_layer": "business_engine",
                "allowed_engines": [ENGINE_ID],
                "demo_api_token": TOKEN,
                "max_request_records": 20,
            }
        }
        self.executor = FakeExecutor()
        self.mock_platform = MockPlatform()
        self.execution_count = 0

    def list_scenarios(self) -> list[dict[str, Any]]:
        return [
            {"id": "s19_over_stock_warning", "name": "超库存预警", "risk_level": "high", "needs_human_approval": True},
            {"id": "s04_invoice_matching", "name": "发票核销", "risk_level": "high", "needs_human_approval": True},
        ]

    def create_task(self, payload: dict[str, Any], progress: Any = None) -> dict[str, Any]:
        self.execution_count += 1
        task_id = f"task-{self.execution_count}"
        if progress:
            progress("task.accepted", "任务记录已创建", {"task_id": task_id})
            progress("identity.resolved", "身份已解析", {"actor": payload["actor"]})
        if payload["scenario_id"] == "s04_invoice_matching" and payload["actor"] == "sales-user":
            if progress:
                progress(
                    "permission.checked",
                    "权限预检拒绝",
                    {"allowed": False, "missing_permissions": ["invoice:read", "receipt:read"]},
                )
                progress("task.finished", "拒绝结果已保存", {"task_id": task_id, "status": "denied"})
            return {
                "id": task_id,
                "status": "denied",
                "duration_ms": 3,
                "executor": self.executor.name,
                "limits": payload,
                "result": {"error": "missing permissions: invoice:read, receipt:read"},
                "logs": [{"event": "sandbox.not_started"}, {"event": "sandbox.denied"}],
                "platform_checks": {
                    "security_compliance": {
                        "allowed": False,
                        "missing_permissions": ["invoice:read", "receipt:read"],
                    },
                    "sandbox_execution": {"started": False, "reason": "permission_precheck_denied"},
                    "cost_control": {"cost_units": 0},
                },
            }
        if progress:
            progress("permission.checked", "权限预检通过", {"allowed": True})
            progress("sandbox.preparing", "创建 Docker 环境", {"executor": self.executor.name})
            progress("sandbox.result_collected", "结果已取回", {"task_id": task_id})
            progress("task.finished", "任务完成", {"task_id": task_id, "status": "success"})
        return {
            "id": task_id,
            "status": "success",
            "duration_ms": 12,
            "executor": self.executor.name,
            "limits": payload,
            "result": {
                "payload": {"status": "warning", "over_qty": 40},
                "files": ["/results/over_stock_warning.json"],
                "sandbox_runtime": {"executor": self.executor.name, "isolation": "docker_container"},
            },
            "logs": [{"event": "sandbox.created"}, {"event": "sandbox.destroyed"}],
            "platform_checks": {
                "security_compliance": {"allowed": True, "missing_permissions": []},
                "sandbox_execution": {"started": True},
            },
        }


def headers(trace_id: str, layer: str = "business_engine", engine_id: str = ENGINE_ID) -> dict[str, str]:
    return {
        "authorization": f"Bearer {TOKEN}",
        "x-caller-layer": layer,
        "x-engine-id": engine_id,
        "x-company-id": "hanhe-group",
        "x-trace-id": trace_id,
    }


def request(trace_id: str, reply_mode: str = "immediate", scenario_id: str = "s19_over_stock_warning") -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "trace_id": trace_id,
        "service_code": "execution_sandbox.run_task",
        "reply_mode": reply_mode,
        "caller": {
            "layer": "business_engine",
            "engine_id": ENGINE_ID,
            "company_id": "hanhe-group",
            "user_id": "sales-user",
        },
        "payload": {
            "scenario_id": scenario_id,
            "agent": "integration-test-agent",
            "limits": {"timeout_seconds": 10, "memory_mb": 512, "cpu_cores": 1},
            "input": {},
        },
    }


def expect_error(code: str, action: Any) -> None:
    try:
        action()
    except PlatformInterfaceError as exc:
        assert exc.code == code, (exc.code, code)
        return
    raise AssertionError(f"expected {code}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        service = FakeService()
        interface = PlatformInterface(root, service)

        catalog = interface.service_catalog()
        assert catalog["preferred_interface"]["submit"] == "/api/v1/layer-interface/messages"
        assert catalog["capabilities"][0]["capability_id"] == "CAP.SANDBOX.TASK.RUN"
        assert catalog["capabilities"][1]["capability_id"] == "CAP.SANDBOX.CODE.RUN"
        assert catalog["legacy_compatibility"]["deprecated_for_new_integration"] is True

        expect_error(
            "caller_layer_not_allowed",
            lambda: interface.submit(request("trace-app-layer"), headers("trace-app-layer", layer="business_application")),
        )
        expect_error(
            "engine_not_registered",
            lambda: interface.submit(request("trace-bad-engine"), headers("trace-bad-engine", engine_id="unknown-engine")),
        )

        immediate, status = interface.submit(request("trace-immediate"), headers("trace-immediate"))
        assert status == 200
        assert immediate["reply_type"] == "result"
        assert immediate["status"] == "succeeded"
        assert immediate["output"]["business_result"]["over_qty"] == 40

        duplicate, duplicate_status = interface.submit(request("trace-immediate"), headers("trace-immediate"))
        assert duplicate_status == 200
        assert duplicate["request_id"] == immediate["request_id"]
        assert service.execution_count == 1

        conflicting = request("trace-immediate")
        conflicting["payload"]["input"] = {"changed": True}
        expect_error(
            "trace_id_conflict",
            lambda: interface.submit(conflicting, headers("trace-immediate")),
        )

        receipt, receipt_status = interface.submit(request("trace-receipt", reply_mode="receipt"), headers("trace-receipt"))
        assert receipt_status == 202
        assert receipt["reply_type"] == "acceptance_receipt"
        assert receipt["status"] == "accepted"
        assert receipt["request_id"].startswith("req-")
        for _ in range(100):
            current = interface.get_request(receipt["request_id"], headers("trace-receipt"))
            if current["status"] not in {"accepted", "running"}:
                break
            time.sleep(0.01)
        assert current["status"] == "succeeded"
        events = interface.get_events(receipt["request_id"], headers("trace-receipt"))
        assert any(item["kind"] == "sandbox.preparing" for item in events["events"])

        denied_body = request("trace-denied", scenario_id="s04_invoice_matching")
        denied, denied_status = interface.submit(denied_body, headers("trace-denied"))
        assert denied_status == 200
        assert denied["reply_type"] == "rejection"
        assert denied["status"] == "rejected"
        assert denied["reason"]["missing_permissions"] == ["invoice:read", "receipt:read"]
        assert denied["reason"]["sandbox_started"] is False

        unknown_user = request("trace-unknown-user")
        unknown_user["caller"]["user_id"] = "unknown-user"
        expect_error(
            "identity_not_resolved",
            lambda: interface.submit(unknown_user, headers("trace-unknown-user")),
        )

    print(json.dumps({"ok": True, "tested": 8, "service_code": "execution_sandbox.run_task"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
