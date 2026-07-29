from __future__ import annotations

from typing import Any

from framework.core import standard_response
from framework.http import post_json


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": "rule.calculate", "enabled": True}]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/rules/instructions":
        handler.send(404)
        return
    payload = envelope.get("payload", {}) if isinstance(envelope.get("payload"), dict) else {}
    parameters = payload.get("parameters", {}) if isinstance(payload.get("parameters"), dict) else {}
    values = parameters.get("values") or _check_deltas(parameters.get("checks"))
    if values:
        _run_delivered_values(handler, envelope, payload, values, "checks" if not parameters.get("values") else "values")
        return

    rule_result = _evaluate_workflow_rule_context(payload)
    handler.send(200, standard_response(envelope, "success", data=rule_result))


def _run_delivered_values(
    handler: Any,
    envelope: dict[str, Any],
    payload: dict[str, Any],
    values: list[float],
    source: str,
) -> None:
    status, result = post_json(
        "http://127.0.0.1:8012/api/v1/delivered-rules/calculate",
        {"trace_id": envelope["trace_id"], "values": values, "unit": payload.get("expected_unit", "CNY")},
        caller={"layer": "business_engine", "module": "rule-adapter"},
    )
    if status != 200 or not result.get("success"):
        handler.send(502, standard_response(envelope, "failed", error={"code": "DELIVERED_RULE_ENGINE_FAILED", "details": result}))
        return
    value = (result.get("data") or {}).get("value")
    rule_result = {
        **result["data"],
        "rule_engine": result["engine_meta"],
        "input_adapter": {"source": source, "values": values},
        "rule_context": payload.get("rule_context"),
        "input_data_refs": payload.get("input_data_refs") or [],
        "rule_results": [{
            "rule_id": "numeric_delta_sum",
            "rule_name": "数值差异汇总",
            "status": "passed" if float(value or 0) == 0 else "warning",
            "value": value,
            "evidence_refs": payload.get("input_data_refs") or [],
        }],
        "risks": [] if float(value or 0) == 0 else [{"risk_id": "numeric_delta_non_zero", "level": "medium", "description": "存在非零差异，需要人工核对。"}],
        "exceptions": [] if float(value or 0) == 0 else [{"exception_id": "numeric_delta_exception", "description": "规则计算得到非零差异。"}],
    }
    handler.send(200, standard_response(envelope, "success", data=rule_result))


def _evaluate_workflow_rule_context(payload: dict[str, Any]) -> dict[str, Any]:
    context = str(payload.get("rule_context") or payload.get("user_goal") or "")
    refs = payload.get("input_data_refs") if isinstance(payload.get("input_data_refs"), list) else []
    prior_outputs = payload.get("workflow_prior_outputs") if isinstance(payload.get("workflow_prior_outputs"), dict) else {}
    aggregates = _aggregates_from_refs(refs) or _aggregates_from_prior_outputs(prior_outputs)

    rule_results: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    evidence_refs = refs[:10]

    budget = _first_aggregate(aggregates, {"budget_summary"})
    if "预算" in context or "budget" in context.lower():
        total = _number(budget.get("total_amount_cny")) if budget else None
        rows = budget.get("detail") if isinstance(budget, dict) and isinstance(budget.get("detail"), list) else []
        status = "passed" if total is not None and total > 0 and rows else "exception"
        rule_results.append({
            "rule_id": "budget.completeness",
            "rule_name": "预算数据完整性检查",
            "status": status,
            "observed_value": total,
            "message": "已识别预算合计和预算明细。" if status == "passed" else "未识别到可核对的预算合计或预算明细。",
            "evidence_refs": evidence_refs,
        })
        if status != "passed":
            exceptions.append({"exception_id": "budget_data_missing", "description": "缺少预算规则计算所需的预算金额或明细。"})

    if "价格" in context or "成本" in context or "price" in context.lower() or "cost" in context.lower():
        product_or_budget = _first_aggregate(aggregates, {"business_object_detail", "business_data_summary", "budget_summary"})
        fields = _price_cost_fields(product_or_budget)
        gross_margin = _number(fields.get("gross_margin_rate") or fields.get("毛利率"))
        status = "passed" if gross_margin is not None and gross_margin >= 0 else "warning"
        rule_results.append({
            "rule_id": "price_cost.margin_available",
            "rule_name": "价格成本口径检查",
            "status": status,
            "observed_value": gross_margin,
            "message": "已识别价格成本相关毛利率。" if gross_margin is not None else "未从上游数据中识别到明确毛利率，需人工补充价格成本口径。",
            "evidence_refs": evidence_refs,
        })
        if gross_margin is None:
            risks.append({"risk_id": "price_cost_basis_missing", "level": "medium", "description": "价格或成本口径不完整，规则结论只能作为待核对结果。"})

    if "盈亏平衡" in context or "break-even" in context.lower() or "breakeven" in context.lower():
        total = _number(budget.get("total_amount_cny")) if budget else None
        rule_results.append({
            "rule_id": "break_even.input_check",
            "rule_name": "盈亏平衡输入检查",
            "status": "warning",
            "observed_value": total,
            "message": "已收到预算数据；盈亏平衡还需要确认单价、单位成本和目标利润口径。",
            "evidence_refs": evidence_refs,
        })
        risks.append({"risk_id": "break_even_assumption_required", "level": "medium", "description": "盈亏平衡计算缺少完整价格成本假设，需人工确认后才能作为正式结论。"})

    if not rule_results:
        rule_results.append({
            "rule_id": "generic.rule_context_received",
            "rule_name": "规则上下文接收检查",
            "status": "warning",
            "message": "规则计算引擎已收到规则上下文，但未识别到具体规则类型。",
            "evidence_refs": evidence_refs,
        })
        risks.append({"risk_id": "formal_rule_missing", "level": "low", "description": "未匹配到正式规则编号，后续应补充规则登记。"})

    return {
        "state": "completed",
        "module": "rule",
        "module_name_cn": "规则计算引擎",
        "platform_capability": "rule.calculate",
        "rule_context": context,
        "input_data_refs": refs,
        "rule_results": rule_results,
        "risks": risks,
        "exceptions": exceptions,
        "evidence_refs": evidence_refs,
        "expected_outputs": payload.get("expected_outputs") or ["rule_results", "risks", "exceptions", "evidence_refs"],
    }


def _aggregates_from_refs(refs: list[Any]) -> list[dict[str, Any]]:
    aggregates = []
    for ref in refs:
        if isinstance(ref, dict) and isinstance(ref.get("aggregate"), dict):
            aggregates.append(ref["aggregate"])
    return aggregates


def _aggregates_from_prior_outputs(prior_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for data in prior_outputs.values():
        if not isinstance(data, dict):
            continue
        storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else data
        aggregate = storage.get("aggregate") if isinstance(storage, dict) else None
        if isinstance(aggregate, dict):
            result.append(aggregate)
    return result


def _first_aggregate(aggregates: list[dict[str, Any]], operations: set[str]) -> dict[str, Any]:
    for aggregate in aggregates:
        if str(aggregate.get("operation") or "") in operations:
            return aggregate
    return {}


def _price_cost_fields(aggregate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(aggregate, dict):
        return {}
    if isinstance(aggregate.get("price_cost"), dict):
        return aggregate["price_cost"]
    if isinstance(aggregate.get("detail"), dict):
        return aggregate["detail"]
    fields: dict[str, Any] = {}
    rows = aggregate.get("detail") if isinstance(aggregate.get("detail"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if value not in (None, ""):
                fields.setdefault(str(key), value)
    return fields


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        text = str(value or "").replace(",", "")
        return float(text)
    except ValueError:
        return None


def _check_deltas(checks: Any) -> list[float]:
    if not isinstance(checks, list):
        return []
    values: list[float] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        expected = check.get("expected_value")
        actual = check.get("actual_value")
        if isinstance(expected, (int, float)) and not isinstance(expected, bool) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
            values.append(float(actual) - float(expected))
    return values
