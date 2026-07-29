from __future__ import annotations

import json
import os
import re
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from framework.core import record_interface_call


def post(handler: Any, payload: dict[str, Any]) -> None:
    if handler.path != "/api/v1/models/responses":
        handler.send(404)
        return
    missing = [key for key in ("trace_id", "actor", "task_type", "messages", "model_policy") if key not in payload]
    if missing:
        handler.send(400, {"error": {"code": "INVALID_MODEL_REQUEST", "message": f"缺少字段: {missing}"}})
        return
    try:
        result = dispatch(payload)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        handler.send(502, {"error": {"code": "MODEL_PROVIDER_ERROR", "message": f"DeepSeek HTTP {exc.code}", "provider_error": detail}})
        return
    except (URLError, TimeoutError, ValueError) as exc:
        handler.send(502, {"error": {"code": "MODEL_PROVIDER_ERROR", "message": str(exc)}})
        return
    handler.send(200, result)


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return _mock(payload)

    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    policy = payload.get("model_policy", {})
    provider_payload = {
        "model": model,
        "messages": _ensure_json_prompt(payload["messages"]),
        "temperature": policy.get("temperature", 0.1),
        "max_tokens": policy.get("max_output_tokens", 500),
        "response_format": {"type": "json_object"},
    }
    request = Request(
        f"{base}/chat/completions",
        data=json.dumps(provider_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = perf_counter()
    with urlopen(request, timeout=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30"))) as response:
        provider = json.loads(response.read().decode("utf-8"))

    content = provider["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    usage = provider.get("usage", {})
    fallback_used = False
    try:
        output = json.loads(content)
    except json.JSONDecodeError as exc:
        output = _mock(payload)["output"]
        if isinstance(output, dict):
            output.setdefault("_model_parse_error", str(exc))
        fallback_used = True

    result = {
        "trace_id": payload["trace_id"],
        "model_call_id": provider.get("id", str(uuid4())),
        "provider": "deepseek",
        "model": provider.get("model", model),
        "output": output,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "estimated_cost": 0,
        },
        "fallback_used": fallback_used,
    }
    record_interface_call(
        trace_id=payload["trace_id"],
        source={"layer": "foundation", "module": "model-dispatcher"},
        target={"layer": "external_provider", "module": "deepseek"},
        capability="model.chat.completions",
        method="POST",
        url=f"{base}/chat/completions",
        request=provider_payload,
        response=result,
        status_code=200,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return result


def _ensure_json_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = " ".join(str(item.get("content", "")) for item in messages)
    if "json" in text.lower():
        return messages
    return [{"role": "system", "content": "You must return a valid JSON object. Do not return markdown."}, *messages]


def _mock(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages", [])
    text = next((str(item.get("content", "")) for item in reversed(messages) if item.get("role") == "user"), "")
    if not text:
        text = next((str(item.get("content", "")) for item in reversed(messages)), "")
    task_type = str(payload.get("task_type") or "")
    if task_type == "intent_analysis":
        output = _mock_intent_output(text)
    elif task_type == "content_generation":
        output = {"content": "当前未配置可用大模型，平台不能基于复杂业务问题形成可信结论；请配置模型 Key 后重试。"}
    else:
        values = [float(value) for value in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text)]
        capability = "rule.calculate" if any(word in text for word in ("计算", "提成", "金额", "比例")) else "knowledge.answer"
        output = {"capability_code": capability, "description": text, "confidence": 0.92, "clarification_required": False, "parameters": {"values": values}}
    return {
        "trace_id": payload["trace_id"],
        "model_call_id": f"mock-{uuid4()}",
        "provider": "local-mock",
        "model": "mock-intent-model",
        "output": output,
        "usage": {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0},
        "fallback_used": True,
    }


def _mock_intent_output(text: str) -> dict[str, Any]:
    user_text = _extract_user_input(text)
    # This is only the no-key development fallback. Keep it generic and
    # structured so the workflow engine can decide what to do next; it must
    # never fabricate a data result or choose a fixed business scenario.
    task_type = "CONTENT_GENERATE"
    required = []
    action = "generate"
    obj = "user_requested_result"
    task = {
        "task_id": "fallback-task-1",
        "task_type": task_type,
        "task_description": user_text or text,
        "action": action,
        "object": obj,
        "capability_code": "content.generate",
        "data_scope": "current conversation uploads or authorized project data",
        "operation": "answer",
        "output_schema": {
            "type": "user_readable_result",
            "requires_evidence": True,
        },
        "expected_outputs": ["user_readable_result", "evidence", "limitations"],
        "required_inputs": required,
        "missing_inputs": [],
        "clarification_required": False,
        "clarification_questions": [],
        "status": "ready",
        "dependencies": [],
        "confidence": 0.62,
    }
    return {
        "result": {
            "tasks": [task],
            "clarification_required": False,
            "global_clarification_required": False,
            "clarification_questions": [],
            "overall_confidence": 0.62,
        },
        "evidence_spans": [{"task_index": 0, "evidence_span": user_text or text[:80]}],
    }


def _extract_user_input(text: str) -> str:
    marker = "User input:"
    if marker not in text:
        return text.strip()
    tail = text.split(marker, 1)[1]
    for stop in ("\n\nContext:", "\n\nUser id:"):
        if stop in tail:
            tail = tail.split(stop, 1)[0]
    return tail.strip()
