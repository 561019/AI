from fastapi.testclient import TestClient

from app.api.routes.intent import (
    get_conversation_state_store,
    get_intent_analyzer,
    get_tasklist_confirmation_manager,
)
from app.main import app
from app.schemas.intent_analysis import IntentAnalysisResult, TaskItem
from app.schemas.tasklist_confirmation import (
    TaskListConfirmationConfirmRequest,
    TaskListConfirmationModifyRequest,
)
from app.services.conversation_understanding import InMemoryConversationStateStore
from app.services.tasklist_confirmation import (
    TaskListConfirmationManager,
    TaskListConfirmationVersionConflict,
)


client = TestClient(app)


class FakeIntentAnalyzer:
    def __init__(self, result: IntentAnalysisResult) -> None:
        self.result = result

    def analyze_with_debug(self, **_: object) -> object:
        return type(
            "Analysis",
            (),
            {
                "result": self.result,
                "debug": {
                    "level1_result": None,
                    "level2_result": None,
                    "level3_result": self.result.model_dump(mode="json"),
                    "final_tasklist": self.result.model_dump(mode="json"),
                },
            },
        )()


def make_result(*, needs_clarification: bool = False) -> IntentAnalysisResult:
    task = TaskItem(
        task_id="task-001",
        task_type="DOCUMENT_GENERATE",
        task_description="Generate a sales report",
        clarification_required=needs_clarification,
        missing_inputs=["document_type"] if needs_clarification else [],
        clarification_questions=["Which document type is needed?"] if needs_clarification else [],
        status="needs_clarification" if needs_clarification else "ready",
        confidence=0.96,
    )
    return IntentAnalysisResult(
        tasks=[task],
        clarification_required=needs_clarification,
        clarification_questions=list(task.clarification_questions),
        overall_confidence=0.96,
    )


def test_confirmation_session_stays_outside_intent_result_schema() -> None:
    result = make_result()
    manager = TaskListConfirmationManager()

    confirmation = manager.create_for_result(result)

    assert confirmation is not None
    assert confirmation.confirmation_status == "pending"
    assert "confirmation_status" not in result.model_dump(mode="json")
    assert "confirmation_status" not in result.tasks[0].model_dump(mode="json")


def test_confirmation_requires_current_tasklist_version() -> None:
    manager = TaskListConfirmationManager()
    confirmation = manager.create_for_result(make_result())

    assert confirmation is not None
    view = manager.modify(
        confirmation_id=confirmation.confirmation_id,
        request=TaskListConfirmationModifyRequest(
            tasklist_version=confirmation.tasklist_version,
            modified_by="user-001",
            tasks=[
                make_result().tasks[0].model_copy(
                    update={"task_description": "Generate an updated sales report"}
                )
            ],
        ),
    )

    assert view.confirmation.confirmation_status == "pending"
    assert view.confirmation.modification_count == 1
    assert view.confirmation.tasklist_version != confirmation.tasklist_version

    try:
        manager.confirm(
            confirmation_id=confirmation.confirmation_id,
            request=TaskListConfirmationConfirmRequest(
                tasklist_version=confirmation.tasklist_version,
                confirmed_by="user-001",
            ),
        )
    except TaskListConfirmationVersionConflict:
        pass
    else:
        raise AssertionError("An outdated task-list version must not be confirmed.")


def test_clarification_completion_makes_tasklist_confirmable() -> None:
    manager = TaskListConfirmationManager()
    result = make_result(needs_clarification=True)
    confirmation = manager.create_for_result(result)

    assert confirmation is not None
    assert confirmation.confirmation_status == "waiting_clarification"

    ready_task = result.tasks[0].model_copy(
        update={
            "clarification_required": False,
            "missing_inputs": [],
            "clarification_questions": [],
            "status": "ready",
        }
    )
    manager.update_task(ready_task)
    view = manager.get(confirmation.confirmation_id)

    assert view.confirmation.confirmation_status == "pending"
    assert view.data.clarification_required is False
    assert view.data.tasks[0].status == "ready"


def test_analyze_and_confirm_tasklist_over_http() -> None:
    manager = TaskListConfirmationManager()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_intent_analyzer] = lambda: FakeIntentAnalyzer(make_result())
    app.dependency_overrides[get_conversation_state_store] = lambda: InMemoryConversationStateStore()
    app.dependency_overrides[get_tasklist_confirmation_manager] = lambda: manager
    try:
        analysis_response = client.post(
            "/api/v1/intent/analyze",
            json={"text": "Generate a sales report", "conversation_id": "confirmation-001"},
        )
        analysis_body = analysis_response.json()

        assert analysis_response.status_code == 200
        assert analysis_body["data"]["tasks"][0]["task_type"] == "DOCUMENT_GENERATE"
        assert analysis_body["confirmation"]["confirmation_status"] == "pending"

        confirmation = analysis_body["confirmation"]
        confirmation_response = client.post(
            f"/api/v1/intent/tasklist-confirmations/{confirmation['confirmation_id']}/confirm",
            json={
                "tasklist_version": confirmation["tasklist_version"],
                "confirmed_by": "user-001",
            },
        )
        confirmation_body = confirmation_response.json()

        assert confirmation_response.status_code == 200
        assert confirmation_body["confirmation"]["confirmation_status"] == "confirmed"
        assert confirmation_body["confirmation"]["confirmed_by"] == "user-001"
    finally:
        app.dependency_overrides.clear()
