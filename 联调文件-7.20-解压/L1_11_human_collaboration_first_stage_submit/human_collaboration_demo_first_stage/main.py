from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
import json
import os
import sqlite3
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field


DB_PATH = os.getenv("HUMAN_COLLAB_DB", "human_collaboration_v1.db")
SERVICE_CODE = "l1.human_collaboration"
PROTOCOL_VERSION = "1.0"

app = FastAPI(
    title="L1.11 人机协同服务",
    description=(
        "按统一层接口规范实现：只管理人工待办、催办与人工处理结果；"
        "完整流程状态和流程恢复由 L2 流程执行引擎负责。"
    ),
    version="1.0.0",
)


# ============================================================
# 统一通信对象
# ============================================================

class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ServiceEndpoint(StrictModel):
    layer: Literal["L1", "L2", "L4"]
    service_code: str


class ActorContext(StrictModel):
    person_id: str
    tenant_id: str
    position_id: Optional[str] = None


class RefObject(StrictModel):
    ref_id: str
    resource_type: str
    version: Optional[str] = None
    data_labels: List[str] = Field(default_factory=list)
    allowed_actions: List[str] = Field(default_factory=list)


class WorkflowContext(StrictModel):
    workflow_instance_id: str
    node_id: str
    task_id: str
    data_refs: List[RefObject] = Field(default_factory=list)
    artifact_refs: List[RefObject] = Field(default_factory=list)


class HumanTaskPayload(StrictModel):
    collaboration_type: Literal[
        "data_confirmation",
        "approval_review",
        "risk_intervention",
        "todo_reminder",
        "content_review",
    ]
    work_mode: Literal["in_loop", "on_loop"] = "in_loop"
    trigger_source_module: str = Field(
        ...,
        description="最初识别出需要人工处理的业务引擎，仅用于说明来源，不用于直连",
    )
    title: str
    content: str
    ai_result: str = ""
    evidence_summary: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"
    target_person_id: str
    deadline_at: Optional[str] = None
    decision_options: List[Literal["approve", "modify_approve", "reject"]] = Field(
        default_factory=lambda: ["approve", "modify_approve", "reject"]
    )


class HumanTaskCreateEnvelope(StrictModel):
    protocol_version: str = PROTOCOL_VERSION
    message_id: str
    trace_id: str
    request_id: str
    parent_message_id: Optional[str] = None
    source: ServiceEndpoint
    target: ServiceEndpoint
    channel: Literal["l2_to_l1"] = "l2_to_l1"
    route_type: Literal["task.dispatch"] = "task.dispatch"
    action: Literal["human.task.create"] = "human.task.create"
    capability_id: str
    capability_dictionary_version: str
    registry_version: str
    actor: ActorContext
    context: WorkflowContext
    idempotency_key: str
    deadline_at: Optional[str] = None
    payload: HumanTaskPayload


class DecisionPayload(StrictModel):
    decision: Literal["approve", "modify_approve", "reject"]
    modified_result: str = ""
    comment: str = ""


class HumanDecisionEnvelope(StrictModel):
    protocol_version: str = PROTOCOL_VERSION
    message_id: str
    trace_id: str
    request_id: str
    parent_message_id: Optional[str] = None
    source: ServiceEndpoint
    target: ServiceEndpoint
    channel: Literal["l2_to_l1"] = "l2_to_l1"
    route_type: Literal["command.handoff"] = "command.handoff"
    action: Literal["human.task.respond"] = "human.task.respond"
    actor: ActorContext
    context: WorkflowContext
    idempotency_key: str
    payload: DecisionPayload


class ReminderPayload(StrictModel):
    operator_id: str
    comment: str = "待办尚未处理，执行一次催办。"


class EscalationPayload(StrictModel):
    operator_id: str
    escalate_to_person_id: str
    comment: str = "待办超时，按规则升级处理。"


# ============================================================
# 工具与数据库
# ============================================================

def now_dt() -> datetime:
    return datetime.now()


def now_text() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")


def iso_deadline(hours: int = 2) -> str:
    return (now_dt() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads(text: Optional[str], default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[attr-defined]
    return model.dict()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS human_task (
            human_task_id TEXT PRIMARY KEY,
            protocol_version TEXT NOT NULL,
            message_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            parent_message_id TEXT,
            source_layer TEXT NOT NULL,
            source_service_code TEXT NOT NULL,
            target_layer TEXT NOT NULL,
            target_service_code TEXT NOT NULL,
            route_type TEXT NOT NULL,
            action TEXT NOT NULL,
            capability_id TEXT,
            capability_dictionary_version TEXT,
            registry_version TEXT,
            actor_person_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            workflow_instance_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            upstream_task_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            collaboration_type TEXT NOT NULL,
            work_mode TEXT NOT NULL,
            trigger_source_module TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            ai_result TEXT,
            evidence_summary TEXT,
            data_refs TEXT,
            artifact_refs TEXT,
            risk_level TEXT,
            target_person_id TEXT NOT NULL,
            status TEXT NOT NULL,
            deadline_at TEXT,
            remind_count INTEGER NOT NULL DEFAULT 0,
            escalated_to TEXT,
            decision TEXT,
            final_result TEXT,
            decision_comment TEXT,
            decision_operator_id TEXT,
            decided_at TEXT,
            result_payload TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS human_task_log (
            log_id TEXT PRIMARY KEY,
            human_task_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            operator_id TEXT,
            action_type TEXT NOT NULL,
            before_status TEXT,
            after_status TEXT,
            detail TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


@app.on_event("startup")
def startup() -> None:
    init_db()


def write_log(
    human_task_id: str,
    trace_id: str,
    operator_id: Optional[str],
    action_type: str,
    before_status: Optional[str],
    after_status: Optional[str],
    detail: str,
) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO human_task_log (
            log_id, human_task_id, trace_id, operator_id,
            action_type, before_status, after_status, detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "LOG-" + uuid4().hex[:10].upper(),
            human_task_id,
            trace_id,
            operator_id,
            action_type,
            before_status,
            after_status,
            detail,
            now_text(),
        ),
    )
    conn.commit()
    conn.close()


def task_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    data["data_refs"] = loads(data.get("data_refs"), [])
    data["artifact_refs"] = loads(data.get("artifact_refs"), [])
    data["result_payload"] = loads(data.get("result_payload"), {})
    return data


def new_reply_message_id() -> str:
    return "msg_reply_" + uuid4().hex[:12]


def reply_payload(
    *,
    reply_type: Literal["success", "accepted", "failed"],
    trace_id: str,
    request_id: str,
    parent_message_id: Optional[str],
    data: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "reply_type": reply_type,
        "message_id": new_reply_message_id(),
        "trace_id": trace_id,
        "request_id": request_id,
        "parent_message_id": parent_message_id,
        "source": {"layer": "L1", "service_code": SERVICE_CODE},
        "data": data or {},
    }
    if error:
        body["error"] = error
    return body


def failed_response(
    *,
    status_code: int,
    trace_id: str,
    request_id: str,
    parent_message_id: Optional[str],
    code: str,
    message: str,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=reply_payload(
            reply_type="failed",
            trace_id=trace_id,
            request_id=request_id,
            parent_message_id=parent_message_id,
            error={"code": code, "message": message, "retryable": retryable},
        ),
    )


def validate_create_envelope(payload: HumanTaskCreateEnvelope) -> Optional[JSONResponse]:
    if payload.source.layer != "L2":
        return failed_response(
            status_code=403,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="SOURCE_LAYER_NOT_ALLOWED",
            message="L1.11 只接受来自 L2 层接口的请求。",
        )
    if payload.target.layer != "L1" or payload.target.service_code != SERVICE_CODE:
        return failed_response(
            status_code=400,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="TARGET_SERVICE_MISMATCH",
            message=f"目标服务必须为 L1/{SERVICE_CODE}。",
        )
    if set(payload.payload.decision_options) != {"approve", "modify_approve", "reject"}:
        return failed_response(
            status_code=400,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="DECISION_OPTIONS_INVALID",
            message="正式人工处理结果仅支持 approve、modify_approve、reject 三种。",
        )
    return None


def validate_decision_envelope(
    task: Dict[str, Any], payload: HumanDecisionEnvelope
) -> Optional[JSONResponse]:
    if payload.source.layer != "L2":
        return failed_response(
            status_code=403,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="SOURCE_LAYER_NOT_ALLOWED",
            message="人工决定必须由 L4 经 L2 层接口转交给 L1.11。",
        )
    if payload.target.layer != "L1" or payload.target.service_code != SERVICE_CODE:
        return failed_response(
            status_code=400,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="TARGET_SERVICE_MISMATCH",
            message=f"目标服务必须为 L1/{SERVICE_CODE}。",
        )
    if payload.trace_id != task["trace_id"]:
        return failed_response(
            status_code=409,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="TRACE_ID_MISMATCH",
            message="trace_id 与原人工待办不一致，不能认领该任务。",
        )
    if payload.context.workflow_instance_id != task["workflow_instance_id"]:
        return failed_response(
            status_code=409,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="WORKFLOW_INSTANCE_MISMATCH",
            message="workflow_instance_id 与原人工待办不一致。",
        )
    if payload.context.node_id != task["node_id"]:
        return failed_response(
            status_code=409,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="NODE_ID_MISMATCH",
            message="node_id 与原人工待办不一致。",
        )
    if payload.payload.decision == "modify_approve" and not payload.payload.modified_result.strip():
        return failed_response(
            status_code=400,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="MODIFIED_RESULT_REQUIRED",
            message="修改后同意时必须提供 modified_result。",
        )
    return None


def get_task(human_task_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM human_task WHERE human_task_id = ?", (human_task_id,)
    ).fetchone()
    conn.close()
    return task_row_to_dict(row) if row else None


def get_task_by_idempotency(idempotency_key: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM human_task WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    conn.close()
    return task_row_to_dict(row) if row else None


def store_human_task(payload: HumanTaskCreateEnvelope) -> Dict[str, Any]:
    human_task_id = "HT-" + uuid4().hex[:10].upper()
    created_at = now_text()
    deadline_at = payload.payload.deadline_at or payload.deadline_at or iso_deadline(2)
    context = payload.context
    data_refs = [model_to_dict(item) for item in context.data_refs]
    artifact_refs = [model_to_dict(item) for item in context.artifact_refs]

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO human_task (
            human_task_id, protocol_version, message_id, trace_id, request_id,
            parent_message_id, source_layer, source_service_code, target_layer,
            target_service_code, route_type, action, capability_id,
            capability_dictionary_version, registry_version, actor_person_id,
            tenant_id, workflow_instance_id, node_id, upstream_task_id,
            idempotency_key, collaboration_type, work_mode, trigger_source_module,
            title, content, ai_result, evidence_summary, data_refs, artifact_refs,
            risk_level, target_person_id, status, deadline_at, remind_count,
            escalated_to, decision, final_result, decision_comment,
            decision_operator_id, decided_at, result_payload, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', '', '', '', '', '', '', ?, ?
        )
        """,
        (
            human_task_id,
            payload.protocol_version,
            payload.message_id,
            payload.trace_id,
            payload.request_id,
            payload.parent_message_id,
            payload.source.layer,
            payload.source.service_code,
            payload.target.layer,
            payload.target.service_code,
            payload.route_type,
            payload.action,
            payload.capability_id,
            payload.capability_dictionary_version,
            payload.registry_version,
            payload.actor.person_id,
            payload.actor.tenant_id,
            context.workflow_instance_id,
            context.node_id,
            context.task_id,
            payload.idempotency_key,
            payload.payload.collaboration_type,
            payload.payload.work_mode,
            payload.payload.trigger_source_module,
            payload.payload.title,
            payload.payload.content,
            payload.payload.ai_result,
            payload.payload.evidence_summary,
            dumps(data_refs),
            dumps(artifact_refs),
            payload.payload.risk_level,
            payload.payload.target_person_id,
            "pending",
            deadline_at,
            created_at,
            created_at,
        ),
    )
    conn.commit()
    conn.close()

    write_log(
        human_task_id,
        payload.trace_id,
        None,
        "人工待办登记",
        None,
        "pending",
        (
            f"由 {payload.source.service_code} 经 L1 层接口登记；"
            f"原触发模块：{payload.payload.trigger_source_module}。"
        ),
    )
    task = get_task(human_task_id)
    if task is None:
        raise RuntimeError("任务写入后无法读取")
    return task


def create_result_payload(
    task: Dict[str, Any],
    *,
    decision: str,
    final_result: str,
    operator_id: str,
    comment: str,
    handled_at: str,
) -> Dict[str, Any]:
    """只返回人工协同结果；流程恢复由 L2 流程执行引擎完成。"""
    return {
        "action": "flow.callback",
        "trace_id": task["trace_id"],
        "workflow_instance_id": task["workflow_instance_id"],
        "node_id": task["node_id"],
        "task_id": task["upstream_task_id"],
        "human_task_id": task["human_task_id"],
        "human_task_status": {
            "approve": "approved",
            "modify_approve": "modified",
            "reject": "rejected",
        }[decision],
        "decision": decision,
        "final_result": final_result,
        "operator_id": operator_id,
        "comment": comment,
        "handled_at": handled_at,
    }


def apply_decision(
    task: Dict[str, Any],
    *,
    decision: str,
    operator_id: str,
    modified_result: str,
    comment: str,
) -> Dict[str, Any]:
    if task["status"] not in {"pending", "escalated"}:
        raise ValueError("任务已经结束，不能重复处理。")

    before_status = task["status"]
    after_status = {
        "approve": "approved",
        "modify_approve": "modified",
        "reject": "rejected",
    }[decision]

    if decision == "modify_approve":
        if not modified_result.strip():
            raise ValueError("修改后同意时必须填写人工修正结果。")
        final_result = modified_result.strip()
    elif decision == "approve":
        final_result = task["ai_result"] or "人工确认原结果可继续使用。"
    else:
        final_result = ""

    handled_at = now_text()
    result = create_result_payload(
        task,
        decision=decision,
        final_result=final_result,
        operator_id=operator_id,
        comment=comment,
        handled_at=handled_at,
    )

    conn = get_conn()
    conn.execute(
        """
        UPDATE human_task
        SET status = ?, decision = ?, final_result = ?, decision_comment = ?,
            decision_operator_id = ?, decided_at = ?, result_payload = ?, updated_at = ?
        WHERE human_task_id = ?
        """,
        (
            after_status,
            decision,
            final_result,
            comment,
            operator_id,
            handled_at,
            dumps(result),
            handled_at,
            task["human_task_id"],
        ),
    )
    conn.commit()
    conn.close()

    write_log(
        task["human_task_id"],
        task["trace_id"],
        operator_id,
        {"approve": "人工同意", "modify_approve": "修改后同意", "reject": "人工驳回"}[decision],
        before_status,
        after_status,
        dumps({"comment": comment, "final_result": final_result}),
    )
    return result


# ============================================================
# API
# ============================================================

@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service_code": SERVICE_CODE,
        "version": app.version,
        "database": DB_PATH,
    }


@app.get("/api/v1/capabilities")
def capabilities() -> Dict[str, Any]:
    return {
        "service_code": SERVICE_CODE,
        "capabilities": [
            {
                "action": "human.task.create",
                "method": "POST",
                "path": "/api/v1/human-tasks",
                "description": "登记一个已由流程执行引擎确定需要真人处理的待办。",
            },
            {
                "action": "human.task.respond",
                "method": "POST",
                "path": "/api/v1/human-tasks/{human_task_id}/responses",
                "description": "记录同意、修改后同意或驳回，并返回供流程执行引擎认领的结果。",
            },
            {
                "action": "human.task.remind",
                "method": "POST",
                "path": "/api/v1/human-tasks/{human_task_id}/reminders",
                "description": "登记一次催办。",
            },
            {
                "action": "human.task.escalate",
                "method": "POST",
                "path": "/api/v1/human-tasks/{human_task_id}/escalations",
                "description": "按已确定规则登记一次升级。",
            },
            {
                "action": "human.task.query",
                "method": "GET",
                "path": "/api/v1/human-tasks/{human_task_id}",
                "description": "查询人工待办状态和处理结果。",
            },
        ],
        "formal_decisions": ["approve", "modify_approve", "reject"],
        "not_responsible_for": [
            "业务异常识别",
            "低风险自动通过判断",
            "完整流程实例状态保存",
            "流程节点推进与恢复",
            "权限授予",
            "正式安全审计存储",
        ],
    }


@app.post("/api/v1/human-tasks")
def api_create_human_task(payload: HumanTaskCreateEnvelope):
    error = validate_create_envelope(payload)
    if error:
        return error

    existing = get_task_by_idempotency(payload.idempotency_key)
    if existing:
        return JSONResponse(
            status_code=200,
            content=reply_payload(
                reply_type="accepted",
                trace_id=existing["trace_id"],
                request_id=payload.request_id,
                parent_message_id=payload.message_id,
                data={
                    "human_task_id": existing["human_task_id"],
                    "status": existing["status"],
                    "duplicate": True,
                    "message": "相同 idempotency_key 已登记，未重复创建。",
                },
            ),
        )

    task = store_human_task(payload)
    return JSONResponse(
        status_code=202,
        content=reply_payload(
            reply_type="accepted",
            trace_id=task["trace_id"],
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            data={
                "human_task_id": task["human_task_id"],
                "status": task["status"],
                "target_person_id": task["target_person_id"],
                "deadline_at": task["deadline_at"],
                "query_action": f"GET /api/v1/human-tasks/{task['human_task_id']}",
            },
        ),
    )


@app.get("/api/v1/human-tasks")
def api_list_human_tasks(status: Optional[str] = None):
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM human_task WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM human_task ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return {
        "reply_type": "success",
        "data": [task_row_to_dict(row) for row in rows],
        "count": len(rows),
    }


@app.get("/api/v1/human-tasks/{human_task_id}")
def api_get_human_task(human_task_id: str):
    task = get_task(human_task_id)
    if not task:
        return failed_response(
            status_code=404,
            trace_id="unknown",
            request_id="unknown",
            parent_message_id=None,
            code="HUMAN_TASK_NOT_FOUND",
            message="人工待办不存在。",
        )
    return {
        "reply_type": "success",
        "trace_id": task["trace_id"],
        "data": task,
    }


@app.post("/api/v1/human-tasks/{human_task_id}/responses")
def api_respond_human_task(human_task_id: str, payload: HumanDecisionEnvelope):
    task = get_task(human_task_id)
    if not task:
        return failed_response(
            status_code=404,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="HUMAN_TASK_NOT_FOUND",
            message="人工待办不存在。",
        )

    error = validate_decision_envelope(task, payload)
    if error:
        return error

    if task["status"] not in {"pending", "escalated"}:
        return failed_response(
            status_code=409,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="HUMAN_TASK_ALREADY_FINISHED",
            message="该人工待办已经处理结束，不能重复回应。",
        )

    try:
        result = apply_decision(
            task,
            decision=payload.payload.decision,
            operator_id=payload.actor.person_id,
            modified_result=payload.payload.modified_result,
            comment=payload.payload.comment,
        )
    except ValueError as exc:
        return failed_response(
            status_code=400,
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            parent_message_id=payload.message_id,
            code="DECISION_INVALID",
            message=str(exc),
        )

    return reply_payload(
        reply_type="success",
        trace_id=payload.trace_id,
        request_id=payload.request_id,
        parent_message_id=payload.message_id,
        data={
            "message": "人工处理结果已登记，完整流程恢复由 L2 流程执行引擎完成。",
            "result": result,
        },
    )


@app.post("/api/v1/human-tasks/{human_task_id}/reminders")
def api_remind_human_task(human_task_id: str, payload: ReminderPayload):
    task = get_task(human_task_id)
    if not task:
        return JSONResponse(status_code=404, content={"reply_type": "failed", "message": "人工待办不存在。"})
    if task["status"] not in {"pending", "escalated"}:
        return JSONResponse(status_code=409, content={"reply_type": "failed", "message": "已结束任务不能催办。"})

    count = int(task["remind_count"] or 0) + 1
    conn = get_conn()
    conn.execute(
        "UPDATE human_task SET remind_count = ?, updated_at = ? WHERE human_task_id = ?",
        (count, now_text(), human_task_id),
    )
    conn.commit()
    conn.close()
    write_log(
        human_task_id,
        task["trace_id"],
        payload.operator_id,
        "待办催办",
        task["status"],
        task["status"],
        payload.comment,
    )
    return {"reply_type": "success", "data": {"human_task_id": human_task_id, "remind_count": count}}


@app.post("/api/v1/human-tasks/{human_task_id}/escalations")
def api_escalate_human_task(human_task_id: str, payload: EscalationPayload):
    task = get_task(human_task_id)
    if not task:
        return JSONResponse(status_code=404, content={"reply_type": "failed", "message": "人工待办不存在。"})
    if task["status"] not in {"pending", "escalated"}:
        return JSONResponse(status_code=409, content={"reply_type": "failed", "message": "已结束任务不能升级。"})

    before = task["status"]
    conn = get_conn()
    conn.execute(
        """
        UPDATE human_task
        SET status = 'escalated', escalated_to = ?, target_person_id = ?, updated_at = ?
        WHERE human_task_id = ?
        """,
        (payload.escalate_to_person_id, payload.escalate_to_person_id, now_text(), human_task_id),
    )
    conn.commit()
    conn.close()
    write_log(
        human_task_id,
        task["trace_id"],
        payload.operator_id,
        "超时升级",
        before,
        "escalated",
        payload.comment + f" 升级至：{payload.escalate_to_person_id}",
    )
    return {
        "reply_type": "success",
        "data": {
            "human_task_id": human_task_id,
            "status": "escalated",
            "target_person_id": payload.escalate_to_person_id,
        },
    }


@app.get("/api/v1/human-tasks/{human_task_id}/logs")
def api_human_task_logs(human_task_id: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM human_task_log WHERE human_task_id = ? ORDER BY created_at ASC",
        (human_task_id,),
    ).fetchall()
    conn.close()
    return {"reply_type": "success", "data": [dict(row) for row in rows]}


# ============================================================
# 本地中文演示台（只用于独立验证，不代表真实跨层直连）
# ============================================================

STATUS_TEXT = {
    "pending": "待人工处理",
    "escalated": "已升级待处理",
    "approved": "已同意",
    "modified": "修改后同意",
    "rejected": "已驳回",
}

TYPE_TEXT = {
    "data_confirmation": "关键数字确认",
    "approval_review": "审批审核",
    "risk_intervention": "风险干预",
    "todo_reminder": "待办催批",
    "content_review": "内容审核",
}

MODE_TEXT = {
    "in_loop": "人在环内：该关键动作必须经真人放行",
    "on_loop": "人在环上：上游规则筛选后，仅异常任务进入人工",
}

DECISION_TEXT = {
    "approve": "同意",
    "modify_approve": "修改后同意",
    "reject": "驳回",
}


def demo_envelope(
    *,
    title: str,
    collaboration_type: str,
    work_mode: str,
    trigger_source_module: str,
    content: str,
    ai_result: str,
    evidence_summary: str,
    risk_level: str,
    target_person_id: str,
    scene_code: str,
) -> HumanTaskCreateEnvelope:
    token = uuid4().hex[:8]
    workflow_id = f"FLOW-DEMO-{scene_code}-{token[:4].upper()}"
    node_id = f"NODE-HUMAN-{scene_code}"
    upstream_task_id = f"TASK-{scene_code}-{token.upper()}"
    return HumanTaskCreateEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=f"msg_{token}",
        trace_id=f"trace_{scene_code.lower()}_{token}",
        request_id=f"req_{token}",
        source={"layer": "L2", "service_code": "l2.workflow_execution"},
        target={"layer": "L1", "service_code": SERVICE_CODE},
        channel="l2_to_l1",
        route_type="task.dispatch",
        action="human.task.create",
        capability_id="CAP.HUMAN.TASK.CREATE",
        capability_dictionary_version="demo-2026.07",
        registry_version="demo-registry-2026.07",
        actor={"person_id": "demo_requester_001", "tenant_id": "tenant_demo"},
        context={
            "workflow_instance_id": workflow_id,
            "node_id": node_id,
            "task_id": upstream_task_id,
            "data_refs": [
                {
                    "ref_id": f"dataref_{scene_code.lower()}_{token}",
                    "resource_type": "business_record",
                    "version": "demo-v1",
                    "data_labels": ["internal"],
                    "allowed_actions": ["read"],
                }
            ],
            "artifact_refs": [],
        },
        idempotency_key=f"{workflow_id}-{node_id}-{upstream_task_id}",
        payload={
            "collaboration_type": collaboration_type,
            "work_mode": work_mode,
            "trigger_source_module": trigger_source_module,
            "title": title,
            "content": content,
            "ai_result": ai_result,
            "evidence_summary": evidence_summary,
            "risk_level": risk_level,
            "target_person_id": target_person_id,
            "deadline_at": iso_deadline(2),
            "decision_options": ["approve", "modify_approve", "reject"],
        },
    )


def create_demo_task(envelope: HumanTaskCreateEnvelope) -> str:
    task = store_human_task(envelope)
    return task["human_task_id"]


def render_refs(task: Dict[str, Any]) -> str:
    refs = task["data_refs"] + task["artifact_refs"]
    if not refs:
        return "无引用"
    return "；".join(
        f"{item.get('ref_id', '')}（{item.get('resource_type', '')}）" for item in refs
    )


def render_task_card(task: Dict[str, Any]) -> str:
    can_operate = task["status"] in {"pending", "escalated"}
    status_class = {
        "pending": "pending",
        "escalated": "escalated",
        "approved": "approved",
        "modified": "modified",
        "rejected": "rejected",
    }.get(task["status"], "pending")

    if can_operate:
        action_html = f"""
        <div class="action-panel">
          <div class="section-label">③ 真人处理</div>
          <form action="/demo/tasks/{task['human_task_id']}/decide" method="get" class="action-form">
            <input type="hidden" name="decision" value="approve">
            <input type="hidden" name="operator_id" value="{escape(task['target_person_id'])}">
            <input name="comment" value="已核对依据，同意继续。">
            <button class="btn approve">同意</button>
          </form>
          <form action="/demo/tasks/{task['human_task_id']}/decide" method="get" class="action-form stacked">
            <input type="hidden" name="decision" value="modify_approve">
            <input type="hidden" name="operator_id" value="{escape(task['target_person_id'])}">
            <input name="modified_result" value="发票号码：FP20260710001；金额：12500.00 元；税额：1600.00 元；价税合计：14100.00 元。">
            <input name="comment" value="已人工复核并修正，使用修正结果继续。">
            <button class="btn modify">修改后同意</button>
          </form>
          <div class="inline-actions">
            <a class="btn reject" href="/demo/tasks/{task['human_task_id']}/decide?decision=reject&operator_id={escape(task['target_person_id'])}&comment=结果不符合要求，驳回处理。">驳回</a>
            <a class="btn remind" href="/demo/tasks/{task['human_task_id']}/remind">催办一次</a>
            <a class="btn escalate" href="/demo/tasks/{task['human_task_id']}/escalate">模拟超时升级</a>
          </div>
        </div>
        """
    else:
        action_html = """
        <div class="action-panel done">
          <div class="section-label">③ 真人处理</div>
          <p>该人工待办已经结束，不能重复回应。</p>
        </div>
        """

    result = task["result_payload"]
    result_html = ""
    if result:
        result_html = f"""
        <div class="result-panel">
          <div class="section-label">④ 标准处理结果（供流程执行引擎认领）</div>
          <div class="result-grid">
            <div><span>决定</span><b>{escape(DECISION_TEXT.get(result.get('decision'), result.get('decision', '')))}</b></div>
            <div><span>状态</span><b>{escape(STATUS_TEXT.get(result.get('human_task_status'), result.get('human_task_status', '')))}</b></div>
            <div><span>处理人</span><b>{escape(result.get('operator_id', ''))}</b></div>
            <div><span>处理时间</span><b>{escape(result.get('handled_at', ''))}</b></div>
          </div>
          <p><b>最终结果：</b>{escape(result.get('final_result') or '无')}</p>
          <p><b>人工意见：</b>{escape(result.get('comment') or '无')}</p>
          <details><summary>查看 flow.callback 字段</summary><pre>{escape(json.dumps(result, ensure_ascii=False, indent=2))}</pre></details>
          <div class="boundary-note">1.11 只返回人工待办状态和处理结果；完整流程恢复、节点推进由 L2 流程执行引擎完成。</div>
        </div>
        """

    return f"""
    <article class="task-card {status_class}">
      <div class="task-head">
        <div>
          <h3>{escape(task['title'])}</h3>
          <p>经 L1 层接口登记；原触发模块：{escape(task['trigger_source_module'])}</p>
        </div>
        <span class="status {status_class}">{escape(STATUS_TEXT.get(task['status'], task['status']))}</span>
      </div>
      <div class="meta-grid">
        <div><span>人工待办编号</span><b>{escape(task['human_task_id'])}</b></div>
        <div><span>追踪编号</span><b>{escape(task['trace_id'])}</b></div>
        <div><span>流程实例</span><b>{escape(task['workflow_instance_id'])}</b></div>
        <div><span>节点 / 上游任务</span><b>{escape(task['node_id'])} / {escape(task['upstream_task_id'])}</b></div>
        <div><span>处理人</span><b>{escape(task['target_person_id'])}</b></div>
        <div><span>催办 / 升级</span><b>{task['remind_count']} 次 / {escape(task['escalated_to'] or '未升级')}</b></div>
      </div>
      <div class="mode-strip"><b>工作模式：</b>{escape(MODE_TEXT.get(task['work_mode'], task['work_mode']))}</div>
      <div class="info-grid">
        <div class="info-box"><div class="section-label">① 需要真人判断的问题</div><p>{escape(task['content'])}</p></div>
        <div class="info-box"><div class="section-label">② 上游 AI / 工具结果</div><p>{escape(task['ai_result'] or '无')}</p></div>
        <div class="info-box"><div class="section-label">依据摘要</div><p>{escape(task['evidence_summary'] or '无')}</p></div>
        <div class="info-box"><div class="section-label">引用与流程关联</div><p>{escape(render_refs(task))}</p><p class="muted">1.11 只保存关联编号，不保存完整流程状态。</p></div>
      </div>
      {result_html}
      {action_html}
    </article>
    """


def render_log(row: sqlite3.Row) -> str:
    return f"""
    <div class="log-item">
      <b>{escape(row['created_at'])}</b>　
      待办：{escape(row['human_task_id'])}　
      trace：{escape(row['trace_id'])}　
      操作人：{escape(row['operator_id'] or '系统')}　
      操作：{escape(row['action_type'])}　
      状态：{escape(row['before_status'] or '无')} → {escape(row['after_status'] or '无')}
      <div>{escape(row['detail'] or '')}</div>
    </div>
    """


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    conn = get_conn()
    task_rows = conn.execute("SELECT * FROM human_task ORDER BY created_at DESC").fetchall()
    log_rows = conn.execute("SELECT * FROM human_task_log ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()

    tasks = [task_row_to_dict(row) for row in task_rows]
    pending = [t for t in tasks if t["status"] in {"pending", "escalated"}]
    done = [t for t in tasks if t["status"] not in {"pending", "escalated"}]
    remind_count = sum(int(t["remind_count"] or 0) for t in tasks)

    pending_html = "".join(render_task_card(t) for t in pending) or "<div class='empty'>暂无待处理任务，请先生成一个演示任务。</div>"
    done_html = "".join(render_task_card(t) for t in done) or "<div class='empty'>暂无已处理任务。</div>"
    log_html = "".join(render_log(row) for row in log_rows) or "<div class='empty'>暂无日志。</div>"

    return f"""
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>L1.11 人机协同联调演示台</title>
      <style>
        * {{ box-sizing: border-box; }}
        body {{ margin:0; font-family:"Microsoft YaHei",Arial,sans-serif; background:#f3f6fb; color:#172033; }}
        a {{ text-decoration:none; color:inherit; }}
        .topbar {{ position:sticky; top:0; z-index:10; background:rgba(255,255,255,.94); border-bottom:1px solid #e4e9f2; backdrop-filter:blur(8px); }}
        .top-inner {{ max-width:1380px; margin:auto; padding:14px 24px; display:flex; justify-content:space-between; align-items:center; gap:16px; }}
        .brand {{ display:flex; gap:12px; align-items:center; }}
        .logo {{ width:42px; height:42px; border-radius:13px; display:grid; place-items:center; color:white; font-weight:900; background:linear-gradient(135deg,#5146e5,#118c80); }}
        .brand h1 {{ margin:0; font-size:18px; }} .brand p {{ margin:3px 0 0; font-size:12px; color:#667085; }}
        .nav {{ display:flex; gap:8px; flex-wrap:wrap; }} .nav a {{ padding:8px 11px; border-radius:999px; font-size:13px; color:#475467; }} .nav a:hover {{ background:#eef2ff; color:#3730a3; }}
        .page {{ max-width:1380px; margin:auto; padding:24px; }}
        .hero {{ display:grid; grid-template-columns:1.4fr 1fr; gap:18px; margin-bottom:18px; }}
        .panel {{ background:white; border:1px solid #e4e9f2; border-radius:22px; padding:24px; box-shadow:0 12px 32px rgba(34,52,84,.06); }}
        .hero h2 {{ margin:8px 0 12px; font-size:30px; }} .hero p {{ color:#526077; line-height:1.8; }}
        .tag {{ display:inline-block; background:#eaf0ff; color:#4238ca; border-radius:999px; padding:6px 11px; font-size:12px; font-weight:700; }}
        .boundary {{ margin-top:16px; padding:14px 16px; border-radius:14px; background:#fff7e8; color:#7a4b00; line-height:1.7; }}
        .quick-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
        .quick {{ display:block; text-align:center; padding:15px 10px; border:1px solid #d7deea; border-radius:14px; font-weight:700; background:#fbfcfe; }}
        .quick:hover {{ border-color:#5146e5; background:#f1f0ff; }} .quick.api {{ background:#e7f7f4; color:#087d70; }} .quick.clear {{ background:#fff0f1; color:#be123c; }}
        .stats {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-bottom:18px; }}
        .stat {{ background:white; border:1px solid #e4e9f2; border-radius:17px; padding:17px; }} .stat span {{ color:#667085; font-size:13px; }} .stat b {{ display:block; font-size:27px; margin-top:7px; }}
        .route {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-top:18px; }} .step {{ background:#f7f8fc; border-radius:13px; padding:13px; font-size:13px; line-height:1.5; }} .step b {{ display:block; color:#3730a3; margin-bottom:4px; }}
        .section {{ margin-top:22px; }} .section-title {{ display:flex; justify-content:space-between; align-items:end; margin-bottom:12px; }} .section-title h2 {{ margin:0; font-size:22px; }} .section-title p {{ margin:0; color:#667085; font-size:13px; }}
        .task-card {{ background:white; border:1px solid #e4e9f2; border-top:5px solid #5146e5; border-radius:19px; padding:20px; margin-bottom:16px; box-shadow:0 9px 25px rgba(34,52,84,.05); }}
        .task-card.escalated {{ border-top-color:#ef7d00; }} .task-card.approved {{ border-top-color:#169c62; }} .task-card.modified {{ border-top-color:#0f8c8b; }} .task-card.rejected {{ border-top-color:#dc3545; }}
        .task-head {{ display:flex; justify-content:space-between; gap:20px; align-items:start; }} .task-head h3 {{ margin:0 0 5px; }} .task-head p {{ margin:0; color:#667085; font-size:13px; }}
        .status {{ border-radius:999px; padding:7px 11px; font-size:12px; font-weight:800; white-space:nowrap; }} .status.pending {{ background:#eeeaff; color:#4938d1; }} .status.escalated {{ background:#fff1d8; color:#a95500; }} .status.approved {{ background:#e6f7ef; color:#087a48; }} .status.modified {{ background:#e4f7f7; color:#087a79; }} .status.rejected {{ background:#ffe9eb; color:#b42336; }}
        .meta-grid,.result-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-top:15px; }} .meta-grid div,.result-grid div {{ background:#f7f8fc; border-radius:12px; padding:11px; min-width:0; }} .meta-grid span,.result-grid span {{ display:block; font-size:11px; color:#667085; margin-bottom:5px; }} .meta-grid b,.result-grid b {{ display:block; font-size:13px; overflow-wrap:anywhere; }}
        .mode-strip {{ margin-top:12px; padding:11px 13px; border-radius:12px; background:#e9f8f4; color:#17665e; font-size:13px; }}
        .info-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px; }} .info-box {{ background:#f9fafc; border:1px solid #edf0f5; border-radius:13px; padding:14px; }} .info-box p {{ margin:8px 0 0; line-height:1.7; font-size:13px; }} .section-label {{ font-weight:800; font-size:13px; color:#344054; }} .muted {{ color:#7b8495; }}
        .action-panel,.result-panel {{ margin-top:13px; border-radius:14px; padding:15px; background:#f8fafc; border:1px solid #e7ebf1; }} .result-panel {{ background:#edf9f3; border-color:#ccebdd; }} .action-form {{ display:grid; grid-template-columns:1fr auto; gap:8px; margin-top:10px; }} .action-form.stacked {{ grid-template-columns:1fr 1fr auto; }} input {{ width:100%; padding:10px 11px; border:1px solid #cfd7e4; border-radius:10px; }}
        .btn {{ border:none; border-radius:10px; padding:10px 15px; color:white; font-weight:800; cursor:pointer; display:inline-block; text-align:center; }} .approve {{ background:#1a9b61; }} .modify {{ background:#0d8e8b; }} .reject {{ background:#d33c4d; }} .remind {{ background:#1566cf; }} .escalate {{ background:#8b43d3; }} .inline-actions {{ display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }}
        .result-panel p {{ font-size:13px; }} pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#172033; color:#e7edf8; padding:12px; border-radius:10px; font-size:12px; }} .boundary-note {{ margin-top:10px; background:#fff7e8; color:#7a4b00; padding:10px 12px; border-radius:10px; font-size:12px; }}
        .log-item {{ background:white; border-left:4px solid #65a5ff; border-radius:10px; padding:11px 13px; margin-bottom:8px; font-size:12px; line-height:1.7; }} .empty {{ background:white; border:1px dashed #cfd7e4; color:#667085; padding:24px; border-radius:15px; text-align:center; }}
        @media(max-width:900px) {{ .hero {{ grid-template-columns:1fr; }} .stats {{ grid-template-columns:repeat(2,1fr); }} .route {{ grid-template-columns:1fr; }} .meta-grid,.result-grid,.info-grid {{ grid-template-columns:1fr; }} .action-form,.action-form.stacked {{ grid-template-columns:1fr; }} }}
      </style>
    </head>
    <body>
      <div class="topbar"><div class="top-inner"><div class="brand"><div class="logo">H</div><div><h1>L1.11 人机协同联调演示台</h1><p>人工待办、催办与人工决定结果</p></div></div><div class="nav"><a href="#pending">待处理</a><a href="#done">已处理</a><a href="#logs">日志</a><a href="/api-test">API 测试</a><a href="/docs" target="_blank">接口文档</a></div></div></div>
      <main class="page">
        <div class="hero">
          <section class="panel">
            <span class="tag">按 2026-07-17 统一层接口规范调整</span>
            <h2>流程告诉我“这里需要人”，我负责把任务交给人</h2>
            <p>1.11 不主动发现业务问题，不判断低风险自动通过，也不保存完整流程实例。L2 流程执行引擎挂起并保存流程状态，经 L1 层接口把人工任务交给本模块；真人完成同意、修改后同意或驳回后，本模块返回状态和结果。</p>
            <div class="boundary"><b>最新职责边界：</b>正式结果仅保留“同意 / 修改后同意 / 驳回”；已删除人工接管和本模块自动通过；权限与安全审计由统一层接口及相邻模块负责。</div>
            <div class="route">
              <div class="step"><b>1. 上游判断</b>规则计算等业务引擎识别需要人工</div>
              <div class="step"><b>2. 流程挂起</b>L2 流程执行保存完整流程状态</div>
              <div class="step"><b>3. 层接口登记</b>经统一信封调用 L1.11</div>
              <div class="step"><b>4. 真人处理</b>同意、修改后同意或驳回</div>
              <div class="step"><b>5. 返回结果</b>流程执行认领结果并恢复流程</div>
            </div>
          </section>
          <section class="panel">
            <h2 style="font-size:22px;margin-top:0">一键生成联调演示任务</h2>
            <p style="margin-top:0">按钮只用于本地 Mock。正式接入时由 L2 流程执行引擎经 L1 层接口调用。</p>
            <div class="quick-grid">
              <a class="quick" href="/demo/invoice">发票确认</a>
              <a class="quick" href="/demo/travel">差旅审批</a>
              <a class="quick" href="/demo/purchase">采购异常</a>
              <a class="quick" href="/demo/risk">风险干预</a>
              <a class="quick" href="/demo/urge">OA 催办</a>
              <a class="quick" href="/demo/content">内容审核</a>
              <a class="quick api" href="/api-test">通用 API</a>
              <a class="quick clear" href="/clear">清空数据</a>
            </div>
          </section>
        </div>
        <div class="stats">
          <div class="stat"><span>任务总数</span><b>{len(tasks)}</b></div>
          <div class="stat"><span>待处理</span><b>{len(pending)}</b></div>
          <div class="stat"><span>已处理</span><b>{len(done)}</b></div>
          <div class="stat"><span>已升级待办</span><b>{len([t for t in tasks if t['status']=='escalated'])}</b></div>
          <div class="stat"><span>催办次数</span><b>{remind_count}</b></div>
        </div>
        <section class="section" id="pending"><div class="section-title"><h2>待处理 / 已升级任务</h2><p>仅管理人工协同任务自身状态</p></div>{pending_html}</section>
        <section class="section" id="done"><div class="section-title"><h2>已处理任务</h2><p>结果可由流程执行引擎凭 trace_id 认领</p></div>{done_html}</section>
        <section class="section" id="logs"><div class="section-title"><h2>本地联调日志</h2><p>正式审计后续经层接口交安全合规模块统一保管</p></div>{log_html}</section>
      </main>
    </body>
    </html>
    """


@app.get("/demo/invoice")
def demo_invoice():
    task_id = create_demo_task(
        demo_envelope(
            title="发票关键数字人工确认",
            collaboration_type="data_confirmation",
            work_mode="in_loop",
            trigger_source_module="l2.rule_calculation",
            content="发票金额、税额与报销单存在差异，需要财务人员确认最终结果。",
            ai_result="发票号码 FP20260710001；金额 12450.00 元；税额 1593.60 元；价税合计 14043.60 元。",
            evidence_summary="规则计算结果与报销单字段比对出现差异。",
            risk_level="high",
            target_person_id="finance_checker_001",
            scene_code="INVOICE",
        )
    )
    return RedirectResponse(url=f"/#pending", status_code=303)


@app.get("/demo/travel")
def demo_travel():
    create_demo_task(
        demo_envelope(
            title="差旅费审批异常",
            collaboration_type="approval_review",
            work_mode="on_loop",
            trigger_source_module="l2.rule_calculation",
            content="差旅报销金额超过标准上限，且部分凭证不完整，需要审批人决定。",
            ai_result="报销金额 3680.00 元；标准上限 3000.00 元；超标 680.00 元。",
            evidence_summary="差旅标准 v2026、报销单和住宿凭证引用。",
            risk_level="high",
            target_person_id="finance_checker_001",
            scene_code="TRAVEL",
        )
    )
    return RedirectResponse(url="/#pending", status_code=303)


@app.get("/demo/purchase")
def demo_purchase():
    create_demo_task(
        demo_envelope(
            title="采购订单异常审批",
            collaboration_type="approval_review",
            work_mode="on_loop",
            trigger_source_module="l2.rule_calculation",
            content="采购金额与合同上限不一致，需要采购负责人决定是否继续。",
            ai_result="订单金额 186000.00 元；合同上限 150000.00 元；超出 36000.00 元。",
            evidence_summary="采购订单、合同登记及付款条件比对结果。",
            risk_level="high",
            target_person_id="purchase_manager_001",
            scene_code="PURCHASE",
        )
    )
    return RedirectResponse(url="/#pending", status_code=303)


@app.get("/demo/risk")
def demo_risk():
    create_demo_task(
        demo_envelope(
            title="高风险业务人工干预",
            collaboration_type="risk_intervention",
            work_mode="on_loop",
            trigger_source_module="l2.analysis_prediction",
            content="风险指标超过预设阈值，流程执行引擎已挂起原流程，请责任人决定。",
            ai_result="风险分值 87；预设阈值 70；主要原因：金额异常与凭据缺失。",
            evidence_summary="分析预测结果、规则版本和来源数据引用。",
            risk_level="high",
            target_person_id="risk_owner_001",
            scene_code="RISK",
        )
    )
    return RedirectResponse(url="/#pending", status_code=303)


@app.get("/demo/urge")
def demo_urge():
    create_demo_task(
        demo_envelope(
            title="OA 流程待办催办",
            collaboration_type="todo_reminder",
            work_mode="in_loop",
            trigger_source_module="l2.workflow_execution",
            content="流程在人工节点等待时间较长，可执行催办或按既定规则升级。",
            ai_result="当前待办已等待 26 小时，超过演示阈值。",
            evidence_summary="流程实例和人工节点等待时长。",
            risk_level="medium",
            target_person_id="department_approver_001",
            scene_code="URGE",
        )
    )
    return RedirectResponse(url="/#pending", status_code=303)


@app.get("/demo/content")
def demo_content():
    create_demo_task(
        demo_envelope(
            title="对外内容发布前审核",
            collaboration_type="content_review",
            work_mode="in_loop",
            trigger_source_module="l2.content_generation",
            content="对外发布内容会产生外部影响，需要真人审阅后才能继续。",
            ai_result="已生成对外通知草稿，待确认措辞、数据和发布范围。",
            evidence_summary="内容草稿和引用资料。",
            risk_level="medium",
            target_person_id="content_reviewer_001",
            scene_code="CONTENT",
        )
    )
    return RedirectResponse(url="/#pending", status_code=303)


@app.get("/demo/tasks/{human_task_id}/decide")
def demo_decide(
    human_task_id: str,
    decision: str = Query(...),
    operator_id: str = Query(...),
    modified_result: str = Query(""),
    comment: str = Query(""),
):
    task = get_task(human_task_id)
    if not task:
        return HTMLResponse("任务不存在", status_code=404)
    if decision not in {"approve", "modify_approve", "reject"}:
        return HTMLResponse("正式处理结果仅支持同意、修改后同意、驳回。", status_code=400)
    try:
        apply_decision(
            task,
            decision=decision,
            operator_id=operator_id,
            modified_result=modified_result,
            comment=comment,
        )
    except ValueError as exc:
        return HTMLResponse(escape(str(exc)), status_code=409)
    return RedirectResponse(url="/#done", status_code=303)


@app.get("/demo/tasks/{human_task_id}/remind")
def demo_remind(human_task_id: str):
    task = get_task(human_task_id)
    if not task:
        return HTMLResponse("任务不存在", status_code=404)
    if task["status"] not in {"pending", "escalated"}:
        return HTMLResponse("已结束任务不能催办", status_code=409)
    count = int(task["remind_count"] or 0) + 1
    conn = get_conn()
    conn.execute(
        "UPDATE human_task SET remind_count = ?, updated_at = ? WHERE human_task_id = ?",
        (count, now_text(), human_task_id),
    )
    conn.commit()
    conn.close()
    write_log(human_task_id, task["trace_id"], "system_reminder", "待办催办", task["status"], task["status"], f"第 {count} 次催办。")
    return RedirectResponse(url="/#pending", status_code=303)


@app.get("/demo/tasks/{human_task_id}/escalate")
def demo_escalate(human_task_id: str):
    task = get_task(human_task_id)
    if not task:
        return HTMLResponse("任务不存在", status_code=404)
    if task["status"] not in {"pending", "escalated"}:
        return HTMLResponse("已结束任务不能升级", status_code=409)
    before = task["status"]
    target = "direct_leader_001"
    conn = get_conn()
    conn.execute(
        "UPDATE human_task SET status='escalated', escalated_to=?, target_person_id=?, updated_at=? WHERE human_task_id=?",
        (target, target, now_text(), human_task_id),
    )
    conn.commit()
    conn.close()
    write_log(human_task_id, task["trace_id"], "system_timer_mock", "超时升级", before, "escalated", f"按演示规则升级给 {target}。")
    return RedirectResponse(url="/#pending", status_code=303)


@app.get("/api-test", response_class=HTMLResponse)
def api_test_page() -> str:
    token = uuid4().hex[:8]
    sample = {
        "protocol_version": "1.0",
        "message_id": f"msg_api_{token}",
        "trace_id": f"trace_api_{token}",
        "request_id": f"req_api_{token}",
        "parent_message_id": None,
        "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
        "target": {"layer": "L1", "service_code": SERVICE_CODE},
        "channel": "l2_to_l1",
        "route_type": "task.dispatch",
        "action": "human.task.create",
        "capability_id": "CAP.HUMAN.TASK.CREATE",
        "capability_dictionary_version": "2026.07.17",
        "registry_version": "registry_2026.07.17",
        "actor": {"person_id": "employee_001", "tenant_id": "tenant_hanhe", "position_id": "finance_staff"},
        "context": {
            "workflow_instance_id": f"flow_api_{token}",
            "node_id": "node_human_approval_001",
            "task_id": f"task_api_{token}",
            "data_refs": [
                {
                    "ref_id": f"dataref_travel_{token}",
                    "resource_type": "travel_reimbursement",
                    "version": "v1",
                    "data_labels": ["internal"],
                    "allowed_actions": ["read"],
                }
            ],
            "artifact_refs": [],
        },
        "idempotency_key": f"flow_api_{token}-node_human_approval_001-v1",
        "deadline_at": iso_deadline(2),
        "payload": {
            "collaboration_type": "approval_review",
            "work_mode": "on_loop",
            "trigger_source_module": "l2.rule_calculation",
            "title": "通用 API 创建的差旅审批异常任务",
            "content": "规则计算结果显示差旅费超标且凭证不完整，需要财务人工确认。",
            "ai_result": "报销金额 3680.00 元；标准上限 3000.00 元；超标 680.00 元。",
            "evidence_summary": "差旅标准 v2026、报销单与凭据引用。",
            "risk_level": "high",
            "target_person_id": "finance_checker_001",
            "deadline_at": iso_deadline(2),
            "decision_options": ["approve", "modify_approve", "reject"],
        },
    }
    sample_json = json.dumps(sample, ensure_ascii=False, indent=2)
    return f"""
    <!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>1.11 统一 API 测试页</title>
    <style>
      body {{ margin:0; background:#f3f6fb; color:#172033; font-family:"Microsoft YaHei",Arial,sans-serif; }}
      .wrap {{ max-width:1180px; margin:36px auto; padding:0 20px; }} .card {{ background:white; border:1px solid #dfe6ef; border-radius:18px; padding:24px; box-shadow:0 10px 30px rgba(30,50,80,.06); }}
      h1 {{ margin-top:0; }} p {{ line-height:1.7; color:#526077; }} textarea {{ width:100%; min-height:530px; border:1px solid #cad4e1; border-radius:12px; padding:14px; font-family:Consolas,monospace; font-size:13px; }}
      button,a {{ display:inline-block; border:none; border-radius:10px; padding:11px 16px; font-weight:800; color:white; cursor:pointer; margin:12px 8px 0 0; text-decoration:none; }} button {{ background:#075f94; }} a {{ background:#22945d; }} pre {{ background:#132033; color:#edf4ff; padding:14px; border-radius:12px; white-space:pre-wrap; overflow-wrap:anywhere; min-height:90px; }} .note {{ background:#fff7e8; color:#744900; border-radius:11px; padding:12px; }}
    </style></head><body><div class="wrap"><div class="card">
      <h1>L1.11 通用 API 测试页</h1>
      <p>测试 <b>POST /api/v1/human-tasks</b>。正式接入时，L2 流程执行引擎通过 L1 层接口按统一信封登记人工任务。</p>
      <div class="note">本接口不接收 auto_pass，也不接收完整 resume_payload；低风险自动通过由上游规则/流程判断，完整流程状态由流程执行引擎保存。</div>
      <textarea id="payload">{escape(sample_json)}</textarea>
      <div><button onclick="sendTask()">发送统一请求</button><a href="/">返回中文演示台</a></div>
      <h2>接口返回结果</h2><pre id="result">等待发送……</pre>
    </div></div>
    <script>
      async function sendTask() {{
        const out = document.getElementById('result');
        try {{
          const payload = JSON.parse(document.getElementById('payload').value);
          const response = await fetch('/api/v1/human-tasks', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(payload)}});
          const data = await response.json();
          out.textContent = JSON.stringify(data, null, 2);
        }} catch (e) {{ out.textContent = '发送失败：' + e; }}
      }}
    </script></body></html>
    """


@app.get("/clear")
def clear_data():
    conn = get_conn()
    conn.execute("DELETE FROM human_task_log")
    conn.execute("DELETE FROM human_task")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)
