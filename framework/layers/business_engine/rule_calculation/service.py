from __future__ import annotations

import math
import re
from datetime import date
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
    aggregates = _dedupe_aggregates(_aggregates_from_refs(refs) + _aggregates_from_prior_outputs(prior_outputs))

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
        fields = _price_cost_fields(budget)
        fixed_cost = _number(
            fields.get("fixed_project_budget")
            or fields.get("fixed_cost")
            or fields.get("fixed_budget")
            or fields.get("固定项目预算")
            or fields.get("固定成本")
            or total
        )
        unit_margin = _unit_contribution_margin(fields)
        if fixed_cost is not None and unit_margin is not None and unit_margin > 0:
            break_even_qty = int(math.ceil(fixed_cost / unit_margin))
            rule_results.append({
                "rule_id": "break_even.quantity",
                "rule_name": "盈亏平衡数量计算",
                "status": "passed",
                "observed_value": break_even_qty,
                "unit": fields.get("unit") or fields.get("单位") or "unit",
                "formula": "ceil(fixed_cost / unit_contribution_margin)",
                "inputs": {
                    "fixed_cost": fixed_cost,
                    "unit_contribution_margin": unit_margin,
                    "list_price": _number(fields.get("list_price") or fields.get("unit_price") or fields.get("price") or fields.get("单价")),
                    "unit_cost": _number(fields.get("standard_variable_cost") or fields.get("unit_cost") or fields.get("variable_cost") or fields.get("cost") or fields.get("成本")),
                    "gross_margin_rate": _number(fields.get("gross_margin_rate") or fields.get("毛利率")),
                },
                "message": f"盈亏平衡数量为 {break_even_qty} {fields.get('unit') or fields.get('单位') or '单位'}。",
                "evidence_refs": evidence_refs,
            })
        else:
            missing = []
            if fixed_cost is None:
                missing.append("固定成本/固定预算")
            if unit_margin is None or unit_margin <= 0:
                missing.append("单位边际贡献（或单价与单位成本）")
            rule_results.append({
                "rule_id": "break_even.input_check",
                "rule_name": "盈亏平衡输入检查",
                "status": "warning",
                "observed_value": total,
                "message": "盈亏平衡还不能给出最终值，缺少：" + "、".join(missing) + "。",
                "evidence_refs": evidence_refs,
            })
            risks.append({"risk_id": "break_even_assumption_required", "level": "medium", "description": "盈亏平衡计算缺少完整价格成本口径，需补充后才能作为正式结论。"})

    if _looks_like_budget_risk_request(context):
        assessment = _budget_risk_assessment(context, budget, aggregates, prior_outputs, evidence_refs)
        rule_results.append(assessment["rule_result"])
        risks.extend(assessment.get("risks") or [])
        exceptions.extend(assessment.get("exceptions") or [])

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
        direct = data.get("aggregate") if isinstance(data.get("aggregate"), dict) else None
        if isinstance(direct, dict) and direct is not aggregate:
            result.append(direct)
    return result


def _dedupe_aggregates(aggregates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for aggregate in aggregates:
        if not isinstance(aggregate, dict):
            continue
        key = repr(sorted(aggregate.items(), key=lambda item: str(item[0])))
        if key in seen:
            continue
        seen.add(key)
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


def _unit_contribution_margin(fields: dict[str, Any]) -> float | None:
    direct = _number(
        fields.get("contribution_margin")
        or fields.get("unit_contribution_margin")
        or fields.get("unit_margin")
        or fields.get("单位边际贡献")
        or fields.get("边际贡献")
    )
    if direct is not None:
        return direct
    price = _number(fields.get("list_price") or fields.get("unit_price") or fields.get("price") or fields.get("单价"))
    cost = _number(
        fields.get("standard_variable_cost")
        or fields.get("unit_cost")
        or fields.get("variable_cost")
        or fields.get("cost")
        or fields.get("单位成本")
        or fields.get("成本")
    )
    if price is not None and cost is not None:
        return price - cost
    margin_rate = _number(fields.get("gross_margin_rate") or fields.get("毛利率"))
    if price is not None and margin_rate is not None:
        return price * margin_rate
    return None


def _looks_like_budget_risk_request(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(word in lowered for word in ("预算风险", "budget risk")) or (
        any(word in lowered for word in ("预算", "budget"))
        and any(word in lowered for word in ("风险", "risk", "预警"))
    )


def _budget_risk_assessment(
    context: str,
    budget: dict[str, Any],
    aggregates: list[dict[str, Any]],
    prior_outputs: dict[str, Any],
    evidence_refs: list[Any],
) -> dict[str, Any]:
    fields = _price_cost_fields(budget)
    fixed_cost = _number(
        fields.get("fixed_project_budget")
        or fields.get("fixed_cost")
        or fields.get("fixed_budget")
        or fields.get("固定项目预算")
        or fields.get("固定成本")
        or (budget.get("total_amount_cny") if isinstance(budget, dict) else None)
    )
    unit_margin = _unit_contribution_margin(fields)
    unit = fields.get("unit") or fields.get("单位") or "单位"
    demand_estimate = _estimate_target_demand(context, aggregates, prior_outputs)
    missing: list[str] = []
    if fixed_cost is None or fixed_cost <= 0:
        missing.append("固定预算/固定成本")
    if unit_margin is None or unit_margin <= 0:
        missing.append("单位边际贡献（或单价、单位成本、毛利率）")
    if demand_estimate.get("quantity") is None:
        missing.append("目标期间需求数量或可估算的月度需求序列")
    if missing:
        return {
            "rule_result": {
                "rule_id": "budget_risk.input_check",
                "rule_name": "预算风险输入检查",
                "status": "warning",
                "message": "预算风险还不能形成完整测算，缺少：" + "、".join(missing) + "。",
                "missing_fields": missing,
                "evidence_refs": evidence_refs,
            },
            "risks": [{
                "risk_id": "budget_risk_input_missing",
                "level": "medium",
                "description": "预算风险分析缺少完整测算口径，需要补齐后再作为正式结论。",
            }],
            "exceptions": [],
        }
    estimated_qty = float(demand_estimate["quantity"])
    estimated_contribution = estimated_qty * float(unit_margin)
    coverage_ratio = estimated_contribution / float(fixed_cost)
    break_even_qty = int(math.ceil(float(fixed_cost) / float(unit_margin)))
    if coverage_ratio >= 1.5:
        level = "low"
        level_cn = "低"
    elif coverage_ratio >= 1.1:
        level = "medium"
        level_cn = "中"
    else:
        level = "high"
        level_cn = "高"
    risks: list[dict[str, Any]] = []
    if level != "low":
        risks.append({
            "risk_id": "budget_coverage_pressure",
            "level": level,
            "description": f"预计边际贡献对预算的覆盖倍数为 {_format_ratio(coverage_ratio)}，预算覆盖压力偏{level_cn}。",
        })
    if demand_estimate.get("method") != "actual_or_forecast":
        risks.append({
            "risk_id": "budget_risk_estimate_basis",
            "level": "low" if level == "low" else "medium",
            "description": f"需求数量来自{demand_estimate.get('basis') or '历史趋势估算'}，正式决策前建议结合最新订单或销售预测复核。",
        })
    return {
        "rule_result": {
            "rule_id": "budget_risk.assessment",
            "rule_name": "预算风险评估",
            "status": "passed",
            "risk_level": level,
            "risk_level_cn": level_cn,
            "observed_value": coverage_ratio,
            "unit": unit,
            "message": (
                f"预算风险等级为{level_cn}：预计目标期间需求约 {_format_number(estimated_qty)} {unit}，"
                f"预计边际贡献约 {_format_number(estimated_contribution)} 元，"
                f"覆盖预算约 {_format_ratio(coverage_ratio)}。"
            ),
            "inputs": {
                "fixed_cost": fixed_cost,
                "unit_contribution_margin": unit_margin,
                "estimated_demand_qty": estimated_qty,
                "estimated_contribution": estimated_contribution,
                "coverage_ratio": coverage_ratio,
                "break_even_qty": break_even_qty,
                "target_period": demand_estimate.get("target_period"),
                "estimate_basis": demand_estimate.get("basis"),
            },
            "evidence_refs": evidence_refs,
        },
        "risks": risks,
        "exceptions": [],
    }


def _estimate_target_demand(context: str, aggregates: list[dict[str, Any]], prior_outputs: dict[str, Any]) -> dict[str, Any]:
    period_values = _period_values_from_aggregates(aggregates)
    if not period_values:
        forecast_values = _forecast_values_from_prior_outputs(prior_outputs)
        if forecast_values:
            return {
                "quantity": sum(forecast_values.values()),
                "target_period": _period_range_label(forecast_values),
                "method": "actual_or_forecast",
                "basis": "上游预测结果",
            }
        return {"quantity": None}
    target_year = _target_year_from_context(context, period_values)
    if _looks_like_second_half(context):
        target_months = list(range(7, 13))
        actual_target = {
            period: value
            for period, value in period_values.items()
            if period.startswith(f"{target_year:04d}-") and int(period[5:7]) in target_months
        }
        if len(actual_target) == len(target_months):
            return {
                "quantity": sum(actual_target.values()),
                "target_period": f"{target_year}H2",
                "method": "actual_or_forecast",
                "basis": "目标期间实际月度需求",
            }
        previous_h2 = {
            period: value
            for period, value in period_values.items()
            if period.startswith(f"{target_year - 1:04d}-") and int(period[5:7]) in target_months
        }
        current_ytd = {
            period: value
            for period, value in period_values.items()
            if period.startswith(f"{target_year:04d}-") and int(period[5:7]) <= 6
        }
        previous_ytd = {
            period: value
            for period, value in period_values.items()
            if period.startswith(f"{target_year - 1:04d}-") and int(period[5:7]) <= 6
        }
        if previous_h2:
            growth = 1.0
            if current_ytd and previous_ytd and sum(previous_ytd.values()) > 0:
                growth = sum(current_ytd.values()) / sum(previous_ytd.values())
            return {
                "quantity": sum(previous_h2.values()) * growth,
                "target_period": f"{target_year}H2",
                "method": "historical_projection",
                "basis": f"上年下半年需求 × 当年上半年同比系数({_format_ratio(growth)})",
            }
    latest = sorted(period_values.items())[-6:]
    if latest:
        return {
            "quantity": sum(value for _, value in latest),
            "target_period": "next_6_months",
            "method": "historical_projection",
            "basis": "最近6个月需求合计",
        }
    return {"quantity": None}


def _forecast_values_from_prior_outputs(prior_outputs: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for data in prior_outputs.values():
        if not isinstance(data, dict):
            continue
        analysis_result = data.get("analysis_result") if isinstance(data.get("analysis_result"), dict) else {}
        forecasts = analysis_result.get("forecasts") if isinstance(analysis_result.get("forecasts"), list) else []
        for item in forecasts:
            if not isinstance(item, dict):
                continue
            period = _normalize_period(item.get("date") or item.get("period"))
            value = _number(item.get("value") or item.get("price") or item.get("demand_qty"))
            if period and value is not None:
                values[period] = values.get(period, 0.0) + value
    return values


def _period_values_from_aggregates(aggregates: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for aggregate in aggregates:
        if not isinstance(aggregate, dict):
            continue
        period_values = aggregate.get("period_values") if isinstance(aggregate.get("period_values"), dict) else {}
        for period, value in period_values.items():
            normalized = _normalize_period(period)
            number = _number(value)
            if normalized and number is not None:
                existing = values.get(normalized)
                if existing is not None and abs(existing - number) < 1e-9:
                    continue
                values[normalized] = (existing or 0.0) + number
    return values


def _target_year_from_context(context: str, period_values: dict[str, float]) -> int:
    match = re.search(r"(20\d{2})", str(context or ""))
    if match:
        return int(match.group(1))
    years = sorted({int(period[:4]) for period in period_values if re.match(r"20\d{2}-\d{2}", period)})
    if "今年" in str(context or "") and years:
        return years[-1]
    return years[-1] if years else date.today().year


def _looks_like_second_half(context: str) -> bool:
    lowered = str(context or "").lower()
    return any(token in lowered for token in ("下半年", "h2", "second half", "7-12", "7到12", "7月至12月"))


def _normalize_period(value: Any) -> str:
    match = re.search(r"(20\d{2})\D?(\d{1,2})", str(value or ""))
    if not match:
        return ""
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return ""
    return f"{int(match.group(1)):04d}-{month:02d}"


def _period_range_label(values: dict[str, float]) -> str:
    periods = sorted(values)
    if not periods:
        return ""
    return periods[0] if len(periods) == 1 else f"{periods[0]}至{periods[-1]}"


def _format_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_ratio(value: Any) -> str:
    number = _number(value)
    if number is None:
        return str(value)
    return f"{number:.2f}倍"


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
