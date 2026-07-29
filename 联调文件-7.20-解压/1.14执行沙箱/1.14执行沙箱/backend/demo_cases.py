from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.mock_platform import MockAccountGateway, MockSecurityCompliance


DEMO_CASES: list[dict[str, Any]] = [
    {
        "id": "invoice_matching",
        "title": "发票核销链路",
        "scenario_id": "s04_invoice_matching",
        "actor": "demo-user",
        "agent": "finance-agent",
        "timeout_seconds": 10,
        "input": {},
        "expected_decision": "allow",
        "expected": "账号、权限、ERP 模拟取数、沙箱执行、成本记录、审计留痕全链路通过。",
    },
    {
        "id": "over_stock_warning",
        "title": "跨部门超库存预警",
        "scenario_id": "s19_over_stock_warning",
        "actor": "sales-user",
        "agent": "sales-agent",
        "timeout_seconds": 10,
        "input": {},
        "expected_decision": "allow",
        "expected": "该场景需要 inventory:read 和 order:read，销售员均具备，因此允许进入 Docker 沙箱。",
    },
    {
        "id": "permission_denied",
        "title": "销售岗位越权尝试：发票核销",
        "scenario_id": "s04_invoice_matching",
        "actor": "sales-user",
        "agent": "sales-agent",
        "timeout_seconds": 10,
        "input": {},
        "expected_decision": "deny",
        "expected": "该场景需要 invoice:read 和 receipt:read，销售员均不具备，因此在创建 Docker 容器前拒绝。",
    },
]


def list_demo_cases() -> list[dict[str, Any]]:
    cases = []
    for item in DEMO_CASES:
        actor_profile = MockAccountGateway.USERS.get(item["actor"], {})
        held_permissions = list(actor_profile.get("permissions", []))
        required_permissions = list(MockSecurityCompliance.SCENARIO_PERMISSIONS.get(item["scenario_id"], []))
        missing_permissions = [permission for permission in required_permissions if permission not in held_permissions]
        cases.append({
            "id": item["id"],
            "title": item["title"],
            "scenario_id": item["scenario_id"],
            "actor": item["actor"],
            "agent": item["agent"],
            "expected": item["expected"],
            "expected_decision": item["expected_decision"],
            "actor_profile": {
                "name": actor_profile.get("name"),
                "department": actor_profile.get("department"),
                "role": actor_profile.get("role"),
            },
            "held_permissions": held_permissions,
            "required_permissions": required_permissions,
            "missing_permissions": missing_permissions,
        })
    return cases


def run_demo_case(service: Any, case_id: str) -> dict[str, Any]:
    case = next((item for item in DEMO_CASES if item["id"] == case_id), None)
    if not case:
        raise ValueError(f"unknown demo case: {case_id}")

    payload = deepcopy(case)
    payload.pop("id", None)
    payload.pop("title", None)
    payload.pop("expected", None)
    payload.pop("expected_decision", None)
    task = service.create_task(payload)
    return {"case": next(item for item in list_demo_cases() if item["id"] == case_id), "task": task}
