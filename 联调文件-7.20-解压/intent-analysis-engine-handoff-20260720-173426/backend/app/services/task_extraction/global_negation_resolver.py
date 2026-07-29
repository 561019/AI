from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.services.task_extraction.future_scope_filter import FutureScopeFilter
from app.services.task_extraction.intent_extractor import TaskCandidate


class NegationDirective(BaseModel):
    marker: str
    target_text: str
    source_text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class GlobalNegationResolution(BaseModel):
    active_candidates: list[TaskCandidate] = Field(default_factory=list)
    removed_candidates: list[TaskCandidate] = Field(default_factory=list)
    directives: list[NegationDirective] = Field(default_factory=list)


class GlobalNegationResolver:
    """Applies later cancellation and deferral directives to earlier task candidates."""

    ACTION_TERMS = {
        "analyze": ("分析", "对比", "比较", "归因", "诊断"),
        "compare": ("分析", "对比", "比较"),
        "calculate": ("计算", "核算", "测算"),
        "generate": ("生成", "整理", "制作", "报告", "材料", "文档"),
        "monitor": ("提醒", "监控", "预警", "告警"),
        "organize": ("整理", "归集", "汇总"),
        "query": ("查询", "获取", "调取"),
    }
    DOMAIN_TERMS = (
        "销售",
        "经营",
        "客户",
        "订单",
        "产品",
        "库存",
        "利润",
        "回款",
        "费用",
        "收入",
        "成本",
        "合同",
        "发票",
        "提成",
        "佣金",
        "数据",
        "报告",
        "材料",
        "文档",
        "提醒",
        "监控",
        "预警",
    )

    def __init__(self, *, future_scope_filter: FutureScopeFilter | None = None) -> None:
        self.future_scope_filter = future_scope_filter or FutureScopeFilter()

    def resolve(self, candidates: list[TaskCandidate], *, original_text: str) -> GlobalNegationResolution:
        directives = self._directives(original_text)
        active: list[TaskCandidate] = []
        removed: list[TaskCandidate] = []
        for candidate in candidates:
            cancelled = any(
                candidate.start < directive.start and self._matches(candidate, directive.target_text)
                for directive in directives
                if directive.target_text
            ) or self.future_scope_filter.should_remove_candidate_text(
                candidate_text=self._candidate_text(candidate),
                original_text=original_text,
                candidate_start=candidate.start,
                candidate_end=candidate.end,
                target_matches=lambda target: self._matches(candidate, target),
            )
            (removed if cancelled else active).append(candidate.model_copy(deep=True))
        return GlobalNegationResolution(
            active_candidates=active,
            removed_candidates=removed,
            directives=directives,
        )

    def _directives(self, text: str) -> list[NegationDirective]:
        directives: list[NegationDirective] = []
        seen: set[tuple[int, int, str]] = set()
        for exclusion in self.future_scope_filter.find_exclusions(text):
            target = self._clean_target(exclusion.target_text)
            if target and not self._has_task_concept(target) and not self.future_scope_filter.is_broad_target(target):
                continue
            key = (exclusion.start, exclusion.end, target)
            if key in seen:
                continue
            seen.add(key)
            directives.append(
                NegationDirective(
                    marker=exclusion.marker,
                    target_text=target,
                    source_text=exclusion.source_text,
                    start=exclusion.start,
                    end=exclusion.end,
                )
            )
        return sorted(directives, key=lambda item: (item.start, item.end))

    def _clean_target(self, value: str) -> str:
        cleaned = value.strip(" ，,。；;！？!?：:")
        cleaned = re.sub(r"^(?:目前|现阶段|这个|这项|该|相关)", "", cleaned)
        cleaned = re.sub(r"(?:功能|事项|工作|任务)$", "", cleaned)
        return cleaned.strip()

    def _has_task_concept(self, target: str) -> bool:
        action_terms = {value for values in self.ACTION_TERMS.values() for value in values}
        return any(term in target for term in (*action_terms, *self.DOMAIN_TERMS))

    def _matches(self, candidate: TaskCandidate, target: str) -> bool:
        candidate_text = self._candidate_text(candidate)
        if candidate.action == "monitor" and any(term in target for term in ("提醒", "监控", "预警", "告警")):
            return True
        if candidate.action == "generate" and any(term in target for term in ("报告", "材料", "文档")):
            return True

        action_matches = any(term in target for term in self.ACTION_TERMS.get(candidate.action, ()))
        shared_domains = [term for term in self.DOMAIN_TERMS if term in target and term in candidate_text]
        return action_matches and bool(shared_domains)

    def _candidate_text(self, candidate: TaskCandidate) -> str:
        return "，".join(
            [candidate.normalized_text, candidate.source_text, candidate.business_object, *candidate.merged_sources]
        )
