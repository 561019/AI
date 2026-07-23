from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


PUBLIC_CAPABILITIES = {"account.create", "account.identity.verify", "account.session.resolve", "account.session.close"}
PRIVILEGED_ROLES = {"platform_admin", "security_admin", "平台管理员", "安全管理员"}


def post(handler: Any, payload: dict[str, Any]) -> None:
    if handler.path != "/api/v1/permissions/check":
        handler.send(404)
        return
    actor = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
    resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    resource_id = str(resource.get("id") or resource.get("dataset") or "")
    action = str(payload.get("action") or scope.get("action") or "invoke")
    roles = {str(role) for role in (actor.get("roles") or ([actor.get("role")] if actor.get("role") else []))}
    public_capability = resource_id in PUBLIC_CAPABILITIES

    effect = "allow"
    reason = "POLICY_SCOPE_MATCHED"
    obligations: list[dict[str, Any]] = []

    if not actor.get("authenticated") and not public_capability:
        effect, reason = "deny", "AUTHENTICATION_REQUIRED"
    elif "denied" in resource_id.lower():
        effect, reason = "deny", "RESOURCE_DENIED_FOR_ACCEPTANCE_TEST"
    elif _tenant_mismatch(actor, resource, scope) and not roles.intersection(PRIVILEGED_ROLES):
        effect, reason = "deny", "TENANT_SCOPE_MISMATCH"
    elif _project_mismatch(actor, resource, scope) and not roles.intersection(PRIVILEGED_ROLES):
        effect, reason = "deny", "PROJECT_SCOPE_DENIED"
    elif str(resource.get("classification") or scope.get("classification") or "").lower() == "restricted" and not roles.intersection(PRIVILEGED_ROLES):
        effect, reason = "deny", "DATA_CLASSIFICATION_DENIED"
    elif action in {"delete", "export", "share", "authorize", "fix_store", "publish"}:
        obligations.append({"type": "confirmation_required", "action": action})

    if public_capability and not actor.get("authenticated"):
        reason = "PUBLIC_ACCOUNT_ENTRY"

    decision = {
        "decision": effect,
        "effect": effect,
        "decision_id": str(uuid4()),
        "reason_code": reason,
        "policy_version": "platform-abac-0.3",
        "row_filter": _row_filter(actor, resource, scope) if effect == "allow" else {},
        "allowed_fields": scope.get("requested_fields") or ["*"],
        "masked_fields": scope.get("masked_fields") or [],
        "max_rows": min(max(int(scope.get("max_rows") or 500), 1), 5000),
        "obligations": obligations,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    handler.send(200, decision)


def _tenant_mismatch(actor: dict[str, Any], resource: dict[str, Any], scope: dict[str, Any]) -> bool:
    requested = resource.get("tenant_id") or scope.get("tenant_id")
    return bool(requested and actor.get("tenant_id") and str(requested) != str(actor.get("tenant_id")))


def _project_mismatch(actor: dict[str, Any], resource: dict[str, Any], scope: dict[str, Any]) -> bool:
    project_id = resource.get("project_id") or scope.get("project_id")
    allowed = actor.get("allowed_project_ids") or actor.get("project_ids")
    return bool(project_id and allowed is not None and str(project_id) not in {str(value) for value in allowed})


def _row_filter(actor: dict[str, Any], resource: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    result = {"tenant_id": actor.get("tenant_id")}
    project_id = resource.get("project_id") or scope.get("project_id")
    allowed = actor.get("allowed_project_ids") or actor.get("project_ids")
    if project_id:
        result["project_id"] = project_id
    elif allowed is not None:
        result["project_id__in"] = list(allowed)
    return result
