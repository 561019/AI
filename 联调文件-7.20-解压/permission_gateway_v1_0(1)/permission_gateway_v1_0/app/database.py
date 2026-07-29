from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import Base, DataAction, ServiceCallRule


DEFAULT_ACTIONS = {
    "create": ("创建", "normal"),
    "read": ("读取", "normal"),
    "fetch": ("取用", "normal"),
    "use": ("使用", "normal"),
    "store": ("存入", "normal"),
    "update": ("修改", "normal"),
    "delete": ("删除", "high"),
    "approve": ("批准", "high"),
    "delegate": ("转授", "high"),
    "export": ("导出", "high"),
    "disable": ("禁用", "high"),
    "freeze": ("冻结", "high"),
    "unfreeze": ("解冻", "high"),
    "content.generate": ("内容生成", "normal"),
}


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._ensure_sqlite_parent(settings.database_url)
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        if settings.database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    @staticmethod
    def _ensure_sqlite_parent(database_url: str) -> None:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            return
        raw = database_url[len(prefix) :]
        if raw == ":memory:" or raw.startswith("file:"):
            return
        Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def initialize_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            if connection.dialect.name == "sqlite":
                for statement in SQLITE_TRIGGERS:
                    connection.exec_driver_sql(statement)
        self._seed_reference_data()

    def _seed_reference_data(self) -> None:
        now = datetime.now(timezone.utc)
        with self.session() as session:
            for action, (description, risk) in DEFAULT_ACTIONS.items():
                if session.get(DataAction, action) is None:
                    session.add(
                        DataAction(
                            action=action,
                            description=description,
                            risk_level=risk,
                            enabled=True,
                            created_by="system",
                            created_at=now,
                        )
                    )
            defaults = [
                ("intent_engine", "content_engine", "*"),
                ("account_gateway", "legacy_runtime", "*"),
            ]
            for source, target, action in defaults:
                exists = session.scalar(
                    select(ServiceCallRule.id).where(
                        ServiceCallRule.source_service == source,
                        ServiceCallRule.target_service == target,
                        ServiceCallRule.action == action,
                    )
                )
                if exists is None:
                    session.add(
                        ServiceCallRule(
                            source_service=source,
                            target_service=target,
                            action=action,
                            enabled=True,
                            created_by="system",
                            created_at=now,
                        )
                    )
            session.commit()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def check(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    def dispose(self) -> None:
        self.engine.dispose()


SQLITE_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS permission_decisions_no_update
    BEFORE UPDATE ON permission_decisions
    BEGIN SELECT RAISE(ABORT, 'permission_decisions is append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS permission_decisions_no_delete
    BEFORE DELETE ON permission_decisions
    BEGIN SELECT RAISE(ABORT, 'permission_decisions is append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS persons_identity_insert
    BEFORE INSERT ON persons WHEN NEW.id <> NEW.actor_id
    BEGIN SELECT RAISE(ABORT, 'person id must equal account actor id'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS persons_identity_update
    BEFORE UPDATE ON persons WHEN NEW.id <> NEW.actor_id
    BEGIN SELECT RAISE(ABORT, 'person id must equal account actor id'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS assignments_identity_insert
    BEFORE INSERT ON person_position_assignments WHEN NEW.person_id <> NEW.actor_id
    BEGIN SELECT RAISE(ABORT, 'assignment person id must equal account actor id'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS assignments_identity_update
    BEFORE UPDATE ON person_position_assignments WHEN NEW.person_id <> NEW.actor_id
    BEGIN SELECT RAISE(ABORT, 'assignment person id must equal account actor id'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS data_owner_identity_insert
    BEFORE INSERT ON data_registry WHEN NEW.owner_person_id <> NEW.owner_actor_id
    BEGIN SELECT RAISE(ABORT, 'data owner person id must equal account actor id'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS data_owner_identity_update
    BEFORE UPDATE ON data_registry WHEN NEW.owner_person_id <> NEW.owner_actor_id
    BEGIN SELECT RAISE(ABORT, 'data owner person id must equal account actor id'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_owner_identity_insert
    BEFORE INSERT ON resources WHEN NEW.owner_person_id <> NEW.owner_actor_id
    BEGIN SELECT RAISE(ABORT, 'resource owner person id must equal account actor id'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS resource_owner_identity_update
    BEFORE UPDATE ON resources WHEN NEW.owner_person_id <> NEW.owner_actor_id
    BEGIN SELECT RAISE(ABORT, 'resource owner person id must equal account actor id'); END
    """,
)
