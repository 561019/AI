from typing import Any
from framework.core import standard_response,validate_envelope
from framework.http import post_json

def post(handler:Any,envelope:dict[str,Any])->None:
    if handler.path!="/api/v1/foundation/instructions": handler.send(404); return
    if validate_envelope(envelope): handler.send(400,{"error":{"code":"INVALID_REQUEST"}}); return
    source=envelope["source"]
    allowed_business_modules={"workflow-execution","workflow-execution-engine-original","engine-gateway","rule-adapter","intent-adapter","intent-analysis-engine-original","content-production-engine-original","document-table-parsing","analysis-prediction","data-operation","digital-asset","project-management","monitoring-reminder","external-system-integration","knowledge-qa","knowledge-map","multimedia-generation"}
    allowed_foundation_modules={"account-gateway","context-prompt-management","knowledge-base","memory-management","human-collaboration","security-compliance","cost-control","device-system-interface","execution-sandbox","evolution-mechanism","control-mechanism"}
    source_allowed=(
        source.get("layer")=="business_engine" and source.get("module") in allowed_business_modules
    ) or (
        source.get("layer")=="foundation" and source.get("module") in allowed_foundation_modules
    )
    if not source_allowed: handler.send(403,{"error":{"code":"SOURCE_LAYER_FORBIDDEN"}}); return
    capability=envelope["target"].get("capability") or "permissions.check"
    registry_status,registration=post_json(f"http://127.0.0.1:8400/api/v1/capabilities/{capability}/resolve",{"trace_id":envelope["trace_id"],"action":"capability.resolve"},caller={"layer":"foundation","module":"foundation-gateway"})
    if registry_status!=200: registration=None
    if not registration or registration["layer"]!="foundation": handler.send(404,{"error":{"code":"CAPABILITY_NOT_FOUND"}}); return
    if capability=="model.respond":
        request=dict(envelope.get("payload",{})); request.setdefault("trace_id",envelope["trace_id"]); request.setdefault("actor",envelope["actor"])
        status,response=post_json(registration["endpoint"],request,timeout=40,caller={"layer":"foundation","module":"foundation-gateway"})
        if status!=200: handler.send(502,standard_response(envelope,"failed",error={"code":"MODEL_UPSTREAM_FAILED","message":"model dispatcher unavailable","retryable":True})); return
        handler.send(200,standard_response(envelope,"success",data=response)); return
    if capability.startswith("template."):
        status,response=post_json(registration["endpoint"],envelope,caller={"layer":"foundation","module":"foundation-gateway"})
        if status!=200 or response.get("status")!="success": handler.send(502,standard_response(envelope,"failed",error={"code":"TEMPLATE_UPSTREAM_FAILED","details":response,"retryable":False})); return
        handler.send(200,response); return
    if capability!="permissions.check":
        status,response=post_json(registration["endpoint"],envelope,caller={"layer":"foundation","module":"foundation-gateway"})
        if status!=200 or response.get("status")!="success": handler.send(502,standard_response(envelope,"failed",error={"code":"FOUNDATION_UPSTREAM_FAILED","details":response,"retryable":False})); return
        handler.send(200,response); return
    request={"actor":envelope["actor"],"action":envelope["action"],"resource":envelope["payload"].get("resource",{}),"scope":envelope["payload"].get("scope",{}),"trace_id":envelope["trace_id"],"context":envelope.get("context") if isinstance(envelope.get("context"),dict) else {},"platform_task_id":(envelope.get("payload") or {}).get("platform_task_id")}
    status,response=post_json(registration["endpoint"],request,caller={"layer":"foundation","module":"foundation-gateway"})
    if status!=200: handler.send(503,standard_response(envelope,"failed",error={"code":"DEPENDENCY_UNAVAILABLE","message":"permission unavailable","retryable":True})); return
    handler.send(200,standard_response(envelope,"success",data=response))
