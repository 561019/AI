from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FunctionRegistry


class FunctionRegistryRepository:
    """Persistence operations for the function registry."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, function: FunctionRegistry) -> FunctionRegistry:
        self.db.add(function)
        self.db.commit()
        self.db.refresh(function)
        return function

    def get_by_code(self, function_code: str) -> FunctionRegistry | None:
        statement = select(FunctionRegistry).where(
            FunctionRegistry.function_code == function_code,
        )
        return self.db.scalar(statement)

    def list_functions(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FunctionRegistry]:
        statement = select(FunctionRegistry).order_by(FunctionRegistry.created_at.desc())

        if status is not None:
            statement = statement.where(FunctionRegistry.status == status)

        statement = statement.offset(offset).limit(limit)
        return list(self.db.scalars(statement).all())

    def search_by_category(
        self,
        intent_category: str,
        *,
        status: str | None = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> list[FunctionRegistry]:
        statement = select(FunctionRegistry).where(
            FunctionRegistry.intent_category == intent_category,
        )

        if status is not None:
            statement = statement.where(FunctionRegistry.status == status)

        statement = statement.order_by(FunctionRegistry.created_at.desc()).offset(offset).limit(limit)
        return list(self.db.scalars(statement).all())
