"""
LLM narrative service — calls DeepSeek API to interpret structured analysis results.

All numerical conclusions are already computed by deterministic tools; the LLM
only reads the computed numbers and produces human-readable interpretation.
It never computes, never accesses raw data, and always includes a disclaimer.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

DEEPSEEK_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

_PROMPTS: dict[str, str] = {
    "financial_statement": """你是一位资深财务分析师。以下是一家企业经过确定性计算后的财务报表分析结果。
所有数字已经过精确计算，你不需要重新计算，只需要解读。

分析结果（JSON）：
{payload}

请用中文给出简洁的经营分析解读，要求：
1. 先一句话总结整体趋势（上升/下降/稳定）
2. 引用具体的同比、环比数字（如"营业收入同比上升25.00%"）
3. 指出杜邦分析中ROE的主要驱动因素
4. 如有异常指标（Z-score检测到的），点出最显著的1-2个
5. 全文不超过250字
6. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "price_forecast": """你是一位采购分析顾问。以下是经过确定性模型计算后的原料价格预测结果。
所有数字已经过精确计算，你不需要重新计算，只需要解读。

分析结果（JSON）：
{payload}

请用中文给出简洁的价格预测解读，要求：
1. 先一句话说明价格走势方向和历史区间
2. 引用预测区间的具体数字
3. 说明波动程度（价格范围和相对波动百分比）
4. 提醒预测的不确定性
5. 全文不超过200字
6. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "business_metric": """你是一位经营管理顾问。以下是经过确定性计算后的经营指标分析结果。
所有数字已经过精确计算，你不需要重新计算，只需要解读。

分析结果（JSON）：
{payload}

请用中文给出简洁的经营指标解读，要求：
1. 先一句话说明净利润情况
2. 逐项分析各成本占比，与目标值对比
3. 如有超标项，明确指出并说明超出幅度
4. 全文不超过200字
5. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",
}


def _build_prompt(analysis_type: str, payload: dict[str, Any]) -> str:
    template = _PROMPTS.get(analysis_type)
    if template is None:
        raise ValueError(f"unsupported analysis_type: {analysis_type}")
    compact = {
        "analysis_type": payload.get("analysis_type"),
        "status": payload.get("status"),
        "conclusions": payload.get("conclusions"),
    }
    if analysis_type == "financial_statement":
        compact["metrics_summary"] = {
            metric: {
                k: v
                for k, v in info.items()
                if k in ("current", "trend", "trend_slope", "period_over_period_percent",
                         "year_over_year_percent", "anomalies")
            }
            for metric, info in payload.get("metrics", {}).items()
        }
        compact["dupont"] = payload.get("dupont", {})
    elif analysis_type == "price_forecast":
        compact["volatility"] = payload.get("volatility", {})
        compact["forecasts"] = payload.get("forecasts", ())
        compact["history_window"] = payload.get("history_window", {})
        compact["uncertainty"] = payload.get("uncertainty", {})
    elif analysis_type == "business_metric":
        compact["net_profit"] = payload.get("net_profit")
        compact["cost_ratios"] = payload.get("cost_ratios")
        compact["target_comparisons"] = payload.get("target_comparisons")
        compact["alert_candidates"] = payload.get("alert_candidates", ())
    return template.format(payload=json.dumps(compact, ensure_ascii=False, indent=2, default=str))


def narrate(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate a natural-language narrative for a computed analysis result."""
    analysis_type = payload.get("analysis_type", "")
    if not DEEPSEEK_API_KEY:
        return {
            "schema_version": "v1",
            "trace_id": payload.get("trace_id", ""),
            "analysis_type": analysis_type,
            "narrative": "",
            "status": "skipped",
            "reason": "DEEPSEEK_API_KEY is not configured",
        }

    prompt = _build_prompt(analysis_type, payload)
    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的企业经营分析助手。只基于给定的数据给出解读，不编造数据。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 600,
        "temperature": 0.3,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{DEEPSEEK_BASE}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        narrative = result["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return {
            "schema_version": "v1",
            "trace_id": payload.get("trace_id", ""),
            "analysis_type": analysis_type,
            "narrative": "",
            "status": "error",
            "reason": f"LLM call failed: {exc}",
        }

    return {
        "schema_version": "v1",
        "trace_id": payload.get("trace_id", ""),
        "analysis_type": analysis_type,
        "narrative": narrative,
        "status": "complete",
        "model": DEEPSEEK_MODEL,
    }
