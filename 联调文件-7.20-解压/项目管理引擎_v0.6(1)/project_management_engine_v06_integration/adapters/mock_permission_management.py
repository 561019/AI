from __future__ import annotations
from uuid import uuid4


class MockPermissionManagement:
    """模拟 L1.1 权限管理，返回 allow/deny、decision_id 和动作范围。"""

    def decide(self, *, person_id, action, resource_scope, allowed_actions=None, valid_from=None, valid_until=None, basis_ref=None):
        allow = True
        reason = "MOCK_ALLOW"
        pid = str(person_id)
        if pid.startswith("DENY_ACTION_"):
            allow, reason = False, "MOCK_ACTION_PERMISSION_DENIED"
        if action == "project.member.authorize" and pid.startswith("DENY_AUTH_"):
            allow, reason = False, "MOCK_AUTHORIZATION_DENIED"
        if action == "project.member.revoke" and pid.startswith("DENY_REVOKE_"):
            allow, reason = False, "MOCK_REVOCATION_DENIED"
        if action == "project.member.update" and pid.startswith("DENY_UPDATE_"):
            allow, reason = False, "MOCK_MEMBER_UPDATE_DENIED"
        if action == "project.archive.access.authorize" and pid.startswith("DENY_ARCHIVE_AUTH_"):
            allow, reason = False, "MOCK_ARCHIVE_AUTHORIZATION_DENIED"
        return {
            "allow": allow,
            "decision_id": "DECISION_" + uuid4().hex[:12].upper(),
            "reason": reason,
            "person_id": person_id,
            "action": action,
            "resource_scope": resource_scope,
            "allowed_actions": allowed_actions or [],
            "valid_from": valid_from,
            "valid_until": valid_until,
            "basis_ref": basis_ref,
            "obligations": [],
            "mock": True,
        }
