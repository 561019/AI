from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import (
    CandidateImplementationReference,
    CandidateSkillTrialRequest,
    ExecutionRequest,
    HumanAction,
    HumanHandlingRequest,
    ProcessingState,
    PreconditionAssessmentRequest,
    RequestDataReference,
    TemporaryAnalysisSpec,
)
from .engine import RuleEngineService
from .ports import IdempotencyRecordPort
from .sqlite_repositories import SQLitePlatformDataAdapter


SERVICE_CODE = "l2.rule_calculation"
PROTOCOL_VERSION = "1.0"
IDEMPOTENCY_RETENTION_DAYS = 30
FLOW_SERVICE_CODES = {"l2.workflow_execution", "l2.flow_execution"}
PUBLIC_PLATFORM_ACTIONS = {
    "rule.evaluate",
    "rule.candidate_skill_apply",
    "rule.candidate_trial",
}
# This action is retained solely for the earlier local console and tests. It is
# deliberately not advertised to the Flow Execution Engine as a platform action.
LEGACY_LOCAL_ACTIONS = {
    "rule.calculate",
}
PLATFORM_ACTIONS = PUBLIC_PLATFORM_ACTIONS | LEGACY_LOCAL_ACTIONS


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class PlatformContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OpenModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ServiceEndpoint(OpenModel):
    layer: str
    service_code: str


class ActorContext(OpenModel):
    person_id: str = Field(min_length=1)
    position_ids: list[str] = Field(default_factory=list)
    tenant_id: str | None = None


class PlatformDataReference(OpenModel):
    ref_id: str = Field(min_length=2, max_length=200)
    purpose: str | None = Field(default=None, min_length=2, max_length=80)
    source_system: str | None = None
    resource_type: str | None = None
    resource_ids: list[str] = Field(default_factory=list)
    version: str | None = None
    data_labels: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    lineage: list[str] = Field(default_factory=list)


class InstructionContext(OpenModel):
    identity_context_ref: str | None = Field(default=None, min_length=8, max_length=200)
    task_id: str | None = None
    subtask_id: str | None = None
    requester_id: str | None = None
    data_refs: list[PlatformDataReference] = Field(default_factory=list)


class RuleCalculatePayload(OpenModel):
    business_type: str | None = Field(default=None, min_length=2, max_length=100)
    node_name: str | None = Field(default=None, min_length=1, max_length=200)
    task: str | None = Field(default=None, min_length=2, max_length=2000)
    service_ref: str | None = Field(default=None, min_length=2, max_length=200)
    business_object_ref: str | None = Field(default=None, min_length=2, max_length=100)
    requested_capability_code: str | None = Field(default=None, min_length=2, max_length=80)
    calculation_as_of: datetime | None = None
    period: str | None = Field(default=None, min_length=2, max_length=40)
    temporary_analysis_spec: TemporaryAnalysisSpec | None = None
    execution_record_id: str | None = Field(default=None, min_length=2, max_length=100)
    human_action: HumanAction | None = None
    comment: str | None = Field(default=None, min_length=2, max_length=500)
    candidate_implementation: CandidateImplementationReference | None = None


class PlatformInstruction(OpenModel):
    protocol_version: str
    message_id: str = Field(min_length=2)
    trace_id: str = Field(min_length=4, max_length=80)
    request_id: str = Field(min_length=4, max_length=80)
    parent_message_id: str = ""
    occurred_at: datetime
    source: ServiceEndpoint
    target: ServiceEndpoint
    channel: str
    action: str
    request_type: str
    actor: ActorContext
    context: InstructionContext
    idempotency_key: str = Field(min_length=1, max_length=200)
    deadline_at: datetime
    payload: RuleCalculatePayload


class PlatformInstructionService:
    """Adapts the platform envelope to the engine's internal execution contract."""

    def __init__(
        self,
        database_path: Path,
        idempotency_records: IdempotencyRecordPort | None = None,
        engine: RuleEngineService | None = None,
    ) -> None:
        self.database_path = database_path
        self.idempotency_records = idempotency_records or SQLitePlatformDataAdapter(database_path)
        self.engine = engine or RuleEngineService(database_path)

    def handle(self, raw_instruction: dict[str, Any]) -> dict[str, Any]:
        try:
            instruction = PlatformInstruction.model_validate(raw_instruction)
            self._validate_instruction(instruction)
            data_ref = None
            if instruction.action in {"rule.evaluate", "rule.calculate"} and instruction.context.data_refs:
                data_ref = self._select_calculation_input(instruction.context.data_refs)
        except ValidationError as error:
            return self._failed(raw_instruction, "invalid_message", str(error))
        except PlatformContractError as error:
            return self._failed(raw_instruction, error.code, str(error))

        digest = self._request_digest(instruction)
        existing = self.idempotency_records.get_idempotency(
            instruction.source.service_code, instruction.action, instruction.idempotency_key
        )
        if existing and self._is_expired(existing["expires_at"]):
            self.idempotency_records.delete_idempotency(
                instruction.source.service_code, instruction.action, instruction.idempotency_key
            )
            existing = None
        if existing:
            if existing["request_digest"] != digest:
                return self._failed(
                    raw_instruction,
                    "idempotency_conflict",
                    "The same caller, action, and idempotency key were used with different request content.",
                )
            if existing.get("reply_json"):
                return self._replay(json.loads(existing["reply_json"]), instruction)
            return self._accepted_processing(instruction, existing.get("execution_record_id"))

        now = datetime.now(timezone.utc)
        claimed = self.idempotency_records.claim_idempotency(
            {
                "caller_service_code": instruction.source.service_code,
                "action": instruction.action,
                "idempotency_key": instruction.idempotency_key,
                "request_digest": digest,
                "status": "processing",
                "trace_id": instruction.trace_id,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "expires_at": (now + timedelta(days=IDEMPOTENCY_RETENTION_DAYS)).isoformat(),
            }
        )
        if not claimed:
            return self.handle(raw_instruction)

        try:
            reply, execution_record_id = self._dispatch_action(instruction, data_ref)
        except PlatformContractError as error:
            reply = self._failed(raw_instruction, error.code, str(error))
            execution_record_id = None
        except LookupError as error:
            reply = self._failed(raw_instruction, "resource_not_found", str(error))
            execution_record_id = None
        except PermissionError as error:
            reply = self._failed(raw_instruction, "permission_denied", str(error))
            execution_record_id = None
        except ValueError as error:
            reply = self._failed(raw_instruction, "conflict", str(error))
            execution_record_id = None
        self.idempotency_records.complete_idempotency(
            instruction.source.service_code,
            instruction.action,
            instruction.idempotency_key,
            "completed" if reply["reply_type"] != "failed" else "failed",
            execution_record_id,
            reply,
            datetime.now(timezone.utc).isoformat(),
        )
        return reply

    @staticmethod
    def _validate_instruction(instruction: PlatformInstruction) -> None:
        if instruction.protocol_version != PROTOCOL_VERSION:
            raise PlatformContractError("unsupported_protocol_version", "unsupported protocol version")
        if instruction.target.layer != "L2" or instruction.target.service_code != SERVICE_CODE:
            raise PlatformContractError("action_not_allowed", "target must be l2.rule_calculation in L2")
        if instruction.action not in PLATFORM_ACTIONS or instruction.request_type != "execute":
            raise PlatformContractError("action_not_allowed", "unsupported rule-calculation action")
        if instruction.source.service_code not in FLOW_SERVICE_CODES:
            raise PlatformContractError(
                "caller_not_allowed",
                "only the Flow Execution Engine may dispatch rule-calculation instructions",
            )
        if instruction.occurred_at.tzinfo is None or instruction.deadline_at.tzinfo is None:
            raise PlatformContractError("invalid_message", "occurred_at and deadline_at must include timezone")
        if instruction.payload.calculation_as_of and instruction.payload.calculation_as_of.tzinfo is None:
            raise PlatformContractError("invalid_message", "calculation_as_of must include timezone")
        if instruction.deadline_at.astimezone(timezone.utc) < datetime.now(timezone.utc):
            raise PlatformContractError("timeout", "deadline exceeded")

    def _dispatch_action(
        self,
        instruction: PlatformInstruction,
        data_ref: PlatformDataReference | None,
    ) -> tuple[dict[str, Any], str | None]:
        identity_context_ref = self._identity_context_ref(instruction)
        if instruction.action in {"rule.evaluate", "rule.calculate"}:
            if data_ref is None:
                assessment = self.engine.assess_preconditions(
                    PreconditionAssessmentRequest(
                        trace_id=instruction.trace_id,
                        request_id=instruction.request_id,
                        task_id=instruction.context.task_id,
                        subtask_id=instruction.context.subtask_id,
                        requester_id=instruction.context.requester_id,
                        node_name=instruction.payload.node_name,
                        task=instruction.payload.task,
                        service_ref=instruction.payload.service_ref,
                        identity_context_ref=identity_context_ref,
                        claimed_actor_id=instruction.actor.person_id,
                        business_type=instruction.payload.business_type,
                        requested_capability_code=instruction.payload.requested_capability_code,
                        business_object_id=instruction.payload.business_object_ref,
                        period=instruction.payload.period,
                    )
                )
                if assessment.state == "blocked":
                    raise PlatformContractError(
                        assessment.reason_code or "precondition_assessment_blocked",
                        assessment.message,
                    )
                return self._base_reply(
                    instruction,
                    "success",
                    {"result_type": "data", "data": assessment.model_dump(mode="json")},
                ), None
            result = self.engine.execute(
                ExecutionRequest(
                    trace_id=instruction.trace_id,
                    request_id=instruction.request_id,
                    task_id=instruction.context.task_id,
                    subtask_id=instruction.context.subtask_id,
                    requester_id=instruction.context.requester_id,
                    node_name=instruction.payload.node_name,
                    task=instruction.payload.task,
                    service_ref=instruction.payload.service_ref,
                    identity_context_ref=identity_context_ref,
                    claimed_actor_id=instruction.actor.person_id,
                    business_type=instruction.payload.business_type,
                    requested_capability_code=instruction.payload.requested_capability_code,
                    business_object_id=instruction.payload.business_object_ref,
                    period=instruction.payload.period,
                    calculation_as_of=instruction.payload.calculation_as_of,
                    data_reference=data_ref.ref_id,
                    request_data_references=[
                        RequestDataReference(
                            reference_id=item.ref_id,
                            purpose=item.purpose,
                            version=item.version,
                            data_labels=item.data_labels,
                            allowed_actions=item.allowed_actions,
                        )
                        for item in instruction.context.data_refs
                    ],
                    data_labels=data_ref.data_labels,
                    allowed_data_actions=data_ref.allowed_actions,
                    temporary_analysis_spec=instruction.payload.temporary_analysis_spec,
                )
            )
            return self._reply_for_result(instruction, result.model_dump(mode="json")), result.execution_record_id

        if instruction.action == "rule.candidate_skill_apply":
            if not instruction.payload.execution_record_id or not instruction.payload.human_action or not instruction.payload.comment:
                raise PlatformContractError("invalid_message", "candidate Skill application requires execution_record_id, human_action, and comment")
            handling = self.engine.handle_waiting_result(
                instruction.payload.execution_record_id,
                HumanHandlingRequest(
                    identity_context_ref=identity_context_ref,
                    action=instruction.payload.human_action,
                    comment=instruction.payload.comment,
                ),
            )
            return self._base_reply(
                instruction,
                "success",
                {"result_type": "data", "data": handling.model_dump(mode="json")},
            ), handling.execution_record_id

        if not instruction.payload.execution_record_id or not instruction.payload.candidate_implementation:
            raise PlatformContractError("invalid_message", "candidate trial requires execution_record_id and candidate_implementation")
        result = self.engine.resume_candidate_skill_trial(
            instruction.payload.execution_record_id,
            CandidateSkillTrialRequest(
                identity_context_ref=identity_context_ref,
                candidate_implementation=instruction.payload.candidate_implementation,
            ),
        )
        return self._reply_for_result(instruction, result.model_dump(mode="json")), result.execution_record_id

    @staticmethod
    def _identity_context_ref(instruction: PlatformInstruction) -> str:
        if instruction.context.identity_context_ref:
            return instruction.context.identity_context_ref
        return f"platform-actor:{instruction.actor.person_id}"

    @staticmethod
    def _request_digest(instruction: PlatformInstruction) -> str:
        semantic_request = {
            "source_service": instruction.source.service_code,
            "target_service": instruction.target.service_code,
            "action": instruction.action,
            "request_id": instruction.request_id,
            "actor": instruction.actor.model_dump(mode="json"),
            "context": instruction.context.model_dump(mode="json"),
            "payload": instruction.payload.model_dump(mode="json"),
        }
        canonical = json.dumps(
            semantic_request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _select_calculation_input(
        data_refs: list[PlatformDataReference],
    ) -> PlatformDataReference:
        explicit_inputs = [item for item in data_refs if item.purpose == "calculation_input"]
        if len(explicit_inputs) == 1:
            return explicit_inputs[0]
        if len(explicit_inputs) > 1:
            raise PlatformContractError(
                "invalid_message",
                "context.data_refs must contain exactly one calculation_input reference.",
            )
        if len(data_refs) == 1:
            return data_refs[0]
        raise PlatformContractError(
            "invalid_message",
            "Multiple data references require one explicit purpose=calculation_input.",
        )

    def _reply_for_result(
        self, instruction: PlatformInstruction, result: dict[str, Any]
    ) -> dict[str, Any]:
        state = result["state"]
        if state == ProcessingState.BLOCKED.value:
            return self._failed(
                instruction.model_dump(mode="json"),
                result.get("reason_code") or "rule_execution_blocked",
                result["message"],
                details={"execution_record_id": result.get("execution_record_id")},
            )
        if state == ProcessingState.WAITING_HUMAN.value:
            return self._base_reply(
                instruction,
                "accepted",
                {
                    "result_type": "task_receipt",
                    "task_id": result["execution_record_id"],
                    "state": state,
                    "handling_type": result.get("handling_type"),
                    "reason_code": result.get("reason_code"),
                    "query_action": "rule.execution.get",
                    "idempotency_key": instruction.idempotency_key,
                },
            )
        return self._base_reply(
            instruction,
            "success",
            {"result_type": "data", "data": result},
        )

    @staticmethod
    def _base_reply(
        instruction: PlatformInstruction, reply_type: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "reply_type": reply_type,
            "message_id": f"msg_{uuid4().hex}",
            "trace_id": instruction.trace_id,
            "request_id": instruction.request_id,
            "in_reply_to": instruction.message_id,
            "service_code": SERVICE_CODE,
            "service_version": "0.2.0",
            "occurred_at": now_iso(),
            "result": result,
            "error": None,
        }

    def _accepted_processing(
        self, instruction: PlatformInstruction, execution_record_id: str | None
    ) -> dict[str, Any]:
        return self._base_reply(
            instruction,
            "accepted",
            {
                "result_type": "task_receipt",
                "task_id": execution_record_id,
                "state": "processing",
                "query_action": "rule.execution.get",
                "idempotency_key": instruction.idempotency_key,
            },
        )

    @staticmethod
    def _replay(reply: dict[str, Any], instruction: PlatformInstruction) -> dict[str, Any]:
        replay = dict(reply)
        replay["message_id"] = f"msg_{uuid4().hex}"
        replay["in_reply_to"] = instruction.message_id
        replay["occurred_at"] = now_iso()
        return replay

    @staticmethod
    def _is_expired(expires_at: str) -> bool:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc)

    @staticmethod
    def _failed(
        instruction: dict[str, Any],
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "reply_type": "failed",
            "message_id": f"msg_{uuid4().hex}",
            "trace_id": instruction.get("trace_id", f"trace_{uuid4().hex}"),
            "request_id": instruction.get("request_id", f"req_{uuid4().hex}"),
            "in_reply_to": instruction.get("message_id", ""),
            "service_code": SERVICE_CODE,
            "service_version": "0.2.0",
            "occurred_at": now_iso(),
            "result": None,
            "error": {
                "code": code,
                "message": message,
                "retryable": code in {"timeout", "dependency_unavailable"},
                "details": details or {},
            },
        }
