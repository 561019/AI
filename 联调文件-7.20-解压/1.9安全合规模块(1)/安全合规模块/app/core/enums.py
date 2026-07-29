from enum import Enum


class StrEnum(str, Enum):
    """Python 3.10 compatible StrEnum backport."""
    pass


class Stage(StrEnum):
    BEFORE_DATA_ACCESS = "before_data_access"
    AFTER_DATA_ACCESS = "after_data_access"
    BEFORE_MODEL_CALL = "before_model_call"
    AFTER_MODEL_OUTPUT = "after_model_output"
    BEFORE_EXTERNAL_OUTPUT = "before_external_output"
    BEFORE_ACTION_EXECUTE = "before_action_execute"
    AFTER_ACTION_EXECUTE = "after_action_execute"
    PERMISSION_TRANSFER = "permission_transfer"
    EMERGENCY_ACCESS = "emergency_access"
    AUDIT_ONLY = "audit_only"


class Decision(StrEnum):
    ALLOW = "allow"
    ALLOW_WITH_OBLIGATIONS = "allow_with_obligations"
    REQUIRE_SELF_CONFIRMATION = "require_self_confirmation"
    REQUIRE_POLICY_APPROVER_CONFIRMATION = "require_policy_approver_confirmation"
    DENY_OVER_SCOPE = "deny_over_scope"
    DENY_COMPLIANCE_RISK = "deny_compliance_risk"
    AUDIT_ONLY = "audit_only"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ModelScope(StrEnum):
    EXTERNAL_ALLOWED = "external_allowed"
    PRIVATE_ONLY = "private_only"
    LOCAL_ONLY = "local_only"
    FORBIDDEN = "forbidden"
