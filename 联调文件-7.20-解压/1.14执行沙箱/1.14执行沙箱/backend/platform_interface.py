from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "1.0"
SERVICE_CODE = "execution_sandbox.run_task"
CODE_SERVICE_CODE = "execution_sandbox.run_code"
BROWSER_SERVICE_CODE = "execution_sandbox.run_browser"
STANDARD_PATH = "/api/v1/layer-interface/messages"
CAPABILITY_MAP = {
    "CAP.SANDBOX.TASK.RUN": (SERVICE_CODE, "sandbox.template.run"),
    "CAP.SANDBOX.CODE.RUN": (CODE_SERVICE_CODE, "sandbox.code.run"),
    "CAP.SANDBOX.BROWSER.RUN": (BROWSER_SERVICE_CODE, "sandbox.browser.run"),
}
ENGINE_BY_SOURCE = {
    "l2.workflow_execution": "flow-execution-engine",
    "l2.rule_computation": "rule-computation-engine",
    "l2.external_system_connector": "external-system-connector-engine",
}

DEFAULT_ALLOWED_ENGINES = [
    "intent-analysis-engine",
    "flow-execution-engine",
    "document-table-parser-engine",
    "external-system-connector-engine",
    "data-aggregation-engine",
    "rule-computation-engine",
    "analysis-forecast-engine",
    "knowledge-qa-engine",
    "content-generation-engine",
    "multimedia-generation-engine",
    "monitoring-alert-engine",
    "digital-asset-engine",
    "project-management-engine",
]


class PlatformInterfaceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail or {}

    def response(self, trace_id: str | None = None) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "trace_id": trace_id,
            "reply_type": "rejection",
            "status": "rejected",
            "reason": {
                "code": self.code,
                "message": self.message,
                "detail": self.detail,
            },
            "responded_at": utc_now(),
        }


class PlatformInterface:
    """Layer-interface compatible adapter for the execution sandbox capability."""

    def __init__(self, project_root: Path, service: Any) -> None:
        self.project_root = project_root
        self.service = service
        self.data_file = project_root / "data" / "platform_requests.json"
        self._lock = threading.RLock()
        config = service.config.get("platform_interface", {})
        self.allowed_layer = str(config.get("allowed_caller_layer", "business_engine"))
        self.allowed_engines = set(config.get("allowed_engines") or DEFAULT_ALLOWED_ENGINES)
        self.api_token = os.environ.get("SANDBOX_PLATFORM_API_TOKEN") or str(config.get("demo_api_token", ""))
        self.max_records = int(config.get("max_request_records", 200))
        self._requests = self._load()
        self._recover_incomplete_requests()

    def service_catalog(self) -> dict[str, Any]:
        scenarios = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "risk_level": item.get("risk_level"),
                "needs_human_approval": item.get("needs_human_approval"),
            }
            for item in self.service.list_scenarios()
        ]
        common = {
            "owner_module": "L1.14 execution sandbox",
            "invocation_path": STANDARD_PATH,
            "query_path_template": f"{STANDARD_PATH}/{{request_id}}",
            "allowed_source": {"layer": "L2", "service_codes": sorted(ENGINE_BY_SOURCE)},
            "standard_replies": ["accepted", "success", "failed"],
            "required_headers": ["Authorization: Bearer <platform-token>", "Content-Type: application/json"],
            "envelope_required": ["message_id", "trace_id", "request_id", "source", "target", "channel", "route_type", "action", "capability_id", "capability_dictionary_version", "registry_version", "actor", "context", "idempotency_key", "deadline_at", "payload"],
            "result_contract": {"success": ["data", "evidence"], "accepted": ["data.task_id", "data.query"], "failed": ["error", "retryable"]},
            "identity_and_policy_source": "mock adapters until 1.4/1.8/1.9 joint integration",
        }
        capabilities = [
            {**common, "capability_id": "CAP.SANDBOX.TASK.RUN", "action": "sandbox.template.run", "service_code": SERVICE_CODE, "service_name": "已登记场景模板隔离运行", "description": "在受限 Docker 环境中运行已登记岗位场景并返回结果、文件和证据。", "payload_required": ["scenario_id", "agent", "limits", "input"], "scenarios": scenarios, "current_runtime": self.service.executor.name},
            {**common, "capability_id": "CAP.SANDBOX.CODE.RUN", "action": "sandbox.code.run", "service_code": CODE_SERVICE_CODE, "service_name": "AI 临时代码隔离运行", "description": "在默认断网的 Docker 容器中运行 AI 生成的 Python 程序。", "payload_required": ["code", "language=python", "input", "limits"], "current_runtime": "DockerAdhocExecutor"},
            {**common, "capability_id": "CAP.SANDBOX.BROWSER.RUN", "action": "sandbox.browser.run", "service_code": BROWSER_SERVICE_CODE, "service_name": "浏览器网页隔离采集", "description": "动态创建内部网络、代理和 Chromium 容器，仅访问白名单网页并返回出站审计。", "payload_required": ["url", "input", "limits"], "current_runtime": "DockerAdhocExecutor"},
        ]
        return {
            "protocol_version": PROTOCOL_VERSION,
            "catalog_version": "2026.07.19",
            "layer": "L1",
            "module": "l1.execution_sandbox",
            "preferred_interface": {"name": "company_standard_v0.3", "submit": STANDARD_PATH, "query": f"{STANDARD_PATH}/{{request_id}}"},
            "capabilities": capabilities,
            "legacy_compatibility": {"deprecated_for_new_integration": True, "paths": ["/api/v1/layer-interface/requests", "/api/tasks", "/api/e2b/*"], "note": "Only for existing demo and compatibility tests; do not use for new platform integration."},
        }

    def submit(self, body: dict[str, Any], headers: dict[str, str]) -> tuple[dict[str, Any], int]:
        self._authorize(headers)
        normalized = self._validate_request(body, headers)
        fingerprint = request_fingerprint(normalized)

        with self._lock:
            existing = self._find_by_idempotency_key(normalized.get("idempotency_key") or normalized["trace_id"])
            if existing:
                if existing.get("request_fingerprint") != fingerprint:
                    raise PlatformInterfaceError(
                        "trace_id_conflict",
                        "The trace_id is already associated with a different request.",
                        409,
                    )
                return self._reply(existing), 202 if existing["status"] in {"accepted", "running"} else 200

            request_id = f"req-{uuid.uuid4().hex[:16]}"
            record = {
                "request_id": request_id,
                "trace_id": normalized["trace_id"],
                "service_code": normalized["service_code"],
                "reply_mode": normalized["reply_mode"],
                "caller": normalized["caller"],
                "payload": normalized["payload"],
                "request_fingerprint": fingerprint,
                "idempotency_key": normalized.get("idempotency_key") or normalized["trace_id"],
                "status": "accepted",
                "reply_type": "acceptance_receipt",
                "progress": {"stage": "accepted", "percent": 0},
                "accepted_at": utc_now(),
                "started_at": None,
                "finished_at": None,
                "task_id": None,
                "output": None,
                "evidence": None,
                "rejection": None,
                "events": [],
            }
            self._requests[request_id] = record
            self._append_event_locked(record, "request.accepted", "请求已由执行沙箱能力接收", {})
            self._save_locked()

        if normalized["reply_mode"] == "immediate":
            self._execute(request_id)
            return self.get_request(request_id, headers, headers_already_authorized=True), 200

        receipt = self.get_request(request_id, headers, headers_already_authorized=True)
        thread = threading.Thread(target=self._execute, args=(request_id,), daemon=True)
        thread.start()
        return receipt, 202

    def submit_standard(self, envelope: dict[str, Any], headers: dict[str, str]) -> tuple[dict[str, Any], int]:
        """Company v0.3 envelope adapter. This is the preferred integration API."""
        standard = self._validate_standard_envelope(envelope)
        source_service = standard["source"]["service_code"]
        engine_id = ENGINE_BY_SOURCE.get(source_service)
        if not engine_id:
            raise PlatformInterfaceError("source_service_not_registered", "source.service_code is not registered as an L2 sandbox caller.", 403)
        service_code, expected_action = CAPABILITY_MAP[standard["capability_id"]]
        if standard["action"] != expected_action:
            raise PlatformInterfaceError("capability_action_mismatch", "action does not match the registered capability_id.", 400)
        payload = dict(standard["payload"])
        payload.setdefault("agent", source_service)
        legacy = {
            "protocol_version": PROTOCOL_VERSION, "trace_id": standard["trace_id"], "service_code": service_code,
            "reply_mode": "receipt" if standard["route_type"] == "task.dispatch" else "immediate",
            "idempotency_key": standard["idempotency_key"],
            "caller": {"layer": "business_engine", "engine_id": engine_id, "company_id": standard["actor"]["tenant_id"], "user_id": standard["actor"]["person_id"]},
            "payload": payload,
        }
        adapted_headers = dict(headers)
        adapted_headers.update({"x-caller-layer": "business_engine", "x-engine-id": engine_id, "x-company-id": standard["actor"]["tenant_id"], "x-trace-id": standard["trace_id"]})
        reply, status = self.submit(legacy, adapted_headers)
        with self._lock:
            record = self._requests.get(reply["request_id"])
            if record:
                record["standard_envelope"] = deepcopy(standard)
                self._save_locked()
        return self._standard_reply(standard, reply), status

    def get_standard_request(self, request_id: str, headers: dict[str, str]) -> dict[str, Any]:
        reply = self.get_request(request_id, headers)
        with self._lock:
            record = deepcopy(self._requests[request_id])
        meta = record.get("standard_envelope", {})
        if not meta:
            raise PlatformInterfaceError("standard_message_not_found", "Request was not created through the standard message interface.", 404)
        return self._standard_reply(meta, reply)

    def get_request(
        self,
        request_id: str,
        headers: dict[str, str],
        headers_already_authorized: bool = False,
    ) -> dict[str, Any]:
        if not headers_already_authorized:
            self._authorize(headers)
        with self._lock:
            record = self._requests.get(request_id)
            if not record:
                raise PlatformInterfaceError("request_not_found", "Platform request was not found.", 404)
            self._authorize_record_owner(record, headers)
            return self._reply(record)

    def get_events(self, request_id: str, headers: dict[str, str]) -> dict[str, Any]:
        self._authorize(headers)
        with self._lock:
            record = self._requests.get(request_id)
            if not record:
                raise PlatformInterfaceError("request_not_found", "Platform request was not found.", 404)
            self._authorize_record_owner(record, headers)
            return {
                "protocol_version": PROTOCOL_VERSION,
                "trace_id": record["trace_id"],
                "request_id": request_id,
                "status": record["status"],
                "progress": deepcopy(record["progress"]),
                "events": deepcopy(record["events"]),
            }

    def _authorize(self, headers: dict[str, str]) -> None:
        if not self.api_token:
            raise PlatformInterfaceError(
                "platform_interface_not_configured",
                "Platform API token is not configured.",
                503,
            )
        authorization = headers.get("authorization", "")
        expected = f"Bearer {self.api_token}"
        if not hmac.compare_digest(authorization, expected):
            raise PlatformInterfaceError("invalid_platform_token", "Platform token is missing or invalid.", 401)
        layer = headers.get("x-caller-layer", "")
        if layer != self.allowed_layer:
            raise PlatformInterfaceError(
                "caller_layer_not_allowed",
                "Execution sandbox only accepts requests from the business engine layer.",
                403,
                {"received_layer": layer, "allowed_layer": self.allowed_layer},
            )
        engine_id = headers.get("x-engine-id", "")
        if engine_id not in self.allowed_engines:
            raise PlatformInterfaceError(
                "engine_not_registered",
                "Calling engine is not present in the layer-interface allowlist.",
                403,
                {"engine_id": engine_id},
            )

    def _authorize_record_owner(self, record: dict[str, Any], headers: dict[str, str]) -> None:
        if record.get("caller", {}).get("engine_id") != headers.get("x-engine-id"):
            raise PlatformInterfaceError(
                "request_owner_mismatch",
                "The request belongs to a different business engine.",
                403,
            )
        if record.get("caller", {}).get("company_id") != headers.get("x-company-id"):
            raise PlatformInterfaceError("tenant_scope_mismatch", "The request belongs to a different company scope.", 403)

    def _validate_request(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        if body.get("protocol_version") != PROTOCOL_VERSION:
            raise PlatformInterfaceError("unsupported_protocol_version", "protocol_version must be 1.0.")
        trace_id = require_string(body, "trace_id", 128)
        header_trace = headers.get("x-trace-id", "")
        if trace_id != header_trace:
            raise PlatformInterfaceError(
                "trace_id_mismatch",
                "X-Trace-Id must match body.trace_id.",
                400,
            )
        service_code = require_string(body, "service_code", 128)
        if service_code not in {SERVICE_CODE, CODE_SERVICE_CODE, BROWSER_SERVICE_CODE}:
            raise PlatformInterfaceError(
                "service_not_registered",
                "Requested service is not registered by this capability package.",
                404,
                {"service_code": service_code},
            )
        reply_mode = require_string(body, "reply_mode", 32)
        if reply_mode not in {"immediate", "receipt"}:
            raise PlatformInterfaceError("invalid_reply_mode", "reply_mode must be immediate or receipt.")

        caller = require_object(body, "caller")
        caller_layer = require_string(caller, "layer", 64)
        engine_id = require_string(caller, "engine_id", 128)
        company_id = require_string(caller, "company_id", 128)
        user_id = require_string(caller, "user_id", 128)
        if caller_layer != headers.get("x-caller-layer") or engine_id != headers.get("x-engine-id"):
            raise PlatformInterfaceError(
                "caller_header_mismatch",
                "Caller identity in headers and request body must match.",
                400,
            )
        if company_id != headers.get("x-company-id"):
            raise PlatformInterfaceError("tenant_scope_mismatch", "X-Company-Id must match caller.company_id.", 400)
        resolved_user = self.service.mock_platform.account.resolve_actor(user_id)
        if resolved_user.get("actor") != user_id:
            raise PlatformInterfaceError(
                "identity_not_resolved",
                "Calling user is not known by the current account gateway.",
                403,
                {"user_id": user_id},
            )

        payload = require_object(body, "payload")
        agent = require_string(payload, "agent", 128)
        task_input = payload.get("input", {})
        if not isinstance(task_input, dict):
            raise PlatformInterfaceError("invalid_input", "payload.input must be a JSON object.")
        limits = require_object(payload, "limits")
        timeout_seconds = require_number(limits, "timeout_seconds", 1, 300)
        memory_mb = require_number(limits, "memory_mb", 64, 4096)
        cpu_cores = require_number(limits, "cpu_cores", 0.1, 8)

        normalized_payload: dict[str, Any] = {
            "agent": agent, "limits": {"timeout_seconds": int(timeout_seconds), "memory_mb": int(memory_mb), "cpu_cores": float(cpu_cores)}, "input": task_input, "retain_snapshot": bool(payload.get("retain_snapshot", False)),
        }
        if service_code == SERVICE_CODE:
            scenario_id = require_string(payload, "scenario_id", 128)
            scenario_ids = {str(item.get("id")) for item in self.service.list_scenarios()}
            if scenario_id not in scenario_ids:
                raise PlatformInterfaceError("scenario_not_registered", "Requested scenario is not registered in the execution sandbox service catalog.", 404, {"scenario_id": scenario_id})
            normalized_payload["scenario_id"] = scenario_id
        elif service_code == CODE_SERVICE_CODE:
            code = require_string(payload, "code", 120000)
            if str(payload.get("language", "python")).lower() != "python":
                raise PlatformInterfaceError("language_not_supported", "Only Python generated code is currently supported.", 400)
            normalized_payload.update({"code": code, "language": "python"})
        else:
            url = require_string(payload, "url", 2048)
            from urllib.parse import urlparse
            parsed = urlparse(url)
            allowed = set(self.service.config.get("egress_policy", {}).get("allowed_domains", []))
            if parsed.scheme not in {"http", "https"} or (parsed.hostname or "") not in allowed:
                raise PlatformInterfaceError("url_not_allowlisted", "Browser URL must be an HTTP(S) URL on the approved allowlist.", 403)
            normalized_payload["url"] = url
        return {
            "protocol_version": PROTOCOL_VERSION,
            "trace_id": trace_id,
            "service_code": service_code,
            "reply_mode": reply_mode,
            "caller": {
                "layer": caller_layer,
                "engine_id": engine_id,
                "company_id": company_id,
                "user_id": user_id,
            },
            "payload": normalized_payload,
            "idempotency_key": body.get("idempotency_key"),
        }

    def _validate_standard_envelope(self, body: dict[str, Any]) -> dict[str, Any]:
        required = ["protocol_version", "message_id", "trace_id", "request_id", "source", "target", "channel", "route_type", "action", "capability_id", "capability_dictionary_version", "registry_version", "actor", "context", "idempotency_key", "deadline_at", "payload"]
        for key in required:
            if key not in body:
                raise PlatformInterfaceError("missing_required_field", f"{key} is required by the platform communication specification.")
        if body["protocol_version"] != PROTOCOL_VERSION:
            raise PlatformInterfaceError("unsupported_protocol_version", "protocol_version must be 1.0.")
        source, target, actor, context = (require_object(body, key) for key in ("source", "target", "actor", "context"))
        if require_string(source, "layer", 8) != "L2" or require_string(target, "layer", 8) != "L1":
            raise PlatformInterfaceError("layer_route_not_allowed", "Execution sandbox only accepts L2 to L1 standard messages.", 403)
        if require_string(target, "service_code", 128) != "l1.execution_sandbox":
            raise PlatformInterfaceError("target_service_mismatch", "target.service_code must be l1.execution_sandbox.", 400)
        capability_id = require_string(body, "capability_id", 128)
        if capability_id not in CAPABILITY_MAP:
            raise PlatformInterfaceError("capability_not_registered", "capability_id is not registered by the execution sandbox.", 404)
        if require_string(body, "route_type", 64) != "task.dispatch":
            raise PlatformInterfaceError("route_type_not_allowed", "Execution sandbox accepts task.dispatch only.", 400)
        if not isinstance(body["payload"], dict):
            raise PlatformInterfaceError("invalid_payload", "payload must be a JSON object.")
        deadline = require_string(body, "deadline_at", 64)
        try:
            datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlatformInterfaceError("invalid_deadline", "deadline_at must be ISO-8601.") from exc
        return {"protocol_version": PROTOCOL_VERSION, "message_id": require_string(body, "message_id", 128), "trace_id": require_string(body, "trace_id", 128), "request_id": require_string(body, "request_id", 128), "parent_message_id": body.get("parent_message_id"), "source": {"layer": "L2", "service_code": require_string(source, "service_code", 128)}, "target": {"layer": "L1", "service_code": "l1.execution_sandbox"}, "channel": require_string(body, "channel", 64), "route_type": "task.dispatch", "action": require_string(body, "action", 128), "capability_id": capability_id, "capability_dictionary_version": require_string(body, "capability_dictionary_version", 128), "registry_version": require_string(body, "registry_version", 128), "actor": {"person_id": require_string(actor, "person_id", 128), "tenant_id": require_string(actor, "tenant_id", 128)}, "context": context, "idempotency_key": require_string(body, "idempotency_key", 256), "deadline_at": deadline, "payload": body["payload"]}

    def _standard_reply(self, message: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
        state = reply.get("status")
        reply_type = "accepted" if state in {"accepted", "running"} else "success" if state == "succeeded" else "failed"
        result = {"protocol_version": PROTOCOL_VERSION, "message_id": f"msg-{uuid.uuid4().hex[:16]}", "parent_message_id": message["message_id"], "trace_id": message["trace_id"], "request_id": reply["request_id"], "source": {"layer": "L1", "service_code": "l1.execution_sandbox"}, "target": message["source"], "channel": message["channel"], "route_type": "flow.callback", "reply_type": reply_type, "context": message["context"]}
        if reply_type == "accepted": result["data"] = {"task_id": reply.get("request_id"), "status": state, "query": f"{STANDARD_PATH}/{reply['request_id']}"}
        elif reply_type == "success": result["data"] = reply.get("output", {}); result["evidence"] = reply.get("evidence", {})
        else: result["error"] = reply.get("reason") or reply.get("output", {"code": "sandbox_execution_failed"}); result["retryable"] = state in {"failed", "timeout"}
        return result

    def _execute(self, request_id: str) -> None:
        with self._lock:
            record = self._requests.get(request_id)
            if not record:
                return
            record["status"] = "running"
            record["started_at"] = utc_now()
            record["progress"] = {"stage": "running", "percent": 5}
            self._append_event_locked(record, "request.started", "执行沙箱开始处理请求", {})
            self._save_locked()
            caller = deepcopy(record["caller"])
            payload = deepcopy(record["payload"])
            trace_id = record["trace_id"]

        def progress(kind: str, detail: str, data: dict[str, Any]) -> None:
            percent_by_kind = {
                "task.accepted": 10,
                "identity.resolved": 20,
                "permission.checked": 30,
                "sandbox.preparing": 45,
                "sandbox.result_collected": 85,
                "task.finished": 100,
            }
            with self._lock:
                current = self._requests.get(request_id)
                if not current:
                    return
                current["progress"] = {
                    "stage": kind,
                    "percent": percent_by_kind.get(kind, current["progress"].get("percent", 5)),
                }
                self._append_event_locked(current, kind, detail, data)
                self._save_locked()

        limits = payload["limits"]
        task_payload = {
            "actor": caller["user_id"],
            "agent": payload["agent"],
            "timeout_seconds": limits["timeout_seconds"],
            "memory_mb": limits["memory_mb"],
            "cpu_cores": limits["cpu_cores"],
            "input": payload["input"],
            "trace_id": trace_id,
            "caller": caller,
            "retain_snapshot": payload.get("retain_snapshot", False),
        }

        try:
            if record["service_code"] == CODE_SERVICE_CODE:
                task_payload.update({"code": payload["code"]})
                task = self.service.create_code_task(task_payload, progress=progress)
            elif record["service_code"] == BROWSER_SERVICE_CODE:
                task_payload.update({"url": payload["url"]})
                task = self.service.create_browser_task(task_payload, progress=progress)
            else:
                task_payload["scenario_id"] = payload["scenario_id"]
                task = self.service.create_task(task_payload, progress=progress)
            self._finish_from_task(request_id, task)
        except Exception as exc:
            with self._lock:
                record = self._requests.get(request_id)
                if not record:
                    return
                record["status"] = "failed"
                record["reply_type"] = "result"
                record["finished_at"] = utc_now()
                record["progress"] = {"stage": "failed", "percent": 100}
                record["output"] = {"status": "failed", "error": str(exc)}
                self._append_event_locked(record, "request.failed", "请求处理失败", {"error": str(exc)})
                self._save_locked()

    def _finish_from_task(self, request_id: str, task: dict[str, Any]) -> None:
        task_status = str(task.get("status", "failed"))
        status_map = {
            "success": "succeeded",
            "denied": "rejected",
            "failed": "failed",
            "timeout": "timeout",
        }
        terminal_status = status_map.get(task_status, "failed")
        result = task.get("result") or {}
        runtime = result.get("sandbox_runtime", {}) if isinstance(result, dict) else {}
        output = {
            "task_id": task.get("id"),
            "status": task_status,
            "business_result": result.get("payload") if isinstance(result, dict) else None,
            "result_files": result.get("files", []) if isinstance(result, dict) else [],
            "duration_ms": task.get("duration_ms"),
        }
        evidence = {
            "executor": task.get("executor"),
            "runtime": runtime,
            "limits": task.get("limits", {}),
            "logs": task.get("logs", []),
            "platform_checks": task.get("platform_checks", {}),
            "snapshot": task.get("snapshot"),
        }
        with self._lock:
            record = self._requests.get(request_id)
            if not record:
                return
            record["status"] = terminal_status
            record["reply_type"] = "rejection" if task_status == "denied" else "result"
            record["finished_at"] = utc_now()
            record["progress"] = {"stage": "finished", "percent": 100}
            record["task_id"] = task.get("id")
            record["output"] = output
            record["evidence"] = evidence
            if task_status == "denied":
                security = task.get("platform_checks", {}).get("security_compliance", {})
                record["rejection"] = {
                    "code": "permission_denied",
                    "message": result.get("error", "Permission precheck denied."),
                    "missing_permissions": security.get("missing_permissions", []),
                    "sandbox_started": False,
                }
                self._append_event_locked(record, "request.rejected", "权限预检拒绝，未创建 Docker 容器", record["rejection"])
            else:
                self._append_event_locked(
                    record,
                    "request.finished",
                    "执行沙箱请求处理完成",
                    {"task_id": task.get("id"), "task_status": task_status},
                )
            self._trim_locked()
            self._save_locked()

    def _reply(self, record: dict[str, Any]) -> dict[str, Any]:
        reply = {
            "protocol_version": PROTOCOL_VERSION,
            "trace_id": record["trace_id"],
            "request_id": record["request_id"],
            "service_code": record["service_code"],
            "reply_type": record["reply_type"],
            "status": record["status"],
            "progress": deepcopy(record["progress"]),
            "accepted_at": record["accepted_at"],
            "started_at": record["started_at"],
            "finished_at": record["finished_at"],
            "links": {
                "self": f"/api/v1/layer-interface/requests/{record['request_id']}",
                "events": f"/api/v1/layer-interface/requests/{record['request_id']}/events",
            },
        }
        if record.get("output") is not None:
            reply["output"] = deepcopy(record["output"])
        if record.get("evidence") is not None:
            reply["evidence"] = deepcopy(record["evidence"])
        if record.get("rejection") is not None:
            reply["reason"] = deepcopy(record["rejection"])
        return reply

    def _append_event_locked(
        self,
        record: dict[str, Any],
        kind: str,
        detail: str,
        data: dict[str, Any],
    ) -> None:
        record["events"].append(
            {
                "seq": len(record["events"]) + 1,
                "at": utc_now(),
                "kind": kind,
                "detail": detail,
                "data": data,
            }
        )

    def _find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        return next((item for item in self._requests.values() if item.get("idempotency_key") == key), None)

    def _load(self) -> dict[str, dict[str, Any]]:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_file.exists():
            return {}
        try:
            records = json.loads(self.data_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {
            str(item["request_id"]): item
            for item in records
            if isinstance(item, dict) and item.get("request_id")
        }

    def _recover_incomplete_requests(self) -> None:
        changed = False
        with self._lock:
            for record in self._requests.values():
                if record.get("status") not in {"accepted", "running"}:
                    continue
                record["status"] = "failed"
                record["reply_type"] = "result"
                record["finished_at"] = utc_now()
                record["progress"] = {"stage": "failed", "percent": 100}
                record["output"] = {
                    "status": "failed",
                    "error": "service_restarted_before_completion",
                }
                self._append_event_locked(
                    record,
                    "request.failed",
                    "服务重启前请求未完成，已终止本次记录",
                    {"reason": "service_restarted_before_completion"},
                )
                changed = True
            if changed:
                self._save_locked()

    def _trim_locked(self) -> None:
        if len(self._requests) <= self.max_records:
            return
        terminal = sorted(
            (
                item
                for item in self._requests.values()
                if item.get("status") in {"succeeded", "rejected", "failed", "timeout"}
            ),
            key=lambda item: item.get("accepted_at", ""),
        )
        for item in terminal[: max(0, len(self._requests) - self.max_records)]:
            self._requests.pop(item["request_id"], None)

    def _save_locked(self) -> None:
        tmp = self.data_file.with_suffix(".json.tmp")
        payload = sorted(self._requests.values(), key=lambda item: item.get("accepted_at", ""))
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.data_file)


def require_string(source: dict[str, Any], key: str, max_length: int) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlatformInterfaceError("missing_required_field", f"{key} must be a non-empty string.")
    value = value.strip()
    if len(value) > max_length:
        raise PlatformInterfaceError("field_too_long", f"{key} exceeds {max_length} characters.")
    return value


def require_object(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise PlatformInterfaceError("missing_required_field", f"{key} must be a JSON object.")
    return value


def require_number(source: dict[str, Any], key: str, minimum: float, maximum: float) -> float:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlatformInterfaceError("invalid_limit", f"{key} must be a number.")
    number = float(value)
    if number < minimum or number > maximum:
        raise PlatformInterfaceError(
            "invalid_limit",
            f"{key} must be between {minimum} and {maximum}.",
        )
    return number


def request_fingerprint(request: dict[str, Any]) -> str:
    raw = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
