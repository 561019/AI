from __future__ import annotations

from http import HTTPStatus

from .audit import write_audit_event
from .utils import ApiError


def check_permission(
    *,
    actor_id: str,
    action: str,
    resource_type: str,
    scope_level: str | None,
    scope_id: str | None,
    resource_id: str | None = None,
) -> None:
    """Week-1 mock adapter for module 1.8.

    Rules:
    - actor_id `blocked` is denied, useful for testing.
    - all other requests are allowed.
    - every decision is audited locally.
    """
    allowed = actor_id != "blocked"
    write_audit_event(
        actor_id=actor_id,
        action=f"permission.{action}",
        resource_type=resource_type,
        resource_id=resource_id,
        scope_level=scope_level,
        scope_id=scope_id,
        permission_result="allow" if allowed else "deny",
    )
    if not allowed:
        raise ApiError(HTTPStatus.FORBIDDEN, "Permission denied by mock adapter")

