from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterDecision:
    passed: bool
    detail: str
    reason_code: str | None = None


@dataclass(frozen=True)
class IdentityResolution:
    passed: bool
    detail: str
    actor_id: str | None = None
    verification_id: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class CodeArtifactReference:
    artifact_ref: str
    artifact_version: str
    source: str
    code_digest: str
    entrypoint: str
    generation_id: str
    content_url: str | None = None
    candidate_only: bool = True
    candidate_request_id: str | None = None


@dataclass(frozen=True)
class DigitalAssetCandidateRequest:
    trace_id: str
    request_id: str
    candidate_request_id: str
    business_type: str
    objective: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    assumptions: list[str]


@dataclass(frozen=True)
class SandboxRunRequest:
    trace_id: str
    artifact: CodeArtifactReference
    data_reference: str
    validation_requirements: list[str]
    resource_limits: dict[str, Any]


@dataclass(frozen=True)
class SandboxRunResult:
    run_id: str
    artifact_ref: str
    succeeded: bool
    detail: str
    result: dict[str, Any]
    validation_evidence: list[dict[str, Any]]
    environment: str
    reason_code: str | None = None


@dataclass(frozen=True)
class ExistingSystemCallRequest:
    trace_id: str
    request_id: str
    capability_code: str
    operation_ref: str
    data_reference: str
    business_object_id: str | None
    period: str | None
    invocation_config: dict[str, Any]


@dataclass(frozen=True)
class ExistingSystemCallResult:
    succeeded: bool
    detail: str
    invocation_id: str
    system_code: str
    operation_ref: str
    service_version: str
    returned_at: str
    result: dict[str, Any]
    data_reference: dict[str, Any]
    reason_code: str | None = None


@dataclass(frozen=True)
class ModelAnalysisRequest:
    trace_id: str
    request_id: str
    task_id: str | None
    subtask_id: str | None
    requester_id: str | None
    node_name: str | None
    task: str
    service_ref: str | None
    legacy_business_type: str | None
    requested_capability_code: str | None
    candidate_capabilities: list[dict[str, Any]]
    data_reference: str
    data_labels: list[str]


@dataclass(frozen=True)
class ModelAnalysisResult:
    analysis_id: str
    model_service: str
    model_version: str
    recommended_path: str
    candidate_capability_code: str | None
    extracted_parameters: dict[str, Any]
    missing_items: list[str]
    rationale: str
    confidence: float


class IdentityGatewayPort(Protocol):
    def resolve(self, identity_context_ref: str, trace_id: str) -> IdentityResolution: ...


class PermissionGatewayPort(Protocol):
    def check(
        self,
        operator_id: str,
        action: str,
        data_reference: str,
        data_labels: list[str] | None = None,
        allowed_data_actions: list[str] | None = None,
    ) -> AdapterDecision: ...


class SecurityGatewayPort(Protocol):
    def check(
        self, operator_id: str, action: str, data_labels: list[str] | None = None
    ) -> AdapterDecision: ...


class BusinessDataPort(Protocol):
    def read(
        self, data_reference: str, business_object_id: str | None, period: str | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...


class DeterministicExecutorPort(Protocol):
    def execute(self, rows: list[dict[str, Any]], rule_payload: dict[str, Any]) -> dict[str, Any]: ...


class ExecutorRegistryPort(Protocol):
    def resolve(self, implementation_ref: str) -> DeterministicExecutorPort: ...


class ResultValidatorPort(Protocol):
    def validate(self, result: dict[str, Any]) -> list[dict[str, Any]]: ...


class ValidatorRegistryPort(Protocol):
    def resolve(self, validation_ref: str) -> ResultValidatorPort: ...


class DigitalAssetGatewayPort(Protocol):
    def request_candidate_code(
        self, request: DigitalAssetCandidateRequest
    ) -> CodeArtifactReference: ...


class SandboxGatewayPort(Protocol):
    def run(self, request: SandboxRunRequest) -> SandboxRunResult: ...


class ExistingSystemGatewayPort(Protocol):
    def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult: ...


class ModelAnalysisGatewayPort(Protocol):
    def analyze(self, request: ModelAnalysisRequest) -> ModelAnalysisResult: ...


class CapabilityCatalogPort(Protocol):
    def capability_exists(self, capability_code: str) -> bool: ...

    def list_published_capabilities(
        self, business_type: str, capability_code: str | None = None
    ) -> list[dict[str, Any]]: ...

    def list_all_published_capabilities(self) -> list[dict[str, Any]]: ...

    def list_published_rule_versions(self, capability_code: str) -> list[dict[str, Any]]: ...


class RuleVersionRepositoryPort(Protocol):
    def create_draft(
        self,
        capability_code: str,
        rule_version: str,
        parameter_version: str,
        treatment_rule_version: str,
        payload: dict[str, Any],
        source_basis: str,
        review_role: str,
        entered_by: str,
    ) -> int: ...

    def get(self, rule_version_id: int) -> dict[str, Any] | None: ...

    def apply_transition(
        self,
        rule_version_id: int,
        capability_code: str,
        from_status: str,
        to_status: str,
        action: str,
        actor_id: str,
        comment: str,
        reviewed_at: str | None = None,
        effective_at: str | None = None,
        retire_previous_published: bool = False,
    ) -> None: ...


class ExecutionRecordPort(Protocol):
    def save_execution(self, record: dict[str, Any]) -> None: ...

    def get_by_trace(self, trace_id: str) -> dict[str, Any] | None: ...

    def get_by_id(self, execution_record_id: str) -> dict[str, Any] | None: ...

    def has_human_handling(self, execution_record_id: str) -> bool: ...

    def get_human_handling(self, execution_record_id: str) -> dict[str, Any] | None: ...

    def save_human_handling(self, record: dict[str, Any]) -> None: ...

    def update_execution_state(
        self, execution_record_id: str, state: str, handling_type: str, reason_code: str | None
    ) -> None: ...


class IdempotencyRecordPort(Protocol):
    def get_idempotency(
        self, caller_service_code: str, action: str, idempotency_key: str
    ) -> dict[str, Any] | None: ...

    def claim_idempotency(self, record: dict[str, Any]) -> bool: ...

    def delete_idempotency(
        self, caller_service_code: str, action: str, idempotency_key: str
    ) -> None: ...

    def complete_idempotency(
        self,
        caller_service_code: str,
        action: str,
        idempotency_key: str,
        status: str,
        execution_record_id: str | None,
        reply: dict[str, Any],
        updated_at: str,
    ) -> None: ...
