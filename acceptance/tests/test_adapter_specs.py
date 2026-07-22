from __future__ import annotations

from framework.adapter_specs import ADAPTER_SPECS, get_adapter_spec
from framework.module_catalog import additional_capabilities


def test_all_inserted_capabilities_have_adapter_specs() -> None:
    missing = [row[0] for row in additional_capabilities() if row[0] not in ADAPTER_SPECS]
    assert missing == []


def test_account_lifecycle_adapter_specs_are_bound_to_real_gateway_routes() -> None:
    create = get_adapter_spec("account.create")
    freeze = get_adapter_spec("account.freeze")
    offboarding = get_adapter_spec("account.offboarding_assets.query")

    assert create is not None
    assert create.method == "POST"
    assert create.path == "/api/accounts"
    assert create.upstream_env == "ACCOUNT_GATEWAY_UPSTREAM_URL"
    assert create.auth_token_env == "ACCOUNT_GATEWAY_ADMIN_TOKEN"

    assert freeze is not None
    assert freeze.path == "/api/accounts/{name}/freeze"

    assert offboarding is not None
    assert offboarding.method == "GET"
    assert offboarding.path == "/api/accounts/{name}/offboarding-assets"


def test_known_delivered_module_routes_are_recorded() -> None:
    expected = {
        "document.parse": "/api/v1/document-parsing/tasks",
        "analysis.financial_statement": "/v1/analysis-jobs/evaluate",
        "data.search": "/api/l2/tasks",
        "asset.create": "/api/flow/tasks",
        "project.register.simple": "/api/v1/l2/internal/messages",
        "monitor.item.register": "/api/v1/l2/internal/messages",
        "knowledge.query": "/api/v1/knowledge-qa/tasks",
        "knowledge.retrieve": "/api/v1/knowledge/tasks",
    }
    for capability, path in expected.items():
        spec = get_adapter_spec(capability)
        assert spec is not None
        assert spec.path == path
