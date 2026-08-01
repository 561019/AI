"""Chat service - NL -> intent -> engine -> platform-model narrative."""

import json, re
from pathlib import Path
from datetime import date
from decimal import Decimal

from analysis_prediction_engine.contracts.requests import parse_analysis_request
from analysis_prediction_engine.services.business_metrics import analyze_business_metrics
from analysis_prediction_engine.services.diagnostic import analyze_diagnostic
from analysis_prediction_engine.services.financial_analysis import analyze_financial_statement
from analysis_prediction_engine.services.platform_model_client import call_platform_model
from analysis_prediction_engine.services.price_forecast import forecast_prices

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent

# In-memory context for follow-up questions (single-user demo; use session store in production)
_last_analysis: dict | None = None


def get_last_analysis() -> dict | None:
    """Return the last analysis context (for testing)."""
    return _last_analysis


def clear_last_analysis() -> None:
    """Clear the last analysis context (for testing)."""
    global _last_analysis
    _last_analysis = None

_INTENT_PROMPT = """You are an intent parser for a business analysis engine. Extract JSON from the user's Chinese message AND conversation history.

## Step 1 — Classify action:
- "financial": financial statements (profit statement / balance sheet / cash flow)
- "price": price forecast (steel / raw material price prediction)
- "business": business metrics (law firm / cost ratio / operating metrics)
- "diagnostic": diagnostic analysis (why did X drop? / root cause / find contributors)

## Step 2 — Match data_files (ALWAYS return an array):
- "2023 profit statement" → ["2023年利润表_请求体.json"]
- "2023 all three statements" → all 3 financial files for 2023
- "predict steel price" → ["2023-2025年钢材价格_请求体.json"]
- "2024 steel" → ["2024年钢材价格_请求体.json"]
- "law firm Q1 2025" → ["2025-Q1律所经营指标_请求体.json"]
- "why did repurchase rate drop" / "复购率为什么下降" / "经销商诊断" / "case 9" → ["案例九_诊断请求_模拟数据.json"]
- "桂中需求预测" / "预测桂中" / "桂中下季度需求" / "demand forecast" → ["案例九_桂中需求预测_请求体.json"]
- "服务事件" / "配送延误" / "回访记录" / "dealer events" → ["案例九_服务事件数据.json"]
- "工作汇报" / "业务员报告" / "work reports" / "付盛贤报告" / "5月8日" → ["案例九_工作汇报数据.json"]

## Step 3 — Check if enough information is present to proceed:
Set "ready": true ONLY when ALL of the following are satisfied:
- data_files is non-empty (at least one file matched)
- The user's intent is clear enough to pick the right analysis type
- The time period / scope is specified or reasonably inferrable

Set "ready": false when:
- data_files is empty (user didn't specify which data / year)
- The analysis type is ambiguous (e.g. user said "analyze" without saying what)
- Critical info is missing that would cause a wrong analysis

When ready is false, write ONE natural Chinese clarification question in "clarification". Ask specifically for the missing piece — don't list all available files unless the user seems to be browsing. Keep it conversational and brief.

## Step 4 — Additional fields:
- filter_months: month range as int array, null for full period
- focus: one Chinese sentence describing the analysis angle
- forecast_horizon: for price forecast, default 6
- message: when ready=true, a brief confirmation. When ready=false, empty string.

Available files:
{DATA_FILES}

Conversation history (most recent last):
{CHAT_HISTORY}

Return ONLY valid JSON. No markdown, no extra text.
Example ready=true:
{"ready":true,"action":"price","data_files":["2023-2025年钢材价格_请求体.json"],"filter_months":null,"focus":"steel price trend and forecast","forecast_horizon":6,"message":"OK, let me analyze the steel price trend.","clarification":""}

Example ready=false:
{"ready":false,"action":"","data_files":[],"filter_months":null,"focus":"","forecast_horizon":6,"message":"","clarification":"请问您想分析哪个年度的数据？我这里有2023到2025年的财务报表和钢材价格数据。"}"""

_LABELS = {
    "revenue":"营业收入","operating_cost":"营业成本","selling_expense":"销售费用",
    "admin_expense":"管理费用","rd_expense":"研发费用","finance_expense":"财务费用",
    "net_income":"净利润","total_assets":"总资产","total_liabilities":"总负债",
    "equity":"所有者权益","cash":"货币资金","accounts_receivable":"应收账款","inventory":"存货",
    "fixed_assets":"固定资产","accounts_payable":"应付账款","short_term_debt":"短期借款",
    "long_term_debt":"长期借款","operating_cashflow":"经营现金流",
}

def _call_platform_text(system, user, max_tokens=800):
    result = call_platform_model(
        trace_id="analysis-prediction-chat",
        task_type="analysis_prediction_chat",
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=0.3,
        output_kind="text",
    )
    if result["status"] != "complete":
        raise RuntimeError(result["reason"])
    return result["text"]


def _call_platform_json(system, user, max_tokens=800):
    result = call_platform_model(
        trace_id="analysis-prediction-chat",
        task_type="analysis_prediction_chat",
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=0.2,
        output_kind="json",
    )
    if result["status"] != "complete":
        raise RuntimeError(result["reason"])
    return result["output"]

def _format_financial(result, records=None):
    lines = ["### 财务分析\n"]
    if records and records[0].get("metrics"):
        rk = list(records[0]["metrics"].keys())
        if rk:
            lines.append("**逐期数据（"+str(len(records))+"期）**\n")
            hdr = "| 期间 | "+" | ".join(_LABELS.get(k,k) for k in rk)+" |"
            sep = "|------|"+"|".join(["------:" for _ in rk])+"|"
            lines.append(hdr);lines.append(sep)
            for rec in records:
                vals = " | ".join(str(rec["metrics"].get(k,"-")) for k in rk)
                lines.append("| "+rec["period"]+" | "+vals+" |")
            lines.append("")
    return "\n".join(lines)

def _format_price(result, records=None):
    lines = ["### 价格预测\n"]
    v=result.get("volatility",{});t=v.get("trend","?")
    tt={"up":"上升","down":"下降","stable":"稳定"}.get(t,t)
    # Historical data table
    if records:
        lines.append("**历史价格（"+str(len(records))+"期）**\n")
        lines.append("| 日期 | 价格 |")
        lines.append("|------|------|")
        for r in records:
            price=r.get("price","-");d=r.get("date","-")
            lines.append("| "+str(d)+" | "+str(price)+" |")
        lines.append("")
    lines.append("**趋势**: "+tt+" | **斜率**: "+str(v.get("slope",""))+" | **波动**: "+str(v.get("relative_range_percent",""))+"%\n")
    fc=result.get("forecasts",())
    if fc:
        lines.append("**预测区间**\n")
        lines.append("| 步数 | 日期 | 预测值 | 下限 | 上限 |")
        lines.append("|------|------|--------|------|------|")
        for f in fc: lines.append("| "+str(f.get("step"))+" | "+str(f.get("date"))+" | "+str(f.get("value"))+" | "+str(f.get("lower"))+" | "+str(f.get("upper"))+" |")
    return "\n".join(lines)

def _format_business(result):
    lines = ["### 经营指标\n"]
    lines.append("**净利润**: "+str(result.get("net_profit",""))+"\n")
    ra=result.get("cost_ratios") or {};cmp=result.get("target_comparisons") or {}
    lm={"sales_cost_ratio":"销售成本率","delivery_cost_ratio":"交付成本率","operating_cost_ratio":"运营成本率"}
    lines.append("| 指标 | 实际 | 目标 | 状态 |");lines.append("|------|------|------|------|")
    for k,label in lm.items():
        a=ra.get(k,"-");c=cmp.get(k,{});tgt=c.get("target","-");st="超标" if c.get("is_exceeded") else "OK"
        lines.append("| "+label+" | "+str(a)+"% | "+str(tgt)+"% | "+st+" |")
    alerts=result.get("alert_candidates",())
    if alerts:lines.append("\n**告警**: "+str(len(alerts))+"项超标")
    return "\n".join(lines)

def _format_diagnostic_entities(entities):
    """Step 1: display entity metrics as a data table — no root cause yet."""
    if not entities:
        return "### 经销商复购数据\n(无数据)"
    lines = ["### 经销商复购数据\n"]
    # Header
    lines.append("| 经销商 | Q1复购率 | Q2复购率 | 环比变化 | Q1活跃客户 | Q2活跃客户 | Q1复购客户 | Q2复购客户 |")
    lines.append("|--------|----------|----------|----------|------------|------------|------------|------------|")
    # Sort by abs change descending so anomalies stand out
    sorted_entities = sorted(entities, key=lambda e: abs(float(e.get("contribution", "0") or "0")), reverse=True)
    for e in sorted_entities:
        m = e.get("metrics", {})
        lines.append(
            f"| {e.get('entity_name', e.get('entity_id', ''))} "
            f"| {m.get('Q1_repurchase_rate', '-')}% "
            f"| {m.get('Q2_repurchase_rate', '-')}% "
            f"| {e.get('contribution', '-')}pp "
            f"| {m.get('Q1_active_customers', '-')} "
            f"| {m.get('Q2_active_customers', '-')} "
            f"| {m.get('Q1_repeat_customers', '-')} "
            f"| {m.get('Q2_repeat_customers', '-')} |"
        )
    # Highlight anomalies
    big_changes = [e for e in sorted_entities if abs(float(e.get("contribution", "0") or "0")) > 3]
    if big_changes:
        lines.append(f"\n**⚠ 异常关注**: {', '.join(e.get('entity_name', e.get('entity_id', '')) for e in big_changes)}环比变化较大。如需分析原因，可以追问\"为什么这些经销商复购率下降\"。")
    return "\n".join(lines)


def _format_diagnostic_root_cause(result):
    """Step 2: root cause analysis — only when user asks follow-up."""
    lines = ["### 根因诊断\n"]
    target = result.get("_target_description", "")
    contributors = result.get("major_contributors", ())
    if contributors:
        lines.append("| 排名 | 实体 | 贡献度 |")
        lines.append("|------|------|--------|")
        for c in contributors:
            lines.append(f"| {c.get('rank', '')} | {c.get('entity_name', '')}({c.get('entity_id', '')}) | {c.get('contribution', '')}pp |")
        lines.append("")
    hypotheses = result.get("root_cause_hypotheses", ())
    if hypotheses:
        lines.append("**根因假设**\n")
        for h in hypotheses:
            refs = ", ".join(h.get("evidence_refs", []))
            lines.append(f"- [{h.get('confidence', '')}] {h.get('description', '')}（证据: {refs}）")
    return "\n".join(lines)

def _to_serializable(obj):
    if obj is None or isinstance(obj,(bool,int,float,str)):return obj
    if isinstance(obj,Decimal):return format(obj,"f")
    if isinstance(obj,date):return obj.isoformat()
    if hasattr(obj,"model_dump"):return _to_serializable(obj.model_dump())
    if isinstance(obj,dict):return {str(k):_to_serializable(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple,set)):return [_to_serializable(v) for v in obj]
    return str(obj)

def _build_history_text(history):
    """Convert conversation history list to readable text for the prompt."""
    if not history:
        return "(no previous conversation)"
    lines = []
    for turn in history[-6:]:  # last 6 turns max to keep prompt compact
        role = "用户" if turn.get("role") == "user" else "系统"
        content = turn.get("content", "")
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def _handle_follow_up(user_message: str, conversation_history=None) -> dict:
    """Handle a follow-up question using the previous analysis context.

    Prepares drill-down data from the last analysis result,
    builds a follow-up prompt, and calls the LLM for a targeted answer.
    """
    from analysis_prediction_engine.services.follow_up import (
        prepare_drilldown_data,
        build_follow_up_prompt,
    )

    prev = _last_analysis
    prev_type = prev.get("type", "generic")
    prev_result = prev.get("result", {})
    prev_raw = prev.get("raw_data", {})
    prev_summary = prev.get("summary", "")

    drilldown = prepare_drilldown_data(prev_result, prev_raw, prev_type, user_message)
    prompt = build_follow_up_prompt(prev_summary, drilldown, user_message, prev_type)

    try:
        narrative = _call_platform_text(prompt["system"], prompt["user"], 2000)
    except Exception as e:
        narrative = f"(追问分析生成失败: {e})\n\n请参考上方详细数据自行分析。"

    return {
        "role": "assistant",
        "content": f"### 追问分析\n\n{narrative}",
        "action": f"follow_up:{prev_type}",
        "is_follow_up": True,
        "follow_up_type": prev_type,
    }


def chat(user_message, conversation_history=None):
    global _last_analysis

    # ---- Step 0: check for follow-up question ----
    from analysis_prediction_engine.services.follow_up import is_follow_up

    if _last_analysis and is_follow_up(_last_analysis, user_message):
        return _handle_follow_up(user_message, conversation_history)

    fs = sorted(p for p in DATA_DIR.glob("20*.json") if any(c.isdigit() for c in p.stem[:4]))
    diag_files = sorted(DATA_DIR.glob("*诊断*.json"))
    guizhong_files = sorted(DATA_DIR.glob("*桂中*预测*.json"))
    events_files = sorted(DATA_DIR.glob("*服务事件*.json"))
    reports_files = sorted(DATA_DIR.glob("*工作汇报*.json"))
    fs = sorted(set(fs + diag_files + guizhong_files + events_files + reports_files))
    df = "\n".join("- " + p.name for p in fs) if fs else "(none)"
    history_text = _build_history_text(conversation_history)

    # ---- Step 1: parse intent + check completeness ----
    try:
        prompt = _INTENT_PROMPT.replace("{DATA_FILES}", df).replace("{CHAT_HISTORY}", history_text)
        intent = _call_platform_json(prompt, user_message, 400)
    except Exception as e:
        return {
            "role": "assistant",
            "content": f"抱歉，我没有理解您的意思。\n\n可用的数据文件：\n{df}\n\n请问您想分析哪些数据？",
            "action": "clarify",
        }

    # ---- Step 2: if info incomplete, return clarification question ----
    if not intent.get("ready", True):
        clarification = intent.get("clarification", "").strip()
        if not clarification:
            clarification = "请问您能再具体说明一下分析需求吗？比如想分析哪个年度、哪些指标？"
        # Append available file hint if user seems unsure
        if not intent.get("data_files") or len(intent.get("data_files", [])) == 0:
            clarification += f"\n\n目前可用的数据文件：\n{df}"
        return {
            "role": "assistant",
            "content": clarification,
            "action": "clarify",
            "data_files": intent.get("data_files", []),
        }

    # ---- Step 3: info complete, run analysis (existing logic below) ----
    data_files=intent.get("data_files",[intent.get("data_file","")])
    if isinstance(data_files,str):data_files=[data_files]
    focus=intent.get("focus","");confirm=intent.get("message","OK")

    try:
        first_raw=json.loads((DATA_DIR/data_files[0]).read_text(encoding="utf-8"))
        dtype=first_raw.get("data_type","")
        atype=first_raw.get("analysis_type","financial_statement")

        if dtype=="service_events":
            # Display-only: show events table grouped by dealer
            by_dealer=first_raw.get("by_dealer",{})
            lines=["### 经销商服务事件\n"]
            for did in sorted(by_dealer.keys()):
                evts=by_dealer[did]
                lines.append(f"**{did}** ({len(evts)}条)")
                for ev in evts:
                    t="配送延误" if ev["type"]=="delivery" else "回访"
                    detail=f"延误{ev['delay_days']}天" if ev.get("delay_days") else ev.get("follow_up_status","")
                    lines.append(f"- {ev['date']} {t} {detail} ({ev['source_ref']})")
                lines.append("")
            fmt="\n".join(lines)
            result={"analysis_type":"service_events","status":"complete","conclusions":[]}
            raw=first_raw

        elif dtype=="work_reports":
            # Display-only: show reports list
            rpts=first_raw.get("reports",[])
            lines=[f"### 工作汇报 ({len(rpts)}条)\n"]
            for r in rpts:
                lines.append(f"**{r['report_id']}** — {r['author']} ({r['date']})")
                if r.get('dealer_id'): lines.append(f"关联经销商: {r['dealer_id']}")
                lines.append(f"> {r['content']}")
                lines.append(f"来源: {r['source_ref']}\n")
            fmt="\n".join(lines)
            result={"analysis_type":"work_reports","status":"complete","conclusions":[]}
            raw=first_raw

        elif atype=="financial_statement":
            merged_records={}
            for fname in list(data_files):
                raw=json.loads((DATA_DIR/fname).read_text(encoding="utf-8"))
                for rec in raw.get("records",[]):
                    p=rec["period"]
                    if p not in merged_records:merged_records[p]={"period":p,"source_record_id":rec.get("source_record_id",p),"metrics":{}}
                    merged_records[p]["metrics"].update(rec.get("metrics",{}))
                try:
                    pv=str(int(fname[:4])-1);pf=pv+fname[4:]
                    if (DATA_DIR/pf).exists() and pf not in data_files:
                        pr=json.loads((DATA_DIR/pf).read_text(encoding="utf-8"))
                        for rec in pr.get("records",[]):
                            p=rec["period"]
                            if p not in merged_records:merged_records[p]={"period":p,"source_record_id":rec["source_record_id"],"metrics":{}}
                            merged_records[p]["metrics"].update(rec.get("metrics",{}))
                except:pass
            records=sorted(merged_records.values(),key=lambda r:r["period"])
            fm=intent.get("filter_months")
            if fm:
                keep = set(fm)
                for m in fm:
                    if m == 1:
                        keep.add(12)  # MoM for Jan needs Dec of previous year
                    else:
                        keep.add(m - 1)
                records = [r for r in records if int(r["period"].split("-")[1]) in keep]
            payload={"schema_version":"v1","trace_id":"m","analysis_type":"financial_statement","records":records}
            req=parse_analysis_request(payload)
            result=analyze_financial_statement(req)
            fmt=_format_financial(result,records=records)

        elif atype=="price_forecast":
            raw=first_raw
            req=parse_analysis_request(raw)
            result=forecast_prices(req)
            fmt=_format_price(result, records=raw.get("records",[]))

        elif atype=="business_metric":
            req=parse_analysis_request(first_raw)
            result=analyze_business_metrics(req)
            fmt=_format_business(result)
            raw=first_raw

        elif atype=="diagnostic":
            raw=first_raw
            entities=raw.get("entities",[])
            # Step 1: always show data table — rank by contribution magnitude
            fmt=_format_diagnostic_entities(entities)
            # Step 2: if user asks "why", run the diagnostic engine
            # (evidence comes from separate service events / work reports data files)
            is_why = any(w in user_message for w in ["为什么","原因","怎么回事","诊断","怎么","为何","是因为"])
            diag_result = None
            if is_why:
                req=parse_analysis_request(raw)
                diag_result=analyze_diagnostic(req)
                if diag_result.get("major_contributors") or diag_result.get("root_cause_hypotheses"):
                    fmt+="\n\n"+_format_diagnostic_root_cause(diag_result)
            result=diag_result if diag_result else {"analysis_type":"diagnostic","status":"complete","conclusions":[],"major_contributors":[],"root_cause_hypotheses":[]}

        else:return {"role":"assistant","content":"Unknown type: "+atype}
    except FileNotFoundError as e:return {"role":"assistant","content":"File not found: "+str(e)+"\nAvailable: "+df}
    except Exception as e:return {"role":"assistant","content":"Calculation failed: "+str(e)}

    try:
        if atype=="diagnostic" and is_why:
            # Root cause mode: send only diagnostic engine output
            compact=json.dumps({k:v for k,v in result.items() if k in ("analysis_type","status","major_contributors","root_cause_hypotheses","conclusions")},ensure_ascii=False,indent=2,default=str)
            system="你是经营诊断助手。只基于给定的诊断结果和证据做解读，绝不编造数据里不存在的信息。用中文回复。"
        elif atype=="diagnostic":
            # Data display mode: only show entity metrics, prevent hallucination
            entities=raw.get("entities",[])
            compact=json.dumps({"analysis_type":"diagnostic","status":"complete","entity_metrics":entities},ensure_ascii=False,indent=2,default=str)
            system="你是经营诊断助手。只基于给定的数据做分析，数据里有什么就说什么，绝不编造数据里不存在的信息。"
        elif dtype in ("service_events","work_reports"):
            # Display-only data: send the actual content so LLM doesn't fabricate
            compact=json.dumps(raw,ensure_ascii=False,indent=2,default=str)
            system="你是经营数据分析助手。只基于给定的数据做总结，数据里有什么就说什么，绝不编造数据里不存在的时间、数字或细节。用中文回复。"
        else:
            compact=json.dumps({k:v for k,v in result.items() if k in ("analysis_type","status","metrics","dupont","volatility","forecasts","history_window","uncertainty","net_profit","cost_ratios","target_comparisons","alert_candidates","conclusions","major_contributors","root_cause_hypotheses")},ensure_ascii=False,indent=2,default=str)
            recs=raw.get("records",[])
            if recs:compact+="\n\nSource data:\n"+json.dumps(recs,ensure_ascii=False,indent=2,default=str)
            system="你是专业顾问。用中文回复。"
        if dtype in ("service_events","work_reports"):
            prompt=compact+"\n\n用户: "+user_message+"\n\n根据数据内容做分析，有多少数据就分析多少。只描述数据中实际存在的内容，绝不编造。结尾：以上分析基于已有数据，仅供决策参考。"
        else:
            prompt=compact+"\n\n用户: "+user_message+"\n聚焦: "+focus+"\n\n引用具体数字做分析，根据数据量多少决定分析深度。数据里有什么就说什么，绝不编造数据里不存在的数字、指标或比率。结尾：以上分析由AI基于确定性计算结果生成，仅供决策参考。"
        narrative=_call_platform_text(system,prompt,2000)
    except Exception as e:narrative="(Narrative failed: "+str(e)+")"

    # ---- Store context for follow-up questions ----
    _last_analysis = {
        "type": atype if atype != "diagnostic" or not is_why else "diagnostic",
        "result": result,
        "raw_data": raw,
        "summary": narrative,
    }
    # For diagnostic display-only mode, also store entities for drill-down
    if atype == "diagnostic" and not is_why:
        _last_analysis["raw_data"]["analysis_type"] = "diagnostic"
    if dtype in ("service_events", "work_reports"):
        _last_analysis["type"] = dtype
        _last_analysis["raw_data"] = raw

    return {"role":"assistant","content":confirm+"\n\n"+fmt+"\n\n<!--CHARTS-->\n\n### AI 分析\n\n"+narrative,"action":intent.get("action",""),"data_files":data_files,"focus":focus,"result":_to_serializable(result),"records":_to_serializable(raw.get("records",[]))}
