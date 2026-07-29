from __future__ import annotations

import re
from dataclasses import dataclass
import inspect
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.context_provider import BaseContextProvider, ContextInput, ContextProviderResponse
from app.services.conversation_understanding.context_extractor import ContextExtractor, ExtractedConversationContext
from app.services.conversation_understanding.noise_filter import NoiseFilter
from app.services.conversation_understanding.reference_resolver import ReferenceResolver
from app.services.conversation_understanding.state_store import ConversationStateStore
from app.services.intent_analysis_engine.llm import ImplicitTaskCandidate, ImplicitTaskExtractionOutcome
from app.services.task_extraction import FutureScopeFilter, LongContextExtractionResult, LongContextTaskExtractionLayer


class ConversationRequestSegment(BaseModel):
    text: str
    task_name: str | None = None
    depends_on_previous: bool = False
    evidence_span: str | None = None
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    selected_by: str | None = None
    source_start: int | None = Field(default=None, ge=0)


class StructuredConversationRequest(BaseModel):
    original_text: str
    normalized_text: str
    resolved_text: str
    filtered_text: str
    context: ExtractedConversationContext
    segments: list[ConversationRequestSegment] = Field(default_factory=list)
    removed_noise: list[str] = Field(default_factory=list)
    resolved_references: list[dict[str, str]] = Field(default_factory=list)
    history_texts: list[str] = Field(default_factory=list)


class NaturalLanguageNormalizer:
    """Normalizes a working copy of text without changing the original request."""

    REPLACEMENTS = (
        (r"看看有没有问题|看有没有问题", "检查分析"),
        (r"重点看|着重看", "重点分析"),
        (r"帮我瞅瞅|帮忙瞅瞅|瞅瞅", "查看"),
        (r"帮我看看|帮忙看看", "查看"),
        (r"看一看|看一下|看看", "分析"),
        (r"查一查|查一下", "查询"),
        (r"拉一下", "拉取"),
        (r"算一算|算一下", "计算"),
        (r"弄一份|搞一份|做一份", "生成一份"),
        (r"整理一下", "整理"),
        (r"捋一遍|捋一下", "汇总"),
        (r"排排", "排序"),
        (r"形成", "生成"),
        (r"筛出|挑出", "筛选"),
        (r"做成(?=凭证|报告|材料|文档)", "生成"),
        (r"月报", "月度报告"),
        (r"吱一声|说一声|通知一声", "提醒我"),
        (r"取出来", "获取"),
        (r"能不能帮我|可以帮我|请帮我|麻烦帮我", ""),
        (r"汇报PPT|汇报ppt|汇报幻灯片", "汇报材料"),
    )

    def normalize(self, text: str) -> str:
        normalized = text.strip()
        for pattern, replacement in self.REPLACEMENTS:
            normalized = re.sub(pattern, replacement, normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"查看(.+?)(?:咋样|怎么样)", r"分析\1情况", normalized)
        normalized = re.sub(r"(.+?政策).*(?:咋规定|怎么规定)", r"\1是什么", normalized)
        normalized = re.sub(r"[，,]{2,}", "，", normalized)
        return normalized.strip(" ，,。；;")


class ConversationParser:
    def __init__(
        self,
        *,
        noise_filter: NoiseFilter | None = None,
        reference_resolver: ReferenceResolver | None = None,
        context_extractor: ContextExtractor | None = None,
        normalizer: NaturalLanguageNormalizer | None = None,
        future_scope_filter: FutureScopeFilter | None = None,
    ) -> None:
        self.noise_filter = noise_filter or NoiseFilter()
        self.reference_resolver = reference_resolver or ReferenceResolver()
        self.context_extractor = context_extractor or ContextExtractor()
        self.normalizer = normalizer or NaturalLanguageNormalizer()
        self.future_scope_filter = future_scope_filter or FutureScopeFilter()

    def parse(self, text: str, *, history: list[Any] | None = None) -> StructuredConversationRequest:
        original_text = text.strip()
        history_texts = self._history_user_texts(history or [])
        resolution = self.reference_resolver.resolve(original_text, history)
        filtered = self.noise_filter.filter(resolution.resolved_text)
        normalized = self.normalizer.normalize(filtered.filtered_text)
        current_context = self.context_extractor.extract(
            resolution.resolved_text,
            context_information=filtered.removed_fragments,
        )
        context = self._merge_history_context(current_context, history or [])
        ambiguous = self._is_ambiguous_request(normalized, history_texts)
        future_scope_excluded = self.future_scope_filter.text_is_fully_excluded(normalized)
        segments = [] if ambiguous or future_scope_excluded else self._segments(normalized, context)
        return StructuredConversationRequest(
            original_text=original_text,
            normalized_text="，然后".join(segment.text for segment in segments) if segments else normalized,
            resolved_text=resolution.resolved_text,
            filtered_text=filtered.filtered_text,
            context=context,
            segments=(
                segments
                if ambiguous or future_scope_excluded
                else (segments or [ConversationRequestSegment(text=normalized or original_text)])
            ),
            removed_noise=filtered.removed_fragments,
            resolved_references=resolution.resolved_references,
            history_texts=history_texts,
        )

    def _merge_history_context(
        self,
        current: ExtractedConversationContext,
        history: list[Any],
    ) -> ExtractedConversationContext:
        history_texts = self._history_user_texts(history)
        if not history_texts:
            return current

        previous = self.context_extractor.extract("，".join(history_texts))
        return current.model_copy(
            update={
                "business_objects": self._merge_unique(current.business_objects, previous.business_objects),
                "constraints": self._merge_unique(current.constraints, previous.constraints),
                "time_ranges": self._merge_unique(current.time_ranges, previous.time_ranges),
                "people_organizations": self._merge_unique(current.people_organizations, previous.people_organizations),
                "data_scopes": self._merge_unique(current.data_scopes, previous.data_scopes),
                "summary_fields": self._merge_unique(current.summary_fields, previous.summary_fields),
                "data_sources": self._merge_unique(current.data_sources, previous.data_sources),
            }
        )

    def _history_user_texts(self, history: list[Any]) -> list[str]:
        history_texts: list[str] = []
        for item in history:
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if isinstance(item, str):
                history_texts.append(item)
            elif isinstance(item, dict) and str(item.get("role", "user")) in {"user", "human"}:
                value = item.get("text") or item.get("content") or item.get("message")
                if value:
                    history_texts.append(str(value))
        return history_texts

    def _merge_unique(self, current: list[str], previous: list[str]) -> list[str]:
        return current + [value for value in previous if value not in current]

    def _is_ambiguous_request(self, text: str, history_texts: list[str]) -> bool:
        if history_texts:
            return False
        normalized = text.strip(" ，,。；;！？!?")
        return bool(
            re.fullmatch(r"(?:随便)?(?:弄|处理|搞)(?:一下)?(?:这个|那个|奖金|结果)?", normalized)
            or re.fullmatch(r"(?:继续|接着)(?:上面的|刚才的|那个)?", normalized)
        )

    def _segments(
        self,
        text: str,
        context: ExtractedConversationContext,
    ) -> list[ConversationRequestSegment]:
        text = self.future_scope_filter.remove_excluded_future_scope(text)
        if not text:
            return []
        if self._use_existing_deterministic_decomposer(text):
            return [ConversationRequestSegment(text=text)]

        clauses = [
            clause.strip()
            for clause in re.split(r"(?:，|,|；|;|。|\b然后\b|然后|最后|接着|随后|并且|并|再(?=[分析查生成制作整理]))", text)
            if clause.strip()
        ]
        if clauses and clauses[0].startswith("查看") and "情况" in clauses[0] and any(
            "原因" in clause or "归因" in clause for clause in clauses[1:]
        ):
            clauses[0] = clauses[0].replace("查看", "查询", 1).replace("情况", "数据", 1)

        expanded_clauses: list[str] = []
        for clause in clauses:
            if "同比" in clause and "环比" in clause:
                expanded_clauses.extend(
                    [
                        clause.replace("和环比", "").replace("及环比", ""),
                        clause.replace("同比和", "").replace("同比及", ""),
                    ]
                )
            else:
                expanded_clauses.append(clause)
        clauses = expanded_clauses
        primary_object = self._primary_object(context)
        segments: list[ConversationRequestSegment] = []
        for clause in clauses:
            segment = self._clause_to_segment(clause, primary_object, context)
            if segment is None:
                continue
            if segments and segment.text == segments[-1].text:
                continue
            if segment.task_name and segment.task_name.endswith("趋势分析"):
                prior_index = next(
                    (index for index, item in enumerate(segments) if item.task_name == segment.task_name),
                    None,
                )
                if prior_index is not None:
                    segments[prior_index] = segment.model_copy(update={"depends_on_previous": prior_index > 0})
                    continue
            segments.append(segment.model_copy(update={"depends_on_previous": bool(segments)}))

        return segments

    def _clause_to_segment(
        self,
        clause: str,
        primary_object: str,
        context: ExtractedConversationContext,
    ) -> ConversationRequestSegment | None:
        clause = clause.strip(" ，,。；;？?")
        if not clause:
            return None

        if clause.startswith(("读取", "提取", "解析", "抽取")) and not re.search(
            r"Excel|excel|PDF|pdf|Word|word|附件|文件|表格",
            clause,
        ):
            document_source = next(
                (
                    value
                    for value in context.data_sources
                    if value in {"Excel", "excel", "PDF", "pdf", "Word", "word", "附件", "文件"}
                ),
                None,
            )
            if document_source:
                clause = f"{clause}{document_source}"

        has_task_action = bool(
            re.search(
                r"查询|获取|拉取|导出|列出|找出|整理|汇总|求和|统计|计算|核算|测算|分析|查看|检查|诊断|原因|生成|制作|写|起草|输出|形成|提醒|监控|预警|告警|设置|了解|筛选|筛出|挑出|过滤|排序|排名|比较|预测|预估|解析|读取|提取|抽取|发起|提交|推送|回传|创建|办理|走|做|制定",
                clause,
            )
        )
        if not has_task_action:
            return None

        if re.search(r"整理成.*(?:结构化|清单|列表)$", clause):
            return None

        if re.search(r"政策|制度|规则|标准", clause) and re.search(r"了解|查询|问|什么|怎么|如何", clause):
            knowledge_text = re.sub(r"^(?:麻烦)?了解", "", clause)
            if not re.search(r"什么|怎么|如何|为什么", knowledge_text):
                knowledge_text = f"{knowledge_text}是什么"
            return ConversationRequestSegment(text=knowledge_text, task_name="智能问答")

        if clause.startswith("查看") and "情况" not in clause:
            return ConversationRequestSegment(
                text=self._augment_context(clause.replace("查看", "查询", 1), primary_object, context),
                task_name=f"获取{primary_object or '业务'}数据",
            )

        if re.search(r"整理(?:出来)?|查询|获取|拉取|导出|列出", clause) and not re.search(r"原因|汇报|报告|材料|PPT|分析", clause):
            if re.search(r"查询|获取|拉取|导出|列出", clause):
                text = clause
                task_name = f"获取{primary_object or '业务'}数据"
            else:
                text = re.sub(r"^.*?(?=去年|今年|上个月|上月|本月|销售|经营|客户|库存|订单)", "整理", clause)
                if not text.startswith("整理"):
                    text = f"整理{text}"
                task_name = f"整理{primary_object or '业务'}数据"
            text = self._augment_context(text, primary_object, context)
            return ConversationRequestSegment(text=text, task_name=task_name)

        if re.search(r"找出|筛选|过滤", clause) and re.search(r"低于|高于|超过|逾期|异常|风险|未", clause):
            text = clause.replace("找出", "筛选")
            if "筛选" in text and not text.startswith("筛选"):
                text = "筛选" + re.sub(r"^(?:把)?", "", text).replace("筛选", "")
            text = re.sub(r"(?:低于|少于).{0,6}?(?:的)?", "低库存", text)
            text = re.sub(r"(?:高于|超过).{0,6}?(?:的)?", "高值", text)
            return ConversationRequestSegment(
                text=self._augment_context(text, primary_object, context),
                task_name="数据筛选",
            )

        if "原因" in clause or "归因" in clause:
            text = self._with_context(clause if "分析" in clause else f"分析{clause}", primary_object, context)
            return ConversationRequestSegment(text=text, task_name=f"{primary_object or '业务'}下降原因分析")

        if re.search(r"汇报|报告|材料|PPT|文档|通知|邮件|方案|计划|建议", clause) and re.search(r"生成|制作|写|起草|输出|整理|形成|制定", clause):
            topic = primary_object or "业务"
            if re.search(r"方案|计划|建议", clause):
                content_type = "改进方案" if "方案" in clause else "计划"
                normalized_topic = "投诉" if topic == "客户投诉" else topic
                return ConversationRequestSegment(
                    text=f"生成{normalized_topic}{content_type}",
                    task_name="生成方案",
                )
            if re.search(r"通知|邮件", clause):
                content_type = "通知" if "通知" in clause else "邮件"
                return ConversationRequestSegment(
                    text=f"生成{topic}{content_type}",
                    task_name=f"生成{content_type}",
                )
            report_match = re.search(r"(?:生成|制作|撰写|输出|整理)([^，。；;！？!?]{0,24}报告)", clause)
            if report_match is not None:
                report_object = report_match.group(1).strip() or "报告"
                return ConversationRequestSegment(
                    text=f"生成{report_object}",
                    task_name=f"生成{report_object}",
                )

            text = f"生成{topic}分析汇报材料"
            if "受众:领导" in context.constraints:
                text += "，给领导看"
            return ConversationRequestSegment(text=text, task_name="生成汇报材料")

        if re.search(r"下降|下滑|波动|趋势|异常|问题|分析|检查|了解|查看", clause):
            text = self._with_context(clause, primary_object, context)
            text = re.sub(r"^(?:麻烦)?(?:查看|了解)(?:一下)?", "分析", text)
            if not re.search(r"分析|检查|诊断|预测|同比|环比|查看|了解", text):
                text = f"分析{text}"
            if "同比" in text:
                task_name = f"{primary_object or '业务'}同比分析"
            elif "环比" in text:
                task_name = f"{primary_object or '业务'}环比分析"
            else:
                task_name = f"{primary_object or '业务'}趋势分析"
            return ConversationRequestSegment(text=text, task_name=task_name)

        if "找出" in clause and re.search(r"低于|高于|超过|逾期|异常|风险|未", clause):
            clause = clause.replace("找出", "筛选")
        if "筛选" in clause and not clause.startswith("筛选"):
            clause = "筛选" + re.sub(r"^(?:把)?", "", clause).replace("筛选", "")
        if clause.startswith(("筛选", "过滤")):
            clause = re.sub(r"(?:低于|少于).{0,6}?(?:的)?", "低库存", clause)
            clause = re.sub(r"(?:高于|超过).{0,6}?(?:的)?", "高值", clause)
        return ConversationRequestSegment(text=self._augment_context(clause, primary_object, context))

    def _use_existing_deterministic_decomposer(self, text: str) -> bool:
        complaint_plan = (
            "客户投诉" in text
            and "改进方案" in text
            and not any(value in text for value in ("邮件", "通知", "报告", "材料", "海报"))
        )
        commission_voucher = (
            "销售" in text
            and any(value in text for value in ("提成", "佣金"))
            and "凭证" in text
            and any(value in text for value in ("整理", "获取", "查询", "拉取", "明细", "数据", "计算", "核算", "测算", "计提"))
        )
        return complaint_plan or commission_voucher

    def _augment_context(
        self,
        clause: str,
        primary_object: str,
        context: ExtractedConversationContext,
    ) -> str:
        text = clause
        object_markers = ("销售", "经营", "客户", "库存", "订单", "利润", "收入", "成本", "费用", "回款", "投诉", "提成", "奖金")
        if primary_object and primary_object not in text and not any(value in text for value in object_markers):
            text = f"{text}{primary_object}"
        if not any(value in text for value in context.time_ranges):
            for value in context.time_ranges:
                text = f"{value}{text}"
                break
        if not any(value in text for value in context.data_scopes):
            for value in context.data_scopes:
                text = f"{value}{text}"
                break
        return text

    def _with_context(self, clause: str, primary_object: str, context: ExtractedConversationContext) -> str:
        text = clause
        if primary_object and primary_object not in text:
            text = f"{text}{primary_object}"
        for value in context.time_ranges:
            if value not in text:
                text = f"{value}{text}"
                break
        for value in context.data_scopes:
            if value not in text:
                text = f"{value}{text}"
                break
        return text

    def _primary_object(self, context: ExtractedConversationContext) -> str:
        for value in context.business_objects:
            if value in {"销售数据", "销售情况"}:
                return "销售"
            if value in {"销售额", "销量"}:
                return "销售"
            if value in {"经营数据", "经营情况"}:
                return "经营"
            if value in {"利润情况"}:
                return "利润"
            return value
        return ""


@dataclass(frozen=True)
class ConversationAnalysisWithDebug:
    result: Any
    debug: dict[str, Any]


class ConversationUnderstandingLayer:
    """Conversation-aware entry layer that delegates every task to the existing analyzer."""

    def __init__(
        self,
        intent_analyzer: Any,
        parser: ConversationParser | None = None,
        state_store: ConversationStateStore | None = None,
        history_limit: int = 20,
        task_extraction_layer: LongContextTaskExtractionLayer | None = None,
        implicit_fallback_batch_characters: int = 8000,
        context_provider: BaseContextProvider | None = None,
    ) -> None:
        self.intent_analyzer = intent_analyzer
        self.parser = parser or ConversationParser()
        self.state_store = state_store
        self.history_limit = history_limit
        self.task_extraction_layer = task_extraction_layer or LongContextTaskExtractionLayer()
        self.implicit_fallback_batch_characters = max(1000, implicit_fallback_batch_characters)
        self.context_provider = context_provider

    def analyze(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
        project_id: str | None = None,
        history: list[Any] | None = None,
    ) -> Any:
        return self.analyze_with_debug(
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
            project_id=project_id,
            history=history,
        ).result

    def analyze_with_debug(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
        project_id: str | None = None,
        history: list[Any] | None = None,
    ) -> ConversationAnalysisWithDebug:
        stored_history, load_error = self._load_stored_history(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        combined_history = self._merge_histories(stored_history, history or [])
        provider_context, context_error = self._load_external_context(
            user_id=user_id,
            conversation_id=conversation_id,
            project_id=project_id,
        )
        context_input = ContextInput.from_provider_response(provider_context)
        enhanced_text, context_resolution = self._resolve_omitted_expression(text, context_input)
        if context_resolution["requires_context"] and not context_resolution["resolved"]:
            result = IntentAnalysisResult(
                original_text=text,
                intent_category="待澄清",
                tasks=[],
                clarification_required=True,
                clarification_questions=["请明确要继续处理的上一轮任务或业务对象。"],
                analysis_level=1,
                overall_confidence=0,
            )
            debug = {
                "conversation_understanding": None,
                "segment_analyses": [],
                "conversation_state": {
                    "enabled": self.state_store is not None,
                    "stored_history_count": len(stored_history),
                    "explicit_history_count": len(history or []),
                    "combined_history_count": len(combined_history),
                    "history_limit": self.history_limit,
                    "load_error": load_error,
                    "save_error": None,
                },
                "external_context": self._external_context_debug(
                    provider_context=provider_context,
                    project_id=project_id,
                    error=context_error,
                ),
                "context_resolution": context_resolution,
                "contextual_input": {
                    "user_input": text,
                    "context": context_input.model_dump(mode="json"),
                },
                "long_context_extraction": None,
                "implicit_task_fallback": None,
                "final_tasklist": result.model_dump(mode="json"),
            }
            return ConversationAnalysisWithDebug(result=result, debug=debug)

        parsed = self.parser.parse(enhanced_text, history=combined_history)
        long_context_result: LongContextExtractionResult | None = None
        implicit_fallback_debug: dict[str, Any] | None = None
        if self.task_extraction_layer.should_extract(text):
            long_context_result = self.task_extraction_layer.extract(text)
            candidate_segments = [
                ConversationRequestSegment(
                    text=candidate.normalized_text,
                    task_name=candidate.normalized_text,
                    depends_on_previous=candidate.depends_on_previous,
                    evidence_span=candidate.source_text,
                    extraction_confidence=candidate.confidence,
                    selected_by="deterministic_extractor",
                    source_start=candidate.start,
                )
                for candidate in long_context_result.merged_candidates
            ]
            unresolved_fragments = self._uncovered_implicit_fragments(long_context_result)
            implicit_candidates, implicit_fallback_debug = self._run_implicit_task_fallback(
                long_context_result,
                unresolved_fragments,
            )
            candidate_segments.extend(
                [
                    ConversationRequestSegment(
                        text=candidate.normalized_text,
                        depends_on_previous=candidate.depends_on_previous,
                        evidence_span=candidate.evidence_span,
                        extraction_confidence=candidate.confidence,
                        selected_by="llm_implicit_fallback",
                        source_start=text.find(candidate.evidence_span),
                    )
                    for candidate in implicit_candidates
                ]
            )
            candidate_segments = self._deduplicate_request_segments(candidate_segments)
            candidate_segments.sort(
                key=lambda segment: segment.source_start if segment.source_start is not None else len(text)
            )
            parsed = parsed.model_copy(
                update={
                    "normalized_text": "，然后".join(segment.text for segment in candidate_segments),
                    "segments": candidate_segments,
                }
            )
        analyses = [
            self._analyze_segment(
                text=segment.text,
                user_id=user_id,
                conversation_id=conversation_id,
                context=context_input,
            )
            for segment in parsed.segments
        ]
        analyses = [
            self._enrich_and_revalidate(analysis, parsed, segment)
            for analysis, segment in zip(analyses, parsed.segments, strict=True)
        ]

        result = self._merge_results(parsed, analyses) if analyses else IntentAnalysisResult(
            original_text=parsed.original_text,
            intent_category="待澄清",
            tasks=[],
            clarification_required=True,
            clarification_questions=["请明确需要处理的业务对象和具体动作。"],
            analysis_level=1,
            overall_confidence=0,
        )
        if isinstance(result, IntentAnalysisResult) and not result.tasks:
            result = result.model_copy(
                update={
                    "clarification_required": True,
                    "clarification_questions": ["请明确需要处理的业务对象和具体动作。"],
                }
            )
        save_error = self._save_turn(
            conversation_id=conversation_id,
            user_id=user_id,
            text=text,
            result=result,
        )
        debug = {
            "conversation_understanding": parsed.model_dump(mode="json"),
            "segment_analyses": [
                {
                    "segment": segment.model_dump(mode="json"),
                    "debug": getattr(analysis, "debug", None),
                }
                for segment, analysis in zip(parsed.segments, analyses, strict=True)
            ],
            "conversation_state": {
                "enabled": self.state_store is not None,
                "stored_history_count": len(stored_history),
                "explicit_history_count": len(history or []),
                "combined_history_count": len(combined_history),
                "history_limit": self.history_limit,
                "load_error": load_error,
                "save_error": save_error,
            },
            "long_context_extraction": (
                long_context_result.model_dump(mode="json")
                if long_context_result is not None
                else None
            ),
            "implicit_task_fallback": implicit_fallback_debug,
        }
        if len(analyses) == 1 and getattr(analyses[0], "debug", None):
            debug.update(analyses[0].debug)
            debug["conversation_understanding"] = parsed.model_dump(mode="json")
            debug["segment_analyses"] = [
                {
                    "segment": parsed.segments[0].model_dump(mode="json"),
                    "debug": analyses[0].debug,
                },
            ]
        debug["external_context"] = self._external_context_debug(
            provider_context=provider_context,
            project_id=project_id,
            error=context_error,
        )
        debug["context_resolution"] = context_resolution
        debug["contextual_input"] = {
            "user_input": enhanced_text,
            "context": context_input.model_dump(mode="json"),
        }
        debug["final_tasklist"] = (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump") and hasattr(result, "tasks")
            else None
        )
        return ConversationAnalysisWithDebug(result=result, debug=debug)

    def _run_implicit_task_fallback(
        self,
        extraction: LongContextExtractionResult,
        fragments: list[str],
    ) -> tuple[list[ImplicitTaskCandidate], dict[str, Any]]:
        if not fragments:
            return [], {
                "attempted": False,
                "accepted_candidates": [],
                "rejection_reasons": ["no_uncovered_segments"],
            }
        llm_analyzer = getattr(self.intent_analyzer, "llm_analyzer", None)
        extractor = getattr(llm_analyzer, "extract_implicit_candidates", None)
        if not callable(extractor):
            return [], {
                "attempted": False,
                "accepted_candidates": [],
                "rejection_reasons": ["implicit_task_extractor_not_configured"],
            }

        batches = self._implicit_fallback_batches(fragments)
        candidates: list[ImplicitTaskCandidate] = []
        batch_debug: list[dict[str, Any]] = []
        rejection_reasons: list[str] = []
        unsupported_reasons: list[str] = []
        for batch_index, batch_text in enumerate(batches):
            try:
                outcome = extractor(batch_text)
            except Exception as error:
                outcome = ImplicitTaskExtractionOutcome(
                    rejection_reasons=[f"model_error:{type(error).__name__}"],
                    reason="implicit_task_model_unavailable",
                )
            candidates.extend(outcome.candidates)
            rejection_reasons.extend(outcome.rejection_reasons)
            if outcome.unsupported and outcome.reason:
                unsupported_reasons.append(outcome.reason)
            batch_debug.append(
                {
                    "batch_index": batch_index,
                    "character_count": len(batch_text),
                    "accepted_count": len(outcome.candidates),
                    "unsupported": outcome.unsupported,
                    "reason": outcome.reason,
                    "rejection_reasons": outcome.rejection_reasons,
                }
            )

        source_text = extraction.document.original_text
        ordered = sorted(
            self._deduplicate_implicit_candidates(candidates),
            key=lambda candidate: source_text.find(candidate.evidence_span),
        )
        return ordered, {
            "attempted": True,
            "batch_count": len(batches),
            "batches": batch_debug,
            "accepted_candidates": [candidate.model_dump(mode="json") for candidate in ordered],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "unsupported_reasons": list(dict.fromkeys(unsupported_reasons)),
        }

    def _uncovered_implicit_fragments(
        self,
        extraction: LongContextExtractionResult,
    ) -> list[str]:
        covered = [(candidate.start, candidate.end) for candidate in extraction.raw_candidates]
        uncovered: list[tuple[int, int]] = []
        seen: set[tuple[int, int, str]] = set()
        for segment in sorted(extraction.segments, key=lambda item: (item.start, item.end)):
            fingerprint = (segment.start, segment.end, segment.text)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            if any(segment.start < end and segment.end > start for start, end in covered):
                continue
            uncovered.append((segment.start, segment.end))

        source_text = extraction.document.original_text
        grouped: list[tuple[int, int]] = []
        for start, end in uncovered:
            if not grouped:
                grouped.append((start, end))
                continue
            previous_start, previous_end = grouped[-1]
            gap = source_text[previous_end:start]
            if re.fullmatch(r"[\s，,。；;！？!?：:]*", gap):
                grouped[-1] = (previous_start, end)
            else:
                grouped.append((start, end))
        return [source_text[start:end] for start, end in grouped if source_text[start:end].strip()]

    def _implicit_fallback_batches(self, fragments: list[str]) -> list[str]:
        batches: list[str] = []
        current = ""
        for fragment in fragments:
            separator = "\n" if current else ""
            if current and len(current) + len(separator) + len(fragment) > self.implicit_fallback_batch_characters:
                batches.append(current)
                current = ""
                separator = ""
            if fragment not in current:
                current += separator + fragment
        if current:
            batches.append(current)
        return batches

    def _deduplicate_request_segments(
        self,
        segments: list[ConversationRequestSegment],
    ) -> list[ConversationRequestSegment]:
        unique: list[ConversationRequestSegment] = []
        fingerprints: set[tuple[str, str | None]] = set()
        for segment in segments:
            fingerprint = (re.sub(r"\s+", "", segment.text), segment.evidence_span)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(segment)
        return unique

    def _deduplicate_implicit_candidates(
        self,
        candidates: list[ImplicitTaskCandidate],
    ) -> list[ImplicitTaskCandidate]:
        unique: list[ImplicitTaskCandidate] = []
        fingerprints: set[tuple[str, str]] = set()
        for candidate in candidates:
            fingerprint = (re.sub(r"\s+", "", candidate.normalized_text), candidate.evidence_span)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(candidate)
        return unique

    def _load_stored_history(
        self,
        *,
        conversation_id: str,
        user_id: str,
    ) -> tuple[list[Any], str | None]:
        if self.state_store is None:
            return [], None
        try:
            return (
                self.state_store.load_history(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    limit=self.history_limit,
                ),
                None,
            )
        except Exception as error:
            return [], str(error)

    def _load_external_context(
        self,
        *,
        user_id: str,
        conversation_id: str,
        project_id: str | None,
    ) -> tuple[ContextProviderResponse, str | None]:
        if self.context_provider is None:
            return ContextProviderResponse(), None
        try:
            return (
                self.context_provider.get_context(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    project_id=project_id,
                ),
                None,
            )
        except Exception as error:
            return ContextProviderResponse(), str(error)

    def _external_context_debug(
        self,
        *,
        provider_context: ContextProviderResponse,
        project_id: str | None,
        error: str | None,
    ) -> dict[str, Any]:
        return {
            "enabled": self.context_provider is not None,
            "project_id": project_id,
            "error": error,
            "context": provider_context.model_dump(mode="json"),
        }

    def _resolve_omitted_expression(
        self,
        text: str,
        context: ContextInput,
    ) -> tuple[str, dict[str, Any]]:
        family = self._omitted_family(text)
        debug: dict[str, Any] = {
            "original_text": text,
            "resolved_text": text,
            "requires_context": family is not None,
            "resolved": False,
            "family": family,
            "scope": None,
            "context_item": None,
        }
        if family is None:
            return text, debug

        match = self._context_item_for_family(context, family)
        if match is None:
            return text, debug

        scope, item = match
        resolved = self._resolved_text_for_family(text, family, item)
        debug.update(
            {
                "resolved_text": resolved,
                "resolved": resolved != text,
                "scope": scope,
                "context_item": item,
            }
        )
        return resolved, debug

    def _omitted_family(self, text: str) -> str | None:
        normalized = text.strip(" ，,。；;！？!?")
        if re.fullmatch(r"(?:帮我)?(?:再|重新)?(?:算|计算|核算|测算)(?:一遍|一下)?", normalized):
            return "calculate"
        if re.fullmatch(r"(?:接着|继续|再)?(?:改|修改|调整)(?:一下|一版)?", normalized):
            return "report"
        if re.fullmatch(r"(?:换个|换一个|再换个).{0,4}维度(?:看看|看一下|分析)?", normalized):
            return "analysis"
        return None

    def _context_item_for_family(
        self,
        context: ContextInput,
        family: str,
    ) -> tuple[str, dict[str, Any]] | None:
        scopes = (
            ("conversation", context.current_conversation),
            ("project", context.current_project),
            ("historical_projects", context.historical_projects),
        )
        for scope_name, scope in scopes:
            items = scope.get("items")
            if not isinstance(items, list):
                continue
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                task = self._task_like_item(item)
                if task is not None and self._item_matches_family(task, family):
                    return scope_name, task
        return None

    def _task_like_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        if any(key in item for key in ("task_type", "task_description", "task_name", "action", "object")):
            return item
        tasks = item.get("tasks")
        if isinstance(tasks, list):
            for task in reversed(tasks):
                if isinstance(task, dict):
                    return task
        result = item.get("result")
        if isinstance(result, dict):
            return self._task_like_item(result)
        return None

    def _item_matches_family(self, item: dict[str, Any], family: str) -> bool:
        text = self._context_item_text(item)
        task_type = str(item.get("task_type") or "")
        if family == "calculate":
            return (
                "CALCULATION" in task_type
                or "计算" in text
                or "核算" in text
                or "提成" in text
                or "佣金" in text
            )
        if family == "report":
            return (
                task_type in {"DOCUMENT_GENERATE", "CONTENT_GENERATE", "IMPROVEMENT_PLAN_GENERATE"}
                or "报告" in text
                or "材料" in text
                or "文档" in text
                or "PPT" in text
            )
        if family == "analysis":
            return "ANALYSIS" in task_type or "分析" in text or "趋势" in text or "维度" in text
        return False

    def _resolved_text_for_family(self, original: str, family: str, item: dict[str, Any]) -> str:
        subject = self._context_item_subject(item)
        if family == "calculate":
            if subject.startswith(("计算", "核算", "测算")):
                return f"重新{subject}"
            return f"重新计算{subject}"
        if family == "report":
            subject = re.sub(r"^(?:生成|制作|撰写|写|输出)", "", subject).strip() or subject
            return f"生成{subject}修改稿"
        if family == "analysis":
            subject = re.sub(r"^(?:分析|查看|检查|诊断|了解)", "", subject).strip() or subject
            return f"换个维度分析{subject}"
        return original

    def _context_item_subject(self, item: dict[str, Any]) -> str:
        for key in ("source_text", "normalized_text", "task_description", "task_name", "text", "content"):
            value = item.get(key)
            if value:
                return str(value)
        action = str(item.get("action") or "")
        business_object = str(item.get("object") or item.get("business_object") or "")
        if action or business_object:
            return f"{action}{business_object}".strip()
        return self._context_item_text(item) or "上一轮任务"

    def _context_item_text(self, item: dict[str, Any]) -> str:
        values: list[str] = []
        for key in (
            "task_type",
            "task_description",
            "task_name",
            "source_text",
            "normalized_text",
            "action",
            "object",
            "business_object",
            "text",
            "content",
        ):
            value = item.get(key)
            if value:
                values.append(str(value))
        return "，".join(values)

    def _merge_histories(self, stored: list[Any], explicit: list[Any]) -> list[Any]:
        merged: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for item in [*stored, *explicit]:
            if hasattr(item, "model_dump"):
                payload = item.model_dump()
            elif isinstance(item, str):
                payload = {"role": "user", "text": item}
            elif isinstance(item, dict):
                payload = item
            else:
                continue
            role = str(payload.get("role", "user"))
            value = payload.get("text") or payload.get("content") or payload.get("message")
            if not value:
                continue
            key = (role, str(value).strip())
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged[-self.history_limit :]

    def _save_turn(
        self,
        *,
        conversation_id: str,
        user_id: str,
        text: str,
        result: Any,
    ) -> str | None:
        if self.state_store is None:
            return None
        try:
            self.state_store.append_turn(
                conversation_id=conversation_id,
                user_id=user_id,
                text=text,
                analysis_result=result.model_dump(mode="json") if hasattr(result, "model_dump") else None,
            )
            return None
        except Exception as error:
            return str(error)

    def _analyze_segment(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
        context: ContextInput,
    ) -> Any:
        if hasattr(self.intent_analyzer, "analyze_with_debug"):
            analyze_with_debug = self.intent_analyzer.analyze_with_debug
            kwargs = {
                "text": text,
                "user_id": user_id,
                "conversation_id": conversation_id,
            }
            if self._supports_parameter(analyze_with_debug, "context"):
                kwargs["context"] = context
            return analyze_with_debug(**kwargs)

        analyze = self.intent_analyzer.analyze
        kwargs = {
            "text": text,
            "user_id": user_id,
            "conversation_id": conversation_id,
        }
        if self._supports_parameter(analyze, "context"):
            kwargs["context"] = context
        result = analyze(**kwargs)
        return _BasicAnalysis(result=result, debug={})

    def _supports_parameter(self, func: Any, parameter: str) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return False
        return parameter in signature.parameters or any(
            item.kind == inspect.Parameter.VAR_KEYWORD
            for item in signature.parameters.values()
        )

    def _enrich_and_revalidate(
        self,
        analysis: Any,
        parsed: StructuredConversationRequest,
        segment: ConversationRequestSegment,
    ) -> Any:
        result = analysis.result
        validator = getattr(self.intent_analyzer, "input_validator", None)
        if not isinstance(result, IntentAnalysisResult) or validator is None:
            return analysis

        explicit_inputs = self._explicit_inputs(parsed, segment.text)
        user_explicit_text = "，".join([*parsed.history_texts, parsed.resolved_text])
        enriched_tasks = []
        for task in result.tasks:
            required_keys = set(validator.required_inputs_for_task(task.task_type))
            retained_inputs = [
                value
                for value in task.required_inputs
                if self._input_is_user_supported(value, user_explicit_text)
            ]
            additions = [
                value
                for key, value in explicit_inputs.items()
                if key in required_keys and not self._has_input(retained_inputs, key)
            ]
            enriched_tasks.append(
                task.model_copy(update={"required_inputs": [*retained_inputs, *additions]})
            )

        enriched = result.model_copy(update={"tasks": enriched_tasks})
        validated, validation_result = validator.apply(enriched, source_text=user_explicit_text)
        debug = dict(getattr(analysis, "debug", {}) or {})
        debug["conversation_explicit_inputs"] = list(explicit_inputs.values())
        debug["input_validation_result"] = validation_result.model_dump(mode="json")
        return _BasicAnalysis(result=validated, debug=debug)

    def _explicit_inputs(
        self,
        parsed: StructuredConversationRequest,
        segment_text: str,
    ) -> dict[str, str]:
        context = parsed.context
        full_text = "，".join([*parsed.history_texts, parsed.resolved_text])
        values: dict[str, str] = {}
        primary_object = self.parser._primary_object(context)
        if primary_object:
            values["analysis_object"] = f"analysis_object:{primary_object}"
            values["topic"] = f"topic:{primary_object}"
            values["data_object"] = f"data_object:{primary_object}"
            if any(marker in full_text for marker in ("数据", "明细", "记录", "列表", "报表")):
                values["data_source"] = f"data_object:{primary_object}"
        if any(marker in full_text for marker in ("销售数据", "销售明细", "销售报表")):
            values["sales_data_source"] = "sales_data_source:销售数据"

        if context.time_ranges:
            values["statistical_range"] = f"statistical_range:{context.time_ranges[0]}"
        if context.data_scopes:
            values["classification_field"] = f"classification_field:{context.data_scopes[0]}"

        if context.summary_fields:
            values["summary_field"] = f"summary_field:{context.summary_fields[0]}"

        if any(marker in full_text for marker in ("政策", "规则", "公式")):
            values["calculation_policy"] = "calculation_policy:用户已提供"
        if any(marker in full_text for marker in ("数据", "明细", "报表", "核算依据")):
            values["calculation_basis"] = "calculation_basis:用户已提供"
        file_is_negated = bool(re.search(r"(?:没有|未提供|不确定有没有|没给|缺少).{0,4}(?:附件|文件|表格)", full_text))
        if not file_is_negated and any(marker in full_text for marker in ("附件", "文件", "Excel", "excel", "PDF", "pdf", "Word", "word", "表格")):
            values["file"] = "file:用户已提供"
        if any(marker in segment_text for marker in ("报告", "材料", "文档", "PPT", "通知", "邮件", "方案", "计划")):
            values["content_type"] = "content_type:用户已提供"
        if "会议" in full_text and "topic" not in values:
            values["topic"] = "topic:会议"
        if "报销" in full_text and "topic" not in values:
            values["topic"] = "topic:报销"
        if any(marker in full_text for marker in ("结果", "结论", "核算结果", "计算结果")):
            values["source_result"] = "source_result:用户已提供"
        if re.search(r"(?:超过|低于|少于|高于|大于|小于).{0,10}(?:\d+|阈值|目标|预算|安全值|账期)", full_text) or any(
            marker in full_text for marker in ("每天", "每周", "每月", "到期", "逾期")
        ):
            values["trigger_condition"] = "trigger_condition:用户已提供"
        for system in ("CRM", "ERP", "OA", "SAP", "财务系统", "业务系统", "金蝶", "用友"):
            if system.lower() in full_text.lower():
                values["external_system"] = f"external_system:{system}"
                break
        if any(marker in full_text for marker in ("查询", "获取", "拉取", "调出来", "读取")):
            values["operation"] = "operation:fetch"
        elif any(marker in full_text for marker in ("提交", "推送", "回传", "写入", "更新", "同步")):
            values["operation"] = "operation:submit"
        for media_type in ("海报", "图片", "视频", "音频", "封面"):
            if media_type in full_text:
                values["media_type"] = f"media_type:{media_type}"
                break
        for topic in ("新品", "产品", "活动", "品牌", "宣传"):
            if topic in full_text:
                values["topic"] = f"topic:{topic}"
                break
        return values

    def _has_input(self, inputs: list[str], key: str) -> bool:
        return any(str(value).split(":", 1)[0].strip() == key for value in inputs)

    def _input_is_user_supported(self, value: str, explicit_text: str) -> bool:
        key = str(value).split(":", 1)[0].strip()
        if key == "calculation_policy":
            return any(marker in explicit_text for marker in ("政策", "规则", "公式"))
        if key == "sales_data_source":
            return any(marker in explicit_text for marker in ("销售数据", "销售明细", "销售报表", "文件", "系统"))
        if key in {"file", "file_type", "source_file"}:
            return not bool(re.search(r"(?:没有|未提供|不确定有没有|没给|缺少).{0,4}(?:附件|文件|表格)", explicit_text))
        return True

    def _merge_results(self, parsed: StructuredConversationRequest, analyses: list[Any]) -> Any:
        raw_results = [analysis.result for analysis in analyses]
        if len(raw_results) == 1:
            result = raw_results[0]
            if isinstance(result, IntentAnalysisResult):
                return result.model_copy(update={"original_text": parsed.original_text})
            return result

        if not all(isinstance(result, IntentAnalysisResult) for result in raw_results):
            return raw_results[0]

        tasks: list[TaskItem] = []
        questions: list[str] = []
        previous_terminal_task_id: str | None = None
        for segment, result in zip(parsed.segments, raw_results, strict=True):
            local_id_map: dict[str, str] = {}
            segment_tasks: list[TaskItem] = []
            for task in result.tasks:
                dependencies = [local_id_map.get(value, value) for value in task.dependencies]
                if segment.depends_on_previous and previous_terminal_task_id and not dependencies:
                    dependencies = [previous_terminal_task_id]
                required_inputs = list(task.required_inputs)
                if (
                    dependencies
                    and "source_result" in task.missing_inputs
                    and not self._has_input(required_inputs, "source_result")
                ):
                    required_inputs.append(f"source_result:task:{dependencies[-1]}")
                task_description = segment.task_name or task.task_description
                action, business_object = TaskItem._derive_action_object(task_description)
                updated = task.model_copy(
                    update={
                        "task_description": task_description,
                        "action": action or task.action,
                        "object": business_object or task.object,
                        "required_inputs": required_inputs,
                        "dependencies": dependencies,
                    },
                )
                local_id_map[task.task_id] = updated.task_id
                segment_tasks.append(updated)
            tasks.extend(segment_tasks)
            if segment_tasks:
                previous_terminal_task_id = segment_tasks[-1].task_id
            for question in result.clarification_questions:
                if question not in questions:
                    questions.append(question)

        merged = IntentAnalysisResult(
            original_text=parsed.original_text,
            intent_category=self._intent_category(raw_results),
            tasks=tasks,
            clarification_required=any(result.clarification_required for result in raw_results),
            clarification_questions=questions,
            analysis_level=max(result.analysis_level for result in raw_results),
            overall_confidence=min((task.confidence for task in tasks), default=0),
        )
        validator = getattr(self.intent_analyzer, "input_validator", None)
        if validator is not None:
            merged, _ = validator.apply(merged)
        return merged

    def _intent_category(self, results: list[IntentAnalysisResult]) -> str:
        categories = []
        for result in results:
            if result.intent_category not in categories:
                categories.append(result.intent_category)
        return categories[0] if len(categories) == 1 else "复合任务型"


@dataclass(frozen=True)
class _BasicAnalysis:
    result: Any
    debug: dict[str, Any]
