from __future__ import annotations

from datetime import datetime, timezone
from core.errors import BusinessError
from core.idempotency import get_cached_reply, save_reply
from core.standard_reply import success
from domain.project_models import ProjectGrade


def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


class ProjectGradeService:
    def __init__(self, repository):
        self.repository = repository

    def validate_request(self, *, project_id, target_grade):
        project = self.repository.get_project(project_id)
        if project is None:
            raise BusinessError("PROJECT_NOT_FOUND", "项目不存在：" + project_id, http_status=404)
        if project["business_status"] != "ACTIVE":
            raise BusinessError("PROJECT_STATE_NOT_ALLOWED", "只有进行中的项目可以申请档位转换", http_status=409)
        try:
            grade = ProjectGrade(str(target_grade).upper())
        except ValueError:
            raise BusinessError("INVALID_PROJECT_GRADE", "target_grade 只能是 SIMPLE 或 MAJOR", http_status=400)
        if project["project_grade"] == grade.value:
            raise BusinessError("PROJECT_GRADE_UNCHANGED", "目标档位与当前档位相同", http_status=409)
        return project, grade.value

    def record_result(self, *, project_id, payload, trace_id, idempotency_key, operator_person_id, workflow_instance_id=None, task_id=None):
        action = "project.grade.change.result.record"
        request_payload = {"project_id": project_id, **payload, "task_id": task_id}
        cached = get_cached_reply(self.repository, idempotency_key=idempotency_key, action=action, payload=request_payload)
        if cached is not None:
            return cached
        project, target_grade = self.validate_request(project_id=project_id, target_grade=payload.get("target_grade"))
        result = str(payload.get("change_result", "")).upper()
        if result not in {"APPROVED", "REJECTED"}:
            raise BusinessError("INVALID_GRADE_CHANGE_RESULT", "change_result 只能是 APPROVED 或 REJECTED", http_status=400)
        basis_ref = payload.get("change_basis_ref")
        if not basis_ref:
            raise BusinessError("GRADE_CHANGE_BASIS_REQUIRED", "档位转换结果必须提供审批依据引用", http_status=400)
        record = {
            "grade_change_record_id": self.repository.new_grade_change_record_id(),
            "project_id": project_id,
            "from_grade": project["project_grade"],
            "target_grade": target_grade,
            "change_result": result,
            "change_basis_ref": basis_ref,
            "change_reason": payload.get("change_reason"),
            "workflow_instance_id": workflow_instance_id,
            "task_id": task_id,
            "operator_person_id": operator_person_id,
            "trace_id": trace_id,
            "created_at": utc_now_text(),
        }
        self.repository.append_grade_change_record(record)
        if result == "APPROVED":
            self.repository.update_project_grade(project_id=project_id, target_grade=target_grade, trace_id=trace_id)
        self.repository.append_status_event(
            project_id=project_id,
            from_status="ACTIVE",
            to_status="ACTIVE",
            event_type="PROJECT_GRADE_CHANGED" if result == "APPROVED" else "PROJECT_GRADE_CHANGE_REJECTED",
            event_reason=payload.get("change_reason"),
            basis_ref=basis_ref,
            operator_person_id=operator_person_id,
            workflow_instance_id=workflow_instance_id,
            trace_id=trace_id,
        )
        reply = success(
            trace_id=trace_id,
            data={"project": self.repository.get_project(project_id), "grade_change_records": self.repository.get_grade_change_records(project_id)},
            message="项目档位转换已登记生效" if result == "APPROVED" else "项目档位转换未通过，原档位保持不变",
        )
        save_reply(self.repository, idempotency_key=idempotency_key, action=action, payload=request_payload, reply=reply)
        return reply
