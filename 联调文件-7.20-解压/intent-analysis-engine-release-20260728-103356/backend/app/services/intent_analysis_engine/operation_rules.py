from dataclasses import dataclass
import re
from typing import Any

from app.schemas.intent_analysis import IntentAnalysisResult
from app.services.intent_analysis_engine.task_factory import TaskFactory
from app.services.task_extraction.future_scope_filter import FutureScopeFilter


@dataclass(frozen=True)
class OperationRuleMatch:
    result: IntentAnalysisResult
    rule_name: str
    rule_priority: int


class OperationRuleMatcher:
    """Level 1 matcher for high-frequency standard operations."""

    RULE_PRIORITIES = {
        "document_table_parsing": 96,
        "external_system_connector": 96,
        "digital_asset": 96,
        "content_output": 95,
        "pivot_table": 94,
        "multimedia_generation": 93,
        "workflow_execution": 92,
        "monitoring_reminder": 91,
        "rule_calculation": 90,
        "forecast": 88,
        "group_sum": 87,
        "year_over_year": 86,
        "month_over_month": 86,
        "filter": 85,
        "sort": 84,
        "complaint_information_organize": 83,
        "summary": 82,
        "data_query_fetch": 81,
        "knowledge_qa": 80,
        "problem_analysis": 60,
    }

    def __init__(self, task_factory: TaskFactory, *, future_scope_filter: FutureScopeFilter | None = None) -> None:
        self.task_factory = task_factory
        self.future_scope_filter = future_scope_filter or FutureScopeFilter()

    def match(self, text: str | dict[str, Any]) -> OperationRuleMatch | None:
        normalized = self._user_input(text).strip()
        if not normalized:
            return None
        if self.future_scope_filter.text_is_fully_excluded(normalized):
            return None
        normalized = self.future_scope_filter.remove_excluded_current_scope(normalized).strip()
        if not normalized:
            return None

        candidates: list[OperationRuleMatch] = []
        for matcher in (
            self._match_document_table_parsing,
            self._match_external_system,
            self._match_digital_asset,
            self._match_multimedia_generation,
            self._match_workflow,
            self._match_monitoring,
            self._match_analytics,
            self._match_filter,
            self._match_rule_calculation,
            self._match_complaint_information_organize,
            self._match_data_query,
            self._match_knowledge_qa,
            self._match_content_output,
        ):
            match = matcher(normalized)
            if match is not None:
                candidates.append(match)

        if "透视表" in normalized:
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="pivot_table",
                    intent_category="数据分析型",
                    task_name="生成数据透视表",
                    task_type="DATA_ANALYSIS_PIVOT",
                    required_inputs=self._data_inputs(normalized, operation="透视表"),
                    confidence=0.97,
                ),
            )

        if self._contains_any(normalized, ["分类求和", "按"]) and self._contains_any(normalized, ["求和", "合计"]):
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="group_sum",
                    intent_category="数据分析型",
                    task_name="分类求和",
                    task_type="DATA_ANALYSIS_GROUP_SUM",
                    required_inputs=self._data_inputs(normalized, operation="分类求和"),
                    confidence=0.94,
                ),
            )

        if "同比" in normalized:
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="year_over_year",
                    intent_category="数据分析型",
                    task_name="同比分析",
                    task_type="DATA_ANALYSIS_YOY",
                    required_inputs=self._data_inputs(normalized, operation="同比"),
                    confidence=0.93,
                ),
            )

        if "环比" in normalized:
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="month_over_month",
                    intent_category="数据分析型",
                    task_name="环比分析",
                    task_type="DATA_ANALYSIS_MOM",
                    required_inputs=self._data_inputs(normalized, operation="环比"),
                    confidence=0.93,
                ),
            )

        period_comparison = self._period_comparison_mode(normalized)
        if period_comparison is not None:
            task_type, task_name, operation = period_comparison
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="period_comparison",
                    intent_category="数据分析型",
                    task_name=task_name,
                    task_type=task_type,
                    required_inputs=self._data_inputs(normalized, operation=operation),
                    confidence=0.92,
                    rule_priority=87,
                ),
            )

        if self._is_sort_request(normalized):
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="sort",
                    intent_category="数据分析型",
                    task_name="数据排序",
                    task_type="DATA_SORT",
                    required_inputs=self._data_inputs(normalized, operation="排序"),
                    confidence=0.9,
                ),
            )

        if self._contains_any(normalized, ["筛选", "过滤"]):
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="filter",
                    intent_category="数据查询型",
                    task_name="数据筛选",
                    task_type="DATA_FILTER",
                    required_inputs=self._data_inputs(normalized, operation="筛选"),
                    confidence=0.9,
                ),
            )

        if self._contains_any(normalized, ["统计", "汇总"]):
            candidates.append(
                self._single_task_result(
                    text=normalized,
                    rule_name="summary",
                    intent_category="数据分析型",
                    task_name="数据统计汇总",
                    task_type="DATA_AGGREGATION_SUMMARY",
                    required_inputs=self._data_inputs(normalized, operation="统计汇总"),
                    confidence=0.9,
                ),
            )

        return self._select_best(candidates)

    def _match_document_table_parsing(self, text: str) -> OperationRuleMatch | None:
        document_keywords = [
            "excel",
            "pdf",
            "word",
            "表格",
            "电子表格",
            "电子表",
            "上传表",
            "文档",
            "附件",
            "合同",
            "发票",
            "单据",
            "文件",
        ]
        parse_keywords = ["解析", "识别", "读取", "提取", "抽取", "拆解", "导入", "查看", "看", "确认", "列"]
        strict_parse_keywords = ["解析", "识别", "读取", "提取", "抽取", "拆解", "导入"]
        structure_keywords = ["结构", "字段", "目录", "条款", "列名", "表头", "字段组成"]
        field_structure_request = self._contains_any(text, parse_keywords) and self._contains_any(
            text,
            structure_keywords,
        )
        document_parse_request = self._contains_any(text.lower(), document_keywords) and (
            self._contains_any(text, strict_parse_keywords) or field_structure_request
        )
        if not (document_parse_request or field_structure_request):
            return None

        task_type = "FILE_STRUCTURE_EXTRACT" if self._contains_any(text, structure_keywords) else "DOCUMENT_TABLE_PARSE"
        task_name = "提取文件结构" if task_type == "FILE_STRUCTURE_EXTRACT" else "解析文档表格"
        return self._single_task_result(
            text=text,
            rule_name="document_table_parsing",
            intent_category="数据查询型",
            task_name=task_name,
            task_type=task_type,
            required_inputs=self._document_inputs(text),
            confidence=0.94,
        )

    def _match_external_system(self, text: str) -> OperationRuleMatch | None:
        system_keywords = [
            "crm",
            "erp",
            "oa",
            "sap",
            "金蝶",
            "用友",
            "飞书",
            "钉钉",
            "企业微信",
            "财务系统",
            "业务系统",
            "外部系统",
            "业务平台",
            "外部平台",
            "平台",
            "系统",
        ]
        operation_keywords = ["获取", "查询", "拉取", "拉", "同步", "提交", "推送", "写入", "写回", "更新", "回传", "回写", "推回", "上传", "导入", "导出"]
        if not (self._contains_any(text.lower(), system_keywords) and self._contains_any(text, operation_keywords)):
            return None

        submit_keywords = ["提交", "推送", "写入", "写回", "更新", "回传", "回写", "推回", "上传", "同步到", "同步回", "导入"]
        task_type = "EXTERNAL_SYSTEM_SUBMIT" if self._contains_any(text, submit_keywords) else "EXTERNAL_DATA_FETCH"
        task_name = "提交外部系统" if task_type == "EXTERNAL_SYSTEM_SUBMIT" else "获取外部系统数据"
        return self._single_task_result(
            text=text,
            rule_name="external_system_connector",
            intent_category="外部系统操作型" if task_type == "EXTERNAL_SYSTEM_SUBMIT" else "数据查询型",
            task_name=task_name,
            task_type=task_type,
            required_inputs=self._external_system_inputs(text),
            confidence=0.93,
        )

    def _match_digital_asset(self, text: str) -> OperationRuleMatch | None:
        asset_keywords = ["计提凭证", "会计凭证", "记账凭证", "凭证", "业务单据", "电子单据", "数字资产", "归档资产"]
        action_keywords = ["生成", "创建", "登记", "归档", "制作", "开具"]
        if not (self._contains_any(text, asset_keywords) and self._contains_any(text, action_keywords)):
            return None

        return self._single_task_result(
            text=text,
            rule_name="digital_asset",
            intent_category="文档生成型",
            task_name="创建数字资产凭证",
            task_type="DIGITAL_ASSET_ACCRUAL_VOUCHER",
            required_inputs=self._digital_asset_inputs(text),
            confidence=0.92,
        )

    def _match_multimedia_generation(self, text: str) -> OperationRuleMatch | None:
        media_keywords = ["图片", "海报", "配图", "封面", "视频", "短视频", "音频", "语音", "多媒体", "宣传图"]
        action_keywords = ["生成", "创建", "制作", "设计", "输出", "画", "做", "处理"]
        if not (self._contains_any(text, media_keywords) and self._contains_any(text, action_keywords)):
            return None

        return self._single_task_result(
            text=text,
            rule_name="multimedia_generation",
            intent_category="内容生成型",
            task_name="生成多媒体内容",
            task_type="MULTIMEDIA_GENERATE",
            required_inputs=self._multimedia_inputs(text),
            confidence=0.92,
        )

    def _match_workflow(self, text: str) -> OperationRuleMatch | None:
        workflow_keywords = ["流程", "审批", "报销", "请假", "采购申请", "立项", "付款申请", "工单"]
        action_keywords = ["发起", "提交", "办理", "流转", "走", "启动", "创建"]
        if not (self._contains_any(text, workflow_keywords) and self._contains_any(text, action_keywords)):
            return None

        task_type = "WORKFLOW_START" if self._contains_any(text, ["发起", "启动", "提交", "创建"]) else "PROCESS_HANDLE"
        task_name = "发起业务流程" if task_type == "WORKFLOW_START" else "办理业务流程"
        return self._single_task_result(
            text=text,
            rule_name="workflow_execution",
            intent_category="流程办理型",
            task_name=task_name,
            task_type=task_type,
            required_inputs=self._workflow_inputs(text),
            confidence=0.92,
        )

    def _match_monitoring(self, text: str) -> OperationRuleMatch | None:
        monitor_keywords = ["提醒", "监控", "预警", "告警", "通知我", "定时", "订阅"]
        if not self._contains_any(text, monitor_keywords):
            return None

        return self._single_task_result(
            text=text,
            rule_name="monitoring_reminder",
            intent_category="流程办理型",
            task_name="创建监控提醒",
            task_type="MONITORING_REMINDER",
            required_inputs=self._monitoring_inputs(text),
            confidence=0.91,
        )

    def _match_analytics(self, text: str) -> OperationRuleMatch | None:
        if self._contains_any(text, ["预测", "预估", " forecast", "趋势预测"]):
            analysis_object = self._analysis_object_from_text(text)
            return self._single_task_result(
                text=text,
                rule_name="forecast",
                intent_category="数据分析型",
                task_name=f"预测{analysis_object}" if analysis_object else "预测分析",
                task_type="DATA_ANALYSIS_FORECAST",
                required_inputs=self._analytics_inputs(text, method="预测"),
                confidence=0.92,
            )

        if self._contains_any(text, ["筛选", "过滤", "生成", "创建", "写", "撰写", "输出", "制作"]):
            return None
        if self._is_list_artifact_request(text):
            return None

        analysis_keywords = ["分析", "诊断", "原因", "归因", "异常", "风险", "趋势", "洞察", "波动"]
        if not self._contains_any(text, analysis_keywords):
            return None

        analysis_object = self._analysis_object_from_text(text)
        return self._single_task_result(
            text=text,
            rule_name="problem_analysis",
            intent_category="数据分析型",
            task_name=f"分析{analysis_object}" if analysis_object else "问题分析",
            task_type="DATA_ANALYSIS_PROBLEM",
            required_inputs=self._analytics_inputs(text, method="问题分析"),
            confidence=0.9,
        )

    def _match_filter(self, text: str) -> OperationRuleMatch | None:
        filter_action_keywords = [
            "筛选",
            "过滤",
            "筛出",
            "筛出来",
            "挑出",
            "挑出来",
            "找出",
            "找出来",
            "列出",
        ]
        condition_keywords = [
            "符合条件",
            "不符合条件",
            "低库存",
            "库存不足",
            "不足",
            "逾期",
            "超期",
            "异常",
            "风险",
            "未付款",
            "未回款",
            "回款",
            "低于",
            "高于",
            "超过",
            "大于",
            "小于",
        ]
        if not (self._contains_any(text, filter_action_keywords) and self._contains_any(text, condition_keywords)):
            return None

        return self._single_task_result(
            text=text,
            rule_name="filter",
            intent_category="数据查询型",
            task_name="数据筛选",
            task_type="DATA_FILTER",
            required_inputs=self._data_inputs(text, operation="筛选"),
            confidence=0.91,
        )

    def _match_rule_calculation(self, text: str) -> OperationRuleMatch | None:
        calculation_keywords = ["计算", "核算", "测算", "算出", "算一下", "计提"]
        calculation_targets = ["提成", "佣金", "奖金", "绩效", "税", "费用", "折扣", "扣款", "分摊", "规则", "公式", "政策"]
        explicit_calculation = self._contains_any(text, calculation_keywords) and self._contains_any(text, calculation_targets)
        if not explicit_calculation and "分析" in text:
            return None
        short_commission_phrase = self._is_short_commission_phrase(text)
        if not explicit_calculation and not short_commission_phrase:
            return None

        topic_only = short_commission_phrase and not explicit_calculation
        task_type = "RULE_CALCULATION_COMMISSION" if self._contains_any(text, ["提成", "佣金"]) else "RULE_CALCULATION_GENERAL"
        task_name = "计算销售提成" if task_type == "RULE_CALCULATION_COMMISSION" else "规则计算"
        return self._single_task_result(
            text=text,
            rule_name="rule_calculation",
            intent_category="规则计算型",
            task_name=task_name,
            task_type=task_type,
            required_inputs=self._calculation_inputs(text),
            confidence=0.86 if topic_only else 0.92,
            rule_priority=70 if topic_only else None,
        )

    def _match_complaint_information_organize(self, text: str) -> OperationRuleMatch | None:
        complaint_keywords = ["客户投诉", "投诉记录", "投诉信息", "投诉明细", "投诉"]
        organize_keywords = ["整理", "归集", "归类", "归档"]
        if not (self._contains_any(text, complaint_keywords) and self._contains_any(text, organize_keywords)):
            return None

        return self._single_task_result(
            text=text,
            rule_name="complaint_information_organize",
            intent_category="数据查询型",
            task_name="投诉信息整理",
            task_type="COMPLAINT_INFORMATION_ORGANIZE",
            required_inputs=["data_object:客户投诉", "operation:整理归集"],
            confidence=0.91,
        )

    def _match_data_query(self, text: str) -> OperationRuleMatch | None:
        query_keywords = ["查询", "获取", "查看", "拉取", "列出", "导出", "找出", "整理", "取出", "取出来", "拿出", "拿出来", "调出"]
        data_keywords = ["数据", "资料", "档案", "信息", "明细", "记录", "列表", "台账", "清单", "客户", "供应商", "合同", "订单", "销售", "库存", "金额", "报表"]
        organize_sales_data = bool(re.fullmatch(r"整理销售数据", text.strip()))
        if not (
            (self._contains_any(text, query_keywords) and self._contains_any(text, data_keywords))
            or organize_sales_data
        ):
            return None

        operation = "整理归集" if organize_sales_data or "整理" in text else "查询获取"
        return self._single_task_result(
            text=text,
            rule_name="data_query_fetch",
            intent_category="数据查询型",
            task_name="获取业务数据",
            task_type="DATA_QUERY_FETCH",
            required_inputs=self._data_inputs(text, operation=operation),
            confidence=0.89,
        )

    def _match_knowledge_qa(self, text: str) -> OperationRuleMatch | None:
        knowledge_keywords = ["政策", "制度", "规则", "标准", "定义", "说明", "知识库", "faq", "问答", "报销标准", "销售政策"]
        question_keywords = ["什么", "如何", "怎么", "为什么", "解释", "说明", "查询", "了解", "告诉我"]
        if not (self._contains_any(text.lower(), knowledge_keywords) and self._contains_any(text, question_keywords)):
            return None

        return self._single_task_result(
            text=text,
            rule_name="knowledge_qa",
            intent_category="智能问答型",
            task_name="智能问答",
            task_type="QUESTION_ANSWER",
            required_inputs=[f"question:{text}"],
            confidence=0.94,
        )

    def _match_content_output(self, text: str) -> OperationRuleMatch | None:
        content_keywords = ["报告", "报表", "日报", "周报", "月报", "文档", "通知", "说明", "方案", "总结", "文案", "邮件", "话术", "材料", "计划"]
        action_keywords = ["生成", "创建", "写", "撰写", "起草", "输出", "制作", "整理成", "给出", "形成", "拟定", "制定"]
        explicit_output_phrase = bool(re.search(r"(?:出|产出).{0,12}(?:报告|报表|文档|通知|说明|方案|总结|文案|邮件|话术|材料|计划|建议)", text))
        if not (
            self._contains_any(text, content_keywords)
            and (self._contains_any(text, action_keywords) or explicit_output_phrase)
        ):
            return None

        if self._contains_any(text, ["报告", "报表", "文档", "材料"]):
            task_type = "DOCUMENT_GENERATE"
            task_name = "生成业务文档"
            intent_category = "文档生成型"
        elif self._contains_any(text, ["方案", "计划"]):
            task_type = "IMPROVEMENT_PLAN_GENERATE"
            task_name = "生成方案"
            intent_category = "内容生成型"
        else:
            task_type = "CONTENT_GENERATE"
            task_name = "生成业务内容"
            intent_category = "内容生成型"

        return self._single_task_result(
            text=text,
            rule_name="content_output",
            intent_category=intent_category,
            task_name=task_name,
            task_type=task_type,
            required_inputs=self._content_inputs(text, task_type=task_type),
            confidence=0.9,
        )

    def _single_task_result(
        self,
        *,
        text: str,
        rule_name: str,
        intent_category: str,
        task_name: str,
        task_type: str,
        required_inputs: list[str],
        confidence: float,
        rule_priority: int | None = None,
    ) -> OperationRuleMatch:
        task = self.task_factory.create_task(
            task_name=task_name,
            task_type=task_type,
            required_inputs=required_inputs,
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=confidence,
        )
        return OperationRuleMatch(
            result=IntentAnalysisResult(
                original_text=text,
                intent_category=intent_category,
                tasks=[task],
                analysis_level=1,
                overall_confidence=confidence,
            ),
            rule_name=rule_name,
            rule_priority=rule_priority if rule_priority is not None else self.RULE_PRIORITIES.get(rule_name, 50),
        )

    def _select_best(self, candidates: list[OperationRuleMatch]) -> OperationRuleMatch | None:
        if not candidates:
            return None
        sort_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.result.tasks
                and candidate.result.tasks[0].task_type == "DATA_SORT"
            ),
            None,
        )
        filter_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.result.tasks
                and candidate.result.tasks[0].task_type == "DATA_FILTER"
            ),
            None,
        )
        if sort_candidate is not None and filter_candidate is not None:
            normalized = sort_candidate.result.original_text
            if re.search(
                r"(?:排序|排名|排行|排列|倒序|升序|降序).{0,10}"
                r"(?:筛选结果|过滤结果|查询结果|这批|这组)",
                normalized,
            ):
                return sort_candidate
        return max(candidates, key=lambda match: (match.rule_priority, match.result.overall_confidence))

    def _period_comparison_mode(self, text: str) -> tuple[str, str, str] | None:
        if not self._contains_any(text, ["比较", "对比", "变化", "差异", "趋势"]):
            return None
        current_first = re.search(
            r"(?:本季度|本月|本周|本期|当前周期).{0,10}"
            r"(?:与|和|及).{0,10}"
            r"(?:上季度|上月|上周|上期|上一周期|去年同期)",
            text,
        )
        previous_first = re.search(
            r"(?:去年同期|上年同期|去年同月|去年同季|上季度|上月|上个月|上周|上期|上一周期)"
            r".{0,12}(?:比较|对比|比|相比).{0,12}"
            r"(?:本季度|本月|本周|本期|当前周期)",
            text,
        )
        if current_first is None and previous_first is None:
            return None
        if re.search(r"去年同期|上年同期|去年同月|去年同季", text):
            return "DATA_ANALYSIS_YOY", "同比分析", "同比"
        return "DATA_ANALYSIS_MOM", "环比分析", "环比"

    def _is_sort_request(self, text: str) -> bool:
        if self._contains_any(text, ["排序", "排名", "排行", "排列", "倒序", "升序", "降序"]):
            return True
        return bool(
            re.search(r"(?:按|根据|以).{1,24}(?:从高到低|从低到高|从大到小|从小到大).{0,10}排(?:一下|一排|个序)?", text)
            or re.search(r"(?:从高到低|从低到高|从大到小|从小到大).{0,10}排(?:一下|一排|个序)?", text)
            or re.search(r"(?<!安)排(?:一下|一排|个序)", text)
        )

    def _is_list_artifact_request(self, text: str) -> bool:
        if not self._contains_any(text, ["清单", "名单", "列表"]):
            return False
        has_list_condition = self._contains_any(
            text,
            ["风险", "异常", "逾期", "超期", "未回款", "未付款", "低库存", "高价值", "重点", "流失"],
        )
        has_analysis_action = self._contains_any(text, ["分析", "诊断", "原因", "归因", "为什么", "为何"])
        return has_list_condition and not has_analysis_action

    def _data_inputs(self, text: str, *, operation: str) -> list[str]:
        inputs = [f"operation:{operation}"]
        if "销售数据" in text:
            inputs.append("data_source:销售数据")
        elif self._has_structured_data_source_object(text):
            inputs.append(f"data_source:{self._structured_data_source_object(text)}")
        elif "销售" in text:
            inputs.append("data_object:销售")
        else:
            data_object = self._data_object_from_text(text)
            if data_object:
                inputs.append(f"data_object:{data_object}")
        if self._has_classification_field(text):
            inputs.append("classification_field:已识别")
        if self._has_statistical_range(text):
            inputs.append("statistical_range:已识别")
        if self._has_summary_field(text):
            inputs.append("summary_field:已识别")
        return inputs

    def _has_structured_data_source_object(self, text: str) -> bool:
        return bool(self._structured_data_source_object(text))

    def _structured_data_source_object(self, text: str) -> str:
        for keyword in ["合同台账", "订单台账", "费用台账", "销售明细", "订单明细", "回款明细", "库存记录", "投诉记录", "发票清单"]:
            if keyword in text:
                return keyword
        return ""

    def _document_inputs(self, text: str) -> list[str]:
        inputs = []
        for keyword in ["Excel", "excel", "PDF", "pdf", "Word", "word", "电子表", "上传表", "表格", "合同", "发票", "附件", "文件"]:
            if keyword in text:
                inputs.append(f"file_type:{keyword}")
                break
        if self._has_document_source(text):
            inputs.append("file:已识别")
        if self._contains_any(text, ["字段", "结构", "目录"]):
            inputs.append("parse_target:结构字段")
        return inputs

    def _external_system_inputs(self, text: str) -> list[str]:
        inputs = []
        system_name = self._detect_system_name(text)
        if system_name:
            inputs.append(f"external_system:{system_name}")
        if self._contains_any(text, ["获取", "查询", "拉取", "拉"]):
            inputs.append("operation:fetch")
        elif self._contains_any(text, ["提交", "推送", "写入", "更新", "回传"]):
            inputs.append("operation:submit")
        return inputs

    def _digital_asset_inputs(self, text: str) -> list[str]:
        inputs = ["asset_type:凭证" if "凭证" in text else "asset_type:数字资产"]
        if self._contains_any(text, ["计算结果", "提成结果", "计提结果"]):
            inputs.append("source_result:计算结果")
        if self._has_statistical_range(text):
            inputs.append("period:已识别")
        return inputs

    def _multimedia_inputs(self, text: str) -> list[str]:
        inputs = []
        for keyword in ["图片", "海报", "配图", "封面", "视频", "音频", "语音", "宣传图"]:
            if keyword in text:
                inputs.append(f"media_type:{keyword}")
                break
        if not inputs and "多媒体" in text:
            inputs.append("media_type:多媒体")
        for keyword in ["新品", "产品", "活动", "会议", "销售", "品牌", "宣传"]:
            if keyword in text:
                inputs.append(f"topic:{keyword}")
                break
        return inputs

    def _workflow_inputs(self, text: str) -> list[str]:
        inputs = []
        for keyword in ["采购", "报销", "请假", "立项", "付款", "审批", "工单"]:
            if keyword in text:
                inputs.append(f"process_name:{keyword}")
                break
        if "我" in text:
            inputs.append("initiator:当前用户")
        return inputs

    def _monitoring_inputs(self, text: str) -> list[str]:
        inputs = []
        for keyword in ["库存", "销售额", "回款", "订单", "合同", "到期", "余额", "风险"]:
            if keyword in text:
                inputs.append(f"monitoring_object:{keyword}")
                break
        if self._has_monitoring_trigger_condition(text):
            inputs.append("trigger_condition:已识别")
        return inputs

    def _analytics_inputs(self, text: str, *, method: str) -> list[str]:
        inputs = [f"analysis_method:{method}"]
        analysis_object = self._analysis_object_from_text(text)
        if analysis_object:
            inputs.append(f"analysis_object:{analysis_object}")
        return inputs

    def _analysis_object_from_text(self, text: str) -> str:
        regional_demand = re.search(r"(桂中|华东|华南|华北|西南|[一-龥]{1,8}(?:区域|地区|门店|渠道)).{0,8}需求", text)
        if regional_demand is not None:
            return regional_demand.group(0).strip(" 的")
        for keyword in [
            "复购率",
            "经销商",
            "需求",
            "销售",
            "客户投诉",
            "投诉",
            "退款",
            "库存",
            "利润",
            "收入",
            "成本",
            "费用",
            "风险",
            "订单",
            "回款",
            "客户",
            "海报",
            "宣传图",
            "图片",
            "封面",
        ]:
            if keyword in text:
                return keyword
        return ""

    def _data_object_from_text(self, text: str) -> str | None:
        for keyword in ["合同台账", "合同清单", "客户列表", "客户名单", "订单列表", "库存记录", "投诉记录", "发票清单"]:
            if keyword in text:
                return keyword
        for keyword in ["台账", "清单", "列表", "记录", "明细"]:
            if keyword in text:
                return keyword
        return None

    def _calculation_inputs(self, text: str) -> list[str]:
        inputs = []
        if self._contains_any(text, ["政策", "规则", "公式"]):
            inputs.append("calculation_policy:已识别")
        if self._has_calculation_basis_hint(text):
            inputs.append("calculation_basis:销售数据")
            if self._contains_any(text, ["销售提成", "提成", "佣金"]):
                inputs.append("sales_data_source:销售数据")
        elif self._contains_any(text, ["费用", "奖金", "绩效", "税"]):
            inputs.append("calculation_basis:业务数据")
        if self._has_statistical_range(text):
            inputs.append("statistical_range:已识别")
            inputs.append("period:已识别")
        return inputs

    def _content_inputs(self, text: str, *, task_type: str) -> list[str]:
        inputs = []
        if task_type == "DOCUMENT_GENERATE":
            inputs.append("content_type:文档")
        elif task_type == "IMPROVEMENT_PLAN_GENERATE":
            inputs.append("content_type:方案")
        else:
            inputs.append("content_type:内容")
        for keyword in ["客户反馈", "客户意见", "用户反馈", "投诉反馈", "销售", "经营", "客户投诉", "会议", "通知", "报销", "产品"]:
            if keyword in text:
                inputs.append(f"topic:{keyword}")
                break
        return inputs

    def _has_classification_field(self, text: str) -> bool:
        return self._contains_any(text, ["各区域", "按区域", "区域", "产品", "客户", "供应商", "部门", "门店", "等级", "分层", "渠道", "分类"])

    def _has_statistical_range(self, text: str) -> bool:
        return self._contains_any(text, ["今天", "本周", "本月", "上月", "上个月", "今年", "去年", "季度"]) or bool(
            re.search(r"\d{4}年|\d{1,2}月", text),
        )

    def _has_summary_field(self, text: str) -> bool:
        return self._contains_any(text, ["复购率", "需求", "金额", "数量", "利润", "销售额", "提成", "收入", "总额", "合计"])

    def _has_monitoring_trigger_condition(self, text: str) -> bool:
        if self._contains_any(text, ["到期", "逾期", "超时", "超预算", "明天", "今天", "每周", "每天", "每月", "定时"]):
            return True

        comparator_pattern = r"(超过|低于|少于|高于|大于|小于|不低于|不高于)"
        threshold_pattern = r"(\d+(?:\.\d+)?|[一二三四五六七八九十百千万]+|阈值|目标|预算|安全值|账期)"
        return bool(re.search(comparator_pattern + r"\s*.{0,8}?" + threshold_pattern, text))

    def _has_data_source_hint(self, text: str) -> bool:
        return self._contains_any(text, ["销售数据", "销售明细", "这张表", "文件", "数据库", "系统", "报表"])

    def _has_calculation_basis_hint(self, text: str) -> bool:
        return self._contains_any(text, ["销售数据", "销售明细", "数据", "明细", "这张表", "文件", "数据库", "系统", "报表"])

    def _has_document_source(self, text: str) -> bool:
        return self._contains_any(text.lower(), ["excel", "pdf", "word", "电子表", "上传表", "表格", "文档", "附件", "合同", "发票", "单据", "文件", "上传"])

    def _is_short_commission_phrase(self, text: str) -> bool:
        if not self._contains_any(text, ["销售提成", "提成", "佣金"]):
            return False

        content_keywords = ["报告", "文档", "通知", "说明", "方案", "总结", "文案", "邮件", "话术", "材料", "计划", "海报", "图片", "视频"]
        if self._contains_any(text, content_keywords):
            return False

        return len(text.strip()) <= 12 or self._contains_any(text, ["销售提成", "提成", "佣金"])

    def _detect_system_name(self, text: str) -> str | None:
        for keyword in ["CRM", "crm", "ERP", "erp", "OA", "oa", "SAP", "sap", "金蝶", "用友", "飞书", "钉钉", "企业微信", "财务系统", "业务系统", "外部系统"]:
            if keyword in text:
                return keyword.upper() if keyword.isascii() else keyword
        return None

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _user_input(self, text: str | dict[str, Any]) -> str:
        if isinstance(text, dict):
            return str(text.get("user_input") or "")
        return text
