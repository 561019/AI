from __future__ import annotations

import json
import os
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from api.api_response import error_response, success_response
from adapters.adapter_registry import get_adapter_status
from adapters.mock_security_compliance import (
    inspect_input,
    inspect_output,
)
from adapters.mock_workflow_callback import publish_callback
from api.layer_message_adapter import process_layer_message
from api.api_validation import (
    build_register_subtask,
    validate_monitor_item_request,
    validate_monitor_item_status_request,
    validate_monitor_item_update_request,
    validate_reminder_action_request,
    validate_reminder_trigger_request,
)
from api.permission_adapter import check_permission
from api.monitor_item_adapter import (
    change_monitor_item_status,
    modify_monitor_item,
    query_monitor_item,
    query_monitor_items,
)
from api.reminder_action_adapter import (
    confirm_reminder,
    escalate_reminder,
    recover_reminder,
)
from api.reminder_service_adapter import (
    process_reminder_trigger,
)
from db import init_db
from repositories.audit_repository import (
    list_api_audits,
    write_api_audit,
)
from repositories.trace_repository import (
    database_connected,
    database_exists,
    read_trace_records,
)
from service_register import create_monitor_item


HOST = os.environ.get("MONITORING_REMINDER_HOST", "127.0.0.1")
PORT = int(os.environ.get("MONITORING_REMINDER_PORT", "8009"))
API_VERSION = "v0.8-final"
MAX_BODY_BYTES = 1024 * 1024


def encode_json(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def parse_int_query(
    query: dict[str, list[str]],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = query.get(name, [str(default)])[0]

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc

    if value < minimum or value > maximum:
        raise ValueError(
            f"{name} 必须在 {minimum} 到 {maximum} 之间"
        )

    return value


class MonitorReminderAPIHandler(BaseHTTPRequestHandler):

    server_version = "MonitorReminderAPI/0.8-stage4"

    def begin_request(self) -> None:
        self._request_started = time.perf_counter()
        self._audit_enabled = True
        self._header_source_module = self.headers.get(
            "X-Source-Module",
            "",
        ).strip()
        self._header_operator_id = self.headers.get(
            "X-Operator-ID",
            "",
        ).strip()
        self._permission_token = self.headers.get(
            "X-Permission-Token",
            "",
        ).strip()
        self._audit_context = {
            "request_id": (
                self.headers.get("X-Request-ID", "").strip()
                or f"AUTO_{uuid4().hex[:16].upper()}"
            ),
            "trace_id": "",
            "source_module": (
                self._header_source_module or "anonymous"
            ),
            "operator_id": self._header_operator_id,
            "permission_name": "",
            "permission_mode": "",
            "permission_allowed": None,
            "permission_decision_id": "",
            "security_audit_ref": "",
        }

    def update_audit_context(
        self,
        data: dict[str, Any],
    ) -> None:
        for field in ("request_id", "trace_id"):
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                self._audit_context[field] = value.strip()

        # 请求头是权限识别的主来源；仅在请求头缺失时，
        # 将请求体模块和操作人用于审计展示，权限仍会拒绝。
        if not self._header_source_module:
            value = data.get("source_module")
            if isinstance(value, str) and value.strip():
                self._audit_context["source_module"] = value.strip()

        if not self._header_operator_id:
            value = data.get("operator_id")
            if isinstance(value, str) and value.strip():
                self._audit_context["operator_id"] = value.strip()

    def write_audit_safely(
        self,
        status_code: int,
        response_data: dict[str, Any],
    ) -> None:
        if not getattr(self, "_audit_enabled", False):
            return

        duration_ms = int(
            (
                time.perf_counter()
                - getattr(
                    self,
                    "_request_started",
                    time.perf_counter(),
                )
            )
            * 1000
        )

        response_payload = response_data.get("data", {})
        business_status = ""
        if isinstance(response_payload, dict):
            business_status = str(
                response_payload.get(
                    "business_status",
                    "",
                )
            )

        if not business_status:
            business_status = (
                "处理成功" if status_code < 400 else "处理失败"
            )

        error_message = ""
        if status_code >= 400:
            error_message = str(
                response_data.get("message", "")
            )

        try:
            write_api_audit(
                request_id=self._audit_context["request_id"],
                trace_id=self._audit_context["trace_id"],
                source_module=self._audit_context[
                    "source_module"
                ],
                operator_id=self._audit_context["operator_id"],
                request_method=self.command,
                request_path=urlparse(self.path).path,
                response_code=status_code,
                business_status=business_status,
                error_message=error_message,
                permission_name=self._audit_context[
                    "permission_name"
                ],
                permission_mode=self._audit_context[
                    "permission_mode"
                ],
                permission_allowed=self._audit_context[
                    "permission_allowed"
                ],
                permission_decision_id=self._audit_context.get(
                    "permission_decision_id",
                    "",
                ),
                security_audit_ref=self._audit_context.get(
                    "security_audit_ref",
                    "",
                ),
                duration_ms=duration_ms,
                client_ip=self.client_address[0],
            )
        except Exception:
            print("[AUDIT] 接口审计写入失败：")
            traceback.print_exc()

    def mark_public_permission(self, name: str) -> None:
        self._audit_context["permission_name"] = name
        self._audit_context["permission_mode"] = "public"
        self._audit_context["permission_allowed"] = 1
        self._audit_context["permission_decision_id"] = "public"

    def require_permission(
        self,
        required_permission: str,
        request_data: dict[str, Any] | None = None,
    ) -> bool:
        body_source_module = ""
        body_operator_id = ""

        if isinstance(request_data, dict):
            body_source_module = str(
                request_data.get("source_module", "")
            ).strip()
            body_operator_id = str(
                request_data.get("operator_id", "")
            ).strip()

        result = check_permission(
            source_module=self._header_source_module,
            operator_id=self._header_operator_id,
            permission_token=self._permission_token,
            required_permission=required_permission,
            body_source_module=body_source_module,
            body_operator_id=body_operator_id,
        )

        self._audit_context["permission_name"] = (
            required_permission
        )
        self._audit_context["permission_mode"] = result["mode"]
        self._audit_context["permission_allowed"] = (
            1 if result["allowed"] else 0
        )
        self._audit_context["permission_decision_id"] = result.get(
            "decision_id",
            "",
        )
        self._last_permission_result = result

        if result["allowed"]:
            return True

        self.send_json(
            403,
            error_response(
                code="MONITOR_PERMISSION_4031",
                message=result["reason"],
                request_id=self._audit_context["request_id"],
                trace_id=self._audit_context["trace_id"],
                data={
                    "business_status": "无权限",
                    **result,
                },
            ),
        )
        return False

    def send_json(
        self,
        status_code: int,
        data: dict[str, Any],
        *,
        audit: bool = True,
    ) -> None:
        security_result = inspect_output(
            data,
            action=f"{self.command} {urlparse(self.path).path}",
            trace_id=self._audit_context.get("trace_id", ""),
        )
        self._audit_context["security_audit_ref"] = security_result.get(
            "audit_ref",
            self._audit_context.get("security_audit_ref", ""),
        )
        data = security_result.get("sanitized_payload", data)

        if audit:
            self.write_audit_safely(
                status_code,
                data,
            )

        body = encode_json(data)

        self.send_response(status_code)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            (
                "Content-Type, X-Request-ID, "
                "X-Source-Module, X-Operator-ID, "
                "X-Permission-Token"
            ),
        )
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            raise ValueError(
                "Content-Type 必须为 application/json"
            )

        try:
            content_length = int(
                self.headers.get("Content-Length", "0")
            )
        except ValueError as exc:
            raise ValueError("Content-Length 不合法") from exc

        if content_length <= 0:
            raise ValueError("请求体不能为空")

        if content_length > MAX_BODY_BYTES:
            raise ValueError("请求体过大，最大允许 1 MB")

        raw_body = self.rfile.read(content_length)

        try:
            decoded = raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("请求体必须使用 UTF-8 编码") from exc

        try:
            data = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON 格式错误：第 {exc.lineno} 行"
                f"第 {exc.colno} 列"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")

        security_result = inspect_input(
            data,
            action=f"{self.command} {urlparse(self.path).path}",
            trace_id=str(data.get("trace_id", "")),
        )
        self._audit_context["security_audit_ref"] = security_result.get(
            "audit_ref",
            "",
        )
        if not security_result.get("allowed", False):
            violations = security_result.get("violations", [])
            raise ValueError(
                "安全合规检查未通过："
                + "、".join(str(item) for item in violations)
            )
        data = security_result.get("sanitized_payload", data)

        self.update_audit_context(data)
        return data

    def do_OPTIONS(self) -> None:
        self.begin_request()
        self._audit_enabled = False
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            (
                "Content-Type, X-Request-ID, "
                "X-Source-Module, X-Operator-ID, "
                "X-Permission-Token"
            ),
        )
        self.end_headers()

    def do_GET(self) -> None:
        self.begin_request()

        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            query = parse_qs(parsed.query)

            if path in ("", "/"):
                self.mark_public_permission("public:api-info")
                self.send_json(
                    200,
                    success_response(
                        request_id=self._audit_context[
                            "request_id"
                        ],
                        data={
                            "engine": "monitor_reminder_engine",
                            "api_version": API_VERSION,
                            "available_endpoints": [
                                "GET /api/v1/health",
                                "GET /api/v1/capabilities",
                                "GET /api/v1/adapters/status",
                                "POST /api/v1/l2/internal/messages",
                                "POST /api/v1/l2/internal/messages（v0.8统一层内入口）",
                "POST /api/v1/monitor-items（legacy_mock_only）",
                                "GET /api/v1/monitor-items",
                                "GET /api/v1/monitor-items/{item_id}",
                                "PUT /api/v1/monitor-items/{item_id}",
                                "POST /api/v1/monitor-items/{item_id}/enable",
                                "POST /api/v1/monitor-items/{item_id}/pause",
                                "POST /api/v1/monitor-items/{item_id}/resume",
                                "POST /api/v1/monitor-items/{item_id}/disable",
                                "POST /api/v1/reminders/trigger",
                                "POST /api/v1/reminders/{id}/escalate",
                                "POST /api/v1/reminders/{id}/confirm",
                                "POST /api/v1/reminders/{id}/recover",
                                "GET /api/v1/traces/{trace_id}",
                                "GET /api/v1/audit-records",
                            ],
                        },
                        message="监控提醒引擎 API 服务",
                    ),
                )
                return

            if path == "/favicon.ico":
                self._audit_enabled = False
                self.send_response(204)
                self.end_headers()
                return

            if path == "/api/v1/health":
                self.mark_public_permission("public:health")
                self.handle_health()
                return

            if path == "/api/v1/capabilities":
                self.handle_capabilities()
                return

            if path == "/api/v1/adapters/status":
                self.handle_adapter_status()
                return

            if path == "/api/v1/monitor-items":
                self.handle_list_monitor_items(query)
                return

            if path == "/api/v1/audit-records":
                self.handle_list_audits(query)
                return

            item_prefix = "/api/v1/monitor-items/"
            if path.startswith(item_prefix):
                item_id = unquote(
                    path[len(item_prefix):]
                ).strip()
                self.handle_get_monitor_item(item_id)
                return

            trace_prefix = "/api/v1/traces/"
            if path.startswith(trace_prefix):
                trace_id = unquote(
                    path[len(trace_prefix):]
                ).strip()
                self._audit_context["trace_id"] = trace_id
                self.handle_trace_query(trace_id)
                return

            self.send_json(
                404,
                error_response(
                    code="MONITOR_API_404",
                    message="接口不存在",
                    request_id=self._audit_context[
                        "request_id"
                    ],
                ),
            )

        except ValueError as exc:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_API_400",
                    message=str(exc),
                    request_id=self._audit_context[
                        "request_id"
                    ],
                ),
            )

        except Exception as exc:
            traceback.print_exc()
            self.send_json(
                500,
                error_response(
                    code="MONITOR_API_500",
                    message=f"接口处理失败：{exc}",
                    request_id=self._audit_context[
                        "request_id"
                    ],
                    trace_id=self._audit_context[
                        "trace_id"
                    ],
                ),
            )

    def do_POST(self) -> None:
        self.begin_request()

        try:
            path = urlparse(self.path).path.rstrip("/")

            if path == "/api/v1/l2/internal/messages":
                self.handle_layer_message()
                return

            if path == "/api/v1/monitor-items":
                self.handle_create_monitor_item()
                return

            if path == "/api/v1/reminders/trigger":
                self.handle_reminder_trigger()
                return

            monitor_status_route = (
                self.parse_monitor_status_route(path)
            )
            if monitor_status_route is not None:
                item_id, action = monitor_status_route
                self.handle_monitor_status_action(
                    item_id,
                    action,
                )
                return

            action_route = self.parse_reminder_action_route(
                path
            )
            if action_route is not None:
                reminder_id, action = action_route
                self.handle_reminder_action(
                    reminder_id,
                    action,
                )
                return

            self.send_json(
                404,
                error_response(
                    code="MONITOR_API_404",
                    message="接口不存在",
                    request_id=self._audit_context[
                        "request_id"
                    ],
                ),
            )

        except ValueError as exc:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_API_400",
                    message=str(exc),
                    request_id=self._audit_context[
                        "request_id"
                    ],
                    trace_id=self._audit_context[
                        "trace_id"
                    ],
                ),
            )

        except Exception as exc:
            traceback.print_exc()
            self.send_json(
                500,
                error_response(
                    code="MONITOR_API_500",
                    message=f"接口处理失败：{exc}",
                    request_id=self._audit_context[
                        "request_id"
                    ],
                    trace_id=self._audit_context[
                        "trace_id"
                    ],
                ),
            )

    def do_PUT(self) -> None:
        self.begin_request()

        try:
            path = urlparse(self.path).path.rstrip("/")
            item_prefix = "/api/v1/monitor-items/"

            if not path.startswith(item_prefix):
                self.send_json(
                    404,
                    error_response(
                        code="MONITOR_API_404",
                        message="接口不存在",
                        request_id=self._audit_context[
                            "request_id"
                        ],
                    ),
                )
                return

            item_id = unquote(
                path[len(item_prefix):]
            ).strip()

            if not item_id or "/" in item_id:
                raise ValueError("item_id 路径参数不合法")

            self.handle_update_monitor_item(item_id)

        except ValueError as exc:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_API_400",
                    message=str(exc),
                    request_id=self._audit_context[
                        "request_id"
                    ],
                    trace_id=self._audit_context[
                        "trace_id"
                    ],
                ),
            )

        except Exception as exc:
            traceback.print_exc()
            self.send_json(
                500,
                error_response(
                    code="MONITOR_API_500",
                    message=f"接口处理失败：{exc}",
                    request_id=self._audit_context[
                        "request_id"
                    ],
                    trace_id=self._audit_context[
                        "trace_id"
                    ],
                ),
            )

    @staticmethod
    def parse_reminder_action_route(
        path: str,
    ) -> tuple[int, str] | None:
        parts = path.strip("/").split("/")

        if len(parts) != 5:
            return None

        if parts[:3] != ["api", "v1", "reminders"]:
            return None

        action = parts[4]
        if action not in ("confirm", "recover", "escalate"):
            return None

        try:
            reminder_id = int(parts[3])
        except ValueError as exc:
            raise ValueError(
                "reminder_id 必须是整数"
            ) from exc

        if reminder_id <= 0:
            raise ValueError("reminder_id 必须大于 0")

        return reminder_id, action

    @staticmethod
    def parse_monitor_status_route(
        path: str,
    ) -> tuple[str, str] | None:
        parts = path.strip("/").split("/")

        if len(parts) != 5:
            return None

        if parts[:3] != ["api", "v1", "monitor-items"]:
            return None

        action = parts[4]
        if action not in ("enable", "pause", "resume", "disable"):
            return None

        item_id = unquote(parts[3]).strip()
        if not item_id:
            raise ValueError("item_id 不能为空")

        return item_id, action

    def handle_layer_message(self) -> None:
        envelope = self.read_json_body()
        source = envelope.get("source", {})
        actor = envelope.get("actor", {})

        if isinstance(source, dict):
            self._audit_context["source_module"] = str(
                source.get("service_code", "")
            )
        if isinstance(actor, dict):
            self._audit_context["operator_id"] = str(
                actor.get("person_id", "")
            )
        self._audit_context["request_id"] = str(
            envelope.get("request_id", self._audit_context["request_id"])
        )
        self._audit_context["trace_id"] = str(
            envelope.get("trace_id", "")
        )

        # 本地联调阶段仍用 v0.7 Mock Token 验证调用端；
        # 正式接入后由 L2 接口控制模块完成准入和动作级判权。
        permission_request = {
            "operator_id": actor.get("person_id", "")
            if isinstance(actor, dict)
            else ""
        }
        if not self.require_permission(
            "layer_message:dispatch",
            permission_request,
        ):
            return

        status_code, response = process_layer_message(envelope)
        context = envelope.get("context", {})
        result_ref = ""
        response_data = response.get("data", {})
        if isinstance(response_data, dict):
            reminder_id = response_data.get("reminder_id")
            item_id = response_data.get("item_id")
            if reminder_id:
                result_ref = f"mock://l1.7/reminder_record/{reminder_id}"
            elif item_id:
                result_ref = f"mock://l1.7/monitor_item/{item_id}"

        callback_result = publish_callback(
            trace_id=str(envelope.get("trace_id", "")),
            workflow_instance_id=str(
                context.get("workflow_instance_id", "")
            ),
            node_id=str(context.get("node_id", "")),
            task_id=str(context.get("task_id", "")),
            reply_type=str(response.get("reply_type", "")),
            status=str(response.get("status", "")),
            result_ref=result_ref,
            error_code=str(
                response.get("error", {}).get("code", "")
                if isinstance(response.get("error"), dict)
                else ""
            ),
        )

        evidence = {
            "permission_decision_id": (
                getattr(self, "_last_permission_result", {}) or {}
            ).get("decision_id", ""),
            "permission_obligations": (
                getattr(self, "_last_permission_result", {}) or {}
            ).get("obligations", []),
            "security_audit_ref": self._audit_context.get(
                "security_audit_ref",
                "",
            ),
            "workflow_callback": callback_result,
        }
        if isinstance(response_data, dict):
            response_data["adapter_evidence"] = evidence
            response["data"] = response_data
        else:
            response["adapter_evidence"] = evidence

        self.send_json(status_code, response)

    def handle_health(self) -> None:
        self.send_json(
            200,
            success_response(
                request_id=self._audit_context[
                    "request_id"
                ],
                data={
                    "engine_name": "monitor_reminder_engine",
                    "engine_version": API_VERSION,
                    "service_status": "running",
                    "database_exists": database_exists(),
                    "database_status": (
                        "connected"
                        if database_connected()
                        else "disconnected"
                    ),
                    "running_mode": (
                        "mock_independent_validation"
                    ),
                    "audit_status": "enabled",
                    "permission_mode": "mock",
                    "permission_status": "enabled",
                    "layer_contract_status": "v0.8-final-enabled",
                    "idempotency_status": "enabled",
                    "governance_status": "stage2b-enabled",
                    "adapter_layer_status": "stage3-enabled",
                    "dashboard_integration_status": "final-enabled",
                    "external_modules": {
                        "workflow_engine": "mock_adapter",
                        "rule_engine": "mock_input",
                        "notification_channel": "mock_adapter",
                        "data_module_1_7": "mock_adapter",
                        "account_gateway_1_8": "mock_adapter",
                        "permission_module_1_1": "mock_adapter",
                        "security_module_1_9": "mock_adapter",
                    },
                },
                message="监控提醒引擎运行正常",
            ),
        )


    def handle_adapter_status(self) -> None:
        if not self.require_permission("adapter:read"):
            return

        self.send_json(
            200,
            success_response(
                request_id=self._audit_context["request_id"],
                trace_id=self._audit_context["trace_id"],
                message="基础模块 Mock 适配层状态查询成功",
                data={
                    "business_status": "已完成",
                    "engine_version": API_VERSION,
                    "adapter_mode": "mock",
                    "replaceable_without_core_change": True,
                    "adapters": get_adapter_status(),
                },
            ),
        )

    def handle_create_monitor_item(self) -> None:
        request_data = self.read_json_body()
        if not self.require_permission(
            "monitor_item:create",
            request_data,
        ):
            return
        request_id = request_data.get("request_id", "")
        trace_id = request_data.get("trace_id", "")

        validation_errors = validate_monitor_item_request(
            request_data
        )

        if validation_errors:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_ITEM_4001",
                    message="监控项登记请求校验失败",
                    request_id=request_id,
                    trace_id=trace_id,
                    data={"errors": validation_errors},
                ),
            )
            return

        service_result = create_monitor_item(
            build_register_subtask(request_data)
        )

        if service_result.get("status") == "无法办理":
            self.send_json(
                400,
                error_response(
                    code="MONITOR_ITEM_4002",
                    message=service_result.get(
                        "reason",
                        "监控项登记失败",
                    ),
                    request_id=request_id,
                    trace_id=trace_id,
                    data={
                        "business_status": "无法办理",
                        "service_result": service_result,
                    },
                ),
            )
            return

        self.send_json(
            201,
            success_response(
                request_id=request_id,
                trace_id=trace_id,
                message="监控项登记成功",
                data={
                    "business_status": service_result.get(
                        "status",
                        "已完成",
                    ),
                    "item_id": service_result.get("item_id"),
                    "source_module": request_data[
                        "source_module"
                    ],
                    "service_result": service_result,
                },
            ),
        )


    def handle_capabilities(self) -> None:
        if not self.require_permission("capability:read"):
            return

        capability_data = {
            "business_status": "已完成",
            "engine_name": "monitor_reminder_engine",
            "engine_version": API_VERSION,
            "engine_position": "AI 平台 L2 业务引擎层",
            "current_mode": "Mock 独立功能验证",
            "responsibilities": [
                "监控项登记、查询、修改、启用、暂停、恢复和停用",
                "接收流程执行引擎派发的、已包含规则判定结果的提醒办理子任务",
                "事件去重、同类合并、重复提醒间隔、免打扰和紧急例外治理",
                "固定通知模板生成",
                "按岗位获取接收人员并调用通知通道",
                "送达记录、真人确认、升级催办和恢复销记",
                "状态回报、接口审计和 trace_id 全过程追踪",
            ],
            "non_responsibilities": [
                "不负责定时调度和跨引擎流程编排",
                "不负责计算业务数值是否超过阈值",
                "不直接读取原始业务数据库",
                "不建设正式账号、组织和岗位体系",
                "不承担正式身份认证和权限策略中心职责",
                "不实现短信、邮件或企业微信底层发送通道",
                "不承担原因分析、预测和业务决策",
            ],
            "rule_boundary": {
                "input_owner": "规则计算引擎",
                "accepted_result": "judgement_result.triggered",
                "engine_recalculates_threshold": False,
                "example": (
                    "经营指标实际值 -12% 与 -10% 预警线的比较，"
                    "由规则计算引擎完成；本引擎只接收 triggered。"
                ),
            },
            "storage_boundary": {
                "current_storage": "SQLite",
                "current_database": "monitor_demo.db",
                "access_pattern": (
                    "API 层 → Adapter 业务适配层 → Repository 数据访问层 "
                    "→ SQLite"
                ),
                "future_replacement": [
                    "PostgreSQL",
                    "平台 1.7 数据接口",
                ],
            },
            "permission_boundary": {
                "current_mode": "Mock 基础模块适配",
                "identity_sources": [
                    "X-Source-Module",
                    "X-Operator-ID",
                    "X-Permission-Token",
                ],
                "future_replacement": [
                    "1.8 账号网关",
                    "1.9 安全合规模块",
                ],
                "replacement_scope": (
                    "后续只替换 permission_adapter.py，"
                    "业务服务和接口路径保持不变"
                ),
            },
            "external_dependencies": {
                "workflow_engine": "Mock，后续负责流程组织和状态接收",
                "rule_engine": "Mock，后续负责规则计算并输出判定结果",
                "notification_channel": "Mock，后续负责真实通知发送",
                "data_module_1_7": "待接入",
                "account_gateway_1_8": "待接入",
                "security_module_1_9": "待接入",
            },
            "supported_interfaces": [
                "GET /api/v1/health",
                "GET /api/v1/capabilities",
                "POST /api/v1/l2/internal/messages（v0.8统一层内入口）",
                "POST /api/v1/monitor-items（legacy_mock_only）",
                "GET /api/v1/monitor-items",
                "GET /api/v1/monitor-items/{item_id}",
                "PUT /api/v1/monitor-items/{item_id}",
                "POST /api/v1/monitor-items/{item_id}/enable",
                "POST /api/v1/monitor-items/{item_id}/pause",
                "POST /api/v1/monitor-items/{item_id}/resume",
                "POST /api/v1/monitor-items/{item_id}/disable",
                "POST /api/v1/reminders/trigger",
                "POST /api/v1/reminders/{id}/escalate",
                "POST /api/v1/reminders/{id}/confirm",
                "POST /api/v1/reminders/{id}/recover",
                "GET /api/v1/traces/{trace_id}",
                "GET /api/v1/audit-records",
            ],
            "trace_fields": [
                "request_id",
                "trace_id",
                "source_module",
                "operator_id",
                "permission_name",
                "response_code",
                "business_status",
                "duration_ms",
                "created_at",
            ],
            "verified_industrial_scenarios": [
                "需求 200：采购节点到期提醒",
                "需求 232：经营指标越限预警",
                "投诉处理三级时效监控",
            ],
            "release_statement": (
                "当前已具备独立接口调用、业务闭环、权限适配、"
                "接口审计和全过程追踪能力；仍不代表正式平台验收或上线。"
            ),
        }

        self.send_json(
            200,
            success_response(
                request_id=self._audit_context["request_id"],
                data=capability_data,
                message="监控提醒引擎能力与工程边界查询成功",
            ),
        )

    def handle_list_monitor_items(
        self,
        query: dict[str, list[str]],
    ) -> None:
        if not self.require_permission("monitor_item:read"):
            return

        status = query.get("status", [""])[0].strip()
        keyword = query.get("keyword", [""])[0].strip()
        limit = parse_int_query(
            query,
            "limit",
            100,
            1,
            500,
        )
        offset = parse_int_query(
            query,
            "offset",
            0,
            0,
            1000000,
        )

        if status and status not in ("enabled", "paused", "disabled"):
            raise ValueError(
                "status 只允许 enabled、paused 或 disabled"
            )

        result = query_monitor_items(
            status=status,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

        self.send_json(
            200,
            success_response(
                request_id=self._audit_context[
                    "request_id"
                ],
                data={
                    "business_status": "已完成",
                    **result,
                },
                message="监控项列表查询成功",
            ),
        )

    def handle_get_monitor_item(
        self,
        item_id: str,
    ) -> None:
        if not self.require_permission("monitor_item:read"):
            return

        if not item_id or "/" in item_id:
            raise ValueError("item_id 路径参数不合法")

        result = query_monitor_item(item_id)

        if result["outcome"] == "not_found":
            self.send_json(
                404,
                error_response(
                    code="MONITOR_ITEM_4041",
                    message=result["message"],
                    request_id=self._audit_context[
                        "request_id"
                    ],
                    data=result,
                ),
            )
            return

        item = result["item"]
        self._audit_context["trace_id"] = (
            item.get("trace_id", "")
        )

        self.send_json(
            200,
            success_response(
                request_id=self._audit_context[
                    "request_id"
                ],
                trace_id=item.get("trace_id", ""),
                data=result,
                message=result["message"],
            ),
        )

    def handle_update_monitor_item(
        self,
        item_id: str,
    ) -> None:
        request_data = self.read_json_body()
        if not self.require_permission(
            "monitor_item:update",
            request_data,
        ):
            return
        validation_errors = (
            validate_monitor_item_update_request(
                request_data
            )
        )

        if validation_errors:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_ITEM_4003",
                    message="监控项修改请求校验失败",
                    request_id=request_data.get(
                        "request_id",
                        "",
                    ),
                    trace_id=request_data.get(
                        "trace_id",
                        "",
                    ),
                    data={"errors": validation_errors},
                ),
            )
            return

        result = modify_monitor_item(
            item_id,
            request_data,
        )
        self.handle_monitor_management_result(
            result,
            request_data,
            success_status=200,
        )

    def handle_monitor_status_action(
        self,
        item_id: str,
        action: str,
    ) -> None:
        request_data = self.read_json_body()
        permission_by_action = {
            "enable": "monitor_item:enable",
            "pause": "monitor_item:pause",
            "resume": "monitor_item:resume",
            "disable": "monitor_item:disable",
        }
        required_permission = permission_by_action[action]
        if not self.require_permission(
            required_permission,
            request_data,
        ):
            return
        validation_errors = (
            validate_monitor_item_status_request(
                request_data
            )
        )

        if validation_errors:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_ITEM_4004",
                    message="监控项状态变更请求校验失败",
                    request_id=request_data.get(
                        "request_id",
                        "",
                    ),
                    trace_id=request_data.get(
                        "trace_id",
                        "",
                    ),
                    data={"errors": validation_errors},
                ),
            )
            return

        target_status_by_action = {
            "enable": "enabled",
            "pause": "paused",
            "resume": "enabled",
            "disable": "disabled",
        }
        target_status = target_status_by_action[action]
        request_data["status_action"] = action

        result = change_monitor_item_status(
            item_id,
            request_data,
            target_status,
        )

        self.handle_monitor_management_result(
            result,
            request_data,
            success_status=200,
        )

    def handle_monitor_management_result(
        self,
        result: dict[str, Any],
        request_data: dict[str, Any],
        *,
        success_status: int,
    ) -> None:
        outcome = result.get("outcome")

        if outcome == "not_found":
            self.send_json(
                404,
                error_response(
                    code="MONITOR_ITEM_4041",
                    message=result["message"],
                    request_id=request_data["request_id"],
                    trace_id=request_data["trace_id"],
                    data=result,
                ),
            )
            return

        if outcome == "trace_mismatch":
            self.send_json(
                409,
                error_response(
                    code="MONITOR_ITEM_4091",
                    message=result["message"],
                    request_id=request_data["request_id"],
                    trace_id=request_data["trace_id"],
                    data=result,
                ),
            )
            return

        if outcome == "invalid_transition":
            self.send_json(
                409,
                error_response(
                    code="MONITOR_ITEM_4092",
                    message=result["message"],
                    request_id=request_data["request_id"],
                    trace_id=request_data["trace_id"],
                    data=result,
                ),
            )
            return

        if outcome in ("invalid_template", "invalid_governance_policy"):
            self.send_json(
                400,
                error_response(
                    code=(
                        "MONITOR_ITEM_4005"
                        if outcome == "invalid_template"
                        else "MONITOR_ITEM_4006"
                    ),
                    message=result["message"],
                    request_id=request_data["request_id"],
                    trace_id=request_data["trace_id"],
                    data=result,
                ),
            )
            return

        self.send_json(
            success_status,
            success_response(
                request_id=request_data["request_id"],
                trace_id=request_data["trace_id"],
                message=result["message"],
                data=result,
            ),
        )

    def handle_reminder_trigger(self) -> None:
        request_data = self.read_json_body()
        if not self.require_permission(
            "reminder:trigger",
            request_data,
        ):
            return
        request_id = request_data.get("request_id", "")
        trace_id = request_data.get("trace_id", "")

        validation_errors = validate_reminder_trigger_request(
            request_data
        )

        if validation_errors:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_TRIGGER_4001",
                    message="提醒触发请求校验失败",
                    request_id=request_id,
                    trace_id=trace_id,
                    data={"errors": validation_errors},
                ),
            )
            return

        result = process_reminder_trigger(request_data)
        outcome = result.get("outcome")

        if outcome == "not_found":
            self.send_json(
                404,
                error_response(
                    code="MONITOR_TRIGGER_4041",
                    message=result["message"],
                    request_id=request_id,
                    trace_id=trace_id,
                    data=result,
                ),
            )
            return

        if outcome in ("paused", "disabled", "trace_mismatch"):
            self.send_json(
                409,
                error_response(
                    code="MONITOR_TRIGGER_4091",
                    message=result["message"],
                    request_id=request_id,
                    trace_id=trace_id,
                    data=result,
                ),
            )
            return

        if outcome == "unable_to_deliver":
            self.send_json(
                422,
                error_response(
                    code="MONITOR_TRIGGER_4221",
                    message=result["message"],
                    request_id=request_id,
                    trace_id=trace_id,
                    data=result,
                ),
            )
            return

        status_code = (
            201 if outcome == "notification_sent" else 200
        )

        self.send_json(
            status_code,
            success_response(
                request_id=request_id,
                trace_id=trace_id,
                message=result["message"],
                data=result,
            ),
        )

    def handle_reminder_action(
        self,
        reminder_id: int,
        action: str,
    ) -> None:
        request_data = self.read_json_body()
        permission_by_action = {
            "confirm": "reminder:confirm",
            "recover": "reminder:recover",
            "escalate": "reminder:escalate",
        }
        if not self.require_permission(
            permission_by_action[action],
            request_data,
        ):
            return
        request_id = request_data.get("request_id", "")
        trace_id = request_data.get("trace_id", "")

        validation_errors = validate_reminder_action_request(
            request_data,
            action,
        )

        if validation_errors:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_ACTION_4001",
                    message="提醒操作请求校验失败",
                    request_id=request_id,
                    trace_id=trace_id,
                    data={"errors": validation_errors},
                ),
            )
            return

        handlers = {
            "confirm": confirm_reminder,
            "recover": recover_reminder,
            "escalate": escalate_reminder,
        }

        result = handlers[action](
            reminder_id,
            request_data,
        )
        outcome = result.get("outcome")

        if outcome == "not_found":
            self.send_json(
                404,
                error_response(
                    code="MONITOR_ACTION_4041",
                    message=result["message"],
                    request_id=request_id,
                    trace_id=trace_id,
                    data=result,
                ),
            )
            return

        if outcome in ("trace_mismatch", "invalid_state"):
            self.send_json(
                409,
                error_response(
                    code="MONITOR_ACTION_4091",
                    message=result["message"],
                    request_id=request_id,
                    trace_id=trace_id,
                    data=result,
                ),
            )
            return

        status_code = 200
        if outcome in ("confirmed", "recovered", "escalated"):
            status_code = 201

        self.send_json(
            status_code,
            success_response(
                request_id=request_id,
                trace_id=trace_id,
                message=result["message"],
                data=result,
            ),
        )

    def handle_trace_query(self, trace_id: str) -> None:
        if not self.require_permission("trace:read"):
            return

        if not trace_id:
            self.send_json(
                400,
                error_response(
                    code="MONITOR_TRACE_4001",
                    message="trace_id 不能为空",
                    request_id=self._audit_context[
                        "request_id"
                    ],
                ),
            )
            return

        records = read_trace_records(trace_id)
        core_table_names = (
            "monitor_item",
            "reminder_record",
            "delivery_record",
            "confirm_record",
            "escalation_record",
            "recovery_record",
        )
        core_total = sum(
            len(records.get(table, []))
            for table in core_table_names
        )
        audit_total = len(
            records.get("api_request_record", [])
        )

        self.send_json(
            200,
            success_response(
                request_id=self._audit_context[
                    "request_id"
                ],
                trace_id=trace_id,
                message="全过程回查完成",
                data={
                    "business_status": "已完成",
                    "trace_id": trace_id,
                    "core_record_count": core_total,
                    "audit_record_count": audit_total,
                    "total_records": core_total + audit_total,
                    "records": records,
                },
            ),
        )

    def handle_list_audits(
        self,
        query: dict[str, list[str]],
    ) -> None:
        if not self.require_permission("audit:read"):
            return

        request_id = query.get(
            "request_id",
            [""],
        )[0].strip()
        trace_id = query.get(
            "trace_id",
            [""],
        )[0].strip()
        source_module = query.get(
            "source_module",
            [""],
        )[0].strip()
        permission_name = query.get(
            "permission_name",
            [""],
        )[0].strip()

        permission_allowed: int | None = None
        raw_permission_allowed = query.get(
            "permission_allowed",
            [""],
        )[0].strip()
        if raw_permission_allowed:
            if raw_permission_allowed not in ("0", "1"):
                raise ValueError(
                    "permission_allowed 只允许 0 或 1"
                )
            permission_allowed = int(
                raw_permission_allowed
            )

        response_code: int | None = None
        raw_response_code = query.get(
            "response_code",
            [""],
        )[0].strip()

        if raw_response_code:
            try:
                response_code = int(raw_response_code)
            except ValueError as exc:
                raise ValueError(
                    "response_code 必须是整数"
                ) from exc

        limit = parse_int_query(
            query,
            "limit",
            100,
            1,
            500,
        )
        offset = parse_int_query(
            query,
            "offset",
            0,
            0,
            1000000,
        )

        if trace_id:
            self._audit_context["trace_id"] = trace_id

        result = list_api_audits(
            request_id=request_id,
            trace_id=trace_id,
            source_module=source_module,
            response_code=response_code,
            permission_name=permission_name,
            permission_allowed=permission_allowed,
            limit=limit,
            offset=offset,
        )

        self.send_json(
            200,
            success_response(
                request_id=self._audit_context[
                    "request_id"
                ],
                trace_id=trace_id,
                data={
                    "business_status": "已完成",
                    **result,
                },
                message="接口审计记录查询成功",
            ),
        )

    def log_message(
        self,
        format_string: str,
        *args: Any,
    ) -> None:
        print(
            f"[API] {self.address_string()} "
            f"{format_string % args}"
        )


def run_server() -> None:
    init_db()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        MonitorReminderAPIHandler,
    )

    print("=" * 78)
    print("监控提醒引擎 API 服务已启动")
    print(f"版本：{API_VERSION}")
    print("基础模块 Mock 适配层：已启用")
    print("新版 Dashboard API 客户端支持：已启用")
    print("统一消息信封：已启用")
    print("幂等控制：已启用")
    print("提醒治理：去重、同类合并、重复间隔、免打扰、紧急例外已启用")
    print(f"适配层状态：http://{HOST}:{PORT}/api/v1/adapters/status")
    print(f"健康检查：http://{HOST}:{PORT}/api/v1/health")
    print(
        "统一层内入口："
        f"POST http://{HOST}:{PORT}/api/v1/l2/internal/messages"
    )
    print(
        "能力边界："
        f"GET http://{HOST}:{PORT}/api/v1/capabilities"
    )
    print(
        "监控项列表："
        f"GET http://{HOST}:{PORT}/api/v1/monitor-items"
    )
    print(
        "监控项详情："
        f"GET http://{HOST}:{PORT}/api/v1/monitor-items/{{item_id}}"
    )
    print(
        "监控项修改："
        f"PUT http://{HOST}:{PORT}/api/v1/monitor-items/{{item_id}}"
    )
    print(
        "监控项启用："
        f"POST http://{HOST}:{PORT}/api/v1/monitor-items/{{item_id}}/enable"
    )
    print(
        "监控项暂停："
        f"POST http://{HOST}:{PORT}/api/v1/monitor-items/{{item_id}}/pause"
    )
    print(
        "监控项恢复："
        f"POST http://{HOST}:{PORT}/api/v1/monitor-items/{{item_id}}/resume"
    )
    print(
        "监控项停用："
        f"POST http://{HOST}:{PORT}/api/v1/monitor-items/{{item_id}}/disable"
    )
    print(
        "接口审计查询："
        f"GET http://{HOST}:{PORT}/api/v1/audit-records"
    )
    print("原有登记、触发、升级、确认、销记、管理和审计接口继续保留（legacy_mock_only）")
    print("除健康检查外，业务接口必须携带 Mock 权限请求头")
    print("按 Ctrl + C 停止服务")
    print("=" * 78)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止 API 服务……")
    finally:
        server.server_close()
        print("API 服务已停止")


if __name__ == "__main__":
    run_server()
