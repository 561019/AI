from __future__ import annotations

from datetime import datetime, timezone

from core.errors import BusinessError
from core.idempotency import get_cached_reply, save_reply
from core.standard_reply import failed, success
from domain.project_models import ProjectStatus
from domain.project_state_machine import ensure_transition_allowed


def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


class ProjectClosureService:
    def __init__(
        self,
        repository,
        permission_management,
        archive_service
    ):
        self.repository = repository
        self.permission_management = permission_management
        self.archive_service = archive_service

    def close_project(
        self,
        *,
        project_id,
        payload,
        trace_id,
        idempotency_key,
        operator_person_id,
        workflow_instance_id=None
    ):
        action = "project.closure.execute"
        request_payload = {"project_id": project_id}
        request_payload.update(payload)

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
            raise BusinessError(
                "PROJECT_NOT_FOUND",
                "项目不存在：" + project_id,
                http_status=404,
            )

        current_status = ProjectStatus(project["business_status"])
        if current_status not in {
            ProjectStatus.ACTIVE,
            ProjectStatus.CLOSING,
        }:
            raise BusinessError(
                "PROJECT_STATE_NOT_ALLOWED",
                "只有进行中或收尾中的项目可以办理项目收尾",
                http_status=409,
            )

        closure_basis_ref = payload.get("closure_basis_ref")
        if not closure_basis_ref:
            raise BusinessError(
                "CLOSURE_BASIS_REQUIRED",
                "项目收尾必须提供办结或解散依据引用",
                http_status=400,
            )

        if current_status == ProjectStatus.ACTIVE:
            ensure_transition_allowed(
                ProjectStatus.ACTIVE,
                ProjectStatus.CLOSING,
            )
            self.repository.update_project_status(
                project_id=project_id,
                target_status="CLOSING",
                lifecycle_phase="CLOSURE",
                trace_id=trace_id,
            )
            self.repository.append_status_event(
                project_id=project_id,
                from_status="ACTIVE",
                to_status="CLOSING",
                event_type="PROJECT_CLOSURE_STARTED",
                event_reason=payload.get("closure_reason"),
                basis_ref=closure_basis_ref,
                operator_person_id=operator_person_id,
                workflow_instance_id=workflow_instance_id,
                trace_id=trace_id,
            )

        active_members = self.repository.list_members(
            project_id,
            include_exited=False,
        )
        closure_record_id = self.repository.new_closure_record_id()

        revoked_count = 0
        failed_count = 0
        revocation_failures = []
        revocation_items = []

        for member in active_members:
            decision = self.permission_management.decide(
                person_id=member["person_id"],
                action="project.member.revoke",
                resource_scope=member["permission_scope"],
                allowed_actions=member["allowed_actions"],
                basis_ref=closure_basis_ref,
            )

            self.repository.append_permission_record(
                member_record_id=member["member_record_id"],
                project_id=project_id,
                person_id=member["person_id"],
                permission_action="BULK_REVOKE",
                requested_scope=member["permission_scope"],
                allowed_actions=member["allowed_actions"],
                basis_ref=closure_basis_ref,
                decision_id=decision["decision_id"],
                decision_result=(
                    "ALLOW" if decision["allow"] else "DENY"
                ),
                decision_reason=decision["reason"],
                operator_person_id=operator_person_id,
                trace_id=trace_id,
            )

            revocation_items.append({
                "closure_record_id": closure_record_id,
                "project_id": project_id,
                "member_record_id": member["member_record_id"],
                "person_id": member["person_id"],
                "decision_id": decision["decision_id"],
                "decision_result": (
                    "ALLOW" if decision["allow"] else "DENY"
                ),
                "decision_reason": decision["reason"],
                "trace_id": trace_id,
                "created_at": utc_now_text(),
            })

            if decision["allow"]:
                self.repository.exit_member(
                    member_record_id=member["member_record_id"],
                    left_at=utc_now_text(),
                    decision_id=decision["decision_id"],
                    trace_id=trace_id,
                )
                self.repository.append_member_event(
                    member_record_id=member["member_record_id"],
                    project_id=project_id,
                    person_id=member["person_id"],
                    event_type="MEMBER_BULK_REVOKED_ON_CLOSURE",
                    event_result="SUCCESS",
                    project_role=member["project_role"],
                    position_code=member["position_code"],
                    decision_id=decision["decision_id"],
                    reason="项目收尾批量收权成功",
                    operator_person_id=operator_person_id,
                    trace_id=trace_id,
                )
                revoked_count += 1
            else:
                self.repository.append_member_event(
                    member_record_id=member["member_record_id"],
                    project_id=project_id,
                    person_id=member["person_id"],
                    event_type="MEMBER_BULK_REVOCATION_FAILED",
                    event_result="FAILED",
                    project_role=member["project_role"],
                    position_code=member["position_code"],
                    decision_id=decision["decision_id"],
                    reason=decision["reason"],
                    operator_person_id=operator_person_id,
                    trace_id=trace_id,
                )
                failed_count += 1
                revocation_failures.append(member["person_id"])

        revocation_status = (
            "SUCCESS" if failed_count == 0 else "FAILED"
        )

        archive_result = self.archive_service.archive_project(
            project_id=project_id,
            archive_mode=payload.get("archive_mode", "SUCCESS"),
            resources=payload.get("archive_resources") or [],
        )
        archive_status = archive_result["status"]

        completed = (
            revocation_status == "SUCCESS"
            and archive_status == "SUCCESS"
        )

        failure_reasons = []
        if revocation_status != "SUCCESS":
            failure_reasons.append(
                "批量收权失败成员："
                + ",".join(revocation_failures)
            )
        if archive_status != "SUCCESS":
            failure_reasons.append(
                archive_result.get("reason") or "归档未完成"
            )

        closure_status = "COMPLETED" if completed else "FAILED"
        failure_reason = (
            None if completed else "；".join(failure_reasons)
        )
        created_at = utc_now_text()

        # 必须先写收尾主记录，再写引用它的逐成员收权明细和归档目录。
        self.repository.create_closure_record({
            "closure_record_id": closure_record_id,
            "project_id": project_id,
            "closure_status": closure_status,
            "closure_basis_ref": closure_basis_ref,
            "revocation_status": revocation_status,
            "archive_status": archive_status,
            "active_member_count": len(active_members),
            "revoked_member_count": revoked_count,
            "failed_member_count": failed_count,
            "archive_catalog_ref": archive_result.get(
                "archive_catalog_ref"
            ),
            "failure_reason": failure_reason,
            "operator_person_id": operator_person_id,
            "workflow_instance_id": workflow_instance_id,
            "trace_id": trace_id,
            "created_at": created_at,
            "completed_at": utc_now_text() if completed else None,
        })

        for revocation_item in revocation_items:
            self.repository.append_bulk_revocation_item(
                revocation_item
            )

        for item in archive_result.get("items", []):
            item_to_save = dict(item)
            item_to_save.update({
                "closure_record_id": closure_record_id,
                "project_id": project_id,
                "sealed_at": (
                    utc_now_text()
                    if item["archive_status"] == "SEALED"
                    else None
                ),
                "trace_id": trace_id,
                "created_at": utc_now_text(),
            })
            self.repository.append_archive_catalog_item(
                item_to_save
            )

        if completed:
            ensure_transition_allowed(
                ProjectStatus.CLOSING,
                ProjectStatus.ARCHIVED,
            )
            archived_at = utc_now_text()
            self.repository.update_project_status(
                project_id=project_id,
                target_status="ARCHIVED",
                lifecycle_phase="ARCHIVED",
                trace_id=trace_id,
                archived_at=archived_at,
            )
            self.repository.append_status_event(
                project_id=project_id,
                from_status="CLOSING",
                to_status="ARCHIVED",
                event_type="PROJECT_ARCHIVED",
                event_reason="批量收权和归档均已完成",
                basis_ref=closure_basis_ref,
                operator_person_id=operator_person_id,
                workflow_instance_id=workflow_instance_id,
                trace_id=trace_id,
            )

            reply = success(
                trace_id=trace_id,
                data={
                    "project": self.repository.get_project(project_id),
                    "closure_record": self.repository.get_closure_records(
                        project_id
                    )[-1],
                    "archive_catalog": self.repository.get_archive_catalog(
                        project_id
                    ),
                },
                message="项目收权和归档均已完成，项目已封存",
            )
        else:
            reply = failed(
                trace_id=trace_id,
                code="PROJECT_CLOSURE_INCOMPLETE",
                message=(
                    "项目收尾未全部完成，项目保持 CLOSING 状态："
                    + failure_reason
                ),
                retryable=True,
                http_status=409,
            )

        save_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
            reply=reply,
        )
        return reply
