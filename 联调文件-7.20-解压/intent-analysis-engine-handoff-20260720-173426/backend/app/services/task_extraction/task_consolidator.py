from __future__ import annotations

import re

from app.services.task_extraction.intent_extractor import TaskCandidate


class TaskConsolidator:
    """Consolidates semantic task families while retaining their source subgoals."""

    REASON_PATTERN = re.compile(r"原因|归因|导致|是不是|是否|关联|下降情况|订单减少|竞争力不足")
    REPORT_PATTERN = re.compile(r"报告|材料|文档|PPT|汇报")
    COMMISSION_PATTERN = re.compile(r"销售提成|销售人员.{0,3}提成|提成|佣金")
    SALES_PATTERN = re.compile(r"销售|经营")

    def consolidate(self, candidates: list[TaskCandidate], *, original_text: str) -> list[TaskCandidate]:
        del original_text
        consolidated: list[TaskCandidate] = []
        cluster_indexes: dict[tuple[str, ...], int] = {}
        for candidate in sorted(candidates, key=lambda item: (item.start, item.end)):
            key = self._cluster_key(candidate)
            if key is None:
                consolidated.append(candidate.model_copy(deep=True))
                continue
            existing_index = cluster_indexes.get(key)
            if existing_index is None:
                cluster_indexes[key] = len(consolidated)
                consolidated.append(self._canonicalize(candidate, key))
                continue
            consolidated[existing_index] = self._combine(consolidated[existing_index], candidate, key)
        return consolidated

    def _cluster_key(self, candidate: TaskCandidate) -> tuple[str, ...] | None:
        text = self._all_text(candidate)
        complaint_context = "投诉" in text and "销售" not in text and "经营" not in text
        if complaint_context:
            return None
        if candidate.action in {"analyze", "compare"} and (
            self.SALES_PATTERN.search(text)
            or (self.REASON_PATTERN.search(text) and re.search(r"客户|订单|产品", text))
        ):
            subtype = "reason" if self.REASON_PATTERN.search(text) else "overview"
            return ("sales_analysis", subtype)
        if candidate.action == "generate" and self.REPORT_PATTERN.search(text):
            return ("business_report",)
        if candidate.action == "calculate" and (self.COMMISSION_PATTERN.search(text) or "销售" in text):
            return ("sales_commission",)
        if (
            candidate.action in {"organize", "query"}
            and self.SALES_PATTERN.search(text)
            and not re.search(r"汇总|统计|合计|求和", text)
        ):
            return (candidate.action, "sales_data")
        return None

    def _canonicalize(self, candidate: TaskCandidate, key: tuple[str, ...]) -> TaskCandidate:
        action, business_object, normalized_text = self._canonical_values(candidate, key)
        return candidate.model_copy(
            deep=True,
            update={
                "action": action,
                "business_object": business_object,
                "normalized_text": normalized_text,
            },
        )

    def _combine(
        self,
        primary: TaskCandidate,
        secondary: TaskCandidate,
        key: tuple[str, ...],
    ) -> TaskCandidate:
        sources = list(primary.merged_sources)
        for value in secondary.merged_sources or [secondary.source_text]:
            if value not in sources:
                sources.append(value)
        constraints = list(primary.constraints)
        for value in secondary.constraints:
            if value not in constraints:
                constraints.append(value)
        action, business_object, normalized_text = self._canonical_values(primary, key)
        return primary.model_copy(
            update={
                "action": action,
                "business_object": business_object,
                "normalized_text": normalized_text,
                "constraints": constraints,
                "confidence": max(primary.confidence, secondary.confidence),
                "merged_sources": sources,
            }
        )

    def _canonical_values(
        self,
        candidate: TaskCandidate,
        key: tuple[str, ...],
    ) -> tuple[str, str, str]:
        if key == ("sales_analysis", "overview"):
            return "analyze", "销售经营", "分析销售经营情况"
        if key == ("sales_analysis", "reason"):
            return "analyze", "销售", "分析销售下降原因"
        if key == ("business_report",):
            return "generate", "经营", "生成经营分析报告"
        if key == ("sales_commission",):
            return "calculate", "销售提成", "计算销售提成"
        if key == ("organize", "sales_data"):
            return "organize", "销售数据", "整理销售数据"
        if key == ("query", "sales_data"):
            return "query", "销售数据", "查询销售数据"
        return candidate.action, candidate.business_object, candidate.normalized_text

    def _all_text(self, candidate: TaskCandidate) -> str:
        return "，".join(
            [candidate.normalized_text, candidate.source_text, candidate.business_object, *candidate.merged_sources]
        )
