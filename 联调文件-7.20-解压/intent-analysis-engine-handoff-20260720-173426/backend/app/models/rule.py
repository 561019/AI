from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuleMapping(Base):
    __tablename__ = "rule_mapping"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    keyword: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    function_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("function_registry.function_code"),
        nullable=False,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
