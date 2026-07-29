from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.database import Database
from app.models import (
    DataAction,
    DataDelegation,
    DataRegistry,
    InstitutionPolicy,
    Person,
    PersonManagerEdge,
    PersonPositionAssignment,
    Position,
    PositionStandardPermission,
)


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def rows(connection: sqlite3.Connection, table: str):
    if not table_exists(connection, table):
        return []
    connection.row_factory = sqlite3.Row
    return connection.execute(f'SELECT * FROM "{table}"').fetchall()


def parse_time(value, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_json_list(value) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Import account-gateway permission data")
    parser.add_argument("source", type=Path, help="Existing account-gateway SQLite database")
    parser.add_argument("--target-url", default=Settings.from_env().database_url)
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"source database does not exist: {args.source}")

    source = sqlite3.connect(args.source)
    now = datetime.now(timezone.utc)
    settings = Settings(database_url=args.target_url)
    target = Database(settings)
    target.initialize_schema()
    assignment_rows = rows(source, "person_position_assignments")
    identity_map = {
        str(row["person_id"]): str(row["user_id"])
        for row in assignment_rows
    }

    def account_id(legacy_person_id: str) -> str:
        return identity_map.get(str(legacy_person_id), str(legacy_person_id))

    with target.session() as session:
        for row in rows(source, "positions"):
            if session.get(Position, row["id"]) is None:
                session.add(
                    Position(
                        id=row["id"],
                        title=row["title"],
                        department_id=row["department_id"],
                        tenant_id=row["tenant_id"],
                        tags_json=row["tags"] or "[]",
                        status="active",
                        created_by=row["created_by"],
                        created_at=parse_time(row["created_at"], now),
                    )
                )
        session.flush()
        for row in assignment_rows:
            identity_id = str(row["user_id"])
            person = session.get(Person, identity_id)
            if person is None:
                person = Person(
                    id=identity_id,
                    actor_id=identity_id,
                    tenant_id=row["tenant_id"],
                    display_name="",
                    status="active" if row["status"] == "active" else "inactive",
                    created_at=parse_time(row["assigned_at"], now),
                )
                session.add(person)
                session.flush()
            session.add(
                PersonPositionAssignment(
                    id=row["id"],
                    person_id=identity_id,
                    actor_id=identity_id,
                    position_id=row["position_id"],
                    tenant_id=row["tenant_id"],
                    status=row["status"],
                    effective_from=parse_time(row["assigned_at"], now),
                    effective_to=parse_time(row["ended_at"], now) if row["ended_at"] else None,
                    assigned_by=row["assigned_by"],
                    ended_by=row["ended_by"],
                )
            )
        for row in rows(source, "person_manager_edges"):
            child_account_id = account_id(row["person_id"])
            manager_account_id = account_id(row["manager_person_id"])
            assignment = session.scalar(
                select(PersonPositionAssignment).where(
                    PersonPositionAssignment.person_id == child_account_id
                )
            )
            for identity_id in (child_account_id, manager_account_id):
                if session.get(Person, identity_id) is None:
                    session.add(
                        Person(
                            id=identity_id,
                            actor_id=identity_id,
                            tenant_id=assignment.tenant_id if assignment else "legacy",
                            display_name="",
                            status="active",
                            created_at=now,
                        )
                    )
            session.flush()
            session.add(
                PersonManagerEdge(
                    id=row["id"],
                    person_id=child_account_id,
                    manager_person_id=manager_account_id,
                    domain_id=row["domain_id"],
                    tenant_id=assignment.tenant_id if assignment else "legacy",
                    status=row["status"],
                    effective_from=parse_time(row["created_at"], now),
                    effective_to=None,
                    created_by=row["created_by"],
                )
            )
        for row in rows(source, "position_standard_resources"):
            position = session.get(Position, row["position_id"])
            session.add(
                PositionStandardPermission(
                    id=row["id"],
                    tenant_id=position.tenant_id if position else "legacy",
                    position_id=row["position_id"],
                    action=row["action"],
                    data_label="*",
                    data_states_json='["active"]',
                    source_service="*",
                    target_service="*",
                    resource_type=row["resource_type"],
                    resource_id=row["resource_id"],
                    effect="allow",
                    valid_from=parse_time(row["created_at"], now),
                    valid_to=None,
                    basis="migrated position standard resource",
                    created_by=row["created_by"],
                )
            )
        for row in rows(source, "delegations"):
            from_account_id = account_id(row["from_person_id"])
            to_account_id = account_id(row["to_person_id"])
            assignment = session.scalar(
                select(PersonPositionAssignment).where(
                    PersonPositionAssignment.person_id == to_account_id
                )
            )
            session.add(
                DataDelegation(
                    id=row["id"],
                    tenant_id=assignment.tenant_id if assignment else "legacy",
                    from_person_id=from_account_id,
                    to_person_id=to_account_id,
                    resource_type=row["resource_type"],
                    resource_id=row["resource_id"],
                    action=row["action"],
                    data_label="*",
                    data_states_json='["active"]',
                    can_redelegate=bool(row["can_redelegate"]),
                    valid_from=parse_time(row["created_at"], now),
                    valid_to=None,
                    basis=row["basis"],
                    created_by=row["created_by"],
                )
            )
        for row in rows(source, "data_actions"):
            item = session.get(DataAction, row["action"])
            if item:
                item.description = row["description"]
                item.risk_level = row["risk_level"]
                item.enabled = bool(row["enabled"])
        for row in rows(source, "data_records"):
            if session.get(DataRegistry, row["id"]) is None:
                keys = set(row.keys())
                owner_account_id = str(row["owner_user_id"])
                initial_accounts = {
                    account_id(item)
                    for item in parse_json_list(
                        row["initial_person_ids"] if "initial_person_ids" in keys else "[]"
                    )
                }
                if "initial_user_ids" in keys:
                    initial_accounts.update(parse_json_list(row["initial_user_ids"]))
                session.add(
                    DataRegistry(
                        id=row["id"],
                        tenant_id=row["tenant_id"],
                        title=row["title"],
                        source_type=row["source_type"],
                        owner_person_id=owner_account_id,
                        owner_actor_id=owner_account_id,
                        data_label="normal",
                        state=row["status"],
                        allowed_actions_json=row["allowed_actions"],
                        initial_person_ids_json=json.dumps(
                            sorted(initial_accounts), ensure_ascii=False
                        ),
                        business_tags_json=row["business_tags"],
                        storage_refs_json=row["storage_refs"],
                        basis=row["basis"],
                        created_by=row["created_by"],
                        created_at=parse_time(row["created_at"], now),
                        updated_at=parse_time(row["updated_at"], now),
                    )
                )
        for row in rows(source, "runtime_policies"):
            session.add(
                InstitutionPolicy(
                    tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "legacy",
                    name=f"migrated:{row['policy_id']}",
                    subject_type="actor",
                    subject_id=row["subject"],
                    action=row["action"],
                    data_label="*",
                    data_states_json='["*"]',
                    source_service="*",
                    target_service="*",
                    resource_type=row["resource_type"],
                    resource_id=row["resource_id"],
                    effect=row["effect"],
                    priority=100,
                    valid_from=now,
                    valid_to=None,
                    basis="migrated runtime policy",
                    created_by="migration",
                )
            )
        session.commit()
    source.close()
    print("account-gateway permission data imported successfully")


if __name__ == "__main__":
    main()
