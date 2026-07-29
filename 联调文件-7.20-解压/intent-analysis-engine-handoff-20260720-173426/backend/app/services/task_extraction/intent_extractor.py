from __future__ import annotations

import re
from uuid import uuid4

from pydantic import BaseModel, Field

from app.services.task_extraction.long_text_parser import LongTextDocument, LongTextParser
from app.services.task_extraction.task_segmenter import SemanticSegment, TaskSegmenter


class TaskCandidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    source_text: str
    normalized_text: str
    action: str
    business_object: str
    constraints: list[str] = Field(default_factory=list)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    source_kind: str
    depends_on_previous: bool = False
    merged_sources: list[str] = Field(default_factory=list)


class LongContextExtractionResult(BaseModel):
    document: LongTextDocument
    segments: list[SemanticSegment]
    raw_candidates: list[TaskCandidate]
    negated_candidates: list[TaskCandidate] = Field(default_factory=list)
    merged_candidates: list[TaskCandidate]
    background_segments: list[str]
    constraint_segments: list[str]


class IntentExtractor:
    """Detects explicit action-object predicates instead of topic keyword mentions."""

    ACTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("compare", ("同比", "环比", "比较", "对比")),
        ("forecast", ("预测", "预估", "推演")),
        ("calculate", ("计算", "核算", "测算", "算出", "算一下")),
        ("analyze", ("分析", "归因", "诊断", "了解", "重点看", "看看")),
        ("generate", ("生成", "形成", "制作", "撰写", "写一份", "出一份")),
        ("parse", ("解析", "读取", "提取", "抽取")),
        ("filter", ("筛选", "过滤", "筛出", "找出")),
        ("sort", ("排序", "排名", "排行")),
        ("organize", ("整理", "归集", "汇总", "统计")),
        ("query", ("查询", "获取", "调取", "拉取", "查看", "列出")),
        ("audit", ("审核", "检查", "核查", "复核")),
        ("convert", ("转换", "转成", "做成")),
        ("export", ("导出",)),
        ("sync", ("同步", "推送", "回传", "提交")),
        ("monitor", ("提醒", "监控", "预警", "告警")),
        ("process", ("发起", "启动", "办理")),
    )
    MODAL_PATTERN = re.compile(r"请|需要|要求|希望|想要|务必|应当|应该|帮我|能否|可否|请把|请将")
    NEGATION_PATTERN = re.compile(r"不需要|无需|不用|不要|暂不|先不|无需再")
    PAST_PATTERN = re.compile(r"^(?:我|我们|团队)(?:已经|曾经|之前)?(?:整理了|发现|注意到|看到|收到|讨论了|准备了)")
    HISTORICAL_PATTERN = re.compile(
        r"^(?:此前|之前|历史上|历史|前期|过去|会上|会议中).{0,24}"
        r"(?:已经|曾经|已|形成|完成|留存|记录|讨论|安排|用于|只用于)"
    )
    BUSINESS_OBJECTS = (
        "销售数据", "销售表现", "销售情况", "销售奖励", "销售提成", "提成", "销售", "利润", "经营情况", "经营数据", "经营",
        "客户投诉", "客户信息", "客户", "库存", "订单", "回款", "费用", "收入", "成本", "合同", "发票", "审批记录", "员工",
    )

    def extract(self, segment: SemanticSegment, *, inherited_object: str = "") -> list[TaskCandidate]:
        candidates: list[TaskCandidate] = []
        for clause, clause_start in self._clauses(segment.text, segment.start):
            candidate = self._extract_clause(clause, clause_start, segment, inherited_object)
            if candidate is not None:
                candidates.append(candidate)
                if candidate.business_object:
                    inherited_object = candidate.business_object
        return candidates

    def _extract_clause(
        self,
        clause: str,
        clause_start: int,
        segment: SemanticSegment,
        inherited_object: str,
    ) -> TaskCandidate | None:
        if (
            self.NEGATION_PATTERN.search(clause)
            or self.PAST_PATTERN.search(clause)
            or self._input_uncertainty_or_option(clause)
            or (
                self.HISTORICAL_PATTERN.search(clause)
                and self.MODAL_PATTERN.search(clause) is None
            )
        ):
            return None

        modal_match = self.MODAL_PATTERN.search(clause)
        action_match = self._find_action(
            clause,
            preferred_start=modal_match.end() if modal_match is not None else None,
        )
        if action_match is None:
            return None
        action, phrase, action_start = action_match
        if phrase == "比较" and re.match(r"比较(?:全面|复杂|简单|准确|清楚|详细|完善|完整|明显|合理)", clause[action_start:]):
            return None
        explicit = modal_match is not None or self._predicate_position(clause, action_start)
        if not explicit:
            return None
        if modal_match is None and re.search(r"(?:启动|开展|推进|执行)(?:以来|之后|后)", clause):
            return None

        object_text = self._object_text(clause, action_start + len(phrase), action=action)
        business_object = self._business_object(clause) or inherited_object
        if action == "calculate" and re.search(r"(?:销售人员的)?提成|销售提成|佣金", clause):
            object_text = "销售提成"
            business_object = "销售提成"
        if action == "organize" and re.search(r"报告|材料|文档|PPT|汇报", object_text or clause):
            action = "generate"
        if not object_text and not business_object:
            return None
        if self._topic_only_statement(clause, action_start):
            return None

        normalized = self._normalize_action(action, object_text or business_object, clause, business_object)
        constraints = self._constraints(clause)
        confidence = 0.94 if self.MODAL_PATTERN.search(clause) else 0.87
        return TaskCandidate(
            source_text=clause,
            normalized_text=normalized,
            action=action,
            business_object=business_object,
            constraints=constraints,
            start=clause_start,
            end=clause_start + len(clause),
            confidence=confidence,
            source_kind=segment.kind,
            merged_sources=[clause],
        )

    def _find_action(self, text: str, *, preferred_start: int | None = None) -> tuple[str, str, int] | None:
        matches: list[tuple[int, int, str, str]] = []
        for priority, (action, phrases) in enumerate(self.ACTIONS):
            for phrase in phrases:
                index = text.find(phrase)
                if index >= 0:
                    matches.append((index, priority, action, phrase))
        if not matches:
            return None
        if preferred_start is not None:
            preferred = [match for match in matches if match[0] >= preferred_start]
            if preferred:
                matches = preferred
        index, _, action, phrase = min(matches)
        return action, phrase, index

    def _predicate_position(self, text: str, action_start: int) -> bool:
        prefix = text[:action_start].strip(" ，,：:")
        if len(prefix) <= 4:
            return True
        if re.match(r"^(?:根据|按照|基于|结合|使用|用).{0,24}$", prefix):
            return True
        if re.search(r"(?:设置|创建).{0,10}$", prefix):
            return True
        return bool(re.search(r"(?:并|然后|再|最后|另外|同时|后续|先|还要|领导希望|会上要求)$", prefix))

    def _object_text(self, text: str, start: int, *, action: str) -> str:
        value = text[start:].strip(" ，,：:的")
        value = re.sub(r"^(?:一下|相关|这些|这个|那个|重点)", "", value)
        value = value.strip(" ，,。；;！？!?")
        if re.fullmatch(r"(?:出来|一下|好|清楚|完成|出来即可|出来就可以)?", value):
            prefix = text[: start].strip(" ，,：:的")
            match = re.search(r"(?:把|将)(?P<object>[^，,。；;！？!?]{1,40})$", prefix)
            if match is not None:
                value = match.group("object").strip(" 的")
        if action == "calculate" and re.search(r"(?:销售人员的)?提成|销售提成|佣金", text):
            return "销售提成"
        return value

    def _business_object(self, text: str) -> str:
        if re.search(r"(?:销售人员的)?提成|销售提成|佣金", text):
            return "销售提成"
        matches = [(text.find(value), -len(value), value) for value in self.BUSINESS_OBJECTS if value in text]
        return min(matches)[2] if matches else ""

    def _input_uncertainty_or_option(self, text: str) -> bool:
        if re.search(
            r"(?:计算对象|计算范围|截止日期|截止时间|数据来源).{0,18}(?:没有明确|未明确|不明确|不确定|需要确认)",
            text,
        ):
            return True
        return bool(re.match(r"^(?:是|还是|或者|或)(?:只)?(?:计算|使用|采用)", text.strip()))

    def _topic_only_statement(self, text: str, action_start: int) -> bool:
        return action_start > 0 and bool(re.search(r"(?:已经|曾经|之前|目前已)", text[:action_start]))

    def _normalize_action(self, action: str, object_text: str, source: str, business_object: str) -> str:
        object_value = object_text
        if action == "calculate":
            object_value = object_value.replace("销售奖励", "销售奖金")
        if action == "query":
            system = next(
                (
                    value
                    for value in ("CRM", "ERP", "OA", "SAP", "财务系统", "业务系统", "金蝶", "用友")
                    if value.lower() in source.lower()
                ),
                "",
            )
            if system and system.lower() not in object_value.lower():
                object_value = f"从{system}获取{object_value}"
        if business_object and business_object not in object_value and object_value in {"原因", "下降原因", "趋势", "报告", "材料", "情况"}:
            object_value = f"{business_object}{object_value}"
        prefixes = {
            "query": "查询",
            "organize": "整理",
            "calculate": "计算",
            "analyze": "分析",
            "compare": "比较",
            "generate": "生成",
            "forecast": "预测",
            "audit": "检查",
            "convert": "转换",
            "export": "导出",
            "sync": "同步",
            "monitor": "监控",
            "parse": "解析",
            "filter": "筛选",
            "sort": "排序",
            "process": "发起",
        }
        if action == "compare" and "同比" in source:
            return f"同比分析{object_value}"
        if action == "compare" and "环比" in source:
            return f"环比分析{object_value}"
        if action == "organize":
            if "统计" in source:
                return f"统计{object_value}"
            if "汇总" in source:
                return f"汇总{object_value}"
        if action == "audit":
            return f"分析检查{object_value}问题"
        if action == "convert" and "凭证" in source:
            return f"生成{object_value}"
        if action == "sync":
            system = next(
                (value for value in ("CRM", "ERP", "OA", "SAP", "财务系统", "业务系统", "金蝶", "用友") if value in source),
                "",
            )
            if system:
                content = object_value.replace(f"到{system}", "").replace(f"至{system}", "")
                return f"同步到{system}{content}"
        if action == "monitor" and business_object and business_object not in object_value:
            return f"监控{business_object}{object_value}"
        if action == "parse":
            if "提取" in source:
                return f"提取{object_value}"
            if "读取" in source:
                return f"读取{object_value}"
        if action == "filter":
            return f"筛选{object_value}"
        if action == "sort":
            return f"排序{object_value}"
        if action == "process":
            if "办理" in source:
                return f"办理{object_value}"
            return f"发起{object_value}"
        return f"{prefixes[action]}{object_value}"

    def _constraints(self, text: str) -> list[str]:
        values: list[str] = []
        for pattern in (r"去年|今年|上个月|本月|第[一二三四1-4]季度|\d{4}年", r"各区域|华东区域|各部门|各产品|管理层|领导"):
            for match in re.finditer(pattern, text):
                if match.group(0) not in values:
                    values.append(match.group(0))
        return values

    def _clauses(self, text: str, base_start: int) -> list[tuple[str, int]]:
        clauses: list[tuple[str, int]] = []
        for match in re.finditer(r"[^，,。；;！？!?]+", text):
            value = match.group(0).strip()
            if value:
                offset = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
                clauses.append((value, base_start + offset))
        return clauses


class LongContextTaskExtractionLayer:
    def __init__(
        self,
        *,
        parser: LongTextParser | None = None,
        segmenter: TaskSegmenter | None = None,
        extractor: IntentExtractor | None = None,
        merger: object | None = None,
        negation_resolver: object | None = None,
        consolidator: object | None = None,
        activation_length: int = 120,
        activation_sentences: int = 3,
    ) -> None:
        self.parser = parser or LongTextParser()
        self.segmenter = segmenter or TaskSegmenter()
        self.extractor = extractor or IntentExtractor()
        if negation_resolver is None:
            from app.services.task_extraction.global_negation_resolver import GlobalNegationResolver

            negation_resolver = GlobalNegationResolver()
        self.negation_resolver = negation_resolver
        if consolidator is None:
            from app.services.task_extraction.task_consolidator import TaskConsolidator

            consolidator = TaskConsolidator()
        self.consolidator = consolidator
        if merger is None:
            from app.services.task_extraction.task_merger import TaskMerger

            merger = TaskMerger()
        self.merger = merger
        self.activation_length = activation_length
        self.activation_sentences = activation_sentences

    def should_extract(self, text: str) -> bool:
        sentence_count = len(re.findall(r"[。！？!?；;\n]", text))
        return len(text) >= self.activation_length or sentence_count >= self.activation_sentences

    def extract(self, text: str) -> LongContextExtractionResult:
        document = self.parser.parse(text)
        segments: list[SemanticSegment] = []
        candidates: list[TaskCandidate] = []
        inherited_object = ""
        for chunk in document.chunks:
            chunk_segments = self.segmenter.segment_chunk(chunk)
            segments.extend(chunk_segments)
            for segment in chunk_segments:
                extracted = self.extractor.extract(segment, inherited_object=inherited_object)
                candidates.extend(extracted)
                for candidate in extracted:
                    if candidate.business_object:
                        inherited_object = candidate.business_object

        negation_resolution = self.negation_resolver.resolve(candidates, original_text=text)
        consolidated = self.consolidator.consolidate(
            negation_resolution.active_candidates,
            original_text=text,
        )
        merged = self.merger.merge(consolidated, original_text=text)
        return LongContextExtractionResult(
            document=document,
            segments=segments,
            raw_candidates=candidates,
            negated_candidates=negation_resolution.removed_candidates,
            merged_candidates=merged,
            background_segments=[segment.text for segment in segments if segment.kind == "background"],
            constraint_segments=[segment.text for segment in segments if segment.kind == "constraint"],
        )
