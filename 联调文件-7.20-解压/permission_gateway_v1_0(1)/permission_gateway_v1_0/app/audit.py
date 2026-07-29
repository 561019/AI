from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .engine import EngineDecision
from .models import PermissionDecision
from .schemas import PermissionCheckRequest


_fallback_lock = threading.Lock()


def four_factors(request: PermissionCheckRequest) -> dict[str, str]:
    return {
        "data_label": request.data_label,
        "action": request.action,
        "actor_id": request.actor_id,
        "data_state": request.data_state,
    }


def add_decision_audit(
    session: Session,
    request: PermissionCheckRequest,
    decision: EngineDecision,
    *,
    decision_id: str | None,
    result: str,
    requested_at: datetime,
    decided_at: datetime,
    error: dict[str, Any] | None = None,
) -> PermissionDecision:
    item = PermissionDecision(
        decision_id=decision_id,
        trace_id=request.trace_id,
        request_id=request.request_id,
        actor_id=request.actor_id,
        person_id=decision.person_id,
        position_id=decision.position_id,
        tenant_id=request.tenant_id,
        action=request.action,
        source_service=request.source_service,
        target_service=request.target_service,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        data_label=request.data_label,
        data_state=request.data_state,
        allowed=decision.allowed,
        result=result,
        reason_code=decision.reason_code,
        reason=decision.reason,
        policy_id=decision.policy_id,
        four_factors_json=(json.dumps(four_factors(request), ensure_ascii=False) if result != "error" else None),
        error_json=(json.dumps(error, ensure_ascii=False) if error else None),
        requested_at=requested_at,
        decided_at=decided_at,
        responsible_actor_id=request.responsible_actor_id or request.actor_id,
        executor_type=request.executor_type,
        executor_id=request.executor_id,
        original_caller_service_id=request.original_caller_service_id,
        ingress_mode=request.ingress_mode,
        transfer_id=request.transfer_id,
        identity_context_hash=request.identity_context_hash,
    )
    session.add(item)
    session.flush()
    return item


def write_fallback(logs_dir: Path, payload: dict[str, Any]) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "fallback_recorded_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    path = logs_dir / "permission-fallback.ndjson"
    encoded = json.dumps(event, ensure_ascii=False, default=str)
    with _fallback_lock:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")
