from __future__ import annotations

import re

from app.services.task_extraction.intent_extractor import TaskCandidate


class TaskMerger:
    """Deduplicates overlapping candidates and derives direct task dependencies."""

    ACTION_FAMILIES = {
        "query": "data",
        "organize": "data",
        "export": "data",
        "analyze": "analysis",
        "compare": "analysis",
        "forecast": "analysis",
        "generate": "output",
        "convert": "output",
        "parse": "data",
        "filter": "data",
        "sort": "data",
    }

    def merge(self, candidates: list[TaskCandidate], *, original_text: str) -> list[TaskCandidate]:
        ordered = sorted(candidates, key=lambda item: (item.start, item.end))
        merged: list[TaskCandidate] = []
        for candidate in ordered:
            duplicate_index = self._merge_target(merged, candidate)
            if duplicate_index is None:
                merged.append(candidate.model_copy(deep=True))
            else:
                merged[duplicate_index] = self._combine(merged[duplicate_index], candidate)

        for index, candidate in enumerate(merged):
            if index == 0:
                candidate.depends_on_previous = False
                continue
            previous = merged[index - 1]
            between = original_text[previous.end : candidate.start]
            candidate.depends_on_previous = self._depends_on(previous, candidate, between)
        return merged

    def _merge_target(self, merged: list[TaskCandidate], candidate: TaskCandidate) -> int | None:
        for index, existing in enumerate(merged):
            if self._fingerprint(existing.normalized_text) == self._fingerprint(candidate.normalized_text):
                return index
            if existing.action != candidate.action:
                continue
            if self._object_root(existing) != self._object_root(candidate):
                continue
            if existing.action == "analyze":
                existing_reason = bool(re.search(r"原因|归因", existing.normalized_text))
                candidate_reason = bool(re.search(r"原因|归因", candidate.normalized_text))
                if existing_reason != candidate_reason:
                    continue
                return index
            if self._similarity(existing.normalized_text, candidate.normalized_text) >= 0.72:
                return index
        return None

    def _combine(self, primary: TaskCandidate, secondary: TaskCandidate) -> TaskCandidate:
        sources = list(primary.merged_sources)
        for value in secondary.merged_sources:
            if value not in sources:
                sources.append(value)
        constraints = list(primary.constraints)
        for value in secondary.constraints:
            if value not in constraints:
                constraints.append(value)
        normalized = primary.normalized_text
        if self._fingerprint(secondary.normalized_text) != self._fingerprint(primary.normalized_text):
            normalized = f"{primary.normalized_text}，重点{secondary.normalized_text}"
        return primary.model_copy(
            update={
                "normalized_text": normalized,
                "constraints": constraints,
                "end": max(primary.end, secondary.end),
                "confidence": max(primary.confidence, secondary.confidence),
                "merged_sources": sources,
            }
        )

    def _depends_on(self, previous: TaskCandidate, current: TaskCandidate, between: str) -> bool:
        if re.search(r"另外|此外|与此同时|独立", between):
            return False
        if re.search(r"然后|再|随后|最后|接着|并形成|并生成", between):
            return True
        if previous.action in {"query", "organize", "export"} and current.action in {"analyze", "compare", "forecast", "calculate"}:
            return True
        if current.action in {"generate", "convert", "sync"} and previous.action in {"analyze", "compare", "forecast", "calculate", "organize"}:
            return True
        return False

    def _object_root(self, candidate: TaskCandidate) -> str:
        value = candidate.business_object or candidate.normalized_text
        for root in ("销售", "经营", "客户投诉", "客户", "库存", "订单", "利润", "回款", "费用", "收入", "成本", "合同", "发票"):
            if root in value:
                return root
        return re.sub(r"查询|整理|计算|分析|比较|生成|预测|检查|转换|导出|同步|重点|情况|数据|表现|原因|区域", "", value)

    def _fingerprint(self, text: str) -> str:
        return re.sub(r"[\s，,。；;：:！？!?的了请帮我一下重点]", "", text.lower())

    def _similarity(self, left: str, right: str) -> float:
        left_chars = set(self._fingerprint(left))
        right_chars = set(self._fingerprint(right))
        if not left_chars or not right_chars:
            return 0
        return len(left_chars & right_chars) / len(left_chars | right_chars)
