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
        ("analyze", ("分析", "归因", "诊断", "判断", "评估", "了解", "重点看", "看看")),
        ("generate", ("生成", "形成", "制作", "撰写", "写一份", "出一份")),
        ("parse", ("解析", "读取", "提取", "抽取")),
        ("filter", ("筛选", "过滤", "筛出", "找出", "圈出来", "圈出", "挑出来", "单独圈")),
        ("sort", ("排序", "排名", "排行", "排列", "倒序", "升序", "降序", "从高到低", "从低到高", "风险高低", "排")),
        ("organize", ("整理", "归集", "汇总", "统计")),
        ("query", ("查询", "获取", "调取", "拉取", "查看", "列出", "拿出来", "拿出", "取出来", "取出", "调出来")),
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
        "复购率", "需求", "经销商", "客户投诉", "客户信息", "客户", "渠道线索", "渠道", "线索", "会员续约", "续约", "退款金额", "退款数据", "退款明细", "退款",
        "门店", "会员", "库存", "订单", "回款", "费用", "收入", "成本", "合同", "发票", "审批记录", "员工",
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
        diagnostic_candidate = self._diagnostic_change_candidate(
            clause,
            clause_start,
            segment,
            inherited_object,
        )
        if diagnostic_candidate is not None:
            return diagnostic_candidate

        if (
            self.NEGATION_PATTERN.search(clause)
            or self.PAST_PATTERN.search(clause)
            or self._input_uncertainty_or_option(clause)
            or self._contextual_instruction_clause(clause)
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

    def _diagnostic_change_candidate(
        self,
        clause: str,
        clause_start: int,
        segment: SemanticSegment,
        inherited_object: str,
    ) -> TaskCandidate | None:
        if self.NEGATION_PATTERN.search(clause):
            return None
        asks_reason = bool(re.search(r"为什么|为何|啥原因|什么原因|原因|归因|导致", clause))
        has_change = bool(re.search(r"下降|下滑|降低|减少|变少|走低|降(?:了)?|波动|异常|上升|增长|增加|变高", clause))
        if not (asks_reason and has_change):
            return None
        if re.search(r"报告|材料|文档|PPT|ppt|汇报", clause) and not re.search(r"分析|原因|归因", clause):
            return None
        business_object = self._business_object(clause) or inherited_object
        if not business_object and not re.search(r"率|额|量|数|指标|需求|收入|成本|费用|利润|订单|库存|回款", clause):
            return None
        if not business_object:
            business_object = "业务指标"
        normalized = clause
        normalized = re.sub(r"^.*?(?:为什么|为何)", "", normalized).strip(" ，,：:")
        normalized = re.sub(
            r"^(?:请|需要|希望|想要|帮我|麻烦|先|首先|随后|接着|然后|再|最后|同时|此外|另外)\s*",
            "",
            normalized,
        ).strip(" ，,：:")
        normalized = re.sub(r"[？?]$", "", normalized)
        if "原因" not in normalized:
            normalized = f"{normalized}原因"
        if not normalized.startswith("分析"):
            normalized = f"分析{normalized}"
        return TaskCandidate(
            source_text=clause,
            normalized_text=normalized,
            action="analyze",
            business_object=business_object,
            constraints=self._constraints(clause),
            start=clause_start,
            end=clause_start + len(clause),
            confidence=0.9 if segment.kind in {"goal", "action"} else 0.84,
            source_kind=segment.kind,
            merged_sources=[clause],
        )

    def _find_action(self, text: str, *, preferred_start: int | None = None) -> tuple[str, str, int] | None:
        matches: list[tuple[int, int, int, str, str]] = []
        for priority, (action, phrases) in enumerate(self.ACTIONS):
            for phrase in phrases:
                index = text.find(phrase)
                if index >= 0 and not self._nominal_action_mention(text, action, index, phrase):
                    matches.append((index, priority, -len(phrase), action, phrase))
        if not matches:
            return None
        if preferred_start is not None:
            preferred = [match for match in matches if match[0] >= preferred_start]
            if preferred:
                matches = preferred
        index, _, _, action, phrase = min(matches)
        return action, phrase, index

    def _predicate_position(self, text: str, action_start: int) -> bool:
        prefix = text[:action_start].strip(" ，,：:")
        if len(prefix) <= 4:
            return True
        if re.match(
            r"^(?:按|根据|按照|基于|结合|使用|用|从|通过|把|将|先|首先|随后|接着|然后|再|最后|同时|此外|另外|之后|在).{0,40}$",
            prefix,
        ):
            return True
        if re.search(r"(?:设置|创建).{0,10}$", prefix):
            return True
        return bool(re.search(r"(?:并|然后|再|最后|另外|同时|后续|先|还要|领导希望|会上要求)$", prefix))

    def _nominal_action_mention(self, text: str, action: str, index: int, phrase: str) -> bool:
        suffix = text[index + len(phrase) :].lstrip(" ，,：:")
        if action == "analyze" and re.match(
            r"(?:结果|需要|内容|方法|口径|范围|数据|情况|报告|任务|过程)",
            suffix,
        ):
            return True
        if action == "organize" and re.match(
            r"(?:之后|以后|后|时|中|方式|方法|结果|说明|口径)",
            suffix,
        ):
            return True
        if action == "sort" and phrase == "排":
            previous = text[index - 1] if index > 0 else ""
            if previous == "安" or suffix.startswith(("查", "除", "练")):
                return True
        return False

    def _contextual_instruction_clause(self, clause: str) -> bool:
        return bool(
            re.search(
                r"(?:汇总|统计|整理|计算|分析|处理|筛选|排序)"
                r"(?:时|之后|以后|过程中|中)"
                r"(?:说明|保留|标记|注明|采用|使用|确认|补充)",
                clause,
            )
            or re.search(
                r"(?:说明|保留|标记|注明|统一|记录).{0,24}"
                r"(?:方式|口径|范围|定义|字段|格式|来源|精度|状态|去重|异常)",
                clause,
            )
        )

    def _object_text(self, text: str, start: int, *, action: str) -> str:
        value = text[start:].strip(" ，,：:的")
        value = re.sub(r"^(?:一下|相关|这些|这个|那个|重点)", "", value)
        value = value.strip(" ，,。；;！？!?")
        if re.fullmatch(r"(?:出来|一下|好|清楚|完成|出来即可|出来就可以)?", value):
            prefix = text[: start].strip(" ，,：:的")
            match = re.search(r"(?:把|将)(?P<object>[^，,。；;！？!?]{1,40})$", prefix)
            if match is not None:
                value = match.group("object").strip(" 的")
        if action == "sort":
            sort_match = re.search(
                r"(?:按|按照|根据|以)(?P<object>[^，,。；;！？!?]{1,32}?)(?:倒序|升序|降序|从高到低|从低到高|排序|排名|排行|排列|排)$",
                text,
            )
            if sort_match is not None:
                value = sort_match.group("object").strip(" 的")
            elif re.fullmatch(r"(?:排序|排名|排行|排列|排|一下|一排|个序)?", value):
                value = ""
        if action == "filter":
            value = re.sub(r"(?:单独|重点)$", "", value).strip(" 的")
        if action == "calculate" and re.search(r"(?:销售人员的)?提成|销售提成|佣金", text):
            return "销售提成"
        return value

    def _business_object(self, text: str) -> str:
        if re.search(r"(?:销售人员的)?提成|销售提成|佣金", text):
            return "销售提成"
        if "桂中" in text and "需求" in text:
            return "桂中需求"
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
        object_value = re.sub(
            r"^(?:请|需要|希望|想要|帮我|麻烦|先|首先|随后|接着|然后|最后|同时|此外|另外|再)\s*",
            "",
            object_value,
        )
        action_prefixes = {
            "query": ("查询", "获取", "拉取", "调取"),
            "organize": ("整理", "归集", "汇总", "统计"),
            "calculate": ("计算", "核算", "测算"),
            "analyze": ("分析", "诊断"),
            "compare": ("比较", "对比"),
            "generate": ("生成", "制作", "撰写"),
            "forecast": ("预测", "预估"),
            "filter": ("筛选", "过滤"),
            "sort": ("排序", "排名", "排行"),
        }
        for prefix in action_prefixes.get(action, ()):
            if object_value.startswith(prefix):
                object_value = object_value[len(prefix) :].lstrip(" ，,：:")
                break
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
        if action == "compare" and re.search(r"去年同期|上年同期|去年同月|去年同季", source):
            return f"同比分析{object_value}"
        if action == "compare" and re.search(r"上季度|上月|上个月|上周|上期|上一周期", source):
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
        for pattern in (
            r"去年|今年|上个月|上月|本月|本季度|上季度|下季度|第[一二三四1-4]季度|\d{4}年|\d{1,2}月|[一二三四五六七八九十]+月",
            r"各区域|华东区域|华南区域|华北区域|西南区域|桂中|各部门|各产品|管理层|领导|前十名经销商|经销商",
        ):
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
        request_spans = self._explicit_user_request_spans(text)
        segments: list[SemanticSegment] = []
        candidates: list[TaskCandidate] = []
        inherited_object = ""
        extraction_units = self._extraction_chunks(text, document=document, request_spans=request_spans)
        for chunk in extraction_units:
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

    def _extraction_chunks(
        self,
        text: str,
        *,
        document: LongTextDocument,
        request_spans: list[tuple[str, int]],
    ) -> list[object]:
        if not request_spans:
            return list(document.chunks)

        chunks: list[object] = []
        next_chunk_index = 0
        for request_text, request_start in request_spans:
            request_document = self.parser.parse(request_text)
            for chunk in request_document.chunks:
                chunks.append(
                    chunk.model_copy(
                        update={
                            "chunk_index": next_chunk_index,
                            "start": chunk.start + request_start,
                            "end": chunk.end + request_start,
                            "units": [
                                unit.model_copy(
                                    update={
                                        "start": unit.start + request_start,
                                        "end": unit.end + request_start,
                                    }
                                )
                                for unit in chunk.units
                            ],
                        }
                    )
                )
                next_chunk_index += 1
        return chunks

    def _explicit_user_request_spans(self, text: str) -> list[tuple[str, int]]:
        spans: list[tuple[str, int]] = []
        patterns = (
            r"(?:[一-龥]{2,12})?(?:在[^，,。；;！？!?\n]{0,12})?(?:问一句|发问|提问|问|说|又说|接着说)\s*[：:]\s*(?P<request>[^。；;！？!?\n]{2,240}[？?]?)",
            r"(?:[一-龥]{2,12})?(?:问|发问|提问|说)[“\"'](?P<request>[^”\"'\n]{2,240})[”\"']",
            r"(?:用户|业务人员|使用者|提问者|客户|员工|同事|领导)?(?:又)?(?:问|说|输入|提出|要求|咨询)\s*[：:]\s*[“\"'](?P<request>[^”\"'\n]{2,240})[”\"']",
            r"(?:用户|业务人员|使用者|提问者|客户|员工|同事|领导)\s*[：:]\s*[“\"']?(?P<request>[^”\"'\n。；;]{2,240}[？?。!]?)",
        )
        seen_fingerprints: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                request = match.group("request").strip(" ，,。；;！？!?“”\"'")
                if not self._looks_like_user_request(request):
                    continue
                fingerprint = self._request_fingerprint(request)
                if any(fingerprint in seen or seen in fingerprint for seen in seen_fingerprints):
                    continue
                seen_fingerprints.add(fingerprint)
                start = match.start("request")
                item = (request, start)
                if item not in spans:
                    spans.append(item)
        return sorted(spans, key=lambda item: item[1])

    def _request_fingerprint(self, text: str) -> str:
        return re.sub(
            r"[\s，,。；;：:！？!?的了着一下请帮我为什么为何要]",
            "",
            text,
        )

    def _looks_like_user_request(self, text: str) -> bool:
        if re.search(r"系统|引擎|模块|权限|数据库表|接口|日志", text) and not re.search(r"请|帮我|为什么|预测|分析|查询|计算|生成", text):
            return False
        return bool(
            re.search(
                r"请|帮我|需要|要求|希望|想要|为什么|为何|分析|查询|获取|计算|核算|预测|预估|生成|整理|统计|汇总|筛选|排序|提取|解析|办理|发起",
                text,
            )
        )
