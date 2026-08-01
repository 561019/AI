from __future__ import annotations

from typing import Any
from uuid import uuid4

from framework.core import now, standard_response
from framework.layers.foundation.generic_module_adapter import get_for, post_for
from framework.module_catalog import MODULE_BY_CODE


MODULE_CODE = "control-mechanism"
MODULE = MODULE_BY_CODE[MODULE_CODE]


def get(handler: Any) -> bool:
    return get_for(MODULE_CODE, handler)


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != MODULE.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability == "control.policy.apply":
        _apply_policy(handler, envelope)
        return
    post_for(MODULE_CODE, handler, envelope)


def _apply_policy(handler: Any, envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    actor = envelope.get("actor") or {}
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    control_context = payload.get("control_context") or payload.get("user_goal") or payload.get("analysis_goal")
    user_goal = str(payload.get("user_goal") or payload.get("utterance") or control_context or "")
    needs_human = any(token in user_goal for token in ("审批", "立项", "确认", "人工", "真人", "负责人"))
    decision_id = str(payload.get("decision_id") or f"control-{payload.get('platform_task_id') or uuid4()}")
    data = {
        "state": "applied",
        "module": MODULE_CODE,
        "module_name_cn": MODULE.name_cn,
        "platform_capability": "control.policy.apply",
        "decision": "allow",
        "decision_id": decision_id,
        "control_context": control_context,
        "workflow_task_id": payload.get("platform_task_id"),
        "tenant_id": actor.get("tenant_id"),
        "owner_account_id": actor.get("user_id") or actor.get("actor_id"),
        "project_id": payload.get("project_id") or context.get("project_id"),
        "conversation_id": payload.get("conversation_id") or context.get("conversation_id"),
        "policy_result": {
            "can_continue": True,
            "requires_human_confirmation": needs_human,
            "handoff_required": needs_human,
            "blocked": False,
        },
        "guardrails": [
            "流程可以继续推进，但不能替代负责人正式审批。",
            "涉及立项、审批、预算、合同或执行落地的结论必须保留真人确认事项。",
            "后续模块只能使用当前账号、项目和对话授权范围内的数据。",
        ],
        "created_at": now(),
    }
    handler.send(200, standard_response(envelope, "success", data=data))
