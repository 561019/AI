from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.service import SandboxService
from backend.compliance import compliance_report
from backend.acceptance import run_acceptance_checks
from backend.demo_cases import list_demo_cases, run_demo_case
from backend.delivery import create_delivery_export, delivery_checklist, delivery_evidence_manifest, delivery_package, integration_contracts, role_scenario_spec
from backend.e2b_adapter import DockerE2BAdapter
from backend.monitor import build_monitor_snapshot
from backend.platform_interface import PlatformInterface, PlatformInterfaceError
from backend.reports import list_verification_reports, write_concurrency_report, write_verification_report
from backend.verification import list_verification_cases, run_all_verification_cases, run_verification_case
from backend.verification_jobs import get_verification_job, start_verification_job


HOST = os.environ.get("SANDBOX_MVP_HOST", "127.0.0.1")
PORT = int(os.environ.get("SANDBOX_MVP_PORT", "8765"))
service = SandboxService(ROOT)
e2b_adapter = DockerE2BAdapter(ROOT, service)
platform_interface = PlatformInterface(ROOT, service)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            return self._send_file(ROOT / "frontend" / "index.html")
        if path.startswith("/static/"):
            return self._send_file(ROOT / "frontend" / path.removeprefix("/static/"))
        if path == "/api/health":
            return self._send_json({"ok": True, "service": "agent-sandbox-mvp"})
        if path == "/api/v1/layer-interface/service-catalog":
            return self._send_json(platform_interface.service_catalog())
        if path.startswith("/api/v1/layer-interface/messages/"):
            request_id = path.removeprefix("/api/v1/layer-interface/messages/").strip("/")
            try:
                return self._send_json(platform_interface.get_standard_request(request_id, self._platform_headers()))
            except PlatformInterfaceError as exc:
                return self._send_json(exc.response(self.headers.get("X-Trace-Id")), exc.http_status)
        if path.startswith("/api/v1/layer-interface/requests/"):
            parts = path.removeprefix("/api/v1/layer-interface/requests/").strip("/").split("/")
            request_id = parts[0] if parts else ""
            try:
                if len(parts) == 1:
                    return self._send_json(platform_interface.get_request(request_id, self._platform_headers()))
                if len(parts) == 2 and parts[1] == "events":
                    return self._send_json(platform_interface.get_events(request_id, self._platform_headers()))
            except PlatformInterfaceError as exc:
                return self._send_json(exc.response(self.headers.get("X-Trace-Id")), exc.http_status)
            return self._send_json({"error": "not_found"}, 404)
        if path == "/api/scenarios":
            return self._send_json({"scenarios": service.list_scenarios()})
        if path == "/api/policy":
            return self._send_json(service.policy())
        if path == "/api/readiness":
            return self._send_json(service.readiness())
        if path == "/api/compliance":
            return self._send_json(compliance_report())
        if path == "/api/acceptance":
            return self._send_json(run_acceptance_checks(ROOT))
        if path == "/api/demo-cases":
            return self._send_json({"demo_cases": list_demo_cases()})
        if path == "/api/monitor":
            return self._send_json(build_monitor_snapshot(service.list_tasks(), service.policy(), service.readiness()))
        if path == "/api/verification":
            return self._send_json({"cases": list_verification_cases()})
        if path.startswith("/api/verification/jobs/"):
            job_id = path.removeprefix("/api/verification/jobs/").strip("/")
            job = get_verification_job(job_id)
            return self._send_json(job if job else {"error": "verification_job_not_found"}, 200 if job else 404)
        if path == "/api/verification/reports":
            return self._send_json(list_verification_reports(ROOT))
        if path == "/api/delivery/checklist":
            return self._send_json(delivery_checklist(ROOT))
        if path == "/api/delivery/evidence":
            return self._send_json(delivery_evidence_manifest(ROOT))
        if path == "/api/delivery/package":
            return self._send_json(delivery_package(ROOT))
        if path == "/api/delivery/export.zip":
            create_delivery_export(ROOT)
            return self._send_file(ROOT / "docs" / "evidence" / "delivery-package.zip")
        if path == "/api/delivery/role-scenario":
            return self._send_json(role_scenario_spec())
        if path == "/api/delivery/integration-contracts":
            return self._send_json(integration_contracts())
        if path == "/api/e2b/capability":
            return self._send_json(e2b_adapter.capability())
        if path == "/api/e2b/sandboxes":
            return self._send_json({"sandboxes": e2b_adapter.list_sessions()})
        if path.startswith("/api/e2b/sandboxes/"):
            parts = path.removeprefix("/api/e2b/sandboxes/").strip("/").split("/")
            if len(parts) == 1:
                session = e2b_adapter.get_session(parts[0])
                return self._send_json(session if session else {"error": "sandbox_not_found"}, 200 if session else 404)
        if path == "/api/tasks":
            return self._send_json({"tasks": service.list_tasks()})
        if path.startswith("/api/files/"):
            return self._send_result_file(path.removeprefix("/api/files/"))
        if path.startswith("/api/tasks/"):
            task = service.get_task(path.removeprefix("/api/tasks/").strip("/"))
            return self._send_json(task if task else {"error": "task_not_found"}, 200 if task else 404)
        return self._send_json({"error": "not_found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/layer-interface/messages":
            try:
                body = self._read_body()
                response, status = platform_interface.submit_standard(body, self._platform_headers())
                return self._send_json(response, status)
            except PlatformInterfaceError as exc:
                return self._send_json(exc.response(self.headers.get("X-Trace-Id")), exc.http_status)
        if path == "/api/v1/layer-interface/requests":
            try:
                body = self._read_body()
                response, status = platform_interface.submit(body, self._platform_headers())
                return self._send_json(response, status)
            except PlatformInterfaceError as exc:
                return self._send_json(exc.response(self.headers.get("X-Trace-Id")), exc.http_status)
            except (ValueError, json.JSONDecodeError) as exc:
                error = PlatformInterfaceError("invalid_json", str(exc), 400)
                return self._send_json(error.response(self.headers.get("X-Trace-Id")), 400)
        if path.startswith("/api/demo-cases/"):
            case_id = path.removeprefix("/api/demo-cases/").strip("/")
            try:
                return self._send_json(run_demo_case(service, case_id), 201)
            except ValueError as exc:
                return self._send_json({"error": "bad_request", "message": str(exc)}, 400)
        if path == "/api/verification/run":
            try:
                body = self._read_body()
                case_id = str(body.get("case_id", "all"))
                result = run_all_verification_cases(ROOT, service) if case_id == "all" else run_verification_case(ROOT, service, case_id)
                return self._send_json(result, 201)
            except Exception as exc:
                return self._send_json({"error": "verification_failed", "message": str(exc)}, 500)
        if path == "/api/verification/jobs":
            try:
                body = self._read_body()
                case_id = str(body.get("case_id", "all"))
                return self._send_json(start_verification_job(ROOT, service, case_id), 202)
            except Exception as exc:
                return self._send_json({"error": "verification_job_start_failed", "message": str(exc)}, 500)
        if path == "/api/verification/report":
            try:
                result = run_all_verification_cases(ROOT, service)
                return self._send_json(write_verification_report(ROOT, result), 201)
            except Exception as exc:
                return self._send_json({"error": "verification_report_failed", "message": str(exc)}, 500)
        if path == "/api/verification/concurrency-report":
            try:
                body = self._read_body()
                return self._send_json(write_concurrency_report(ROOT, service, int(body.get("count", 3))), 201)
            except Exception as exc:
                return self._send_json({"error": "concurrency_report_failed", "message": str(exc)}, 500)
        if path == "/api/delivery/export":
            try:
                return self._send_json(create_delivery_export(ROOT), 201)
            except Exception as exc:
                return self._send_json({"error": "delivery_export_failed", "message": str(exc)}, 500)
        if path == "/api/e2b/sandboxes":
            try:
                return self._send_json(e2b_adapter.create_session(self._read_body()), 201)
            except ValueError as exc:
                return self._send_json({"error": "bad_request", "message": str(exc)}, 400)
        if path.startswith("/api/e2b/sandboxes/"):
            parts = path.removeprefix("/api/e2b/sandboxes/").strip("/").split("/")
            try:
                if len(parts) == 2 and parts[1] == "run":
                    return self._send_json(e2b_adapter.run_template(parts[0], self._read_body()), 201)
                if len(parts) == 2 and parts[1] == "destroy":
                    return self._send_json(e2b_adapter.destroy_session(parts[0]))
            except ValueError as exc:
                return self._send_json({"error": "bad_request", "message": str(exc)}, 400)
        if path != "/api/tasks":
            return self._send_json({"error": "not_found"}, 404)
        try:
            task = service.create_task(self._read_body())
        except ValueError as exc:
            return self._send_json({"error": "bad_request", "message": str(exc)}, 400)
        return self._send_json(task, 201)

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _platform_headers(self) -> dict[str, str]:
        return {
            "authorization": self.headers.get("Authorization", ""),
            "x-caller-layer": self.headers.get("X-Caller-Layer", ""),
            "x-engine-id": self.headers.get("X-Engine-Id", ""),
            "x-trace-id": self.headers.get("X-Trace-Id", ""),
            "x-company-id": self.headers.get("X-Company-Id", ""),
        }

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            return self._send_json({"error": "file_not_found"}, 404)
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_result_file(self, rel_path: str) -> None:
        safe_root = (ROOT / "data" / "results").resolve()
        target = (safe_root / rel_path).resolve()
        if not str(target).startswith(str(safe_root)) or not target.exists() or not target.is_file():
            return self._send_json({"error": "file_not_found"}, 404)
        self._send_file(target)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Agent sandbox MVP running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
