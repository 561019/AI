from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.services.intent_analysis_engine.input_validator import QUESTION_BY_INPUT
from app.services.intent_analysis_engine.task_schema.required_inputs import (
    canonical_input_name,
    input_is_provided,
    provided_input_keys,
)
from app.services.intent_analysis_engine.task_schema.validator import TaskTypeSchemaCatalog


class LLMResponseContractValidationResult(BaseModel):
    result: IntentAnalysisResult
    corrections: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    evidence_spans_by_task_id: dict[str, str] = Field(default_factory=dict)


class LLMResponseContractValidator:
    """Code-level contract guard for LLM-generated TaskList responses."""

    DATA_PREP_TASK_TYPE = "DATA_QUERY_FETCH"
    REPORT_TASK_TYPES = {"DOCUMENT_GENERATE", "CONTENT_GENERATE"}

    def __init__(self, schema_catalog: TaskTypeSchemaCatalog | None = None) -> None:
        self.schema_catalog = schema_catalog or TaskTypeSchemaCatalog()

    def validate(
        self,
        result: IntentAnalysisResult,
        *,
        source_text: str = "",
    ) -> LLMResponseContractValidationResult:
        corrections: list[str] = []
        errors: list[str] = []
        evidence_by_task_id: dict[str, str] = {}

        tasks = list(result.tasks)
        tasks = self._normalize_task_fields(tasks, corrections=corrections, errors=errors)
        tasks = self._remove_invalid_dependencies(tasks, corrections=corrections)
        tasks, inserted_data_task_id = self._ensure_data_preparation_split(
            tasks,
            source_text=source_text,
            corrections=corrections,
            evidence_by_task_id=evidence_by_task_id,
        )
        tasks = self._ensure_report_dependencies(tasks, corrections=corrections)
        tasks = self._remove_invalid_dependencies(tasks, corrections=corrections)
        tasks = self._normalize_missing_inputs(tasks, corrections=corrections)

        clarification_required = result.clarification_required
        clarification_questions = list(result.clarification_questions)
        missing_inputs = self._collect_missing_inputs(tasks)
        if missing_inputs:
            if not clarification_required:
                corrections.append("clarification_required_enabled_for_missing_inputs")
            clarification_required = True
            for missing_input in missing_inputs:
                question = self._question_for_missing_input(missing_input, source_text=source_text)
                if question not in clarification_questions:
                    clarification_questions.append(question)
                    corrections.append(f"clarification_question_added:{missing_input}")

        updated = result.model_copy(
            update={
                "tasks": tasks,
                "clarification_required": clarification_required,
                "clarification_questions": clarification_questions,
            },
        )
        return LLMResponseContractValidationResult(
            result=updated,
            corrections=list(dict.fromkeys(corrections)),
            errors=list(dict.fromkeys(errors)),
            evidence_spans_by_task_id=evidence_by_task_id,
        )

    def _normalize_missing_inputs(
        self,
        tasks: list[TaskItem],
        *,
        corrections: list[str],
    ) -> list[TaskItem]:
        normalized_tasks: list[TaskItem] = []
        for index, task in enumerate(tasks):
            schema = self.schema_catalog.get(task.task_type)
            if schema is None:
                if task.missing_inputs:
                    corrections.append(f"unknown_task_missing_inputs_removed:{index}")
                normalized_tasks.append(
                    task.model_copy(
                        update={
                            "missing_inputs": [],
                            "clarification_required": bool(task.clarification_questions),
                            "status": (
                                "needs_clarification"
                                if task.clarification_questions
                                else "ready"
                            ),
                        },
                    ),
                )
                continue

            provided_inputs = provided_input_keys(task.required_inputs)
            schema_missing = [
                input_name
                for input_name in schema.required_inputs
                if not input_is_provided(input_name, provided_inputs)
            ]
            model_missing = [
                canonical_input_name(value)
                for value in task.missing_inputs
            ]
            if model_missing != task.missing_inputs:
                corrections.append(f"missing_inputs_canonicalized:{index}")
            if model_missing != schema_missing:
                corrections.append(f"missing_inputs_recomputed_from_task_type_schema:{index}")

            questions = list(task.clarification_questions)
            if schema_missing:
                questions = [
                    QUESTION_BY_INPUT[input_name]
                    for input_name in schema_missing
                    if input_name in QUESTION_BY_INPUT
                ]

            normalized_tasks.append(
                task.model_copy(
                    update={
                        "missing_inputs": schema_missing,
                        "clarification_required": bool(schema_missing) or bool(
                            task.clarification_questions
                        ),
                        "clarification_questions": questions,
                        "status": (
                            "needs_clarification"
                            if schema_missing or task.clarification_questions
                            else "ready"
                        ),
                    },
                ),
            )
        return normalized_tasks

    def _normalize_task_fields(
        self,
        tasks: list[TaskItem],
        *,
        corrections: list[str],
        errors: list[str],
    ) -> list[TaskItem]:
        normalized: list[TaskItem] = []
        for index, task in enumerate(tasks):
            task_type = task.task_type.strip()
            task_description = task.task_description.strip()
            if not task_type:
                errors.append(f"empty_task_type:{index}")
            if not task_description:
                errors.append(f"empty_task_description:{index}")

            required_inputs = [value.strip() for value in task.required_inputs if str(value).strip()]
            if required_inputs != task.required_inputs:
                corrections.append(f"required_inputs_normalized:{index}")

            normalized.append(
                task.model_copy(
                    update={
                        "task_type": task_type,
                        "task_description": task_description,
                        "required_inputs": required_inputs,
                    },
                ),
            )
        return normalized

    def _remove_invalid_dependencies(
        self,
        tasks: list[TaskItem],
        *,
        corrections: list[str],
    ) -> list[TaskItem]:
        task_ids = {task.task_id for task in tasks}
        normalized: list[TaskItem] = []
        for index, task in enumerate(tasks):
            dependencies: list[str] = []
            for dependency in task.dependencies:
                if dependency == task.task_id:
                    corrections.append(f"self_dependency_removed:{index}")
                    continue
                if dependency not in task_ids:
                    corrections.append(f"unknown_dependency_removed:{index}")
                    continue
                if dependency not in dependencies:
                    dependencies.append(dependency)
            normalized.append(task.model_copy(update={"dependencies": dependencies}))
        return normalized

    def _ensure_data_preparation_split(
        self,
        tasks: list[TaskItem],
        *,
        source_text: str,
        corrections: list[str],
        evidence_by_task_id: dict[str, str],
    ) -> tuple[list[TaskItem], str | None]:
        if self._has_data_preparation_task(tasks):
            return self._normalize_merged_analysis_descriptions(tasks, corrections=corrections), None
        first_analysis_index = self._first_analysis_index(tasks)
        if first_analysis_index is None:
            return tasks, None
        if not self._data_preparation_requested(source_text, tasks):
            return tasks, None

        analysis_task = tasks[first_analysis_index]
        data_object = self._infer_data_object(source_text, analysis_task)
        data_task = TaskItem(
            task_type=self.DATA_PREP_TASK_TYPE,
            task_description=f"整理{data_object}",
            action="整理",
            object=data_object,
            required_inputs=[
                "operation:整理归集",
                f"data_source:{data_object}",
            ],
            missing_inputs=[],
            dependencies=[],
            confidence=max(0.70, min(analysis_task.confidence, 0.90)),
        )
        evidence = self._extract_data_preparation_evidence(source_text, data_object)
        if evidence:
            evidence_by_task_id[data_task.task_id] = evidence

        tasks = list(tasks)
        tasks.insert(first_analysis_index, data_task)
        shifted_analysis_index = first_analysis_index + 1
        analysis_task = tasks[shifted_analysis_index]
        dependencies = list(analysis_task.dependencies)
        if data_task.task_id not in dependencies:
            dependencies.insert(0, data_task.task_id)
        tasks[shifted_analysis_index] = analysis_task.model_copy(update={"dependencies": dependencies})
        tasks = self._normalize_merged_analysis_descriptions(tasks, corrections=corrections)
        corrections.append("data_preparation_task_inserted")
        return tasks, data_task.task_id

    def _normalize_merged_analysis_descriptions(
        self,
        tasks: list[TaskItem],
        *,
        corrections: list[str],
    ) -> list[TaskItem]:
        normalized: list[TaskItem] = []
        for index, task in enumerate(tasks):
            description = task.task_description
            if self._is_analysis_task(task) and self._contains_data_prep_action(description):
                data_object = task.object if "数据" in task.object else "销售数据"
                normalized.append(
                    task.model_copy(
                        update={
                            "task_description": f"分析{data_object}",
                            "action": "分析",
                            "object": data_object,
                        },
                    ),
                )
                corrections.append(f"merged_analysis_description_normalized:{index}")
                continue
            normalized.append(task)
        return normalized

    def _ensure_report_dependencies(
        self,
        tasks: list[TaskItem],
        *,
        corrections: list[str],
    ) -> list[TaskItem]:
        normalized = list(tasks)
        for report_index, task in enumerate(normalized):
            if not self._is_report_task(task):
                continue
            analysis_ids = [
                candidate.task_id
                for index, candidate in enumerate(normalized)
                if index < report_index and self._is_analysis_task(candidate)
            ] or [
                candidate.task_id
                for candidate in normalized
                if candidate.task_id != task.task_id and self._is_analysis_task(candidate)
            ]
            if not analysis_ids:
                continue
            dependencies = list(task.dependencies)
            if not any(dependency in analysis_ids for dependency in dependencies):
                for analysis_id in analysis_ids:
                    if analysis_id not in dependencies:
                        dependencies.append(analysis_id)
                normalized[report_index] = task.model_copy(update={"dependencies": dependencies})
                corrections.append(f"report_dependencies_added:{report_index}")
        return normalized

    def _data_preparation_requested(self, source_text: str, tasks: list[TaskItem]) -> bool:
        if re.search(r"(?:整理|获取|准备|收集|汇总).{0,30}(?:销售)?数据", source_text):
            return True
        return any(
            self._is_analysis_task(task)
            and self._contains_data_prep_action(task.task_description)
            and "分析" in task.task_description
            for task in tasks
        )

    def _contains_data_prep_action(self, text: str) -> bool:
        return bool(re.search(r"(?:整理|获取|准备|收集|汇总)", text))

    def _extract_data_preparation_evidence(self, source_text: str, data_object: str) -> str:
        patterns = [
            rf"(?:整理|获取|准备|收集|汇总)[^。；;\n]{{0,80}}?{re.escape(data_object)}",
            r"(?:整理|获取|准备|收集|汇总)[^。；;\n]{0,80}?销售数据",
            r"(?:整理|获取|准备|收集|汇总)[^。；;\n]{0,80}?数据",
        ]
        for pattern in patterns:
            match = re.search(pattern, source_text)
            if match:
                return match.group(0)
        return ""

    def _infer_data_object(self, source_text: str, analysis_task: TaskItem) -> str:
        if re.search(r"销售数据", source_text) or "销售" in analysis_task.task_description:
            return "销售数据"
        if analysis_task.object and "数据" in analysis_task.object:
            return analysis_task.object
        return "数据"

    def _has_data_preparation_task(self, tasks: list[TaskItem]) -> bool:
        return any(
            task.task_type == self.DATA_PREP_TASK_TYPE
            or (
                task.action in {"整理", "获取", "查询", "准备", "收集", "汇总"}
                and "数据" in f"{task.task_description}{task.object}"
            )
            for task in tasks
        )

    def _first_analysis_index(self, tasks: list[TaskItem]) -> int | None:
        for index, task in enumerate(tasks):
            if self._is_analysis_task(task):
                return index
        return None

    def _is_analysis_task(self, task: TaskItem) -> bool:
        return task.task_type.startswith("DATA_ANALYSIS") or task.action in {"分析", "预测", "统计"}

    def _is_report_task(self, task: TaskItem) -> bool:
        text = f"{task.task_description}{task.object}"
        return task.task_type in self.REPORT_TASK_TYPES and any(
            keyword in text for keyword in ("报告", "材料", "文档", "经营分析")
        )

    def _collect_missing_inputs(self, tasks: list[TaskItem]) -> list[str]:
        missing_inputs: list[str] = []
        for task in tasks:
            for missing_input in task.missing_inputs:
                if missing_input not in missing_inputs:
                    missing_inputs.append(missing_input)
        return missing_inputs

    def _question_for_missing_input(self, input_name: str, *, source_text: str) -> str:
        if input_name == "calculation_policy":
            return "请确认销售提成适用的政策版本（去年版或今年调整版）。"
        if input_name == "calculation_object":
            return "请确认销售提成的计算对象（全部销售人员或仅正式员工）。"
        if input_name in {"sales_data_source", "data_source"}:
            return "请确认销售数据来源（CRM系统或财务系统确认后的收入数据，以哪个为准）。"
        if input_name == "statistical_range":
            if "本季度" in source_text:
                return "请确认本季度经营分析的数据时间范围和最终截止日期。"
            return "请确认统计范围（例如时间范围、组织范围）。"
        return QUESTION_BY_INPUT.get(input_name, f"请补充 {input_name}。")
