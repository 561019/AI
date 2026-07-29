"""Record the L1 layer-interface evidence with each decision.

Revision ID: 0003_layer_interface_audit_fields
Revises: 0002_account_person_identity
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_layer_interface_audit_fields"
down_revision: Union[str, None] = "0002_account_person_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("permission_decisions")}
    for name, length in (
        ("responsible_actor_id", 128),
        ("executor_type", 32),
        ("executor_id", 128),
        ("original_caller_service_id", 128),
        ("ingress_mode", 64),
        ("transfer_id", 255),
        ("identity_context_hash", 128),
    ):
        if name not in existing:
            op.add_column("permission_decisions", sa.Column(name, sa.String(length=length), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("permission_decisions")}
    if "ix_permission_decisions_transfer_id" not in indexes:
        op.create_index("ix_permission_decisions_transfer_id", "permission_decisions", ["transfer_id"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("permission_decisions")}
    if "ix_permission_decisions_transfer_id" in indexes:
        op.drop_index("ix_permission_decisions_transfer_id", table_name="permission_decisions")
    for name in ("identity_context_hash", "transfer_id", "ingress_mode", "original_caller_service_id", "executor_id", "executor_type", "responsible_actor_id"):
        op.drop_column("permission_decisions", name)
