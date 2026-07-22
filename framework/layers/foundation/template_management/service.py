from __future__ import annotations

from typing import Any

from framework.core import standard_response
from l1_2_template_management.template_management import InMemoryTemplateRepository, TemplateManagementService, seed_common_templates


SERVICE = TemplateManagementService(InMemoryTemplateRepository())
seed_common_templates(SERVICE)


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/templates/instructions":
        handler.send(404); return
    source = envelope.get("source", {})
    if source.get("layer") != "business_engine" or source.get("module") != "workflow-execution-engine-original":
        handler.send(403, {"error": {"code": "SOURCE_LAYER_FORBIDDEN"}}); return
    action = str(envelope.get("action") or envelope.get("target", {}).get("capability") or "")
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    request_type = "query" if action in {"template.retrieve", "template.list", "template.validate"} else "maintain"
    result = SERVICE.handle_instruction({
        "caller_layer": "L2", "service_name": action, "request_type": request_type,
        "actor_id": envelope.get("actor", {}).get("actor_id") or envelope.get("actor", {}).get("user_id") or "workflow-execution",
        "payload": payload, "trace_id": envelope.get("trace_id"),
    })
    if not result.get("ok"):
        handler.send(422, standard_response(envelope, "failed", error=result.get("error"))); return
    handler.send(200, standard_response(envelope, "success", data=result["result"]))
