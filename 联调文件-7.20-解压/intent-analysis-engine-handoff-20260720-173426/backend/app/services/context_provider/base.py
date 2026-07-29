from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.context_provider.schemas import ContextProviderResponse


class BaseContextProvider(ABC):
    """External context dependency consumed by the intent analysis engine."""

    @abstractmethod
    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        project_id: str | None = None,
    ) -> ContextProviderResponse:
        """Return conversation, project, and historical project context."""
