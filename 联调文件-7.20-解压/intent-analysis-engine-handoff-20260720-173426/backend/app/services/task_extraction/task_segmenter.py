from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.services.task_extraction.long_text_parser import TextChunk


SegmentKind = Literal["background", "goal", "action", "constraint", "supplement"]


class SemanticSegment(BaseModel):
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    chunk_index: int = Field(ge=0)
    kind: SegmentKind
    confidence: float = Field(ge=0, le=1)


class TaskSegmenter:
    """Classifies rhetorical sentence roles before task candidate extraction."""

    ACTION_PATTERN = re.compile(
        r"查询|获取|调取|拉取|查看|列出|读取|解析|提取|抽取|筛选|过滤|排序|排名|整理|归集|汇总|统计|计算|核算|测算|分析|了解|比较|对比|同比|环比|生成|形成|制作|撰写|写|预测|预估|检查|审核|转换|导出|同步|推送|提交|提醒|监控|发起|启动|办理"
    )
    REQUEST_PATTERN = re.compile(r"请|需要|要求|希望|想要|务必|应当|应该|帮我|能否|可否|请把|请将")
    CONSTRAINT_PATTERN = re.compile(r"必须|不得|不要|仅限|范围|时间|截止|格式|口径|按照|基于|面向|给.{0,8}看")
    BACKGROUND_PATTERN = re.compile(r"背景|由于|因为|鉴于|目前|现状|此前|公司准备|会议提到|会上提到")
    PAST_STATEMENT_PATTERN = re.compile(r"^(?:我|我们|团队)(?:已经|曾经|之前)?(?:整理了|发现|注意到|看到|收到|讨论了|准备了)")
    NEGATED_ACTION_PATTERN = re.compile(
        r"(?:不需要|无需|不用|不要|暂不|先不).{0,6}(?:" + ACTION_PATTERN.pattern + r")"
    )

    def segment_chunk(self, chunk: TextChunk) -> list[SemanticSegment]:
        segments: list[SemanticSegment] = []
        for unit in chunk.units:
            for match in re.finditer(r"[^，,]+(?:[，,]|$)", unit.text):
                raw = match.group(0)
                value = raw.strip(" ，,")
                if not value:
                    continue
                leading = len(raw) - len(raw.lstrip())
                start = unit.start + match.start() + leading
                segments.append(
                    self._classify(
                        value,
                        start,
                        start + len(value),
                        chunk.chunk_index,
                    )
                )
        return segments

    def _classify(self, text: str, start: int, end: int, chunk_index: int) -> SemanticSegment:
        has_action = bool(self.ACTION_PATTERN.search(text))
        has_request = bool(self.REQUEST_PATTERN.search(text))
        negated = bool(self.NEGATED_ACTION_PATTERN.search(text))

        if self.PAST_STATEMENT_PATTERN.search(text) and not has_request:
            kind: SegmentKind = "background"
            confidence = 0.94
        elif self.BACKGROUND_PATTERN.search(text) and not (has_request and has_action):
            kind = "background"
            confidence = 0.9
        elif negated and not has_request:
            kind = "background"
            confidence = 0.9
        elif has_request and has_action:
            kind = "goal"
            confidence = 0.95
        elif has_action and self._action_is_predicate(text):
            kind = "action"
            confidence = 0.88
        elif self.CONSTRAINT_PATTERN.search(text):
            kind = "constraint"
            confidence = 0.84
        elif re.search(r"重点|尤其|其中|补充|另外说明|需要注意", text):
            kind = "supplement"
            confidence = 0.78
        else:
            kind = "background"
            confidence = 0.72

        return SemanticSegment(
            text=text,
            start=start,
            end=end,
            chunk_index=chunk_index,
            kind=kind,
            confidence=confidence,
        )

    def _action_is_predicate(self, text: str) -> bool:
        match = self.ACTION_PATTERN.search(text)
        if match is None:
            return False
        prefix = text[: match.start()].strip(" ，,：:")
        if not prefix:
            return True
        return bool(re.search(r"(?:并|然后|再|最后|另外|同时|后续|先|再请|还要)$", prefix))
