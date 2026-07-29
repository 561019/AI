from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RuleMapping


class RuleEngineRepository:
    """Read access for first-level rule mappings."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_active_rules(self) -> list[RuleMapping]:
        statement = (
            select(RuleMapping)
            .where(RuleMapping.status == "active")
            .order_by(RuleMapping.priority.asc(), RuleMapping.created_at.asc())
        )
        return list(self.db.scalars(statement).all())
