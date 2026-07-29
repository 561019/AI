from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.templates import TEMPLATES, run_template


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pivot = run_template(
            "s06_messy_table_pivot",
            {
                "rows": [
                    {"product": "A", "region": "华南", "amount": 120},
                    {"product": "A", "region": "华南", "amount": 80},
                    {"product": "B", "region": "华北", "amount": 50}
                ]
            },
            root / "pivot",
            5,
        )
        assert pivot["payload"]["pivot"]["A"]["华南"] == 200
        assert pivot["files"]

        cost = run_template("s03_product_cost", {}, root / "cost", 5)
        assert cost["payload"]["unit_cost"] > 0

        warning = run_template("s19_over_stock_warning", {}, root / "stock", 5)
        assert warning["payload"]["status"] == "warning"

        for scenario_id in TEMPLATES:
            result = run_template(scenario_id, {}, root / "all" / scenario_id, 5)
            assert "payload" in result

    print(json.dumps({"ok": True, "tested": ["s06", "s03", "s19", "all_20_templates"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
