from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceRegistration:
    service_id: str
    module_id: str
    command: str
    allowed_callers: frozenset[str]
    required_permission_action: str
    resource_type: str
    target_url: str | None = None
    status: str = "active"


# This registry intentionally contains routes, not copies of module facts.
# Production replaces it with an audited registry database/control plane.
REGISTRY_VERSION = "v1-20260717"
REGISTRY = {
    "account.identity_context.v1": ServiceRegistration(
        service_id="account.identity_context.v1", module_id="account_gateway",
        command="identity.context.read_self", allowed_callers=frozenset({"content_generation", "workflow_engine", "login_engine", "e2e_business_engine"}),
        required_permission_action="identity.context.read_self", resource_type="identity_context",
        target_url="http://127.0.0.1:8080/api/layer/identity-context",
    ),
    "account.authenticate.v1": ServiceRegistration(
        service_id="account.authenticate.v1", module_id="account_gateway",
        command="identity.authenticate", allowed_callers=frozenset({"login_engine"}),
        required_permission_action="identity.authenticate", resource_type="identity",
        target_url="http://127.0.0.1:8080/login",
    ),
    # Local E2E target. It only confirms that the channel forwarded an
    # already-authorized command and is never an authorization authority.
    "test.permission_probe.v1": ServiceRegistration(
        service_id="test.permission_probe.v1", module_id="account_gateway_test_target",
        command="permission.probe.execute", allowed_callers=frozenset({"e2e_business_engine"}),
        required_permission_action="*", resource_type="*",
        target_url="http://127.0.0.1:8080/api/layer/permission-probe",
    ),
}


def find(service_id: str, command: str, caller: str) -> ServiceRegistration | None:
    item = REGISTRY.get(service_id)
    if not item or item.status != "active" or item.command != command or caller not in item.allowed_callers:
        return None
    return item
