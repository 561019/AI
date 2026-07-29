from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.monitor import build_monitor_snapshot
from backend.service import SandboxService


def main() -> None:
    service = SandboxService(ROOT)
    service.create_task({"scenario_id": "s04_invoice_matching", "actor": "demo-user", "agent": "finance-agent", "input": {}})
    service.create_task({"scenario_id": "s19_over_stock_warning", "actor": "sales-user", "agent": "sales-agent", "input": {}})

    snapshot = build_monitor_snapshot(service.list_tasks(), service.policy(), service.readiness())
    assert snapshot["summary"]["total"] >= 2, snapshot
    assert snapshot["instances"], snapshot
    assert snapshot["latest_instance"]["id"], snapshot
    assert snapshot["latest_instance"]["audit_count"] >= 0, snapshot

    print(json.dumps({"ok": True, "summary": snapshot["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
