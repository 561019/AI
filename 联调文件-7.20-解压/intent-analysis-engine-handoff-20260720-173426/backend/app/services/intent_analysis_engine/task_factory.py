from app.schemas.intent_analysis import TaskItem
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog


class TaskFactory:
    def __init__(self, registry: FunctionRegistryCatalog) -> None:
        self.registry = registry

    def create_task(
        self,
        *,
        task_name: str,
        task_type: str,
        required_inputs: list[str] | None = None,
        missing_inputs: list[str] | None = None,
        dependencies: list[str] | None = None,
        execution_order: int,
        confidence: float,
    ) -> TaskItem:
        self.registry.get_by_task_type(task_type)
        return TaskItem(
            task_type=task_type,
            task_description=task_name,
            required_inputs=required_inputs or [],
            missing_inputs=missing_inputs or [],
            dependencies=dependencies or [],
            confidence=confidence,
        )
