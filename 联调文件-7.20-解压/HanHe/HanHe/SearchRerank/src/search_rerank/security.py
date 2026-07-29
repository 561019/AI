from __future__ import annotations

from dataclasses import dataclass

import httpx


class PermissionDenied(RuntimeError):
    pass


@dataclass
class PermissionPolicy:
    endpoint: str | None = None
    api_key: str | None = None
    allow_demo_actor: bool = True

    def require(self, actor_id: str, action: str, business_tags: list[str]) -> None:
        if not actor_id.strip():
            raise PermissionDenied("X-Actor-ID is required")
        if not business_tags:
            raise PermissionDenied("at least one authorized business tag is required")
        if not self.endpoint:
            if self.allow_demo_actor and actor_id == "demo-user":
                return
            raise PermissionDenied("permission service is not configured for this actor")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = httpx.post(
            self.endpoint,
            headers=headers,
            json={"actor_id": actor_id, "action": action, "business_tags": business_tags},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("allowed"):
            raise PermissionDenied(payload.get("reason") or "permission service denied the request")

