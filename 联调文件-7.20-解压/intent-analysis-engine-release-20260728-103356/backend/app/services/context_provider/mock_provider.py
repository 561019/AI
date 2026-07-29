from __future__ import annotations

from typing import Any

from app.services.context_provider.base import BaseContextProvider
from app.services.context_provider.schemas import ContextProviderResponse


class MockContextProvider(BaseContextProvider):
    """Test-only context provider that does not depend on a real context system."""

    def __init__(
        self,
        *,
        default_context: ContextProviderResponse | dict[str, Any] | None = None,
        contexts: dict[tuple[str, str, str | None], ContextProviderResponse | dict[str, Any]] | None = None,
    ) -> None:
        self.default_context = self._coerce(default_context)
        self.contexts = {
            key: self._coerce(value)
            for key, value in (contexts or {}).items()
        }
        self.calls: list[dict[str, str | None]] = []

    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        project_id: str | None = None,
    ) -> ContextProviderResponse:
        self.calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "project_id": project_id,
            }
        )
        return self.contexts.get((user_id, conversation_id, project_id), self.default_context)

    def _coerce(self, value: ContextProviderResponse | dict[str, Any] | None) -> ContextProviderResponse:
        if value is None:
            return ContextProviderResponse()
        if isinstance(value, ContextProviderResponse):
            return value
        return ContextProviderResponse.model_validate(value)
