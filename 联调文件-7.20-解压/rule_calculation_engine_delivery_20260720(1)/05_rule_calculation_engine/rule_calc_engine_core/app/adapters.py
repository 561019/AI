from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import connect
from .ports import (
    AdapterDecision,
    CodeArtifactReference,
    DigitalAssetCandidateRequest,
    ExistingSystemCallRequest,
    ExistingSystemCallResult,
    IdentityResolution,
    ModelAnalysisRequest,
    ModelAnalysisResult,
    SandboxRunRequest,
    SandboxRunResult,
)


class LocalIdentityAdapter:
    """Development stand-in for 1.8. It only identifies the current operator."""

    CONTEXTS = {
        "ctx-business-operator": "business_operator",
        "ctx-business-manager": "business_manager",
        "ctx-dsm-operator": "dsm_operator",
        "ctx-rule-engineer": "rule_engineer",
        "ctx-designated-reviewer": "designated_reviewer",
        "ctx-unauthorized-user": "unauthorized_user",
    }

    def resolve(self, identity_context_ref: str, trace_id: str) -> IdentityResolution:
        actor_id = self.CONTEXTS.get(identity_context_ref)
        if actor_id is None and identity_context_ref.startswith("platform-actor:"):
            actor_id = identity_context_ref.removeprefix("platform-actor:")
        if actor_id is None:
            return IdentityResolution(False, "Identity context cannot be resolved.", reason_code="IDENTITY_CONTEXT_INVALID")
        return IdentityResolution(
            True,
            f"Local identity context resolved for {actor_id}.",
            actor_id=actor_id,
            verification_id=f"IDV-{trace_id}-{actor_id}",
        )


class LocalPermissionAdapter:
    """Development stand-in for 1.1. It returns a decision; the engine owns no final permission policy."""

    def check(
        self,
        operator_id: str,
        action: str,
        data_reference: str,
        data_labels: list[str] | None = None,
        allowed_data_actions: list[str] | None = None,
    ) -> AdapterDecision:
        if operator_id in {"business_operator", "business_manager"} and action.startswith("rule.calculate."):
            return AdapterDecision(True, f"Local permission allowed {action} for {data_reference}.")
        if operator_id in {"business_operator", "business_manager"} and action == "rule.authorize.ai_generation":
            return AdapterDecision(True, f"Local permission allowed {action} for {data_reference}.")
        if operator_id in {"business_operator", "business_manager"} and action in {
            "rule.execute.sandbox",
            "rule.review.sandbox_result",
        }:
            return AdapterDecision(True, f"Local permission allowed {action} for {data_reference}.")
        if operator_id == "designated_reviewer" and action == "rule.handle.result":
            return AdapterDecision(True, f"Local permission allowed {action} for {data_reference}.")
        if operator_id == "dsm_operator" and action == "rule.version.create":
            return AdapterDecision(True, f"Local permission allowed {action} for {data_reference}.")
        if operator_id == "rule_engineer" and action in {"rule.version.start_testing", "rule.version.submit_review"}:
            return AdapterDecision(True, f"Local permission allowed {action} for {data_reference}.")
        if operator_id == "designated_reviewer" and action == "rule.version.approve_publish":
            return AdapterDecision(True, f"Local permission allowed {action} for {data_reference}.")
        return AdapterDecision(False, "Current operator is not allowed to perform this rule-engine action.", "PERMISSION_DENIED")


class LocalSecurityAdapter:
    """Development stand-in for 1.9."""

    def check(
        self, operator_id: str, action: str, data_labels: list[str] | None = None
    ) -> AdapterDecision:
        return AdapterDecision(True, f"Local security check passed for {operator_id}:{action}.")


class LocalModelAnalysisAdapter:
    """Local contract simulator for model access through L1.5; it performs no calculation."""

    PATH_BY_CAPABILITY_TYPE = {
        "declarative_rule": "deterministic",
        "fixed_python": "deterministic",
        "existing_system": "existing_system",
    }

    def analyze(self, request: ModelAnalysisRequest) -> ModelAnalysisResult:
        if request.requested_capability_code:
            candidates = [
                item
                for item in request.candidate_capabilities
                if item.get("capability_code") == request.requested_capability_code
                and (
                    request.legacy_business_type is None
                    or item.get("scenario") == request.legacy_business_type
                )
            ]
        elif request.legacy_business_type:
            candidates = [
                item
                for item in request.candidate_capabilities
                if item.get("scenario") == request.legacy_business_type
            ]
        else:
            raise ConnectionError(
                "A real model adapter is required to analyze an unclassified task."
            )
        if len(candidates) == 1:
            candidate = candidates[0]
            recommended_path = self.PATH_BY_CAPABILITY_TYPE.get(
                str(candidate.get("capability_type")), "sandbox"
            )
            capability_code = str(candidate["capability_code"])
            rationale = (
                "The local L1.5 contract simulator matched one published capability "
                "from the governed catalogue using the supplied task hint."
            )
            missing_items: list[str] = []
            confidence = 1.0
        elif len(candidates) > 1:
            recommended_path = "deterministic"
            capability_code = None
            rationale = (
                "Multiple published capabilities match the supplied task hint; "
                "the simulator cannot safely choose one."
            )
            missing_items = ["capability_disambiguation"]
            confidence = 0.0
        else:
            recommended_path = "sandbox"
            capability_code = None
            rationale = (
                "No published deterministic or existing-system capability matches "
                "the supplied task hint."
            )
            missing_items = []
            confidence = 1.0
        return ModelAnalysisResult(
            analysis_id=f"MRA-{uuid4().hex[:12].upper()}",
            model_service="local-model-analysis-contract-simulator",
            model_version="simulator-1.0",
            recommended_path=recommended_path,
            candidate_capability_code=capability_code,
            extracted_parameters={
                "task": request.task,
                "legacy_business_type": request.legacy_business_type,
                "data_reference": request.data_reference,
            },
            missing_items=missing_items,
            rationale=rationale,
            confidence=confidence,
        )


class SQLiteBusinessDataProvider:
    """Development stand-in for L1.7 data-reference resolution."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def read(
        self, data_reference: str, business_object_id: str | None, period: str | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        conditions = ["data_reference = ?"]
        parameters: list[str] = [data_reference]
        if business_object_id:
            conditions.append("business_object_id = ?")
            parameters.append(business_object_id)
        if period:
            conditions.append("period = ?")
            parameters.append(period)
        with connect(self.database_path) as connection:
            row = connection.execute(
                f"SELECT * FROM business_datasets WHERE {' AND '.join(conditions)}",
                parameters,
            ).fetchone()
        if row is None:
            return [], {}
        data = json.loads(row["payload_json"])
        canonical_data = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return data, {
            "reference_id": data_reference,
            "source_system": row["source_system"],
            "source_description": row["source_description"],
            "source_version": data_reference,
            "data_digest": hashlib.sha256(canonical_data.encode("utf-8")).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "row_count": len(data),
        }


# Compatibility alias for callers created before the generic data port was introduced.
SQLiteReceivableDataProvider = SQLiteBusinessDataProvider


class LocalDigitalAssetAdapter:
    """Contract simulator only; it does not call an LLM or create a real file."""

    def request_candidate_code(self, request: DigitalAssetCandidateRequest) -> CodeArtifactReference:
        mock_code = "def calculate(data): return {'simulation': True}"
        return CodeArtifactReference(
            artifact_ref=f"asset://candidate-python/{request.trace_id}",
            artifact_version="candidate-1",
            source=f"digital-asset-simulator:{request.business_type}",
            code_digest=hashlib.sha256(mock_code.encode("utf-8")).hexdigest(),
            entrypoint="calculate",
            generation_id=f"GEN-{uuid4().hex[:12].upper()}",
            candidate_request_id=request.candidate_request_id,
        )


class LocalSandboxAdapter:
    """Contract simulator only; real sandbox execution remains an L1.14 integration."""

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        return SandboxRunResult(
            run_id=f"SBX-{uuid4().hex[:12].upper()}",
            artifact_ref=request.artifact.artifact_ref,
            succeeded=True,
            detail="The local L1.14 Agent execution sandbox simulator completed the test run.",
            result={
                "simulation": True,
                "data_reference": request.data_reference,
                "trace_id": request.trace_id,
                "adjusted_revenue": "513000.00",
                "gross_profit_change": "-5720.00",
            },
            validation_evidence=[
                {
                    "name": "sandbox_contract_only",
                    "passed": True,
                    "detail": "The local contract simulator returned a controlled reference result.",
                }
            ],
            environment="local-l1.14-contract-simulator",
        )


class LocalExistingSystemAdapter:
    """Translates the internal call into a simulated L1.10/external-system call."""

    def invoke(self, request: ExistingSystemCallRequest) -> ExistingSystemCallResult:
        invocation_id = f"EXT-{uuid4().hex[:12].upper()}"
        returned_at = datetime.now(timezone.utc).isoformat()
        if request.operation_ref != "finance-system.payroll.calculate":
            return ExistingSystemCallResult(
                succeeded=False,
                detail="The requested external operation is not available in the local adapter.",
                reason_code="EXISTING_SYSTEM_OPERATION_UNAVAILABLE",
                invocation_id=invocation_id,
                system_code="local-existing-system-simulator",
                operation_ref=request.operation_ref,
                service_version="unknown",
                returned_at=returned_at,
                result={},
                data_reference={},
            )

        source_rows = [
            {"employee_id": "EMP-001", "gross_pay": "12000.00", "deductions": "1800.00"},
            {"employee_id": "EMP-002", "gross_pay": "15000.00", "deductions": "2100.00"},
            {"employee_id": "EMP-003", "gross_pay": "9000.00", "deductions": "1300.00"},
        ]
        gross = sum((Decimal(row["gross_pay"]) for row in source_rows), Decimal("0"))
        deductions = sum((Decimal(row["deductions"]) for row in source_rows), Decimal("0"))
        net = gross - deductions
        canonical_data = json.dumps(
            source_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return ExistingSystemCallResult(
            succeeded=True,
            detail="The simulated finance system returned its authoritative payroll calculation.",
            invocation_id=invocation_id,
            system_code="finance-system",
            operation_ref=request.operation_ref,
            service_version="payroll-api-2.1",
            returned_at=returned_at,
            result={
                "employee_count": len(source_rows),
                "gross_payroll": str(gross.quantize(Decimal("0.01"))),
                "deductions": str(deductions.quantize(Decimal("0.01"))),
                "net_payroll": str(net.quantize(Decimal("0.01"))),
            },
            data_reference={
                "reference_id": request.data_reference,
                "source_system": "finance-system",
                "source_description": "Payroll input resolved and calculated by the simulated finance system.",
                "source_version": "payroll-data-2026-06-v1",
                "data_digest": hashlib.sha256(canonical_data.encode("utf-8")).hexdigest(),
                "retrieved_at": returned_at,
                "row_count": len(source_rows),
            },
        )
