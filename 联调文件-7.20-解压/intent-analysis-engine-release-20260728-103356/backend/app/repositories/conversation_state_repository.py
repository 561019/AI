from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConversationMessage


class ConversationStateRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def append_message(self, message: ConversationMessage) -> ConversationMessage:
        self.db.add(message)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(message)
        return message

    def list_recent(
        self,
        *,
        conversation_id: str,
        user_id: str,
        limit: int,
    ) -> list[ConversationMessage]:
        statement = (
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.user_id == user_id,
            )
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
        )
        return list(reversed(list(self.db.scalars(statement).all())))

    def delete_conversation(self, *, conversation_id: str, user_id: str) -> int:
        messages = self.list_recent(
            conversation_id=conversation_id,
            user_id=user_id,
            limit=10000,
        )
        for message in messages:
            self.db.delete(message)
        self.db.commit()
        return len(messages)
