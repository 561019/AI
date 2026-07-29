"""Chat service - NL -> intent -> engine -> LLM narrative."""

import json, os, re, urllib.request
from pathlib import Path
from datetime import date
from decimal import Decimal

from analysis_prediction_engine.contracts.requests import parse_analysis_request
from analysis_prediction_engine.services.business_metrics import analyze_business_metrics
from analysis_prediction_engine.services.financial_analysis import analyze_financial_statement
from analysis_prediction_engine.services.price_forecast import forecast_prices

DEEPSEEK_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent

_INTENT_PROMPT = """You are an intent parser. Extract JSON from user's Chinese message:

1. action: "financial"(financial statements), "price"(price forecast), or "business"(business metrics)
   "prediction"/"price"/"steel" -> price
   "profit"/"balance sheet"/"cash flow" -> financial
   "business"/"metric"/"cost ratio"/"law firm" -> business

2. data_files: pick ALL matching files. Always return ARRAY.
   "2023 profit statement" -> ["2023年利润表_请求体.json"]
   "2023 all three statements" -> all 3 financial files for 2023
   "predict steel price" -> ["2023-2025年钢材价格_请求体.json"]
   "2024 steel" -> ["2024年钢材价格_请求体.json"]

3. filter_months: month range as int array, null for full period
4. focus: one Chinese sentence describing the analysis angle
5. forecast_horizon: for price forecast, default 6

Available files:
{DATA_FILES}

Return ONLY valid JSON:
{"action":"price","data_files":["2023-2025年钢材价格_请求体.json"],"filter_months":null,"focus":"steel price trend forecast","forecast_horizon":6,"message":"OK"}"""

_LABELS = {
    "revenue":"营业收入","operating_cost":"营业成本","selling_expense":"销售费用",
    "admin_expense":"管理费用","rd_expense":"研发费用","finance_expense":"财务费用",
    "net_income":"净利润","total_assets":"总资产","total_liabilities":"总负债",
    "equity":"所有者权益","cash":"货币资金","accounts_receivable":"应收账款","inventory":"存货",
    "fixed_assets":"固定资产","accounts_payable":"应付账款","short_term_debt":"短期借款",
    "long_term_debt":"长期借款","operating_cashflow":"经营现金流",
}

def _call_deepseek(system, user, max_tokens=800):
    if not DEEPSEEK_API_KEY: raise RuntimeError("DEEPSEEK_API_KEY not set")
    body = json.dumps({"model":DEEPSEEK_MODEL,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"max_tokens":max_tokens,"temperature":0.3}).encode("utf-8")
    req = urllib.request.Request(f"{DEEPSEEK_BASE}/chat/completions",data=body,headers={"Content-Type":"application/json","Authorization":f"Bearer {DEEPSEEK_API_KEY}"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()

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

def _to_serializable(obj):
    if obj is None or isinstance(obj,(bool,int,float,str)):return obj
    if isinstance(obj,Decimal):return format(obj,"f")
    if isinstance(obj,date):return obj.isoformat()
    if hasattr(obj,"model_dump"):return _to_serializable(obj.model_dump())
    if isinstance(obj,dict):return {str(k):_to_serializable(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple,set)):return [_to_serializable(v) for v in obj]
    return str(obj)

def chat(user_message, conversation_history=None):
    if not DEEPSEEK_API_KEY:return {"role":"error","content":"DEEPSEEK_API_KEY not configured."}
    fs=sorted(p for p in DATA_DIR.glob("20*.json") if any(c.isdigit() for c in p.stem[:4]))
    df="\n".join("- "+p.name for p in fs) if fs else "(none)"
    try:
        ri=_call_deepseek(_INTENT_PROMPT.replace("{DATA_FILES}",df),user_message,300).strip()
        if ri.startswith("```"):ri=ri.split("\n",1)[-1].rsplit("```",1)[0].strip()
        if "{" in ri and "}" in ri:ri=ri[ri.index("{"):ri.rindex("}")+1]
        ri=re.sub(r"'([a-z_]+)'\s*:",r'"\1":',ri);ri=re.sub(r":\s*'([^']*)'",r':"\1"',ri)
        intent=json.loads(ri)
    except Exception as e:
        return {"role":"assistant","content":"Unable to parse intent.\n("+str(e)+")\n\nAvailable: "+df}
    data_files=intent.get("data_files",[intent.get("data_file","")])
    if isinstance(data_files,str):data_files=[data_files]
    focus=intent.get("focus","");confirm=intent.get("message","OK")

    try:
        first_raw=json.loads((DATA_DIR/data_files[0]).read_text(encoding="utf-8"))
        atype=first_raw.get("analysis_type","financial_statement")

        if atype=="financial_statement":
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
            if fm:records=[r for r in records if int(r["period"].split("-")[1]) in fm]
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

        else:return {"role":"assistant","content":"Unknown type: "+atype}
    except FileNotFoundError as e:return {"role":"assistant","content":"File not found: "+str(e)+"\nAvailable: "+df}
    except Exception as e:return {"role":"assistant","content":"Calculation failed: "+str(e)}

    try:
        compact=json.dumps({k:v for k,v in result.items() if k in ("analysis_type","status","metrics","dupont","volatility","forecasts","history_window","uncertainty","net_profit","cost_ratios","target_comparisons","alert_candidates","conclusions")},ensure_ascii=False,indent=2,default=str)
        recs=raw.get("records",[])
        if recs:compact+="\n\nSource data:\n"+json.dumps(recs,ensure_ascii=False,indent=2,default=str)
        prompt="你是企业经营分析顾问。\n\n"+compact+"\n\n用户: "+user_message+"\n聚焦: "+focus+"\n\n按聚焦指令分析，引用数字，800字以内。结尾：以上分析由AI基于确定性计算结果生成，仅供决策参考。"
        narrative=_call_deepseek("你是专业顾问。用中文回复。",prompt,2000)
    except Exception as e:narrative="(Narrative failed: "+str(e)+")"

    return {"role":"assistant","content":confirm+"\n\n"+fmt+"\n\n<!--CHARTS-->\n\n### AI 分析\n\n"+narrative,"action":intent.get("action",""),"data_files":data_files,"focus":focus,"result":_to_serializable(result),"records":_to_serializable(raw.get("records",[]))}
