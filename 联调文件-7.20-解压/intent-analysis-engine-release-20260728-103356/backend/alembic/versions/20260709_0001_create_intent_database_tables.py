"""create intent database tables

Revision ID: 20260709_0001
Revises:
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260709_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "function_registry",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("function_code", sa.String(length=64), nullable=False),
        sa.Column("function_name", sa.String(length=200), nullable=False),
        sa.Column("intent_category", sa.String(length=80), nullable=False),
        sa.Column("target_engine", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("example_sentences", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("function_code"),
    )
    op.create_index("idx_function_registry_function_code", "function_registry", ["function_code"])
    op.create_index("idx_function_registry_intent_category", "function_registry", ["intent_category"])
    op.create_index("idx_function_registry_target_engine", "function_registry", ["target_engine"])
    op.create_index("idx_function_registry_status", "function_registry", ["status"])

    op.create_table(
        "rule_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("keyword", sa.String(length=120), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=True),
        sa.Column("function_code", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["function_code"], ["function_registry.function_code"]),
    )
    op.create_index("idx_rule_mapping_keyword", "rule_mapping", ["keyword"])
    op.create_index("idx_rule_mapping_function_code", "rule_mapping", ["function_code"])
    op.create_index("idx_rule_mapping_status", "rule_mapping", ["status"])

    op.create_table(
        "intent_record",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("conversation_id", sa.String(length=120), nullable=False),
        sa.Column("analysis_level", sa.String(length=64), nullable=False),
        sa.Column("matched_function", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("result", sa.String(length=64), nullable=False),
        sa.Column("cost_time", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["matched_function"], ["function_registry.function_code"]),
    )
    op.create_index("idx_intent_record_user_id", "intent_record", ["user_id"])
    op.create_index("idx_intent_record_conversation_id", "intent_record", ["conversation_id"])
    op.create_index("idx_intent_record_analysis_level", "intent_record", ["analysis_level"])
    op.create_index("idx_intent_record_matched_function", "intent_record", ["matched_function"])
    op.create_index("idx_intent_record_result", "intent_record", ["result"])


def downgrade() -> None:
    op.drop_index("idx_intent_record_result", table_name="intent_record")
    op.drop_index("idx_intent_record_matched_function", table_name="intent_record")
    op.drop_index("idx_intent_record_analysis_level", table_name="intent_record")
    op.drop_index("idx_intent_record_conversation_id", table_name="intent_record")
    op.drop_index("idx_intent_record_user_id", table_name="intent_record")
    op.drop_table("intent_record")

    op.drop_index("idx_rule_mapping_status", table_name="rule_mapping")
    op.drop_index("idx_rule_mapping_function_code", table_name="rule_mapping")
    op.drop_index("idx_rule_mapping_keyword", table_name="rule_mapping")
    op.drop_table("rule_mapping")

    op.drop_index("idx_function_registry_status", table_name="function_registry")
    op.drop_index("idx_function_registry_target_engine", table_name="function_registry")
    op.drop_index("idx_function_registry_intent_category", table_name="function_registry")
    op.drop_index("idx_function_registry_function_code", table_name="function_registry")
    op.drop_table("function_registry")
