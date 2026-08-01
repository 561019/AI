from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .audit import write_audit_event
from .chat import chat_with_session, list_session_messages
from .config import get_llm_config
from .control_center import (
    answer_platform_history,
    answer_project_history,
    get_platform_history,
    get_project_history,
)
from .cross_project_references import (
    check_existing_references,
    create_cross_project_reference,
    delete_cross_project_reference,
    list_cross_project_references,
)
from .control_center_messages import list_control_center_messages
from .context_memory import (
    archive_context_memory,
    create_context_memory,
    get_context_memory,
    list_context_memories,
    update_context_memory,
)
from .context_engineering import (
    add_context_usage,
    compact_session_context,
    estimate_context_payload,
    list_context_compactions,
)
from .db import connect, rows_to_dicts
from .artifacts import create_artifact_file, get_artifact_file, list_artifact_files
from .handoff import (
    close_session,
    delete_handoff_file,
    delete_work_report,
    generate_handoff_file,
    generate_handoff_package,
    generate_work_report,
    list_handoff_files,
    list_handoff_packages,
    list_work_reports,
)
from .handoff_runs import (
    complete_handoff_run,
    generate_run_handoff_file,
    generate_run_work_report,
    get_handoff_run,
    upgrade_run_sync_package,
    write_handoff_reply,
)
from .langfuse_platform import (
    fetch_langfuse_prompt,
    get_langfuse_status,
    get_prompt_run_trace,
    list_prompt_run_traces,
    score_prompt_run_trace,
)
from .prompts import (
    create_prompt_template,
    create_prompt_version,
    publish_prompt_version,
    list_prompt_templates,
    list_prompt_versions,
)
from .prompt_governance import get_prompt_governance
from .sessions import (
    check_session_writable,
    create_session,
    get_session,
    list_capacity_events,
    list_sessions,
    delete_session,
    update_session_capacity,
    update_session_notes,
)
from .sync_packages import delete_sync_package, get_latest_sync_package, list_sync_packages, upgrade_sync_package
from .utils import ApiError, json_dumps


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "static"


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "L1_6ContextPromptMVP/0.1"

    def do_GET(self) -> None:
        if self._try_send_static():
            return
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def _handle(self, method: str) -> None:
        try:
            result = self._route(method)
            self._send_json(HTTPStatus.OK, result)
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message, "details": exc.details})
        except Exception as exc:  # Keep week-1 API debuggable.
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _route(self, method: str) -> Any:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        actor_id = self.headers.get("X-Actor-Id", "system")

        if method == "GET" and path == "/health":
            return {"status": "ok"}

        if path == "/api/context/memories":
            if method == "POST":
                return create_context_memory(self._read_json())
            if method == "GET":
                return {"items": list_context_memories(query, actor_id)}

        if path == "/api/context/estimate":
            if method == "POST":
                return estimate_context_payload(self._read_json())

        if path == "/api/platform/control-center/history" and method == "GET":
            return get_platform_history(query, actor_id)

        if path == "/api/platform/control-center/answer" and method == "POST":
            return answer_platform_history(self._read_json())

        if path == "/api/platform/control-center/messages" and method == "GET":
            return {"items": list_control_center_messages(scope_level="platform", scope_id="global", actor_id=actor_id)}

        if path == "/api/sessions":
            if method == "POST":
                return create_session(self._read_json())
            if method == "GET":
                return {"items": list_sessions(query, actor_id)}

        if path.startswith("/api/sessions/"):
            parts = path.split("/")
            session_id = parts[3]
            if len(parts) == 4 and method == "GET":
                return get_session(session_id, actor_id)
            if len(parts) == 4 and method == "DELETE":
                return delete_session(session_id, actor_id)
            if len(parts) == 5 and parts[4] == "capacity" and method == "PATCH":
                return update_session_capacity(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "notes" and method == "PATCH":
                return update_session_notes(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "capacity-events" and method == "GET":
                return {"items": list_capacity_events(session_id, actor_id)}
            if len(parts) == 5 and parts[4] == "messages" and method == "GET":
                return {"items": list_session_messages(session_id, actor_id)}
            if len(parts) == 5 and parts[4] == "chat" and method == "POST":
                return chat_with_session(session_id, self._read_json())
            if len(parts) == 6 and parts[4] == "handoff" and parts[5] == "start" and method == "POST":
                payload = self._read_json()
                payload.setdefault("actor_id", actor_id)
                from .handoff_runs import start_handoff_run

                return start_handoff_run(session_id, payload)
            if len(parts) == 5 and parts[4] == "context-usage" and method == "POST":
                return add_context_usage(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "compactions" and method == "POST":
                return compact_session_context(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "compactions" and method == "GET":
                return {"items": list_context_compactions(session_id, actor_id)}
            if len(parts) == 5 and parts[4] == "work-report" and method == "POST":
                return generate_work_report(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "handoff-file" and method == "POST":
                return generate_handoff_file(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "handoff-package" and method == "POST":
                return generate_handoff_package(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "close" and method == "POST":
                return close_session(session_id, self._read_json())
            if len(parts) == 5 and parts[4] == "status" and method == "GET":
                session = get_session(session_id, actor_id)
                return {
                    "session_id": session["id"],
                    "locked": session.get("locked", False),
                    "auto_handoff_done": session.get("auto_handoff_done", False),
                    "capacity_ratio": session.get("capacity_ratio", 0),
                    "status": session.get("status"),
                    "next_session_id": session.get("next_session_id"),
                }

        if path.startswith("/api/handoff-runs/"):
            parts = path.split("/")
            run_id = parts[3]
            if len(parts) == 4 and method == "GET":
                return get_handoff_run(run_id, actor_id)
            if len(parts) == 5 and parts[4] == "reply" and method == "POST":
                return write_handoff_reply(run_id, self._read_json())
            if len(parts) == 5 and parts[4] == "work-report" and method == "POST":
                return generate_run_work_report(run_id, self._read_json())
            if len(parts) == 5 and parts[4] == "handoff-file" and method == "POST":
                return generate_run_handoff_file(run_id, self._read_json())
            if len(parts) == 5 and parts[4] == "sync-package" and method == "POST":
                return upgrade_run_sync_package(run_id, self._read_json())
            if len(parts) == 5 and parts[4] == "complete" and method == "POST":
                return complete_handoff_run(run_id, self._read_json())

        if path.startswith("/api/context/memories/"):
            parts = path.split("/")
            item_id = parts[4]
            if len(parts) == 5 and method == "GET":
                return get_context_memory(item_id, actor_id)
            if len(parts) == 5 and method == "PATCH":
                return update_context_memory(item_id, self._read_json())
            if len(parts) == 6 and parts[5] == "archive" and method == "POST":
                payload = self._read_json()
                return archive_context_memory(item_id, payload.get("actor_id", actor_id))

        if path == "/api/prompts/templates":
            if method == "POST":
                return create_prompt_template(self._read_json())
            if method == "GET":
                return {"items": list_prompt_templates(query, actor_id)}

        if path.startswith("/api/prompts/templates/"):
            parts = path.split("/")
            template_id = parts[4]
            if len(parts) == 6 and parts[5] == "versions":
                if method == "POST":
                    return create_prompt_version(template_id, self._read_json())
                if method == "GET":
                    return {"items": list_prompt_versions(template_id, actor_id)}

        if path.startswith("/api/prompts/versions/"):
            parts = path.split("/")
            version_id = parts[4]
            if len(parts) == 6 and parts[5] == "publish" and method == "POST":
                return publish_prompt_version(version_id, self._read_json())

        if path == "/api/artifacts/files":
            if method == "POST":
                return create_artifact_file(self._read_json())
            if method == "GET":
                return {"items": list_artifact_files(query, actor_id)}

        if path.startswith("/api/artifacts/files/"):
            parts = path.split("/")
            file_id = parts[4]
            if len(parts) == 5 and method == "GET":
                return get_artifact_file(file_id, actor_id)

        if path.startswith("/api/projects/"):
            parts = path.split("/")
            project_id = parts[3]
            if len(parts) == 5 and parts[4] == "sync-packages" and method == "GET":
                return {"items": list_sync_packages(project_id, query, actor_id)}
            if len(parts) == 6 and parts[4] == "sync-packages" and parts[5] == "latest" and method == "GET":
                return get_latest_sync_package(project_id, actor_id)
            if len(parts) == 6 and parts[4] == "sync-packages" and parts[5] == "upgrade" and method == "POST":
                return upgrade_sync_package(project_id, self._read_json())
            if len(parts) == 6 and parts[4] == "sync-packages" and method == "DELETE":
                return delete_sync_package(project_id, parts[5], actor_id)
            if len(parts) == 6 and parts[4] == "control-center" and parts[5] == "history" and method == "GET":
                return get_project_history(project_id, query, actor_id)
            if len(parts) == 6 and parts[4] == "control-center" and parts[5] == "answer" and method == "POST":
                return answer_project_history(project_id, self._read_json())
            if len(parts) == 6 and parts[4] == "control-center" and parts[5] == "messages" and method == "GET":
                return {
                    "items": list_control_center_messages(
                        scope_level="project",
                        scope_id=project_id,
                        actor_id=actor_id,
                    )
                }
            if len(parts) == 5 and parts[4] == "cross-project-references" and method == "GET":
                return {"items": list_cross_project_references(project_id, actor_id)}
            if len(parts) == 5 and parts[4] == "cross-project-references" and method == "POST":
                return create_cross_project_reference(project_id, self._read_json())
            if len(parts) == 6 and parts[4] == "cross-project-references" and method == "DELETE":
                return delete_cross_project_reference(project_id, parts[5], actor_id)
            if len(parts) == 6 and parts[4] == "prompt-governance" and parts[5] == "overview" and method == "GET":
                return get_prompt_governance(project_id, actor_id)

        if method == "GET" and path == "/api/work-reports":
            return {"items": list_work_reports(query, actor_id)}

        if path.startswith("/api/work-reports/"):
            parts = path.split("/")
            if len(parts) == 4 and method == "DELETE":
                return delete_work_report(parts[3], actor_id)

        if method == "GET" and path == "/api/handoff-packages":
            return {"items": list_handoff_packages(query, actor_id)}

        if path.startswith("/api/handoff-packages/"):
            parts = path.split("/")
            if len(parts) == 4 and method == "DELETE":
                return delete_handoff_file(parts[3], actor_id)

        if method == "GET" and path == "/api/handoff-files":
            return {"items": list_handoff_files(query, actor_id)}

        if path.startswith("/api/handoff-files/"):
            parts = path.split("/")
            if len(parts) == 4 and method == "DELETE":
                return delete_handoff_file(parts[3], actor_id)

        if method == "GET" and path == "/api/langfuse/config":
            return get_langfuse_status()

        if method == "GET" and path == "/api/kimi/config":
            return get_llm_config()

        if method == "GET" and path == "/api/llm/config":
            return get_llm_config()

        if method == "GET" and path == "/api/deepseek/config":
            return get_llm_config()

        if path.startswith("/api/langfuse/prompts/"):
            parts = path.split("/")
            prompt_name = parts[4]
            if len(parts) == 5 and method == "GET":
                return fetch_langfuse_prompt(prompt_name, _first(query, "label") or "production")

        if method == "GET" and path == "/api/langfuse/traces":
            return {"items": list_prompt_run_traces(query)}

        if path.startswith("/api/langfuse/traces/"):
            parts = path.split("/")
            trace_id = parts[4]
            if len(parts) == 5 and method == "GET":
                return get_prompt_run_trace(trace_id)
            if len(parts) == 6 and parts[5] == "score" and method == "POST":
                return score_prompt_run_trace(trace_id, self._read_json())

        if method == "GET" and path == "/api/references/check":
            return {
                "referenced_project_ids": check_existing_references(
                    source_project_id=_first(query, "source_project_id") or "",
                    source_record_type=_first(query, "source_record_type") or "",
                    source_record_id=_first(query, "source_record_id") or "",
                    actor_id=actor_id,
                )
            }

        if method == "GET" and path == "/api/audit-events":
            with connect() as conn:
                rows = conn.execute("SELECT * FROM audit_event ORDER BY created_at DESC LIMIT 200").fetchall()
            return {"items": rows_to_dicts(rows)}

        write_audit_event(
            actor_id=actor_id,
            action="http.not_found",
            resource_type="http",
            resource_id=path,
            permission_result="allow",
        )
        raise ApiError(HTTPStatus.NOT_FOUND, "Route not found", {"method": method, "path": path})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Invalid JSON") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return data

    def _send_json(self, status: int | HTTPStatus, data: Any) -> None:
        body = json_dumps(data)
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _try_send_static(self) -> bool:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            target = STATIC_DIR / "index.html"
        elif path.startswith("/static/"):
            relative = path.removeprefix("/static/").replace("/", "\\")
            target = STATIC_DIR / relative
        else:
            return False
        try:
            resolved = target.resolve()
            static_root = STATIC_DIR.resolve()
            if static_root not in resolved.parents and resolved != static_root:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
                return True
            if not resolved.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Static file not found"})
                return True
            body = resolved.read_bytes()
        except OSError as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return True
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        if resolved.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif resolved.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif resolved.suffix == ".css":
            content_type = f"{content_type}; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def log_message(self, fmt: str, *args: Any) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
