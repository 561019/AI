from typing import Any
from framework.core import standard_response
from framework.http import post_json

def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/content/instructions": handler.send(404); return
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    if payload.get("content_type") == "verified_result_explanation":
        user_result = payload.get("verified_result")
        if not isinstance(user_result, dict) or not user_result.get("summary"):
            handler.send(422, standard_response(envelope, "failed", error={"code": "VERIFIED_RESULT_REQUIRED"})); return
        handler.send(200, standard_response(envelope, "success", data={
            "state": "completed",
            "content": user_result["summary"],
            "user_result": user_result,
            "content_engine": {
                "source": "verified-result-template",
                "component": "content_production.grounded_result_explanation",
                "grounding": "workflow-verified-findings-only",
            },
        }))
        return
    status, result = post_json("http://127.0.0.1:8013/api/v1/delivered-content/generate", {"trace_id": envelope["trace_id"], "actor": envelope["actor"], "task_id": payload.get("platform_task_id"), "parameters": payload}, timeout=70, caller={"layer": "business_engine", "module": "content-adapter"})
    if status != 200 or not result.get("success"):
        handler.send(502, standard_response(envelope, "failed", error={"code": "DELIVERED_CONTENT_ENGINE_FAILED", "details": result})); return
    handler.send(200, standard_response(envelope, "success", data={**result["data"], "content_engine": result["engine_meta"]}))
