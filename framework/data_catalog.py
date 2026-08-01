from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    code: str
    owner_module: str
    classification: str = "internal"
    retention_policy: str = "business-default"
    sensitive: bool = False
    allowed_readers: tuple[str, ...] = ("data-operation",)
    allowed_writers: tuple[str, ...] = ("data-operation",)
    required_fields: tuple[str, ...] = ()


def _spec(
    code: str,
    owner: str,
    *,
    classification: str = "internal",
    retention: str = "business-default",
    sensitive: bool = False,
    readers: tuple[str, ...] = ("data-operation",),
    writers: tuple[str, ...] = ("data-operation",),
    required: tuple[str, ...] = (),
) -> DatasetSpec:
    return DatasetSpec(code, owner, classification, retention, sensitive, readers, writers, required)


DATASETS: tuple[DatasetSpec, ...] = (
    _spec("accounts", "account-gateway", classification="sensitive", readers=("account-gateway", "data-operation", "application-gateway"), writers=("account-gateway",), required=("account_id", "login_name")),
    _spec("account_credentials", "account-gateway", classification="restricted", sensitive=True, readers=("account-gateway",), writers=("account-gateway",), required=("account_id", "password_hash")),
    _spec("account_role_bindings", "account-gateway", classification="sensitive", sensitive=True, readers=("account-gateway", "permission-adapter"), writers=("account-gateway", "permission-adapter"), required=("account_id", "role_id")),
    _spec("account_sessions", "account-gateway", classification="restricted", retention="session-lifetime", sensitive=True, readers=("account-gateway",), writers=("account-gateway",), required=("session_id", "account_id")),
    _spec("conversations", "application-gateway", readers=("application-gateway", "data-operation", "context-prompt-management", "memory-management"), writers=("application-gateway", "data-operation"), required=("conversation_id",)),
    _spec("conversation_messages", "application-gateway", classification="sensitive", readers=("application-gateway", "data-operation", "context-prompt-management", "memory-management", "workflow-execution"), writers=("application-gateway", "data-operation", "workflow-execution"), required=("message_id", "conversation_id")),
    _spec("uploaded_files", "application-gateway", classification="sensitive", readers=("application-gateway", "data-operation", "document-table-parsing", "knowledge-base"), writers=("application-gateway", "data-operation", "document-table-parsing"), required=("file_id", "object_id")),
    _spec("storage_objects", "foundation-data", classification="sensitive", readers=("application-gateway", "data-operation", "document-table-parsing", "knowledge-base", "foundation-data"), writers=("application-gateway", "foundation-data"), required=("object_id", "sha256", "size_bytes")),
    _spec("generated_files", "application-gateway", classification="sensitive", readers=("application-gateway", "data-operation"), writers=("application-gateway", "data-operation"), required=("file_id", "object_id", "conversation_id", "original_name")),
    _spec("task_snapshots", "workflow-execution", readers=("application-gateway", "data-operation", "workflow-execution", "intent-adapter"), writers=("application-gateway", "workflow-execution", "intent-adapter"), required=("record_id",)),
    _spec("workflow_instances", "workflow-execution", readers=("workflow-execution", "application-gateway", "data-operation", "human-collaboration"), writers=("workflow-execution",), required=("workflow_instance_id", "state")),
    _spec("workflow_node_instances", "workflow-execution", readers=("workflow-execution", "application-gateway", "data-operation", "human-collaboration"), writers=("workflow-execution",), required=("node_instance_id", "workflow_instance_id", "state")),
    _spec("workflow_events", "workflow-execution", retention="audit-7y", readers=("workflow-execution", "application-gateway", "data-operation", "security-compliance"), writers=("workflow-execution",), required=("event_id", "workflow_instance_id")),
    _spec("human_tasks", "human-collaboration", classification="sensitive", readers=("human-collaboration", "workflow-execution", "application-gateway", "data-operation"), writers=("human-collaboration", "workflow-execution"), required=("human_task_id", "assignee_id", "state")),
    _spec("confirmations", "human-collaboration", classification="sensitive", readers=("human-collaboration", "workflow-execution", "application-gateway"), writers=("human-collaboration", "workflow-execution", "application-gateway"), required=("confirmation_id", "state")),
    _spec("data_assets", "data-operation", readers=("data-operation",), writers=("data-operation",), required=("asset_id", "dataset")),
    _spec("data_lineage", "data-operation", retention="audit-7y", readers=("data-operation", "security-compliance"), writers=("data-operation",), required=("lineage_id", "source_ref", "target_ref")),
    _spec("parse_jobs", "document-table-parsing", readers=("document-table-parsing", "data-operation", "workflow-execution"), writers=("document-table-parsing",), required=("parse_job_id", "file_id")),
    _spec("extracted_fields", "document-table-parsing", classification="sensitive", readers=("document-table-parsing", "data-operation", "workflow-execution", "rule-adapter"), writers=("document-table-parsing",), required=("record_id", "parse_job_id")),
    _spec("rule_runs", "rule-adapter", readers=("rule-adapter", "workflow-execution", "data-operation"), writers=("rule-adapter",), required=("rule_run_id",)),
    _spec("rule_results", "rule-adapter", classification="sensitive", readers=("rule-adapter", "workflow-execution", "data-operation", "application-gateway"), writers=("rule-adapter",), required=("rule_result_id", "rule_run_id")),
    _spec("content_jobs", "content-adapter", readers=("content-adapter", "workflow-execution", "data-operation"), writers=("content-adapter",), required=("content_job_id",)),
    _spec("content_versions", "content-adapter", classification="sensitive", readers=("content-adapter", "workflow-execution", "data-operation", "application-gateway"), writers=("content-adapter",), required=("content_version_id", "content_job_id")),
    _spec("projects", "project-management", classification="sensitive", readers=("project-management", "data-operation", "application-gateway"), writers=("project-management", "application-gateway"), required=("project_id",)),
    _spec("project_members", "project-management", classification="sensitive", readers=("project-management", "data-operation", "permission-adapter"), writers=("project-management",), required=("record_id", "project_id", "account_id")),
    _spec("digital_assets", "digital-asset", readers=("digital-asset", "data-operation", "knowledge-map", "application-gateway"), writers=("digital-asset",), required=("asset_id", "asset_type")),
    _spec("knowledge_sources", "knowledge-base", classification="sensitive", readers=("knowledge-base", "knowledge-qa", "data-operation", "digital-asset", "application-gateway"), writers=("knowledge-base", "digital-asset"), required=("knowledge_source_id",)),
    _spec("knowledge_chunks", "knowledge-base", classification="sensitive", readers=("knowledge-base", "knowledge-qa", "data-operation", "workflow-execution", "application-gateway"), writers=("knowledge-base",), required=("chunk_id", "knowledge_source_id")),
    _spec("knowledge_indexes", "knowledge-base", classification="sensitive", readers=("knowledge-base", "knowledge-qa", "data-operation", "workflow-execution", "application-gateway"), writers=("knowledge-base",), required=("index_id", "knowledge_source_id")),
    _spec("memory_items", "memory-management", classification="sensitive", readers=("memory-management", "context-prompt-management"), writers=("memory-management",), required=("memory_id", "source_ref")),
    _spec("context_capacity_events", "context-prompt-management", classification="sensitive", readers=("context-prompt-management", "application-gateway"), writers=("context-prompt-management",), required=("event_id", "conversation_id", "state")),
    _spec("context_work_reports", "context-prompt-management", classification="sensitive", readers=("context-prompt-management", "application-gateway"), writers=("context-prompt-management",), required=("report_id", "conversation_id", "project_id")),
    _spec("context_handoff_files", "context-prompt-management", classification="sensitive", readers=("context-prompt-management", "application-gateway"), writers=("context-prompt-management",), required=("handoff_id", "conversation_id", "project_id")),
    _spec("context_inheritance_packages", "context-prompt-management", classification="sensitive", readers=("context-prompt-management", "application-gateway"), writers=("context-prompt-management",), required=("package_id", "project_id", "version_no")),
    _spec("context_imports", "context-prompt-management", classification="sensitive", readers=("context-prompt-management", "application-gateway"), writers=("context-prompt-management",), required=("import_id", "target_conversation_id", "source_record_id")),
    _spec("context_cross_project_references", "context-prompt-management", classification="sensitive", readers=("context-prompt-management", "application-gateway"), writers=("context-prompt-management",), required=("reference_id", "target_project_id", "source_record_id")),
    _spec("context_control_center_messages", "context-prompt-management", classification="sensitive", readers=("context-prompt-management", "application-gateway"), writers=("context-prompt-management",), required=("record_id", "scope")),
    _spec("monitor_items", "monitoring-reminder", readers=("monitoring-reminder", "data-operation"), writers=("monitoring-reminder",), required=("monitor_item_id",)),
    _spec("notifications", "monitoring-reminder", classification="sensitive", readers=("monitoring-reminder", "human-collaboration", "application-gateway"), writers=("monitoring-reminder",), required=("notification_id", "recipient_id")),
    _spec("model_usage", "model-dispatcher", retention="audit-3y", readers=("model-dispatcher", "cost-control", "security-compliance"), writers=("model-dispatcher",), required=("model_call_id",)),
    _spec("security_events", "security-compliance", classification="restricted", retention="audit-7y", sensitive=True, readers=("security-compliance",), writers=("security-compliance", "permission-adapter", "foundation-data"), required=("security_event_id",)),
    _spec("permission_decisions", "permission-adapter", classification="restricted", retention="audit-7y", sensitive=True, readers=("permission-adapter", "security-compliance"), writers=("permission-adapter", "foundation-data"), required=("decision_id", "effect")),
    _spec("business_records", "data-operation"),
    _spec("reconciliation_results", "data-operation", classification="sensitive", retention="business-7y", readers=("data-operation", "workflow-execution", "application-gateway", "content-adapter"), writers=("data-operation", "workflow-execution"), required=("record_id",)),
    _spec("case2_sales_reconciliation", "data-operation", classification="sensitive", retention="business-7y", readers=("data-operation", "workflow-execution", "rule-adapter", "content-adapter"), writers=("data-operation", "workflow-execution")),
)


DATASET_BY_CODE = {item.code: item for item in DATASETS}
