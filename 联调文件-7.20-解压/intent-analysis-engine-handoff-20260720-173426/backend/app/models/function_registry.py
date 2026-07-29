from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FunctionRegistry(Base):
    __tablename__ = "function_registry"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    function_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    function_name: Mapped[str] = mapped_column(String(200), nullable=False)
    intent_category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_engine: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    example_sentences: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
