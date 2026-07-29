from __future__ import annotations

import time
from typing import Any


class MockAccountGateway:
    USERS = {
        "demo-user": {
            "actor": "demo-user",
            "name": "演示用户",
            "department": "财务部",
            "role": "财务会计",
            "permissions": ["invoice:read", "receipt:read", "inventory:read", "purchase:read", "contract:read"],
        },
        "sales-user": {
            "actor": "sales-user",
            "name": "销售演示用户",
            "department": "销售部",
            "role": "销售员",
            "permissions": ["inventory:read", "order:read"],
        },
    }

    def resolve_actor(self, actor: str) -> dict[str, Any]:
        return self.USERS.get(actor, self.USERS["demo-user"])

    def can(self, actor_info: dict[str, Any], permission: str) -> bool:
        return permission in actor_info.get("permissions", [])


class MockSecurityCompliance:
    SCENARIO_PERMISSIONS = {
        "s04_invoice_matching": ["invoice:read", "receipt:read"],
        "s15_contract_diff": ["contract:read"],
        "s19_over_stock_warning": ["inventory:read", "order:read"],
        "s20_purchase_plan": ["purchase:read", "inventory:read"],
    }

    def precheck(self, scenario_id: str, actor_info: dict[str, Any], account: MockAccountGateway) -> dict[str, Any]:
        required = self.SCENARIO_PERMISSIONS.get(scenario_id, [])
        missing = [perm for perm in required if not account.can(actor_info, perm)]
        return {
            "allowed": not missing,
            "required_permissions": required,
            "missing_permissions": missing,
            "egress_policy": "deny_by_default_allow_mock_internal",
            "sensitive_data_policy": "mask_secrets_and_keep_audit",
        }

    def audit(self, event: str, detail: dict[str, Any]) -> dict[str, Any]:
        return {"time": now(), "event": event, "detail": detail}


class MockERP:
    def invoice_payload(self) -> dict[str, Any]:
        return {
            "invoices": [
                {"invoice_no": "INV001", "supplier": "供应商A", "amount": 10000, "tax_rate": 0.13},
                {"invoice_no": "INV002", "supplier": "供应商B", "amount": 8800, "tax_rate": 0.09},
            ],
            "receipts": [
                {"receipt_no": "IN001", "supplier": "供应商A", "amount": 10000},
                {"receipt_no": "IN002", "supplier": "供应商B", "amount": 9000},
            ],
        }

    def inventory_order_payload(self) -> dict[str, Any]:
        return {
            "inventory": 50,
            "orders": [
                {"department": "销售一部", "qty": 30},
                {"department": "销售二部", "qty": 30},
                {"department": "销售三部", "qty": 30},
            ],
        }

    def purchase_plan_payload(self) -> dict[str, Any]:
        return {"history": [80, 100, 110, 130], "current_stock": 60}


class MockOA:
    def contract_payload(self) -> dict[str, Any]:
        return {
            "old": "付款期限为30天。交货地点为南宁。违约金按合同总额1%计算。",
            "new": "付款期限为45天。交货地点为南宁。违约金按合同总额2%计算。",
        }

    def create_todo(self, title: str, reason: str) -> dict[str, Any]:
        return {"todo_id": f"TODO-{int(time.time())}", "title": title, "reason": reason, "status": "created"}


class MockCostControl:
    def record(self, task: dict[str, Any]) -> dict[str, Any]:
        limits = task.get("limits", {})
        duration_ms = int(task.get("duration_ms") or 0)
        memory_mb = int(limits.get("memory_mb", 512))
        cpu_cores = float(limits.get("cpu_cores", 1))
        cost_units = round((duration_ms / 1000) * cpu_cores + memory_mb / 1024 * 0.01, 4)
        return {
            "meter": "mock_cost_control",
            "duration_ms": duration_ms,
            "memory_mb": memory_mb,
            "cpu_cores": cpu_cores,
            "cost_units": cost_units,
        }


class MockPlatform:
    def __init__(self):
        self.account = MockAccountGateway()
        self.security = MockSecurityCompliance()
        self.erp = MockERP()
        self.oa = MockOA()
        self.cost = MockCostControl()

    def enrich_input(self, scenario_id: str, task_input: dict[str, Any]) -> dict[str, Any]:
        merged = dict(task_input)
        if scenario_id == "s04_invoice_matching":
            merged = {**self.erp.invoice_payload(), **merged}
        elif scenario_id == "s15_contract_diff":
            merged = {**self.oa.contract_payload(), **merged}
        elif scenario_id == "s19_over_stock_warning":
            merged = {**self.erp.inventory_order_payload(), **merged}
        elif scenario_id == "s20_purchase_plan":
            merged = {**self.erp.purchase_plan_payload(), **merged}
        return merged


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

