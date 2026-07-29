from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.service import SandboxService


def main() -> None:
    service = SandboxService(ROOT)

    invoice = service.create_task({"scenario_id": "s04_invoice_matching", "actor": "demo-user", "input": {}})
    assert invoice["status"] == "success"
    assert invoice["platform_checks"]["mock_sources"] == ["mock_erp_or_oa"]
    assert invoice["result"]["payload"]["matches"][0]["status"] == "matched"
    assert invoice["platform_checks"]["cost_control"]["meter"] == "mock_cost_control"

    stock = service.create_task({"scenario_id": "s19_over_stock_warning", "actor": "sales-user", "input": {}})
    assert stock["status"] == "success"
    assert stock["result"]["payload"]["status"] == "warning"

    denied = service.create_task({"scenario_id": "s04_invoice_matching", "actor": "sales-user", "input": {}})
    assert denied["status"] == "denied"
    assert denied["platform_checks"]["sandbox_execution"]["started"] is False
    assert denied["platform_checks"]["cost_control"]["cost_units"] == 0
    assert "invoice:read" in denied["result"]["error"]
    assert "receipt:read" in denied["result"]["error"]

    report = {
        "ok": True,
        "validated": [
            "mock account gateway",
            "mock security precheck",
            "mock ERP/OA data injection",
            "mock cost control record",
            "audit events",
            "permission denial path",
        ],
    }
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
