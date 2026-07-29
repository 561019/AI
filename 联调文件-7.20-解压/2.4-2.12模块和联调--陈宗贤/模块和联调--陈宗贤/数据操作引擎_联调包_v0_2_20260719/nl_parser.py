from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable


PERIOD_DASH_RE = re.compile(r"(?<!\d)(20\d{2})[-/.年](0?[1-9]|1[0-2])(?:月)?")


class NaturalLanguageParser:
    """Explainable parser for the demo's deliberately narrow aggregation domain.

    It maps Chinese business wording to registered fields. It never calculates a
    result and it never silently fills metric, company scope, period or grouping.
    """

    METRIC_ALIASES = {
        "sales_amount": ("销售金额", "销售额", "销售收入"),
        "expense_amount": ("费用金额", "费用额", "费用", "支出"),
        "frozen_metric": ("冻结指标", "已冻结测试指标"),
    }
    COMPANY_ALIASES = {
        "TEST-A": ("甲公司", "甲企业"),
        "TEST-B": ("乙公司", "乙企业"),
        "TEST-C": ("丙公司", "丙企业"),
    }
    DIMENSION_ALIASES = {
        "company_code": ("按公司", "分公司", "各公司", "每家公司", "公司维度"),
        "period": ("按月", "按月份", "按期间", "每月", "月份维度", "期间维度"),
        "department": ("按部门", "各部门", "每个部门", "部门维度"),
        "product": ("按产品", "各产品", "每个产品", "产品维度"),
    }

    def __init__(self, today_provider: Callable[[], date] | None = None):
        self._today = today_provider or date.today

    @staticmethod
    def _previous_month(value: date) -> str:
        year = value.year if value.month > 1 else value.year - 1
        month = value.month - 1 if value.month > 1 else 12
        return f"{year:04d}-{month:02d}"

    @staticmethod
    def _field(value: Any, evidence: list[str], confidence: float) -> dict[str, Any]:
        return {"value": value, "evidence": evidence, "confidence": confidence}

    def parse(self, text: str, registered_metrics: list[dict[str, Any]]) -> dict[str, Any]:
        raw = str(text or "").strip()
        compact = re.sub(r"\s+", "", raw)
        unresolved: list[dict[str, Any]] = []
        warnings: list[str] = []

        registered = {row["metric_id"]: row for row in registered_metrics}
        metric_hits: list[tuple[str, str]] = []
        for metric_id, aliases in self.METRIC_ALIASES.items():
            for alias in aliases:
                if alias in compact:
                    metric_hits.append((metric_id, alias))
                    break
        metric_ids = sorted({item[0] for item in metric_hits})
        if len(metric_ids) == 1 and metric_ids[0] in registered:
            metric_id = metric_ids[0]
            metric_evidence = [alias for mid, alias in metric_hits if mid == metric_id]
            metric_field = self._field(metric_id, metric_evidence, 0.99)
        else:
            metric_id = None
            metric_field = self._field(None, [alias for _, alias in metric_hits], 0.0)
            message = "一次请求只能确定一个已登记指标" if len(metric_ids) > 1 else "没有识别到已登记指标"
            unresolved.append({"field": "metric_id", "message": message, "suggestions": ["销售金额", "费用金额"]})

        companies: list[str] = []
        company_evidence: list[str] = []
        all_scope_phrases = ("全部三家公司", "三家公司", "全部公司", "所有公司", "集团全部公司")
        for phrase in all_scope_phrases:
            if phrase in compact:
                companies = ["TEST-A", "TEST-B", "TEST-C"]
                company_evidence.append(phrase)
                break
        if not companies and re.search(r"甲[、,，和及与]?乙[、,，和及与]?丙", compact):
            companies = ["TEST-A", "TEST-B", "TEST-C"]
            company_evidence.append("甲、乙、丙")
        if not companies:
            for company_code, aliases in self.COMPANY_ALIASES.items():
                for alias in aliases:
                    if alias in compact:
                        companies.append(company_code)
                        company_evidence.append(alias)
                        break
        companies = sorted(set(companies))
        company_field = self._field(companies, company_evidence, 0.98 if companies else 0.0)
        if not companies:
            unresolved.append({"field": "company_codes", "message": "没有明确公司数据范围，系统禁止默认查询全量", "suggestions": ["甲公司", "甲、乙、丙三家公司"]})

        period: str | None = None
        period_evidence: list[str] = []
        explicit_period = PERIOD_DASH_RE.search(compact)
        if explicit_period:
            period = f"{int(explicit_period.group(1)):04d}-{int(explicit_period.group(2)):02d}"
            period_evidence.append(explicit_period.group(0))
        elif "上个月" in compact or "上月" in compact:
            period = self._previous_month(self._today())
            period_evidence.append("上个月" if "上个月" in compact else "上月")
        elif "本月" in compact or "这个月" in compact:
            today = self._today()
            period = f"{today.year:04d}-{today.month:02d}"
            period_evidence.append("本月" if "本月" in compact else "这个月")
        period_field = self._field(period, period_evidence, 0.98 if period else 0.0)
        if not period:
            unresolved.append({"field": "period", "message": "没有识别到单月期间", "suggestions": ["2026年6月", "上个月"]})

        dimensions: list[str] = []
        dimension_evidence: list[str] = []
        for dimension, aliases in self.DIMENSION_ALIASES.items():
            for alias in aliases:
                if alias in compact:
                    dimensions.append(dimension)
                    dimension_evidence.append(alias)
                    break
        dimensions = list(dict.fromkeys(dimensions))
        dimension_field = self._field(dimensions, dimension_evidence, 0.96 if dimensions else 0.0)
        if not dimensions:
            unresolved.append({"field": "dimensions", "message": "没有明确汇总维度，系统不会猜测分组方式", "suggestions": ["按公司汇总", "按公司和部门汇总"]})

        destination = "csv" if any(word in compact.lower() for word in ("csv", "导出", "下载")) else "inline"
        destination_evidence = [word for word in ("CSV", "csv", "导出", "下载", "表") if word in raw]
        destination_field = self._field(destination, destination_evidence or ["默认页面结果"], 0.92)

        if not any(word in compact for word in ("汇总", "合计", "统计", "聚合", "总额")):
            warnings.append("语句未出现明确的汇总动词；系统仍按已识别字段生成聚合候选，请在执行前核对。")

        status = "ready" if not unresolved else "clarification_required"
        fields = {
            "metric_id": metric_field,
            "company_codes": company_field,
            "period": period_field,
            "dimensions": dimension_field,
            "result_destination": destination_field,
        }
        payload = None
        if status == "ready":
            payload = {
                "metric_id": metric_id,
                "dimensions": dimensions,
                "filters": {
                    "company_codes": companies,
                    "period_from": period,
                    "period_to": period,
                },
                "result_destination": destination,
            }
        confidence_values = [field["confidence"] for field in fields.values() if field["value"] not in (None, [], "")]
        return {
            "status": status,
            "intent": "data.aggregate" if metric_id else None,
            "confidence": round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0,
            "fields": fields,
            "unresolved": unresolved,
            "warnings": warnings,
            "payload": payload,
            "parser": {
                "mode": "explainable_local_domain_parser",
                "version": "1.0.0",
                "calculation_role": "none",
            },
        }
