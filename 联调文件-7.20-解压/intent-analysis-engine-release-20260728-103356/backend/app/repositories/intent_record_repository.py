from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IntentRecord


class IntentRecordRepository:
    """Persistence operations for intent analysis records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_record(self, record: IntentRecord) -> IntentRecord:
        self.db.add(record)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(record)
        return record

    def get_by_id(self, record_id: str) -> IntentRecord | None:
        statement = select(IntentRecord).where(IntentRecord.id == record_id)
        return self.db.scalar(statement)

    def list_records(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IntentRecord]:
        statement = (
            select(IntentRecord)
            .order_by(IntentRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(statement).all())

    def query_by_user(
        self,
        user_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IntentRecord]:
        statement = (
            select(IntentRecord)
            .where(IntentRecord.user_id == user_id)
            .order_by(IntentRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(statement).all())

    def query_by_level(
        self,
        analysis_level: int | str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IntentRecord]:
        statement = (
            select(IntentRecord)
            .where(IntentRecord.analysis_level == str(analysis_level))
            .order_by(IntentRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(statement).all())
