from __future__ import annotations

import argparse
from framework.server import serve


SERVICES = {
    "application": ("framework.layers.business_application.application_gateway.service", 8100),
    "engine": ("framework.layers.business_engine.engine_gateway.service", 8200),
    "foundation": ("framework.layers.foundation.foundation_gateway.service", 8300),
    "intent": ("framework.layers.business_engine.intent_analysis.service", 8000),
    "intent_original": ("framework.layers.business_engine.intent_analysis.delivered_engine.service", 8003),
    "workflow": ("framework.layers.business_engine.workflow_execution.service", 8020),
    "workflow_original": ("framework.layers.business_engine.workflow_execution.delivered_engine.service", 8021),
    "rule": ("framework.layers.business_engine.rule_calculation.service", 8010),
    "rule_original": ("framework.layers.business_engine.rule_calculation.delivered_engine.service", 8012),
    "content": ("framework.layers.business_engine.content_production.service", 8011),
    "content_original": ("framework.layers.business_engine.content_production.delivered_engine.service", 8013),
    "document_table_parsing": ("framework.layers.business_engine.document_table_parsing.service", 8036),
    "analysis_prediction": ("framework.layers.business_engine.analysis_prediction.service", 8030),
    "data_operation": ("framework.layers.business_engine.data_operation.service", 8031),
    "digital_asset": ("framework.layers.business_engine.digital_asset.service", 8032),
    "project_management": ("framework.layers.business_engine.project_management.service", 8033),
    "monitoring_reminder": ("framework.layers.business_engine.monitoring_reminder.service", 8034),
    "external_system_integration": ("framework.layers.business_engine.external_system_integration.service", 8037),
    "knowledge_qa": ("framework.layers.business_engine.knowledge_qa.service", 8038),
    "knowledge_map": ("framework.layers.business_engine.knowledge_map.service", 8039),
    "multimedia_generation": ("framework.layers.business_engine.multimedia_generation.service", 8035),
    "permission": ("framework.layers.foundation.permission.service", 8001),
    "model": ("framework.layers.foundation.model_dispatcher.service", 8002),
    "registry": ("framework.layers.foundation.capability_registry.service", 8400),
    "template": ("framework.layers.foundation.template_management.service", 8004),
    "context_prompt_management": ("framework.layers.foundation.context_prompt_management.service", 8059),
    "foundation_data": ("framework.layers.foundation.foundation_data.service", 8060),
    "account_gateway": ("framework.layers.foundation.account_gateway.service", 8050),
    "security_compliance": ("framework.layers.foundation.security_compliance.service", 8051),
    "human_collaboration": ("framework.layers.foundation.human_collaboration.service", 8052),
    "execution_sandbox": ("framework.layers.foundation.execution_sandbox.service", 8053),
    "evolution_mechanism": ("framework.layers.foundation.evolution_mechanism.service", 8054),
    "control_mechanism": ("framework.layers.foundation.control_mechanism.service", 8061),
    "knowledge_base": ("framework.layers.foundation.knowledge_base.service", 8055),
    "memory_management": ("framework.layers.foundation.memory_management.service", 8062),
    "device_system_interface": ("framework.layers.foundation.device_system_interface.service", 8063),
    "cost_control": ("framework.layers.foundation.cost_control.service", 8064),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=SERVICES)
    args = parser.parse_args()
    _, port = SERVICES[args.service]
    serve(args.service, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
