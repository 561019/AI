from __future__ import annotations

from app.services.context_provider.base import BaseContextProvider
from app.services.context_provider.mock_provider import MockContextProvider
from app.services.context_provider.schemas import ContextProviderResponse


class ContextProviderClient(BaseContextProvider):
    """Adapter entry point for an external context service.

    The engine owns only this consumption boundary; the real Context & Prompt
    Management implementation can replace the provider behind this client.
    """

    def __init__(self, provider: BaseContextProvider | None = None) -> None:
        self.provider = provider or MockContextProvider()

    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        project_id: str | None = None,
    ) -> ContextProviderResponse:
        return self.provider.get_context(
            user_id=user_id,
            conversation_id=conversation_id,
            project_id=project_id,
        )
