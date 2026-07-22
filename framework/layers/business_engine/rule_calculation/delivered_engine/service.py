from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "联调文件-7.20-解压" / "rule_calculation_engine_delivery_20260720(1)" / "05_rule_calculation_engine" / "rule_calc_engine_core"
sys.path.insert(0, str(SOURCE)) if str(SOURCE) not in sys.path else None
from app.executors import DeclarativeRuleExecutor  # noqa: E402


def post(handler: Any, request: dict[str, Any]) -> None:
    if handler.path != "/api/v1/delivered-rules/calculate":
        handler.send(404); return
    values = request.get("values") or []
    if not values:
        handler.send(422, {"success": False, "error": {"code": "VALUES_REQUIRED"}}); return
    rows = [{"values": values}]
    formulas = []
    # 原执行器只允许声明式二元公式；把 N 个值转换为连续 add 公式。
    flat_row = {f"value_{i}": value for i, value in enumerate(values)}
    rows = [flat_row]
    previous = {"field": "value_0"}
    for index in range(1, len(values)):
        name = f"sum_{index}"
        formulas.append({"name": name, "operator": "add", "operands": [previous, {"field": f"value_{index}"}], "scale": 2})
        previous = {"formula": name}
    rule = {"rule_schema_version": "1.0", "parameter_tables": {}, "operations": {"lookups": [], "formulas": formulas, "conditions": [], "aggregates": [], "line_outputs": {"value": previous}}}
    result = DeclarativeRuleExecutor().execute(rows, rule)
    value = float(values[0]) if len(values) == 1 else float(result["lines"][0]["value"])
    handler.send(200, {"success": True, "data": {"state": "completed", "value": value, "unit": request.get("unit", "CNY"), "evidence": result}, "engine_meta": {"source": "user-delivered-module", "component": "DeclarativeRuleExecutor", "delivery_root": str(SOURCE)}})
