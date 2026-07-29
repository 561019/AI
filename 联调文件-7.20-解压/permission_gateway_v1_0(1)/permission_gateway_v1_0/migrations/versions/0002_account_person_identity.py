"""Enforce one real-name account identity.

Revision ID: 0002_account_person_identity
Revises: 0001_initial
"""
from typing import Sequence, Union

from alembic import op

from app.database import SQLITE_TRIGGERS


revision: str = "0002_account_person_identity"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_legacy_identities() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS permission_decisions_no_update")
    bind.exec_driver_sql(
        """
        CREATE TEMP TABLE _account_identity_map AS
        SELECT id AS old_id, actor_id AS account_id
        FROM persons
        WHERE id <> actor_id
        """
    )

    bind.exec_driver_sql(
        """
        UPDATE person_manager_edges
        SET person_id = COALESCE(
                (SELECT account_id FROM _account_identity_map WHERE old_id = person_id),
                person_id
            ),
            manager_person_id = COALESCE(
                (SELECT account_id FROM _account_identity_map WHERE old_id = manager_person_id),
                manager_person_id
            )
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE data_delegations
        SET from_person_id = COALESCE(
                (SELECT account_id FROM _account_identity_map WHERE old_id = from_person_id),
                from_person_id
            ),
            to_person_id = COALESCE(
                (SELECT account_id FROM _account_identity_map WHERE old_id = to_person_id),
                to_person_id
            )
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE institution_policies
        SET subject_id = COALESCE(
            (SELECT account_id FROM _account_identity_map WHERE old_id = subject_id),
            subject_id
        )
        WHERE subject_type IN ('actor', 'person', 'user')
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE data_registry
        SET initial_person_ids_json = COALESCE(
            (
                SELECT json_group_array(
                    COALESCE(identity_map.account_id, CAST(items.value AS TEXT))
                )
                FROM json_each(data_registry.initial_person_ids_json) AS items
                LEFT JOIN _account_identity_map AS identity_map
                    ON identity_map.old_id = CAST(items.value AS TEXT)
            ),
            '[]'
        )
        WHERE json_valid(initial_person_ids_json)
        """
    )

    bind.exec_driver_sql(
        "UPDATE person_position_assignments SET person_id = actor_id WHERE person_id <> actor_id"
    )
    bind.exec_driver_sql(
        "UPDATE data_registry SET owner_person_id = owner_actor_id WHERE owner_person_id <> owner_actor_id"
    )
    bind.exec_driver_sql(
        "UPDATE resources SET owner_person_id = owner_actor_id WHERE owner_person_id <> owner_actor_id"
    )
    bind.exec_driver_sql(
        "UPDATE permission_decisions SET person_id = actor_id WHERE person_id IS NOT NULL AND person_id <> actor_id"
    )
    bind.exec_driver_sql("UPDATE persons SET id = actor_id WHERE id <> actor_id")
    bind.exec_driver_sql("DROP TABLE _account_identity_map")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _normalize_legacy_identities()
        for statement in SQLITE_TRIGGERS:
            bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    for trigger in (
        "resource_owner_identity_update",
        "resource_owner_identity_insert",
        "data_owner_identity_update",
        "data_owner_identity_insert",
        "assignments_identity_update",
        "assignments_identity_insert",
        "persons_identity_update",
        "persons_identity_insert",
    ):
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger}")
