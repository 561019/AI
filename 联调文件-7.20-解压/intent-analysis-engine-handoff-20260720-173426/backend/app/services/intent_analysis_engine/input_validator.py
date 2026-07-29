from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem, TaskStatus
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog
from app.services.semantic.capability_config import SemanticCapabilityCatalog


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
    "media_type": "请确认需要生成的媒体类型。",
    "process_name": "请确认需要办理的流程名称。",
    "initiator": "请确认流程发起人。",
    "monitoring_object": "请确认监控对象。",
    "trigger_condition": "请确认触发提醒的条件。",
    "asset_type": "请确认数字资产或凭证类型。",
    "source_result": "请提供生成数字资产所依据的来源结果。",
}


PROVIDED_INPUT_ALIASES = {
    "file": ["file", "file_type", "source_file"],
    "statistical_range": ["statistical_range", "period", "time_range", "date_range"],
    "sales_data_source": ["sales_data_source", "data_source"],
    "data_source": ["data_source", "data_object"],
}


InputState = Literal["provided", "missing", "uncertain", "conflict"]


class InputStateDebugDetail(BaseModel):
    task_id: str
    task_type: str
    input_name: str
    state: InputState
    validator_rule: str
    source: str
    question: str | None = None


class MissingInputDebugDetail(BaseModel):
    task_id: str
    task_type: str
    input_name: str
    validator_rule: str
    source: str
    question: str
    state: Literal["missing", "uncertain", "conflict"] = "missing"


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


class TaskInputValidator:
    """Validates task inputs after task construction, regardless of matcher source."""

    def __init__(
        self,
        *,
        registry: FunctionRegistryCatalog,
        capability_catalog: SemanticCapabilityCatalog | None = None,
    ) -> None:
        self.registry = registry
        self.capability_catalog = capability_catalog or SemanticCapabilityCatalog.from_default_file()

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
        questions = self._questions_from_details(states)
        return task.model_copy(
            update={
                "missing_inputs": unresolved_inputs,
                "clarification_required": bool(unresolved_inputs),
                "clarification_questions": questions,
                "status": "needs_clarification" if unresolved_inputs else "ready",
                "blocked_reason": None,
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
        clarification_questions: list[str] = []
        for task in tasks:
            if not task.clarification_required:
                continue
            for question in task.clarification_questions:
                if question not in clarification_questions:
                    clarification_questions.append(question)
        return InputValidationResult(
            clarification_required=bool(unresolved_details),
            provided_inputs=self._names_for_state(state_details, "provided"),
            missing_inputs=self._names_for_state(state_details, "missing"),
            uncertain_inputs=self._names_for_state(state_details, "uncertain"),
            conflict_inputs=self._names_for_state(state_details, "conflict"),
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
                )
                for detail in unresolved_details
            ],
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
                updated.append(
                    task.model_copy(
                        update={
                            "status": "needs_clarification" if task.clarification_required else "ready",
                            "blocked_reason": None,
                        }
                    )
                )

        if any(original.status != current.status for original, current in zip(tasks, updated, strict=True)):
            return self._apply_dependency_status(updated)
        return updated

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
            updated.append(
                task.model_copy(update={"required_inputs": [*task.required_inputs, *additions]})
                if additions
                else task
            )
        return updated

    def _has_input(self, values: list[str], input_name: str) -> bool:
        return self._is_provided(input_name, self._provided_input_keys(values))

    def required_inputs_for_task(self, task_type: str) -> list[str]:
        configured = self.capability_catalog.required_inputs_for(task_type)
        if configured is not None:
            return configured

        try:
            return list(self.registry.get_by_task_type(task_type).required_inputs)
        except KeyError:
            return []

    def required_inputs_source_for_task(self, task_type: str) -> str:
        if self.capability_catalog.get_by_task_type(task_type) is not None:
            return "semantic_capabilities.yaml.required_inputs"

        try:
            self.registry.get_by_task_type(task_type)
        except KeyError:
            return "unknown_task_type"
        return "function_registry.required_inputs"

    def _provided_input_keys(self, required_inputs: list[str]) -> set[str]:
        provided = set()
        for value in required_inputs:
            key = str(value).split(":", 1)[0].strip()
            if key:
                provided.add(key)
        return provided

    def _is_provided(self, required_input: str, provided_inputs: set[str]) -> bool:
        accepted_keys = PROVIDED_INPUT_ALIASES.get(required_input, [required_input])
        return any(key in provided_inputs for key in accepted_keys)

    def _input_states_for_task(self, task: TaskItem, *, source_text: str) -> list[InputStateDebugDetail]:
        input_names = list(self.required_inputs_for_task(task.task_type))
        if task.task_type == "RULE_CALCULATION_COMMISSION" and self._has_calculation_object_uncertainty(source_text):
            insert_at = input_names.index("statistical_range") if "statistical_range" in input_names else len(input_names)
            input_names.insert(insert_at, "calculation_object")
        provided_inputs = self._provided_input_keys(task.required_inputs)
        source = self.required_inputs_source_for_task(task.task_type)
        return [
            self._state_detail(
                task=task,
                input_name=input_name,
                provided_inputs=provided_inputs,
                source_text=source_text,
                source=source,
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
    ) -> InputStateDebugDetail:
        source_state = self._state_from_source(input_name, source_text)
        if source_state is not None:
            state: InputState = source_state
        elif self._is_provided(input_name, provided_inputs):
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
                question=(
                    None
                    if state == "provided"
                    else self._question_for(input_name, state=state, source_text=source_text)
                ),
            )

    def _state_from_source(
        self,
        input_name: str,
        source_text: str,
    ) -> Literal["uncertain", "conflict"] | None:
        if not source_text:
            return None
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
