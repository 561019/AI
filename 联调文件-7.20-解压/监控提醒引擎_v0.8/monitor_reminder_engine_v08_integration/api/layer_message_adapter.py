from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any, Callable

from api.api_validation import (
    build_register_subtask,
    validate_monitor_item_request,
    validate_monitor_item_status_request,
    validate_monitor_item_update_request,
    validate_reminder_action_request,
    validate_reminder_trigger_request,
)
from api.message_envelope_validation import validate_message_envelope
from api.monitor_item_adapter import (
    change_monitor_item_status,
    modify_monitor_item,
)
from api.reminder_action_adapter import (
    confirm_reminder,
    escalate_reminder,
    recover_reminder,
)
from api.reminder_service_adapter import process_reminder_trigger
from api.standard_reply import (
    accepted_reply,
    failed_reply,
    success_reply,
)
from repositories.idempotency_repository import (
    begin_idempotent_request,
    complete_idempotent_request,
)
from repositories.trace_repository import read_trace_records
from service_register import create_monitor_item


def _request_hash(envelope: dict[str, Any]) -> str:
    raw = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _legacy_common(envelope: dict[str, Any]) -> dict[str, Any]:
    actor = envelope["actor"]
    context = envelope["context"]
    return {
        "request_id": envelope["request_id"],
        "trace_id": envelope["trace_id"],
        "source_module": "workflow_engine_demo",
        "operator_id": actor["person_id"],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "task_id": context["task_id"],
    }


def _validation_failed(
    envelope: dict[str, Any],
    errors: list[str],
    code: str,
) -> tuple[int, dict[str, Any]]:
    return 400, failed_reply(
        envelope,
        code=code,
        message="请求业务字段校验失败",
        data={"business_status": "无法办理", "errors": errors},
    )


def _register(envelope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request_data = {
        **_legacy_common(envelope),
        "payload": envelope["payload"],
    }
    errors = validate_monitor_item_request(request_data)
    if errors:
        return _validation_failed(envelope, errors, "MONITOR_LAYER_REGISTER_4001")

    result = create_monitor_item(build_register_subtask(request_data))
    if result.get("status") == "无法办理":
        return 400, failed_reply(
            envelope,
            code="MONITOR_LAYER_REGISTER_4002",
            message=result.get("reason", "监控事项登记失败"),
            data={"business_status": "无法办理", "service_result": result},
        )

    return 201, success_reply(
        envelope,
        message="监控事项登记完成",
        data={
            "business_status": "已完成",
            "item_id": result.get("item_id"),
            "result_ref": f"monitor_item:{result.get('item_id')}",
            "service_result": result,
        },
    )


def _update(envelope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    payload = envelope["payload"]
    request_data = {
        **_legacy_common(envelope),
        "updates": payload.get("updates"),
    }
    errors = validate_monitor_item_update_request(request_data)
    if not isinstance(payload.get("item_id"), str) or not payload.get("item_id", "").strip():
        errors.append("payload.item_id 缺失或为空")
    if errors:
        return _validation_failed(envelope, errors, "MONITOR_LAYER_UPDATE_4001")

    result = modify_monitor_item(payload["item_id"], request_data)
    if result.get("outcome") == "not_found":
        return 404, failed_reply(envelope, code="MONITOR_LAYER_ITEM_4041", message=result["message"], data=result)
    if result.get("outcome") == "trace_mismatch":
        return 409, failed_reply(envelope, code="MONITOR_LAYER_TRACE_4091", message=result["message"], data=result)
    if result.get("outcome") == "invalid_template":
        return 400, failed_reply(envelope, code="MONITOR_LAYER_TEMPLATE_4001", message=result["message"], data=result)
    if result.get("outcome") == "invalid_governance_policy":
        return 400, failed_reply(envelope, code="MONITOR_LAYER_POLICY_4001", message=result["message"], data=result)
    return 200, success_reply(envelope, message=result["message"], data=result)


def _status(
    envelope: dict[str, Any],
    target_status: str,
    status_action: str = "",
) -> tuple[int, dict[str, Any]]:
    payload = envelope["payload"]
    request_data = {
        **_legacy_common(envelope),
        "status_action": status_action,
    }
    errors = validate_monitor_item_status_request(request_data)
    if not isinstance(payload.get("item_id"), str) or not payload.get("item_id", "").strip():
        errors.append("payload.item_id 缺失或为空")
    if errors:
        return _validation_failed(envelope, errors, "MONITOR_LAYER_STATUS_4001")
    result = change_monitor_item_status(payload["item_id"], request_data, target_status)
    if result.get("outcome") == "not_found":
        return 404, failed_reply(envelope, code="MONITOR_LAYER_ITEM_4041", message=result["message"], data=result)
    if result.get("outcome") == "trace_mismatch":
        return 409, failed_reply(envelope, code="MONITOR_LAYER_TRACE_4091", message=result["message"], data=result)
    if result.get("outcome") == "invalid_transition":
        return 409, failed_reply(envelope, code="MONITOR_LAYER_STATUS_4092", message=result["message"], data=result)
    return 200, success_reply(envelope, message=result["message"], data=result)


def _handle_reminder(envelope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    payload = envelope["payload"]
    request_data = {
        **_legacy_common(envelope),
        "item_id": payload.get("item_id"),
        "judgement_result": payload.get("judgement_result"),
    }
    errors = validate_reminder_trigger_request(request_data)
    if errors:
        return _validation_failed(envelope, errors, "MONITOR_LAYER_REMINDER_4001")

    result = process_reminder_trigger(request_data)
    outcome = result.get("outcome")
    if outcome == "not_found":
        return 404, failed_reply(envelope, code="MONITOR_LAYER_REMINDER_4041", message=result["message"], data=result)
    if outcome in ("paused", "disabled", "trace_mismatch"):
        return 409, failed_reply(envelope, code="MONITOR_LAYER_REMINDER_4091", message=result["message"], data=result)
    if outcome == "unable_to_deliver":
        return 422, failed_reply(envelope, code="MONITOR_LAYER_REMINDER_4221", message=result["message"], retryable=True, data=result)
    if outcome == "notification_sent":
        return 202, accepted_reply(
            envelope,
            message="提醒已经生成并送达，等待真人确认或后续流程回调",
            status="waiting_human_confirmation",
            data={
                **result,
                "next_action": "等待确定性确认请求或流程继续派发",
                "query_action": "monitor.trace.query",
            },
        )
    return 200, success_reply(envelope, message=result["message"], data=result)


def _action(envelope: dict[str, Any], action: str) -> tuple[int, dict[str, Any]]:
    payload = envelope["payload"]
    request_data = {**_legacy_common(envelope)}
    if action == "confirm":
        request_data["confirm_user"] = payload.get("confirm_user")
        handler: Callable[[int, dict[str, Any]], dict[str, Any]] = confirm_reminder
    elif action == "escalate":
        request_data["escalation_role"] = payload.get("escalation_role")
        request_data["reason"] = payload.get("reason")
        handler = escalate_reminder
    else:
        request_data["recovery_user"] = payload.get("recovery_user")
        handler = recover_reminder

    errors = validate_reminder_action_request(request_data, action)
    reminder_id = payload.get("reminder_id")
    if isinstance(reminder_id, bool) or not isinstance(reminder_id, int) or reminder_id <= 0:
        errors.append("payload.reminder_id 必须是大于0的整数")
    if errors:
        return _validation_failed(envelope, errors, "MONITOR_LAYER_ACTION_4001")

    result = handler(reminder_id, request_data)
    if result.get("outcome") == "not_found":
        return 404, failed_reply(envelope, code="MONITOR_LAYER_ACTION_4041", message=result["message"], data=result)
    if result.get("outcome") in ("trace_mismatch", "invalid_state"):
        return 409, failed_reply(envelope, code="MONITOR_LAYER_ACTION_4091", message=result["message"], data=result)
    return 201, success_reply(envelope, message=result["message"], data=result)


def _trace(envelope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    query_trace_id = envelope["payload"].get("trace_id") or envelope["trace_id"]
    records = read_trace_records(query_trace_id)
    total_records = sum(len(rows) for rows in records.values())
    return 200, success_reply(
        envelope,
        message="全过程记录查询完成",
        data={
            "business_status": "已完成",
            "query_trace_id": query_trace_id,
            "total_records": total_records,
            "records": records,
        },
    )


def _dispatch(envelope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    handlers: dict[str, Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]] = {
        "monitor.item.register": _register,
        "monitor.item.update": _update,
        "monitor.item.enable": lambda env: _status(
            env,
            "enabled",
            "enable",
        ),
        "monitor.item.pause": lambda env: _status(
            env,
            "paused",
            "pause",
        ),
        "monitor.item.resume": lambda env: _status(
            env,
            "enabled",
            "resume",
        ),
        "monitor.item.disable": lambda env: _status(
            env,
            "disabled",
            "disable",
        ),
        "reminder.handle": _handle_reminder,
        "reminder.confirm.record": lambda env: _action(env, "confirm"),
        "reminder.escalate.record": lambda env: _action(env, "escalate"),
        "reminder.recover.record": lambda env: _action(env, "recover"),
        "monitor.trace.query": _trace,
    }
    handler = handlers.get(envelope["action"])
    if handler is None:
        return 400, failed_reply(
            envelope,
            code="MONITOR_LAYER_ACTION_NOT_REGISTERED",
            message="当前 action 未登记到监控提醒引擎",
        )
    return handler(envelope)


def process_layer_message(
    envelope: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    errors = validate_message_envelope(envelope)
    if errors:
        return 400, failed_reply(
            envelope,
            code="MONITOR_ENVELOPE_INVALID",
            message="统一消息信封校验失败",
            data={"business_status": "无法办理", "errors": errors},
        )

    request_hash = _request_hash(envelope)
    state, record = begin_idempotent_request(
        idempotency_key=envelope["idempotency_key"],
        request_hash=request_hash,
        message_id=envelope["message_id"],
        trace_id=envelope["trace_id"],
        action=envelope["action"],
    )

    if state == "conflict":
        return 409, failed_reply(
            envelope,
            code="MONITOR_IDEMPOTENCY_CONFLICT",
            message="相同 idempotency_key 对应了不同请求内容",
            data={"business_status": "无法办理"},
        )

    if state == "processing":
        return 202, accepted_reply(
            envelope,
            message="相同幂等任务正在处理中，本次不重复执行",
            data={"business_status": "办理中", "idempotency_replayed": True},
        )

    if state == "replay" and record:
        response = json.loads(record["response_json"])
        response = copy.deepcopy(response)
        response.setdefault("meta", {})["idempotency_replayed"] = True
        return int(record["response_code"]), response

    try:
        status_code, response = _dispatch(envelope)
    except Exception as exc:
        status_code, response = 500, failed_reply(
            envelope,
            code="MONITOR_LAYER_INTERNAL_ERROR",
            message=f"层内任务办理异常：{exc}",
            retryable=True,
            status="failed",
        )

    complete_idempotent_request(
        idempotency_key=envelope["idempotency_key"],
        response_code=status_code,
        response_data=response,
    )
    return status_code, response
