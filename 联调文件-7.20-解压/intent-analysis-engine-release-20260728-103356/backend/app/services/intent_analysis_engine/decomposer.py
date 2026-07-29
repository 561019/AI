import re

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.intent_analysis_engine.task_factory import TaskFactory


class TaskDecomposer:
    """Deterministic decomposition for known multi-action enterprise requests."""

    def __init__(self, task_factory: TaskFactory) -> None:
        self.task_factory = task_factory

    def decompose(self, text: str) -> IntentAnalysisResult | None:
        normalized = text.strip()
        if not normalized:
            return None

        if self._is_metric_change_diagnostic_request(normalized):
            return self._metric_change_diagnostic(normalized)

        if self._is_policy_commission_voucher_request(normalized):
            return self._policy_commission_voucher(normalized)

        if self._is_sales_commission_voucher_request(normalized):
            return self._sales_commission_voucher(normalized)

        if self._is_complaint_improvement_plan_request(normalized):
            return self._complaint_improvement_plan(normalized)

        return None

    def _is_sales_commission_voucher_request(self, text: str) -> bool:
        has_sales = "销售" in text
        has_commission = any(keyword in text for keyword in ["提成", "佣金", "奖金"])
        has_voucher = "凭证" in text
        has_data_step = any(keyword in text for keyword in ["整理", "获取", "查询", "拉取", "明细", "数据"])
        has_calculation_step = any(keyword in text for keyword in ["算", "计算", "核算", "测算", "计提"])
        return has_sales and has_commission and has_voucher and (has_data_step or has_calculation_step)

    def _is_policy_commission_voucher_request(self, text: str) -> bool:
        has_policy_inquiry = self._has_policy_inquiry_clause(text)
        has_sales_commission = "销售" in text and any(keyword in text for keyword in ["提成", "佣金", "奖金"])
        has_voucher = "凭证" in text
        has_calculation_step = any(keyword in text for keyword in ["算", "计算", "核算", "测算", "计提"])
        return has_policy_inquiry and has_sales_commission and has_voucher and has_calculation_step

    def _has_policy_inquiry_clause(self, text: str) -> bool:
        for clause in re.split(r"[，,。；;！？!?\n]+", text):
            clause = clause.strip()
            if not clause:
                continue
            has_policy = any(keyword in clause for keyword in ["政策", "制度", "规则", "标准"])
            has_inquiry = any(keyword in clause for keyword in ["查询", "了解", "问", "说明", "解释", "怎么", "如何", "什么"])
            has_calculation = any(keyword in clause for keyword in ["算", "计算", "核算", "测算", "计提"])
            if has_policy and has_inquiry and not has_calculation:
                return True
        return False

    def _is_complaint_improvement_plan_request(self, text: str) -> bool:
        has_complaint = all(keyword in text for keyword in ["客户投诉", "改进方案"])
        if not has_complaint:
            return False

        has_preparation_step = any(keyword in text for keyword in ["整理", "归集", "归类", "归档"])
        has_step_connector = any(keyword in text for keyword in ["，", ",", "并", "然后", "再", "最后"])
        return has_preparation_step and has_step_connector

    def _is_metric_change_diagnostic_request(self, text: str) -> bool:
        asks_reason = bool(
            re.search(r"为什么|为何|啥原因|什么原因|原因(?:是|在|出在)|归因|导致", text)
            or (re.search(r"同比|环比", text) and re.search(r"原因|归因", text))
        )
        has_change = bool(re.search(r"下降|下滑|降低|减少|变少|走低|降(?:了)?|上升|增长|增加|变高", text))
        has_metric = bool(
            re.search(
                r"复购率|转化率|留存率|客单价|销售额|销量|收入|利润|成本|费用|订单|需求|库存|回款|指标|经销商",
                text,
            )
            or re.search(r"(?:[一-龥]{1,12}(?:率|额|量)|订单数|客户数).{0,8}(?:下降|上升|增长|减少)", text)
        )
        return asks_reason and has_change and has_metric

    def _sales_commission_voucher(self, text: str) -> IntentAnalysisResult:
        task1 = self.task_factory.create_task(
            task_name="获取销售明细",
            task_type="DATA_QUERY_FETCH",
            required_inputs=self._sales_detail_inputs(text),
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=0.93,
        )
        task2 = self.task_factory.create_task(
            task_name="根据政策计算销售提成",
            task_type="RULE_CALCULATION_COMMISSION",
            required_inputs=self._sales_commission_inputs(text),
            missing_inputs=[],
            dependencies=[task1.task_id],
            execution_order=2,
            confidence=0.91,
        )
        task3 = self.task_factory.create_task(
            task_name="生成计提凭证",
            task_type="DIGITAL_ASSET_ACCRUAL_VOUCHER",
            required_inputs=["asset_type:计提凭证", "source_result:销售提成计算结果"],
            missing_inputs=[],
            dependencies=[task2.task_id],
            execution_order=3,
            confidence=0.9,
        )
        return self._result(
            text=text,
            intent_category="规则计算型",
            tasks=[task1, task2, task3],
            analysis_level=3,
        )

    def _policy_commission_voucher(self, text: str) -> IntentAnalysisResult:
        task1 = self.task_factory.create_task(
            task_name="智能问答",
            task_type="QUESTION_ANSWER",
            required_inputs=[f"question:{self._policy_question(text)}"],
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=0.93,
        )
        task2 = self.task_factory.create_task(
            task_name="计算销售提成",
            task_type="RULE_CALCULATION_COMMISSION",
            required_inputs=[],
            missing_inputs=[],
            dependencies=[task1.task_id],
            execution_order=2,
            confidence=0.9,
        )
        task3 = self.task_factory.create_task(
            task_name="生成计提凭证",
            task_type="DIGITAL_ASSET_ACCRUAL_VOUCHER",
            required_inputs=["asset_type:计提凭证", "source_result:销售提成计算结果"],
            missing_inputs=[],
            dependencies=[task2.task_id],
            execution_order=3,
            confidence=0.89,
        )
        return self._result(
            text=text,
            intent_category="复合任务型",
            tasks=[task1, task2, task3],
            analysis_level=3,
        )

    def _complaint_improvement_plan(self, text: str) -> IntentAnalysisResult:
        task1 = self.task_factory.create_task(
            task_name="投诉信息整理",
            task_type="COMPLAINT_INFORMATION_ORGANIZE",
            required_inputs=["data_object:客户投诉"],
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=0.9,
        )
        task2 = self.task_factory.create_task(
            task_name="问题分析",
            task_type="DATA_ANALYSIS_PROBLEM",
            required_inputs=["analysis_object:客户投诉", "analysis_method:问题分析"],
            missing_inputs=[],
            dependencies=[task1.task_id],
            execution_order=2,
            confidence=0.88,
        )
        task3 = self.task_factory.create_task(
            task_name="方案生成",
            task_type="IMPROVEMENT_PLAN_GENERATE",
            required_inputs=["topic:客户投诉改进方案"],
            missing_inputs=[],
            dependencies=[task2.task_id],
            execution_order=3,
            confidence=0.87,
        )
        return self._result(
            text=text,
            intent_category="内容生成型",
            tasks=[task1, task2, task3],
            analysis_level=3,
        )

    def _metric_change_diagnostic(self, text: str) -> IntentAnalysisResult:
        metric = self._metric_name(text)
        period = self._period_name(text)
        scope = self._data_scope_name(text)
        direction = self._change_direction(text)
        query_inputs = [
            f"data_object:{self._join_scope_metric(scope, metric)}",
            "data_source:metric_context",
            "operation:查询获取",
        ]
        if period:
            query_inputs.append(f"statistical_range:{period}")
        task1 = self.task_factory.create_task(
            task_name=f"查询{self._join_scope_metric(scope, metric)}数据",
            task_type="DATA_QUERY_FETCH",
            required_inputs=query_inputs,
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=0.91,
        )

        tasks: list[TaskItem] = [task1]
        previous_task_id = task1.task_id
        next_order = 2
        if "同比" in text or "环比" in text:
            compare_task_type = "DATA_ANALYSIS_YOY" if "同比" in text else "DATA_ANALYSIS_MOM"
            compare_name = "同比分析" if compare_task_type == "DATA_ANALYSIS_YOY" else "环比分析"
            compare_inputs = [
                f"analysis_object:{metric}",
                f"summary_field:{metric}",
                "data_source:dependency_data",
            ]
            if period:
                compare_inputs.append(f"statistical_range:{period}")
            task2 = self.task_factory.create_task(
                task_name=f"{compare_name}{metric}变化",
                task_type=compare_task_type,
                required_inputs=compare_inputs,
                missing_inputs=[],
                dependencies=[task1.task_id],
                execution_order=next_order,
                confidence=0.9,
            )
            tasks.append(task2)
            previous_task_id = task2.task_id
            next_order += 1

        breakdown_inputs = [
            f"summary_field:{metric}",
            "classification_field:经销商" if "经销商" in text else "classification_field:业务维度",
            "data_source:dependency_data",
        ]
        if period:
            breakdown_inputs.append(f"statistical_range:{period}")
        if scope:
            breakdown_inputs.append(f"data_scope:{scope}")
        task3 = self.task_factory.create_task(
            task_name=f"汇总{metric}{direction}贡献",
            task_type="DATA_ANALYSIS_GROUP_SUM",
            required_inputs=breakdown_inputs,
            missing_inputs=[],
            dependencies=[previous_task_id],
            execution_order=next_order,
            confidence=0.88,
        )
        tasks.append(task3)
        next_order += 1

        task4 = self.task_factory.create_task(
            task_name=f"分析{metric}{direction}原因",
            task_type="DATA_ANALYSIS_PROBLEM",
            required_inputs=[
                f"analysis_object:{metric}{direction}",
                "analysis_method:原因分析",
                "data_source:dependency_data",
            ],
            missing_inputs=[],
            dependencies=[task3.task_id],
            execution_order=next_order,
            confidence=0.88,
        )
        tasks.append(task4)
        return self._result(
            text=text,
            intent_category="数据分析型",
            tasks=tasks,
            analysis_level=3,
        )

    def _metric_name(self, text: str) -> str:
        for keyword in ("复购率", "转化率", "留存率", "客单价", "销售额", "销量", "收入", "利润", "成本", "费用", "订单", "需求", "库存", "回款"):
            if keyword in text:
                return keyword
        rate_match = re.search(r"([一-龥]{1,12}率)", text)
        if rate_match is not None:
            return rate_match.group(1)
        return "业务指标"

    def _period_name(self, text: str) -> str:
        for pattern in (
            r"本季度",
            r"上季度",
            r"下季度",
            r"第[一二三四1-4]季度",
            r"本月",
            r"上月",
            r"上个月",
            r"\d{1,2}月",
            r"[一二三四五六七八九十]+月",
            r"\d{4}年(?:\d{1,2}月)?",
        ):
            match = re.search(pattern, text)
            if match is not None:
                return match.group(0)
        return ""

    def _data_scope_name(self, text: str) -> str:
        for pattern in (r"[一二三四五六七八九十\d]+月前十名经销商", r"前十名经销商", r"经销商", r"桂中", r"华东区域|华南区域|华北区域|西南区域"):
            match = re.search(pattern, text)
            if match is not None:
                return match.group(0)
        return ""

    def _change_direction(self, text: str) -> str:
        if re.search(r"上升|增长|增加|变高", text):
            return "上升"
        if re.search(r"波动|异常", text):
            return "波动"
        return "下降"

    def _join_scope_metric(self, scope: str, metric: str) -> str:
        if scope and metric not in scope:
            return f"{scope}{metric}"
        return scope or metric

    def _sales_detail_inputs(self, text: str) -> list[str]:
        inputs = ["data_object:销售明细", "data_source:销售明细", "operation:查询获取"]
        if "上个月" in text or "上月" in text:
            inputs.append("period:上个月")
            inputs.append("statistical_range:上个月")
        if "各区域" in text or "区域" in text:
            inputs.append("classification_field:区域")
        return inputs

    def _sales_commission_inputs(self, text: str) -> list[str]:
        inputs = [
            "calculation_basis:销售明细",
            "calculation_policy:销售提成政策",
            "sales_data_source:销售明细",
        ]
        if "上个月" in text or "上月" in text:
            inputs.append("statistical_range:上个月")
        return inputs

    def _policy_question(self, text: str) -> str:
        first_clause = text.split("，", 1)[0].split(",", 1)[0].strip()
        if any(marker in first_clause for marker in ("什么", "怎么", "如何", "为什么")):
            return first_clause
        return f"{first_clause}是什么"

    def _result(
        self,
        *,
        text: str,
        intent_category: str,
        tasks: list[TaskItem],
        analysis_level: int,
    ) -> IntentAnalysisResult:
        return IntentAnalysisResult(
            original_text=text,
            intent_category=intent_category,
            tasks=tasks,
            clarification_required=False,
            clarification_questions=[],
            analysis_level=analysis_level,
            overall_confidence=min(task.confidence for task in tasks),
        )
