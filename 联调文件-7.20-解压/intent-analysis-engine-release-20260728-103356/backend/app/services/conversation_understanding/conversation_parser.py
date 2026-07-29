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
from app.services.intent_analysis_engine.context_recovery import EllipsisResolver
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
    scope_filtered_text: str = ""
    scope_removed_clauses: list[str] = Field(default_factory=list)
    current_scope_empty: bool = False


class NaturalLanguageNormalizer:
    """Normalizes a working copy of text without changing the original request."""

    REPLACEMENTS = (
        (r"客服投诉", "客户投诉"),
        (r"看看有没有问题|看有没有问题", "检查分析"),
        (r"重点看|着重看", "重点分析"),
        (r"帮我瞅瞅|帮忙瞅瞅|瞅瞅", "查看"),
        (r"帮我看看|帮忙看看", "查看"),
        (r"看一下(?=.{0,12}(?:报告|报表|提成|佣金))", "处理"),
        (r"看一下(?=.{0,12}(?:海报|宣传图|图片|封面))", "处理"),
        (r"看一下(?=.{0,12}(?:逾期|未回款|未付款|低库存|异常|风险))", "筛选"),
        (r"看一看|看一下|看看", "分析"),
        (r"查一查|查一下", "查询"),
        (r"拉一下", "拉取"),
        (r"拉出来|调出来|拿出来|拿出|取出来|取出", "获取"),
        (r"算一算|算一下", "计算"),
        (r"弄一份|搞一份|做一份", "生成一份"),
        (r"整理一下", "整理"),
        (r"捋一遍|捋一下", "汇总"),
        (r"排排", "排序"),
        (r"倒序排列|倒序排|从高到低排列|从大到小排列|按风险高低排", "排序"),
        (r"形成", "生成"),
        (r"单独圈出来|圈出来|圈出", "筛选"),
        (r"给出整改建议|输出整改建议|制定整改建议", "生成改进方案"),
        (r"筛出|挑出", "筛选"),
        (r"做成(?=凭证|报告|材料|文档)", "生成"),
        (r"日报", "日度报告"),
        (r"周报", "周度报告"),
        (r"月报", "月度报告"),
        (r"吱一声|说一声|通知一声", "提醒我"),
        (r"取出来", "获取"),
        (r"能不能帮我|可以帮我|请帮我|麻烦帮我", ""),
        (r"汇报PPT|汇报ppt|汇报幻灯片", "汇报材料"),
    )

    def normalize(self, text: str) -> str:
        normalized = text.strip()
        for pattern, replacement in self.REPLACEMENTS:
            if pattern == r"看一看|看一下|看看" and self._is_document_structure_request(normalized):
                continue
            normalized = re.sub(pattern, replacement, normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"查看(.+?)(?:咋样|怎么样)", r"分析\1情况", normalized)
        normalized = re.sub(r"(.+?政策).*(?:咋规定|怎么规定)", r"\1是什么", normalized)
        normalized = re.sub(r"[，,]{2,}", "，", normalized)
        return normalized.strip(" ，,。；;")

    def _is_document_structure_request(self, text: str) -> bool:
        return bool(
            re.search(r"(?:Excel|excel|PDF|pdf|Word|word|电子表|上传表|附件|文件|表格|文档|这份)", text)
            and re.search(r"(?:字段|结构|列名|表头|字段组成|目录)", text)
            and re.search(r"(?:看一看|看一下|看看|看下|确认|查看)", text)
        )


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
        ambiguous = self._is_ambiguous_request(original_text, history_texts) or self._is_ambiguous_request(
            normalized,
            history_texts,
        )
        scope_result = self.future_scope_filter.filter_current_scope(normalized)
        current_scope_empty = not ambiguous and scope_result.current_scope_empty
        scoped_text = scope_result.filtered_text or normalized
        segments = [] if ambiguous or current_scope_empty else self._segments(scoped_text, context)
        return StructuredConversationRequest(
            original_text=original_text,
            normalized_text="，然后".join(segment.text for segment in segments) if segments else scoped_text,
            resolved_text=resolution.resolved_text,
            filtered_text=filtered.filtered_text,
            context=context,
            segments=(
                segments
                if ambiguous or current_scope_empty
                else (segments or [ConversationRequestSegment(text=scoped_text or original_text)])
            ),
            removed_noise=filtered.removed_fragments,
            resolved_references=resolution.resolved_references,
            history_texts=history_texts,
            scope_filtered_text=scope_result.filtered_text,
            scope_removed_clauses=list(scope_result.removed_clauses),
            current_scope_empty=current_scope_empty,
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
            or re.fullmatch(r"(?:帮我|帮忙)?(?:看一下|看下|看看)", normalized)
            or re.fullmatch(r"(?:把)?(?:这些|那些|这个|那个|它|这块|那块).{0,4}(?:整理|处理|弄|搞)(?:一下|下|掉|好|完)?", normalized)
        )

    def _segments(
        self,
        text: str,
        context: ExtractedConversationContext,
    ) -> list[ConversationRequestSegment]:
        text = self.future_scope_filter.remove_excluded_current_scope(text)
        if not text:
            return []
        if self._use_existing_deterministic_decomposer(text):
            return [ConversationRequestSegment(text=text)]

        clauses = [
            clause.strip()
            for clause in re.split(
                r"(?:，|,|；|;|。|\b然后\b|然后|最后|接着|随后|并且|并|再(?=[分析查生成制作整理给筛选提交推送预测提取解析读取判断获取拉拿圈排序]))",
                text,
            )
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
                r"查询|获取|拉取|拉|拿出来|拿出|取出来|取出|调出来|导出|列出|找出|整理|处理|汇总|求和|合计|统计|计算|核算|测算|分析|判断|评估|查看|检查|诊断|原因|生成|制作|写|起草|输出|形成|提醒|监控|预警|告警|设置|了解|筛选|筛出|筛|挑出|过滤|圈出来|圈出|单独圈|排序|排名|排行|排列|倒序|升序|降序|从高到低|从低到高|风险高低|比较|预测|预估|解析|读取|提取|抽取|发起|提交|推送|回传|创建|办理|走|做|制定|给出",
                clause,
            )
        )
        if not has_task_action:
            return None

        if re.search(r"整理成.*(?:结构化|清单|列表)$", clause):
            return None

        if re.fullmatch(r"(?:让|要求|通知).{1,30}(?:提交|提供|反馈|补充).{0,20}(?:说明|材料|资料|信息|文件)", clause):
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

        if re.search(r"整理(?:出来)?|查询|获取|拉取|拉|拿出来|拿出|取出来|取出|调出来|导出|列出", clause) and not re.search(r"原因|汇报|报告|材料|PPT|分析", clause):
            if re.search(r"查询|获取|拉取|拉|拿出来|拿出|取出来|取出|调出来|导出|列出", clause):
                text = clause
                text = re.sub(r"^(?:请)?(?:先|首先)?把(.{1,60}?)(?:拿出来|拿出|取出来|取出|调出来)$", r"获取\1", text)
                task_name = f"获取{primary_object or '业务'}数据"
            else:
                text = re.sub(r"^.*?(?=去年|今年|上个月|上月|本月|销售|经营|客户|库存|订单)", "整理", clause)
                if not text.startswith("整理"):
                    text = f"整理{text}"
                task_name = f"整理{primary_object or '业务'}数据"
            text = self._augment_context(text, primary_object, context)
            return ConversationRequestSegment(text=text, task_name=task_name)

        if re.search(r"排序|排名|排行|排列|倒序|升序|降序|从高到低|从低到高|风险高低", clause):
            text = clause
            if not re.search(r"排序|排名|排行", text):
                text = f"{text}排序"
            return ConversationRequestSegment(
                text=self._augment_context(text, primary_object, context),
                task_name="数据排序",
            )

        if re.search(r"找出|筛选|筛出|筛|挑出|过滤|圈出来|圈出|单独圈", clause) and re.search(r"低于|高于|超过|逾期|异常|风险|未|回款|高价值|重点|可疑", clause):
            text = clause.replace("找出", "筛选")
            text = text.replace("筛出", "筛选").replace("挑出", "筛选")
            text = re.sub(r"(?:单独)?圈出来|圈出|单独圈", "筛选", text)
            if text.startswith("筛") and not text.startswith("筛选"):
                text = "筛选" + text[1:]
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

        if re.search(r"汇报|报告|材料|PPT|文档|通知|邮件|方案|计划|建议", clause) and re.search(r"生成|制作|写|起草|输出|整理|形成|制定|给出", clause):
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

        if re.search(r"下降|下滑|波动|趋势|异常|问题|分析|判断|评估|检查|了解|查看", clause):
            text = self._with_context(clause, primary_object, context)
            text = re.sub(r"^(?:麻烦)?(?:查看|了解)(?:一下)?", "分析", text)
            text = re.sub(r"^(?:再)?做(?:一个)?", "", text)
            text = text.replace("判断", "分析")
            if not re.search(r"分析|检查|诊断|预测|同比|环比|查看|了解", text):
                text = f"分析{text}"
            if "同比" in text:
                task_name = f"{primary_object or '业务'}同比分析"
            elif "环比" in text:
                task_name = f"{primary_object or '业务'}环比分析"
            else:
                task_name = f"{primary_object or '业务'}趋势分析"
            return ConversationRequestSegment(text=text, task_name=task_name)

        if "找出" in clause and re.search(r"低于|高于|超过|逾期|异常|风险|未|回款", clause):
            clause = clause.replace("找出", "筛选")
        if clause.startswith("筛") and not clause.startswith("筛选"):
            clause = "筛选" + clause[1:]
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
        object_markers = (
            "销售",
            "经营",
            "复购率",
            "需求",
            "经销商",
            "客户",
            "渠道",
            "线索",
            "续约",
            "退款",
            "门店",
            "会员",
            "库存",
            "订单",
            "利润",
            "收入",
            "成本",
            "费用",
            "回款",
            "投诉",
            "提成",
            "奖金",
        )
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
            if value == "桂中需求":
                return "桂中需求"
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
        self.ellipsis_resolver = EllipsisResolver()

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
        provider_context_input = ContextInput.from_provider_response(provider_context)
        history_context_items = self._history_context_items(combined_history)
        context_input = self._merge_context_input(
            provider_context_input,
            history_context_items=history_context_items,
        )
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
                    history_context_items=history_context_items,
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

        direct_recovery = self._direct_context_recovery_result(
            text=text,
            context_input=context_input,
            context_resolution=context_resolution,
        )
        if direct_recovery is not None:
            result, task_recovery_debug = direct_recovery
            context_resolution["task_recovery"] = task_recovery_debug
            save_error = self._save_turn(
                conversation_id=conversation_id,
                user_id=user_id,
                text=text,
                result=result,
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
                    "save_error": save_error,
                },
                "external_context": self._external_context_debug(
                    provider_context=provider_context,
                    project_id=project_id,
                    error=context_error,
                    history_context_items=history_context_items,
                ),
                "context_resolution": context_resolution,
                "contextual_input": {
                    "user_input": context_resolution["resolved_text"],
                    "context": context_input.model_dump(mode="json"),
                },
                "long_context_extraction": None,
                "implicit_task_fallback": None,
                "final_decision": {
                    "selected_by": "context_recovery",
                    "reason": "High-confidence ellipsis was resolved from context before L1/L2 matching.",
                    "selected_tasks": [
                        {
                            "task_id": task.task_id,
                            "task_type": task.task_type,
                            "action": task.action,
                            "object": task.object,
                            "confidence": task.confidence,
                        }
                        for task in result.tasks
                    ],
                },
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
                        source_start=self._source_start_for_evidence(text, candidate.evidence_span),
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
                    "current_scope_empty": parsed.current_scope_empty and not candidate_segments,
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
            intent_category="无当前任务" if parsed.current_scope_empty else "待澄清",
            tasks=[],
            clarification_required=not parsed.current_scope_empty,
            clarification_questions=[] if parsed.current_scope_empty else ["请明确需要处理的业务对象和具体动作。"],
            analysis_level=1,
            overall_confidence=1 if parsed.current_scope_empty else 0,
        )
        if isinstance(result, IntentAnalysisResult) and not result.tasks and not parsed.current_scope_empty:
            result = result.model_copy(
                update={
                    "clarification_required": True,
                    "clarification_questions": ["请明确需要处理的业务对象和具体动作。"],
                }
            )
        if isinstance(result, IntentAnalysisResult):
            result, task_recovery_debug = self._apply_context_task_recovery(
                result=result,
                context_resolution=context_resolution,
            )
            context_resolution["task_recovery"] = task_recovery_debug
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
            history_context_items=history_context_items,
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

    def _source_start_for_evidence(self, source_text: str, evidence_span: str | None) -> int | None:
        if not evidence_span:
            return None
        source_start = source_text.find(evidence_span)
        return source_start if source_start >= 0 else None

    def _source_order_key(self, source_text: str, evidence_span: str | None) -> int:
        source_start = self._source_start_for_evidence(source_text, evidence_span)
        return source_start if source_start is not None else len(source_text)

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
            key=lambda candidate: self._source_order_key(source_text, candidate.evidence_span),
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
        fragments: list[str] = []
        for start, end in grouped:
            fragment = source_text[start:end].strip()
            if not fragment:
                continue
            scope_result = self.parser.future_scope_filter.filter_current_scope(fragment)
            if scope_result.current_scope_empty:
                continue
            filtered = scope_result.filtered_text.strip() or fragment
            if filtered:
                fragments.append(filtered)
        return fragments

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
        history_context_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "enabled": self.context_provider is not None,
            "project_id": project_id,
            "error": error,
            "context": provider_context.model_dump(mode="json"),
            "history_context_items": history_context_items or [],
        }

    def _merge_context_input(
        self,
        context_input: ContextInput,
        *,
        history_context_items: list[dict[str, Any]],
    ) -> ContextInput:
        current_conversation = dict(context_input.current_conversation)
        existing_items = current_conversation.get("items")
        merged_items = list(existing_items) if isinstance(existing_items, list) else []
        merged_items = self._merge_equivalent_context_items(merged_items, history_context_items)
        current_conversation["items"] = merged_items
        return context_input.model_copy(update={"current_conversation": current_conversation})

    def _history_context_items(self, history: list[Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for turn_index, raw_item in enumerate(history[-self.history_limit :]):
            payload = self._history_payload(raw_item)
            if payload is None:
                continue

            source_text = str(payload.get("text") or payload.get("content") or payload.get("message") or "").strip()
            analysis_result = payload.get("analysis_result")
            structured_items = self._task_context_items_from_result(
                analysis_result,
                source_text=source_text,
                turn_index=turn_index,
                source="stored_analysis_result",
            )
            if structured_items:
                items.extend(structured_items)
                continue

            if str(payload.get("role", "user")) not in {"user", "human"} or not source_text:
                continue
            deterministic_result = self._deterministic_history_result(source_text)
            if deterministic_result is None:
                continue
            items.extend(
                self._task_context_items_from_result(
                    deterministic_result.model_dump(mode="json"),
                    source_text=source_text,
                    turn_index=turn_index,
                    source="deterministic_history_parse",
                )
            )
        return self._deduplicate_context_items(items)

    def _history_payload(self, item: Any) -> dict[str, Any] | None:
        if hasattr(item, "model_dump"):
            payload = item.model_dump()
        elif isinstance(item, str):
            payload = {"role": "user", "text": item}
        elif isinstance(item, dict):
            payload = item
        else:
            return None
        return payload if isinstance(payload, dict) else None

    def _deterministic_history_result(self, text: str) -> IntentAnalysisResult | None:
        normalized = self.parser.normalizer.normalize(text)
        fast_path = getattr(self.intent_analyzer, "fast_path", None)
        if fast_path is not None:
            result = fast_path.match(normalized)
            if result is not None:
                return result

        decomposer = getattr(self.intent_analyzer, "decomposer", None)
        if decomposer is not None:
            result = decomposer.decompose(normalized)
            if result is not None:
                return result

        operation_rules = getattr(self.intent_analyzer, "operation_rules", None)
        if operation_rules is not None:
            match = operation_rules.match(normalized)
            if match is not None:
                return match.result
        return None

    def _task_context_items_from_result(
        self,
        value: Any,
        *,
        source_text: str,
        turn_index: int,
        source: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(value, dict):
            return []

        if isinstance(value.get("data"), dict):
            return self._task_context_items_from_result(
                value["data"],
                source_text=source_text,
                turn_index=turn_index,
                source=source,
            )
        if isinstance(value.get("result"), dict):
            return self._task_context_items_from_result(
                value["result"],
                source_text=source_text,
                turn_index=turn_index,
                source=source,
            )

        tasks = value.get("tasks")
        if not isinstance(tasks, list):
            return []

        items: list[dict[str, Any]] = []
        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict):
                continue
            task_type = str(task.get("task_type") or "").strip()
            if not task_type or not self._task_type_is_registered(task_type):
                continue
            task_description = str(
                task.get("task_description")
                or task.get("task_name")
                or source_text
                or task_type
            )
            items.append(
                {
                    "task_id": task.get("task_id"),
                    "task_type": task_type,
                    "task_name": task.get("task_name") or task_description,
                    "task_description": task_description,
                    "action": task.get("action"),
                    "object": task.get("object") or task.get("business_object"),
                    "required_inputs": task.get("required_inputs") or [],
                    "missing_inputs": task.get("missing_inputs") or [],
                    "source_text": source_text or task_description,
                    "history_source": source,
                    "history_turn_index": turn_index,
                    "history_task_index": task_index,
                }
            )
        return items

    def _deduplicate_context_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduplicated: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            fingerprint = (
                str(item.get("task_type") or ""),
                str(item.get("task_description") or ""),
                str(item.get("source_text") or ""),
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            deduplicated.append(item)
        return deduplicated

    def _merge_equivalent_context_items(
        self,
        existing_items: list[Any],
        new_items: list[dict[str, Any]],
    ) -> list[Any]:
        merged = list(existing_items)
        for item in new_items:
            if not isinstance(item, dict):
                continue
            equivalent_index = self._equivalent_context_item_index(merged, item)
            if equivalent_index is None:
                merged.append(item)
                continue
            existing = merged[equivalent_index]
            if not isinstance(existing, dict):
                continue
            merged[equivalent_index] = self._merge_context_item_details(existing, item)
        return merged

    def _equivalent_context_item_index(self, items: list[Any], candidate: dict[str, Any]) -> int | None:
        for index, item in enumerate(items):
            if isinstance(item, dict) and self._context_items_are_equivalent(item, candidate):
                return index
        return None

    def _context_items_are_equivalent(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_task_type = str(left.get("task_type") or "").strip()
        right_task_type = str(right.get("task_type") or "").strip()
        if not left_task_type or left_task_type != right_task_type:
            return False

        for key in ("source_text", "task_description"):
            left_value = str(left.get(key) or "").strip()
            right_value = str(right.get(key) or "").strip()
            if left_value and right_value and left_value == right_value:
                return True

        left_object = str(left.get("object") or left.get("business_object") or "").strip()
        right_object = str(right.get("object") or right.get("business_object") or "").strip()
        if left_object and right_object and left_object == right_object:
            return True
        return False

    def _merge_context_item_details(self, existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing)
        for key, value in incoming.items():
            if key in {"required_inputs", "missing_inputs"}:
                merged[key] = self._merge_required_inputs(
                    self._list_string_values(merged.get(key)),
                    self._list_string_values(value),
                )
            elif not merged.get(key) and value:
                merged[key] = value
        return merged

    def _list_string_values(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _resolve_omitted_expression(
        self,
        text: str,
        context: ContextInput,
    ) -> tuple[str, dict[str, Any]]:
        resolution = self.ellipsis_resolver.resolve(text, context)
        return resolution.resolved_text, resolution.to_debug()

    def _direct_context_recovery_result(
        self,
        *,
        text: str,
        context_input: ContextInput,
        context_resolution: dict[str, Any],
    ) -> tuple[IntentAnalysisResult, dict[str, Any]] | None:
        if not context_resolution.get("direct_recovery"):
            return None
        item = context_resolution.get("context_item")
        if not isinstance(item, dict):
            return None

        source_task_type = str(item.get("task_type") or "").strip()
        task_type = str(context_resolution.get("task_type_override") or source_task_type).strip()
        if not task_type or not self._task_type_is_registered(task_type):
            return None

        task_description = self._recovered_task_description(
            original_text=text,
            task_type=task_type,
            context_resolution=context_resolution,
            item=item,
        )
        family = str(context_resolution.get("family") or "")
        action, business_object = TaskItem._derive_action_object(task_description)
        reuse_context_action_object = task_type == source_task_type and family not in {"analysis_variant", "forecast_variant"}
        action = str(item.get("action") or action) if reuse_context_action_object else action
        business_object = (
            str(item.get("object") or item.get("business_object") or business_object)
            if reuse_context_action_object
            else business_object
        )
        required_inputs = self._merge_required_inputs(
            self._context_required_inputs(item),
            self._derived_context_inputs(
                original_text=text,
                task_type=task_type,
                task_description=task_description,
                business_object=business_object,
                family=family,
            ),
        )
        task_payload: dict[str, Any] = {
            "task_type": task_type,
            "task_description": task_description,
            "action": action,
            "object": business_object,
            "required_inputs": required_inputs,
            "missing_inputs": [],
            "dependencies": [],
            "confidence": float(context_resolution.get("context_recovery_confidence") or 0.95),
        }
        context_task_id = str(item.get("task_id") or "").strip()
        if context_task_id and task_type == source_task_type:
            task_payload["task_id"] = context_task_id

        task = TaskItem.model_validate(task_payload)
        result = IntentAnalysisResult(
            original_text=text,
            intent_category=self._intent_category_for_task(task_type),
            tasks=[task],
            clarification_required=False,
            clarification_questions=[],
            analysis_level=1,
            overall_confidence=task.confidence,
        )
        validator = getattr(self.intent_analyzer, "input_validator", None)
        if validator is not None:
            result, _ = validator.apply(
                result,
                source_text=f"{text}，{task_description}，{business_object}",
            )

        final_task = result.tasks[0]
        debug = {
            "applied": True,
            "reason": "ellipsis_context_direct_recovery",
            "task_id_preserved": bool(context_task_id and final_task.task_id == context_task_id),
            "task_type_preserved": bool(source_task_type and final_task.task_type == source_task_type),
            "source_task_id": context_task_id or None,
            "source_task_type": source_task_type or None,
            "final_task_id": final_task.task_id,
            "final_task_type": final_task.task_type,
            "semantic_matching_suppressed": context_resolution.get("semantic_matching_weight") == 0.0,
        }
        return result, debug

    def _recovered_task_description(
        self,
        *,
        original_text: str,
        task_type: str,
        context_resolution: dict[str, Any],
        item: dict[str, Any],
    ) -> str:
        family = str(context_resolution.get("family") or "")
        resolved_text = str(context_resolution.get("resolved_text") or "").strip()
        if family == "workflow_result_query":
            return resolved_text or "查询流程最新结果"
        if family == "analysis_variant" and task_type == "DATA_ANALYSIS_FORECAST":
            target = self._explicit_business_object(original_text)
            return f"预测{target}" if target else (resolved_text or "预测业务指标")
        if family in {"analysis_variant", "forecast_variant"} and resolved_text:
            return resolved_text
        for key in ("source_text", "normalized_text", "task_description", "task_name", "text", "content"):
            value = item.get(key)
            if value:
                return str(value)
        action = str(item.get("action") or "")
        business_object = str(item.get("object") or item.get("business_object") or "")
        if action or business_object:
            return f"{action}{business_object}".strip()
        return resolved_text or original_text

    def _derived_context_inputs(
        self,
        *,
        original_text: str,
        task_type: str,
        task_description: str,
        business_object: str,
        family: str,
    ) -> list[str]:
        validator = getattr(self.intent_analyzer, "input_validator", None)
        required_keys = (
            set(validator.required_inputs_for_task(task_type))
            if validator is not None
            else set()
        )
        if not required_keys:
            return []

        inputs: list[str] = []
        text = f"{original_text}，{task_description}，{business_object}"

        def add(key: str, value: str) -> None:
            if key in required_keys and value and not self._has_input(inputs, key):
                inputs.append(f"{key}:{value}")

        object_value = self._explicit_business_object(original_text) or business_object or task_description
        if task_type in {"PROCESS_HANDLE", "WORKFLOW_START"}:
            add("process_name", object_value)
        if task_type in {"DATA_ANALYSIS_PROBLEM", "DATA_ANALYSIS_FORECAST"} or task_type.startswith("DATA_ANALYSIS"):
            add("analysis_object", object_value)
            if task_type == "DATA_ANALYSIS_PROBLEM":
                add("analysis_method", self._analysis_method(text))
        if task_type in {"DOCUMENT_GENERATE", "CONTENT_GENERATE", "IMPROVEMENT_PLAN_GENERATE"}:
            add("topic", object_value)
            add("content_type", self._content_type(task_type, text))
        if task_type in {"DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT"}:
            add("file", "context_recovered")
        if task_type == "DATA_QUERY_FETCH":
            add("operation", "fetch")
            if family == "workflow" and "跟进" in original_text and not re.search(r"状态|进度|进展|情况", original_text):
                add("data_source", "context_recovered")
        if task_type in {"DATA_FILTER", "DATA_SORT"}:
            add("operation", task_type.removeprefix("DATA_").lower())
        return inputs

    def _explicit_business_object(self, text: str) -> str:
        for value in ("利润", "收入", "销售", "成本", "费用", "订单", "库存", "客户", "渠道", "线索", "续约", "退款", "门店", "会员", "投诉", "回款", "审批", "流程"):
            if value in text:
                return value
        return ""

    def _analysis_method(self, text: str) -> str:
        if "原因" in text or "归因" in text:
            return "原因分析"
        if "趋势" in text:
            return "趋势分析"
        if "风险" in text or "异常" in text:
            return "问题分析"
        return "上下文分析"

    def _content_type(self, task_type: str, text: str) -> str:
        if task_type == "IMPROVEMENT_PLAN_GENERATE":
            return "方案"
        if task_type == "DOCUMENT_GENERATE":
            for value in ("报告", "文档", "材料", "PPT"):
                if value in text:
                    return value
            return "文档"
        return "内容"

    def _intent_category_for_task(self, task_type: str) -> str:
        registry = getattr(self.intent_analyzer, "registry", None)
        if registry is not None:
            try:
                entry = registry.get_by_task_type(task_type)
            except KeyError:
                entry = None
            if entry is not None and entry.supported_intents:
                return entry.supported_intents[0]
        return "上下文恢复"

    def _apply_context_task_recovery(
        self,
        *,
        result: IntentAnalysisResult,
        context_resolution: dict[str, Any],
    ) -> tuple[IntentAnalysisResult, dict[str, Any]]:
        debug: dict[str, Any] = {
            "applied": False,
            "reason": None,
            "task_id_preserved": False,
            "task_type_preserved": False,
        }
        if not context_resolution.get("resolved"):
            debug["reason"] = "context_not_resolved"
            return result, debug
        if not result.tasks:
            debug["reason"] = "no_result_task"
            return result, debug

        item = context_resolution.get("context_item")
        if not isinstance(item, dict):
            debug["reason"] = "context_item_missing"
            return result, debug

        task_index = self._context_recovery_task_index(result, item)
        if task_index is None:
            debug["reason"] = "matching_result_task_missing"
            return result, debug

        original_task = result.tasks[task_index]
        context_task_id = str(item.get("task_id") or "").strip()
        context_task_type = str(item.get("task_type") or "").strip()
        updates: dict[str, Any] = {
            "required_inputs": self._merge_required_inputs(
                self._context_required_inputs(item),
                original_task.required_inputs,
            ),
        }
        if context_task_id:
            updates["task_id"] = context_task_id
        if context_task_type and self._task_type_is_registered(context_task_type):
            updates["task_type"] = context_task_type
        for field in ("action", "object"):
            value = str(item.get(field) or item.get("business_object" if field == "object" else "") or "").strip()
            if value:
                updates[field] = value

        recovered_task = original_task.model_copy(update=updates)
        id_map = {original_task.task_id: recovered_task.task_id}
        recovered_tasks = []
        for index, task in enumerate(result.tasks):
            if index == task_index:
                recovered_tasks.append(recovered_task)
                continue
            dependencies = [id_map.get(dependency, dependency) for dependency in task.dependencies]
            recovered_tasks.append(task.model_copy(update={"dependencies": dependencies}))

        recovered = result.model_copy(update={"tasks": recovered_tasks})
        validator = getattr(self.intent_analyzer, "input_validator", None)
        if validator is not None:
            recovered, _ = validator.apply(recovered)

        final_task = recovered.tasks[task_index]
        debug.update(
            {
                "applied": True,
                "reason": "context_task_recovered",
                "task_id_preserved": bool(context_task_id and final_task.task_id == context_task_id),
                "task_type_preserved": bool(context_task_type and final_task.task_type == context_task_type),
                "source_task_id": context_task_id or None,
                "source_task_type": context_task_type or None,
                "final_task_id": final_task.task_id,
                "final_task_type": final_task.task_type,
            }
        )
        return recovered, debug

    def _context_recovery_task_index(self, result: IntentAnalysisResult, item: dict[str, Any]) -> int | None:
        context_task_type = str(item.get("task_type") or "").strip()
        if context_task_type:
            for index, task in enumerate(result.tasks):
                if task.task_type == context_task_type:
                    return index
        family = self._task_type_family(context_task_type)
        for index, task in enumerate(result.tasks):
            if family and self._task_type_family(task.task_type) == family:
                return index
        return 0 if len(result.tasks) == 1 else None

    def _task_type_family(self, task_type: str) -> str | None:
        if "CALCULATION" in task_type:
            return "calculate"
        if task_type in {"DOCUMENT_GENERATE", "CONTENT_GENERATE", "IMPROVEMENT_PLAN_GENERATE"}:
            return "content"
        if "ANALYSIS" in task_type:
            return "analysis"
        if task_type:
            return task_type
        return None

    def _task_type_is_registered(self, task_type: str) -> bool:
        registry = getattr(self.intent_analyzer, "registry", None)
        if registry is None:
            return True
        try:
            registry.get_by_task_type(task_type)
        except KeyError:
            return False
        return True

    def _context_required_inputs(self, item: dict[str, Any]) -> list[str]:
        inputs: list[str] = []
        raw_inputs = item.get("required_inputs")
        if isinstance(raw_inputs, list):
            for value in raw_inputs:
                if isinstance(value, str) and ":" in value:
                    inputs.append(value)
                elif isinstance(value, dict):
                    inputs.extend(self._dict_inputs(value))
        for key in ("inputs", "final_inputs", "parameters"):
            value = item.get(key)
            if isinstance(value, dict):
                inputs.extend(self._dict_inputs(value))
        return inputs

    def _dict_inputs(self, values: dict[str, Any]) -> list[str]:
        return [
            f"{key}:{value}"
            for key, value in values.items()
            if isinstance(key, str) and value not in (None, "")
        ]

    def _merge_required_inputs(self, context_inputs: list[str], current_inputs: list[str]) -> list[str]:
        merged_by_key: dict[str, str] = {}
        for value in current_inputs:
            if ":" in value:
                key = value.split(":", 1)[0].strip()
                merged_by_key[key] = value
        for value in context_inputs:
            if ":" in value:
                key = value.split(":", 1)[0].strip()
                merged_by_key[key] = value
        return list(merged_by_key.values())

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
        segment_explicit_text = self._segment_validation_text(parsed, segment)
        enriched_tasks = []
        for task in result.tasks:
            required_keys = set(validator.required_inputs_for_task(task.task_type))
            retained_inputs = [
                value
                for value in task.required_inputs
                if self._input_is_user_supported(value, segment_explicit_text)
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
        validated, validation_result = validator.apply(enriched, source_text=segment_explicit_text)
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
            if any(marker in full_text for marker in ("数据库", "系统", "文件", "附件", "表格", "数据表", "明细表", "报表")):
                values["data_source"] = f"data_object:{primary_object}"
        if any(marker in full_text for marker in ("销售数据", "销售明细", "销售报表")):
            values["sales_data_source"] = "sales_data_source:销售数据"

        if context.time_ranges:
            values["statistical_range"] = f"statistical_range:{context.time_ranges[0]}"
        elif re.search(r"(?:本年|本年度|全年|今年|去年|本季度|上季度|本月|上月|Q[1-4]|20\d{2}年)", full_text, flags=re.IGNORECASE):
            values["statistical_range"] = "statistical_range:用户已提供"
        if context.data_scopes:
            values["classification_field"] = f"classification_field:{context.data_scopes[0]}"

        explicit_summary_fields = [
            value
            for value in context.summary_fields
            if value not in {"成本", "费用"} or re.search(rf"(?:{re.escape(value)})(?:金额|总额|合计)", full_text)
        ]
        if explicit_summary_fields:
            values["summary_field"] = f"summary_field:{explicit_summary_fields[0]}"

        if any(marker in segment_text for marker in ("政策", "规则", "公式")):
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
        if any(marker in full_text for marker in ("查询", "获取", "拉取", "调出来", "拿出来", "拿出", "取出来", "取出", "读取")):
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

    def _segment_validation_text(
        self,
        parsed: StructuredConversationRequest,
        segment: ConversationRequestSegment,
    ) -> str:
        parts = [*parsed.history_texts, segment.text]
        for clause in re.split(r"[。；;！？!?\n]+", parsed.resolved_text):
            clause = clause.strip()
            if not clause or clause in parts:
                continue
            if self._is_relevant_input_uncertainty_clause(clause):
                parts.append(clause)
        return "，".join(parts)

    def _is_relevant_input_uncertainty_clause(self, clause: str) -> bool:
        has_uncertainty = bool(
            re.search(r"不确定|不清楚|需要确认|需要先确认|尚未明确|没有明确|不明确|到底|究竟|还是|或", clause)
        )
        if not has_uncertainty:
            return False
        return bool(
            re.search(
                r"政策|规则|公式|数据来源|销售数据|资料.{0,12}(?:存放|来自)|文件|附件|表格|截止日期|截止时间|计算对象|计算范围",
                clause,
            )
        )

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

        validator = getattr(self.intent_analyzer, "input_validator", None)
        tasks: list[TaskItem] = []
        task_validation_sources: dict[str, str] = {}
        previous_terminal_task_id: str | None = None
        for segment, result in zip(parsed.segments, raw_results, strict=True):
            local_id_map: dict[str, str] = {}
            segment_tasks: list[TaskItem] = []
            validation_source = self._segment_validation_text(parsed, segment)
            result_task_count = len(result.tasks)
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
                if (
                    dependencies
                    and task.task_type == "DATA_AGGREGATION_SUMMARY"
                    and not self._has_input(required_inputs, "statistical_range")
                    and self._has_data_fetch_dependency(dependencies, [*tasks, *segment_tasks])
                ):
                    required_inputs.append(f"statistical_range:dependency:{dependencies[-1]}")
                task_description = (
                    segment.task_name
                    if segment.task_name and result_task_count == 1
                    else task.task_description
                )
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
                if validator is not None:
                    updated = validator.validate_task(updated, source_text=validation_source)
                task_validation_sources[updated.task_id] = validation_source
                segment_tasks.append(updated)
            tasks.extend(segment_tasks)
            if segment_tasks:
                previous_terminal_task_id = segment_tasks[-1].task_id

        tasks = self._provide_chained_data_sources(tasks)
        if validator is not None:
            tasks = [
                validator.validate_task(
                    task,
                    source_text=task_validation_sources.get(task.task_id, ""),
                )
                for task in tasks
            ]
            tasks = validator._apply_dependency_status(tasks)
        questions: list[str] = []
        for task in tasks:
            if not task.clarification_required:
                continue
            for question in task.clarification_questions:
                if question not in questions:
                    questions.append(question)
        merged = IntentAnalysisResult(
            original_text=parsed.original_text,
            intent_category=self._intent_category(raw_results),
            tasks=tasks,
            clarification_required=any(task.clarification_required for task in tasks),
            clarification_questions=questions,
            analysis_level=max(result.analysis_level for result in raw_results),
            overall_confidence=min((task.confidence for task in tasks), default=0),
        )
        return merged

    def _intent_category(self, results: list[IntentAnalysisResult]) -> str:
        categories = []
        for result in results:
            if result.intent_category not in categories:
                categories.append(result.intent_category)
        return categories[0] if len(categories) == 1 else "复合任务型"

    def _has_data_fetch_dependency(self, dependencies: list[str], tasks: list[TaskItem]) -> bool:
        dependency_ids = set(dependencies)
        return any(
            task.task_id in dependency_ids and task.task_type in {"DATA_QUERY_FETCH", "EXTERNAL_DATA_FETCH"}
            for task in tasks
        )

    def _provide_chained_data_sources(self, tasks: list[TaskItem]) -> list[TaskItem]:
        depended_task_ids = {
            dependency
            for task in tasks
            for dependency in task.dependencies
        }
        if not depended_task_ids:
            return tasks

        updated: list[TaskItem] = []
        for task in tasks:
            if (
                task.task_type == "DATA_QUERY_FETCH"
                and task.task_id in depended_task_ids
                and not self._has_input(task.required_inputs, "data_source")
                and (
                    self._has_input(task.required_inputs, "data_object")
                    or self._has_specific_business_data_object(task)
                )
            ):
                updated.append(
                    task.model_copy(
                        update={
                            "required_inputs": [
                                *task.required_inputs,
                                "data_source:upstream_business_object",
                            ],
                        }
                    )
                )
            else:
                updated.append(task)
        return updated

    def _has_specific_business_data_object(self, task: TaskItem) -> bool:
        value = str(task.object or task.task_description or "")
        if not value or value in {"数据", "业务数据"}:
            return False
        return any(
            marker in value
            for marker in (
                "客户",
                "供应商",
                "订单",
                "合同",
                "库存",
                "销售",
                "回款",
                "档案",
                "资料",
                "台账",
                "清单",
                "列表",
                "记录",
                "明细",
            )
        )


@dataclass(frozen=True)
class _BasicAnalysis:
    result: Any
    debug: dict[str, Any]
