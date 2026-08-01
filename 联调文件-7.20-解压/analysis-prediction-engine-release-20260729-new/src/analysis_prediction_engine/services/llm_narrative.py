"""
LLM narrative service — calls the platform model dispatcher to interpret structured analysis results.

All numerical conclusions are already computed by deterministic tools; the LLM
only reads the computed numbers and produces human-readable interpretation.
It never computes, never accesses raw data, and always includes a disclaimer.
"""

from __future__ import annotations

import json
from typing import Any

from analysis_prediction_engine.method_registry import LLM_NARRATIVE_VERSION
from analysis_prediction_engine.services.platform_model_client import call_platform_model

_PROMPTS: dict[str, str] = {
    "financial_statement": """你是一位资深财务分析师。以下是一家企业经过确定性计算后的财务报表分析结果。
所有数字已经过精确计算，你不需要重新计算，只需要解读。

分析结果（JSON）：
{payload}

请用中文给出经营分析解读，根据数据量多少决定分析深度，要求：
1. 总结整体趋势（上升/下降/稳定），引用具体同比、环比数字
2. 分析杜邦分析中ROE的驱动因素
3. 如有异常指标（Z-score检测到的），逐项指出
4. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "price_forecast": """你是一位采购分析顾问。以下是经过确定性模型计算后的原料价格预测结果。
所有数字已经过精确计算，你不需要重新计算，只需要解读。

分析结果（JSON）：
{payload}

请用中文给出价格预测解读，根据数据量多少决定分析深度，要求：
1. 说明价格走势方向和历史区间，引用具体数字
2. 分析预测区间，说明波动程度
3. 提醒预测的不确定性
4. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "business_metric": """你是一位经营管理顾问。以下是经过确定性计算后的经营指标分析结果。
所有数字已经过精确计算，你不需要重新计算，只需要解读。

分析结果（JSON）：
{payload}

请用中文给出经营指标解读，根据数据量多少决定分析深度，要求：
1. 分析净利润情况
2. 逐项分析各成本占比，与目标值对比
3. 如有超标项，明确指出并说明超出幅度
4. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "diagnostic": """你是一位经营诊断分析师。以下是经过确定性计算后的诊断分析结果。
所有数值已经过精确计算，根因假设已由AI基于证据生成，你只需要解读。

分析结果（JSON）：
{payload}

请用中文给出诊断结论解读，根据证据量多少决定分析深度，要求：
1. 说明诊断目标和主要发现
2. 列出主要贡献实体及其贡献度
3. 逐条解读根因假设，引用支持证据
4. 强调结论为假设性质，需人工确认
5. 结尾必须附上：「⚠️ 以上诊断假设由AI基于已有证据生成，仅供决策参考，须经真人确认后生效。」""",
}

_FOLLOW_UP_PROMPTS: dict[str, str] = {
    "financial_statement": """你是一位资深财务分析师。用户刚才看过一份财务报表的总体分析，现在对某个细节进行追问。

下钻数据（已包含逐期明细、异常标记和杜邦分解）：
{drilldown_data}

上轮分析摘要（供你了解上下文，不要重复）：
{prev_summary}

用户追问：{question}

请针对追问给出分析：
1. 直接回答问题，不要复述总体报告已说过的内容
2. 从下钻数据中引用具体数字和指标
3. 如果数据不足以回答，如实说明
4. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "price_forecast": """你是一位采购分析顾问。用户刚才看过价格预测的总体分析，现在对某个细节进行追问。

下钻数据（已包含历史价格变化率、波动性指标和预测区间明细）：
{drilldown_data}

上轮分析摘要（供你了解上下文，不要重复）：
{prev_summary}

用户追问：{question}

请针对追问给出分析：
1. 直接回答问题，不要复述总体报告已说过的内容
2. 从下钻数据中引用具体数字
3. 提醒预测的不确定性
4. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "business_metric": """你是一位经营管理顾问。用户刚才看过经营指标的总体分析，现在对某个细节进行追问。

下钻数据（已包含成本结构分解、目标对比和告警明细）：
{drilldown_data}

上轮分析摘要（供你了解上下文，不要重复）：
{prev_summary}

用户追问：{question}

请针对追问给出分析：
1. 直接回答问题，不要复述总体报告已说过的内容
2. 从下钻数据中引用具体数字，说明超标幅度和影响
3. 如果数据不足以回答，如实说明
4. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",

    "diagnostic": """你是一位经营诊断分析师。用户刚才看过诊断分析结果，现在对某个细节进行追问。

下钻数据（已包含实体排名、贡献度分解和证据记录）：
{drilldown_data}

上轮分析摘要（供你了解上下文，不要重复）：
{prev_summary}

用户追问：{question}

请针对追问给出分析：
1. 直接回答问题，不要复述总体报告已说过的内容
2. 引用证据记录中的具体内容（证据编号、日期、摘要）
3. 使用"证据显示""初步判断""值得关注的是"等审慎措辞
4. 如果证据不足以支持判断，如实说明
5. 结尾必须附上：「⚠️ 以上分析由AI基于已有证据生成，仅供决策参考，须经真人确认后生效。」""",

    "generic": """你是一位企业经营分析顾问。用户刚才看过一份分析报告，现在对某个细节进行追问。

下钻数据：
{drilldown_data}

上轮分析摘要（供你了解上下文，不要重复）：
{prev_summary}

用户追问：{question}

请针对追问给出分析：
1. 直接回答问题，不要复述总体报告已说过的内容
2. 从下钻数据中引用具体数字
3. 如果数据不足以回答，如实说明
4. 结尾必须附上：「⚠️ 以上分析由AI基于确定性计算结果生成，仅供决策参考，须经真人确认后生效。」""",
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
    prompt = _build_prompt(analysis_type, payload)
    result = call_platform_model(
        trace_id=str(payload.get("trace_id") or ""),
        task_type="analysis_prediction_narrative",
        system="你是一个专业的企业经营分析助手。只基于给定的数据给出解读，不编造数据。",
        user=prompt,
        max_tokens=600,
        temperature=0.3,
        output_kind="text",
    )
    if result["status"] != "complete":
        return {
            "schema_version": "v1",
            "trace_id": payload.get("trace_id", ""),
            "analysis_type": analysis_type,
            "narrative": "",
            "status": "error",
            "reason": result["reason"],
            "model_version": LLM_NARRATIVE_VERSION,
        }

    return {
        "schema_version": "v1",
        "trace_id": payload.get("trace_id", ""),
        "analysis_type": analysis_type,
        "narrative": result["text"],
        "status": "complete",
        "model": result.get("model") or "platform-model-dispatcher",
        "provider": result.get("provider"),
        "model_call_id": result.get("model_call_id"),
        "model_version": LLM_NARRATIVE_VERSION,
    }


def narrate_follow_up(
    analysis_type: str,
    prev_summary: str,
    drilldown_data: str,
    question: str,
) -> dict[str, Any]:
    """Generate a follow-up narrative for a drill-down question.

    Uses the follow-up prompt templates which include the previous analysis
    summary, drill-down data, and the user's specific question.
    """
    template = _FOLLOW_UP_PROMPTS.get(analysis_type, _FOLLOW_UP_PROMPTS["generic"])
    prompt = template.format(
        prev_summary=prev_summary,
        drilldown_data=drilldown_data,
        question=question,
    )

    result = call_platform_model(
        trace_id="",
        task_type="analysis_prediction_follow_up",
        system="你是一个专业的企业经营分析助手。只基于给定的数据给出解读，不编造数据。",
        user=prompt,
        max_tokens=800,
        temperature=0.3,
        output_kind="text",
    )
    if result["status"] != "complete":
        return {
            "schema_version": "v1",
            "trace_id": "",
            "analysis_type": analysis_type,
            "narrative": "",
            "status": "error",
            "reason": result["reason"],
            "model_version": LLM_NARRATIVE_VERSION,
        }

    return {
        "schema_version": "v1",
        "trace_id": "",
        "analysis_type": analysis_type,
        "narrative": result["text"],
        "status": "complete",
        "model": result.get("model") or "platform-model-dispatcher",
        "provider": result.get("provider"),
        "model_call_id": result.get("model_call_id"),
        "model_version": LLM_NARRATIVE_VERSION,
    }
