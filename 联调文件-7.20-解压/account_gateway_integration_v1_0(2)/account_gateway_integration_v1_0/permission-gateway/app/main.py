from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError

from . import __version__
from .audit import add_decision_audit, four_factors, write_fallback
from .config import Settings
from .database import Database
from .engine import EngineDecision, PermissionEngine
from .ids import new_decision_id
from .integrations import platform_capabilities
from .management import create_management_router
from .models import DataAction, PermissionDecision
from .schemas import (
    AuditItem,
    AuditListResponse,
    FourFactors,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionError,
    IntegrationEventRequest,
)


logger = logging.getLogger("permission_gateway")


def _mechanism_request_is_trusted(request: Request, payload: PermissionCheckRequest, settings: Settings) -> bool:
    """Authenticate the sole non-recursive path from the L1 internal channel.

    The shared secret is a local-development substitute for the production mTLS
    client identity.  The payload's caller fields are never an authority.
    """
    return bool(
        settings.mechanism_secret
        and payload.ingress_mode == "mechanism_direct"
        and request.headers.get("X-L1-Caller-Service") == "l1_internal_channel"
        and secrets.compare_digest(
            request.headers.get("X-L1-Mechanism-Secret", ""),
            settings.mechanism_secret,
        )
    )


def _response_time(settings: Settings, value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.astimezone(ZoneInfo(settings.timezone))


def _error_response(
    settings: Settings,
    status: int,
    *,
    trace_id: str = "",
    request_id: str = "",
    code: str,
    reason: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = PermissionCheckResponse(
        trace_id=trace_id,
        request_id=request_id,
        decision_id=None,
        allowed=False,
        result="error",
        reason_code=code,
        reason=reason,
        four_factors=None,
        error=PermissionError(code=code, message=message, details=details or {}),
        decided_at=_response_time(settings),
    )
    return JSONResponse(status_code=status, content=json.loads(payload.model_dump_json()))


def _audit_error_payload(
    database: Database,
    settings: Settings,
    payload: dict[str, Any],
    *,
    code: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    record = PermissionDecision(
        decision_id=None,
        trace_id=str(payload.get("trace_id", "")),
        request_id=str(payload.get("request_id", "")),
        actor_id=str(payload.get("actor_id", "")),
        person_id=payload.get("person_id"),
        position_id=payload.get("position_id"),
        tenant_id=payload.get("tenant_id"),
        action=str(payload.get("action", "")),
        source_service=str(payload.get("source_service", "")),
        target_service=str(payload.get("target_service", "")),
        resource_type=payload.get("resource_type"),
        resource_id=payload.get("resource_id"),
        data_label=str(payload.get("data_label", "")),
        data_state=str(payload.get("data_state", "")),
        allowed=False,
        result="error",
        reason_code=code,
        reason=reason,
        policy_id=None,
        four_factors_json=None,
        error_json=json.dumps(
            {"code": code, "message": reason, "details": details or {}},
            ensure_ascii=False,
        ),
        requested_at=now,
        decided_at=now,
    )
    try:
        with database.session() as session:
            session.add(record)
            session.commit()
    except SQLAlchemyError:
        write_fallback(
            settings.logs_dir,
            {
                **payload,
                "allowed": False,
                "result": "error",
                "reason_code": code,
                "reason": reason,
                "details": details or {},
            },
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings)
    engine = PermissionEngine()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            database.initialize_schema()
        except SQLAlchemyError as error:
            logger.error("permission database initialization failed: %s", error)
        yield
        database.dispose()

    app = FastAPI(
        title="Hanhe Permission Gateway",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.permission_engine = engine
    app.include_router(create_management_router(database))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError):
        body = error.body if isinstance(error.body, dict) else {}
        fields = json.loads(json.dumps(error.errors(), default=str))
        details = {"fields": fields}
        _audit_error_payload(
            database,
            settings,
            body,
            code="INVALID_REQUEST",
            reason="请求缺少字段或字段类型错误",
            details=details,
        )
        return _error_response(
            settings,
            422,
            trace_id=str(body.get("trace_id", "")),
            request_id=str(body.get("request_id", "")),
            code="INVALID_REQUEST",
            reason="请求缺少字段或字段类型错误",
            message="请求字段校验失败",
            details=details,
        )

    @app.get("/health")
    def health():
        try:
            database.check()
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "service": "permission_gateway",
                    "version": __version__,
                    "database": "unavailable",
                    "timestamp": _response_time(settings).isoformat(),
                },
            )
        return {
            "status": "ok",
            "service": "permission_gateway",
            "version": __version__,
            "database": "ok",
            "timestamp": _response_time(settings).isoformat(),
        }

    @app.get("/api/integrations/capabilities")
    def integration_capabilities():
        """Discover the stable platform-wide permission integration contract."""

        return platform_capabilities()

    @app.post("/api/integrations/events")
    def integration_events_reserved(event: IntegrationEventRequest):
        """Keep the future event address stable while rejecting unsafe writes in v1."""

        return JSONResponse(
            status_code=501,
            content={
                "error": "INTEGRATION_EVENT_NOT_ENABLED",
                "message": "异步权限事件入口已预留，v1 尚未启用写入。",
                "event_id": event.event_id,
                "event_type": event.event_type,
                "activation_prerequisites": [
                    "service authentication or mTLS",
                    "idempotency store",
                    "event persistence and replay governance",
                ],
            },
        )

    @app.post("/api/permission/check", response_model=PermissionCheckResponse)
    def check_permission(request: PermissionCheckRequest, response: Response, raw_request: Request):
        requested_at = datetime.now(timezone.utc)
        if not _mechanism_request_is_trusted(raw_request, request, settings):
            response.status_code = 403
            return PermissionCheckResponse(
                trace_id=request.trace_id,
                request_id=request.request_id,
                decision_id=None,
                allowed=False,
                result="error",
                reason_code="UNTRUSTED_INGRESS",
                reason="权限判定只接受基础模块层对内通道的机制性直达请求",
                four_factors=None,
                error=PermissionError(
                    code="UNTRUSTED_INGRESS",
                    message="调用方身份或入口模式不可信",
                    details={},
                ),
                decided_at=_response_time(settings),
            )
        # A human account is the permission subject.  Agents and systems are
        # execution context only and cannot substitute the responsible human.
        if request.responsible_actor_id and request.responsible_actor_id != request.actor_id:
            response.status_code = 400
            return PermissionCheckResponse(
                trace_id=request.trace_id,
                request_id=request.request_id,
                decision_id=None,
                allowed=False,
                result="error",
                reason_code="INVALID_REQUEST",
                reason="责任真人必须与权限主体账号一致",
                four_factors=None,
                error=PermissionError(code="INVALID_REQUEST", message="责任真人不一致", details={}),
                decided_at=_response_time(settings),
            )
        try:
            with database.session() as session:
                valid_states = {"active", "disabled", "frozen", "archived", "offboarding"}
                registered_action = session.get(DataAction, request.action)
                identity_mismatch = bool(
                    request.person_id and request.person_id != request.actor_id
                )
                if (
                    request.data_state not in valid_states
                    or registered_action is None
                    or not registered_action.enabled
                    or identity_mismatch
                ):
                    decided_at = datetime.now(timezone.utc)
                    invalid = EngineDecision(
                        allowed=False,
                        reason_code="INVALID_REQUEST",
                        reason="请求包含非法字段，账号与真人编号必须相同",
                    )
                    add_decision_audit(
                        session,
                        request,
                        invalid,
                        decision_id=None,
                        result="error",
                        requested_at=(request.requested_at or requested_at),
                        decided_at=decided_at,
                        error={
                            "code": "INVALID_REQUEST",
                            "message": "业务字段非法或账号真人不一致",
                            "details": {},
                        },
                    )
                    session.commit()
                    response.status_code = 400
                    return PermissionCheckResponse(
                        trace_id=request.trace_id,
                        request_id=request.request_id,
                        decision_id=None,
                        allowed=False,
                        result="error",
                        reason_code="INVALID_REQUEST",
                        reason=invalid.reason,
                        four_factors=None,
                        error=PermissionError(
                            code="INVALID_REQUEST",
                            message="业务字段非法或账号真人不一致",
                            details={},
                        ),
                        decided_at=_response_time(settings, decided_at),
                    )
                decision = engine.evaluate(session, request, now=requested_at)
                decision_id = new_decision_id()
                decided_at = datetime.now(timezone.utc)
                result = "allow" if decision.allowed else "deny"
                add_decision_audit(
                    session,
                    request,
                    decision,
                    decision_id=decision_id,
                    result=result,
                    requested_at=(request.requested_at or requested_at),
                    decided_at=decided_at,
                )
                session.commit()
                return PermissionCheckResponse(
                    trace_id=request.trace_id,
                    request_id=request.request_id,
                    decision_id=decision_id,
                    allowed=decision.allowed,
                    result=result,
                    reason_code=decision.reason_code,
                    reason=decision.reason,
                    four_factors=FourFactors(**four_factors(request)),
                    decided_at=_response_time(settings, decided_at),
                )
        except OperationalError as error:
            write_fallback(
                settings.logs_dir,
                {
                    **request.model_dump(mode="json"),
                    "allowed": False,
                    "result": "error",
                    "reason_code": "PERMISSION_DB_ERROR",
                    "reason": "权限数据库异常",
                    "error": str(error.__class__.__name__),
                },
            )
            response.status_code = 503
            return PermissionCheckResponse(
                trace_id=request.trace_id,
                request_id=request.request_id,
                decision_id=None,
                allowed=False,
                result="error",
                reason_code="PERMISSION_DB_ERROR",
                reason="权限数据库异常",
                four_factors=None,
                error=PermissionError(
                    code="PERMISSION_DB_ERROR",
                    message="权限数据库暂时不可用",
                    details={},
                ),
                decided_at=_response_time(settings),
            )
        except Exception as error:
            logger.exception("permission check failed")
            _audit_error_payload(
                database,
                settings,
                request.model_dump(mode="json"),
                code="PERMISSION_SERVICE_ERROR",
                reason="权限模块暂时不可用",
                details={"error_type": error.__class__.__name__},
            )
            response.status_code = 500
            return PermissionCheckResponse(
                trace_id=request.trace_id,
                request_id=request.request_id,
                decision_id=None,
                allowed=False,
                result="error",
                reason_code="PERMISSION_SERVICE_ERROR",
                reason="权限模块暂时不可用",
                four_factors=None,
                error=PermissionError(
                    code="PERMISSION_SERVICE_ERROR",
                    message="权限模块内部处理失败",
                    details={},
                ),
                decided_at=_response_time(settings),
            )

    @app.get("/api/permission/audits", response_model=AuditListResponse)
    def list_audits(
        trace_id: str | None = Query(default=None),
        request_id: str | None = Query(default=None),
        actor_id: str | None = Query(default=None),
        result: str | None = Query(default=None, pattern="^(allow|deny|error)$"),
        from_ts: datetime | None = Query(default=None),
        to_ts: datetime | None = Query(default=None),
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        try:
            query = select(PermissionDecision).where(PermissionDecision.id > after_id)
            if trace_id:
                query = query.where(PermissionDecision.trace_id == trace_id)
            if request_id:
                query = query.where(PermissionDecision.request_id == request_id)
            if actor_id:
                query = query.where(PermissionDecision.actor_id == actor_id)
            if result:
                query = query.where(PermissionDecision.result == result)
            if from_ts:
                query = query.where(PermissionDecision.decided_at >= from_ts)
            if to_ts:
                query = query.where(PermissionDecision.decided_at <= to_ts)
            query = query.order_by(PermissionDecision.id).limit(limit)
            with database.session() as session:
                rows = session.scalars(query).all()
                items = [_audit_item(row) for row in rows]
                return AuditListResponse(
                    audits=items,
                    next_after_id=(items[-1].id if items else None),
                )
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "PERMISSION_DB_ERROR",
                    "message": "权限数据库暂时不可用",
                },
            )

    return app


def _audit_item(row: PermissionDecision) -> AuditItem:
    def decode(raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    return AuditItem(
        id=row.id,
        decision_id=row.decision_id,
        trace_id=row.trace_id,
        request_id=row.request_id,
        actor_id=row.actor_id,
        person_id=row.person_id,
        position_id=row.position_id,
        tenant_id=row.tenant_id,
        action=row.action,
        source_service=row.source_service,
        target_service=row.target_service,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        data_label=row.data_label,
        data_state=row.data_state,
        allowed=row.allowed,
        result=row.result,
        reason_code=row.reason_code,
        reason=row.reason,
        policy_id=row.policy_id,
        four_factors=decode(row.four_factors_json),
        error=decode(row.error_json),
        requested_at=row.requested_at,
        decided_at=row.decided_at,
        responsible_actor_id=row.responsible_actor_id,
        executor_type=row.executor_type,
        executor_id=row.executor_id,
        original_caller_service_id=row.original_caller_service_id,
        ingress_mode=row.ingress_mode,
        transfer_id=row.transfer_id,
        identity_context_hash=row.identity_context_hash,
    )


app = create_app()
