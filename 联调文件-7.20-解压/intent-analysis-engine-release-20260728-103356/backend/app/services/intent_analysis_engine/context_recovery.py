from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.context_provider import ContextInput


@dataclass(frozen=True)
class EllipsisResolution:
    original_text: str
    normalized_text: str
    resolved_text: str
    requires_context: bool
    resolved: bool
    family: str | None
    scope: str | None = None
    context_item: dict[str, Any] | None = None
    candidate_count: int = 0
    ambiguous: bool = False
    ambiguity_scope: str | None = None
    clarification_reason: str | None = None
    context_recovery_confidence: float = 0.0
    semantic_matching_weight: float = 1.0
    direct_recovery: bool = False
    task_type_override: str | None = None

    def to_debug(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "resolved_text": self.resolved_text,
            "requires_context": self.requires_context,
            "resolved": self.resolved,
            "family": self.family,
            "scope": self.scope,
            "context_item": self.context_item,
            "candidate_count": self.candidate_count,
            "ambiguous": self.ambiguous,
            "ambiguity_scope": self.ambiguity_scope,
            "clarification_reason": self.clarification_reason,
            "context_recovery_confidence": self.context_recovery_confidence,
            "semantic_matching_weight": self.semantic_matching_weight,
            "direct_recovery": self.direct_recovery,
            "task_type_override": self.task_type_override,
        }


class EllipsisResolver:
    """Resolves high-confidence omitted follow-up requests before task matching."""

    _SCOPE_ORDER = (
        ("conversation", "current_conversation"),
        ("project", "current_project"),
        ("historical_projects", "historical_projects"),
    )

    def resolve(self, text: str, context: ContextInput) -> EllipsisResolution:
        normalized = self._normalize(text)
        family = self._ellipsis_family(normalized)
        if family is None:
            return EllipsisResolution(
                original_text=text,
                normalized_text=normalized,
                resolved_text=text,
                requires_context=False,
                resolved=False,
                family=None,
            )

        match = self._context_item_for_family(context, family)
        if match is None:
            return EllipsisResolution(
                original_text=text,
                normalized_text=normalized,
                resolved_text=text,
                requires_context=True,
                resolved=False,
                family=family,
                clarification_reason="context_not_found",
                context_recovery_confidence=0.0,
                semantic_matching_weight=0.0,
            )

        scope, items = match
        if len(items) > 1:
            return EllipsisResolution(
                original_text=text,
                normalized_text=normalized,
                resolved_text=text,
                requires_context=True,
                resolved=False,
                family=family,
                scope=scope,
                candidate_count=len(items),
                ambiguous=True,
                ambiguity_scope=scope,
                clarification_reason="ambiguous_context",
                context_recovery_confidence=0.0,
                semantic_matching_weight=0.0,
            )

        item = items[0]
        return EllipsisResolution(
            original_text=text,
            normalized_text=normalized,
            resolved_text=self._resolved_text_for_family(text, family, item),
            requires_context=True,
            resolved=True,
            family=family,
            scope=scope,
            context_item=item,
            candidate_count=1,
            context_recovery_confidence=0.95,
            semantic_matching_weight=0.0,
            direct_recovery=True,
            task_type_override=self._task_type_override(family, item, normalized),
        )

    def _normalize(self, text: str) -> str:
        normalized = text.strip(" ，,。；;！？!?")
        normalized = re.sub(r"^(?:也|再)?(?:帮我|帮忙|麻烦|请)\s*", "", normalized)
        normalized = re.sub(r"^(?:继续处理|接着处理|继续|接着)[:：]\s*", "", normalized)
        normalized = re.sub(r"^(?:上一轮那个|上轮那个|刚才那个|上面的|上一步的|上一步|上次那个|那个)\s*", "", normalized)
        return normalized.strip(" ，,。；;！？!?")

    def _ellipsis_family(self, normalized: str) -> str | None:
        if self._looks_like_context_reference(normalized):
            return "context_reference"
        if re.fullmatch(r"(?:换个|换一?个|按|按照|照).{0,8}(?:口径|规则|方式).{0,8}(?:再|重新|重)?(?:算|计算|核算|测算)(?:一遍|一次|一下)?", normalized):
            return "calculate"
        if re.fullmatch(r"(?:继续|接着|再|重新)?(?:润色|改写|调整|修改|优化)(?:一下|一版|一遍|一稿)?", normalized):
            return "content_edit"
        if re.fullmatch(r"(?:继续|接着|再)(?:弄|做|处理)(?:一下|一版|一遍)?", normalized):
            return "same_task"
        if re.fullmatch(r"(?:帮我)?(?:再|重新)?(?:算|计算|核算|测算)(?:一次|一遍|一下)?", normalized):
            return "calculate"
        if re.fullmatch(r"(?:接着|继续|再)?(?:改|修改|调整)(?:一下|一版)?", normalized):
            return "content_edit"
        if re.fullmatch(
            r"(?:(?:沿用|照着)(?:同样|相同|刚才|之前|上次|上一轮)?"
            r"|(?:按|按照)(?:同样|相同|刚才|之前|上次|上一轮)"
            r"|(?:同样|相同|刚才|之前|上次|上一轮))"
            r".{0,8}(?:条件|规则|口径|方式)?(?:再|继续|接着)?"
            r".{0,4}(?:筛|筛选|过滤|挑|挑出|找|找出)(?:一批|一组|一版|一次|一遍|一下)?.*",
            normalized,
        ):
            return "filter"
        if re.fullmatch(
            r"(?:再|继续|接着|重新)(?:筛|筛选|过滤|挑|挑出|找|找出)(?:一批|一组|一版|一次|一遍|一下)?.*",
            normalized,
        ):
            return "filter"
        if re.fullmatch(r"(?:继续|接着|再)?(?:看|查看|确认).{0,8}(?:符合条件|命中条件|筛选结果|过滤结果).{0,8}", normalized):
            return "filter"
        if re.fullmatch(r"(?:换个|换一个|再换个).{0,4}维度(?:看看|看一下|分析)?", normalized):
            return "analysis"
        if re.fullmatch(r"(?:继续|接着|再)分析(?:一下|一遍)?", normalized):
            return "analysis"
        if re.fullmatch(
            r"(?:继续|接着|再)?(?:确认|查看|看下|看看|看一下|检查|梳理|列|提取|解析|读取)"
            r".{0,8}(?:字段|结构|列|列名|表头|清单|列结构|字段清单)",
            normalized,
        ):
            return "document_parse"
        if re.fullmatch(
            r"(?:按|按照)?(?:上一轮|上次|刚才|之前).{0,8}"
            r"(?:确认|查看|看下|看一下|查询|查|跟进).{0,8}(?:办理)?(?:进展|进度|状态|情况)",
            normalized,
        ):
            return "workflow"
        if re.fullmatch(
            r"(?:继续|接着|再)?(?:确认|查看|看下|看一下|查询|查|跟进).{0,8}(?:办理)?(?:进展|进度|状态|情况)",
            normalized,
        ):
            return "workflow"
        if re.fullmatch(r"(?:继续|接着|再)?跟进(?:一下|下)?", normalized):
            return "workflow"
        if re.fullmatch(r"(?:继续|接着)?处理(?:刚才|之前|上次|上一轮|上一步|上面)的?(?:分析|任务|结果)?", normalized):
            return "same_task"
        if re.fullmatch(r"(?:继续|接着|重新|再)(?:处理|做|看|看看|查|查询|来)(?:一次|一遍|一下)?", normalized):
            return "same_task"
        if re.fullmatch(r"(?:重新|再)(?:看看|看一下)", normalized):
            return "same_task"
        if re.fullmatch(r"(?:沿用|照着|按|按照)(?:同样|相同|刚才|之前|上次|上一轮).{0,8}(?:继续|接着|再)?(?:处理|做|执行|来一遍)?(?:一下)?", normalized):
            return "same_task"
        if re.fullmatch(r"(?:按|按照)?(?:同样|相同|刚才|之前|上次|上一轮).{0,6}(?:方式|口径|规则|条件|结果)(?:继续|再)?(?:处理|做|来一遍)?(?:一下)?", normalized):
            return "same_task"
        if re.fullmatch(r"(?:按|按照)?(?:同样|相同|刚才|之前|上次|上一轮).{0,10}(?:再|继续)?(?:筛|筛选|过滤|找).{0,8}", normalized):
            return "filter"
        if re.fullmatch(r"(?:再|继续|接着)?(?:提取|解析|读取|检查|查看|看|列)(?:字段|结构|列信息)(?:一下)?", normalized):
            return "document_parse"
        if re.fullmatch(r"(?:字段|结构|列信息)(?:也)?(?:列|看|检查|提取)(?:一下)?", normalized):
            return "document_parse"
        if re.fullmatch(r"(?:查看|查询|看一下|看看)(?:这个|该|上个|刚才的|上一轮的).{0,12}(?:审批|流程|工单).{0,8}(?:结果|进度|状态|情况)", normalized):
            return "workflow_result_query"
        if re.fullmatch(r"(?:(?:继续|接着|再)(?:处理|办理|跟进|推进)|(?:跟进|推进)).{0,12}(?:流程|审批|工单).{0,8}(?:情况|进度|状态)?", normalized):
            return "workflow"
        if re.fullmatch(r"(?:换成|改成|也看|也分析|再看|再分析).{1,12}(?:看看|看一下|分析)?", normalized):
            return "analysis_variant"
        if re.fullmatch(r".{1,12}也预测一下|再预测.{1,12}|(?:换成|改成).{1,12}看看", normalized):
            return "forecast_variant"
        if re.fullmatch(r"(?:语气|口吻|表达)?(?:再)?(?:正式|严谨|简洁|委婉|专业)(?:点|一点)?", normalized):
            return "content_edit"
        return None

    def _looks_like_context_reference(self, normalized: str) -> bool:
        if not normalized:
            return False
        if self._has_explicit_current_task(normalized):
            return False

        reference_objects = (
            "上文",
            "上面",
            "前面",
            "前文",
            "刚才",
            "之前",
            "上次",
            "上一轮",
            "上一步",
            "客户反馈",
            "客户意见",
            "用户反馈",
            "用户意见",
            "反馈内容",
            "意见建议",
            "调研反馈",
            "投诉反馈",
            "沟通记录",
            "会议纪要",
            "这份材料",
            "这些材料",
            "这段内容",
            "这些信息",
            "客户需求",
            "业务反馈",
            "问题反馈",
            "整理结果",
            "分析结果",
            "筛选结果",
        )
        reference_pattern = "|".join(re.escape(value) for value in reference_objects)
        prefix = r"(?:根据|基于|按照|按|结合|参考|依据|用|拿|围绕)"
        generic_tail = r"(?:来|去|再)?(?:处理|做|弄|执行|推进|完善|调整)?(?:一下|一遍|一版)?"
        return bool(
            re.fullmatch(rf"{prefix}.{{0,10}}(?:{reference_pattern}).{{0,8}}{generic_tail}", normalized)
            or re.fullmatch(rf"(?:{reference_pattern}).{{0,8}}{generic_tail}", normalized)
            or re.fullmatch(r"(?:按|按照).{0,8}(?:之前|上文|上面|刚才|上一轮|上一步).{0,8}(?:任务|内容|材料)(?:处理|做|执行)?(?:一下)?", normalized)
        )

    def _has_explicit_current_task(self, normalized: str) -> bool:
        explicit_actions = (
            "生成",
            "创建",
            "写",
            "撰写",
            "起草",
            "输出",
            "制作",
            "整理成",
            "分析",
            "诊断",
            "判断",
            "评估",
            "预测",
            "计算",
            "核算",
            "测算",
            "查询",
            "获取",
            "拉取",
            "导出",
            "筛选",
            "排序",
            "汇总",
            "统计",
            "办理",
            "发起",
            "提交",
            "提醒",
            "监控",
            "解析",
            "提取",
            "读取",
        )
        if any(action in normalized for action in explicit_actions):
            return True
        return bool(re.search(r"(?:出|给出|形成|拟定|制定).{0,12}(?:方案|计划|建议|报告|材料)", normalized))

    def _context_item_for_family(
        self,
        context: ContextInput,
        family: str,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        for scope_name, attr_name in self._SCOPE_ORDER:
            scope = getattr(context, attr_name)
            items = scope.get("items")
            if not isinstance(items, list):
                continue
            candidates = [
                task
                for item in reversed(items)
                if isinstance(item, dict)
                for task in [self._task_like_item(item)]
                if task is not None and self._item_matches_family(task, family)
            ]
            if candidates:
                return scope_name, candidates
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
        task_family = self._task_family(task_type)
        if family == "same_task":
            return bool(task_type or text)
        if family == "context_reference":
            return bool(task_type or text)
        if family == "calculate":
            return task_family == "calculate" or any(value in text for value in ("计算", "核算", "测算", "提成", "佣金"))
        if family in {"content_edit", "report"}:
            return task_family == "content" or any(value in text for value in ("报告", "材料", "文档", "PPT", "邮件", "通知", "说明", "文案"))
        if family == "analysis":
            return task_family == "analysis" or any(value in text for value in ("分析", "趋势", "原因", "维度"))
        if family == "analysis_variant":
            return task_family in {"analysis", "forecast", "aggregation"} or any(value in text for value in ("分析", "预测", "统计", "汇总"))
        if family == "forecast_variant":
            return task_family == "forecast" or "预测" in text or "预估" in text
        if family == "filter":
            return task_family in {"filter", "data_fetch"} or any(value in text for value in ("筛选", "过滤", "找出", "查询", "获取", "拉取"))
        if family == "document_parse":
            return task_family == "document_parse" or any(value in text for value in ("解析", "提取", "读取", "Excel", "表格", "字段", "结构"))
        if family in {"workflow", "workflow_result_query"}:
            return task_family == "workflow" or any(value in text for value in ("流程", "审批", "工单", "办理", "发起"))
        return False

    def _task_family(self, task_type: str) -> str | None:
        if "CALCULATION" in task_type:
            return "calculate"
        if task_type in {"DOCUMENT_GENERATE", "CONTENT_GENERATE", "IMPROVEMENT_PLAN_GENERATE"}:
            return "content"
        if task_type in {"DATA_ANALYSIS_FORECAST"}:
            return "forecast"
        if task_type.startswith("DATA_ANALYSIS"):
            return "analysis"
        if task_type in {"DATA_AGGREGATION_SUMMARY", "DATA_ANALYSIS_GROUP_SUM", "DATA_ANALYSIS_PIVOT"}:
            return "aggregation"
        if task_type == "DATA_FILTER":
            return "filter"
        if task_type in {"DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT"}:
            return "document_parse"
        if task_type in {"PROCESS_HANDLE", "WORKFLOW_START"}:
            return "workflow"
        if task_type in {"DATA_QUERY_FETCH", "EXTERNAL_DATA_FETCH"}:
            return "data_fetch"
        if task_type:
            return task_type
        return None

    def _resolved_text_for_family(self, original: str, family: str, item: dict[str, Any]) -> str:
        subject = self._context_item_subject(item)
        if family == "same_task":
            return subject
        if family == "context_reference":
            return subject
        if family == "calculate":
            if subject.startswith(("计算", "核算", "测算")):
                return f"重新{subject}"
            return f"重新计算{subject}"
        if family in {"content_edit", "report"}:
            subject = re.sub(r"^(?:生成|制作|撰写|写|输出|起草)", "", subject).strip() or subject
            return f"生成{subject}修改稿"
        if family == "analysis":
            subject = re.sub(r"^(?:分析|查看|检查|诊断|了解)", "", subject).strip() or subject
            return f"换个维度分析{subject}"
        if family == "analysis_variant":
            return self._analysis_variant_text(original, subject)
        if family == "forecast_variant":
            return self._forecast_variant_text(original, subject)
        if family == "filter":
            subject = re.sub(r"^(?:筛选|过滤|找出)", "", subject).strip() or subject
            return f"筛选{subject}"
        if family == "document_parse":
            return subject
        if family == "workflow_result_query":
            subject = re.sub(r"^(?:发起|启动|提交|创建|办理|处理)", "", subject).strip() or subject
            return f"查询{subject}最新结果"
        if family == "workflow":
            return subject
        return original

    def _analysis_variant_text(self, original: str, subject: str) -> str:
        target = self._explicit_business_object(original)
        if target:
            return f"分析{target}"
        return subject

    def _forecast_variant_text(self, original: str, subject: str) -> str:
        target = self._explicit_business_object(original)
        if target:
            return f"预测{target}"
        if subject.startswith(("预测", "预估")):
            return subject
        return f"预测{subject}"

    def _explicit_business_object(self, text: str) -> str:
        for value in ("利润", "收入", "销售", "成本", "费用", "订单", "库存", "客户", "投诉", "回款"):
            if value in text:
                return value
        return ""

    def _task_type_override(self, family: str, item: dict[str, Any], normalized: str) -> str | None:
        if family == "filter":
            return "DATA_FILTER"
        if family == "workflow_result_query":
            return "DATA_QUERY_FETCH"
        if family == "workflow" and str(item.get("task_type") or "") == "WORKFLOW_START":
            return "DATA_QUERY_FETCH"
        return None

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
