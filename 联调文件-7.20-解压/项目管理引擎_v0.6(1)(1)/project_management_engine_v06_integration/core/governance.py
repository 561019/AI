from __future__ import annotations

from core.errors import BusinessError


class ActionGovernanceGuard:
    def __init__(self, repository, account_gateway, permission_management, security_compliance):
        self.repository = repository
        self.account_gateway = account_gateway
        self.permission_management = permission_management
        self.security_compliance = security_compliance

    def authorize(self, *, actor_person_id, action, trace_id, resource_scope=None, payload=None, project_id=None, basis_ref=None):
        resource_scope = resource_scope or {}
        payload = payload or {}
        person = self.account_gateway.resolve_person(actor_person_id)
        if not person["active"]:
            raise BusinessError("ACTOR_INACTIVE", "当前操作真人账号不是有效状态", http_status=403)

        decision = self.permission_management.decide(
            person_id=actor_person_id,
            action=action,
            resource_scope=resource_scope,
            allowed_actions=[action],
            basis_ref=basis_ref,
        )
        security = self.security_compliance.inspect(
            person_id=actor_person_id,
            action=action,
            resource_scope=resource_scope,
            payload=payload,
        )
        self.repository.append_action_decision({
            "project_id": project_id,
            "actor_person_id": actor_person_id,
            "action": action,
            "resource_scope": resource_scope,
            "decision_id": decision["decision_id"],
            "permission_result": "ALLOW" if decision["allow"] else "DENY",
            "permission_reason": decision["reason"],
            "audit_ref": security["audit_ref"],
            "security_result": "ALLOW" if security["allow"] else "BLOCK",
            "security_reason": security["reason"],
            "trace_id": trace_id,
        })
        if not decision["allow"]:
            raise BusinessError("ACTION_PERMISSION_DENIED", "权限管理拒绝当前动作", http_status=403)
        if not security["allow"]:
            raise BusinessError("SECURITY_COMPLIANCE_BLOCKED", "安全合规检查阻断当前动作", http_status=422)
        return {
            "actor": {"person_id": person["person_id"], "tenant_id": person["tenant_id"], "position_code": person["position_code"]},
            "permission": {"decision_id": decision["decision_id"], "result": "ALLOW", "reason": decision["reason"]},
            "security": {"audit_ref": security["audit_ref"], "result": "ALLOW", "obligations": security["obligations"]},
        }
