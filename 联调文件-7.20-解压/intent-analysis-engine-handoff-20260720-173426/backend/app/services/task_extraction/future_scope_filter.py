from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class FutureScopeExclusion:
    marker: str
    target_text: str
    source_text: str
    start: int
    end: int


class FutureScopeFilter:
    """Removes future/planning candidates when the current scope explicitly excludes them."""

    FUTURE_SCOPE_PATTERN = re.compile(r"未来规划|未来考虑|未来|以后|后续|将来|后面")
    EXCLUSION_MARKERS = (
        "目前不包含",
        "目前不包括",
        "本次不考虑",
        "本次不需要",
        "本次不做",
        "暂时不需要",
        "暂不需要",
        "暂时不用",
        "不用考虑",
        "暂不用",
        "先不要",
        "不包含",
        "不包括",
        "不考虑",
        "不需要",
        "不用",
        "取消",
        "以后再做",
    )
    ACTION_TERMS = (
        "查询",
        "获取",
        "调取",
        "拉取",
        "查看",
        "列出",
        "读取",
        "解析",
        "提取",
        "抽取",
        "筛选",
        "过滤",
        "排序",
        "排名",
        "整理",
        "归集",
        "汇总",
        "统计",
        "计算",
        "核算",
        "测算",
        "分析",
        "了解",
        "比较",
        "对比",
        "生成",
        "形成",
        "制作",
        "撰写",
        "写",
        "预测",
        "预估",
        "检查",
        "审核",
        "转换",
        "导出",
        "同步",
        "推送",
        "提交",
        "提醒",
        "监控",
        "预警",
        "告警",
        "发起",
        "启动",
        "办理",
    )
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
        "异常",
        "负责人",
        "提醒",
        "监控",
        "预警",
        "告警",
    )
    GENERIC_TARGET_PATTERN = re.compile(
        r"^(?:相关|对应|上述|以上|这些|这类|此类)?(?:功能|事项|工作|任务|能力|内容)?$"
        r"|(?:相关|对应|上述|以上|这些|这类|此类).{0,8}(?:功能|事项|工作|任务|能力|内容)"
    )
    SCOPE_PREFIX_PATTERN = re.compile(r"本次|这次|当前|目前|现阶段|范围|任务范围")
    CLAUSE_PATTERN = re.compile(r"[^，,。；;！？!?\n]+")

    _BOUNDARY_CHARS = "，,。；;！？!?\n"
    _MARKER_PATTERN = "|".join(re.escape(marker) for marker in sorted(EXCLUSION_MARKERS, key=len, reverse=True))
    FORWARD_PATTERN = re.compile(rf"(?P<marker>{_MARKER_PATTERN})(?P<target>[^{_BOUNDARY_CHARS}]{{0,40}})")
    REVERSE_PATTERN = re.compile(rf"(?P<target>[^{_BOUNDARY_CHARS}]{{1,32}}?)(?P<marker>{_MARKER_PATTERN})")

    def is_future_scoped(self, text: str) -> bool:
        return bool(self.FUTURE_SCOPE_PATTERN.search(text))

    def is_task_like(self, text: str) -> bool:
        return any(term in text for term in (*self.ACTION_TERMS, *self.DOMAIN_TERMS))

    def remove_excluded_future_scope(self, text: str) -> str:
        kept: list[str] = []
        removed_any = False
        for clause, start, end in self.iter_clauses(text):
            if self.should_remove_candidate_text(
                candidate_text=clause,
                original_text=text,
                candidate_start=start,
                candidate_end=end,
            ):
                removed_any = True
                continue
            kept.append(clause)
        if not removed_any:
            return text
        return "，".join(kept).strip(" ，,。；;！？!?")

    def text_is_fully_excluded(self, text: str) -> bool:
        task_like_clauses = [
            (clause, start, end)
            for clause, start, end in self.iter_clauses(text)
            if self.is_task_like(clause) and not self._is_pure_exclusion(clause)
        ]
        if not task_like_clauses:
            return False
        return all(
            self.should_remove_candidate_text(
                candidate_text=clause,
                original_text=text,
                candidate_start=start,
                candidate_end=end,
            )
            for clause, start, end in task_like_clauses
        )

    def should_remove_candidate_text(
        self,
        *,
        candidate_text: str,
        original_text: str,
        candidate_start: int,
        candidate_end: int,
        target_matches: Callable[[str], bool] | None = None,
    ) -> bool:
        if not self._candidate_is_future_scoped(candidate_text, original_text, candidate_start, candidate_end):
            return False

        for exclusion in self.find_exclusions(original_text):
            if exclusion.start <= candidate_start:
                continue
            if exclusion.target_text == "" or self.is_broad_target(exclusion.target_text):
                return True
            if target_matches is not None and target_matches(exclusion.target_text):
                return True
            if self._text_terms_overlap(candidate_text, exclusion.target_text):
                return True
        return False

    def find_exclusions(self, text: str) -> list[FutureScopeExclusion]:
        exclusions: list[FutureScopeExclusion] = []
        seen: set[tuple[int, int, str, str]] = set()
        for pattern, allow_empty_target in ((self.FORWARD_PATTERN, True), (self.REVERSE_PATTERN, False)):
            for match in pattern.finditer(text):
                marker = match.group("marker")
                if marker in {"不包含", "不包括"} and not self.SCOPE_PREFIX_PATTERN.search(
                    text[max(0, match.start() - 16) : match.start()]
                ):
                    continue
                target = self.clean_target(match.group("target"))
                if not target and not allow_empty_target:
                    continue
                key = (match.start(), match.end(), marker, target)
                if key in seen:
                    continue
                seen.add(key)
                exclusions.append(
                    FutureScopeExclusion(
                        marker=marker,
                        target_text=target,
                        source_text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                    )
                )
        return sorted(exclusions, key=lambda item: (item.start, item.end))

    def iter_clauses(self, text: str) -> list[tuple[str, int, int]]:
        clauses: list[tuple[str, int, int]] = []
        for match in self.CLAUSE_PATTERN.finditer(text):
            value = match.group(0).strip()
            if not value:
                continue
            leading = len(match.group(0)) - len(match.group(0).lstrip())
            start = match.start() + leading
            clauses.append((value, start, start + len(value)))
        return clauses

    def clean_target(self, value: str) -> str:
        cleaned = value.strip(" ，,。；;！？!?：:")
        cleaned = re.sub(r"^(?:但|但是|不过|目前|当前|现阶段|本次|这次|这个|这项|该|相关)", "", cleaned)
        cleaned = re.sub(r"^(?:任务)?范围(?:里面|里)?", "", cleaned)
        cleaned = re.sub(r"(?:功能|事项|工作|任务)$", "", cleaned)
        return cleaned.strip()

    def is_broad_target(self, target: str) -> bool:
        return bool(self.GENERIC_TARGET_PATTERN.search(target.strip()))

    def _candidate_is_future_scoped(
        self,
        candidate_text: str,
        original_text: str,
        candidate_start: int,
        candidate_end: int,
    ) -> bool:
        window = original_text[max(0, candidate_start - 12) : candidate_end]
        return self.is_future_scoped(candidate_text) or self.is_future_scoped(window)

    def _text_terms_overlap(self, candidate_text: str, target: str) -> bool:
        if any(term in candidate_text for term in ("提醒", "监控", "预警", "告警")) and any(
            term in target for term in ("提醒", "监控", "预警", "告警")
        ):
            return True
        candidate_terms = {term for term in (*self.ACTION_TERMS, *self.DOMAIN_TERMS) if term in candidate_text}
        target_terms = {term for term in (*self.ACTION_TERMS, *self.DOMAIN_TERMS) if term in target}
        return bool(candidate_terms & target_terms)

    def _is_pure_exclusion(self, text: str) -> bool:
        stripped = text.strip(" ，,。；;！？!?")
        return any(stripped.endswith(marker) or stripped == marker for marker in self.EXCLUSION_MARKERS)
