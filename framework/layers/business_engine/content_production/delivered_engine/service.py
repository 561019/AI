from __future__ import annotations
import sys
from pathlib import Path
from typing import Any
from framework.envelope import make_internal_envelope
from framework.http import post_json

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "联调文件-7.20-解压" / "2.8-2.9交付资料" / "engines" / "content_engine_v0_2"
sys.path.insert(0, str(SOURCE)) if str(SOURCE) not in sys.path else None
from backend.models import IntegrationSubtaskRequest  # noqa: E402
from backend.task_adapter import adapt_content_subtask  # noqa: E402

def post(handler: Any, request: dict[str, Any]) -> None:
    if handler.path != "/api/v1/delivered-content/generate": handler.send(404); return
    params = request.get("parameters") or {}
    requirement = params.get("utterance") or params.get("description") or params.get("action") or "生成文字内容"
    original_request = IntegrationSubtaskRequest(trace_id=request["trace_id"], task_id=request.get("task_id"), actor=request.get("actor", {}), capability={"capability_id": "content_generic_draft"}, input={**params, "requirement": requirement}, input_brief=requirement, content_type=params.get("content_type", "generic_text_draft"))
    adapted = adapt_content_subtask(original_request)
    if not adapted.get("accepted"):
        handler.send(422, {"success": False, "error": {"code": adapted.get("code"), "message": adapted.get("message")}}); return
    envelope = make_internal_envelope(request["trace_id"], request.get("actor", {}), request.get("task_id") or request["trace_id"], "model.respond", "foundation", "foundation-gateway", {"task_type": "content_generation", "messages": [{"role": "system", "content": "你是企业内容产出引擎。只依据用户要求生成可直接审阅的中文文字初稿，不虚构未提供的事实。必须返回 JSON 对象，格式为 {\"content\": \"正文\"}。"}, {"role": "user", "content": requirement}], "model_policy": {"quality_level": "high", "allow_fallback": False, "temperature": 0.4, "max_output_tokens": 1800}}, source_module="content-production-engine-original")
    status, model = post_json("http://127.0.0.1:8300/api/v1/foundation/instructions", envelope, timeout=60, caller={"layer": "business_engine", "module": "content-production-engine-original"})
    if status != 200 or model.get("status") != "success": handler.send(502, {"success": False, "error": {"code": "MODEL_FAILED", "details": model}}); return
    data = model["data"]
    output = data.get("output")
    content = output if isinstance(output, str) else (output.get("content") if isinstance(output, dict) else str(output))
    handler.send(200, {"success": True, "data": {"state": "completed", "content": content, "normalized_task": adapted.get("normalized"), "missing_fields": adapted.get("missing_fields", [])}, "engine_meta": {"source": "user-delivered-module", "component": "adapt_content_subtask", "generation": "platform-model-gateway", "provider": data.get("provider"), "model": data.get("model"), "model_call_id": data.get("model_call_id"), "delivery_root": str(SOURCE)}})
