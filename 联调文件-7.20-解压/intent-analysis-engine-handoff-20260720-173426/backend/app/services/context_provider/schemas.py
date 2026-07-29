from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class ContextProviderResponse(BaseModel):
    """Context payload supplied by an external context system."""

    conversation_context: list[dict[str, Any]] = Field(default_factory=list)
    project_context: list[dict[str, Any]] = Field(default_factory=list)
    user_project_context: list[dict[str, Any]] = Field(default_factory=list)


class ContextInput(BaseModel):
    """Normalized context consumed by the intent analysis engine."""

    current_conversation: dict[str, Any] = Field(default_factory=dict)
    current_project: dict[str, Any] = Field(default_factory=dict)
    historical_projects: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_provider_response(cls, value: Any) -> Any:
        if isinstance(value, ContextProviderResponse):
            return cls.from_provider_response(value).model_dump(mode="python")
        if isinstance(value, dict) and (
            "conversation_context" in value
            or "project_context" in value
            or "user_project_context" in value
        ):
            response = ContextProviderResponse.model_validate(value)
            return cls.from_provider_response(response).model_dump(mode="python")
        return value

    @classmethod
    def from_provider_response(cls, response: ContextProviderResponse) -> "ContextInput":
        return cls(
            current_conversation={"items": response.conversation_context},
            current_project={"items": response.project_context},
            historical_projects={"items": response.user_project_context},
        )

    def has_context(self) -> bool:
        return any(
            self._items(scope)
            for scope in (
                self.current_conversation,
                self.current_project,
                self.historical_projects,
            )
        )

    def _items(self, scope: dict[str, Any]) -> list[Any]:
        items = scope.get("items")
        return items if isinstance(items, list) else []


class ContextualIntentInput(BaseModel):
    """Unified input shape for rule, semantic, and LLM analysis."""

    user_input: str
    context: ContextInput = Field(default_factory=ContextInput)

    def has_context(self) -> bool:
        return self.context.has_context()
