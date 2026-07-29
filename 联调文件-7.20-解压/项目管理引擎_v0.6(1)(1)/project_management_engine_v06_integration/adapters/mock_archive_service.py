from __future__ import annotations

from uuid import uuid4


class MockArchiveService:
    """
    模拟数据操作引擎组织归档、L1.7 执行物理存取后的结果。
    """

    def archive_project(self, *, project_id, archive_mode, resources):
        mode = str(archive_mode or "SUCCESS").upper()

        if mode == "FAIL":
            return {
                "status": "FAILED",
                "archive_catalog_ref": None,
                "items": [],
                "reason": "MOCK_ARCHIVE_FAILED",
                "mock": True,
            }

        items = []
        for index, resource in enumerate(resources or [], start=1):
            items.append({
                "catalog_item_id": "CATALOG_" + uuid4().hex[:16].upper(),
                "resource_type": resource.get("resource_type", "PROJECT_DATA"),
                "resource_name": resource.get("resource_name", "资源{}".format(index)),
                "data_ref": resource.get("data_ref"),
                "artifact_ref": resource.get("artifact_ref"),
                "asset_ref": resource.get("asset_ref"),
                "version": resource.get("version", "v1"),
                "data_labels": resource.get("data_labels", ["project_archive"]),
                "archive_status": "SEALED" if mode == "SUCCESS" else "PARTIAL",
            })

        if not items:
            items = [
                {
                    "catalog_item_id": "CATALOG_" + uuid4().hex[:16].upper(),
                    "resource_type": "PROJECT_REGISTRY",
                    "resource_name": "项目台账快照",
                    "data_ref": "DATAREF_PROJECT_" + project_id,
                    "artifact_ref": None,
                    "asset_ref": None,
                    "version": "v1",
                    "data_labels": ["project_archive", "registry"],
                    "archive_status": "SEALED" if mode == "SUCCESS" else "PARTIAL",
                }
            ]

        return {
            "status": "SUCCESS" if mode == "SUCCESS" else "PARTIAL",
            "archive_catalog_ref": "ARCHIVE_CATALOG_" + project_id,
            "items": items,
            "reason": None if mode == "SUCCESS" else "MOCK_ARCHIVE_PARTIAL",
            "mock": True,
        }
