from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from .engine import FLOW_SERVICES, FlowExecutionEngine, now_iso


PROTOCOL_VERSION = "1.0"
SERVICE_CODE = "l2.workflow_execution"
REQUIRED_FIELDS = {
    "protocol_version", "message_id", "trace_id", "request_id", "occurred_at",
    "source", "target", "channel", "action", "request_type", "actor",
    "context", "deadline_at", "payload",
}
ACTION_MAP = {
    "flow.start": "flow.start",
    "flow.get": "flow.get",
    "task.get": "flow.get",
    "flow.list": "flow.list",
    "task.list": "flow.list",
    "human.decide": "flow.decide_human",
    "flow.decide_human": "flow.decide_human",
    "flow.callback": "flow.dispatch_status",
    "flow.dispatch_status": "flow.dispatch_status",
    "flow.cancel": "flow.cancel",
    "flow.health": "flow.health",
    "flow.scan_timeouts": "flow.scan_timeouts",
    "flow.scan_delivery_retries": "flow.scan_delivery_retries",
}
ACTION_ROUTE_RULES = {
    "flow.start": {"layers": {"L2"}, "channels": {"l2_internal"}},
    "flow.get": {"layers": {"L4", "L2"}, "channels": {"l4_to_l2", "l2_internal"}},
    "task.get": {"layers": {"L4", "L2"}, "channels": {"l4_to_l2", "l2_internal"}},
    "flow.list": {"layers": {"L4", "L2"}, "channels": {"l4_to_l2", "l2_internal"}},
    "task.list": {"layers": {"L4", "L2"}, "channels": {"l4_to_l2", "l2_internal"}},
    "human.decide": {"layers": {"L4"}, "channels": {"l4_to_l2"}},
    "flow.decide_human": {"layers": {"L4"}, "channels": {"l4_to_l2"}},
    "flow.callback": {"layers": {"L2"}, "channels": {"callback"}},
    "flow.dispatch_status": {"layers": {"L2"}, "channels": {"callback"}},
    "flow.cancel": {"layers": {"L4"}, "channels": {"l4_to_l2"}},
    "flow.scan_timeouts": {"layers": {"L2"}, "channels": {"scheduled"}},
    "flow.scan_delivery_retries": {"layers": {"L2"}, "channels": {"scheduled"}},
}


class PlatformRequestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PlatformFlowExecutionAdapter:
    """v1 platform-envelope adapter; the engine remains the sole owner of runtime state."""

    def __init__(self, engine: FlowExecutionEngine) -> None:
        self.engine = engine

    def handle(self, instruction: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._validate(instruction)
            action = str(instruction["action"])
            service_name = ACTION_MAP.get(action)
            if not service_name:
                return self._failed(instruction, "action_not_allowed", f"unsupported L2 workflow action: {action}")
            self._validate_route(instruction, action)
            payload = dict(instruction["payload"])
            actor = instruction["actor"]
            if service_name == "flow.start":
                form_data = payload.get("form_data") if isinstance(payload.get("form_data"), dict) else {}
                if form_data:
                    payload = {**form_data, **{key: value for key, value in payload.items() if key != "form_data"}}
                if not payload.get("request_text"):
                    payload["request_text"] = str(payload.get("task_title") or payload.get("form_type") or instruction["action"])
                if not isinstance(payload.get("intent_result"), dict):
                    payload["intent_result"] = {"task_type": str(payload.get("task_type") or "execution")}
                payload.setdefault("requester_id", actor["person_id"])
                payload.setdefault("idempotency_key", instruction.get("idempotency_key") or "")
                self._validate_flow_start_handoff(instruction, payload)
            elif service_name == "flow.decide_human":
                payload.setdefault("decided_by", actor["person_id"])
                if "human_task_id" in payload and "task_id" not in payload:
                    payload["task_id"] = payload["human_task_id"]
            elif service_name == "flow.dispatch_status":
                payload.setdefault("callback_id", instruction["message_id"])
            local = {
                "service_name": service_name,
                "request_type": instruction["request_type"],
                "actor_id": actor["person_id"],
                "trace_id": instruction["trace_id"],
                "payload": payload,
            }
            outcome = self.engine.handle_instruction(local)
            if not outcome.get("ok"):
                error = outcome.get("error") or {}
                return self._failed(instruction, str(error.get("code") or "internal_error"), str(error.get("message") or "workflow request failed"))
            result = outcome["result"]
            if service_name == "flow.start" and result.get("status") in {"accepted", "in_progress", "waiting_human"}:
                return self._reply(
                    instruction,
                    "accepted",
                    {"result_type": "task_receipt", "task_id": result["instance_id"], "status": result["status"], "status_query_action": "task.get"},
                )
            return self._reply(instruction, "success", {"result_type": "data", "data": result})
        except PlatformRequestError as exc:
            return self._failed(instruction, exc.code, str(exc))
        except ValueError as exc:
            return self._failed(instruction, "invalid_message", str(exc))

    def capabilities(self) -> Dict[str, Any]:
        return {
            "service_code": SERVICE_CODE,
            "service_version": self.engine.service_registry()["version"],
            "protocol_version": PROTOCOL_VERSION,
            "actions": sorted(ACTION_MAP),
            "engine_services": sorted(FLOW_SERVICES),
            "health_check": "/health",
        }

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "service_code": SERVICE_CODE, "protocol_version": PROTOCOL_VERSION, "runtime": self.engine.health()}

    def _validate(self, instruction: Dict[str, Any]) -> None:
        missing = REQUIRED_FIELDS.difference(instruction)
        if missing:
            raise ValueError(f"missing required fields: {', '.join(sorted(missing))}")
        if instruction["protocol_version"] != PROTOCOL_VERSION:
            raise ValueError("unsupported protocol version")
        if instruction["request_type"] not in {"query", "execute", "maintain"}:
            raise ValueError("request_type must be query, execute, or maintain")
        for field in ("source", "target", "actor", "context", "payload"):
            if not isinstance(instruction[field], dict):
                raise ValueError(f"{field} must be an object")
        if instruction["target"].get("service_code") != SERVICE_CODE or instruction["target"].get("layer") != "L2":
            raise ValueError("target must be l2.workflow_execution in L2")
        if not instruction["actor"].get("person_id"):
            raise ValueError("actor.person_id is required")
        if instruction["request_type"] in {"execute", "maintain"} and not instruction.get("idempotency_key"):
            raise ValueError("idempotency_key is required for execute and maintain")
        deadline = datetime.fromisoformat(str(instruction["deadline_at"]).replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            raise ValueError("deadline_at must include timezone")
        if deadline.astimezone(timezone.utc) < datetime.now(timezone.utc):
            raise ValueError("deadline exceeded")

    def _validate_route(self, instruction: Dict[str, Any], action: str) -> None:
        rule = ACTION_ROUTE_RULES.get(action)
        if not rule:
            return
        if instruction["source"].get("layer") not in rule["layers"]:
            raise PlatformRequestError("caller_not_allowed", "source layer is not allowed for this action")
        if instruction.get("channel") not in rule["channels"]:
            raise PlatformRequestError("caller_not_allowed", "channel is not allowed for this action")

    def _validate_flow_start_handoff(self, instruction: Dict[str, Any], payload: Dict[str, Any]) -> None:
        """A workflow starts only after intent analysis has produced a confirmed command."""
        intent_result = payload.get("intent_result") if isinstance(payload.get("intent_result"), dict) else {}
        capability_ids = intent_result.get("capability_ids") or []
        if not capability_ids:
            return  # Local transitional planning remains available for registered demos/templates.
        if instruction["source"].get("service_code") != "l2.intent_analysis":
            raise PlatformRequestError("caller_not_allowed", "capability command must be handed off by l2.intent_analysis")
        if intent_result.get("requires_user_confirmation") and not intent_result.get("user_confirmed"):
            raise PlatformRequestError("intent_confirmation_required", "confirmed intent command is required before flow execution")

    def _reply(self, instruction: Dict[str, Any], reply_type: str, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "reply_type": reply_type,
            "message_id": f"msg_{uuid4().hex}",
            "trace_id": instruction["trace_id"],
            "request_id": instruction["request_id"],
            "in_reply_to": instruction["message_id"],
            "service_code": SERVICE_CODE,
            "service_version": self.engine.service_registry()["version"],
            "occurred_at": now_iso(),
            "result": result,
            "error": None,
            "audit": {"decision_id": "", "event_id": ""},
        }

    def _failed(self, instruction: Dict[str, Any], code: str, message: str) -> Dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "reply_type": "failed",
            "message_id": f"msg_{uuid4().hex}",
            "trace_id": instruction.get("trace_id", f"trace_{uuid4().hex}"),
            "request_id": instruction.get("request_id", f"req_{uuid4().hex}"),
            "in_reply_to": instruction.get("message_id", ""),
            "service_code": SERVICE_CODE,
            "service_version": self.engine.service_registry()["version"],
            "occurred_at": now_iso(),
            "result": None,
            "error": {"code": code, "message": message, "retryable": False, "details": {}},
            "audit": {"decision_id": "", "event_id": ""},
        }
