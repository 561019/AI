from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from app.core.enums import ModelScope


@dataclass
class ModelPolicy:
    route_mode: str = "open"
    model_scope: ModelScope = ModelScope.EXTERNAL_ALLOWED
    allowed_model_tags: List[str] = field(default_factory=lambda: ["external", "private", "local"])
    forbidden_model_tags: List[str] = field(default_factory=list)
    fallback_strategy: str = "external_or_private"
    reasons: List[str] = field(default_factory=list)

    @property
    def allow_external_model(self) -> bool:
        return self.model_scope == ModelScope.EXTERNAL_ALLOWED

    def restrict(self, scope: ModelScope, reason: str) -> None:
        self.model_scope = self._most_restrictive(self.model_scope, scope)
        self.reasons.append(reason)
        if self.model_scope == ModelScope.EXTERNAL_ALLOWED:
            self.route_mode = "open"
            self.allowed_model_tags = ["external", "private", "local"]
            self.forbidden_model_tags = []
            self.fallback_strategy = "external_or_private"
        elif self.model_scope == ModelScope.PRIVATE_ONLY:
            self.route_mode = "restricted"
            self.allowed_model_tags = ["private", "local"]
            self.forbidden_model_tags = ["external", "oversea"]
            self.fallback_strategy = "private_first"
        elif self.model_scope == ModelScope.LOCAL_ONLY:
            self.route_mode = "restricted"
            self.allowed_model_tags = ["local"]
            self.forbidden_model_tags = ["external", "oversea", "private_cloud"]
            self.fallback_strategy = "local_only"
        elif self.model_scope == ModelScope.FORBIDDEN:
            self.route_mode = "blocked"
            self.allowed_model_tags = []
            self.forbidden_model_tags = ["external", "oversea", "private", "local"]
            self.fallback_strategy = "none"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_mode": self.route_mode,
            "model_scope": self.model_scope.value,
            "allowed_model_tags": self.allowed_model_tags,
            "forbidden_model_tags": self.forbidden_model_tags,
            "fallback_strategy": self.fallback_strategy,
            "reasons": self.reasons,
        }

    @staticmethod
    def _most_restrictive(a: ModelScope, b: ModelScope) -> ModelScope:
        order = {ModelScope.EXTERNAL_ALLOWED: 0, ModelScope.PRIVATE_ONLY: 1, ModelScope.LOCAL_ONLY: 2, ModelScope.FORBIDDEN: 3}
        return a if order[a] >= order[b] else b
