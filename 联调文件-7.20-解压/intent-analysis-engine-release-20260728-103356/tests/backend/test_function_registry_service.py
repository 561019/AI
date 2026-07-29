from unittest.mock import MagicMock

import pytest

from app.models import FunctionRegistry
from app.services.function_registry_service import (
    FunctionRegistryAlreadyExistsError,
    FunctionRegistryInactiveError,
    FunctionRegistryNotFoundError,
    FunctionRegistryService,
)


def make_function(function_code: str = "FUNC_TEST", status: str = "active") -> FunctionRegistry:
    return FunctionRegistry(
        function_code=function_code,
        function_name="Test Function",
        intent_category="智能问答型",
        target_engine="知识库问答引擎",
        description="Test function definition.",
        required_parameters={"question": True},
        example_sentences=["查询数据"],
        status=status,
    )


def make_service() -> FunctionRegistryService:
    service = FunctionRegistryService(MagicMock())
    service.repository = MagicMock()
    return service


def test_register_function_creates_new_function() -> None:
    service = make_service()
    service.repository.get_by_code.return_value = None
    service.repository.create.side_effect = lambda function: function

    result = service.register_function(
        function_code="FUNC_REPORT",
        function_name="报告生成",
        intent_category="报告生成型",
        target_engine="内容产出引擎",
        description="生成报告。",
        required_parameters={"period": True},
        example_sentences=["生成报告"],
    )

    assert result.function_code == "FUNC_REPORT"
    assert result.status == "active"
    service.repository.create.assert_called_once()


def test_register_function_rejects_duplicate_code() -> None:
    service = make_service()
    service.repository.get_by_code.return_value = make_function()

    with pytest.raises(FunctionRegistryAlreadyExistsError):
        service.register_function(
            function_code="FUNC_TEST",
            function_name="Test Function",
            intent_category="报告生成型",
            target_engine="内容产出引擎",
            description="Duplicate.",
        )


def test_get_function_delegates_to_repository() -> None:
    service = make_service()
    function = make_function()
    service.repository.get_by_code.return_value = function

    result = service.get_function("FUNC_TEST")

    assert result is function
    service.repository.get_by_code.assert_called_once_with("FUNC_TEST")


def test_search_by_category_delegates_candidate_lookup() -> None:
    service = make_service()
    service.repository.search_by_category.return_value = [make_function()]

    result = service.search_by_category("智能问答型")

    assert len(result) == 1
    service.repository.search_by_category.assert_called_once_with(
        "智能问答型",
        status="active",
        limit=100,
        offset=0,
    )


def test_validate_function_status_returns_active_function() -> None:
    service = make_service()
    function = make_function(status="active")
    service.repository.get_by_code.return_value = function

    result = service.validate_function_status("FUNC_TEST")

    assert result is function


def test_validate_function_status_raises_when_missing() -> None:
    service = make_service()
    service.repository.get_by_code.return_value = None

    with pytest.raises(FunctionRegistryNotFoundError):
        service.validate_function_status("FUNC_MISSING")


def test_validate_function_status_raises_when_inactive() -> None:
    service = make_service()
    service.repository.get_by_code.return_value = make_function(status="disabled")

    with pytest.raises(FunctionRegistryInactiveError):
        service.validate_function_status("FUNC_TEST")
