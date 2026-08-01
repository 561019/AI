from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from framework.module_catalog import ALL_MODULES


PayloadMode = Literal["platform_envelope", "l2_internal_message", "account_lifecycle"]


@dataclass(frozen=True)
class AdapterSpec:
    capability: str
    module_code: str
    layer: str
    method: str
    path: str
    upstream_env: str
    default_base_url: str
    payload_mode: PayloadMode = "l2_internal_message"
    action: str | None = None
    auth_token_env: str | None = None
    description_cn: str = ""


MODULE_UPSTREAMS: dict[str, tuple[str, str]] = {
    "rule-adapter": ("RULE_ADAPTER_UPSTREAM_URL", "http://127.0.0.1:8012"),
    "content-adapter": ("CONTENT_ADAPTER_UPSTREAM_URL", "http://127.0.0.1:8013"),
    "document-table-parsing": ("DOCUMENT_TABLE_PARSING_UPSTREAM_URL", "http://127.0.0.1:8071"),
    "data-operation": ("DATA_OPERATION_UPSTREAM_URL", "http://127.0.0.1:8061"),
    "analysis-prediction": ("ANALYSIS_PREDICTION_UPSTREAM_URL", "http://127.0.0.1:8060"),
    "monitoring-reminder": ("MONITORING_REMINDER_UPSTREAM_URL", "http://127.0.0.1:8009"),
    "project-management": ("PROJECT_MANAGEMENT_UPSTREAM_URL", "http://127.0.0.1:8008"),
    "external-system-integration": ("EXTERNAL_SYSTEM_INTEGRATION_UPSTREAM_URL", "http://127.0.0.1:8074"),
    "knowledge-qa": ("KNOWLEDGE_QA_UPSTREAM_URL", "http://127.0.0.1:8075"),
    "digital-asset": ("DIGITAL_ASSET_UPSTREAM_URL", "http://127.0.0.1:8765"),
    "knowledge-map": ("KNOWLEDGE_MAP_UPSTREAM_URL", "http://127.0.0.1:8076"),
    "multimedia-generation": ("MULTIMEDIA_GENERATION_UPSTREAM_URL", "http://127.0.0.1:8065"),
    "context-prompt-management": ("CONTEXT_PROMPT_MANAGEMENT_UPSTREAM_URL", "http://127.0.0.1:8077"),
    "foundation-data": ("FOUNDATION_DATA_UPSTREAM_URL", "http://127.0.0.1:8078"),
    "account-gateway": ("ACCOUNT_GATEWAY_UPSTREAM_URL", "http://127.0.0.1:8080"),
    "human-collaboration": ("HUMAN_COLLABORATION_UPSTREAM_URL", "http://127.0.0.1:8067"),
    "evolution-mechanism": ("EVOLUTION_MECHANISM_UPSTREAM_URL", "http://127.0.0.1:8069"),
    "control-mechanism": ("CONTROL_MECHANISM_UPSTREAM_URL", "http://127.0.0.1:8079"),
    "knowledge-base": ("KNOWLEDGE_BASE_UPSTREAM_URL", "http://127.0.0.1:8070"),
    "execution-sandbox": ("EXECUTION_SANDBOX_UPSTREAM_URL", "http://127.0.0.1:8765"),
    "memory-management": ("MEMORY_MANAGEMENT_UPSTREAM_URL", "http://127.0.0.1:8081"),
    "device-system-interface": ("DEVICE_SYSTEM_INTERFACE_UPSTREAM_URL", "http://127.0.0.1:8082"),
    "security-compliance": ("SECURITY_COMPLIANCE_UPSTREAM_URL", "http://127.0.0.1:8066"),
    "cost-control": ("COST_CONTROL_UPSTREAM_URL", "http://127.0.0.1:8083"),
}


MODULE_DEFAULT_PATHS: dict[str, tuple[str, PayloadMode]] = {
    "rule-adapter": ("/api/v1/delivered-rules/calculate", "platform_envelope"),
    "content-adapter": ("/api/v1/delivered-content/generate", "platform_envelope"),
    "document-table-parsing": ("/api/v1/document-parsing/tasks", "l2_internal_message"),
    "data-operation": ("/api/l2/tasks", "l2_internal_message"),
    "analysis-prediction": ("/v1/analysis-jobs/evaluate", "platform_envelope"),
    "monitoring-reminder": ("/api/v1/l2/internal/messages", "l2_internal_message"),
    "project-management": ("/api/v1/l2/internal/messages", "l2_internal_message"),
    "external-system-integration": ("/api/v1/external-systems/tasks", "l2_internal_message"),
    "knowledge-qa": ("/api/v1/knowledge-qa/tasks", "l2_internal_message"),
    "digital-asset": ("/api/flow/tasks", "l2_internal_message"),
    "knowledge-map": ("/api/v1/knowledge-map/tasks", "l2_internal_message"),
    "multimedia-generation": ("/api/multimedia/subtasks", "l2_internal_message"),
    "context-prompt-management": ("/api/v1/context-prompts/tasks", "l2_internal_message"),
    "foundation-data": ("/api/v1/foundation-data/tasks", "l2_internal_message"),
    "security-compliance": ("/api/v1/security-compliance/check", "platform_envelope"),
    "human-collaboration": ("/api/v1/human/tasks", "l2_internal_message"),
    "execution-sandbox": ("/api/v1/layer-interface/messages", "l2_internal_message"),
    "evolution-mechanism": ("/api/v1/evolution/actions", "l2_internal_message"),
    "control-mechanism": ("/api/v1/control/actions", "l2_internal_message"),
    "knowledge-base": ("/api/v1/knowledge/tasks", "l2_internal_message"),
    "memory-management": ("/api/v1/memory/tasks", "l2_internal_message"),
    "device-system-interface": ("/api/v1/device-systems/tasks", "l2_internal_message"),
    "cost-control": ("/api/v1/cost/tasks", "l2_internal_message"),
}


ACCOUNT_LIFECYCLE_SPECS: tuple[AdapterSpec, ...] = (
    AdapterSpec("account.create", "account-gateway", "foundation", "POST", "/api/accounts", *MODULE_UPSTREAMS["account-gateway"], "account_lifecycle", "account.create", "ACCOUNT_GATEWAY_ADMIN_TOKEN", "创建账号"),
    AdapterSpec("account.list", "account-gateway", "foundation", "GET", "/api/accounts", *MODULE_UPSTREAMS["account-gateway"], "account_lifecycle", "account.list", "ACCOUNT_GATEWAY_ADMIN_TOKEN", "查询账号列表"),
    AdapterSpec("account.update", "account-gateway", "foundation", "PATCH", "/api/accounts", *MODULE_UPSTREAMS["account-gateway"], "account_lifecycle", "account.update", "ACCOUNT_GATEWAY_ADMIN_TOKEN", "更新账号"),
    AdapterSpec("account.delete", "account-gateway", "foundation", "DELETE", "/api/accounts", *MODULE_UPSTREAMS["account-gateway"], "account_lifecycle", "account.delete", "ACCOUNT_GATEWAY_ADMIN_TOKEN", "删除账号"),
    AdapterSpec("account.freeze", "account-gateway", "foundation", "POST", "/api/accounts/{name}/freeze", *MODULE_UPSTREAMS["account-gateway"], "account_lifecycle", "account.freeze", "ACCOUNT_GATEWAY_ADMIN_TOKEN", "冻结账号并锁定资产"),
    AdapterSpec("account.handover_confirm", "account-gateway", "foundation", "POST", "/api/accounts/{name}/handover-confirm", *MODULE_UPSTREAMS["account-gateway"], "account_lifecycle", "account.handover_confirm", "ACCOUNT_GATEWAY_ADMIN_TOKEN", "确认离职资产交接"),
    AdapterSpec("account.offboarding_assets.query", "account-gateway", "foundation", "GET", "/api/accounts/{name}/offboarding-assets", *MODULE_UPSTREAMS["account-gateway"], "account_lifecycle", "account.offboarding_assets.query", "ACCOUNT_GATEWAY_ADMIN_TOKEN", "查询离职资产"),
)


def _build_specs() -> dict[str, AdapterSpec]:
    specs = {item.capability: item for item in ACCOUNT_LIFECYCLE_SPECS}
    for module in ALL_MODULES:
        if module.code == "account-gateway":
            path, payload_mode = "/api/identity/context", "platform_envelope"
        else:
            path, payload_mode = MODULE_DEFAULT_PATHS.get(module.code, ("/api/v1/instructions", "l2_internal_message"))
        upstream_env, default_base_url = MODULE_UPSTREAMS[module.code]
        for capability in module.capabilities:
            specs.setdefault(
                capability,
                AdapterSpec(
                    capability=capability,
                    module_code=module.code,
                    layer=module.layer,
                    method="POST",
                    path=path,
                    upstream_env=upstream_env,
                    default_base_url=default_base_url,
                    payload_mode=payload_mode,  # type: ignore[arg-type]
                    action=capability,
                    auth_token_env=(
                        "ACCOUNT_GATEWAY_ADMIN_TOKEN" if module.code == "account-gateway"
                        else "SANDBOX_PLATFORM_API_TOKEN" if module.code == "execution-sandbox"
                        else None
                    ),
                    description_cn=f"{module.name_cn}：{capability}",
                ),
            )
    return specs


ADAPTER_SPECS: dict[str, AdapterSpec] = _build_specs()


def get_adapter_spec(capability: str) -> AdapterSpec | None:
    return ADAPTER_SPECS.get(capability)
