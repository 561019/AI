from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProcessingState(str, Enum):
    AUTOMATIC_PASS = "automatic_pass"
    WAITING_HUMAN = "waiting_human"
    BLOCKED = "blocked"


class HandlingType(str, Enum):
    CONFIRM_EFFECTIVE = "confirm_effective"
    EXCEPTION_DISPOSAL = "exception_disposal"
    SUPPLEMENT_AND_RECALCULATE = "supplement_and_recalculate"
    AUTHORIZE_AI_GENERATION = "authorize_ai_generation"
    REVIEW_SANDBOX_RESULT = "review_sandbox_result"


class HumanAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    SUPPLEMENT_AND_RECALCULATE = "supplement_and_recalculate"


class ExecutionPath(str, Enum):
    DETERMINISTIC = "deterministic"
    EXISTING_SYSTEM = "existing_system"
    SANDBOX = "sandbox"


class ModelRoutingAnalysis(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    analysis_id: str = Field(min_length=1)
    model_service: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    recommended_path: ExecutionPath
    candidate_capability_code: str | None = None
    extracted_parameters: dict[str, Any] = Field(default_factory=dict)
    missing_items: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class RoutingDecision(BaseModel):
    accepted_model_recommendation: bool
    selected_path: ExecutionPath | None = None
    selected_capability_code: str | None = None
    decision_code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class RuleVersionStatus(str, Enum):
    DRAFT = "draft"
    TESTING = "testing"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    RETIRED = "retired"


class RuleVersionAction(str, Enum):
    START_TESTING = "start_testing"
    SUBMIT_REVIEW = "submit_review"
    APPROVE_PUBLISH = "approve_publish"
    RETIRE = "retire"


class RequestDataReference(BaseModel):
    reference_id: str = Field(min_length=2, max_length=200)
    purpose: str | None = Field(default=None, min_length=2, max_length=80)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    data_labels: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)


class TemporaryAnalysisSpec(BaseModel):
    objective: str = Field(min_length=4, max_length=1000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)


class PreconditionQueryRequirement(BaseModel):
    """A bounded dependency query requested before calculation can begin."""

    query_type: str = Field(min_length=2, max_length=80)
    purpose: str = Field(min_length=4, max_length=300)
    required: bool = True
    query_hints: dict[str, str] = Field(default_factory=dict)


class PreconditionAssessmentRequest(BaseModel):
    """Initial request assessment before business data references are available."""

    trace_id: str = Field(min_length=4, max_length=80)
    request_id: str = Field(min_length=4, max_length=80)
    task_id: str | None = Field(default=None, min_length=1, max_length=100)
    subtask_id: str | None = Field(default=None, min_length=1, max_length=100)
    requester_id: str | None = Field(default=None, min_length=1, max_length=100)
    node_name: str | None = Field(default=None, min_length=1, max_length=200)
    task: str | None = Field(default=None, min_length=2, max_length=2000)
    service_ref: str | None = Field(default=None, min_length=2, max_length=200)
    identity_context_ref: str = Field(min_length=8, max_length=200)
    claimed_actor_id: str | None = Field(default=None, min_length=1, max_length=100)
    business_type: str | None = Field(default=None, min_length=2, max_length=100)
    requested_capability_code: str | None = Field(default=None, min_length=2, max_length=80)
    business_object_id: str | None = Field(default=None, min_length=2, max_length=100)
    period: str | None = Field(default=None, min_length=2, max_length=40)

    @model_validator(mode="after")
    def require_task_description(self) -> "PreconditionAssessmentRequest":
        if not self.task and not self.business_type:
            raise ValueError("Either task or the legacy business_type hint is required.")
        return self


class PreconditionAssessmentResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    state: str = Field(min_length=2, max_length=80)
    reason_code: str | None = None
    message: str = Field(min_length=2)
    model_analysis: ModelRoutingAnalysis | None = None
    query_requirements: list[PreconditionQueryRequirement] = Field(default_factory=list)
    clarification_items: list[str] = Field(default_factory=list)


class ExecutionRequest(BaseModel):
    trace_id: str = Field(min_length=4, max_length=80)
    request_id: str = Field(min_length=4, max_length=80)
    task_id: str | None = Field(default=None, min_length=1, max_length=100)
    subtask_id: str | None = Field(default=None, min_length=1, max_length=100)
    requester_id: str | None = Field(default=None, min_length=1, max_length=100)
    node_name: str | None = Field(default=None, min_length=1, max_length=200)
    task: str | None = Field(default=None, min_length=2, max_length=2000)
    service_ref: str | None = Field(default=None, min_length=2, max_length=200)
    identity_context_ref: str = Field(min_length=8, max_length=200)
    claimed_actor_id: str | None = Field(default=None, min_length=1, max_length=100)
    business_type: str | None = Field(default=None, min_length=2, max_length=100)
    requested_capability_code: str | None = None
    business_object_id: str | None = Field(default=None, min_length=2, max_length=100)
    period: str | None = Field(default=None, min_length=2, max_length=40)
    calculation_as_of: datetime | None = None
    data_reference: str = Field(min_length=2, max_length=200)
    request_data_references: list[RequestDataReference] = Field(default_factory=list)
    data_labels: list[str] = Field(default_factory=list)
    allowed_data_actions: list[str] = Field(default_factory=list)
    temporary_analysis_spec: TemporaryAnalysisSpec | None = None

    @model_validator(mode="after")
    def require_task_description(self) -> "ExecutionRequest":
        if not self.task and not self.business_type:
            raise ValueError("Either task or the legacy business_type hint is required.")
        return self


class VersionReference(BaseModel):
    capability_code: str
    capability_version: str
    rule_version: str
    parameter_version: str
    treatment_rule_version: str


class DataReference(BaseModel):
    reference_id: str
    source_system: str
    source_description: str
    source_version: str
    data_digest: str
    retrieved_at: str
    row_count: int


class ExistingSystemReference(BaseModel):
    invocation_id: str = Field(min_length=1)
    system_code: str = Field(min_length=1)
    operation_ref: str = Field(min_length=1)
    service_version: str = Field(min_length=1)
    returned_at: str = Field(min_length=1)


class CandidateAssetReference(BaseModel):
    artifact_ref: str = Field(min_length=1)
    artifact_version: str = Field(min_length=1)
    source: str = Field(min_length=1)
    code_digest: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    candidate_only: bool = True


class CandidateImplementationReference(CandidateAssetReference):
    """Candidate implementation returned through the Flow Execution Engine.

    ``content_url`` is optional because a real L1.14 Agent Execution Sandbox may
    resolve an implementation reference internally. The local sandbox simulator
    uses it only to fetch the candidate content during integration tests.
    """

    candidate_request_id: str = Field(min_length=4, max_length=100)
    content_url: str | None = None


class CandidateSkillCreationRequest(BaseModel):
    """A dependency request for the Flow Execution Engine, not an asset command."""

    trace_id: str
    request_id: str
    authorization_execution_record_id: str
    candidate_request_id: str
    requester_id: str
    task: str
    business_type: str | None = None
    data_references: list[RequestDataReference] = Field(default_factory=list)
    temporary_analysis_spec: TemporaryAnalysisSpec
    validation_requirements: list[str] = Field(default_factory=list)


class SandboxExecutionReference(BaseModel):
    run_id: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    environment: str = Field(min_length=1)


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class ExecutionResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    trace_id: str
    request_id: str
    state: ProcessingState
    execution_path: ExecutionPath | None = None
    handling_type: HandlingType | None = None
    reason_code: str | None = None
    message: str
    versions: VersionReference | None = None
    data_references: list[DataReference] = Field(default_factory=list)
    existing_system_reference: ExistingSystemReference | None = None
    candidate_asset_reference: CandidateAssetReference | None = None
    sandbox_execution_reference: SandboxExecutionReference | None = None
    model_analysis: ModelRoutingAnalysis | None = None
    routing_decision: RoutingDecision | None = None
    result: dict[str, Any] | None = None
    validation: list[ValidationCheck] = Field(default_factory=list)
    execution_record_id: str | None = None


class HumanHandlingRequest(BaseModel):
    identity_context_ref: str = Field(min_length=8, max_length=200)
    action: HumanAction
    comment: str = Field(min_length=2, max_length=500)


class HumanHandlingResult(BaseModel):
    execution_record_id: str
    trace_id: str
    state: ProcessingState
    reason_code: str | None = None
    message: str
    handling_record_id: str
    next_execution_record_id: str | None = None
    candidate_skill_creation_request: CandidateSkillCreationRequest | None = None


class CandidateSkillTrialRequest(BaseModel):
    """Flow-mediated continuation after the Digital Asset Engine returns a candidate."""

    identity_context_ref: str = Field(min_length=8, max_length=200)
    candidate_implementation: CandidateImplementationReference


class RuleVersionDraftRequest(BaseModel):
    capability_code: str = Field(min_length=2, max_length=80)
    rule_version: str = Field(min_length=2, max_length=80)
    parameter_version: str = Field(min_length=2, max_length=80)
    treatment_rule_version: str = Field(min_length=2, max_length=80)
    payload: dict[str, Any]
    source_basis: str = Field(min_length=4, max_length=300)
    review_role: str = Field(min_length=2, max_length=80)
    identity_context_ref: str = Field(min_length=8, max_length=200)


class RuleVersionTransitionRequest(BaseModel):
    identity_context_ref: str = Field(min_length=8, max_length=200)
    action: RuleVersionAction
    comment: str = Field(min_length=2, max_length=500)


class RuleVersionResult(BaseModel):
    rule_version_id: int
    capability_code: str
    rule_version: str
    parameter_version: str
    treatment_rule_version: str
    status: RuleVersionStatus
    source_basis: str
    review_role: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    effective_at: str | None = None
