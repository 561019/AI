from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from framework.envelope import make_internal_envelope
from framework.http import post_json


DELIVERY_ROOT = Path(__file__).resolve().parents[5] / "联调文件-7.20-解压" / "intent-analysis-engine-handoff-20260720-173426"
BACKEND_ROOT = DELIVERY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer  # noqa: E402
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog  # noqa: E402
from app.services.model_gateway.schemas.llm_response import LLMResponse  # noqa: E402


class PlatformModelGateway:
    """Connects the delivered engine to the platform model gateway over HTTP."""

    def __init__(self, *, trace_id: str, actor: dict[str, Any], task_id: str) -> None:
        self.trace_id = trace_id
        self.actor = actor
        self.task_id = task_id
        self.last_model: dict[str, Any] = {}

    def analyze(self, messages: list[dict[str, str]], response_schema: dict[str, Any] | None = None) -> LLMResponse:
        envelope = make_internal_envelope(
            self.trace_id, self.actor, self.task_id, "model.respond", "foundation", "foundation-gateway",
            {
                "task_type": "intent_analysis", "messages": messages,
                "response_schema": response_schema or {"type": "object"},
                "model_policy": {"quality_level": "high", "allow_fallback": False, "sensitive_data": False, "temperature": 0.1, "max_output_tokens": 1800},
            },
            source_module="intent-analysis-engine-original",
        )
        status, response = post_json(
            "http://127.0.0.1:8300/api/v1/foundation/instructions", envelope,
            timeout=45, caller={"layer": "business_engine", "module": "intent-analysis-engine-original"},
        )
        if status != 200 or response.get("status") != "success":
            raise RuntimeError(f"platform model gateway failed: {response}")
        model = response["data"]
        self.last_model = model
        output = model.get("output") or {}
        return LLMResponse(
            provider=model.get("provider", "unknown"), model=model.get("model", "unknown"),
            content=json.dumps(output, ensure_ascii=False), parsed_json=output,
            request_id=model.get("model_call_id", ""), fallback_used=bool(model.get("fallback_used", False)),
        )


def post(handler: Any, request: dict[str, Any]) -> None:
    if handler.path != "/api/v1/delivered-intent/analyze":
        handler.send(404); return
    text = str(request.get("text", "")).strip()
    if not text:
        handler.send(422, {"success": False, "error": {"code": "EMPTY_TEXT"}}); return
    gateway = PlatformModelGateway(trace_id=request["trace_id"], actor=request["actor"], task_id=request.get("platform_task_id", request["trace_id"]))
    analyzer = LLMTaskAnalyzer(model_gateway=gateway, registry=FunctionRegistryCatalog(), confidence_threshold=0.0)
    outcome = analyzer.analyze_with_validation(text, user_id=request.get("user_id", "unknown"))
    result = outcome.result
    if result is None:
        handler.send(422, {"success": False, "error": {"code": "DELIVERED_INTENT_REJECTED", "reasons": outcome.rejection_reasons}, "engine_meta": {"delivery_root": str(DELIVERY_ROOT), "component": "LLMTaskAnalyzer"}}); return
    handler.send(200, {
        "success": True,
        "data": result.model_dump(mode="json"),
        "validation": {"rejection_reasons": outcome.rejection_reasons, "contract_corrections": outcome.contract_corrections, "contract_errors": outcome.contract_errors},
        "engine_meta": {"delivery_root": str(DELIVERY_ROOT), "component": "LLMTaskAnalyzer", "source": "user-delivered-module", "provider": gateway.last_model.get("provider"), "model": gateway.last_model.get("model"), "model_call_id": gateway.last_model.get("model_call_id"), "fallback_used": gateway.last_model.get("fallback_used", False), "model_output": gateway.last_model.get("output") or {}},
    })
