from __future__ import annotations

import re
from typing import Any

from framework.core import standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import MODULE_BY_CODE


MODULE = MODULE_BY_CODE["data-operation"]


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in MODULE.capabilities]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path not in {MODULE.interface, "/api/v1/data/instructions"}:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability not in MODULE.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE", "capability": capability}))
        return
    actor = envelope.get("actor") or {}
    if not actor.get("tenant_id"):
        handler.send(422, standard_response(envelope, "failed", error={"code": "TENANT_CONTEXT_REQUIRED"}))
        return
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    payload = {
        **payload,
        "owner_account_id": payload.get("owner_account_id") or actor.get("user_id") or actor.get("actor_id"),
        "project_id": payload.get("project_id") or context.get("project_id"),
        "conversation_id": payload.get("conversation_id") or context.get("conversation_id"),
    }
    foundation_capability, foundation_payload = _translate(capability, payload)
    foundation_payload["_requesting_module"] = str((envelope.get("source") or {}).get("module") or "unknown")
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        actor,
        str(payload.get("platform_task_id") or envelope.get("request_id")),
        foundation_capability,
        "foundation",
        "foundation-gateway",
        foundation_payload,
        source_layer="business_engine",
        source_module="data-operation",
        context=context,
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=120 if foundation_capability == "foundation_data.write" else 30,
        caller={"layer": "business_engine", "module": "data-operation"},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        handler.send(502, standard_response(envelope, "failed", error={"code": "FOUNDATION_DATA_OPERATION_FAILED", "details": response}))
        return
    data = response.get("data") or {}
    if capability == "data.aggregate":
        data = _aggregate(data, payload)
    handler.send(200, standard_response(envelope, "success", data={
        "state": "completed",
        "module": "data-operation",
        "module_name_cn": "数据操作引擎",
        "platform_capability": capability,
        "storage_capability": foundation_capability,
        "storage_result": data,
        "received_summary": {
            "dataset": payload.get("dataset") or payload.get("collection"),
            "operation": payload.get("operation"),
            "record_count": len(payload.get("records") or []) if isinstance(payload.get("records"), list) else (1 if payload.get("record") else 0),
            "filters": payload.get("filters") or {},
            "trace_id": envelope.get("trace_id"),
        },
    }))


def _translate(capability: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    dataset = str(payload.get("dataset") or payload.get("collection") or "business_records")
    if capability == "data.catalog":
        return "foundation_data.catalog.list", {}
    if capability == "data.trace":
        return "foundation_data.access.trace", {"trace_id": payload.get("trace_id")}
    if capability in {"data.collect", "data.consolidate", "data.persist", "data.create", "data.update", "data.delete"}:
        operation = {
            "data.collect": payload.get("operation") or "upsert",
            "data.consolidate": payload.get("operation") or "upsert",
            "data.persist": payload.get("operation") or "upsert",
            "data.create": "insert",
            "data.update": "update",
            "data.delete": "delete",
        }[capability]
        records = payload.get("records")
        if not isinstance(records, list):
            record = payload.get("record") if isinstance(payload.get("record"), dict) else {
                key: value for key, value in payload.items()
                if key not in {"platform_task_id", "operation", "records", "record"}
            }
            records = [record]
        scope = {
            "owner_account_id": payload.get("owner_account_id"),
            "project_id": payload.get("project_id"),
            "conversation_id": payload.get("conversation_id"),
        }
        records = [{**scope, **record} if isinstance(record, dict) else record for record in records]
        return "foundation_data.write", {
            "dataset": dataset,
            "operation": operation,
            "records": records,
            **({"writes": payload["writes"]} if isinstance(payload.get("writes"), list) else {}),
        }
    if capability == "data.read" and payload.get("record_id"):
        return "foundation_data.read", {"dataset": dataset, "record_id": payload.get("record_id"), "tenant_id": payload.get("tenant_id")}
    query_filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    return "foundation_data.query", {
        "dataset": dataset,
        "filters": _physical_query_filters(dataset, query_filters),
        "tenant_id": payload.get("tenant_id"),
        "limit": payload.get("limit", 100),
        "compact": bool(payload.get("compact")),
    }


def _physical_query_filters(dataset: str, filters: dict[str, Any]) -> dict[str, Any]:
    if dataset != "extracted_fields":
        return filters
    physical_keys = {
        "parse_job_id", "file_id", "object_id", "sha256", "record_id",
        "owner_account_id", "project_id", "conversation_id", "tenant_id",
    }
    return {key: value for key, value in filters.items() if key in physical_keys}


def _aggregate(data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items") or []
    items = _filter_items_by_business_scope(raw_items, payload)
    operation = str(payload.get("aggregate_operation") or payload.get("operation") or "").lower()
    goal = str(payload.get("analysis_goal") or payload.get("utterance") or payload.get("query") or "")
    if raw_items and not items and _has_business_scope(payload):
        return {**data, "items": [], "aggregate": _scope_mismatch_summary(raw_items, payload)}
    if operation == "business_object_detail":
        return {**data, "items": items, "aggregate": _business_object_detail(items, payload)}
    if operation == "budget_summary":
        return {**data, "items": items, "aggregate": _budget_summary(items, payload)}
    if operation == "latest_metric_by_entity":
        return {**data, "items": items, "aggregate": _latest_metric_by_entity(items, payload)}
    scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
    allow_entity_list = scope.get("scope_key") != "customer_feedback"
    if operation in {"list", "list_distinct", "entity_list", "enumerate"} or (allow_entity_list and (_looks_like_entity_list_goal(goal) or _looks_like_group_count_goal(goal))):
        return {**data, "items": items, "aggregate": _list_entity_summary(items, payload)}
    if operation in {"monthly_max_metric", "monthly_metric_series"}:
        return {**data, "items": items, "aggregate": _monthly_max_metric(items, payload)}
    if operation in {"retrieve", "query", "search", "summarize", "summary", "analyze", "analyse", "retrieve_and_summarize", "retrieve_and_rank", "recommend", "rank", "统计", "汇总", "分析"}:
        scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
        should_list_entities = scope.get("scope_key") != "customer_feedback" and (_looks_like_entity_list_goal(goal) or _looks_like_group_count_goal(goal))
        entity_summary = _list_entity_summary(items, payload) if should_list_entities else None
        if entity_summary and entity_summary.get("names"):
            return {**data, "items": items, "aggregate": entity_summary}
        summary = _summarize_relevant_rows(items, payload)
        if summary:
            return {**data, "items": items, "aggregate": summary}
    if operation == "business_summary":
        return {**data, "aggregate": {
            "operation": "unsupported",
            "answer": "",
            "detail": "business_summary 已废弃。数据操作模块只接受明确命名、输入输出清楚的结构化算子。",
            "items_count": len(items),
            "error": {"code": "UNSUPPORTED_AGGREGATE_OPERATION", "operation": "business_summary"},
            "requires_model_reasoning": True,
        }}
    field = payload.get("aggregate_field")
    if not field:
        return {**data, "aggregate": {
            "operation": "model_required",
            "answer": "",
            "detail": "当前数据操作模块没有收到明确的结构化聚合字段或算子，已将授权数据交给后续模型节点形成业务回答。",
            "items_count": len(items),
            "evidence": [],
            "requires_model_reasoning": True,
        }}
    values = [item.get(field) for item in items if isinstance(item.get(field), (int, float))]
    return {**data, "aggregate": {"operation": payload.get("aggregate_operation", "sum"), "field": field, "value": sum(values)}}


def _has_business_scope(payload: dict[str, Any]) -> bool:
    scope = payload.get("business_scope")
    return isinstance(scope, dict) and str(scope.get("scope_key") or "generic") != "generic"


def _filter_items_by_business_scope(items: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
    if not scope or str(scope.get("scope_key") or "generic") == "generic":
        return items
    preferred_sheets = [str(item).strip() for item in (scope.get("preferred_sheets") or []) if str(item).strip()]
    allowed_fields = [str(item).strip().lower() for item in (scope.get("allowed_fields") or []) if str(item).strip()]
    entity_id = str(scope.get("entity_id") or "").strip().upper()
    groups = _row_groups(items)
    kept_keys: set[str] = set()
    for key, group in groups.items():
        sheet = str(group.get("sheet") or "")
        fields = group.get("fields") or {}
        text = f"{sheet} {fields}".upper()
        sheet_ok = not preferred_sheets or any(sheet == name or name in sheet or sheet in name for name in preferred_sheets)
        entity_ok = not entity_id or entity_id in text
        field_ok = not allowed_fields or any(_field_allowed(name, allowed_fields) for name in fields)
        filter_ok = _row_matches_payload_filters(fields, payload)
        if sheet_ok and entity_ok and field_ok and filter_ok:
            kept_keys.add(key)
    result: list[dict[str, Any]] = []
    for item in items:
        key = _row_key(item)
        if key not in kept_keys:
            continue
        if allowed_fields and not _field_allowed(str(item.get("field_name") or ""), allowed_fields):
            if entity_id and entity_id in str(item.get("value") or "").upper():
                result.append(item)
            continue
        result.append(item)
    return result


def _row_groups(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _row_key(item)
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        group = groups.setdefault(key, {"sheet": source.get("sheet") or item.get("sheet"), "row": source.get("row") or item.get("row"), "fields": {}, "items": []})
        field_name = str(item.get("field_name") or "")
        if field_name:
            group["fields"][field_name] = item.get("value")
        group["items"].append(item)
    return groups


def _row_key(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    key = "|".join(str(source.get(part) or "") for part in ("sheet", "row", "record_key"))
    if not key.strip("|"):
        key = str(item.get("record_id") or id(item))
    return key


def _field_allowed(field_name: str, allowed_fields: list[str]) -> bool:
    lower = str(field_name or "").strip().lower()
    return any(lower == allowed or allowed in lower or lower in allowed for allowed in allowed_fields)


def _row_matches_payload_filters(fields: dict[str, Any], payload: dict[str, Any]) -> bool:
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    business_filters = {
        key: value for key, value in filters.items()
        if key not in {"parse_job_id", "file_id", "object_id", "sha256", "record_id", "tenant_id", "owner_account_id", "project_id", "conversation_id"}
        and value not in (None, "")
    }
    if not business_filters:
        return True
    for key, expected in business_filters.items():
        actual = _field_value_for_filter(fields, str(key))
        if actual in (None, ""):
            continue
        if isinstance(expected, list):
            if not any(_value_matches_filter(actual, item) for item in expected):
                return False
        elif not _value_matches_filter(actual, expected):
            return False
    return True


def _field_value_for_filter(fields: dict[str, Any], key: str) -> Any:
    aliases = {
        "region": ("region", "区域", "地区", "销售区域"),
        "dealer": ("dealer", "dealer_name", "distributor", "经销商", "经销商名称", "客户", "客户名称"),
        "dealer_name": ("dealer_name", "dealer", "distributor", "经销商", "经销商名称", "客户", "客户名称"),
        "product_id": ("product_id", "product", "产品编号", "产品ID", "产品"),
        "month": ("month", "月份", "年月", "period", "date", "日期"),
        "year": ("year", "年份", "年度", "年月", "period", "date", "日期"),
    }
    candidates = aliases.get(key.lower(), (key,))
    lowered = {str(name).strip().lower(): value for name, value in fields.items()}
    for candidate in candidates:
        direct = lowered.get(str(candidate).strip().lower())
        if direct not in (None, ""):
            return direct
    for name, value in fields.items():
        lower_name = str(name).strip().lower()
        if any(str(candidate).strip().lower() in lower_name or lower_name in str(candidate).strip().lower() for candidate in candidates):
            return value
    return None


def _value_matches_filter(actual: Any, expected: Any) -> bool:
    actual_text = str(actual).strip().lower()
    expected_text = str(expected).strip().lower()
    if not expected_text:
        return True
    return actual_text == expected_text or expected_text in actual_text or actual_text in expected_text


def _scope_mismatch_summary(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
    sheets = sorted({
        str((item.get("source") or {}).get("sheet") or item.get("sheet") or "")
        for item in items
        if isinstance(item, dict)
    })
    return {
        "operation": "data_scope_mismatch",
        "answer": "未能在正确的业务数据范围内形成可信结果。",
        "detail": "数据操作引擎已阻止把不同业务对象的数据混合成答案。",
        "business_scope": scope,
        "available_sheets": [sheet for sheet in sheets if sheet][:20],
        "items_count": len(items),
        "error": {"code": "BUSINESS_SCOPE_NO_MATCH"},
        "requires_model_reasoning": False,
    }


def _business_object_detail(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
    groups = _row_groups(items)
    fields: dict[str, Any] = {}
    evidence: list[str] = []
    for group in groups.values():
        for name, value in (group.get("fields") or {}).items():
            if name not in fields and value not in (None, ""):
                fields[name] = value
        for item in (group.get("items") or [])[:4]:
            evidence.append(_evidence_label(item))
    label = str(scope.get("label") or payload.get("data_object") or "业务对象")
    entity_id = str(scope.get("entity_id") or "")
    title = f"已找到 {entity_id} 的{label}。" if entity_id else f"已找到{label}相关资料。"
    if not fields:
        title = f"未找到可展示的{label}字段。"
    return {
        "operation": "business_object_detail",
        "answer": title,
        "detail": fields,
        "data_object": label,
        "entity_id": entity_id,
        "row_count": len(groups),
        "evidence": evidence[:16],
        "recommendation": "请按以上字段核对业务口径；如需继续分析，可指定价格、成本、预算或适用区域。",
    }


def _budget_summary(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    groups = _row_groups(items)
    rows: list[dict[str, Any]] = []
    subtotal = 0.0
    declared_total: float | None = None
    evidence: list[str] = []
    price_cost: dict[str, Any] = {}
    price_cost_evidence: list[str] = []
    for group in groups.values():
        fields = group.get("fields") or {}
        for field_name, value in fields.items():
            if value in (None, "") or not _is_price_cost_field(str(field_name)):
                continue
            price_cost.setdefault(str(field_name), value)
            if len(price_cost_evidence) < 8:
                price_cost_evidence.extend((_evidence_label(item) for item in (group.get("items") or [])[:2]))
        name = _first_field(fields, ("item_name", "budget_item", "项目", "预算项", "费用项", "项目名称"))
        amount = _first_number(fields, ("amount_cny", "budget_amount", "金额", "预算金额"))
        if name is None and amount is None:
            continue
        is_total_row = "合计" in str(name or "")
        if amount is not None and is_total_row:
            declared_total = amount
        elif amount is not None:
            subtotal += amount
        rows.append({"item": name, "amount_cny": amount})
        for item in (group.get("items") or [])[:2]:
            evidence.append(_evidence_label(item))
    total = declared_total if declared_total is not None else subtotal
    return {
        "operation": "budget_summary",
        "answer": f"已汇总项目预算，共 {len(rows)} 个预算项，金额合计 {_format_number(total)} 元。" if rows else "未找到可汇总的预算项。",
        "detail": rows,
        "total_amount_cny": total,
        "subtotal_amount_cny": subtotal,
        "declared_total_amount_cny": declared_total,
        "price_cost": price_cost,
        "price_cost_evidence": price_cost_evidence[:8],
        "row_count": len(rows),
        "evidence": evidence[:16],
        "recommendation": "请确认预算项是否完整；审批前应重点核对预备费、宣传制作、物流保障和客户培训等费用。",
    }


def _latest_metric_by_entity(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    rows = _row_groups(items)
    if not rows:
        return {
            "operation": "latest_metric_by_entity",
            "answer": "\u5f53\u524d\u6388\u6743\u6570\u636e\u4e2d\u6ca1\u6709\u627e\u5230\u53ef\u8ba1\u7b97\u7684\u8868\u683c\u884c\u3002",
            "detail": "\u5df2\u5c1d\u8bd5\u6309\u884c\u8fd8\u539f\u7ed3\u6784\u5316\u5b57\u6bb5\uff0c\u4f46\u6ca1\u6709\u5f62\u6210\u53ef\u7528\u8bb0\u5f55\u3002",
            "rows": [],
            "entity_count": 0,
            "evidence": [],
        }
    entity_field = _choose_field_from_candidates(rows, payload.get("entity_field_candidates"))
    metric_field = str(payload.get("metric_field") or "").strip()
    if metric_field and not _field_exists(rows, metric_field):
        metric_field = ""
    if not metric_field:
        metric_field = _choose_field_from_candidates(rows, payload.get("metric_field_candidates"))
    if not entity_field:
        entity_field = _infer_entity_field(rows)
    rows_for_time = _rows_having_fields(rows, [entity_field, metric_field]) if entity_field and metric_field else rows
    time_field = _choose_field_from_candidates(rows_for_time, payload.get("time_field_candidates"))
    if not time_field:
        time_field, _ = _infer_month_metric_fields(rows_for_time)
    if not metric_field:
        _, metric_field = _infer_month_metric_fields(rows)
    if not entity_field or not time_field or not metric_field:
        return {
            "operation": "latest_metric_by_entity",
            "answer": "\u5f53\u524d\u6388\u6743\u6570\u636e\u8fd8\u4e0d\u8db3\u4ee5\u6309\u5b9e\u4f53\u8ba1\u7b97\u6700\u8fd1\u4e00\u671f\u6307\u6807\u3002",
            "detail": {
                "entity_field": entity_field,
                "time_field": time_field,
                "metric_field": metric_field,
                "available_fields": _available_field_names(rows)[:40],
            },
            "rows": [],
            "entity_count": 0,
            "evidence": [],
            "error": {"code": "LATEST_METRIC_FIELDS_NOT_IDENTIFIED"},
        }

    grouped: dict[str, dict[str, Any]] = {}
    for group in rows.values():
        fields = group.get("fields") or {}
        entity = str(fields.get(entity_field) or "").strip()
        metric_value = _number(fields.get(metric_field))
        period = _period_from_fields(fields, 0) or _period_from_value(fields.get(time_field), 0)
        if not entity or metric_value is None or not period:
            continue
        current = grouped.get(entity)
        if not current or str(period) > str(current.get("period") or ""):
            grouped[entity] = {
                "entity": entity,
                "period": period,
                "metric": metric_field,
                "value": metric_value,
                "evidence": _group_evidence(group, limit=4),
            }
        elif current and period == current.get("period"):
            current["value"] = float(current.get("value") or 0) + metric_value
            current["evidence"] = (current.get("evidence") or [])[:4]

    result_rows = sorted(grouped.values(), key=lambda item: str(item.get("entity") or ""))
    latest_period = max((str(item.get("period") or "") for item in result_rows), default="")
    if not result_rows:
        return {
            "operation": "latest_metric_by_entity",
            "answer": "\u672a\u627e\u5230\u540c\u65f6\u5305\u542b\u5b9e\u4f53\u3001\u65f6\u95f4\u548c\u6307\u6807\u503c\u7684\u4e1a\u52a1\u8bb0\u5f55\u3002",
            "detail": {
                "entity_field": entity_field,
                "time_field": time_field,
                "metric_field": metric_field,
            },
            "rows": [],
            "entity_count": 0,
            "evidence": [],
        }
    display_rows = [
        {
            "entity": item["entity"],
            "period": item["period"],
            "metric": item["metric"],
            "value": item["value"],
        }
        for item in result_rows
    ]
    evidence: list[str] = []
    for item in result_rows:
        evidence.extend(item.get("evidence") or [])
    return {
        "operation": "latest_metric_by_entity",
        "answer": _format_latest_metric_answer(entity_field, metric_field, display_rows),
        "detail": {
            "entity_field": entity_field,
            "time_field": time_field,
            "metric_field": metric_field,
            "latest_period": latest_period,
        },
        "entity_count": len(display_rows),
        "latest_period": latest_period,
        "rows": display_rows,
        "evidence": evidence[:16],
    }


def _infer_entity_field(rows: dict[str, dict[str, Any]]) -> str:
    candidates = ["product_name", "product", "product_id", "dealer_name", "dealer", "customer_name", "customer", "region"]
    return _choose_field_from_candidates(rows, candidates)


def _rows_having_fields(rows: dict[str, dict[str, Any]], field_names: list[str]) -> dict[str, dict[str, Any]]:
    required = [str(name or "").strip().lower() for name in field_names if str(name or "").strip()]
    if not required:
        return rows
    result: dict[str, dict[str, Any]] = {}
    for key, row in rows.items():
        field_lookup = {str(name).strip().lower() for name in (row.get("fields") or {})}
        if all(name in field_lookup for name in required):
            result[key] = row
    return result or rows


def _available_field_names(rows: dict[str, dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for row in rows.values():
        for name in (row.get("fields") or {}):
            if name not in names:
                names.append(str(name))
    return names


def _group_evidence(group: dict[str, Any], *, limit: int) -> list[str]:
    evidence = group.get("evidence") if isinstance(group.get("evidence"), list) else []
    if evidence:
        return evidence[:limit]
    return [_evidence_label(item) for item in (group.get("items") or [])[:limit] if isinstance(item, dict)]


def _format_latest_metric_answer(entity_field: str, metric_field: str, rows: list[dict[str, Any]]) -> str:
    parts = [
        f"{item.get('entity')}: {item.get('period')} {metric_field}={_format_number(float(item.get('value') or 0))}"
        for item in rows[:20]
    ]
    suffix = f"\uff0c\u7b49 {len(rows)} \u9879" if len(rows) > 20 else ""
    return f"\u6309 {entity_field} \u627e\u5230 {len(rows)} \u4e2a\u5bf9\u8c61\u7684\u6700\u8fd1\u4e00\u671f {metric_field}\uff1a" + "\uff1b".join(parts) + suffix + "\u3002"


def _is_price_cost_field(field_name: str) -> bool:
    lower = str(field_name or "").lower()
    return any(token in lower for token in (
        "unit_price", "price", "unit_cost", "cost", "gross_margin_rate",
        "fixed_project_budget", "margin", "budget",
        "list_price", "standard_variable_cost", "variable_cost", "contribution_margin", "unit_margin",
        "unit", "uom",
        "\u5355\u4ef7", "\u4ef7\u683c", "\u6210\u672c", "\u6bdb\u5229",
        "\u56fa\u5b9a\u9879\u76ee\u9884\u7b97", "\u9884\u7b97", "\u5355\u4f4d",
    ))


def _first_field(fields: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in fields and fields.get(name) not in (None, ""):
            return fields.get(name)
    lowered = {str(key).lower(): key for key in fields}
    for name in names:
        key = lowered.get(name.lower())
        if key and fields.get(key) not in (None, ""):
            return fields.get(key)
    return None


def _month_from_value(value: Any, target_year: int) -> int | None:
    text = str(value)
    if target_year:
        match = re.search(rf"{target_year}\D+(\d{{1,2}})", text)
        if match:
            month = int(match.group(1))
            return month if 1 <= month <= 12 else None
    match = re.search(r"(20\d{2})\D+(\d{1,2})", text)
    if match and (not target_year or int(match.group(1)) == target_year):
        month = int(match.group(2))
        return month if 1 <= month <= 12 else None
    match = re.search(r"(?<!\d)(\d{1,2})(?:月|month)(?!\d)", text, re.IGNORECASE)
    if match:
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    return None


def _first_number(fields: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _first_field(fields, (name,))
        number = _number(value)
        if number is not None:
            return number
    return None


def _summarize_relevant_rows(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any] | None:
    row_groups: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        key = "|".join(str(source.get(part) or "") for part in ("sheet", "row", "record_key"))
        if not key.strip("|"):
            key = str(item.get("record_id") or len(row_groups))
        group = row_groups.setdefault(key, {"sheet": source.get("sheet"), "row": source.get("row"), "fields": {}, "evidence": []})
        group["fields"][str(item.get("field_name") or "").strip()] = item.get("value")
        if len(group["evidence"]) < 6:
            group["evidence"].append(_evidence_label(item))
    if not row_groups:
        return None
    access_contract = payload.get("data_access_contract") if isinstance(payload.get("data_access_contract"), dict) else {}
    data_object = str(
        payload.get("data_object")
        or payload.get("object")
        or access_contract.get("business_object_label")
        or access_contract.get("sheet_name")
        or ""
    ).strip()
    goal = " ".join(
        str(part).strip()
        for part in (
            payload.get("analysis_goal") or payload.get("utterance") or "",
            access_contract.get("semantic_query") or "",
            data_object,
            " ".join(str(item) for item in (payload.get("fields") or [])) if isinstance(payload.get("fields"), list) else "",
        )
        if str(part).strip()
    )
    preferred_sheet = (
        str(access_contract.get("sheet_name") or "").strip()
        or _sheet_hint_from_goal(goal, row_groups)
    )
    groups = [
        group for group in row_groups.values()
        if not preferred_sheet or str(group.get("sheet") or "") == preferred_sheet
    ]
    if not groups and preferred_sheet:
        groups = [
            group for group in row_groups.values()
            if preferred_sheet in str(group.get("sheet") or "") or str(group.get("sheet") or "") in preferred_sheet
        ]
    if not groups:
        return None
    numeric: dict[str, list[float]] = {}
    evidence: list[str] = []
    for group in groups:
        evidence.extend((group.get("evidence") or [])[:2])
        for field, value in (group.get("fields") or {}).items():
            number = _number(value)
            if number is None:
                continue
            numeric.setdefault(str(field), []).append(number)
    metrics = {
        field: {
            "count": len(values),
            "sum": sum(values),
            "max": max(values),
            "min": min(values),
        }
        for field, values in numeric.items()
    }
    source_label = preferred_sheet or "当前授权数据"
    return {
        "operation": "business_data_summary",
        "answer": f"已找到{source_label}相关数据，共 {len(groups)} 行业务记录。",
        "detail": f"已按用户问题定位到“{source_label}”，并汇总其中可计算的数值字段。",
        "data_object": source_label,
        "row_count": len(groups),
        "numeric_metrics": metrics,
        "evidence": evidence[:16],
        "recommendation": "请结合字段口径确认后，再据此制定后续执行意见。",
    }


def _monthly_max_metric(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    """Execute an explicit monthly_max_metric operation only."""
    operation_name = str(payload.get("aggregate_operation") or payload.get("operation") or "monthly_max_metric").lower()
    time_field = str(payload.get("time_field") or "").strip()
    metric_field = str(payload.get("metric_field") or "").strip()
    target_year = (
        payload.get("year_filter")
        or payload.get("target_year")
        or _year_from_text(str(payload.get("analysis_goal") or ""))
        or payload.get("year")
    )
    try:
        target_year = int(target_year) if target_year else None
    except (TypeError, ValueError):
        target_year = None
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("field_name"):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        key = "|".join(str(source.get(part) or "") for part in ("sheet", "row", "record_key"))
        if not key.strip("|"):
            key = str(item.get("record_id") or len(rows))
        row = rows.setdefault(key, {"fields": {}, "evidence": []})
        row["fields"][str(item.get("field_name")).strip()] = item.get("value")
        if len(row["evidence"]) < 4:
            row["evidence"].append(_evidence_label(item))
    if time_field and not _field_exists(rows, time_field):
        time_field = ""
    if metric_field and not _field_exists(rows, metric_field):
        metric_field = ""
    if not time_field:
        time_field = _choose_field_from_candidates(rows, payload.get("time_field_candidates"))
    if not metric_field:
        metric_field = _choose_field_from_candidates(rows, payload.get("metric_field_candidates"))
    if not time_field or not metric_field:
        inferred_time, inferred_metric = _infer_month_metric_fields(rows)
        time_field = time_field or inferred_time
        metric_field = metric_field or inferred_metric
    if not time_field or not metric_field:
        return {
            "operation": "monthly_max_metric",
            "answer": "",
            "detail": "monthly_max_metric 需要明确提供或识别 time_field 和 metric_field。",
            "error": {
                "code": "STRUCTURED_OPERATION_INPUT_REQUIRED",
                "required": ["time_field", "metric_field"],
            },
        }
    monthly: dict[int, float] = {}
    period_values: dict[str, float] = {}
    evidence: dict[int, list[str]] = {}
    period_evidence: dict[str, list[str]] = {}
    for row in rows.values():
        time_value = row["fields"].get(time_field)
        metric_value = _number(row["fields"].get(metric_field))
        if time_value is None or metric_value is None:
            continue
        month = _month_from_value(time_value, target_year or 0)
        if month is None:
            month = _month_from_fields(row["fields"], target_year or 0)
        period = _period_from_fields(row["fields"], target_year or 0)
        if month is None:
            continue
        monthly[month] = monthly.get(month, 0.0) + metric_value
        evidence.setdefault(month, []).extend(row["evidence"][:4])
        if period:
            period_values[period] = period_values.get(period, 0.0) + metric_value
            period_evidence.setdefault(period, []).extend(row["evidence"][:4])
    if not monthly:
        return {
            "operation": "monthly_max_metric",
            "answer": "",
            "detail": "没有找到符合明确字段和年份条件的月度数据。",
            "error": {"code": "STRUCTURED_OPERATION_NO_MATCH"},
            "evidence": [],
        }
    month, value = max(monthly.items(), key=lambda pair: pair[1])
    return {
        "operation": operation_name,
        "answer": (
            f"已形成 {len(period_values) or len(monthly)} 个月度{metric_field}序列，可交给分析预测引擎使用。"
            if operation_name == "monthly_metric_series"
            else f"{month} 月的 {metric_field} 汇总值最高，为 {_format_number(value)}。"
        ),
        "time_field": time_field,
        "metric_field": metric_field,
        "year": target_year,
        "month": month,
        "max_month": month,
        "value": value,
        "max_value": value,
        "period_values": {key: val for key, val in sorted(period_values.items())},
        "monthly_values": {str(key): val for key, val in sorted(monthly.items())},
        "evidence": (period_evidence.get(max(period_values, key=period_values.get), []) if period_values else evidence.get(month, []))[:8],
    }


def _period_from_fields(fields: dict[str, Any], target_year: int) -> str | None:
    for name, value in fields.items():
        lower = str(name).lower()
        if any(token in lower for token in ("date", "month", "year_month", "period", "日期", "月份", "年月", "期间")):
            period = _period_from_value(value, target_year)
            if period:
                return period
    year = None
    month = None
    for name, value in fields.items():
        lower = str(name).lower()
        if lower in {"year", "年份"} or "年度" in lower:
            parsed = _number(value)
            if parsed is not None:
                year = int(parsed)
        if lower in {"month", "月份", "月"}:
            parsed = _number(value)
            if parsed is not None:
                month = int(parsed)
    if year and month and 1 <= month <= 12 and (not target_year or year == target_year):
        return f"{year:04d}-{month:02d}"
    if target_year and month and 1 <= month <= 12:
        return f"{target_year:04d}-{month:02d}"
    return None


def _period_from_value(value: Any, target_year: int) -> str | None:
    text = str(value or "")
    match = re.search(r"(20\d{2})\D+(\d{1,2})", text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        if 1 <= month <= 12 and (not target_year or year == target_year):
            return f"{year:04d}-{month:02d}"
    return None


def _field_exists(rows: dict[str, dict[str, Any]], field_name: str) -> bool:
    target = str(field_name or "").strip().lower()
    if not target:
        return False
    return any(target == str(name).strip().lower() for row in rows.values() for name in (row.get("fields") or {}))


def _choose_field_from_candidates(rows: dict[str, dict[str, Any]], candidates: Any) -> str:
    candidate_list = [str(item).strip().lower() for item in (candidates or []) if str(item).strip()]
    if not candidate_list:
        return ""
    scores: dict[str, int] = {}
    for row in rows.values():
        for name, value in (row.get("fields") or {}).items():
            if value in (None, ""):
                continue
            lower = str(name).strip().lower()
            for index, candidate in enumerate(candidate_list):
                if lower == candidate:
                    scores[str(name)] = scores.get(str(name), 0) + 100 - index
                elif candidate in lower or lower in candidate:
                    scores[str(name)] = scores.get(str(name), 0) + 30 - min(index, 20)
    return max(scores.items(), key=lambda item: item[1])[0] if scores else ""


def _infer_month_metric_fields(rows: dict[str, dict[str, Any]]) -> tuple[str, str]:
    time_candidates: dict[str, int] = {}
    metric_candidates: dict[str, int] = {}
    for row in rows.values():
        fields = row.get("fields") or {}
        for name, value in fields.items():
            lower = str(name).lower()
            if any(token in lower for token in ("date", "month", "period", "年月", "月份", "日期", "月")):
                time_candidates[str(name)] = time_candidates.get(str(name), 0) + 2
            elif _month_from_value(value, 0) is not None:
                time_candidates[str(name)] = time_candidates.get(str(name), 0) + 1
            if _number(value) is None:
                continue
            if any(token in lower for token in ("demand_qty", "demand", "需求量", "需求")):
                metric_candidates[str(name)] = metric_candidates.get(str(name), 0) + 5
            elif any(token in lower for token in ("order_qty", "order", "订单量", "订单", "sales_qty", "销量", "销售量", "quantity", "qty", "amount", "金额")):
                metric_candidates[str(name)] = metric_candidates.get(str(name), 0) + 2
    time_field = max(time_candidates.items(), key=lambda item: item[1])[0] if time_candidates else ""
    metric_field = max(metric_candidates.items(), key=lambda item: item[1])[0] if metric_candidates else ""
    return time_field, metric_field


def _year_from_text(text: str) -> int | None:
    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


def _month_from_fields(fields: dict[str, Any], target_year: int) -> int | None:
    for name, value in fields.items():
        lower = name.lower()
        if any(token in lower for token in ("date", "month", "月份", "年月", "期间", "period")):
            month = _month_from_value(value, target_year)
            if month:
                return month
    year = None
    month = None
    for name, value in fields.items():
        lower = name.lower()
        if lower in {"year", "年份"} or "年度" in lower:
            parsed = _number(value)
            if parsed:
                year = int(parsed)
        if lower in {"month", "月份"} or "月" == lower:
            parsed = _number(value)
            if parsed:
                month = int(parsed)
    if year == target_year and month and 1 <= month <= 12:
        return month
    return None


def _month_from_value(value: Any, target_year: int) -> int | None:
    text = str(value)
    match = re.search(rf"{target_year}[-/.年 ]+(\d{{1,2}})", text)
    if match:
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    match = re.search(r"(\d{1,2})\s*月", text)
    if match and str(target_year) in text:
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    return None


def _month_from_value(value: Any, target_year: int) -> int | None:
    text = str(value)
    if target_year:
        match = re.search(rf"{target_year}\D+(\d{{1,2}})", text)
        if match:
            month = int(match.group(1))
            return month if 1 <= month <= 12 else None
    match = re.search(r"(20\d{2})\D+(\d{1,2})", text)
    if match and (not target_year or int(match.group(1)) == target_year):
        month = int(match.group(2))
        return month if 1 <= month <= 12 else None
    match = re.search(r"(?<!\d)(\d{1,2})(?:月|month)(?!\d)", text, re.IGNORECASE)
    if match:
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    return None


def _demand_from_fields(fields: dict[str, Any]) -> float | None:
    candidates = []
    for name, value in fields.items():
        lower = name.lower()
        if any(token in lower for token in ("需求", "需求量", "demand", "order", "订单", "销量", "销售量", "quantity", "qty")):
            number = _number(value)
            if number is not None:
                candidates.append(number)
    if candidates:
        return max(candidates)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _month_from_value(value: Any, target_year: int) -> int | None:
    text = str(value)
    if target_year:
        match = re.search(rf"{target_year}\D+(\d{{1,2}})", text)
        if match:
            month = int(match.group(1))
            return month if 1 <= month <= 12 else None
    match = re.search(r"(20\d{2})\D+(\d{1,2})", text)
    if match and (not target_year or int(match.group(1)) == target_year):
        month = int(match.group(2))
        return month if 1 <= month <= 12 else None
    match = re.search(r"(?<!\d)(\d{1,2})(?:月|month)(?!\d)", text, re.IGNORECASE)
    if match:
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    return None


def _evidence_label(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    field = item.get("field_name")
    location = f"{source.get('sheet') or '数据'} 第{source.get('row') or '?'}行"
    return f"{location} {field}: {item.get('value')}"


def _format_number(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _looks_like_group_count_goal(goal: str) -> bool:
    text = goal.lower()
    has_dimension = any(token in text for token in ("经销商", "客户", "供应商", "dealer", "distributor", "customer", "supplier"))
    has_count_or_list = any(token in text for token in ("几个", "多少", "多少个", "数量", "总数", "个数", "参与", "合作", "列举", "名单", "清单", "一一列举", "分别", "哪些", "有哪些", "所有", "全部", "确定", "去重"))
    return has_dimension and has_count_or_list


def _preferred_sheet_from_goal(goal: str) -> str | None:
    text = goal.lower()
    if any(token in text for token in ("经销商订单", "经销商", "dealer", "distributor")):
        return "经销商订单"
    if any(token in text for token in ("需求历史", "需求", "demand")):
        return "需求历史"
    return None


def _sheet_matches(group: dict[str, Any], preferred_sheet: str | None) -> bool:
    if not preferred_sheet:
        return True
    evidence = " ".join(str(item) for item in group.get("evidence") or [])
    return preferred_sheet in evidence


def _format_name_list(names: list[str]) -> str:
    if len(names) <= 30:
        return "、".join(names)
    return "、".join(names[:30]) + f" 等 {len(names)} 个"


def _sheet_hint_from_goal(goal: str, row_groups: dict[str, dict[str, Any]]) -> str | None:
    sheets = sorted({str(group.get("sheet") or "") for group in row_groups.values() if group.get("sheet")})
    lowered = goal.lower()
    exact = [sheet for sheet in sheets if sheet and sheet.lower() in lowered]
    if exact:
        return max(exact, key=len)
    keywords = [part for part in re.split(r"[\s,，。；;:：/]+", goal) if len(part) >= 2]
    matches = [sheet for sheet in sheets if any(keyword in sheet or sheet in keyword for keyword in keywords)]
    return max(matches, key=len) if matches else None


def _looks_like_entity_list_goal(goal: str) -> bool:
    text = str(goal or "")
    return any(token in text for token in ("哪些", "有哪些", "都有谁", "有谁", "所有", "全部", "确定", "列举", "列出", "清单", "明细", "名单", "一一", "分别", "去重"))


def _display_field(fields: dict[str, Any]) -> str | None:
    candidates = [str(name) for name in fields if fields.get(name) not in (None, "")]
    if not candidates:
        return None
    scored = []
    for name in candidates:
        lower = name.lower()
        score = 5
        if lower.endswith("_name") or "名称" in name or "标题" in name:
            score = 0
        elif lower in {"name", "title", "label"}:
            score = 1
        elif lower.endswith("_id") or lower == "id" or "编号" in name:
            score = 3
        scored.append((score, name))
    return min(scored)[1]


def _list_entity_summary(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    row_groups: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        key = "|".join(str(source.get(part) or "") for part in ("record_key", "sheet", "row"))
        if not key.strip("|"):
            key = str(item.get("record_id") or len(row_groups))
        group = row_groups.setdefault(key, {"fields": {}, "evidence": [], "sheet": source.get("sheet")})
        group["fields"][str(item.get("field_name") or "").strip()] = item.get("value")
        if len(group["evidence"]) < 4:
            group["evidence"].append(_evidence_label(item))
    if _looks_like_group_count_goal(str(payload.get("analysis_goal") or payload.get("utterance") or "")):
        grouped = _group_count_summary(row_groups, payload)
        if grouped:
            return grouped
    return _list_entity_summary_from_groups(row_groups, payload) or _group_count_summary(row_groups, payload) or {
        "operation": "entity_list",
        "answer": "当前授权数据中没有找到可列举的实体记录。",
        "detail": f"已读取 {len(items)} 条结构化字段，但没有识别出可展示的实体名称或编号。",
        "names": [],
        "evidence": [],
    }


def _list_entity_summary_from_groups(
    row_groups: dict[str, dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    goal = str(payload.get("analysis_goal") or payload.get("utterance") or "")
    if not _looks_like_entity_list_goal(goal):
        return None
    preferred_sheet = _sheet_hint_from_goal(goal, row_groups) or _preferred_sheet_from_goal(goal)
    groups = [
        group for group in row_groups.values()
        if not preferred_sheet or group.get("sheet") == preferred_sheet
    ]
    if not groups:
        return None
    names: list[str] = []
    evidence: list[str] = []
    display_field = None
    for group in groups:
        fields = group.get("fields") or {}
        field = _target_entity_field(fields, goal) or _display_field(fields)
        if not field:
            continue
        display_field = display_field or field
        value = str(fields.get(field) or "").strip()
        if not value or value.lower() in {"none", "null", "nan"} or value in names:
            continue
        names.append(value)
        evidence.extend((group.get("evidence") or [])[:2])
    if not names:
        return None
    source_label = preferred_sheet or "当前授权数据"
    return {
        "operation": "entity_list",
        "answer": f"{source_label}中找到 {len(names)} 项相关记录：{_format_name_list(names)}。",
        "detail": f"已根据用户问题定位数据范围，并按字段“{display_field}”去重列举。",
        "sheet": preferred_sheet,
        "display_field": display_field,
        "distinct_count": len(names),
        "names": names,
        "evidence": evidence[:12],
        "recommendation": "如需进一步筛选，请补充时间、区域、状态或其他业务条件。",
    }


def _target_entity_field(fields: dict[str, Any], goal: str) -> str | None:
    goal_text = str(goal or "").lower()
    candidates = [str(name) for name in fields if fields.get(name) not in (None, "")]
    if not candidates:
        return None
    targets: list[tuple[int, str]] = []
    for name in candidates:
        lower = name.lower()
        score = 100
        if "经销商" in goal_text or "dealer" in goal_text or "distributor" in goal_text:
            if lower in {"dealer_name", "distributor_name"} or "经销商名称" in name:
                score = 0
            elif lower in {"dealer", "distributor"} or name == "经销商":
                score = 1
            elif lower in {"dealer_id", "distributor_id"} or "经销商编号" in name:
                score = 4
        elif "客户" in goal_text or "customer" in goal_text:
            if lower == "customer_name" or "客户名称" in name:
                score = 0
            elif lower == "customer" or name == "客户":
                score = 1
            elif lower == "customer_id" or "客户编号" in name:
                score = 4
        elif "供应商" in goal_text or "supplier" in goal_text:
            if lower == "supplier_name" or "供应商名称" in name:
                score = 0
            elif lower == "supplier" or name == "供应商":
                score = 1
            elif lower == "supplier_id" or "供应商编号" in name:
                score = 4
        elif "产品" in goal_text or "product" in goal_text:
            if lower == "product_name" or "产品名称" in name:
                score = 0
            elif lower == "product" or name == "产品":
                score = 1
            elif lower == "product_id" or "产品编号" in name:
                score = 4
        if score < 100:
            targets.append((score, name))
    return min(targets)[1] if targets else None


def _dimension_score(name: str) -> int:
    lower = name.lower()
    if lower in {"dealer_name", "distributor_name", "customer_name", "supplier_name"} or any(token in name for token in ("经销商名称", "客户名称", "供应商名称")):
        return 0
    if lower in {"dealer", "distributor", "customer", "supplier"} or name in {"经销商", "客户", "供应商"}:
        return 1
    if lower.endswith("_name") or "名称" in name:
        return 2
    if lower.endswith("_id") or lower.endswith("id") or "编号" in name:
        return 3
    return 4


def _group_count_summary(row_groups: dict[str, dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any] | None:
    """Count uploaded rows by an identified business dimension when no filter was supplied."""
    goal = str(payload.get("analysis_goal") or payload.get("utterance") or "")
    data_object = str(payload.get("data_object") or payload.get("object") or "")
    scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
    object_hint = " ".join(part for part in (goal, data_object, str(scope.get("label") or ""), str(scope.get("scope_key") or "")) if part)
    object_label = "经销商" if any(token in object_hint.lower() for token in ("经销商", "dealer", "distributor")) else ("客户" if any(token in object_hint.lower() for token in ("客户", "customer")) else "对象")
    preferred_sheet = _preferred_sheet_from_goal(goal) or ("经销商订单" if object_label == "经销商" else None)
    dimension_names = ("经销商名称", "经销商", "dealer_name", "dealer", "distributor", "customer_name", "customer", "客户名称", "客户")
    candidates: dict[str, dict[str, int]] = {}
    evidence_by_value: dict[str, list[str]] = {}
    for group in row_groups.values():
        if not _sheet_matches(group, preferred_sheet):
            continue
        fields = group.get("fields") or {}
        matched_names = [
            str(name)
            for name in fields
            if any(token in str(name).lower() for token in dimension_names)
        ]
        dimension_name = min(matched_names, key=_dimension_score) if matched_names else None
        if not dimension_name:
            continue
        value = str(fields.get(dimension_name) or "").strip()
        if not value or value.lower() in {"none", "null", "nan"}:
            continue
        bucket = candidates.setdefault(dimension_name, {})
        bucket[value] = bucket.get(value, 0) + 1
        evidence_by_value.setdefault(value, [])
        if len(evidence_by_value[value]) < 2:
            evidence_by_value[value].extend((group.get("evidence") or [])[:2])
    if not candidates:
        return None
    dimension_name, counts = max(candidates.items(), key=lambda item: len(item[1]))
    ordered = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    names = list(ordered.keys())
    total_rows = sum(ordered.values())
    source_label = preferred_sheet or "当前可访问数据"
    return {
        "operation": "group_count",
        "answer": f"{source_label}中共有 {len(ordered)} 个不同{object_label}参与合作：{_format_name_list(names)}。",
        "detail": f"已按“{dimension_name}”去重统计，共识别 {total_rows} 条相关记录。",
        "dimension": dimension_name,
        "total": total_rows,
        "distinct_count": len(ordered),
        "names": names,
        "groups": ordered,
        "evidence": [f"{name}：{count} 条记录" for name, count in list(ordered.items())[:10]],
        "source_evidence": {name: evidence_by_value.get(name, [])[:2] for name in names[:10]},
        "recommendation": "请确认经销商名称字段和订单记录口径符合业务统计要求后再正式引用。",
    }


def _month_from_fields(fields: dict[str, Any], target_year: int) -> int | None:
    for name, value in fields.items():
        lower = str(name).lower()
        if any(token in lower for token in ("date", "month", "月份", "年月", "期间", "period")):
            month = _month_from_value(value, target_year)
            if month:
                return month
    year = None
    month = None
    for name, value in fields.items():
        lower = str(name).lower()
        if lower in {"year", "年份"} or "年度" in lower:
            parsed = _number(value)
            if parsed is not None:
                year = int(parsed)
        if lower in {"month", "月份", "月"}:
            parsed = _number(value)
            if parsed is not None:
                month = int(parsed)
    if year and month and 1 <= month <= 12 and (not target_year or year == target_year):
        return month
    if target_year and month and 1 <= month <= 12:
        return month
    return None


def _month_from_value(value: Any, target_year: int) -> int | None:
    text = str(value)
    if target_year:
        match = re.search(rf"{target_year}\D+(\d{{1,2}})", text)
        if match:
            month = int(match.group(1))
            return month if 1 <= month <= 12 else None
    match = re.search(r"(20\d{2})\D+(\d{1,2})", text)
    if match:
        month = int(match.group(1))
        if len(match.groups()) >= 2:
            month = int(match.group(2))
        return month if 1 <= month <= 12 else None
    match = re.search(r"(\d{1,2})\s*月", text)
    if match and (not target_year or str(target_year) in text):
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    return None


def _demand_from_fields(fields: dict[str, Any]) -> float | None:
    preferred: list[float] = []
    fallback: list[float] = []
    for name, value in fields.items():
        lower = str(name).lower()
        number = _number(value)
        if number is None:
            continue
        if any(token in lower for token in ("demand_qty", "demand", "需求量", "需求")):
            preferred.append(number)
        elif any(token in lower for token in ("order_qty", "order", "订单量", "订单", "销量", "销售量", "quantity", "qty")):
            fallback.append(number)
    if preferred:
        return max(preferred)
    if fallback:
        return max(fallback)
    return None


def _evidence_label(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    field = item.get("field_name")
    sheet = source.get("sheet") or item.get("sheet") or "数据"
    row = source.get("row") or item.get("row") or "?"
    return f"{sheet} 第 {row} 行 {field}: {item.get('value')}"
