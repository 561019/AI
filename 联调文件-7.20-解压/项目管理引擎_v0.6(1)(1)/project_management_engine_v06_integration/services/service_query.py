from __future__ import annotations

from core.errors import BusinessError
from core.standard_reply import success


class ProjectQueryService:
    def __init__(self, repository):
        self.repository = repository

    def get_project(self, *, project_id, trace_id):
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
                "project": project,
                "current_members": self.repository.list_members(
                    project_id,
                    include_exited=False,
                ),
                "status_events": self.repository.get_status_events(
                    project_id
                ),
                "approval_records": self.repository.get_approval_records(
                    project_id
                ),
                "grade_change_records": self.repository.get_grade_change_records(project_id),
            },
            message="项目查询成功",
        )

    def list_projects(self, *, trace_id):
        projects = self.repository.list_projects()
        for project in projects:
            project["active_member_count"] = len(
                self.repository.list_members(
                    project["project_id"],
                    include_exited=False,
                )
            )
        return success(
            trace_id=trace_id,
            data={"projects": projects},
            message="项目列表查询成功",
        )
