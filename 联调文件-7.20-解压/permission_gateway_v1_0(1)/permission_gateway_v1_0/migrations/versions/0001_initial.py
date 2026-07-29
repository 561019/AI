"""Create the independent permission schema.

Revision ID: 0001_initial
Revises:
"""
from typing import Sequence, Union

from alembic import op

from app.models import Base


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS permission_decisions_no_update
            BEFORE UPDATE ON permission_decisions
            BEGIN
                SELECT RAISE(ABORT, 'permission_decisions is append-only');
            END
            """
        )
        bind.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS permission_decisions_no_delete
            BEFORE DELETE ON permission_decisions
            BEGIN
                SELECT RAISE(ABORT, 'permission_decisions is append-only');
            END
            """
        )


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
