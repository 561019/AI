"""数据操作引擎的统一平台接入适配服务。

这个文件不是流程执行引擎：它只接受流程执行引擎已经确定的动作，
将平台标准信封转换为本模块既有的 L2 内部派单，再返回标准响应。
"""
from __future__ import annotations

import argparse
import json
import shutil
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from engine import AggregationEngine, EngineError


PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_ROOT / "data"
DATABASE_PATH = DATA_DIR / "data_operation_engine.db"
MODULE_CODE = "data-operation"
INSTRUCTION_PATH = "/api/v1/data-operation/instructions"
SUPPORTED_ACTIONS = {
    "data.collect",
    "data.consolidate",
    "data.persist",
    "data.search",
    "data.read",
    "data.update",
    "data.delete",
    "data.trace",
}
WRITE_ACTIONS = {"data.collect", "data.consolidate", "data.persist", "data.update", "data.delete"}


def _error_response(
    *, trace_id: str | None, request_id: str | None, code: str, message: str,
    http_status: int = 400, details: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    return http_status, {
        "status": "failed",
        "trace_id": trace_id,
        "request_id": request_id,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "retryable": http_status >= 500,
        },
    }


class PlatformAdapter:
    """Validate platform envelopes and delegate deterministic data operations."""

    def __init__(self, db_path: str | Path = DATABASE_PATH):
        self.engine = AggregationEngine(db_path)

    def close(self) -> None:
        self.engine.close()

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    def _validate_envelope(self, envelope: Any) -> tuple[dict[str, Any] | None, tuple[int, dict[str, Any]] | None]:
        if not isinstance(envelope, dict):
            return None, _error_response(
                trace_id=None, request_id=None, code="REQUEST_BODY_INVALID",
                message="请求体必须为 JSON 对象。",
            )
        trace_id = self._text(envelope.get("trace_id"))
        request_id = self._text(envelope.get("request_id"))
        required_top = ("protocol_version", "message_id", "request_id", "trace_id", "source", "target", "actor", "context", "request_type", "action", "payload", "expected_response")
        missing = [field for field in required_top if field not in envelope]
        if missing:
            return None, _error_response(
                trace_id=trace_id or None, request_id=request_id or None,
                code="STANDARD_ENVELOPE_REQUIRED", message="缺少平台标准请求字段。",
                details={"missing": missing},
            )
        if self._text(envelope.get("protocol_version")) != "1.0":
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="PROTOCOL_VERSION_UNSUPPORTED", message="仅支持 protocol_version=1.0。")
        if not all(self._text(envelope.get(field)) for field in ("message_id", "request_id", "trace_id", "request_type", "action")):
            return None, _error_response(trace_id=trace_id or None, request_id=request_id or None, code="REQUEST_ID_REQUIRED", message="message_id、request_id、trace_id、request_type 和 action 不可为空。")

        source = envelope.get("source")
        target = envelope.get("target")
        actor = envelope.get("actor")
        context = envelope.get("context")
        expected_response = envelope.get("expected_response")
        payload = envelope.get("payload")
        if not all(isinstance(value, dict) for value in (source, target, actor, context, expected_response, payload)):
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="STANDARD_ENVELOPE_INVALID", message="source、target、actor、context、payload、expected_response 必须为对象。")

        source_module = self._text(source.get("module")).replace("_", "-")
        if self._text(source.get("layer")) != "business_engine" or source_module not in {"workflow-execution", "workflow-execution-engine"}:
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="WORKFLOW_SOURCE_REQUIRED", message="数据操作引擎只接受业务引擎层流程执行引擎的派单。")
        if self._text(target.get("layer")) != "business_engine" or self._text(target.get("module")).replace("_", "-") != MODULE_CODE:
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="TARGET_MODULE_INVALID", message="target 必须指向 business_engine/data-operation。")
        action = self._text(envelope.get("action"))
        capability = self._text(target.get("capability"))
        if action not in SUPPORTED_ACTIONS or capability != action:
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="CAPABILITY_NOT_SUPPORTED", message="action 必须是本模块登记能力，且与 target.capability 一致。", details={"supported": sorted(SUPPORTED_ACTIONS)})
        if self._text(envelope.get("request_type")) != "task.dispatch":
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="REQUEST_TYPE_INVALID", message="数据操作引擎只接收 task.dispatch 请求。")
        if not bool(actor.get("authenticated")) or not self._text(actor.get("tenant_id")) or not self._text(actor.get("user_id")):
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="ACTOR_AUTH_REQUIRED", message="必须携带已认证的 tenant_id、user_id 和 authenticated=true。")
        if not self._text(context.get("account_id")) or not self._text(context.get("project_id")):
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="OWNERSHIP_CONTEXT_REQUIRED", message="context.account_id 和 context.project_id 不可为空。")
        mode = self._text(expected_response.get("mode"))
        if mode not in {"sync", "async"}:
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="RESPONSE_MODE_INVALID", message="expected_response.mode 只能为 sync 或 async。")
        if action in WRITE_ACTIONS and not self._text(envelope.get("idempotency_key")):
            return None, _error_response(trace_id=trace_id, request_id=request_id, code="IDEMPOTENCY_KEY_REQUIRED", message="写操作必须携带 idempotency_key。")
        return envelope, None

    @staticmethod
    def _business_context(envelope: dict[str, Any]) -> dict[str, Any]:
        payload = dict(envelope["payload"])
        inherited = payload.get("business_context") if isinstance(payload.get("business_context"), dict) else {}
        context = envelope["context"]
        actor = envelope["actor"]
        return {
            **inherited,
            "tenant_id": actor["tenant_id"],
            "owner_account_id": context["account_id"],
            "project_id": context["project_id"],
            "conversation_id": context.get("conversation_id"),
            "file_id": context.get("file_id"),
            "object_id": context.get("object_id"),
            "workflow_instance_id": context.get("workflow_instance_id"),
            "parent_request_id": envelope.get("parent_request_id"),
            "message_id": envelope["message_id"],
            "idempotency_key": envelope.get("idempotency_key"),
        }

    def _to_internal_task(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = dict(envelope["payload"])
        payload["business_context"] = self._business_context(envelope)
        return {
            "protocol_version": "1.0",
            "message_id": envelope["message_id"],
            "request_id": envelope["request_id"],
            "trace_id": envelope["trace_id"],
            "parent_request_id": envelope.get("parent_request_id"),
            "source_service": "L2.workflow_execution",
            "source": {"service_code": "L2.workflow_execution"},
            "actor_id": envelope["actor"]["user_id"],
            "actor": {"person_id": envelope["actor"]["user_id"], **envelope["actor"]},
            "channel": "l2_internal",
            "route_type": "task.dispatch",
            "action_id": envelope["action"],
            "capability_id": envelope["target"]["capability"],
            "payload": payload,
            "mock": envelope.get("mock") if isinstance(envelope.get("mock"), dict) else {},
        }

    def handle_instruction(self, envelope: Any) -> tuple[int, dict[str, Any]]:
        envelope, failure = self._validate_envelope(envelope)
        if failure:
            return failure
        assert envelope is not None
        trace_id = str(envelope["trace_id"])
        request_id = str(envelope["request_id"])
        actor_id = str(envelope["actor"]["user_id"])
        try:
            accepted = self.engine.receive_workflow_task(self._to_internal_task(envelope))
            mode = envelope["expected_response"]["mode"]
            status_url = f"/api/v1/data-operation/tasks/{trace_id}?actor_id={actor_id}"
            if mode == "async":
                return HTTPStatus.ACCEPTED, {
                    "status": "accepted", "trace_id": trace_id, "request_id": request_id,
                    "task_id": trace_id, "progress": accepted.get("task_status", "accepted"),
                    "status_url": status_url, "error": None,
                }
            detail = self.engine.task_detail(trace_id, actor_id)
            response = detail.get("response") or {}
            if detail["task"]["status"] == "failed":
                error = response.get("error") or {
                    "code": detail["task"].get("reason_code") or "TASK_FAILED",
                    "message": response.get("message") or "数据操作任务失败。",
                    "details": {"task_id": trace_id}, "retryable": False,
                }
                return HTTPStatus.BAD_REQUEST, {
                    "status": "failed", "trace_id": trace_id, "request_id": request_id,
                    "data": None, "error": error,
                }
            return HTTPStatus.OK, {
                "status": "success", "trace_id": trace_id, "request_id": request_id,
                "task_id": trace_id, "data": response.get("data"), "error": None,
            }
        except EngineError as exc:
            return _error_response(trace_id=trace_id, request_id=request_id, code=exc.code, message=exc.message, http_status=exc.http_status)
        except Exception as exc:  # pragma: no cover - defensive boundary for platform callers
            return _error_response(trace_id=trace_id, request_id=request_id, code="MODULE_INTERNAL_ERROR", message="模块内部异常。", http_status=500, details={"exception_type": type(exc).__name__})

    def task_detail(self, trace_id: str, actor_id: str) -> tuple[int, dict[str, Any]]:
        try:
            detail = self.engine.task_detail(trace_id, actor_id)
            return HTTPStatus.OK, {"status": "success", "trace_id": trace_id, "request_id": detail["task"]["request_id"], "data": detail, "error": None}
        except EngineError as exc:
            return _error_response(trace_id=trace_id, request_id=None, code=exc.code, message=exc.message, http_status=exc.http_status)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "DataOperationIntegration/0.6"

    @property
    def adapter(self) -> PlatformAdapter:
        return self.server.adapter  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(HTTPStatus.OK, {"status": "success", "trace_id": None, "request_id": None, "data": {"module": MODULE_CODE, "service": "healthy"}, "error": None})
            return
        if parsed.path == "/manifest":
            self._send(HTTPStatus.OK, json.loads((PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8")))
            return
        if parsed.path.startswith("/api/v1/data-operation/tasks/"):
            trace_id = parsed.path.rsplit("/", 1)[-1]
            actor_id = (parse_qs(parsed.query).get("actor_id") or [""])[0]
            status, body = self.adapter.task_detail(trace_id, actor_id)
            self._send(status, body)
            return
        self._send(HTTPStatus.NOT_FOUND, _error_response(trace_id=None, request_id=None, code="ROUTE_NOT_FOUND", message="未找到接口。", http_status=404)[1])

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != INSTRUCTION_PATH:
            self._send(HTTPStatus.NOT_FOUND, _error_response(trace_id=None, request_id=None, code="ROUTE_NOT_FOUND", message="未找到接口。", http_status=404)[1])
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            envelope = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            status, body = _error_response(trace_id=None, request_id=None, code="JSON_INVALID", message="请求体必须是 UTF-8 JSON。")
            self._send(status, body)
            return
        status, body = self.adapter.handle_instruction(envelope)
        self._send(status, body)


def create_server(host: str, port: int, db_path: str | Path = DATABASE_PATH) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    server.adapter = PlatformAdapter(db_path)  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Data operation engine platform adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8031)
    parser.add_argument("--reset", action="store_true", help="Reset only this package's local mock data")
    args = parser.parse_args()
    if args.reset and DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = create_server(args.host, args.port)
    print(f"data-operation integration adapter listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    finally:
        server.adapter.close()  # type: ignore[attr-defined]
        server.server_close()


if __name__ == "__main__":
    main()
