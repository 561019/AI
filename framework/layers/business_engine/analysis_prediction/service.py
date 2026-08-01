from __future__ import annotations

import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from framework.core import ROOT, standard_response
from framework.module_catalog import MODULE_BY_CODE


MODULE_CODE = "analysis-prediction"
DELIVERY_ROOT = ROOT / "联调文件-7.20-解压" / "analysis-prediction-engine-release-20260729-new"
SRC_ROOT = DELIVERY_ROOT / "src"


def get(handler: Any) -> bool:
    module = MODULE_BY_CODE[MODULE_CODE]
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in module.capabilities]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    module = MODULE_BY_CODE[MODULE_CODE]
    if handler.path != module.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = (
        envelope.get("target", {}).get("capability")
        or envelope.get("action")
        or envelope.get("payload", {}).get("action")
        or "analysis.business_metric"
    )
    if capability not in module.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={
            "code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE",
            "capability": capability,
            "provider_module": module.code,
        }))
        return

    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    try:
        result = _run_delivered_engine(capability, payload, envelope)
    except Exception as exc:
        handler.send(200, standard_response(envelope, "success", data={
            "state": "not_computable",
            "module": module.code,
            "module_name_cn": module.name_cn,
            "platform_capability": capability,
            "delivery_root": str(DELIVERY_ROOT),
            "received_payload": payload,
            "analysis_goal": payload.get("analysis_goal") or payload.get("user_goal"),
            "input_data_refs": payload.get("input_data_refs") or [],
            "error": {
                "code": "ANALYSIS_ENGINE_EVALUATION_FAILED",
                "message": str(exc),
            },
            "requires_upstream_data": True,
            "derived_from_input_data_refs": bool(payload.get("input_data_refs")),
        }))
        return

    handler.send(200, standard_response(envelope, "success", data={
        "state": "completed",
        "module": module.code,
        "module_name_cn": module.name_cn,
        "platform_capability": capability,
        "delivery_root": str(DELIVERY_ROOT),
        "received_payload": payload,
        "analysis_goal": payload.get("analysis_goal") or payload.get("user_goal"),
        "input_data_refs": payload.get("input_data_refs") or [],
        "derived_from_input_data_refs": bool(payload.get("input_data_refs")),
        "upstream_contract": result["request"],
        "analysis_result": result["response"],
        "normalized_task": {
            "capability_code": capability,
            "analysis_type": result["request"].get("analysis_type"),
            "source_action": payload.get("action") or envelope.get("action"),
            "interface": module.interface,
        },
    }))


def _run_delivered_engine(capability: str, payload: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    _ensure_delivery_importable()
    if capability == "analysis.financial_statement":
        return _run_financial_statement(payload, envelope)
    if capability == "analysis.price_forecast":
        return _run_price_forecast(payload, envelope)
    return _run_business_metric(payload, envelope)


def _ensure_delivery_importable() -> None:
    if not SRC_ROOT.exists():
        raise RuntimeError(f"delivered analysis prediction engine not found: {SRC_ROOT}")
    src = str(SRC_ROOT)
    if src not in sys.path:
        sys.path.insert(0, src)


def _run_business_metric(payload: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    goal = str(payload.get("analysis_goal") or payload.get("user_goal") or "")
    if _looks_like_forecast_goal(goal):
        return _run_price_forecast(payload, envelope, platform_analysis_type="business_metric")

    from analysis_prediction_engine.contracts.requests import BusinessMetricRequest
    from analysis_prediction_engine.services.business_metrics import analyze_business_metrics

    request_payload = _business_metric_request_from_payload(payload, envelope)
    request = BusinessMetricRequest.model_validate(request_payload)
    response = analyze_business_metrics(request)
    return {"request": request_payload, "response": _json_safe(response)}


def _run_price_forecast(
    payload: dict[str, Any],
    envelope: dict[str, Any],
    *,
    platform_analysis_type: str = "price_forecast",
) -> dict[str, Any]:
    from analysis_prediction_engine.contracts.requests import PriceForecastRequest
    from analysis_prediction_engine.services.price_forecast import forecast_prices

    records = _forecast_records_from_payload(payload)
    forecast_horizon = payload.get("forecast_horizon")
    if forecast_horizon in (None, "", 0):
        forecast_horizon = _forecast_horizon_from_target_period(payload, records)
    if forecast_horizon in (None, "", 0):
        forecast_horizon = _forecast_horizon_from_goal(payload)
    if forecast_horizon in (None, "", 0):
        raise ValueError("预测任务缺少明确预测周期，不能默认按下季度执行。请由意图分析或流程执行传入 forecast_horizon。")
    request_payload = {
        "schema_version": "v1",
        "trace_id": str(envelope.get("trace_id") or payload.get("trace_id") or "untraced"),
        "analysis_type": "price_forecast",
        "records": records,
        "forecast_horizon": int(forecast_horizon),
    }
    request = PriceForecastRequest.model_validate(request_payload)
    response = _json_safe(forecast_prices(request))
    response["platform_analysis_type"] = platform_analysis_type
    response["source_metric"] = _forecast_metric_name(payload)
    return {"request": request_payload, "response": response}


def _run_financial_statement(payload: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    from analysis_prediction_engine.contracts.requests import FinancialStatementRequest
    from analysis_prediction_engine.services.financial_analysis import analyze_financial_statement

    request_payload = {
        "schema_version": "v1",
        "trace_id": str(envelope.get("trace_id") or payload.get("trace_id") or "untraced"),
        "analysis_type": "financial_statement",
        "records": payload.get("records") or [],
    }
    request = FinancialStatementRequest.model_validate(request_payload)
    response = analyze_financial_statement(request)
    return {"request": request_payload, "response": _json_safe(response)}


def _business_metric_request_from_payload(payload: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    if payload.get("record") and payload.get("target_limits"):
        return {
            "schema_version": "v1",
            "trace_id": str(envelope.get("trace_id") or payload.get("trace_id") or "untraced"),
            "analysis_type": "business_metric",
            "record": payload["record"],
            "target_limits": payload["target_limits"],
        }
    metrics = _metrics_from_prior_outputs(payload)
    return {
        "schema_version": "v1",
        "trace_id": str(envelope.get("trace_id") or payload.get("trace_id") or "untraced"),
        "analysis_type": "business_metric",
        "record": {
            "period": metrics.get("period") or date.today().strftime("%Y-%m"),
            "source_record_id": metrics.get("source_record_id") or "workflow-prior-data",
            "revenue": _decimal_wire(metrics.get("revenue") or 0),
            "sales_cost": _decimal_wire(metrics.get("sales_cost") or 0),
            "delivery_cost": _decimal_wire(metrics.get("delivery_cost") or 0),
            "operating_cost": _decimal_wire(metrics.get("operating_cost") or 0),
        },
        "target_limits": payload.get("target_limits") or {
            "sales_cost_ratio": "60",
            "delivery_cost_ratio": "15",
            "operating_cost_ratio": "25",
        },
    }


def _forecast_records_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    if isinstance(payload.get("records"), list) and payload["records"]:
        return payload["records"]

    monthly_values = _monthly_values_from_prior_outputs(payload)
    if monthly_values:
        return monthly_values

    rows = _row_groups_from_prior_outputs(payload)
    metric_field = _pick_metric_field(rows, payload)
    records: list[dict[str, str]] = []
    for row in rows:
        fields = row.get("fields") or {}
        period = _period_from_fields(fields)
        value = _number(fields.get(metric_field)) if metric_field else None
        if not period or value is None:
            continue
        records.append({
            "date": f"{period}-01",
            "source_record_id": str(row.get("source_record_id") or f"workflow-data-{period}"),
            "price": _decimal_wire(value),
        })
    records = _dedupe_forecast_records(records)
    if len(records) < 3:
        raise RuntimeError("analysis prediction requires at least 3 monthly upstream records from data operation")
    return records


def _monthly_values_from_prior_outputs(payload: dict[str, Any]) -> list[dict[str, str]]:
    prior = payload.get("workflow_prior_outputs") if isinstance(payload.get("workflow_prior_outputs"), dict) else {}
    for data in prior.values():
        if not isinstance(data, dict):
            continue
        aggregate = _aggregate_from_output(data)
        period_values = aggregate.get("period_values") if isinstance(aggregate, dict) else None
        if isinstance(period_values, dict):
            records = []
            for period, value in sorted(period_values.items()):
                normalized = _normalize_period(period)
                if not normalized:
                    continue
                records.append({
                    "date": f"{normalized}-01",
                    "source_record_id": f"workflow-monthly-{normalized}",
                    "price": _decimal_wire(value),
                })
            if len(records) >= 3:
                return records
        monthly = aggregate.get("monthly_values") if isinstance(aggregate, dict) else None
        year = aggregate.get("year") if isinstance(aggregate, dict) else None
        if not isinstance(monthly, dict) or not year:
            continue
        records = []
        for month, value in sorted(monthly.items(), key=lambda item: int(item[0])):
            records.append({
                "date": f"{int(year):04d}-{int(month):02d}-01",
                "source_record_id": f"workflow-monthly-{int(year):04d}-{int(month):02d}",
                "price": _decimal_wire(value),
            })
        if len(records) >= 3:
            return records
    return []


def _normalize_period(value: Any) -> str:
    import re

    match = re.search(r"(20\d{2})\D+(\d{1,2})", str(value or ""))
    if not match:
        return ""
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return ""
    return f"{year:04d}-{month:02d}"


def _row_groups_from_prior_outputs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    prior = payload.get("workflow_prior_outputs") if isinstance(payload.get("workflow_prior_outputs"), dict) else {}
    groups: dict[str, dict[str, Any]] = {}
    for data in prior.values():
        if not isinstance(data, dict):
            continue
        storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else data
        items = storage.get("items") if isinstance(storage.get("items"), list) else data.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            key = "|".join(str(source.get(part) or "") for part in ("sheet", "row", "record_key"))
            if not key.strip("|"):
                key = str(item.get("record_id") or len(groups))
            group = groups.setdefault(key, {
                "fields": {},
                "source_record_id": item.get("record_id") or source.get("record_key") or key,
            })
            field_name = str(item.get("field_name") or "").strip()
            if field_name:
                group["fields"][field_name] = item.get("value")
    return list(groups.values())


def _aggregate_from_output(data: dict[str, Any]) -> dict[str, Any]:
    storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else data
    aggregate = storage.get("aggregate") if isinstance(storage.get("aggregate"), dict) else data.get("aggregate")
    return aggregate if isinstance(aggregate, dict) else {}


def _metrics_from_prior_outputs(payload: dict[str, Any]) -> dict[str, Any]:
    rows = _row_groups_from_prior_outputs(payload)
    if not rows:
        return {}
    fields = rows[-1].get("fields") or {}
    return {
        "period": _period_from_fields(fields),
        "source_record_id": rows[-1].get("source_record_id"),
        "revenue": _first_number(fields, ("revenue", "amount", "amount_cny", "收入", "金额")),
        "sales_cost": _first_number(fields, ("sales_cost", "unit_cost", "cost", "销售成本", "成本")),
        "delivery_cost": _first_number(fields, ("delivery_cost", "logistics_cost", "物流成本")),
        "operating_cost": _first_number(fields, ("operating_cost", "推广费用", "宣传制作", "客户培训")),
    }


def _pick_metric_field(rows: list[dict[str, Any]], payload: dict[str, Any]) -> str:
    preferred = [str(item).lower() for item in payload.get("metric_field_candidates", []) if str(item)]
    preferred.extend(["demand_qty", "demand", "需求量", "需求", "order_qty", "订单量", "sales_qty", "销量", "quantity", "数量"])
    scores: dict[str, int] = {}
    for row in rows:
        for name, value in (row.get("fields") or {}).items():
            if _number(value) is None:
                continue
            lower = str(name).lower()
            for index, candidate in enumerate(preferred):
                if lower == candidate:
                    scores[str(name)] = scores.get(str(name), 0) + 100 - index
                elif candidate in lower or lower in candidate:
                    scores[str(name)] = scores.get(str(name), 0) + 30 - min(index, 20)
    return max(scores.items(), key=lambda item: item[1])[0] if scores else ""


def _period_from_fields(fields: dict[str, Any]) -> str:
    for name in ("month", "year_month", "period", "date", "月份", "年月", "日期"):
        value = fields.get(name)
        period = _period_from_value(value)
        if period:
            return period
    for value in fields.values():
        period = _period_from_value(value)
        if period:
            return period
    return ""


def _period_from_value(value: Any) -> str:
    import re

    text = str(value or "")
    match = re.search(r"(20\d{2})\D+(\d{1,2})", text)
    if not match:
        return ""
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return ""
    return f"{year:04d}-{month:02d}"


def _first_number(fields: dict[str, Any], names: tuple[str, ...]) -> float | None:
    lowered = {str(key).lower(): key for key in fields}
    for name in names:
        key = lowered.get(name.lower())
        if key is not None:
            number = _number(fields.get(key))
            if number is not None:
                return number
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return float(value)
    import re

    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def _decimal_wire(value: Any) -> str:
    number = _number(value)
    if number is None:
        number = 0.0
    return format(Decimal(str(number)).quantize(Decimal("0.01")), "f")


def _dedupe_forecast_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    by_date: dict[str, dict[str, str]] = {}
    for record in records:
        by_date[record["date"]] = record
    return [by_date[key] for key in sorted(by_date)]


def _forecast_metric_name(payload: dict[str, Any]) -> str:
    candidates = payload.get("metric_field_candidates") if isinstance(payload.get("metric_field_candidates"), list) else []
    return str(candidates[0]) if candidates else "demand_or_business_metric"


def _forecast_horizon_from_goal(payload: dict[str, Any]) -> int | None:
    goal = str(payload.get("analysis_goal") or payload.get("user_goal") or "")
    lowered = goal.lower()
    if (
        "下一个月" in goal
        or "下个月" in goal
        or "下月" in goal
        or "下一月" in goal
        or "未来一个月" in goal
        or "未来1个月" in goal
        or "next month" in lowered
    ):
        return 1
    if "下一年" in goal or "未来一年" in goal or "后续一年" in goal or "未来12个月" in goal or "未来十二个月" in goal or "next year" in lowered:
        return 12
    if "下半年" in goal or "未来半年" in goal or "后半年" in goal or "half year" in lowered or "six months" in lowered:
        return 6
    match = re.search(r"(?:未来|后续|下)\s*(\d{1,2})\s*(?:个)?月", goal)
    if match:
        months = int(match.group(1))
        if 1 <= months <= 24:
            return months
    if "下季度" in goal or "next quarter" in goal.lower():
        return 3
    return None


def _forecast_horizon_from_target_period(payload: dict[str, Any], records: list[dict[str, Any]]) -> int | None:
    target = _normalize_period(payload.get("target_period"))
    if not target and payload.get("target_year") and payload.get("target_month"):
        try:
            target = f"{int(payload['target_year']):04d}-{int(payload['target_month']):02d}"
        except (TypeError, ValueError):
            target = ""
    if not target:
        return None
    source_periods = [_normalize_period(item.get("date")) for item in records if isinstance(item, dict)]
    source_periods = [item for item in source_periods if item]
    if not source_periods:
        return None
    latest = max(source_periods)
    target_year, target_month = (int(part) for part in target.split("-"))
    latest_year, latest_month = (int(part) for part in latest.split("-"))
    horizon = (target_year - latest_year) * 12 + (target_month - latest_month)
    if horizon <= 0:
        return 1
    return min(horizon, 24)


def _looks_like_forecast_goal(goal: str) -> bool:
    lowered = str(goal or "").lower()
    return any(word in lowered for word in ("预测", "下一个月", "下个月", "下月", "下季度", "下半年", "半年", "下一年", "未来一年", "一年", "趋势", "forecast", "predict", "next month", "next year"))


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return value
