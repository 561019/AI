"""create conversation message table

Revision ID: 20260713_0002
Revises: 20260709_0001
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260713_0002"
down_revision: str | None = "20260709_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_message",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("conversation_id", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("analysis_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_conversation_message_conversation_id", "conversation_message", ["conversation_id"])
    op.create_index("idx_conversation_message_user_id", "conversation_message", ["user_id"])
    op.create_index("idx_conversation_message_role", "conversation_message", ["role"])
    op.create_index(
        "idx_conversation_message_lookup",
        "conversation_message",
        ["user_id", "conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_conversation_message_lookup", table_name="conversation_message")
    op.drop_index("idx_conversation_message_role", table_name="conversation_message")
    op.drop_index("idx_conversation_message_user_id", table_name="conversation_message")
    op.drop_index("idx_conversation_message_conversation_id", table_name="conversation_message")
    op.drop_table("conversation_message")
