from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.demo_cases import list_demo_cases, run_demo_case
from backend.service import SandboxService


def main() -> None:
    service = SandboxService(ROOT)
    cases = list_demo_cases()
    assert len(cases) == 3, cases

    invoice = run_demo_case(service, "invoice_matching")["task"]
    assert invoice["status"] == "success", invoice
    assert invoice["platform_checks"]["security_compliance"]["allowed"] is True

    stock = run_demo_case(service, "over_stock_warning")["task"]
    assert stock["status"] == "success", stock
    assert stock["result"]["payload"]["status"] == "warning"

    denied = run_demo_case(service, "permission_denied")["task"]
    assert denied["status"] == "failed", denied
    assert denied["platform_checks"]["security_compliance"]["allowed"] is False

    print(json.dumps({"ok": True, "validated": [item["id"] for item in cases]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
