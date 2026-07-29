from __future__ import annotations

from datetime import datetime, timezone

from core.idempotency import get_cached_reply, save_reply
from core.standard_reply import accepted, success
from domain.project_models import ProjectGrade, ProjectRegistrationCommand, ProjectStatus
from domain.project_number_generator import generate_project_number
from domain.project_rules import validate_registration


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectRegistrationService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def register(
        self,
        *,
        payload: dict,
        trace_id: str,
        idempotency_key: str,
        operator_person_id: str,
        workflow_instance_id: str | None = None,
    ) -> dict:
        grade = ProjectGrade(payload.get("project_grade", "SIMPLE"))
        action = (
            "project.register.major"
            if grade == ProjectGrade.MAJOR
            else "project.register.simple"
        )

        cached = get_cached_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=payload,
        )
        if cached is not None:
            return cached

        command = ProjectRegistrationCommand(
            project_name=str(payload.get("project_name", "")),
            project_category=str(payload.get("project_category", "")),
            project_grade=grade,
            budget_attribute=str(payload.get("budget_attribute", "")),
            initiator_person_id=str(payload.get("initiator_person_id") or operator_person_id),
            description=payload.get("description"),
        )
        validate_registration(command)

        project_id = generate_project_number(self.repository)
        created_at = utc_now_text()

        if grade == ProjectGrade.SIMPLE:
            status = ProjectStatus.ACTIVE
            lifecycle_phase = "IN_PROGRESS"
            activated_at = created_at
        else:
            status = ProjectStatus.APPROVAL_PENDING
            lifecycle_phase = "INITIATION"
            activated_at = None

        project = {
            "project_id": project_id,
            "project_name": command.project_name.strip(),
            "project_category": command.project_category.strip(),
            "project_grade": grade.value,
            "budget_attribute": command.budget_attribute.strip(),
            "lifecycle_phase": lifecycle_phase,
            "business_status": status.value,
            "initiator_person_id": command.initiator_person_id,
            "description": command.description,
            "approval_workflow_id": workflow_instance_id,
            "approval_basis_ref": None,
            "created_at": created_at,
            "activated_at": activated_at,
            "archived_at": None,
            "version": 1,
            "last_trace_id": trace_id,
        }

        self.repository.create_project(project)
        self.repository.append_status_event(
            project_id=project_id,
            from_status=None,
            to_status=status.value,
            event_type=(
                "SIMPLE_PROJECT_REGISTERED"
                if grade == ProjectGrade.SIMPLE
                else "MAJOR_PROJECT_SUBMITTED"
            ),
            operator_person_id=operator_person_id,
            trace_id=trace_id,
            workflow_instance_id=workflow_instance_id,
        )

        data = {
            "project": self.repository.get_project(project_id),
            "next_action": (
                None
                if grade == ProjectGrade.SIMPLE
                else "等待流程执行引擎组织重大项目审批"
            ),
        }

        if grade == ProjectGrade.SIMPLE:
            reply = success(
                trace_id=trace_id,
                data=data,
                message="普通项目登记完成，项目已成立",
                http_status=201,
            )
        else:
            reply = accepted(
                trace_id=trace_id,
                data=data,
                message="重大项目登记已受理，等待审批结果",
                http_status=202,
            )

        save_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=payload,
            reply=reply,
        )
        return reply
