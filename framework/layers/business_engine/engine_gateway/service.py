from typing import Any
from framework.core import get_task, update_task, validate_envelope
from framework.http import post_json

def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path == "/api/v1/callbacks":
        task_id=envelope.get("task_id")
        if not task_id or not get_task(task_id): handler.send(404); return
        update_task(task_id,state=str(envelope.get("event_type","")).removeprefix("task."),progress=envelope.get("progress"),result=envelope.get("data"),sequence=envelope.get("sequence")); handler.send(204); return
    if handler.path != "/api/v1/engine/instructions": handler.send(404); return
    if validate_envelope(envelope): handler.send(400,{"error":{"code":"INVALID_REQUEST"}}); return
    source=envelope["source"]
    allowed_modules={"application-gateway","intent-adapter","workflow-execution","rule-adapter","content-adapter","document-table-parsing","analysis-prediction","data-operation","digital-asset","project-management","monitoring-reminder","external-system-integration","knowledge-qa","knowledge-map","multimedia-generation","account-gateway"}
    if source.get("layer") not in {"business_application","business_engine","foundation"} or source.get("module") not in allowed_modules: handler.send(403,{"error":{"code":"SOURCE_LAYER_FORBIDDEN"}}); return
    capability=envelope["target"].get("capability") or envelope["action"]
    registry_status,registration=post_json(f"http://127.0.0.1:8400/api/v1/capabilities/{capability}/resolve",{"trace_id":envelope["trace_id"],"action":"capability.resolve"},caller={"layer":"business_engine","module":"engine-gateway"})
    if registry_status!=200: registration=None
    if not registration or registration["layer"]!="business_engine": handler.send(404,{"error":{"code":"CAPABILITY_NOT_FOUND"}}); return
    status,result=post_json(registration["endpoint"],envelope,timeout=65,caller={"layer":"business_engine","module":"engine-gateway"}); task_id=envelope["payload"].get("platform_task_id")
    if status not in {200,202}:
        if task_id: update_task(task_id,state="failed",error={"code":"DEPENDENCY_UNAVAILABLE"})
        handler.send(502,result); return
    if task_id and capability=="intent.analyze":
        confirmation={"type":"confirmation","id":f"intent-{task_id}","version":"1","tenant_id":envelope["actor"]["tenant_id"]}; update_task(task_id,state="waiting_human",progress=25,confirmation=confirmation,result=result)
    handler.send(202 if task_id else status,result)
