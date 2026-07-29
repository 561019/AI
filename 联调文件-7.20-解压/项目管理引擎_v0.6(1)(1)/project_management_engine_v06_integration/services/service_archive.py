from __future__ import annotations

from core.errors import BusinessError
from core.standard_reply import success


class ProjectArchiveService:
    def __init__(self, repository):
        self.repository = repository

    def query_archive_catalog(self, *, project_id, trace_id):
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
                "project_status": project["business_status"],
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
            },
            message="项目收尾与归档目录查询成功",
        )
