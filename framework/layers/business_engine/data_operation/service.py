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
    if handler.path != MODULE.interface:
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
        caller={"layer": "business_engine", "module": "data-operation"},
    )
    if status != 200 or response.get("status") != "success":
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
    if capability in {"data.persist", "data.create", "data.update", "data.delete"}:
        operation = {
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
    return "foundation_data.query", {
        "dataset": dataset,
        "filters": payload.get("filters") or {},
        "tenant_id": payload.get("tenant_id"),
        "limit": payload.get("limit", 100),
        "compact": bool(payload.get("compact")),
    }


def _aggregate(data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items") or []
    operation = str(payload.get("aggregate_operation") or payload.get("operation") or "").lower()
    if operation in {"list", "list_distinct", "entity_list", "enumerate"}:
        return {**data, "aggregate": _list_entity_summary(items, payload)}
    if operation == "monthly_max_metric":
        return {**data, "aggregate": _monthly_max_metric(items, payload)}
    if operation in {"retrieve", "query", "search", "summarize", "summary", "analyze", "analyse", "retrieve_and_summarize", "retrieve_and_rank", "recommend", "rank", "统计", "汇总", "分析"}:
        summary = _summarize_relevant_rows(items, payload)
        if summary:
            return {**data, "aggregate": summary}
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
    time_field = str(payload.get("time_field") or "").strip()
    metric_field = str(payload.get("metric_field") or "").strip()
    if not time_field or not metric_field:
        return {
            "operation": "monthly_max_metric",
            "answer": "",
            "detail": "monthly_max_metric 需要明确提供 time_field 和 metric_field。",
            "error": {
                "code": "STRUCTURED_OPERATION_INPUT_REQUIRED",
                "required": ["time_field", "metric_field"],
            },
        }
    target_year = _year_from_text(str(payload.get("analysis_goal") or "")) or payload.get("year")
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
    monthly: dict[int, float] = {}
    evidence: dict[int, list[str]] = {}
    for row in rows.values():
        time_value = row["fields"].get(time_field)
        metric_value = _number(row["fields"].get(metric_field))
        if time_value is None or metric_value is None:
            continue
        month = _month_from_value(time_value, target_year or 0)
        if month is None:
            continue
        monthly[month] = monthly.get(month, 0.0) + metric_value
        evidence.setdefault(month, []).extend(row["evidence"][:4])
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
        "operation": "monthly_max_metric",
        "answer": f"{month} 月的 {metric_field} 汇总值最高，为 {_format_number(value)}。",
        "time_field": time_field,
        "metric_field": metric_field,
        "month": month,
        "value": value,
        "monthly_values": {str(key): val for key, val in sorted(monthly.items())},
        "evidence": evidence.get(month, [])[:8],
    }


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
    has_count_or_list = any(token in text for token in ("几个", "多少个", "数量", "参与", "合作", "列举", "名单", "清单", "一一列举", "分别"))
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
    return any(token in goal for token in ("哪些", "有哪些", "列举", "清单", "明细", "名单", "一一"))


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
    return _list_entity_summary_from_groups(row_groups, payload) or {
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
    preferred_sheet = _sheet_hint_from_goal(goal, row_groups)
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
        field = _display_field(fields)
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
    preferred_sheet = _preferred_sheet_from_goal(goal)
    dimension_names = ("经销商名称", "经销商", "dealer_name", "dealer", "distributor", "customer_name", "customer", "客户名称", "客户")
    candidates: dict[str, dict[str, int]] = {}
    evidence_by_value: dict[str, list[str]] = {}
    total_rows = 0
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
        total_rows += 1
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
    object_label = "经销商" if "经销商" in goal or "dealer" in goal.lower() or "distributor" in goal.lower() else "对象"
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
    if year == target_year and month and 1 <= month <= 12:
        return month
    return None


def _month_from_value(value: Any, target_year: int) -> int | None:
    text = str(value)
    match = re.search(rf"{target_year}[-/.年](\d{{1,2}})", text)
    if match:
        month = int(match.group(1))
        return month if 1 <= month <= 12 else None
    match = re.search(r"(\d{1,2})\s*月", text)
    if match and str(target_year) in text:
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
