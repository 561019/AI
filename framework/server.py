from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from typing import Any

from framework.core import initialize, record_interface_call


SERVICE_MODULES = {
    "application": "framework.layers.business_application.application_gateway.service",
    "engine": "framework.layers.business_engine.engine_gateway.service",
    "intent": "framework.layers.business_engine.intent_analysis.service",
    "intent_original": "framework.layers.business_engine.intent_analysis.delivered_engine.service",
    "workflow": "framework.layers.business_engine.workflow_execution.service",
    "workflow_original": "framework.layers.business_engine.workflow_execution.delivered_engine.service",
    "rule": "framework.layers.business_engine.rule_calculation.service",
    "rule_original": "framework.layers.business_engine.rule_calculation.delivered_engine.service",
    "content": "framework.layers.business_engine.content_production.service",
    "content_original": "framework.layers.business_engine.content_production.delivered_engine.service",
    "document_table_parsing": "framework.layers.business_engine.document_table_parsing.service",
    "analysis_prediction": "framework.layers.business_engine.analysis_prediction.service",
    "data_operation": "framework.layers.business_engine.data_operation.service",
    "digital_asset": "framework.layers.business_engine.digital_asset.service",
    "project_management": "framework.layers.business_engine.project_management.service",
    "monitoring_reminder": "framework.layers.business_engine.monitoring_reminder.service",
    "external_system_integration": "framework.layers.business_engine.external_system_integration.service",
    "knowledge_qa": "framework.layers.business_engine.knowledge_qa.service",
    "knowledge_map": "framework.layers.business_engine.knowledge_map.service",
    "multimedia_generation": "framework.layers.business_engine.multimedia_generation.service",
    "foundation": "framework.layers.foundation.foundation_gateway.service",
    "permission": "framework.layers.foundation.permission.service",
    "model": "framework.layers.foundation.model_dispatcher.service",
    "registry": "framework.layers.foundation.capability_registry.service",
    "template": "framework.layers.foundation.template_management.service",
    "context_prompt_management": "framework.layers.foundation.context_prompt_management.service",
    "foundation_data": "framework.layers.foundation.foundation_data.service",
    "account_gateway": "framework.layers.foundation.account_gateway.service",
    "security_compliance": "framework.layers.foundation.security_compliance.service",
    "human_collaboration": "framework.layers.foundation.human_collaboration.service",
    "execution_sandbox": "framework.layers.foundation.execution_sandbox.service",
    "evolution_mechanism": "framework.layers.foundation.evolution_mechanism.service",
    "control_mechanism": "framework.layers.foundation.control_mechanism.service",
    "knowledge_base": "framework.layers.foundation.knowledge_base.service",
    "memory_management": "framework.layers.foundation.memory_management.service",
    "device_system_interface": "framework.layers.foundation.device_system_interface.service",
    "cost_control": "framework.layers.foundation.cost_control.service",
}

ENDPOINTS = {
    "application": ["GET /chat", "GET /cases", "GET /uploads", "GET /modules", "GET /demo", "GET /monitor", "GET /health", "POST /api/v1/application/instructions", "GET /api/v1/uploads", "POST /api/v1/uploads", "POST /api/v1/application/context/capacity", "POST /api/v1/application/context/handoff", "POST /api/v1/application/context/handoff/query", "POST /api/v1/application/knowledge/files/delete", "GET /api/v1/platform/overview", "GET /api/v1/data/catalog", "GET /api/v1/data/records?dataset={dataset}", "GET /api/v1/runtime/session/{trace_id}", "GET /api/v1/traces/{trace_id}/data-access", "POST /api/application/capability-management/commands", "POST /api/application/knowledge-governance/commands", "POST /api/application/account/commands", "GET /api/v1/module-verification/cases", "POST /api/v1/module-verification/run", "GET /api/v1/tasks/{task_id}", "GET /api/v1/traces/{trace_id}/calls", "POST /api/v1/confirmations/{confirmation_id}/decisions"],
    "engine": ["GET /health", "POST /api/v1/engine/instructions", "POST /api/v1/callbacks"],
    "foundation": ["GET /health", "POST /api/v1/foundation/instructions"],
    "intent": ["GET /health", "POST /api/v1/intent/analyze"],
    "intent_original": ["GET /health", "POST /api/v1/delivered-intent/analyze"],
    "workflow": ["GET /health", "POST /api/v1/workflows/executions", "GET /api/v1/workflows/executions/{execution_id}", "POST /api/v1/workflows/executions/{execution_id}/resume"],
    "workflow_original": ["GET /health", "POST /api/v1/delivered-workflow/plan", "POST /api/v1/delivered-workflow/execute", "POST /api/v1/delivered-workflow/instructions"],
    "permission": ["GET /health", "POST /api/v1/permissions/check"],
    "model": ["GET /health", "POST /api/v1/models/responses"],
    "rule": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/rules/instructions"],
    "rule_original": ["GET /health", "POST /api/v1/delivered-rules/calculate"],
    "content": ["GET /health", "POST /api/v1/content/instructions"],
    "content_original": ["GET /health", "POST /api/v1/delivered-content/generate"],
    "document_table_parsing": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/document-table/instructions"],
    "analysis_prediction": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/analysis/instructions"],
    "data_operation": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/data-operation/instructions"],
    "digital_asset": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/assets/instructions"],
    "project_management": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/projects/instructions"],
    "monitoring_reminder": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/monitoring/instructions"],
    "external_system_integration": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/external-systems/instructions"],
    "knowledge_qa": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/knowledge-qa/instructions"],
    "knowledge_map": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/knowledge-map/instructions"],
    "multimedia_generation": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/multimedia/instructions"],
    "registry": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/capabilities/{capability_code}/resolve"],
    "template": ["GET /health", "POST /api/v1/templates/instructions"],
    "context_prompt_management": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/context-prompts/instructions"],
    "foundation_data": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/foundation-data/instructions"],
    "account_gateway": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/accounts/instructions"],
    "security_compliance": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/security/instructions"],
    "human_collaboration": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/human/instructions"],
    "execution_sandbox": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/sandbox/instructions"],
    "evolution_mechanism": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/evolution/instructions"],
    "control_mechanism": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/control/instructions"],
    "knowledge_base": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/knowledge/instructions"],
    "memory_management": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/memory/instructions"],
    "device_system_interface": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/device-systems/instructions"],
    "cost_control": ["GET /health", "GET /api/v1/capabilities", "POST /api/v1/cost/instructions"],
}


class Handler(BaseHTTPRequestHandler):
    service = ""

    def log_message(self, *_: Any) -> None:
        return

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def send(self, status: int, body: Any = None) -> None:
        self.last_response_status = status
        self.last_response_body = body
        raw = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if raw:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def send_html(self, status: int, body: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    @property
    def module(self) -> Any:
        return import_module(SERVICE_MODULES[self.service])

    def do_GET(self) -> None:
        if self.path in {"/", "/docs"}:
            self.send(200, {"status": "ok", "service": self.service, "version": "0.2.0", "message": "服务已启动", "endpoints": ENDPOINTS.get(self.service, ["GET /health"])}); return
        if self.path == "/health":
            self.send(200, {"status": "ok", "service": self.service}); return
        get_handler = getattr(self.module, "get", None)
        if get_handler and get_handler(self): return
        self.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})

    def do_POST(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if content_type.lower().startswith("multipart/form-data"):
            multipart_handler = getattr(self.module, "post_multipart", None)
            if multipart_handler:
                multipart_handler(self)
                return
            self.send(415, {"error": {"code": "UNSUPPORTED_MEDIA_TYPE"}})
            return
        body = self.body()
        try:
            self.module.post(self, body)
        except Exception as exc:
            self.send(500, {"error": {"code": "MODULE_REQUEST_FAILED", "message": str(exc)}})
        finally:
            source = body.get("source") if isinstance(body.get("source"), dict) else {"layer": "external", "module": "frontend-client"}
            target = {"layer": "runtime", "module": self.service}
            capability = str((body.get("target") or {}).get("capability") or body.get("action") or self.path)
            bind_host = os.getenv("PLATFORM_BIND_HOST", "127.0.0.1")
            display_host = "127.0.0.1" if bind_host in {"", "0.0.0.0"} else bind_host
            record_interface_call(
                trace_id=str(body.get("trace_id") or "untraced"), source=source, target=target,
                capability=capability, method="POST", url=f"http://{display_host}:{self.server.server_port}{self.path}",
                request=body, response=getattr(self, "last_response_body", None),
                status_code=int(getattr(self, "last_response_status", 500)), duration_ms=0,
            )


def serve(service: str, port: int) -> None:
    # start_all.ps1 initializes the shared database once before it starts the
    # service fleet. Keep standalone `run_services` usable as well.
    if os.getenv("PLATFORM_DB_INITIALIZED") != "1":
        initialize()
    bind_host = os.getenv("PLATFORM_BIND_HOST", "127.0.0.1")
    handler = type(f"{service.title()}Handler", (Handler,), {"service": service})
    ThreadingHTTPServer((bind_host, port), handler).serve_forever()
