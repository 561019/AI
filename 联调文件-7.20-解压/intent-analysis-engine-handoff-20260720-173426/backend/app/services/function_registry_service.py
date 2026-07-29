from sqlalchemy.orm import Session

from app.models import FunctionRegistry
from app.repositories.function_registry_repository import FunctionRegistryRepository


class FunctionRegistryError(Exception):
    """Base error for function registry service failures."""


class FunctionRegistryAlreadyExistsError(FunctionRegistryError):
    """Raised when a function code already exists."""


class FunctionRegistryNotFoundError(FunctionRegistryError):
    """Raised when a function code cannot be found."""


class FunctionRegistryInactiveError(FunctionRegistryError):
    """Raised when a function exists but is not available."""


class FunctionRegistryService:
    """Business access layer for the function registry."""

    def __init__(self, db: Session) -> None:
        self.repository = FunctionRegistryRepository(db)

    def register_function(
        self,
        *,
        function_code: str,
        function_name: str,
        intent_category: str,
        target_engine: str,
        description: str,
        required_parameters: dict | None = None,
        example_sentences: list | None = None,
        status: str = "active",
    ) -> FunctionRegistry:
        existing = self.repository.get_by_code(function_code)
        if existing is not None:
            raise FunctionRegistryAlreadyExistsError(f"Function already exists: {function_code}")

        function = FunctionRegistry(
            function_code=function_code,
            function_name=function_name,
            intent_category=intent_category,
            target_engine=target_engine,
            description=description,
            required_parameters=required_parameters or {},
            example_sentences=example_sentences or [],
            status=status,
        )
        return self.repository.create(function)

    def get_function(self, function_code: str) -> FunctionRegistry | None:
        return self.repository.get_by_code(function_code)

    def list_functions(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FunctionRegistry]:
        return self.repository.list_functions(status=status, limit=limit, offset=offset)

    def search_by_category(
        self,
        intent_category: str,
        *,
        status: str | None = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> list[FunctionRegistry]:
        return self.repository.search_by_category(
            intent_category,
            status=status,
            limit=limit,
            offset=offset,
        )

    def validate_function_status(
        self,
        function_code: str,
        *,
        required_status: str = "active",
    ) -> FunctionRegistry:
        function = self.repository.get_by_code(function_code)
        if function is None:
            raise FunctionRegistryNotFoundError(f"Function not found: {function_code}")

        if function.status != required_status:
            raise FunctionRegistryInactiveError(
                f"Function {function_code} status is {function.status}, expected {required_status}",
            )

        return function
