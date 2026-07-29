from __future__ import annotations

from core.errors import BusinessError
from core.standard_reply import success


class ProjectTraceService:
    def __init__(self, repository):
        self.repository = repository

    def query_project_trace(self, *, project_id, trace_id):
        project = self.repository.get_project(project_id)
        if project is None:
            raise BusinessError(
                "PROJECT_NOT_FOUND",
                "项目不存在：" + project_id,
                http_status=404,
            )

        return success(
            trace_id=trace_id,
            data={
                "project_id": project_id,
                "project": project,
                "status_events": self.repository.get_status_events(
                    project_id
                ),
                "approval_records": self.repository.get_approval_records(
                    project_id
                ),
                "members": self.repository.list_members(
                    project_id,
                    include_exited=True,
                ),
                "member_events": self.repository.get_member_events(
                    project_id
                ),
                "permission_records": self.repository.get_permission_records(
                    project_id
                ),
                "closure_records": self.repository.get_closure_records(
                    project_id
                ),
                "bulk_revocation_items": (
                    self.repository.get_bulk_revocation_items(
                        project_id
                    )
                ),
                "archive_catalog": self.repository.get_archive_catalog(
                    project_id
                ),
                "archive_authorizations": (
                    self.repository.list_access_authorizations(
                        project_id
                    )
                ),
                "grade_change_records": self.repository.get_grade_change_records(project_id),
                "action_decisions": self.repository.get_action_decisions(project_id=project_id),
                "async_tasks": self.repository.list_async_tasks(project_id=project_id),
            },
            message="项目全过程查询成功",
        )
