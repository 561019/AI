from __future__ import annotations

from core.errors import BusinessError
from domain.project_models import ProjectStatus


_ALLOWED_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.INITIATION_PENDING: {
        ProjectStatus.ACTIVE,
        ProjectStatus.APPROVAL_PENDING,
        ProjectStatus.REJECTED,
    },
    ProjectStatus.APPROVAL_PENDING: {
        ProjectStatus.ACTIVE,
        ProjectStatus.REJECTED,
    },
    ProjectStatus.ACTIVE: {ProjectStatus.CLOSING},
    ProjectStatus.CLOSING: {
        ProjectStatus.ARCHIVED,
        ProjectStatus.ACTIVE,
    },
    ProjectStatus.ARCHIVED: set(),
    ProjectStatus.REJECTED: set(),
}


def ensure_transition_allowed(current_status: ProjectStatus, target_status: ProjectStatus) -> None:
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise BusinessError(
            "PROJECT_STATE_NOT_ALLOWED",
            f"项目状态不允许转换：{current_status.value} -> {target_status.value}",
            http_status=409,
        )
