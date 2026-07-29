from unittest.mock import MagicMock

from app.models import FunctionRegistry
from app.repositories.function_registry_repository import FunctionRegistryRepository


def make_function(function_code: str = "FUNC_TEST") -> FunctionRegistry:
    return FunctionRegistry(
        function_code=function_code,
        function_name="Test Function",
        intent_category="报告生成型",
        target_engine="内容产出引擎",
        description="Test function definition.",
        required_parameters={"period": True},
        example_sentences=["生成报告"],
        status="active",
    )


def test_create_persists_function_registry_model() -> None:
    session = MagicMock()
    function = make_function()
    repository = FunctionRegistryRepository(session)

    result = repository.create(function)

    assert result is function
    session.add.assert_called_once_with(function)
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(function)


def test_get_by_code_returns_single_function() -> None:
    session = MagicMock()
    function = make_function()
    session.scalar.return_value = function
    repository = FunctionRegistryRepository(session)

    result = repository.get_by_code("FUNC_TEST")

    assert result is function
    session.scalar.assert_called_once()


def test_list_functions_returns_all_rows_from_scalar_result() -> None:
    session = MagicMock()
    function = make_function()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [function]
    session.scalars.return_value = scalar_result
    repository = FunctionRegistryRepository(session)

    result = repository.list_functions(status="active")

    assert result == [function]
    session.scalars.assert_called_once()


def test_search_by_category_returns_candidate_functions() -> None:
    session = MagicMock()
    function = make_function()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [function]
    session.scalars.return_value = scalar_result
    repository = FunctionRegistryRepository(session)

    result = repository.search_by_category("报告生成型")

    assert result == [function]
    session.scalars.assert_called_once()
