from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from threading import RLock
from typing import Any

from pydantic import BaseModel

from app.models import ConversationMessage
from app.repositories.conversation_state_repository import ConversationStateRepository


class ConversationStateItem(BaseModel):
    role: str
    text: str
    analysis_result: dict[str, Any] | None = None


class ConversationStateStore(ABC):
    @abstractmethod
    def load_history(
        self,
        *,
        conversation_id: str,
        user_id: str,
        limit: int,
    ) -> list[ConversationStateItem]:
        raise NotImplementedError

    @abstractmethod
    def append_turn(
        self,
        *,
        conversation_id: str,
        user_id: str,
        text: str,
        analysis_result: dict[str, Any] | None,
    ) -> None:
        raise NotImplementedError


class PostgresConversationStateStore(ConversationStateStore):
    def __init__(self, repository: ConversationStateRepository) -> None:
        self.repository = repository

    def load_history(
        self,
        *,
        conversation_id: str,
        user_id: str,
        limit: int,
    ) -> list[ConversationStateItem]:
        return [
            ConversationStateItem(
                role=message.role,
                text=message.content,
                analysis_result=message.analysis_result,
            )
            for message in self.repository.list_recent(
                conversation_id=conversation_id,
                user_id=user_id,
                limit=limit,
            )
        ]

    def append_turn(
        self,
        *,
        conversation_id: str,
        user_id: str,
        text: str,
        analysis_result: dict[str, Any] | None,
    ) -> None:
        self.repository.append_message(
            ConversationMessage(
                conversation_id=conversation_id,
                user_id=user_id,
                role="user",
                content=text,
                analysis_result=analysis_result,
            )
        )


class InMemoryConversationStateStore(ConversationStateStore):
    """Thread-safe state store for tests and local non-persistent use."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], list[ConversationStateItem]] = defaultdict(list)
        self._lock = RLock()

    def load_history(
        self,
        *,
        conversation_id: str,
        user_id: str,
        limit: int,
    ) -> list[ConversationStateItem]:
        with self._lock:
            return list(self._items[(user_id, conversation_id)][-limit:])

    def append_turn(
        self,
        *,
        conversation_id: str,
        user_id: str,
        text: str,
        analysis_result: dict[str, Any] | None,
    ) -> None:
        with self._lock:
            self._items[(user_id, conversation_id)].append(
                ConversationStateItem(
                    role="user",
                    text=text,
                    analysis_result=analysis_result,
                )
            )

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
