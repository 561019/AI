from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskTypeSchema:
    task_type: str
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    field_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    allow_clarification: bool = True


DEFAULT_TASK_TYPE_SCHEMAS: tuple[TaskTypeSchema, ...] = (
    TaskTypeSchema(
        task_type="RULE_CALCULATION_COMMISSION",
        required_inputs=("calculation_policy",),
        optional_inputs=(
            "calculation_basis",
            "sales_data_source",
            "statistical_range",
            "data_scope",
            "calculation_object",
        ),
        field_sources={
            "calculation_policy": ("user_input", "context"),
            "calculation_basis": ("user_input", "context"),
            "sales_data_source": ("user_input", "context"),
            "statistical_range": ("user_input", "context"),
            "data_scope": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="RULE_CALCULATION_GENERAL",
        required_inputs=("calculation_basis",),
        optional_inputs=("calculation_policy", "statistical_range"),
        field_sources={
            "calculation_basis": ("user_input", "context"),
            "calculation_policy": ("user_input", "context"),
            "statistical_range": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DATA_QUERY_FETCH",
        required_inputs=("data_source",),
        optional_inputs=("operation", "data_object", "classification_field", "statistical_range", "summary_field"),
        field_sources={
            "data_source": ("user_input", "context"),
            "operation": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DATA_AGGREGATION_SUMMARY",
        required_inputs=("statistical_range", "summary_field"),
        optional_inputs=("classification_field", "data_source"),
        field_sources={
            "statistical_range": ("user_input", "context"),
            "summary_field": ("user_input", "context"),
            "classification_field": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DATA_ANALYSIS_GROUP_SUM",
        required_inputs=("statistical_range",),
        optional_inputs=("classification_field", "summary_field", "data_source"),
        field_sources={
            "statistical_range": ("user_input", "context"),
            "classification_field": ("user_input", "context"),
            "summary_field": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DATA_ANALYSIS_PROBLEM",
        required_inputs=("analysis_object",),
        optional_inputs=("analysis_method", "statistical_range", "summary_field"),
        field_sources={
            "analysis_object": ("user_input", "context"),
            "analysis_method": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DATA_ANALYSIS_FORECAST",
        required_inputs=("analysis_object",),
        optional_inputs=("statistical_range", "analysis_method"),
        field_sources={"analysis_object": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="DATA_ANALYSIS_YOY",
        required_inputs=("statistical_range",),
        optional_inputs=("summary_field", "analysis_object"),
        field_sources={
            "statistical_range": ("user_input", "context"),
            "summary_field": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DATA_ANALYSIS_MOM",
        required_inputs=("statistical_range",),
        optional_inputs=("summary_field", "analysis_object"),
        field_sources={
            "statistical_range": ("user_input", "context"),
            "summary_field": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DOCUMENT_GENERATE",
        required_inputs=("document_type",),
        optional_inputs=("topic", "template", "output_format", "data_source"),
        field_sources={
            "document_type": ("user_input", "context"),
            "topic": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="PROCESS_HANDLE",
        required_inputs=("process_name",),
        optional_inputs=("initiator", "process_step"),
        field_sources={"process_name": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="WORKFLOW_START",
        required_inputs=("process_name",),
        optional_inputs=("initiator", "priority"),
        field_sources={"process_name": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="EXTERNAL_DATA_FETCH",
        required_inputs=("external_system",),
        optional_inputs=("operation", "data_object"),
        field_sources={"external_system": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="EXTERNAL_SYSTEM_SUBMIT",
        required_inputs=("external_system",),
        optional_inputs=("operation", "payload", "target_object"),
        field_sources={"external_system": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="DOCUMENT_TABLE_PARSE",
        required_inputs=("file",),
        optional_inputs=("parse_target", "file_type"),
        field_sources={"file": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="FILE_STRUCTURE_EXTRACT",
        required_inputs=("file",),
        optional_inputs=("parse_target", "file_type"),
        field_sources={"file": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="MONITORING_REMINDER",
        required_inputs=("trigger_condition",),
        optional_inputs=("monitoring_object",),
        field_sources={
            "trigger_condition": ("user_input", "context"),
            "monitoring_object": ("user_input", "context"),
        },
    ),
    TaskTypeSchema(
        task_type="DIGITAL_ASSET_ACCRUAL_VOUCHER",
        required_inputs=("source_result",),
        optional_inputs=("asset_type", "period"),
        field_sources={"source_result": ("user_input", "context")},
    ),
    TaskTypeSchema(
        task_type="QUESTION_ANSWER",
        required_inputs=(),
        optional_inputs=("question",),
        field_sources={"question": ("user_input", "context")},
        allow_clarification=False,
    ),
    TaskTypeSchema(
        task_type="GENERAL_TASK",
        required_inputs=(),
        optional_inputs=("task_object", "time", "location", "assignee", "task_parameters"),
        field_sources={
            "task_object": ("user_input", "context"),
            "time": ("user_input", "context"),
            "location": ("user_input", "context"),
            "task_parameters": ("user_input", "context"),
        },
        allow_clarification=False,
    ),
)
