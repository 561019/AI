"""Platform-wide integration reservations for the permission gateway."""

from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "v1"


def platform_capabilities() -> dict[str, Any]:
    """Return the stable integration contract without exposing permission data."""

    return {
        "contract_version": CONTRACT_VERSION,
        "identity_contract": {
            "rule": "user_id = actor_id = person_id",
            "trusted_identity_source": "account_gateway JWT",
            "tenant_source": "account_gateway JWT org_id",
        },
        "transport": {
            "phase": "l1-layer-interface",
            "caller_rule": "Only l1_internal_channel may call the runtime permission endpoint using the mechanism-direct identity.",
            "future_requirement": "Replace the development mechanism secret with an mTLS client identity before cross-host access.",
        },
        "channels": [
            {
                "id": "runtime_permission_check",
                "status": "active_mechanism_direct_only",
                "method": "POST",
                "path": "/api/permission/check",
                "purpose": "L1 internal-channel pre-transfer check; business callers use /api/layer/dispatch.",
                "required_fields": [
                    "trace_id",
                    "request_id",
                    "actor_id",
                    "action",
                    "source_service",
                    "target_service",
                    "data_label",
                    "data_state",
                ],
            },
            {
                "id": "permission_audit_pull",
                "status": "active",
                "method": "GET",
                "path": "/api/permission/audits",
                "purpose": "Pull permission decisions by trace, request, actor, result, or time window.",
                "access": "approved audit/security consumer through the trusted network",
            },
            {
                "id": "permission_fact_sync",
                "status": "active_via_account_gateway",
                "methods": ["POST", "GET"],
                "paths": [
                    "/api/org/commands",
                    "/api/org/snapshot",
                    "/api/permissions/commands",
                    "/api/permissions/snapshot",
                ],
                "purpose": "Synchronize approved organization, resource, data, action, and policy facts.",
                "access": "account_gateway validates JWT and forwards trusted actor headers",
            },
            {
                "id": "integration_event_inbox",
                "status": "reserved",
                "method": "POST",
                "path": "/api/integrations/events",
                "purpose": "Future idempotent asynchronous lifecycle event intake.",
                "activation_prerequisites": [
                    "service authentication or mTLS",
                    "idempotency store",
                    "event persistence and replay governance",
                ],
            },
        ],
        "module_profiles": _module_profiles(),
        "integration_rules": [
            "Register module actions in data_actions before requesting those actions.",
            "Create an enabled service_call_rule before a new source_service -> target_service pair is allowed.",
            "Use resource_id for data-level delegation and data registry evaluation.",
            "Reuse trace_id across a workflow and create one request_id per call.",
            "Treat a non-200 result or allowed=false as a denied execution.",
        ],
    }


def _module_profiles() -> list[dict[str, str]]:
    common = "l1_layer_interface"
    return [
        _profile("L1.2", "流程管控", "workflow_control", "l1_layer_interface", "workflow.instance.*"),
        _profile("L1.3", "进化机制", "evolution_engine", common, "evolution.rule.*"),
        _profile("L1.4", "驾驭机制", "governance_control", common, "governance.policy.*"),
        _profile("L1.5", "大模型调度", "model_orchestrator", common, "model.invocation.*"),
        _profile("L1.6", "上下文与提示词管理", "context_prompt", common, "prompt.template.*"),
        _profile("L1.7", "数据", "data_platform", common, "data.record.*"),
        _profile("L1.8", "账号网关", "account_gateway", common, "identity.account.*"),
        _profile("L1.9", "安全合规", "security_compliance", "permission_audit_pull", "security.finding.*"),
        _profile("L1.10", "设备与系统接口", "device_system_adapter", common, "device.resource.*"),
        _profile("L1.11", "人机协同", "human_machine", common, "task.assignment.*"),
        _profile("L1.12", "成本管控", "cost_control", common, "cost.record.*"),
        _profile("L1.13", "Agent 知识库", "agent_knowledge", common, "knowledge.document.*"),
        _profile("L1.14", "Agent 执行沙箱", "agent_sandbox", common, "sandbox.execution.*"),
        _profile("L1.15", "Agent 记忆管理", "agent_memory", common, "memory.record.*"),
        _profile("L2.1", "文档表格解析", "document_table_parser", common, "document.parse.*"),
        _profile("L2.2", "外部系统对接", "external_system_connector", common, "external.sync.*"),
        _profile("L2.3", "数据归集聚合", "data_aggregation", common, "data.aggregate.*"),
        _profile("L2.4", "规则计算", "rule_engine", common, "rule.calculate.*"),
        _profile("L2.5", "分析预测", "analytics_forecast", common, "analysis.forecast.*"),
        _profile("L2.6", "知识库问答", "knowledge_qa", common, "knowledge.answer.*"),
        _profile("L2.7", "内容产出", "content_generation", common, "content.generate.*"),
        _profile("L2.8", "多媒体生成", "multimedia_generation", common, "media.generate.*"),
        _profile("L2.9", "人机交互", "human_machine_engine", common, "interaction.session.*"),
        _profile("L2.10", "数据可视化", "data_visualization", common, "visualization.render.*"),
        _profile("L4", "企业业务界面", "business_application", "l2_only", "business.operation.*"),
    ]


def _profile(
    layer: str,
    module_name: str,
    source_service: str,
    primary_channel: str,
    reserved_event_prefix: str,
) -> dict[str, str]:
    return {
        "layer": layer,
        "module_name": module_name,
        "source_service": source_service,
        "primary_channel": primary_channel,
        "fact_sync_channel": "permission_fact_sync",
        "reserved_event_prefix": reserved_event_prefix,
    }
