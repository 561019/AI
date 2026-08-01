"""Platform model-dispatch client for analysis-prediction engine.

The analysis-prediction engine must not call external model providers
directly in platform integration. All LLM text/JSON generation goes through
the platform foundation gateway and model dispatcher so audit, key management,
policy and cost control stay centralized.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4


def call_platform_model(
    *,
    trace_id: str,
    task_type: str,
    system: str,
    user: str,
    max_tokens: int = 800,
    temperature: float = 0.3,
    output_kind: str = "text",
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from framework.envelope import make_internal_envelope
        from framework.http import post_json
    except Exception as exc:
        return {
            "status": "error",
            "reason": f"platform framework unavailable: {exc}",
            "output": {},
            "text": "",
        }

    normalized_trace_id = trace_id or f"analysis-prediction-{uuid4()}"
    response_instruction = (
        "请只返回 JSON 对象，格式为 {\"content\":\"中文回答\"}。"
        if output_kind == "text"
        else "请只返回符合用户要求的 JSON 对象，不要返回 Markdown。"
    )
    envelope = make_internal_envelope(
        normalized_trace_id,
        actor or {"account_id": "analysis-prediction-engine", "role": "system"},
        normalized_trace_id,
        "model.respond",
        "foundation",
        "foundation-gateway",
        {
            "task_type": task_type,
            "messages": [
                {"role": "system", "content": f"{system}\n{response_instruction}"},
                {"role": "user", "content": user},
            ],
            "model_policy": {
                "quality_level": "high",
                "allow_fallback": False,
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        },
        source_module="analysis-prediction",
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        envelope,
        timeout=45,
        caller={"layer": "business_engine", "module": "analysis-prediction"},
    )
    if status != 200 or not isinstance(response, dict) or response.get("status") != "success":
        return {
            "status": "error",
            "reason": f"platform model gateway failed: {response}",
            "output": {},
            "text": "",
        }

    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    text = _text_from_output(output)
    return {
        "status": "complete",
        "reason": "",
        "output": output,
        "text": text,
        "model": data.get("model"),
        "provider": data.get("provider"),
        "model_call_id": data.get("model_call_id"),
        "usage": data.get("usage"),
    }


def _text_from_output(output: dict[str, Any]) -> str:
    for key in ("content", "narrative", "answer", "summary", "text"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if output:
        return json.dumps(output, ensure_ascii=False)
    return ""
