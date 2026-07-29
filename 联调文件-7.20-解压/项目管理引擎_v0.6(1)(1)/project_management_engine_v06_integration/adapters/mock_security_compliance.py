from __future__ import annotations

from uuid import uuid4


def _contains_block(value):
    if isinstance(value, dict):
        return any(_contains_block(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_block(v) for v in value)
    return "BLOCK_SECURITY" in str(value)


class MockSecurityCompliance:
    """模拟 L1.9 安全合规：输入输出检查、脱敏义务和 audit_ref。"""

    def inspect(self, *, person_id, action, resource_scope, payload):
        allowed = not str(person_id).startswith("BLOCK_SECURITY_") and not _contains_block(payload)
        return {
            "allow": allowed,
            "audit_ref": "AUDIT_" + uuid4().hex[:14].upper(),
            "reason": "MOCK_SECURITY_ALLOW" if allowed else "MOCK_SECURITY_BLOCKED",
            "obligations": ["MASK_SENSITIVE_FIELDS"] if action.endswith("read") or "query" in action else [],
            "action": action,
            "resource_scope": resource_scope,
            "mock": True,
        }
