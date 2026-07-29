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

        if self._is_sales_commission_voucher_request(normalized):
            return self._sales_commission_voucher(normalized)

        if all(keyword in normalized for keyword in ["客户投诉", "改进方案"]):
            return self._complaint_improvement_plan(normalized)

        return None

    def _is_sales_commission_voucher_request(self, text: str) -> bool:
        has_sales = "销售" in text
        has_commission = any(keyword in text for keyword in ["提成", "佣金", "奖金"])
        has_voucher = "凭证" in text
        has_data_step = any(keyword in text for keyword in ["整理", "获取", "查询", "拉取", "明细", "数据"])
        has_calculation_step = any(keyword in text for keyword in ["算", "计算", "核算", "测算", "计提"])
        return has_sales and has_commission and has_voucher and (has_data_step or has_calculation_step)

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
