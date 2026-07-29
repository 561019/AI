"""Persist the effective permission facts created by asset publication.

Revision ID: 0004_resource_publication_grants
Revises: 0003_layer_interface_audit_fields
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_resource_publication_grants"
down_revision: Union[str, None] = "0003_layer_interface_audit_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "resource_publication_grants" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "resource_publication_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("publication_id", sa.Integer(), sa.ForeignKey("resource_publications.id"), nullable=False),
        sa.Column("position_permission_id", sa.Integer(), sa.ForeignKey("position_standard_permissions.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("publication_id", "position_permission_id"),
    )


def downgrade() -> None:
    if "resource_publication_grants" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("resource_publication_grants")
