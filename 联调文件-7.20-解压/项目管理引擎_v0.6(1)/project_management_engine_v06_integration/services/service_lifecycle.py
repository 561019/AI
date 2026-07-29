from __future__ import annotations

from datetime import datetime, timezone

from core.errors import BusinessError
from core.idempotency import get_cached_reply, save_reply
from core.standard_reply import success
from domain.project_models import ProjectStatus
from domain.project_state_machine import ensure_transition_allowed


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectLifecycleService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def record_approval_result(
        self,
        *,
        project_id: str,
        payload: dict,
        trace_id: str,
        idempotency_key: str,
        operator_person_id: str,
        workflow_instance_id: str | None = None,
    ) -> dict:
        action = "project.approval.result.record"
        request_payload = {"project_id": project_id, **payload}

        cached = get_cached_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
        )
        if cached is not None:
            return cached

        project = self.repository.get_project(project_id)
        if project is None:
            raise BusinessError("PROJECT_NOT_FOUND", f"项目不存在：{project_id}", http_status=404)

        current = ProjectStatus(project["business_status"])
        if current != ProjectStatus.APPROVAL_PENDING:
            raise BusinessError(
                "APPROVAL_RESULT_NOT_ALLOWED",
                "只有待审批的重大项目可以登记审批结果",
                http_status=409,
            )

        approval_result = str(payload.get("approval_result", "")).upper()
        if approval_result not in {"APPROVED", "REJECTED"}:
            raise BusinessError(
                "INVALID_APPROVAL_RESULT",
                "approval_result 只能是 APPROVED 或 REJECTED",
            )

        target = ProjectStatus.ACTIVE if approval_result == "APPROVED" else ProjectStatus.REJECTED
        ensure_transition_allowed(current, target)

        approval_basis_ref = payload.get("approval_basis_ref")
        activated_at = utc_now_text() if target == ProjectStatus.ACTIVE else None
        lifecycle_phase = "IN_PROGRESS" if target == ProjectStatus.ACTIVE else "INITIATION"

        self.repository.append_approval_record(
            project_id=project_id,
            approval_result=approval_result,
            approval_basis_ref=approval_basis_ref,
            workflow_instance_id=workflow_instance_id,
            operator_person_id=operator_person_id,
            trace_id=trace_id,
        )
        self.repository.update_project_status(
            project_id=project_id,
            target_status=target.value,
            lifecycle_phase=lifecycle_phase,
            trace_id=trace_id,
            activated_at=activated_at,
            approval_basis_ref=approval_basis_ref,
        )
        self.repository.append_status_event(
            project_id=project_id,
            from_status=current.value,
            to_status=target.value,
            event_type=(
                "MAJOR_PROJECT_APPROVED"
                if target == ProjectStatus.ACTIVE
                else "MAJOR_PROJECT_REJECTED"
            ),
            event_reason=payload.get("approval_comment"),
            basis_ref=approval_basis_ref,
            workflow_instance_id=workflow_instance_id,
            operator_person_id=operator_person_id,
            trace_id=trace_id,
        )

        reply = success(
            trace_id=trace_id,
            data={
                "project": self.repository.get_project(project_id),
                "approval_records": self.repository.get_approval_records(project_id),
            },
            message=(
                "重大项目审批通过，项目登记生效"
                if target == ProjectStatus.ACTIVE
                else "重大项目审批未通过，项目未成立"
            ),
        )

        save_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
            reply=reply,
        )
        return reply
