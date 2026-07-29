# -*- coding: utf-8 -*-
"""MVP 固定工具适配器。

这里不是通用脚本执行器，也不接受用户上传代码。数字资产引擎只允许绑定
白名单内、带固定版本的确定性工具，从而证明“技能资产”能被真实调用，同时
避免把任意代码执行能力塞进治理引擎。
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


FERMENTATION_RULES = {
    "temperature_c": {"min": 28.0, "max": 32.0, "unit": "°C", "label": "温度"},
    "ph": {"min": 6.0, "max": 7.0, "unit": "", "label": "pH"},
    "dissolved_oxygen_pct": {"min": 20.0, "max": 100.0, "unit": "%", "label": "溶氧"},
}

TOOL_DEFINITIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("fermentation_anomaly_checker", "1.0.0"): {
        "tool_id": "fermentation_anomaly_checker",
        "version": "1.0.0",
        "tool_name": "发酵参数异常检查固定工具",
        "handler": "fermentation_anomaly_checker_v1",
        "input_schema": {
            "type": "object",
            "required": list(FERMENTATION_RULES),
            "properties": {
                "temperature_c": {"type": "number", "title": "温度（°C）"},
                "ph": {"type": "number", "title": "pH"},
                "dissolved_oxygen_pct": {"type": "number", "title": "溶氧（%）"},
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["conclusion", "abnormal_items", "requires_human_review", "tool_version"],
        },
        "rules": FERMENTATION_RULES,
        "test_cases": [
            {
                "name": "正常批次",
                "input": {"temperature_c": 30, "ph": 6.5, "dissolved_oxygen_pct": 35},
                "expected": {"conclusion": "normal", "abnormal_count": 0},
            },
            {
                "name": "温度与溶氧异常",
                "input": {"temperature_c": 34, "ph": 6.5, "dissolved_oxygen_pct": 12},
                "expected": {"conclusion": "abnormal", "abnormal_count": 2},
            },
        ],
    }
}


def tool_checksum(definition: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "handler": definition["handler"],
            "version": definition["version"],
            "rules": definition["rules"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def public_tool_definitions() -> list[dict[str, Any]]:
    result = []
    for definition in TOOL_DEFINITIONS.values():
        item = dict(definition)
        item["checksum"] = tool_checksum(definition)
        result.append(item)
    return result


def _number(payload: dict[str, Any], field: str) -> float:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是数值")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} 必须是有限数值")
    return value


def execute_fixed_tool(tool_id: str, version: str, payload: dict[str, Any]) -> dict[str, Any]:
    definition = TOOL_DEFINITIONS.get((tool_id, version))
    if not definition:
        raise KeyError(f"固定工具未登记或版本不存在：{tool_id}@{version}")
    if definition["handler"] != "fermentation_anomaly_checker_v1":
        raise KeyError(f"固定工具处理器未进入白名单：{definition['handler']}")

    values = {field: _number(payload, field) for field in FERMENTATION_RULES}
    abnormal_items = []
    for field, rule in FERMENTATION_RULES.items():
        value = values[field]
        if value < rule["min"] or value > rule["max"]:
            abnormal_items.append(
                {
                    "field": field,
                    "label": rule["label"],
                    "actual": value,
                    "expected": f"{rule['min']:g}–{rule['max']:g}{rule['unit']}",
                    "message": f"{rule['label']} {value:g}{rule['unit']} 超出固定规则范围",
                }
            )

    return {
        "conclusion": "abnormal" if abnormal_items else "normal",
        "abnormal_count": len(abnormal_items),
        "abnormal_items": abnormal_items,
        "normalized_input": values,
        "requires_human_review": bool(abnormal_items),
        "human_review_instruction": "异常结果必须由发酵工艺岗位真人确认；本工具不自动调整工艺参数。",
        "tool_id": tool_id,
        "tool_version": version,
        "rule_version": "fermentation-rule-2026.07",
        "tool_checksum": tool_checksum(definition),
    }
