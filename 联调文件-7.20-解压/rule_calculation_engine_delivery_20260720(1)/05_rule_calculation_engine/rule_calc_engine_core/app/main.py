from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from .contracts import (
    CandidateSkillTrialRequest,
    ExecutionRequest,
    ExecutionResult,
    HumanHandlingRequest,
    HumanHandlingResult,
    RuleVersionDraftRequest,
    RuleVersionResult,
    RuleVersionTransitionRequest,
)
from .database import initialize_database
from .engine import RuleEngineService
from .platform_instruction import PlatformInstructionService
from .platform_instruction import PUBLIC_PLATFORM_ACTIONS, SERVICE_CODE


def database_path() -> Path:
    configured_path = os.getenv("RULE_ENGINE_DB_PATH")
    return Path(configured_path) if configured_path else Path(__file__).resolve().parents[1] / "data" / "rule_engine.db"


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database(database_path())
    yield


app = FastAPI(title="Rule Calculation Engine", version="0.1.0", lifespan=lifespan)


TEST_CONSOLE_PATH = Path(__file__).resolve().parent / "static" / "test_console.html"


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/test-console")


@app.get("/test-console", include_in_schema=False)
def test_console() -> FileResponse:
    return FileResponse(TEST_CONSOLE_PATH)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "rule-calculation"}


@app.get("/api/v1/capabilities")
def capabilities() -> dict[str, object]:
    return {
        "items": [
            {
                "service_code": SERVICE_CODE,
                "layer": "L2",
                "actions": {action: "execute" for action in sorted(PUBLIC_PLATFORM_ACTIONS)},
                "async_supported": True,
            }
        ]
    }


@app.post("/v1/executions", response_model=ExecutionResult)
def create_execution(request: ExecutionRequest) -> ExecutionResult:
    return RuleEngineService(database_path()).execute(request)


@app.post("/api/v1/instructions")
def receive_platform_instruction(instruction: dict[str, object]) -> dict[str, object]:
    return PlatformInstructionService(database_path()).handle(instruction)


@app.get("/v1/executions/{trace_id}")
def get_execution(trace_id: str) -> dict[str, object]:
    record = RuleEngineService(database_path()).get_record(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Execution record not found.")
    return record


@app.post("/v1/executions/{execution_record_id}/human-handling", response_model=HumanHandlingResult)
def handle_execution(execution_record_id: str, request: HumanHandlingRequest) -> HumanHandlingResult:
    try:
        return RuleEngineService(database_path()).handle_waiting_result(execution_record_id, request)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/v1/executions/{execution_record_id}/candidate-skill-trial", response_model=ExecutionResult)
def resume_candidate_skill_trial(
    execution_record_id: str, request: CandidateSkillTrialRequest
) -> ExecutionResult:
    try:
        return RuleEngineService(database_path()).resume_candidate_skill_trial(
            execution_record_id, request
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/v1/rule-versions/drafts", response_model=RuleVersionResult)
def create_rule_version_draft(request: RuleVersionDraftRequest) -> RuleVersionResult:
    try:
        return RuleEngineService(database_path()).create_rule_version_draft(request)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.post("/v1/rule-versions/{rule_version_id}/transitions", response_model=RuleVersionResult)
def transition_rule_version(rule_version_id: int, request: RuleVersionTransitionRequest) -> RuleVersionResult:
    try:
        return RuleEngineService(database_path()).transition_rule_version(rule_version_id, request)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
