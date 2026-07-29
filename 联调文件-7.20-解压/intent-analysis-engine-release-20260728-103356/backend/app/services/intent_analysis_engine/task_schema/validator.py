from __future__ import annotations

from dataclasses import dataclass

from app.services.intent_analysis_engine.task_schema.required_inputs import (
    input_is_provided,
    provided_input_keys,
)
from app.services.intent_analysis_engine.task_schema.task_type_schema import (
    DEFAULT_TASK_TYPE_SCHEMAS,
    TaskTypeSchema,
)


@dataclass(frozen=True)
class TaskSchemaValidation:
    task_type: str
    required_inputs: tuple[str, ...]
    provided_inputs: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    required_inputs_source: str
    allow_clarification: bool


class TaskTypeSchemaCatalog:
    def __init__(self, schemas: list[TaskTypeSchema] | None = None) -> None:
        self.schemas = schemas or list(DEFAULT_TASK_TYPE_SCHEMAS)
        self._by_task_type = {schema.task_type: schema for schema in self.schemas}

    def get(self, task_type: str) -> TaskTypeSchema | None:
        return self._by_task_type.get(task_type)

    def required_inputs_for(self, task_type: str) -> list[str]:
        schema = self.get(task_type)
        return list(schema.required_inputs) if schema is not None else []

    def optional_inputs_for(self, task_type: str) -> list[str]:
        schema = self.get(task_type)
        return list(schema.optional_inputs) if schema is not None else []

    def allow_clarification_for(self, task_type: str) -> bool:
        schema = self.get(task_type)
        return bool(schema.allow_clarification) if schema is not None else False

    def required_inputs_source_for(self, task_type: str) -> str:
        return "task_type_schema" if self.get(task_type) is not None else "unknown_task_type"

    def validate(self, task_type: str, provided_values: list[str]) -> TaskSchemaValidation:
        schema = self.get(task_type)
        required_inputs = tuple(schema.required_inputs) if schema is not None else ()
        provided_keys = provided_input_keys(provided_values)
        missing_inputs = tuple(
            input_name
            for input_name in required_inputs
            if not input_is_provided(input_name, provided_keys)
        )
        return TaskSchemaValidation(
            task_type=task_type,
            required_inputs=required_inputs,
            provided_inputs=tuple(sorted(provided_keys)),
            missing_inputs=missing_inputs,
            required_inputs_source=self.required_inputs_source_for(task_type),
            allow_clarification=self.allow_clarification_for(task_type),
        )

    def schema_list(self) -> list[TaskTypeSchema]:
        return list(self.schemas)
