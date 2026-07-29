from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem, TaskStatus
from app.services.intent_analysis_engine.conflict.rules import conflict_missing_input
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog
from app.services.intent_analysis_engine.task_schema.required_inputs import (
    input_is_provided,
    provided_input_keys,
)
from app.services.intent_analysis_engine.task_schema.validator import TaskTypeSchemaCatalog


QUESTION_BY_INPUT = {
    "classification_field": "请确认统计维度（例如区域、产品、客户）。",
    "statistical_range": "请确认统计范围（例如时间范围、组织范围）。",
    "summary_field": "请确认汇总字段（例如金额、数量、利润）。",
    "data_source": "请提供数据来源（例如数据库、文件或业务系统）。",
    "data_object": "请确认数据对象。",
    "sales_data_source": "请提供销售数据来源（例如数据库、文件或业务系统）。",
    "calculation_policy": "请提供计算规则或适用政策。",
    "calculation_basis": "请提供计算依据或基础数据。",
    "file": "请提供需要解析的文件或附件。",
    "external_system": "请确认目标外部系统。",
    "operation": "请确认需要执行的系统操作。",
    "analysis_object": "请确认分析对象。",
    "analysis_method": "请确认分析方法。",
    "question": "请提供需要回答的问题。",
    "topic": "请确认内容主题。",
    "content_type": "请确认需要生成的内容类型。",
    "document_type": "请确认需要生成的文档类型。",
    "media_type": "请确认需要生成的媒体类型。",
    "process_name": "请确认需要办理的流程名称。",
    "initiator": "请确认流程发起人。",
    "monitoring_object": "请确认监控对象。",
    "trigger_condition": "请确认触发提醒的条件。",
    "asset_type": "请确认数字资产或凭证类型。",
    "source_result": "请提供生成数字资产所依据的来源结果。",
}


InputState = Literal["provided", "missing", "uncertain", "conflict"]


class InputStateDebugDetail(BaseModel):
    task_id: str
    task_type: str
    input_name: str
    state: InputState
    validator_rule: str
    source: str
    input_source: Literal["user_input", "context", "unknown"] | None = None
    question: str | None = None


class MissingInputDebugDetail(BaseModel):
    task_id: str
    task_type: str
    input_name: str
    validator_rule: str
    source: str
    question: str
    state: Literal["missing", "uncertain", "conflict"] = "missing"
    required_inputs_source: str = "task_type_schema"


class TaskClarification(BaseModel):
    task_id: str
    task_type: str
    missing_inputs: list[str] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    status: TaskStatus = "ready"
    blocked_reason: str | None = None


class InputValidationResult(BaseModel):
    clarification_required: bool = False
    provided_inputs: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    uncertain_inputs: list[str] = Field(default_factory=list)
    conflict_inputs: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    task_clarifications: list[TaskClarification] = Field(default_factory=list)
    input_state_details: list[InputStateDebugDetail] = Field(default_factory=list)
    missing_input_details: list[MissingInputDebugDetail] = Field(default_factory=list)
    required_inputs_source: str = "task_type_schema"


class TaskInputValidator:
    """Validates task inputs after task construction, regardless of matcher source."""

    def __init__(
        self,
        *,
        registry: FunctionRegistryCatalog,
        schema_catalog: TaskTypeSchemaCatalog | None = None,
    ) -> None:
        self.registry = registry
        self.schema_catalog = schema_catalog or TaskTypeSchemaCatalog()

    def apply(
        self,
        result: IntentAnalysisResult,
        *,
        source_text: str | None = None,
    ) -> tuple[IntentAnalysisResult, InputValidationResult]:
        validation_text = result.original_text if source_text is None else source_text
        validated_tasks = self.validate_task_list(result.tasks, source_text=validation_text)
        validation_result = self.validate_tasks(validated_tasks, source_text=validation_text)
        return (
            result.model_copy(
                update={
                    "tasks": validated_tasks,
                    "clarification_required": validation_result.clarification_required,
                    "global_clarification_required": validation_result.clarification_required,
                    "clarification_questions": validation_result.clarification_questions,
                },
            ),
            validation_result,
        )

    def validate_task(self, task: TaskItem, *, source_text: str | None = None) -> TaskItem:
        states = self._input_states_for_task(task, source_text=source_text or "")
        unresolved_inputs = [
            detail.input_name
            for detail in states
            if detail.state != "provided"
        ]
        for missing_input in self._blocking_conflict_missing_inputs(task):
            if missing_input not in unresolved_inputs:
                unresolved_inputs.append(missing_input)
        questions = self._questions_from_details(states)
        for question in self._blocking_conflict_questions(task):
            if question not in questions:
                questions.append(question)
        return task.model_copy(
            update={
                "missing_inputs": unresolved_inputs,
                "clarification_required": bool(unresolved_inputs),
                "clarification_questions": questions,
                "status": "needs_clarification" if unresolved_inputs else "ready",
                "blocked_reason": self._blocking_conflict_reason(task) if unresolved_inputs else None,
            }
        )

    def validate_task_list(
        self,
        tasks: list[TaskItem],
        *,
        source_text: str | None = None,
    ) -> list[TaskItem]:
        tasks = self._inherit_dependency_inputs(tasks)
        validated = [
            self.validate_task(task, source_text=source_text or "")
            for task in tasks
        ]
        return self._apply_dependency_status(validated)

    def validate_tasks(
        self,
        tasks: list[TaskItem],
        *,
        source_text: str | None = None,
    ) -> InputValidationResult:
        state_details = [
            detail
            for task in tasks
            for detail in self._input_states_for_task(task, source_text=source_text or "")
        ]
        unresolved_details = [detail for detail in state_details if detail.state != "provided"]
        conflict_missing_inputs = [
            missing_input
            for task in tasks
            for missing_input in self._blocking_conflict_missing_inputs(task)
        ]
        clarification_questions: list[str] = []
        for task in tasks:
            if not task.clarification_required:
                continue
            for question in task.clarification_questions:
                if question not in clarification_questions:
                    clarification_questions.append(question)
        return InputValidationResult(
            clarification_required=bool(unresolved_details or conflict_missing_inputs),
            provided_inputs=self._names_for_state(state_details, "provided"),
            missing_inputs=self._merge_unique(
                self._names_for_state(state_details, "missing"),
                conflict_missing_inputs,
            ),
            uncertain_inputs=self._names_for_state(state_details, "uncertain"),
            conflict_inputs=self._merge_unique(
                self._names_for_state(state_details, "conflict"),
                conflict_missing_inputs,
            ),
            clarification_questions=clarification_questions,
            task_clarifications=[
                TaskClarification(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    missing_inputs=task.missing_inputs,
                    clarification_required=task.clarification_required,
                    clarification_questions=task.clarification_questions,
                    status=task.status,
                    blocked_reason=task.blocked_reason,
                )
                for task in tasks
            ],
            input_state_details=state_details,
            missing_input_details=[
                MissingInputDebugDetail(
                    task_id=detail.task_id,
                    task_type=detail.task_type,
                    input_name=detail.input_name,
                    validator_rule=detail.validator_rule,
                    source=detail.source,
                    question=detail.question or QUESTION_BY_INPUT.get(
                        detail.input_name,
                        f"请补充 {detail.input_name}。",
                    ),
                    state=detail.state,
                    required_inputs_source=detail.source,
                )
                for detail in unresolved_details
            ],
            required_inputs_source="task_type_schema",
        )

    def _questions_from_details(self, details: list[InputStateDebugDetail]) -> list[str]:
        questions: list[str] = []
        for detail in details:
            if detail.state == "provided" or not detail.question:
                continue
            if detail.question not in questions:
                questions.append(detail.question)
        return questions

    def _apply_dependency_status(self, tasks: list[TaskItem]) -> list[TaskItem]:
        unresolved_task_ids = {
            task.task_id
            for task in tasks
            if task.clarification_required or task.status == "waiting_dependency"
        }
        updated: list[TaskItem] = []
        for task in tasks:
            blocking_dependencies = [
                dependency
                for dependency in task.dependencies
                if dependency in unresolved_task_ids
            ]
            if blocking_dependencies:
                updated.append(
                    task.model_copy(
                        update={
                            "status": "waiting_dependency",
                            "blocked_reason": f"waiting_for_dependency:{blocking_dependencies[0]}",
                        }
                    )
                )
            else:
                blocked_reason = self._blocking_conflict_reason(task) if task.clarification_required else None
                updated.append(
                    task.model_copy(
                        update={
                            "status": "needs_clarification" if task.clarification_required else "ready",
                            "blocked_reason": blocked_reason,
                        }
                    )
                )

        if any(original.status != current.status for original, current in zip(tasks, updated, strict=True)):
            return self._apply_dependency_status(updated)
        return updated

    def _blocking_conflict_missing_inputs(self, task: TaskItem) -> list[str]:
        return [
            conflict_missing_input(str(self._conflict_value(conflict, "conflict_type")))
            for conflict in task.conflicts
            if self._conflict_value(conflict, "resolution_status") == "needs_clarification"
        ]

    def _blocking_conflict_questions(self, task: TaskItem) -> list[str]:
        questions: list[str] = []
        for conflict in task.conflicts:
            if self._conflict_value(conflict, "resolution_status") != "needs_clarification":
                continue
            question = self._conflict_value(conflict, "clarification_question")
            if isinstance(question, str) and question and question not in questions:
                questions.append(question)
        return questions

    def _blocking_conflict_reason(self, task: TaskItem) -> str | None:
        for conflict in task.conflicts:
            if self._conflict_value(conflict, "resolution_status") == "needs_clarification":
                return f"conflict:{self._conflict_value(conflict, 'conflict_type')}"
        return None

    def _conflict_value(self, conflict: object, field: str) -> object:
        if isinstance(conflict, dict):
            return conflict.get(field)
        return getattr(conflict, field, None)

    def _merge_unique(self, first: list[str], second: list[str]) -> list[str]:
        merged = list(first)
        for value in second:
            if value not in merged:
                merged.append(value)
        return merged

    def _inherit_dependency_inputs(self, tasks: list[TaskItem]) -> list[TaskItem]:
        by_id = {task.task_id: task for task in tasks}
        updated: list[TaskItem] = []
        for task in tasks:
            additions: list[str] = []
            dependency_tasks = [
                by_id[dependency_id]
                for dependency_id in task.dependencies
                if dependency_id in by_id
            ]
            if task.task_type == "RULE_CALCULATION_COMMISSION" and any(
                dependency.task_type == "DATA_QUERY_FETCH"
                for dependency in dependency_tasks
            ):
                if not self._has_input(task.required_inputs, "sales_data_source"):
                    additions.append("sales_data_source:dependency_data")
                if not self._has_input(task.required_inputs, "statistical_range"):
                    additions.append("statistical_range:dependency_data_scope")
            if task.task_type == "DATA_AGGREGATION_SUMMARY" and any(
                dependency.task_type in {"DATA_QUERY_FETCH", "EXTERNAL_DATA_FETCH"}
                for dependency in dependency_tasks
            ):
                if not self._has_input(task.required_inputs, "statistical_range"):
                    additions.append("statistical_range:dependency_data_scope")
                task_text = f"{task.task_description} {task.object}"
                if (
                    not self._has_input(task.required_inputs, "summary_field")
                    and re.search(r"(?:风险|等级|层级|tier|risk|count|数量|个数)", task_text, flags=re.IGNORECASE)
                ):
                    additions.append("summary_field:count")
            updated.append(
                task.model_copy(update={"required_inputs": [*task.required_inputs, *additions]})
                if additions
                else task
            )
        return updated

    def _has_input(self, values: list[str], input_name: str) -> bool:
        return self._is_provided(input_name, self._provided_input_keys(values))

    def required_inputs_for_task(self, task_type: str) -> list[str]:
        return self.schema_catalog.required_inputs_for(task_type)

    def required_inputs_source_for_task(self, task_type: str) -> str:
        return self.schema_catalog.required_inputs_source_for(task_type)

    def _provided_input_keys(self, required_inputs: list[str]) -> set[str]:
        return provided_input_keys(required_inputs)

    def _is_provided(self, required_input: str, provided_inputs: set[str]) -> bool:
        return input_is_provided(required_input, provided_inputs)

    def _input_states_for_task(self, task: TaskItem, *, source_text: str) -> list[InputStateDebugDetail]:
        schema_validation = self.schema_catalog.validate(
            task.task_type,
            task.required_inputs,
        )
        input_names = list(schema_validation.required_inputs)
        provided_inputs = self._provided_input_keys(task.required_inputs)
        source = schema_validation.required_inputs_source
        return [
            self._state_detail(
                task=task,
                input_name=input_name,
                provided_inputs=provided_inputs,
                source_text=source_text,
                source=source,
                input_source=(
                    self._provided_input_source(task.required_inputs, input_name)
                    or ("user_input" if self._source_provides_input(input_name, source_text) else None)
                ),
            )
            for input_name in input_names
        ]

    def _state_detail(
        self,
        *,
        task: TaskItem,
        input_name: str,
        provided_inputs: set[str],
        source_text: str,
        source: str,
        input_source: Literal["user_input", "context", "unknown"] | None,
    ) -> InputStateDebugDetail:
        source_state = self._state_from_source(input_name, source_text)
        if source_state is not None:
            state: InputState = source_state
        elif self._is_provided(input_name, provided_inputs):
            state = "provided"
        elif self._source_provides_input(input_name, source_text):
            state = "provided"
        else:
            state = "missing"
        return InputStateDebugDetail(
                task_id=task.task_id,
                task_type=task.task_type,
                input_name=input_name,
                state=state,
                validator_rule=f"required_input_{state}",
                source=source,
                input_source=input_source if state == "provided" else None,
                question=(
                    None
                    if state == "provided"
                    else self._question_for(input_name, state=state, source_text=source_text)
                ),
            )

    def _provided_input_source(
        self,
        values: list[str],
        input_name: str,
    ) -> Literal["user_input", "context", "unknown"] | None:
        provided_keys = self._provided_input_keys(values)
        if not self._is_provided(input_name, provided_keys):
            return None
        for value in values:
            text = str(value)
            key = text.split(":", 1)[0].strip()
            if not input_is_provided(input_name, {key}):
                continue
            lowered = text.lower()
            if "context" in lowered or "dependency" in lowered or "task:" in lowered:
                return "context"
            return "user_input"
        return "unknown"

    def _state_from_source(
        self,
        input_name: str,
        source_text: str,
    ) -> Literal["uncertain", "conflict"] | None:
        if not source_text:
            return None
        if input_name == "calculation_policy" and re.search(
            r"(?:换|换个|换一个|另|另一个|新的|新).{0,8}(?:口径|规则|政策)",
            source_text,
        ) and not re.search(r"20\d{2}|现行|当前|新版|今年|去年|调整后", source_text):
            return "uncertain"
        if input_name == "calculation_policy" and (
            re.search(r"(?:不太确定|不确定|不知道|尚未确定).{0,80}(?:提成)?(?:政策|规则)", source_text)
            or re.search(r"(?:提成)?(?:政策|规则).{0,40}(?:需要确认|尚未明确|没有明确|不明确)", source_text)
        ):
            return "uncertain"
        if input_name in {"sales_data_source", "data_source"} and re.search(
            r"(?:销售数据|数据).{0,30}(?:到底|究竟)?(?:使用|采用).{0,35}(?:财务系统|销售系统|业务系统|CRM|ERP).{0,35}(?:还是|或).{0,35}(?:系统|CRM|ERP)",
            source_text,
            flags=re.IGNORECASE,
        ):
            return "conflict"
        if input_name in {"sales_data_source", "data_source"} and re.search(
            r"(?:数据来源|资料.{0,12}(?:存放|来自)).{0,30}(?:不清楚|不确定|需要确认|尚未明确)",
            source_text,
        ):
            return "uncertain"
        if input_name == "calculation_object" and self._has_calculation_object_uncertainty(source_text):
            return "uncertain"
        if input_name == "statistical_range" and re.search(
            r"(?:具体)?(?:截止日期|截止时间|数据截止日).{0,24}(?:需要确认|不确定|尚未明确|没有明确)",
            source_text,
        ):
            return "uncertain"
        return None

    def _has_calculation_object_uncertainty(self, source_text: str) -> bool:
        return bool(
            re.search(
                r"(?:销售提成)?(?:计算对象|计算范围).{0,60}(?:没有明确|未明确|不明确|不确定|需要确认|还是|或)",
                source_text,
            )
        )

    def _question_for(self, input_name: str, *, state: InputState, source_text: str) -> str:
        if input_name == "calculation_policy" and state in {"uncertain", "conflict"}:
            return "请确认销售提成适用的政策版本（去年版或今年调整版）。"
        if input_name in {"sales_data_source", "data_source"} and state in {"uncertain", "conflict"}:
            return "请确认销售数据来源（财务系统或销售系统，以哪个为准）。"
        if input_name == "calculation_object":
            return "请确认销售提成的计算对象（全部销售人员或指定区域人员）。"
        if input_name == "statistical_range" and "截止" in source_text:
            return "请确认今年截至目前数据的最终截止日期。"
        return QUESTION_BY_INPUT.get(input_name, f"请补充 {input_name}。")

    def _source_provides_input(self, input_name: str, source_text: str) -> bool:
        if not source_text:
            return False
        if input_name == "document_type":
            return bool(
                re.search(r"(?:报告|报表|文档|通知|邮件|方案|计划|材料|周报|日报|月报|季报|复盘|PPT|ppt|memo|report|review)", source_text, flags=re.IGNORECASE)
                or re.search(r"(?:生成|输出|形成|整理|准备|撰写|制作).{0,20}材料", source_text)
            )
        if input_name == "calculation_policy":
            return bool(re.search(r"(?:20\d{2}.{0,8})?(?:规则|政策|公式|口径|核算口径|计算口径)", source_text))
        if input_name == "statistical_range":
            return bool(
                re.search(
                    r"(?:今天|本周|本月|上月|上个月|今年|去年|本年|本年度|全年|季度|下月|Q[1-4]|20\d{2}年?)",
                    source_text,
                    flags=re.IGNORECASE,
                )
            )
        if input_name == "summary_field":
            return bool(re.search(r"(?:金额|数量|利润|销售额|收入|提成|总额|合计)", source_text))
        if input_name == "data_source":
            return bool(
                re.search(r"(?:CRM|ERP|OA|SAP|系统|数据库|文件|附件|表格)", source_text, flags=re.IGNORECASE)
                or re.search(r"(?:报表|数据表|明细表|台账文件|清单文件)", source_text)
            )
        if input_name == "external_system":
            return bool(re.search(r"\b(?:CRM|ERP|OA|SAP)\b|财务系统|业务系统", source_text, flags=re.IGNORECASE))
        if input_name == "process_name":
            normalized = re.sub(r"\s+", "", source_text.strip(" ，,。；;！？!?"))
            if re.fullmatch(r"(?:帮我|请)?(?:办理|处理|发起|启动|创建|推进|走)?(?:一下|一个|下)?(?:业务)?(?:流程|审批|工单|申请)", normalized):
                return False
            return bool(
                re.search(r"(?:流程|审批|工单|申请|准入|报销|付款|合同|立项)", source_text)
                and not re.search(r"(?:不需要|不用|不要|暂不|先不).{0,8}(?:流程|审批|工单|申请)", source_text)
            )
        if input_name == "analysis_object":
            return self._has_analysis_object(source_text)
        if input_name == "topic":
            return self._has_content_topic(source_text)
        if input_name == "trigger_condition":
            return bool(self._has_trigger_condition(source_text))
        return False

    def _has_trigger_condition(self, source_text: str) -> bool:
        if re.search(r"(?:到期|逾期|每天|每周|每月|定时)", source_text):
            return True
        return bool(
            re.search(
                r"(?:超过|低于|少于|高于|大于|小于|不低于|不高于)\s*.{0,12}?(?:\d+|目标|阈值|预算|账期|安全线|红线|警戒线|上限|下限|水位)",
                source_text,
            )
        )

    def _has_analysis_object(self, source_text: str) -> bool:
        if re.search(
            r"(?:客户|渠道|门店|供应链|库存|订单|回款|投诉|退款|续约|经营|销售|利润|收入|线索|风险|partner|customer|renewal|sales|revenue|channel|risk)",
            source_text,
            flags=re.IGNORECASE,
        ):
            return True
        return bool(
            re.search(
                r"(?:下滑|下降|增长|异常|变差|质量|健康度|投入产出|qualified leads|health|signals)",
                source_text,
                flags=re.IGNORECASE,
            )
        )

    def _has_content_topic(self, source_text: str) -> bool:
        return bool(
            re.search(
                r"(?:客户|渠道|门店|供应链|库存|订单|回款|投诉|续约|经营|销售|利润|收入|风险|整改|改进|remediation|renewal|customer|manager|operating|review)",
                source_text,
                flags=re.IGNORECASE,
            )
        )

    def _names_for_state(
        self,
        details: list[InputStateDebugDetail],
        state: InputState,
    ) -> list[str]:
        names: list[str] = []
        for detail in details:
            if detail.state == state and detail.input_name not in names:
                names.append(detail.input_name)
        return names
