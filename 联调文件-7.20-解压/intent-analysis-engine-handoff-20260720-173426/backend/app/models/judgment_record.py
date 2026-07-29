from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IntentRecord(Base):
    __tablename__ = "intent_record"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    analysis_level: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    matched_function: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("function_registry.function_code"),
        nullable=True,
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    result: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cost_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
