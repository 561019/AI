from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapters import (
    LocalExistingSystemAdapter,
    LocalIdentityAdapter,
    LocalModelAnalysisAdapter,
    LocalPermissionAdapter,
    LocalSecurityAdapter,
    LocalSandboxAdapter,
    SQLiteBusinessDataProvider,
)
from .contracts import (
    CandidateAssetReference,
    CandidateImplementationReference,
    CandidateSkillCreationRequest,
    CandidateSkillTrialRequest,
    DataReference,
    ExecutionPath,
    ExecutionRequest,
    ExecutionResult,
    ExistingSystemReference,
    HandlingType,
    HumanAction,
    HumanHandlingRequest,
    HumanHandlingResult,
    ModelRoutingAnalysis,
    PreconditionAssessmentRequest,
    PreconditionAssessmentResult,
    PreconditionQueryRequirement,
    ProcessingState,
    RequestDataReference,
    RoutingDecision,
    RuleVersionAction,
    RuleVersionDraftRequest,
    RuleVersionResult,
    RuleVersionStatus,
    RuleVersionTransitionRequest,
    SandboxExecutionReference,
    ValidationCheck,
    VersionReference,
)
from .executors import ExecutorRegistry
from .ports import (
    CapabilityCatalogPort,
    BusinessDataPort,
    CodeArtifactReference,
    ExecutorRegistryPort,
    ExistingSystemCallRequest,
    ExistingSystemGatewayPort,
    ExecutionRecordPort,
    IdentityGatewayPort,
    IdentityResolution,
    ModelAnalysisGatewayPort,
    ModelAnalysisRequest,
    PermissionGatewayPort,
    RuleVersionRepositoryPort,
    SandboxGatewayPort,
    SandboxRunRequest,
    SecurityGatewayPort,
    ValidatorRegistryPort,
)
from .sqlite_repositories import SQLitePlatformDataAdapter
from .validators import ValidatorRegistry


class RuleEngineService:
    """Coordinates a deterministic capability; it does not contain business arithmetic itself."""

    def __init__(
        self,
        database_path: Path,
        identity: IdentityGatewayPort | None = None,
        permission: PermissionGatewayPort | None = None,
        security: SecurityGatewayPort | None = None,
        data_provider: BusinessDataPort | None = None,
        executor_registry: ExecutorRegistryPort | None = None,
        validator_registry: ValidatorRegistryPort | None = None,
        capability_catalog: CapabilityCatalogPort | None = None,
        rule_versions: RuleVersionRepositoryPort | None = None,
        execution_records: ExecutionRecordPort | None = None,
        model_analysis_gateway: ModelAnalysisGatewayPort | None = None,
        existing_system_gateway: ExistingSystemGatewayPort | None = None,
        sandbox_gateway: SandboxGatewayPort | None = None,
    ) -> None:
        self.database_path = database_path
        local_platform_data = SQLitePlatformDataAdapter(database_path)
        self.identity = identity or LocalIdentityAdapter()
        self.permission = permission or LocalPermissionAdapter()
        self.security = security or LocalSecurityAdapter()
        self.data_provider = data_provider or SQLiteBusinessDataProvider(database_path)
        self.executor_registry = executor_registry or ExecutorRegistry()
        self.validator_registry = validator_registry or ValidatorRegistry()
        self.capability_catalog = capability_catalog or local_platform_data
        self.rule_versions = rule_versions or local_platform_data
        self.execution_records = execution_records or local_platform_data
        self.model_analysis_gateway = model_analysis_gateway or LocalModelAnalysisAdapter()
        self.existing_system_gateway = existing_system_gateway or LocalExistingSystemAdapter()
        digital_asset_simulator_url = os.getenv("DIGITAL_ASSET_SIMULATOR_URL", "").strip()
        if sandbox_gateway is not None:
            self.sandbox_gateway = sandbox_gateway
        elif digital_asset_simulator_url:
            from .http_adapters import RestrictedLocalSandboxAdapter

            self.sandbox_gateway = RestrictedLocalSandboxAdapter(database_path)
        else:
            self.sandbox_gateway = LocalSandboxAdapter()

    def assess_preconditions(
        self, request: PreconditionAssessmentRequest
    ) -> PreconditionAssessmentResult:
        """Identify bounded rule, capability, and data queries before execution.

        This stage does not read business data or run any calculation. The model
        may help classify the task, while the returned requirements remain a
        deterministic, reviewable request for the Flow Execution Engine.
        """
        identity = self.identity.resolve(request.identity_context_ref, request.trace_id)
        if not identity.passed:
            return PreconditionAssessmentResult(
                state="blocked",
                reason_code=identity.reason_code,
                message=identity.detail,
            )
        if request.claimed_actor_id and request.claimed_actor_id != identity.actor_id:
            return PreconditionAssessmentResult(
                state="blocked",
                reason_code="ACTOR_IDENTITY_MISMATCH",
                message="The actor declared by the platform envelope does not match the human resolved by L1.8.",
            )

        request_scope = request.business_object_id or request.task_id or "rule-calculation-request"
        request_permission = self.permission.check(
            identity.actor_id,
            "rule.calculate.request",
            request_scope,
            [],
            [],
        )
        if not request_permission.passed:
            return PreconditionAssessmentResult(
                state="blocked",
                reason_code=request_permission.reason_code,
                message=request_permission.detail,
            )
        request_security = self.security.check(
            identity.actor_id, "rule.calculate.request", []
        )
        if not request_security.passed:
            return PreconditionAssessmentResult(
                state="blocked",
                reason_code=request_security.reason_code,
                message=request_security.detail,
            )

        candidate_capabilities = self.capability_catalog.list_all_published_capabilities()
        try:
            raw_model_analysis = self.model_analysis_gateway.analyze(
                ModelAnalysisRequest(
                    trace_id=request.trace_id,
                    request_id=request.request_id,
                    task_id=request.task_id,
                    subtask_id=request.subtask_id,
                    requester_id=request.requester_id,
                    node_name=request.node_name,
                    task=request.task or request.business_type or "",
                    service_ref=request.service_ref,
                    legacy_business_type=request.business_type,
                    requested_capability_code=request.requested_capability_code,
                    candidate_capabilities=[
                        self._capability_summary(item) for item in candidate_capabilities
                    ],
                    data_reference=f"precondition:{request.task_id or request.request_id}",
                    data_labels=[],
                )
            )
            model_analysis = ModelRoutingAnalysis(
                analysis_id=raw_model_analysis.analysis_id,
                model_service=raw_model_analysis.model_service,
                model_version=raw_model_analysis.model_version,
                recommended_path=ExecutionPath(raw_model_analysis.recommended_path),
                candidate_capability_code=raw_model_analysis.candidate_capability_code,
                extracted_parameters=raw_model_analysis.extracted_parameters,
                missing_items=raw_model_analysis.missing_items,
                rationale=raw_model_analysis.rationale,
                confidence=raw_model_analysis.confidence,
            )
        except (ConnectionError, TimeoutError, TypeError, ValueError) as error:
            return PreconditionAssessmentResult(
                state="blocked",
                reason_code="MODEL_ANALYSIS_UNAVAILABLE",
                message=f"Model analysis through L1.5 did not return a valid result: {error}",
            )

        if model_analysis.missing_items:
            return PreconditionAssessmentResult(
                state="clarification_required",
                reason_code="CALCULATION_CONDITIONS_INCOMPLETE",
                message="The calculation task needs clarification before limited dependency queries can be issued.",
                model_analysis=model_analysis,
                clarification_items=model_analysis.missing_items,
            )

        hints = {
            key: value
            for key, value in {
                "task": request.task,
                "business_type": request.business_type,
                "requested_capability_code": request.requested_capability_code,
                "business_object_id": request.business_object_id,
                "period": request.period,
            }.items()
            if value is not None
        }
        return PreconditionAssessmentResult(
            state="precondition_query_required",
            message="The engine has completed initial assessment and requires bounded references before path selection and execution.",
            model_analysis=model_analysis,
            query_requirements=[
                PreconditionQueryRequirement(
                    query_type="formal_calculation_basis",
                    purpose="Locate effective policy, formula, parameter table, and version applicable to this calculation task.",
                    query_hints=hints,
                ),
                PreconditionQueryRequirement(
                    query_type="published_calculation_capability",
                    purpose="Locate a registered, published, callable calculation Skill, fixed implementation, or existing-system operation.",
                    query_hints=hints,
                ),
                PreconditionQueryRequirement(
                    query_type="authorized_business_data",
                    purpose="Return only the approved business-data references required by the applicable calculation basis.",
                    query_hints=hints,
                ),
            ],
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        identity = self.identity.resolve(request.identity_context_ref, request.trace_id)
        if not identity.passed:
            return self._blocked(request, identity.reason_code, identity.detail, identity=identity)
        if request.claimed_actor_id and request.claimed_actor_id != identity.actor_id:
            return self._blocked(
                request,
                "ACTOR_IDENTITY_MISMATCH",
                "The actor declared by the platform envelope does not match the human resolved by L1.8.",
                identity=identity,
            )

        request_permission = self.permission.check(
            identity.actor_id,
            "rule.calculate.request",
            request.data_reference,
            request.data_labels,
            request.allowed_data_actions,
        )
        if not request_permission.passed:
            return self._blocked(
                request,
                request_permission.reason_code,
                request_permission.detail,
                identity=identity,
            )
        request_security = self.security.check(
            identity.actor_id, "rule.calculate.request", request.data_labels
        )
        if not request_security.passed:
            return self._blocked(
                request,
                request_security.reason_code,
                request_security.detail,
                identity=identity,
            )

        candidate_capabilities = self.capability_catalog.list_all_published_capabilities()
        try:
            raw_model_analysis = self.model_analysis_gateway.analyze(
                ModelAnalysisRequest(
                    trace_id=request.trace_id,
                    request_id=request.request_id,
                    task_id=request.task_id,
                    subtask_id=request.subtask_id,
                    requester_id=request.requester_id,
                    node_name=request.node_name,
                    task=request.task or request.business_type or "",
                    service_ref=request.service_ref,
                    legacy_business_type=request.business_type,
                    requested_capability_code=request.requested_capability_code,
                    candidate_capabilities=[
                        self._capability_summary(item) for item in candidate_capabilities
                    ],
                    data_reference=request.data_reference,
                    data_labels=list(request.data_labels),
                )
            )
            model_analysis = ModelRoutingAnalysis(
                analysis_id=raw_model_analysis.analysis_id,
                model_service=raw_model_analysis.model_service,
                model_version=raw_model_analysis.model_version,
                recommended_path=ExecutionPath(raw_model_analysis.recommended_path),
                candidate_capability_code=raw_model_analysis.candidate_capability_code,
                extracted_parameters=raw_model_analysis.extracted_parameters,
                missing_items=raw_model_analysis.missing_items,
                rationale=raw_model_analysis.rationale,
                confidence=raw_model_analysis.confidence,
            )
        except (ConnectionError, TimeoutError, TypeError, ValueError) as error:
            return self._blocked(
                request,
                "MODEL_ANALYSIS_UNAVAILABLE",
                f"Model analysis through L1.5 did not return a valid result: {error}",
                identity=identity,
                routing_decision=RoutingDecision(
                    accepted_model_recommendation=False,
                    decision_code="MODEL_ANALYSIS_UNAVAILABLE",
                    detail="The mandatory model analysis through L1.5 could not be completed.",
                ),
            )

        matching_capabilities = [
            item
            for item in candidate_capabilities
            if (
                request.business_type is None
                or item.get("scenario") == request.business_type
            )
            and (
                request.requested_capability_code is None
                or item.get("capability_code") == request.requested_capability_code
            )
        ]
        if model_analysis.missing_items:
            reason_code = (
                "AMBIGUOUS_CAPABILITY_MATCH"
                if "capability_disambiguation" in model_analysis.missing_items
                else "MODEL_ANALYSIS_INCOMPLETE"
            )
            return self._blocked(
                request,
                reason_code,
                "The mandatory model analysis identified missing information and no formal capability can be locked safely.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=RoutingDecision(
                    accepted_model_recommendation=False,
                    decision_code=reason_code,
                    detail="Model-reported missing items require clarification before execution.",
                ),
            )
        if model_analysis.candidate_capability_code is None:
            if model_analysis.recommended_path != ExecutionPath.SANDBOX:
                return self._blocked(
                    request,
                    "MODEL_RECOMMENDATION_INCONSISTENT",
                    "The model recommended a formal path without identifying a registered capability.",
                    identity=identity,
                    model_analysis=model_analysis,
                    routing_decision=RoutingDecision(
                        accepted_model_recommendation=False,
                        decision_code="MODEL_RECOMMENDATION_INCONSISTENT",
                        detail="A formal path requires a registered candidate capability.",
                    ),
                )
            if request.business_type is None and request.requested_capability_code:
                requested = [
                    item
                    for item in candidate_capabilities
                    if item.get("capability_code")
                    == request.requested_capability_code
                ]
                if len(requested) == 1:
                    return self._blocked(
                        request,
                        "MODEL_IGNORED_EXPLICIT_CAPABILITY",
                        "The model selected the sandbox path without assessing the explicitly requested published capability.",
                        identity=identity,
                        model_analysis=model_analysis,
                        routing_decision=RoutingDecision(
                            accepted_model_recommendation=False,
                            decision_code="MODEL_IGNORED_EXPLICIT_CAPABILITY",
                            detail="The explicit capability must be assessed before the task can enter the sandbox path.",
                        ),
                    )
            routing_decision = RoutingDecision(
                accepted_model_recommendation=True,
                selected_path=ExecutionPath.SANDBOX,
                decision_code="NO_FORMAL_CAPABILITY_CONFIRMED",
                detail="Model analysis identified no formal capability, and no registered capability was selected for execution.",
            )
            return self._await_ai_authorization(
                request, identity, model_analysis, routing_decision
            )

        selected = [
            item
            for item in candidate_capabilities
            if item.get("capability_code") == model_analysis.candidate_capability_code
        ]
        if len(selected) != 1:
            return self._blocked(
                request,
                "MODEL_RECOMMENDED_CAPABILITY_NOT_REGISTERED",
                "The model recommended a capability that is not uniquely registered and published.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=RoutingDecision(
                    accepted_model_recommendation=False,
                    decision_code="MODEL_RECOMMENDED_CAPABILITY_NOT_REGISTERED",
                    detail="The model candidate was rejected by the governed capability catalogue.",
                ),
            )
        capability = selected[0]
        if capability not in matching_capabilities:
            return self._blocked(
                request,
                "MODEL_RECOMMENDED_CAPABILITY_NOT_APPLICABLE",
                "The model-recommended capability does not match the governed task scope or explicit capability hint.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=RoutingDecision(
                    accepted_model_recommendation=False,
                    decision_code="MODEL_RECOMMENDED_CAPABILITY_NOT_APPLICABLE",
                    detail="The candidate failed deterministic scope validation.",
                ),
            )
        selected_path = self._path_for_capability_type(capability.get("capability_type"))
        if selected_path is None:
            return self._blocked(
                request,
                "CAPABILITY_TYPE_UNSUPPORTED",
                f"The registered capability type is not available in the current implementation: {capability.get('capability_type')}",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=RoutingDecision(
                    accepted_model_recommendation=False,
                    decision_code="CAPABILITY_TYPE_UNSUPPORTED",
                    detail="The registered capability type has no supported execution path.",
                ),
            )
        if model_analysis.recommended_path != selected_path:
            return self._blocked(
                request,
                "MODEL_PATH_CAPABILITY_CONFLICT",
                "The model-recommended path conflicts with the registered capability type.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=RoutingDecision(
                    accepted_model_recommendation=False,
                    selected_path=selected_path,
                    selected_capability_code=capability["capability_code"],
                    decision_code="MODEL_PATH_CAPABILITY_CONFLICT",
                    detail="The catalogue-derived path and model recommendation do not agree.",
                ),
            )
        routing_decision = RoutingDecision(
            accepted_model_recommendation=True,
            selected_path=selected_path,
            selected_capability_code=capability["capability_code"],
            decision_code="MODEL_RECOMMENDATION_VALIDATED",
            detail="The model recommendation exists in the published catalogue and passed deterministic scope validation.",
        )

        required_action = capability.get("required_action")
        if not required_action:
            return self._blocked(
                request,
                "CAPABILITY_ACTION_NOT_REGISTERED",
                "The published capability does not declare the permission action required for execution.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        permission = self.permission.check(
            identity.actor_id,
            required_action,
            request.data_reference,
            request.data_labels,
            request.allowed_data_actions,
        )
        if not permission.passed:
            return self._blocked(
                request,
                permission.reason_code,
                permission.detail,
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        security = self.security.check(identity.actor_id, required_action, request.data_labels)
        if not security.passed:
            return self._blocked(
                request,
                security.reason_code,
                security.detail,
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        rule_versions = self.capability_catalog.list_published_rule_versions(capability["capability_code"])
        if not rule_versions:
            return self._blocked(
                request,
                "RULE_VERSION_NOT_FOUND",
                "No published rule and parameter version is available.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        if len(rule_versions) > 1:
            return self._blocked(
                request,
                "PUBLISHED_VERSION_CONFLICT",
                "Multiple published rule and parameter versions exist for the selected capability; execution is blocked until governance resolves the conflict.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        rule_version = rule_versions[0]
        effective_time_error = self._effective_time_error(request, rule_version)
        if effective_time_error:
            return self._blocked(
                request,
                effective_time_error["reason_code"],
                effective_time_error["message"],
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        versions = VersionReference(
            capability_code=capability["capability_code"],
            capability_version=capability["capability_version"],
            rule_version=rule_version["rule_version"],
            parameter_version=rule_version["parameter_version"],
            treatment_rule_version=rule_version["treatment_rule_version"],
        )
        parameter_reference_error = self._parameter_reference_error(request, versions)
        if parameter_reference_error:
            return self._blocked(
                request,
                parameter_reference_error["reason_code"],
                parameter_reference_error["message"],
                versions=versions,
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        rule_payload = json.loads(rule_version["payload_json"])
        capability_type = capability.get("capability_type")
        if capability_type == "existing_system":
            return self._execute_existing_system(
                request,
                capability,
                versions,
                rule_payload,
                identity,
                model_analysis,
                routing_decision,
            )
        if capability_type not in {"fixed_python", "declarative_rule"}:
            return self._blocked(
                request,
                "CAPABILITY_TYPE_UNSUPPORTED",
                f"The registered capability type is not available in the current implementation: {capability_type}",
                versions=versions,
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        rows, data_metadata = self.data_provider.read(
            request.data_reference, request.business_object_id, request.period
        )
        if not rows:
            return self._blocked(
                request,
                "DATA_NOT_FOUND",
                "No authorized business data matches the request reference and period.",
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        data_reference = DataReference(**data_metadata)
        try:
            self._validate_input_schema(rows, capability)
            executor = self.executor_registry.resolve(capability["implementation_ref"])
            validator = self.validator_registry.resolve(capability["validation_ref"])
            result = executor.execute(rows, rule_payload)
            validation = [ValidationCheck(**item) for item in validator.validate(result)]
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            return self._blocked(
                request,
                "EXECUTION_CONFIGURATION_INVALID",
                str(error),
                versions=versions,
                data_references=[data_reference],
                identity=identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        if not all(item.passed for item in validation):
            return self._blocked(
                request,
                "RESULT_VALIDATION_FAILED",
                "The calculation result did not pass deterministic validation.",
                versions,
                [data_reference],
                validation,
                identity,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        treatment = self._resolve_treatment(rule_payload["treatment_rule"], result)
        handling_type = treatment.get("handling_type")
        response = ExecutionResult(
            trace_id=request.trace_id,
            request_id=request.request_id,
            state=ProcessingState(treatment["state"]),
            execution_path=ExecutionPath.DETERMINISTIC,
            handling_type=HandlingType(handling_type) if handling_type else None,
            reason_code=treatment.get("reason_code"),
            message=treatment["message"],
            versions=versions,
            data_references=[data_reference],
            result=result,
            validation=validation,
            model_analysis=model_analysis,
            routing_decision=routing_decision,
        )
        return self._record(
            request,
            response,
            identity,
            input_evidence={
                "request": request.model_dump(),
                "capability": {
                    "capability_code": capability["capability_code"],
                    "capability_version": capability["capability_version"],
                    "implementation_ref": capability["implementation_ref"],
                },
                "versions": versions.model_dump(),
                "rule_payload": rule_payload,
                "business_data": rows,
            },
        )

    def _execute_existing_system(
        self,
        request: ExecutionRequest,
        capability: dict[str, Any],
        versions: VersionReference,
        rule_payload: dict[str, Any],
        identity: IdentityResolution,
        model_analysis: ModelRoutingAnalysis,
        routing_decision: RoutingDecision,
    ) -> ExecutionResult:
        try:
            self._validate_existing_system_request(request, capability)
        except ValueError as error:
            return self._blocked(
                request,
                "EXISTING_SYSTEM_REQUEST_INVALID",
                str(error),
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        try:
            call_result = self.existing_system_gateway.invoke(
                ExistingSystemCallRequest(
                    trace_id=request.trace_id,
                    request_id=request.request_id,
                    capability_code=capability["capability_code"],
                    operation_ref=capability["implementation_ref"],
                    data_reference=request.data_reference,
                    business_object_id=request.business_object_id,
                    period=request.period,
                    invocation_config=rule_payload.get("invocation", {}),
                )
            )
        except (ConnectionError, TimeoutError) as error:
            return self._blocked(
                request,
                "EXISTING_SYSTEM_UNAVAILABLE",
                str(error),
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        try:
            system_reference = ExistingSystemReference(
                invocation_id=call_result.invocation_id,
                system_code=call_result.system_code,
                operation_ref=call_result.operation_ref,
                service_version=call_result.service_version,
                returned_at=call_result.returned_at,
            )
        except ValueError as error:
            return self._blocked(
                request,
                "EXISTING_SYSTEM_RESPONSE_INVALID",
                str(error),
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        if not call_result.succeeded:
            return self._blocked(
                request,
                call_result.reason_code or "EXISTING_SYSTEM_CALL_FAILED",
                call_result.detail,
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                existing_system_reference=system_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        if call_result.operation_ref != capability["implementation_ref"]:
            return self._blocked(
                request,
                "EXISTING_SYSTEM_OPERATION_MISMATCH",
                "The external response does not match the registered operation reference.",
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                existing_system_reference=system_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        expected_system_code = rule_payload["invocation"].get("authoritative_result_source")
        if expected_system_code and call_result.system_code != expected_system_code:
            return self._blocked(
                request,
                "EXISTING_SYSTEM_SOURCE_MISMATCH",
                "The external response was not returned by the registered authoritative system.",
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                existing_system_reference=system_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        if call_result.data_reference.get("reference_id") != request.data_reference:
            return self._blocked(
                request,
                "EXISTING_SYSTEM_DATA_REFERENCE_MISMATCH",
                "The external response is not tied to this request's authorized data reference.",
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                existing_system_reference=system_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        try:
            data_reference = DataReference(**call_result.data_reference)
            validator = self.validator_registry.resolve(capability["validation_ref"])
            validation = [
                ValidationCheck(**item) for item in validator.validate(call_result.result)
            ]
        except (KeyError, ValueError) as error:
            return self._blocked(
                request,
                "EXISTING_SYSTEM_RESPONSE_INVALID",
                str(error),
                versions=versions,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                existing_system_reference=system_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        if not all(item.passed for item in validation):
            return self._blocked(
                request,
                "RESULT_VALIDATION_FAILED",
                "The existing-system result did not pass the registered deterministic validation.",
                versions=versions,
                data_references=[data_reference],
                validation=validation,
                identity=identity,
                execution_path=ExecutionPath.EXISTING_SYSTEM,
                existing_system_reference=system_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )

        treatment = self._resolve_treatment(rule_payload["treatment_rule"], call_result.result)
        handling_type = treatment.get("handling_type")
        response = ExecutionResult(
            trace_id=request.trace_id,
            request_id=request.request_id,
            state=ProcessingState(treatment["state"]),
            execution_path=ExecutionPath.EXISTING_SYSTEM,
            handling_type=HandlingType(handling_type) if handling_type else None,
            reason_code=treatment.get("reason_code"),
            message=treatment["message"],
            versions=versions,
            data_references=[data_reference],
            existing_system_reference=system_reference,
            result=call_result.result,
            validation=validation,
            model_analysis=model_analysis,
            routing_decision=routing_decision,
        )
        return self._record(
            request,
            response,
            identity,
            input_evidence={
                "request": request.model_dump(),
                "capability": {
                    "capability_code": capability["capability_code"],
                    "capability_version": capability["capability_version"],
                    "operation_ref": capability["implementation_ref"],
                },
                "versions": versions.model_dump(),
                "invocation_config": rule_payload.get("invocation", {}),
                "authorized_data_reference": data_reference.model_dump(),
            },
        )

    def get_record(self, trace_id: str) -> dict[str, Any] | None:
        return self.execution_records.get_by_trace(trace_id)

    def create_rule_version_draft(self, request: RuleVersionDraftRequest) -> RuleVersionResult:
        identity = self._require_permission(
            request.identity_context_ref,
            "rule.version.create",
            request.capability_code,
            f"RULE-DRAFT-{request.capability_code}-{request.rule_version}",
        )
        if not self.capability_catalog.capability_exists(request.capability_code):
            raise LookupError("Calculation capability not found.")
        rule_version_id = self.rule_versions.create_draft(
            capability_code=request.capability_code,
            rule_version=request.rule_version,
            parameter_version=request.parameter_version,
            treatment_rule_version=request.treatment_rule_version,
            payload=request.payload,
            source_basis=request.source_basis,
            review_role=request.review_role,
            entered_by=identity.actor_id,
        )
        return self._get_rule_version(rule_version_id)

    def transition_rule_version(
        self, rule_version_id: int, request: RuleVersionTransitionRequest
    ) -> RuleVersionResult:
        row = self.rule_versions.get(rule_version_id)
        if row is None:
            raise LookupError("Rule version not found.")
        current_status = RuleVersionStatus(row["status"])
        target_status, permission_action = self._version_transition_target(current_status, request.action)
        identity = self._require_permission(
            request.identity_context_ref,
            permission_action,
            row["capability_code"],
            f"RULE-TRANSITION-{rule_version_id}-{request.action.value}",
        )
        now = datetime.now(timezone.utc).isoformat()
        publishing = request.action == RuleVersionAction.APPROVE_PUBLISH
        self.rule_versions.apply_transition(
            rule_version_id=rule_version_id,
            capability_code=row["capability_code"],
            from_status=current_status.value,
            to_status=target_status.value,
            action=request.action.value,
            actor_id=identity.actor_id,
            comment=request.comment,
            reviewed_at=now if publishing else None,
            effective_at=now if publishing else None,
            retire_previous_published=publishing,
        )
        return self._get_rule_version(rule_version_id)

    def handle_waiting_result(
        self, execution_record_id: str, request: HumanHandlingRequest
    ) -> HumanHandlingResult:
        record = self.execution_records.get_by_id(execution_record_id)
        if record is None:
            raise LookupError("Execution record not found.")
        handling_type = HandlingType(record["handling_type"])
        permission_actions = {
            HandlingType.AUTHORIZE_AI_GENERATION: "rule.authorize.ai_generation",
            HandlingType.REVIEW_SANDBOX_RESULT: "rule.review.sandbox_result",
        }
        permission_action = permission_actions.get(handling_type, "rule.handle.result")
        identity = self._require_permission(
            request.identity_context_ref,
            permission_action,
            "human-handling",
            record["trace_id"],
        )
        if (
            handling_type == HandlingType.AUTHORIZE_AI_GENERATION
            and identity.actor_id != record.get("operator_id")
        ):
            raise PermissionError(
                "Only the original calculation requester may authorize AI candidate generation."
            )
        if record["state"] != ProcessingState.WAITING_HUMAN.value:
            raise ValueError("Only a waiting_human execution record can be handled.")
        if self.execution_records.has_human_handling(execution_record_id):
            raise ValueError("This execution record has already been handled.")

        outcome = self._handling_outcome(request.action, handling_type)
        handling_record_id = f"HND-{uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        self.execution_records.save_human_handling(
            {
                "handling_record_id": handling_record_id,
                "execution_record_id": execution_record_id,
                "trace_id": record["trace_id"],
                "handler_id": identity.actor_id,
                "identity_verification_id": identity.verification_id,
                "identity_context_digest": self._digest(request.identity_context_ref),
                "action": request.action.value,
                "comment": request.comment,
                "created_at": now,
            }
        )
        self.execution_records.update_execution_state(
            execution_record_id,
            outcome["state"].value,
            record["handling_type"],
            outcome["reason_code"],
        )
        next_execution: ExecutionResult | None = None
        candidate_skill_creation_request: CandidateSkillCreationRequest | None = None
        if (
            request.action == HumanAction.APPROVE
            and handling_type == HandlingType.AUTHORIZE_AI_GENERATION
        ):
            candidate_skill_creation_request = self._build_candidate_skill_creation_request(
                record, identity
            )
        return HumanHandlingResult(
            execution_record_id=execution_record_id,
            trace_id=record["trace_id"],
            state=next_execution.state if next_execution else outcome["state"],
            reason_code=(
                next_execution.reason_code if next_execution else outcome["reason_code"]
            ),
            message=next_execution.message if next_execution else outcome["message"],
            handling_record_id=handling_record_id,
            next_execution_record_id=(
                next_execution.execution_record_id if next_execution else None
            ),
            candidate_skill_creation_request=candidate_skill_creation_request,
        )

    def resume_candidate_skill_trial(
        self,
        authorization_execution_record_id: str,
        trial_request: CandidateSkillTrialRequest,
    ) -> ExecutionResult:
        authorization_record = self.execution_records.get_by_id(authorization_execution_record_id)
        if authorization_record is None:
            raise LookupError("AI generation authorization record not found.")
        if authorization_record.get("handling_type") != HandlingType.AUTHORIZE_AI_GENERATION.value:
            raise ValueError("Only an AI-generation authorization record can resume a candidate trial.")
        if authorization_record.get("reason_code") != "AI_GENERATION_AUTHORIZED":
            raise ValueError("The requester has not approved candidate Skill generation.")
        handling = self.execution_records.get_human_handling(authorization_execution_record_id)
        if handling is None or handling.get("action") != HumanAction.APPROVE.value:
            raise ValueError("The requester approval record is missing.")

        identity = self.identity.resolve(
            trial_request.identity_context_ref, authorization_record["trace_id"]
        )
        if not identity.passed:
            raise PermissionError(identity.detail)
        if identity.actor_id != authorization_record.get("operator_id"):
            raise PermissionError(
                "Candidate trial must continue under the original authorized operator."
            )

        request_context = json.loads(authorization_record.get("request_context_json") or "{}")
        request_context["identity_context_ref"] = trial_request.identity_context_ref
        request_context["claimed_actor_id"] = identity.actor_id
        original_request_id = str(request_context.get("request_id") or "REQ-SANDBOX")
        request_context["request_id"] = f"{original_request_id[:68]}-SBX"
        try:
            request = ExecutionRequest(**request_context)
        except ValueError as error:
            raise ValueError(
                "The authorized request context cannot be reconstructed for sandbox execution."
            ) from error

        stored_model_analysis = json.loads(
            authorization_record.get("model_analysis_json") or "null"
        )
        stored_routing_decision = json.loads(
            authorization_record.get("routing_decision_json") or "null"
        )
        model_analysis = (
            ModelRoutingAnalysis.model_validate(stored_model_analysis)
            if isinstance(stored_model_analysis, dict)
            else None
        )
        routing_decision = (
            RoutingDecision.model_validate(stored_routing_decision)
            if isinstance(stored_routing_decision, dict)
            else None
        )

        parent_id = authorization_record["execution_record_id"]
        expected_candidate_request_id = self._candidate_request_id(parent_id)
        if trial_request.candidate_implementation.candidate_request_id != expected_candidate_request_id:
            raise ValueError(
                "The candidate implementation does not match this authorized candidate Skill request."
            )
        if request.temporary_analysis_spec is None:
            raise ValueError(
                "Candidate trial requires a temporary analysis objective, input contract, and output contract."
            )
        if not trial_request.candidate_implementation.candidate_only:
            raise ValueError("The resumed implementation must be a candidate Skill implementation.")

        artifact = CodeArtifactReference(
            artifact_ref=trial_request.candidate_implementation.artifact_ref,
            artifact_version=trial_request.candidate_implementation.artifact_version,
            source=trial_request.candidate_implementation.source,
            code_digest=trial_request.candidate_implementation.code_digest,
            entrypoint=trial_request.candidate_implementation.entrypoint,
            generation_id=trial_request.candidate_implementation.generation_id,
            content_url=trial_request.candidate_implementation.content_url,
            candidate_only=True,
        )
        candidate_reference = CandidateAssetReference(
            artifact_ref=artifact.artifact_ref,
            artifact_version=artifact.artifact_version,
            source=artifact.source,
            code_digest=artifact.code_digest,
            entrypoint=artifact.entrypoint,
            generation_id=artifact.generation_id,
            candidate_only=True,
        )
        return self._run_candidate_sandbox(
            request=request,
            identity=identity,
            artifact=artifact,
            candidate_reference=candidate_reference,
            model_analysis=model_analysis,
            routing_decision=routing_decision,
            parent_execution_record_id=parent_id,
        )

    def _run_candidate_sandbox(
        self,
        request: ExecutionRequest,
        identity: IdentityResolution,
        artifact: CodeArtifactReference,
        candidate_reference: CandidateAssetReference,
        model_analysis: ModelRoutingAnalysis | None,
        routing_decision: RoutingDecision | None,
        parent_execution_record_id: str,
    ) -> ExecutionResult:
        spec = request.temporary_analysis_spec
        if spec is None:
            raise ValueError("Candidate sandbox execution requires a temporary analysis specification.")

        sandbox_permission = self.permission.check(
            identity.actor_id,
            "rule.execute.sandbox",
            request.data_reference,
            request.data_labels,
            request.allowed_data_actions,
        )
        if not sandbox_permission.passed:
            return self._blocked(
                request,
                sandbox_permission.reason_code,
                sandbox_permission.detail,
                identity=identity,
                execution_path=ExecutionPath.SANDBOX,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
                parent_execution_record_id=parent_execution_record_id,
            )
        sandbox_security = self.security.check(
            identity.actor_id, "rule.execute.sandbox", request.data_labels
        )
        if not sandbox_security.passed:
            return self._blocked(
                request,
                sandbox_security.reason_code,
                sandbox_security.detail,
                identity=identity,
                execution_path=ExecutionPath.SANDBOX,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
                parent_execution_record_id=parent_execution_record_id,
            )

        validation_requirements = self._candidate_validation_requirements(spec)
        try:
            sandbox_result = self.sandbox_gateway.run(
                SandboxRunRequest(
                    trace_id=request.trace_id,
                    artifact=artifact,
                    data_reference=request.data_reference,
                    validation_requirements=validation_requirements,
                    resource_limits={
                        "timeout_seconds": 3,
                        "network_access": False,
                        "host_filesystem_access": False,
                        "required_output_fields": spec.output_schema.get(
                            "required_fields", []
                        ),
                    },
                )
            )
            sandbox_reference = SandboxExecutionReference(
                run_id=sandbox_result.run_id,
                artifact_ref=sandbox_result.artifact_ref,
                environment=sandbox_result.environment,
            )
            validation = [
                ValidationCheck(**item) for item in sandbox_result.validation_evidence
            ]
        except (ConnectionError, TimeoutError, ValueError) as error:
            return self._blocked(
                request,
                "SANDBOX_EXECUTION_FAILED",
                f"L1.14 Agent execution sandbox did not return a valid run result: {error}",
                identity=identity,
                execution_path=ExecutionPath.SANDBOX,
                candidate_asset_reference=candidate_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
                parent_execution_record_id=parent_execution_record_id,
            )

        if not sandbox_result.succeeded:
            return self._blocked(
                request,
                sandbox_result.reason_code or "SANDBOX_EXECUTION_FAILED",
                sandbox_result.detail,
                validation=validation,
                identity=identity,
                execution_path=ExecutionPath.SANDBOX,
                candidate_asset_reference=candidate_reference,
                sandbox_execution_reference=sandbox_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
                parent_execution_record_id=parent_execution_record_id,
            )
        if not validation or not all(item.passed for item in validation):
            return self._blocked(
                request,
                "RESULT_VALIDATION_FAILED",
                "The temporary sandbox result did not pass all required checks.",
                validation=validation,
                identity=identity,
                execution_path=ExecutionPath.SANDBOX,
                candidate_asset_reference=candidate_reference,
                sandbox_execution_reference=sandbox_reference,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
                parent_execution_record_id=parent_execution_record_id,
            )

        response = ExecutionResult(
            trace_id=request.trace_id,
            request_id=request.request_id,
            state=ProcessingState.WAITING_HUMAN,
            execution_path=ExecutionPath.SANDBOX,
            handling_type=HandlingType.REVIEW_SANDBOX_RESULT,
            reason_code="SANDBOX_RESULT_REVIEW_REQUIRED",
            message=(
                "The candidate code completed a controlled L1.14 Agent execution sandbox run. "
                "This result is temporary reference material and requires responsible-person review; "
                "it cannot be written back or registered as a formal capability automatically."
            ),
            candidate_asset_reference=candidate_reference,
            sandbox_execution_reference=sandbox_reference,
            result=sandbox_result.result,
            validation=validation,
            model_analysis=model_analysis,
            routing_decision=routing_decision,
        )
        return self._record(
            request,
            response,
            identity,
            input_evidence={
                "temporary_analysis_spec": spec.model_dump(),
                "data_reference": request.data_reference,
                "candidate_asset_reference": candidate_reference.model_dump(),
                "sandbox_requirements": validation_requirements,
            },
            parent_execution_record_id=parent_execution_record_id,
        )

    def _build_candidate_skill_creation_request(
        self, authorization_record: dict[str, Any], identity: IdentityResolution
    ) -> CandidateSkillCreationRequest:
        request_context = json.loads(authorization_record.get("request_context_json") or "{}")
        request_context["identity_context_ref"] = "authorized-context-not-persisted"
        request_context["claimed_actor_id"] = identity.actor_id
        try:
            request = ExecutionRequest(**request_context)
        except ValueError as error:
            raise ValueError("The authorized request context cannot be reconstructed.") from error
        if request.temporary_analysis_spec is None:
            raise ValueError(
                "Candidate Skill creation requires a temporary analysis objective, input contract, and output contract."
            )
        return CandidateSkillCreationRequest(
            trace_id=request.trace_id,
            request_id=request.request_id,
            authorization_execution_record_id=authorization_record["execution_record_id"],
            candidate_request_id=self._candidate_request_id(
                authorization_record["execution_record_id"]
            ),
            requester_id=identity.actor_id,
            task=request.task or request.business_type or "",
            business_type=request.business_type,
            data_references=request.request_data_references
            or [RequestDataReference(reference_id=request.data_reference, purpose="calculation_input")],
            temporary_analysis_spec=request.temporary_analysis_spec,
            validation_requirements=self._candidate_validation_requirements(
                request.temporary_analysis_spec
            ),
        )

    @staticmethod
    def _candidate_request_id(authorization_execution_record_id: str) -> str:
        """Derive a stable, auditable binding ID for one authorized candidate request."""
        return f"CSR-{authorization_execution_record_id}"

    @staticmethod
    def _candidate_validation_requirements(spec: TemporaryAnalysisSpec) -> list[str]:
        requirements = [
            f"Output must satisfy field contract: {field}"
            for field in spec.output_schema.get("required_fields", [])
        ]
        requirements.extend(
            [
                "The run must use the authorized data reference only.",
                "The candidate code must not access the network or host filesystem.",
                "The result is temporary reference material and must not be written back automatically.",
            ]
        )
        return requirements

    def _get_rule_version(self, rule_version_id: int) -> RuleVersionResult:
        row = self.rule_versions.get(rule_version_id)
        if row is None:
            raise LookupError("Rule version not found.")
        return RuleVersionResult(
            rule_version_id=row["id"],
            capability_code=row["capability_code"],
            rule_version=row["rule_version"],
            parameter_version=row["parameter_version"],
            treatment_rule_version=row["treatment_rule_version"],
            status=RuleVersionStatus(row["status"]),
            source_basis=row["source_basis"],
            review_role=row["review_role"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            effective_at=row["effective_at"],
        )

    def _require_permission(
        self, identity_context_ref: str, action: str, reference: str, trace_id: str
    ) -> IdentityResolution:
        identity = self.identity.resolve(identity_context_ref, trace_id)
        if not identity.passed:
            raise PermissionError(identity.detail)
        permission = self.permission.check(identity.actor_id, action, reference)
        if not permission.passed:
            raise PermissionError(permission.detail)
        security = self.security.check(identity.actor_id, action)
        if not security.passed:
            raise PermissionError(security.detail)
        return identity

    @staticmethod
    def _version_transition_target(
        current_status: RuleVersionStatus, action: RuleVersionAction
    ) -> tuple[RuleVersionStatus, str]:
        transitions = {
            (RuleVersionStatus.DRAFT, RuleVersionAction.START_TESTING): (
                RuleVersionStatus.TESTING, "rule.version.start_testing"
            ),
            (RuleVersionStatus.TESTING, RuleVersionAction.SUBMIT_REVIEW): (
                RuleVersionStatus.PENDING_REVIEW, "rule.version.submit_review"
            ),
            (RuleVersionStatus.PENDING_REVIEW, RuleVersionAction.APPROVE_PUBLISH): (
                RuleVersionStatus.PUBLISHED, "rule.version.approve_publish"
            ),
        }
        transition = transitions.get((current_status, action))
        if transition is None:
            raise ValueError(f"Action {action.value} is not allowed while version status is {current_status.value}.")
        return transition

    def _blocked(
        self,
        request: ExecutionRequest,
        reason_code: str | None,
        message: str,
        versions: VersionReference | None = None,
        data_references: list[DataReference] | None = None,
        validation: list[ValidationCheck] | None = None,
        identity: IdentityResolution | None = None,
        execution_path: ExecutionPath | None = None,
        existing_system_reference: ExistingSystemReference | None = None,
        candidate_asset_reference: CandidateAssetReference | None = None,
        sandbox_execution_reference: SandboxExecutionReference | None = None,
        model_analysis: ModelRoutingAnalysis | None = None,
        routing_decision: RoutingDecision | None = None,
        parent_execution_record_id: str | None = None,
    ) -> ExecutionResult:
        response = ExecutionResult(
            trace_id=request.trace_id,
            request_id=request.request_id,
            state=ProcessingState.BLOCKED,
            execution_path=execution_path,
            reason_code=reason_code,
            message=message,
            versions=versions,
            data_references=data_references or [],
            validation=validation or [],
            existing_system_reference=existing_system_reference,
            candidate_asset_reference=candidate_asset_reference,
            sandbox_execution_reference=sandbox_execution_reference,
            model_analysis=model_analysis,
            routing_decision=routing_decision,
        )
        return self._record(
            request,
            response,
            identity,
            parent_execution_record_id=parent_execution_record_id,
        )

    def _await_ai_authorization(
        self,
        request: ExecutionRequest,
        identity: IdentityResolution,
        model_analysis: ModelRoutingAnalysis,
        routing_decision: RoutingDecision,
    ) -> ExecutionResult:
        if request.temporary_analysis_spec is None:
            return self._blocked(
                request,
                "TEMPORARY_ANALYSIS_SPEC_REQUIRED",
                "Candidate Skill creation requires a temporary analysis objective, input contract, and output contract.",
                identity=identity,
                execution_path=ExecutionPath.SANDBOX,
                model_analysis=model_analysis,
                routing_decision=routing_decision,
            )
        response = ExecutionResult(
            trace_id=request.trace_id,
            request_id=request.request_id,
            state=ProcessingState.WAITING_HUMAN,
            execution_path=ExecutionPath.SANDBOX,
            handling_type=HandlingType.AUTHORIZE_AI_GENERATION,
            reason_code="AI_GENERATION_AUTHORIZATION_REQUIRED",
            message=(
                "No published deterministic or existing-system capability matches this task. "
                "The requester must authorize a candidate Skill creation application, controlled sandbox execution, "
                "and separate human review of the result before processing can continue."
            ),
            model_analysis=model_analysis,
            routing_decision=routing_decision,
        )
        return self._record(request, response, identity)

    @staticmethod
    def _capability_summary(capability: dict[str, Any]) -> dict[str, Any]:
        return {
            "capability_code": capability.get("capability_code"),
            "scenario": capability.get("scenario"),
            "capability_type": capability.get("capability_type"),
            "capability_version": capability.get("capability_version"),
            "owner": capability.get("owner"),
            "input_schema": json.loads(capability.get("input_schema_json") or "{}"),
        }

    @staticmethod
    def _path_for_capability_type(capability_type: str | None) -> ExecutionPath | None:
        mapping = {
            "declarative_rule": ExecutionPath.DETERMINISTIC,
            "fixed_python": ExecutionPath.DETERMINISTIC,
            "existing_system": ExecutionPath.EXISTING_SYSTEM,
        }
        return mapping.get(str(capability_type))

    @staticmethod
    def _validate_input_schema(rows: list[dict[str, Any]], capability: dict[str, Any]) -> None:
        schema = json.loads(capability.get("input_schema_json") or "{}")
        required_fields = set(schema.get("required_fields", []))
        for index, row in enumerate(rows, start=1):
            missing = sorted(required_fields.difference(row))
            if missing:
                raise ValueError(f"Input row {index} is missing required fields: {', '.join(missing)}")

    @staticmethod
    def _validate_existing_system_request(
        request: ExecutionRequest, capability: dict[str, Any]
    ) -> None:
        schema = json.loads(capability.get("input_schema_json") or "{}")
        request_values = request.model_dump()
        missing = sorted(
            field
            for field in schema.get("required_context_fields", [])
            if not request_values.get(field)
        )
        if missing:
            raise ValueError(
                f"Existing-system call is missing required context fields: {', '.join(missing)}"
            )

    @staticmethod
    def _parameter_reference_error(
        request: ExecutionRequest, versions: VersionReference
    ) -> dict[str, str] | None:
        parameter_refs = [
            item for item in request.request_data_references if item.purpose == "rule_parameter"
        ]
        if len(parameter_refs) > 1:
            return {
                "reason_code": "AMBIGUOUS_PARAMETER_REFERENCE",
                "message": "Only one rule_parameter reference may be supplied for the selected capability version.",
            }
        if not parameter_refs:
            return None
        parameter_ref = parameter_refs[0]
        if not parameter_ref.version:
            return {
                "reason_code": "PARAMETER_REFERENCE_VERSION_REQUIRED",
                "message": "A supplied rule_parameter reference must declare its version for consistency checking.",
            }
        if parameter_ref.version != versions.parameter_version:
            return {
                "reason_code": "PARAMETER_VERSION_MISMATCH",
                "message": (
                    "The supplied rule_parameter reference does not match the published parameter version "
                    "locked by the calculation capability."
                ),
            }
        return None

    @staticmethod
    def _effective_time_error(
        request: ExecutionRequest, rule_version: dict[str, Any]
    ) -> dict[str, str] | None:
        effective_at_raw = rule_version.get("effective_at")
        if not effective_at_raw:
            return {
                "reason_code": "RULE_EFFECTIVE_TIME_MISSING",
                "message": "The published rule version has no governed effective time and cannot be used for formal calculation.",
            }
        try:
            effective_at = datetime.fromisoformat(str(effective_at_raw).replace("Z", "+00:00"))
        except ValueError:
            return {
                "reason_code": "RULE_EFFECTIVE_TIME_INVALID",
                "message": "The published rule version has an invalid effective time.",
            }
        if effective_at.tzinfo is None:
            return {
                "reason_code": "RULE_EFFECTIVE_TIME_INVALID",
                "message": "The published rule version effective time must include timezone information.",
            }
        calculation_as_of = request.calculation_as_of or datetime.now(timezone.utc)
        if calculation_as_of.tzinfo is None:
            return {
                "reason_code": "CALCULATION_TIME_INVALID",
                "message": "The calculation reference time must include timezone information.",
            }
        if effective_at.astimezone(timezone.utc) > calculation_as_of.astimezone(timezone.utc):
            return {
                "reason_code": "RULE_NOT_EFFECTIVE_AT_CALCULATION_TIME",
                "message": "The published rule version was not yet effective at the requested calculation reference time.",
            }
        return None

    def _record(
        self,
        request: ExecutionRequest,
        response: ExecutionResult,
        identity: IdentityResolution | None,
        input_evidence: dict[str, Any] | None = None,
        parent_execution_record_id: str | None = None,
    ) -> ExecutionResult:
        execution_record_id = f"EXE-{uuid4().hex[:12].upper()}"
        evidence = dict(input_evidence or {"request": request.model_dump()})
        if response.model_analysis:
            evidence["model_analysis"] = response.model_analysis.model_dump()
        if response.routing_decision:
            evidence["routing_decision"] = response.routing_decision.model_dump()
        canonical_evidence = json.dumps(
            evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        input_digest = hashlib.sha256(canonical_evidence.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        self.execution_records.save_execution(
            {
                "execution_record_id": execution_record_id,
                "parent_execution_record_id": parent_execution_record_id,
                "trace_id": request.trace_id,
                "request_id": request.request_id,
                "claimed_actor_id": request.claimed_actor_id,
                "operator_id": identity.actor_id if identity and identity.actor_id else "unresolved",
                "identity_verification_id": identity.verification_id if identity else None,
                "identity_context_digest": self._digest(request.identity_context_ref),
                "business_type": request.business_type or request.task,
                "execution_path": response.execution_path.value if response.execution_path else None,
                "state": response.state.value,
                "handling_type": response.handling_type.value if response.handling_type else None,
                "reason_code": response.reason_code,
                "versions": response.versions.model_dump() if response.versions else None,
                "data_reference": request.data_reference,
                "request_data_references": [
                    item.model_dump() for item in request.request_data_references
                ],
                "request_context": request.model_dump(
                    mode="json", exclude={"identity_context_ref"}
                ),
                "input_digest": input_digest,
                "result": response.result,
                "existing_system_reference": (
                    response.existing_system_reference.model_dump()
                    if response.existing_system_reference
                    else None
                ),
                "candidate_asset_reference": (
                    response.candidate_asset_reference.model_dump()
                    if response.candidate_asset_reference
                    else None
                ),
                "sandbox_execution_reference": (
                    response.sandbox_execution_reference.model_dump()
                    if response.sandbox_execution_reference
                    else None
                ),
                "model_analysis": (
                    response.model_analysis.model_dump()
                    if response.model_analysis
                    else None
                ),
                "routing_decision": (
                    response.routing_decision.model_dump()
                    if response.routing_decision
                    else None
                ),
                "validation": [item.model_dump() for item in response.validation],
                "created_at": now,
            }
        )
        response.execution_record_id = execution_record_id
        return response

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _handling_outcome(action: HumanAction, handling_type: HandlingType) -> dict[str, Any]:
        if action == HumanAction.APPROVE and handling_type == HandlingType.AUTHORIZE_AI_GENERATION:
            return {
                "state": ProcessingState.AUTOMATIC_PASS,
                "reason_code": "AI_GENERATION_AUTHORIZED",
                "message": "Candidate Skill generation was authorized. Return the creation application to the Flow Execution Engine.",
            }
        if action == HumanAction.APPROVE and handling_type == HandlingType.REVIEW_SANDBOX_RESULT:
            return {
                "state": ProcessingState.AUTOMATIC_PASS,
                "reason_code": "SANDBOX_RESULT_REVIEWED_REFERENCE_ONLY",
                "message": "The responsible person reviewed the temporary sandbox result. It remains reference-only and cannot be written back or formalized automatically.",
            }
        if action == HumanAction.APPROVE:
            return {
                "state": ProcessingState.AUTOMATIC_PASS,
                "reason_code": None,
                "message": "The responsible person confirmed the result. It may now take effect under the business write-back rule.",
            }
        if action == HumanAction.REJECT:
            return {
                "state": ProcessingState.BLOCKED,
                "reason_code": "HUMAN_TERMINATED",
                "message": "The responsible person terminated this result. It must not take effect or be written back.",
            }
        return {
            "state": ProcessingState.BLOCKED,
            "reason_code": "RECALCULATION_REQUIRED",
            "message": "Supplementary data or correction is required. Keep this record and submit a new calculation request.",
        }

    @classmethod
    def _resolve_treatment(
        cls, treatment_rule: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        if "conditions" not in treatment_rule:
            return treatment_rule
        for condition in treatment_rule["conditions"]:
            actual = result.get(condition["result_field"])
            if cls._compare(actual, condition["operator"], condition["value"]):
                return condition
        return treatment_rule["default"]

    @staticmethod
    def _compare(actual: Any, operator: str, expected: Any) -> bool:
        comparisons = {
            "eq": lambda: actual == expected,
            "ne": lambda: actual != expected,
            "gt": lambda: actual > expected,
            "gte": lambda: actual >= expected,
            "lt": lambda: actual < expected,
            "lte": lambda: actual <= expected,
        }
        try:
            return comparisons[operator]()
        except KeyError as error:
            raise ValueError(f"Unsupported treatment-rule operator: {operator}") from error
