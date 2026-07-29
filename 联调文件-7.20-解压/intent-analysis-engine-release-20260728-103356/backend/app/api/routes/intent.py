from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.model_gateway import ModelGateway
from app.services.context_provider import BaseContextProvider, ContextProviderClient
from app.repositories.intent_record_repository import IntentRecordRepository
from app.repositories.conversation_state_repository import ConversationStateRepository
from app.schemas.intent_analysis import IntentAnalysisResult
from app.schemas.intent_http import (
    ApiError,
    ClarificationAnswerRequest,
    ClarificationAnswerResponse,
    IntentAnalyzeRequest,
    IntentAnalyzeResponse,
    IntentHistoryData,
    IntentHistoryResponse,
    IntentRecordItem,
)
from app.schemas.llm import NeedConfirmationResult
from app.schemas.task import TaskList
from app.schemas.tasklist_confirmation import (
    TaskListConfirmationCancelRequest,
    TaskListConfirmationConfirmRequest,
    TaskListConfirmationModifyRequest,
    TaskListConfirmationView,
)
from app.services.function_registry_service import FunctionRegistryService
from app.services.intent_record_service import IntentRecordService
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.clarification import (
    ClarificationSessionManager,
    ClarificationSessionNotFound,
    get_default_clarification_session_manager,
)
from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer
from app.services.tasklist_confirmation import (
    TaskListConfirmationManager,
    TaskListConfirmationSessionNotFound,
    TaskListConfirmationTransitionError,
    TaskListConfirmationVersionConflict,
    get_default_tasklist_confirmation_manager,
)
from app.services.conversation_understanding import (
    ConversationStateStore,
    ConversationUnderstandingLayer,
    PostgresConversationStateStore,
)
from app.services.semantic import SemanticMatcher
from app.services.semantic.runtime import (
    configure_runtime_vector_repository,
    get_runtime_embedding_service,
)
from app.services.task_extraction import LongContextTaskExtractionLayer, LongTextParser


router = APIRouter()


def get_intent_record_service(db: Session = Depends(get_db)) -> IntentRecordService:
    return IntentRecordService(IntentRecordRepository(db))


def get_conversation_state_store(db: Session = Depends(get_db)) -> ConversationStateStore:
    return PostgresConversationStateStore(ConversationStateRepository(db))


def get_context_provider() -> BaseContextProvider:
    return ContextProviderClient()


def get_clarification_session_manager() -> ClarificationSessionManager:
    return get_default_clarification_session_manager()


def get_tasklist_confirmation_manager() -> TaskListConfirmationManager:
    return get_default_tasklist_confirmation_manager()


def get_intent_analyzer(db: Session = Depends(get_db)) -> StandardIntentAnalyzer:
    intent_record_repository = IntentRecordRepository(db)
    intent_record_service = IntentRecordService(intent_record_repository)
    model_gateway = ModelGateway()

    registry = FunctionRegistryCatalog.from_database_functions(
        FunctionRegistryService(db).list_functions(status="active", limit=500),
    )
    semantic_matcher = None
    if settings.enable_semantic_matching:
        embedding_service = get_runtime_embedding_service()
        semantic_matcher = SemanticMatcher(
            embedding_service=embedding_service,
            vector_repository=configure_runtime_vector_repository(
                registry=registry,
                embedding_service=embedding_service,
            ),
            registry=registry,
            match_threshold=settings.semantic_threshold,
        )
    llm_analyzer = LLMTaskAnalyzer(
        model_gateway=model_gateway,
        registry=registry,
        confidence_threshold=settings.llm_confidence_threshold,
        implicit_confidence_threshold=settings.implicit_task_confidence_threshold,
    )

    return StandardIntentAnalyzer(
        registry=registry,
        semantic_matcher=semantic_matcher,
        llm_analyzer=llm_analyzer,
        intent_record_service=intent_record_service,
        semantic_threshold=settings.semantic_threshold,
        llm_confidence_threshold=settings.llm_confidence_threshold,
    )


def get_full_intent_analyzer(db: Session = Depends(get_db)) -> StandardIntentAnalyzer:
    return get_intent_analyzer(db)


@router.post("/analyze", response_model=IntentAnalyzeResponse)
async def analyze_intent(
    request: IntentAnalyzeRequest,
    debug: bool = Query(default=False),
    analyzer: StandardIntentAnalyzer = Depends(get_intent_analyzer),
    state_store: ConversationStateStore = Depends(get_conversation_state_store),
    context_provider: BaseContextProvider = Depends(get_context_provider),
    clarification_session_manager: ClarificationSessionManager = Depends(get_clarification_session_manager),
    tasklist_confirmation_manager: TaskListConfirmationManager = Depends(get_tasklist_confirmation_manager),
) -> IntentAnalyzeResponse | JSONResponse:
    include_debug = debug or request.debug
    try:
        result, debug_payload = _analyze_with_debug(
            analyzer=analyzer,
            text=request.text,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            project_id=request.project_id,
            history=request.history,
            state_store=state_store,
            context_provider=context_provider,
        )
    except Exception as error:
        response = IntentAnalyzeResponse(
            success=False,
            data=None,
            error=ApiError(
                code="intent_analysis_failed",
                message=str(error),
            ),
            debug=None,
        )
        return JSONResponse(
            status_code=500,
            content=response.model_dump(mode="json"),
        )

    if isinstance(result, NeedConfirmationResult):
        return IntentAnalyzeResponse(
            success=False,
            data=None,
            error=ApiError(
                code="need_confirmation",
                message=result.reason,
                details=result.model_dump(mode="json"),
            ),
            debug=debug_payload if include_debug else None,
        )

    if isinstance(result, IntentAnalysisResult):
        result = clarification_session_manager.create_sessions_for_result(result)
        confirmation = tasklist_confirmation_manager.create_for_result(result)
        debug_payload["final_tasklist"] = result.model_dump(mode="json")
        debug_payload["tasklist_confirmation"] = (
            confirmation.model_dump(mode="json") if confirmation else None
        )
        debug_payload["clarification_sessions"] = [
            {
                "task_id": task.task_id,
                "clarification_session_id": task.clarification_session_id,
                "missing_inputs": task.missing_inputs,
                "clarification_questions": task.clarification_questions,
            }
            for task in result.tasks
            if task.clarification_session_id
        ]
    else:
        confirmation = None

    return IntentAnalyzeResponse(
        success=True,
        data=result,
        confirmation=confirmation,
        error=None,
        debug=debug_payload if include_debug else None,
    )


@router.post("/clarification/answer", response_model=ClarificationAnswerResponse)
async def answer_clarification(
    request: ClarificationAnswerRequest,
    analyzer: StandardIntentAnalyzer = Depends(get_intent_analyzer),
    clarification_session_manager: ClarificationSessionManager = Depends(get_clarification_session_manager),
    tasklist_confirmation_manager: TaskListConfirmationManager = Depends(get_tasklist_confirmation_manager),
) -> ClarificationAnswerResponse | JSONResponse:
    try:
        result = clarification_session_manager.answer(
            clarification_session_id=request.clarification_session_id,
            answer=request.answer,
            validator=analyzer.input_validator,
        )
        tasklist_confirmation_manager.update_task(result.task)
    except ClarificationSessionNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "code": "clarification_session_not_found",
                "message": "Clarification session not found.",
            },
        )
    except Exception as error:
        return JSONResponse(
            status_code=500,
            content={
                "code": "clarification_answer_failed",
                "message": str(error),
            },
        )

    return ClarificationAnswerResponse(
        task_id=result.task_id,
        status=result.status,
        missing_inputs=result.missing_inputs,
        final_inputs=result.final_inputs,
        clarification_questions=result.clarification_questions,
        clarification_session_id=result.clarification_session_id,
        session_status=result.session_status.value,
    )


@router.get("/tasklist-confirmations/{confirmation_id}", response_model=TaskListConfirmationView)
async def get_tasklist_confirmation(
    confirmation_id: str,
    tasklist_confirmation_manager: TaskListConfirmationManager = Depends(get_tasklist_confirmation_manager),
) -> TaskListConfirmationView | JSONResponse:
    try:
        return tasklist_confirmation_manager.get(confirmation_id)
    except TaskListConfirmationSessionNotFound:
        return _tasklist_confirmation_error(
            status_code=404,
            code="tasklist_confirmation_not_found",
            message="Task list confirmation session was not found.",
        )


@router.post(
    "/tasklist-confirmations/{confirmation_id}/confirm",
    response_model=TaskListConfirmationView,
)
async def confirm_tasklist(
    confirmation_id: str,
    request: TaskListConfirmationConfirmRequest,
    tasklist_confirmation_manager: TaskListConfirmationManager = Depends(get_tasklist_confirmation_manager),
) -> TaskListConfirmationView | JSONResponse:
    try:
        return tasklist_confirmation_manager.confirm(
            confirmation_id=confirmation_id,
            request=request,
        )
    except TaskListConfirmationSessionNotFound:
        return _tasklist_confirmation_error(
            status_code=404,
            code="tasklist_confirmation_not_found",
            message="Task list confirmation session was not found.",
        )
    except TaskListConfirmationVersionConflict as error:
        return _tasklist_confirmation_error(
            status_code=409,
            code="tasklist_confirmation_version_conflict",
            message=str(error),
        )
    except TaskListConfirmationTransitionError as error:
        return _tasklist_confirmation_error(
            status_code=409,
            code="tasklist_confirmation_invalid_transition",
            message=str(error),
        )


@router.post(
    "/tasklist-confirmations/{confirmation_id}/modify",
    response_model=TaskListConfirmationView,
)
async def modify_tasklist_confirmation(
    confirmation_id: str,
    request: TaskListConfirmationModifyRequest,
    tasklist_confirmation_manager: TaskListConfirmationManager = Depends(get_tasklist_confirmation_manager),
) -> TaskListConfirmationView | JSONResponse:
    try:
        return tasklist_confirmation_manager.modify(
            confirmation_id=confirmation_id,
            request=request,
        )
    except TaskListConfirmationSessionNotFound:
        return _tasklist_confirmation_error(
            status_code=404,
            code="tasklist_confirmation_not_found",
            message="Task list confirmation session was not found.",
        )
    except TaskListConfirmationVersionConflict as error:
        return _tasklist_confirmation_error(
            status_code=409,
            code="tasklist_confirmation_version_conflict",
            message=str(error),
        )
    except TaskListConfirmationTransitionError as error:
        return _tasklist_confirmation_error(
            status_code=409,
            code="tasklist_confirmation_invalid_transition",
            message=str(error),
        )


@router.post(
    "/tasklist-confirmations/{confirmation_id}/cancel",
    response_model=TaskListConfirmationView,
)
async def cancel_tasklist_confirmation(
    confirmation_id: str,
    request: TaskListConfirmationCancelRequest,
    tasklist_confirmation_manager: TaskListConfirmationManager = Depends(get_tasklist_confirmation_manager),
) -> TaskListConfirmationView | JSONResponse:
    try:
        return tasklist_confirmation_manager.cancel(
            confirmation_id=confirmation_id,
            request=request,
        )
    except TaskListConfirmationSessionNotFound:
        return _tasklist_confirmation_error(
            status_code=404,
            code="tasklist_confirmation_not_found",
            message="Task list confirmation session was not found.",
        )
    except TaskListConfirmationVersionConflict as error:
        return _tasklist_confirmation_error(
            status_code=409,
            code="tasklist_confirmation_version_conflict",
            message=str(error),
        )
    except TaskListConfirmationTransitionError as error:
        return _tasklist_confirmation_error(
            status_code=409,
            code="tasklist_confirmation_invalid_transition",
            message=str(error),
        )


def _tasklist_confirmation_error(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message},
    )


def _analyze_with_debug(
    *,
    analyzer: Any,
    text: str,
    user_id: str,
    conversation_id: str,
    project_id: str | None = None,
    history: list[Any] | None = None,
    state_store: ConversationStateStore | None = None,
    context_provider: BaseContextProvider | None = None,
) -> tuple[IntentAnalysisResult | TaskList | NeedConfirmationResult, dict[str, Any]]:
    conversation_layer = ConversationUnderstandingLayer(
        analyzer,
        state_store=state_store,
        context_provider=context_provider,
        history_limit=settings.conversation_history_limit,
        task_extraction_layer=LongContextTaskExtractionLayer(
            parser=LongTextParser(
                chunk_size=settings.long_text_chunk_size,
                chunk_overlap=settings.long_text_chunk_overlap,
            ),
            activation_length=settings.long_text_activation_length,
            activation_sentences=settings.long_text_activation_sentences,
        ),
        implicit_fallback_batch_characters=settings.implicit_fallback_batch_characters,
    )
    analysis = conversation_layer.analyze_with_debug(
        text=text,
        user_id=user_id,
        conversation_id=conversation_id,
        project_id=project_id,
        history=history,
    )
    return analysis.result, analysis.debug


@router.get("/history", response_model=IntentHistoryResponse)
async def get_intent_history(
    user_id: str | None = Query(default=None),
    analysis_level: int | str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    intent_record_service: IntentRecordService = Depends(get_intent_record_service),
) -> IntentHistoryResponse | JSONResponse:
    try:
        records = intent_record_service.get_analysis_history(
            user_id=user_id,
            analysis_level=analysis_level,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        response = IntentHistoryResponse(
            success=False,
            data=None,
            error=ApiError(
                code="intent_history_query_failed",
                message=str(error),
            ),
        )
        return JSONResponse(
            status_code=500,
            content=response.model_dump(mode="json"),
        )

    return IntentHistoryResponse(
        success=True,
        data=IntentHistoryData(
            records=[IntentRecordItem.model_validate(record) for record in records],
            count=len(records),
            limit=limit,
            offset=offset,
        ),
        error=None,
    )
