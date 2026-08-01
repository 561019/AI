"""Follow-up analysis service — drill-down router and data preparation.

When a user asks a follow-up question after receiving an overall analysis,
this module:
1. Detects whether the message is a follow-up (vs a new topic)
2. Prepares detailed drill-down data based on the analysis type
3. Builds LLM prompts that combine previous context + drill-down data
"""

from __future__ import annotations

import json
from typing import Any

_FOLLOW_UP_KEYWORDS = [
    "为什么", "原因", "怎么回事", "怎么会", "哪些", "哪个",
    "具体", "详细", "怎么", "为何", "是因为", "进一步",
    "深入", "解释", "说明", "展开", "细说", "讲一下",
    "是因为什么", "什么原因", "什么导致", "造成",
]


def is_follow_up(prev_context: dict | None, message: str) -> bool:
    """Check if the message is a follow-up to a previous analysis.

    Returns True when:
    - There is a previous analysis context available
    - The message contains follow-up keywords

    Also returns False when the message clearly starts a new topic
    (e.g. contains explicit new-analysis keywords like "分析", "预测",
    "看看" without follow-up keywords).
    """
    if prev_context is None:
        return False
    if not message or not message.strip():
        return False

    has_follow_kw = any(kw in message for kw in _FOLLOW_UP_KEYWORDS)

    # New-topic keywords: user explicitly asks for a fresh analysis
    new_topic_keywords = ["分析", "预测", "诊断", "看看", "帮我", "查"]
    has_new_topic_kw = any(kw in message for kw in new_topic_keywords)

    # If user says "分析一下2025年的" — that's a new topic, not follow-up
    if has_new_topic_kw and not has_follow_kw:
        return False

    return has_follow_kw


def prepare_drilldown_data(
    prev_result: dict | None,
    prev_raw: dict | None,
    analysis_type: str,
    question: str,
) -> str:
    """Prepare drill-down data for the LLM based on analysis type.

    Returns a formatted text string containing the detailed data needed
    to answer the user's follow-up question.
    """
    if prev_result is None:
        return "(无上轮分析结果)"

    if analysis_type == "financial_statement":
        return _prepare_financial_drilldown(prev_result, prev_raw)
    elif analysis_type == "price_forecast":
        return _prepare_price_drilldown(prev_result, prev_raw)
    elif analysis_type == "business_metric":
        return _prepare_business_drilldown(prev_result, prev_raw)
    elif analysis_type in ("diagnostic", "service_events", "work_reports"):
        return _prepare_diagnostic_drilldown(prev_result, prev_raw)
    else:
        return _prepare_generic_drilldown(prev_result, prev_raw)


def build_follow_up_prompt(
    prev_summary: str,
    drilldown_data: str,
    question: str,
    analysis_type: str = "generic",
) -> dict[str, str]:
    """Build system and user prompts for a follow-up question.

    Returns {"system": ..., "user": ...} for use with the platform model dispatcher.
    """
    type_labels = {
        "financial_statement": "财务报表",
        "price_forecast": "价格走势",
        "business_metric": "经营指标",
        "diagnostic": "经营诊断",
        "service_events": "服务事件",
        "work_reports": "工作汇报",
    }

    label = type_labels.get(analysis_type, "数据分析")

    system = (
        f"你是一位资深经营分析顾问。用户刚才看了一份{label}的总体报告，现在对报告中的细节进行追问。\n\n"
        "你收到的数据包含：(1) 上轮分析摘要 - 这是用户已经看过的内容 (2) 本轮下钻的详细数据 - 所有数据均为原文引用。\n\n"
        "## 核心规则（必须严格遵守）：\n"
        "1. 只使用下面「下钻详细数据」中明确出现的数字和事实。数据里有什么就引用什么，数据里没有的不能说有。\n"
        "2. 禁止做任何数学计算。不要自己算百分比、不要自己算增长率、不要自己算差值。如果数据里没写\"25%\"你就不能说25%。\n"
        "3. 禁止推断因果关系。数据说\"配送延误\"就说\"配送延误\"，不能说\"配送延误导致了复购下降\"。只能说\"数据显示配送延误和复购下降同时发生\"。\n"
        "4. 禁止添加数据中没有的细节。比如数据只说\"配送延误5天\"，你不能说\"严重配送延误\"或\"长期延误\"。\n"
        "5. 引用证据时必须用原文原句，放在引号中。\n"
        "6. 直接针对用户的具体问题回答，不要重复总体报告已说过的内容\n"
        "7. 如果数据不足以回答用户的问题，如实说明\"目前的数据不足以确定原因\"\n"
        "8. 结尾必须附上：「⚠️ 以上分析由AI基于已有数据生成，仅供决策参考，须经真人确认后生效。」"
    )

    user = (
        f"## 上轮分析摘要（用户已看过，供你了解上下文）\n\n"
        f"{_truncate_summary(prev_summary, 1200)}\n\n"
        f"## 下钻详细数据（请基于此回答用户追问）\n\n"
        f"{drilldown_data}\n\n"
        f"## 用户追问\n\n"
        f"{question}\n\n"
        f"请针对以上追问，基于下钻数据给出分析。"
    )

    return {"system": system, "user": user}


# ---- Internal helpers ----

def _truncate_summary(text: str, max_chars: int) -> str:
    """Truncate a summary text to max_chars, keeping whole sentences."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = max(truncated.rfind("。"), truncated.rfind("；"), truncated.rfind("\n"))
    if last_period > max_chars // 2:
        return truncated[: last_period + 1] + "\n...(已截断)"
    return truncated + "..."


def _compact(obj: Any, max_items: int = 50) -> Any:
    """Compact a data structure for LLM consumption — limit list/dict size."""
    if isinstance(obj, dict):
        if len(obj) > max_items:
            keys = list(obj.keys())[:max_items]
            return {str(k): _compact(obj[k], max_items) for k in keys}
        return {str(k): _compact(v, max_items) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        if len(obj) > max_items:
            return [_compact(item, max_items) for item in obj[:max_items]]
        return [_compact(item, max_items) for item in obj]
    return obj


# ---- Per-type drill-down data preparation ----

def _prepare_financial_drilldown(
    prev_result: dict, prev_raw: dict | None
) -> str:
    """Extract per-period details, anomalies, and DuPont breakdown."""
    metrics = prev_result.get("metrics", {})
    dupont = prev_result.get("dupont", {})

    lines = ["### 财务报表 — 下钻数据\n"]

    # Per-metric per-period breakdown
    if metrics:
        lines.append("**逐期指标明细**\n")
        for metric_name, metric_data in metrics.items():
            if not isinstance(metric_data, dict):
                continue
            current = metric_data.get("current", "-")
            trend = metric_data.get("trend", "-")
            trend_slope = metric_data.get("trend_slope", "-")
            lines.append(
                f"- **{metric_name}**: 最新值={current}, "
                f"趋势={trend}, 斜率={trend_slope}"
            )

            # Anomalies
            anomalies = metric_data.get("anomalies", ())
            if anomalies:
                lines.append(f"  ⚠ 异常检测（Z-score）: {len(anomalies)}处")
                for anom in anomalies:
                    idx = anom.get("index", "?")
                    val = anom.get("value", "?")
                    z = anom.get("z_score", "?")
                    lines.append(f"    - 第{idx}期: 值={val}, Z-score={z}")

            # Per-period data
            by_period = metric_data.get("by_period", ())
            if by_period:
                lines.append(f"  | 期间 | 值 | 环比% | 同比% |")
                lines.append(f"  |------|-----|-------|-------|")
                for row in by_period:
                    period = row.get("period", "-")
                    value = row.get("value", "-")
                    mom = row.get("period_over_period_percent", "-")
                    yoy = row.get("year_over_year_percent", "-")
                    lines.append(f"  | {period} | {value} | {mom} | {yoy} |")
                lines.append("")

    # DuPont breakdown
    if dupont and dupont.get("by_period"):
        lines.append("**杜邦分析 — 逐期分解**\n")
        lines.append("| 期间 | ROE% | 净利率% | 资产周转率 | 权益乘数 |")
        lines.append("|------|------|---------|-----------|---------|")
        for row in dupont["by_period"]:
            period = row.get("period", "-")
            roe = row.get("roe_percent", "-")
            margin = row.get("net_margin_percent", "-")
            turnover = row.get("asset_turnover", "-")
            leverage = row.get("equity_multiplier", "-")
            lines.append(f"| {period} | {roe} | {margin} | {turnover} | {leverage} |")

    return "\n".join(lines)


def _prepare_price_drilldown(
    prev_result: dict, prev_raw: dict | None
) -> str:
    """Extract historical price details, volatility, and forecast table."""
    volatility = prev_result.get("volatility", {})
    forecasts = prev_result.get("forecasts", ())
    history = prev_result.get("history_window", {})
    uncertainty = prev_result.get("uncertainty", {})

    lines = ["### 价格预测 — 下钻数据\n"]

    if volatility:
        lines.append("**波动性指标**")
        lines.append(f"- 趋势方向: {volatility.get('trend', '-')}")
        lines.append(f"- 斜率: {volatility.get('slope', '-')}")
        lines.append(f"- 价格区间: {volatility.get('price_range', '-')}")
        lines.append(f"- 相对波动: {volatility.get('relative_range_percent', '-')}%")
        lines.append(f"- 模型版本: {volatility.get('model_version', '-')}")
        lines.append("")

    if forecasts:
        lines.append("**预测区间明细**\n")
        lines.append("| 步数 | 日期 | 预测值 | 下限 | 上限 | 区间宽度 |")
        lines.append("|------|------|--------|------|------|---------|")
        for f in forecasts:
            step = f.get("step", "-")
            date = f.get("date", "-")
            value = f.get("value", "-")
            lower = f.get("lower", "-")
            upper = f.get("upper", "-")
            try:
                width = round(float(upper) - float(lower), 2)
            except (ValueError, TypeError):
                width = "-"
            lines.append(f"| {step} | {date} | {value} | {lower} | {upper} | {width} |")

    if history:
        lines.append(f"\n历史窗口: {history.get('start', '?')} 至 {history.get('end', '?')}")

    if uncertainty:
        lines.append(f"不确定性说明: {uncertainty.get('message', '-')}")

    # If raw data with records is available, show price change rates
    if prev_raw and prev_raw.get("records"):
        lines.append("\n**历史价格变化**")
        records = sorted(prev_raw["records"], key=lambda r: str(r.get("date", "")))
        for i in range(1, len(records)):
            prev_price = float(records[i - 1].get("price", 0))
            curr_price = float(records[i].get("price", 0))
            if prev_price:
                change = round((curr_price - prev_price) / prev_price * 100, 2)
                lines.append(
                    f"- {records[i].get('date', '?')}: "
                    f"{records[i].get('price', '?')} "
                    f"(环比变化: {change}%)"
                )

    return "\n".join(lines)


def _prepare_business_drilldown(
    prev_result: dict, prev_raw: dict | None
) -> str:
    """Extract cost breakdown, target comparison, and alert details."""
    lines = ["### 经营指标 — 下钻数据\n"]

    net_profit = prev_result.get("net_profit", "-")
    cost_ratios = prev_result.get("cost_ratios", {}) or {}
    comparisons = prev_result.get("target_comparisons", {}) or {}
    alerts = prev_result.get("alert_candidates", ())

    lines.append(f"**净利润**: {net_profit}\n")

    # Cost breakdown
    lines.append("**成本结构分解**\n")
    labels = {
        "sales_cost_ratio": "销售成本率",
        "delivery_cost_ratio": "交付成本率",
        "operating_cost_ratio": "运营成本率",
    }
    lines.append("| 成本项 | 实际(%) | 目标(%) | 差异 | 状态 |")
    lines.append("|--------|---------|---------|------|------|")
    for key, label in labels.items():
        actual = cost_ratios.get(key, "-")
        comp = comparisons.get(key, {})
        target = comp.get("target", "-")
        diff = comp.get("difference", "-")
        is_exceeded = comp.get("is_exceeded", False)
        status = "⚠ 超标" if is_exceeded else "✓ 达标"
        lines.append(f"| {label} | {actual} | {target} | {diff} | {status} |")

    # Alerts detail
    if alerts:
        lines.append(f"\n**告警明细** ({len(alerts)}项超标)")
        for alert in alerts:
            lines.append(
                f"- {alert.get('metric', '?')}: "
                f"实际={alert.get('actual', '?')}%, "
                f"目标={alert.get('target', '?')}%, "
                f"超出={alert.get('excess', '?')}%, "
                f"严重度={alert.get('severity', 'warning')}"
            )

    # Raw record detail
    if prev_raw and prev_raw.get("record"):
        rec = prev_raw["record"]
        lines.append(f"\n**原始数据**")
        lines.append(f"- 期间: {rec.get('period', '-')}")
        lines.append(f"- 收入: {rec.get('revenue', '-')}")
        lines.append(f"- 销售成本: {rec.get('sales_cost', '-')}")
        lines.append(f"- 交付成本: {rec.get('delivery_cost', '-')}")
        lines.append(f"- 运营成本: {rec.get('operating_cost', '-')}")

    return "\n".join(lines)


def _load_related_data_files() -> dict[str, dict]:
    """Auto-discover and load related data files from the data directory.

    Looks for: service events, work reports, and any diagnostic-related files.
    Returns a dict of {filename: parsed_json}.
    """
    import json as _json
    from pathlib import Path as _Path

    data_dir = _Path(__file__).resolve().parent.parent.parent.parent
    related: dict[str, dict] = {}

    # Load service events if available
    for pattern in ("*服务事件*.json", "*service_events*.json"):
        for p in data_dir.glob(pattern):
            try:
                related[p.name] = _json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    # Load work reports if available
    for pattern in ("*工作汇报*.json", "*work_report*.json"):
        for p in data_dir.glob(pattern):
            try:
                related[p.name] = _json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    return related


def _prepare_diagnostic_drilldown(
    prev_result: dict, prev_raw: dict | None
) -> str:
    """Extract entity-level detail, evidence, and root cause hypotheses.

    Also auto-loads related data files (service events, work reports)
    to provide the LLM with ALL available evidence — not just what's
    in the diagnostic request file.
    """
    lines = ["### 经营诊断 — 下钻数据\n"]

    contributors = prev_result.get("major_contributors", ())
    hypotheses = prev_result.get("root_cause_hypotheses", ())

    # ---- Part 1: Entity metrics (from diagnostic request) ----
    lines.append("## 1. 实体指标数据（来源：诊断请求文件）\n")

    # Get entities from raw data (full list) or contributors
    all_entities = []
    if prev_raw and prev_raw.get("entities"):
        all_entities = list(prev_raw["entities"])

    if all_entities:
        # Sort by abs contribution
        sorted_entities = sorted(
            all_entities,
            key=lambda e: abs(float(e.get("contribution", "0") or "0")),
            reverse=True,
        )
        lines.append("| 排名 | 实体ID | 实体名称 | Q1复购率 | Q2复购率 | 贡献度(pp) | Q1活跃客户 | Q2活跃客户 | Q1复购客户 | Q2复购客户 |")
        lines.append("|------|--------|----------|----------|----------|-----------|-----------|-----------|-----------|-----------|")
        for i, e in enumerate(sorted_entities):
            metrics = e.get("metrics", {})
            lines.append(
                f"| {i + 1} "
                f"| {e.get('entity_id', '-')} "
                f"| {e.get('entity_name', '-')} "
                f"| {metrics.get('Q1_repurchase_rate', '-')}% "
                f"| {metrics.get('Q2_repurchase_rate', '-')}% "
                f"| {e.get('contribution', '-')} "
                f"| {metrics.get('Q1_active_customers', '-')} "
                f"| {metrics.get('Q2_active_customers', '-')} "
                f"| {metrics.get('Q1_repeat_customers', '-')} "
                f"| {metrics.get('Q2_repeat_customers', '-')} |"
            )
        lines.append("")

    # ---- Part 2: Diagnostic evidence (verbatim from diagnostic request) ----
    if prev_raw and prev_raw.get("evidence"):
        evidence_list = prev_raw["evidence"]
        lines.append(f"## 2. 诊断证据记录（来源：诊断请求文件，共{len(evidence_list)}条）\n")
        lines.append("以下为原文引用，不得修改或添加：\n")
        for ev in evidence_list:
            eid = ev.get('evidence_id', '?')
            entity = ev.get('entity_id', '?')
            etype = ev.get('evidence_type', '?')
            edate = ev.get('date', '无日期')
            summary = ev.get('summary', '?')
            source = ev.get('source_ref', '?')
            lines.append(f"**[{eid}]** 实体={entity} | 类型={etype} | 日期={edate}")
            lines.append(f"> 原文: {summary}")
            lines.append(f"  来源: {source}")
            lines.append("")

    # ---- Part 3: Service events (from separate data file) ----
    related = _load_related_data_files()
    events_file = None
    for name, data in related.items():
        if "服务事件" in name or "service_event" in name.lower():
            events_file = data
            break

    if events_file and events_file.get("by_dealer"):
        by_dealer = events_file["by_dealer"]
        lines.append(f"## 3. 服务事件记录（来源：{name}，共{events_file.get('total', '?')}条）\n")
        lines.append("以下为原文引用，不得修改或添加：\n")
        total_shown = 0
        for dealer_id, events in sorted(by_dealer.items()):
            lines.append(f"### {dealer_id} ({len(events)}条事件)")
            for ev in events:
                total_shown += 1
                ev_id = ev.get('event_id', '?')
                ev_date = ev.get('date', '无日期')
                ev_type = "配送" if ev.get('type') == 'delivery' else "回访"
                delay = ev.get('delay_days', 0)
                status = ev.get('follow_up_status', '')
                src = ev.get('source_ref', '?')
                if ev_type == "配送":
                    lines.append(f"  - [{ev_id}] {ev_date} 配送延误 {delay}天 | 来源: {src}")
                else:
                    lines.append(f"  - [{ev_id}] {ev_date} 回访状态={status} | 来源: {src}")
            lines.append("")
        lines.append(f"(共展示{total_shown}条服务事件)\n")

    # ---- Part 4: Work reports (from separate data file) ----
    reports_file = None
    for name, data in related.items():
        if "工作汇报" in name or "work_report" in name.lower():
            reports_file = data
            break

    if reports_file and reports_file.get("reports"):
        reports = reports_file["reports"]
        lines.append(f"## 4. 工作汇报记录（来源：{name}，共{len(reports)}条）\n")
        lines.append("以下为原文引用，不得修改或添加：\n")
        for r in reports:
            rid = r.get('report_id', '?')
            author = r.get('author', '?')
            rdate = r.get('date', '?')
            dealer = r.get('dealer_id', '')
            region = r.get('region', '')
            content = r.get('content', '?')
            src = r.get('source_ref', '?')
            dealer_info = f" 关联经销商={dealer}" if dealer else ""
            region_info = f" 区域={region}" if region else ""
            lines.append(f"**[{rid}]** 作者={author} | 日期={rdate}{dealer_info}{region_info}")
            lines.append(f"> 原文: {content}")
            lines.append(f"  来源: {src}")
            lines.append("")

    # ---- Part 5: Root cause hypotheses (if already computed) ----
    if hypotheses:
        lines.append(f"## 5. 已生成的根因假设 ({len(hypotheses)}条)\n")
        for h in hypotheses:
            refs = ", ".join(h.get("evidence_refs", []))
            lines.append(
                f"- [{h.get('confidence', '?')}] {h.get('hypothesis_id', '?')}: "
                f"{h.get('description', '?')}"
            )
            if refs:
                lines.append(f"  引用的证据编号: {refs}")
        lines.append("")

    return "\n".join(lines)


def _prepare_generic_drilldown(
    prev_result: dict, prev_raw: dict | None
) -> str:
    """Generic fallback: dump the raw data in structured form."""
    lines = ["### 上轮分析 — 详细数据\n"]

    if prev_raw:
        compacted = _compact(prev_raw)
        # Remove very large fields to keep prompt manageable
        for key in list(compacted.keys()):
            val = compacted[key]
            if isinstance(val, (list, tuple)) and len(val) > 30:
                compacted[key] = f"(共{len(val)}项，已截断)"
        lines.append("```json")
        lines.append(json.dumps(compacted, ensure_ascii=False, indent=2, default=str))
        lines.append("```")

    return "\n".join(lines)
