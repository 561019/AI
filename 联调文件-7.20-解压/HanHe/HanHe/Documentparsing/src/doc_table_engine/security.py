from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class PermissionDenied(RuntimeError):
    pass


class PermissionPolicy(Protocol):
    def require(self, actor_id: str, action: str, business_tags: list[str]) -> None: ...


@dataclass
class StaticPermissionPolicy:
    """MVP 权限门禁；生产环境替换为平台 1.1 权限管理连接器。"""

    grants: dict[str, set[str]] = field(default_factory=dict)
    allow_demo_actor: bool = False

    def require(self, actor_id: str, action: str, business_tags: list[str]) -> None:
        if not actor_id.strip():
            raise PermissionDenied("必须提供当前操作真人 actor_id")
        if self.allow_demo_actor and actor_id == "demo-user":
            return
        allowed = self.grants.get(actor_id, set())
        required = {action, *(f"tag:{tag}" for tag in business_tags)}
        if action not in allowed and "*" not in allowed:
            raise PermissionDenied(f"真人 {actor_id} 无 {action} 权限")
        denied_tags = [item for item in required if item.startswith("tag:") and item not in allowed and "tag:*" not in allowed and "*" not in allowed]
        if denied_tags:
            raise PermissionDenied(f"真人 {actor_id} 无业务对象权限: {', '.join(denied_tags)}")


class HttpPermissionPolicy:
    """平台权限服务适配器，约定 POST JSON 并返回 ``{"allowed": true}``。"""

    def __init__(self, endpoint: str, api_key: str | None = None, timeout_seconds: float = 10):
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def require(self, actor_id: str, action: str, business_tags: list[str]) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("HTTP 权限校验需要安装 api 可选依赖") from exc
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = httpx.post(
            self.endpoint,
            headers=headers,
            json={"actor_id": actor_id, "action": action, "business_tags": business_tags},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("allowed"):
            raise PermissionDenied(payload.get("reason") or "权限服务拒绝该操作")
