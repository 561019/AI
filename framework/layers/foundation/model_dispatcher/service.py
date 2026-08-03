from __future__ import annotations

import json
import os
import re
from http.client import RemoteDisconnected
from ssl import SSLError
from time import perf_counter, sleep
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
        handler.send(502, {"error": {"code": "MODEL_PROVIDER_ERROR", "message": f"Model provider HTTP {exc.code}", "provider_error": detail}})
        return
    except (URLError, TimeoutError, ValueError) as exc:
        handler.send(502, {"error": {"code": "MODEL_PROVIDER_ERROR", "message": str(exc)}})
        return
    handler.send(200, result)


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    provider_name, api_key, base, model, timeout_seconds = _provider_config()
    if not api_key:
        return _mock(payload)

    policy = payload.get("model_policy", {})
    if _should_use_compact_intent_prompt(provider_name, model, payload):
        provider_payload = _empty_content_retry_payload(payload=payload, model=model, policy=policy)
    else:
        provider_payload = {
            "model": model,
            "messages": _ensure_json_prompt(payload["messages"]),
            "temperature": policy.get("temperature", 0.1),
            "max_tokens": policy.get("max_output_tokens", 500),
        }
    if _should_disable_thinking(provider_name, model, payload):
        provider_payload["thinking"] = {"type": "disabled"}
    if _supports_response_format(provider_name, model):
        provider_payload["response_format"] = {"type": "json_object"}
    started = perf_counter()
    provider = _call_provider(base=base, api_key=api_key, provider_payload=provider_payload, timeout_seconds=timeout_seconds)

    message = provider["choices"][0].get("message", {})
    content = str(message.get("content") or "").strip()
    retry_used = False
    if not content and _should_retry_empty_content(provider_name, model, payload):
        _record_failed_provider_call(
            payload=payload,
            provider_name=provider_name,
            model=model,
            base=base,
            provider_payload=provider_payload,
            provider=provider,
            error="MODEL_EMPTY_CONTENT",
            content=content,
            started=started,
        )
        provider_payload = _empty_content_retry_payload(payload=payload, model=model, policy=policy)
        started = perf_counter()
        provider = _call_provider(
            base=base,
            api_key=api_key,
            provider_payload=provider_payload,
            timeout_seconds=timeout_seconds,
        )
        message = provider["choices"][0].get("message", {})
        content = str(message.get("content") or "").strip()
        retry_used = True
    usage = provider.get("usage", {})
    fallback_used = False
    try:
        output = _parse_model_json(content)
    except json.JSONDecodeError as exc:
        if _should_retry_malformed_intent_json(provider_name, model, payload, retry_used):
            _record_failed_provider_call(
                payload=payload,
                provider_name=provider_name,
                model=model,
                base=base,
                provider_payload=provider_payload,
                provider=provider,
                error=f"MODEL_JSON_PARSE_RETRYING: {exc}",
                content=content,
                started=started,
            )
            provider_payload = _empty_content_retry_payload(payload=payload, model=model, policy=policy)
            started = perf_counter()
            provider = _call_provider(
                base=base,
                api_key=api_key,
                provider_payload=provider_payload,
                timeout_seconds=timeout_seconds,
            )
            message = provider["choices"][0].get("message", {})
            content = str(message.get("content") or "").strip()
            usage = provider.get("usage", {})
            retry_used = True
            try:
                output = _parse_model_json(content)
            except json.JSONDecodeError as retry_exc:
                exc = retry_exc
            else:
                exc = None
        if exc is None:
            pass
        elif not bool(policy.get("allow_fallback", True)):
            _record_failed_provider_call(
                payload=payload,
                provider_name=provider_name,
                model=model,
                base=base,
                provider_payload=provider_payload,
                provider=provider,
                error=f"MODEL_JSON_PARSE_FAILED: {exc}",
                content=content,
                started=started,
            )
            raise ValueError(f"MODEL_JSON_PARSE_FAILED: {exc}") from exc
        else:
            output = _mock(payload)["output"]
            if isinstance(output, dict):
                output.setdefault("_model_parse_error", str(exc))
            fallback_used = True
    except ValueError as exc:
        if not bool(policy.get("allow_fallback", True)):
            _record_failed_provider_call(
                payload=payload,
                provider_name=provider_name,
                model=model,
                base=base,
                provider_payload=provider_payload,
                provider=provider,
                error=str(exc),
                content=content,
                started=started,
            )
            raise
        output = _mock(payload)["output"]
        if isinstance(output, dict):
            output.setdefault("_model_parse_error", str(exc))
        fallback_used = True

    result = {
        "trace_id": payload["trace_id"],
        "model_call_id": provider.get("id", str(uuid4())),
        "provider": provider_name,
        "model": provider.get("model", model),
        "output": output,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "estimated_cost": 0,
        },
        "fallback_used": fallback_used,
        "provider_retry_used": retry_used,
    }
    record_interface_call(
        trace_id=payload["trace_id"],
        source={"layer": "foundation", "module": "model-dispatcher"},
        target={"layer": "external_provider", "module": provider_name},
        capability="model.chat.completions",
        method="POST",
        url=f"{base}/chat/completions",
        request=provider_payload,
        response=result,
        status_code=200,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return result


def _call_provider(
    *,
    base: str,
    api_key: str,
    provider_payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        request = Request(
            f"{base}/chat/completions",
            data=json.dumps(provider_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError:
            raise
        except (RemoteDisconnected, ConnectionResetError, SSLError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < 2:
                sleep(0.4 * (attempt + 1))
                continue
            break
    raise URLError(f"MODEL_PROVIDER_CONNECTION_FAILED after 3 attempts: {last_error}")


def _supports_response_format(provider_name: str, model: str) -> bool:
    normalized_model = (model or "").strip().lower()
    if provider_name == "deepseek" and normalized_model == "deepseek-v4-flash":
        # This model returns an empty message.content when json_object is sent,
        # even though it returns valid JSON when guided by prompt text alone.
        return False
    return True


def _should_disable_thinking(provider_name: str, model: str, payload: dict[str, Any]) -> bool:
    normalized_model = (model or "").strip().lower()
    return (
        provider_name == "deepseek"
        and normalized_model.startswith("deepseek-v4")
        and str(payload.get("task_type") or "") in {"intent_analysis", "content_generation"}
    )


def _should_use_compact_intent_prompt(provider_name: str, model: str, payload: dict[str, Any]) -> bool:
    return _should_retry_empty_content(provider_name, model, payload)


def _should_retry_empty_content(provider_name: str, model: str, payload: dict[str, Any]) -> bool:
    normalized_model = (model or "").strip().lower()
    return (
        provider_name == "deepseek"
        and normalized_model == "deepseek-v4-flash"
        and str(payload.get("task_type") or "") == "intent_analysis"
    )


def _should_retry_malformed_intent_json(
    provider_name: str,
    model: str,
    payload: dict[str, Any],
    retry_used: bool,
) -> bool:
    return (
        not retry_used
        and _should_retry_empty_content(provider_name, model, payload)
    )


def _empty_content_retry_payload(
    *,
    payload: dict[str, Any],
    model: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if _is_intent_summary_request(payload):
        return _compact_intent_summary_payload(payload=payload, model=model, policy=policy)
    source_messages = payload.get("messages", [])
    user_text = _extract_intent_user_input(source_messages)
    runtime_context = _extract_segmented_runtime_context(source_messages)
    system = (
        "You are an intent analyzer. Return exactly one valid JSON object. "
        "Do not execute the task or invent business facts. "
        "If USER_INPUT contains a clear request, tasks must not be empty. "
        "USER_INPUT is the only source of the new business goal. "
        "CONTEXT is only for resolving references such as 'this file', 'above', or 'previous'. "
        "Do not treat CONTEXT JSON as the user's new request. "
        "If USER_INPUT is a follow-up using pronouns such as it/this/that/above and CONTEXT contains a relevant "
        "assistant execution_result with concrete entity values, use that CONTEXT to fill the referenced object; "
        "do not ask for clarification just because the object is not repeated in USER_INPUT. "
        "Missing files or data are missing_inputs for later workflow steps, not a reason to refuse. "
        "Use DATA_QUERY_FETCH/data.search for retrieval, DATA_AGGREGATION_SUMMARY/data.aggregate for aggregation, "
        "DATA_ANALYSIS_FORECAST/content.generate for forecast, RULE_CALCULATION_GENERAL/rule.calculate for calculations, "
        "CONTENT_GENERATE/content.generate for judgment, risk analysis, recommendations, or final prose. "
        "Use GENERAL_TASK/content.generate if unsure. "
        "Each task needs task_id, task_type, task_description, action, object, capability_code, required_inputs, "
        "missing_inputs, clarification_required, clarification_questions, status, dependencies, confidence. "
        "task_type must be one of DATA_QUERY_FETCH, DATA_AGGREGATION_SUMMARY, DATA_ANALYSIS_FORECAST, "
        "RULE_CALCULATION_GENERAL, CONTENT_GENERATE, GENERAL_TASK. "
        "status must be ready, needs_clarification, or waiting_dependency. Use ready when no clarification is needed. "
        "dependencies must contain task_id strings such as task_1, never numbers. "
        "Return envelope: {\"result\":{\"tasks\":[],"
        "\"clarification_required\":false,\"global_clarification_required\":false,"
        "\"clarification_questions\":[],\"overall_confidence\":0.0},"
        "\"evidence_spans\":[]}. "
        "Add one evidence_spans item per task: {\"task_index\":0,\"evidence_span\":\"exact substring\"}. "
        "Keep text short and in the same language as USER_INPUT."
    )
    user_content = f"USER_INPUT:\n{user_text}"
    if runtime_context:
        user_content += f"\n\nCONTEXT:\n{runtime_context}"
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": policy.get("temperature", 0.1),
        "max_tokens": max(int(policy.get("max_output_tokens", 500) or 500), 4096),
        **({"thinking": {"type": "disabled"}} if (model or "").strip().lower().startswith("deepseek-v4") else {}),
    }


def _is_intent_summary_request(payload: dict[str, Any]) -> bool:
    messages = payload.get("messages")
    if isinstance(messages, list):
        combined = "\n".join(str(item.get("content") or "") for item in messages if isinstance(item, dict))
        return "MODEL_TASK_OUTPUT" in combined and (
            "user_facing_intent_summary" in combined
            or "intent confirmation summary" in combined
            or "质量自检" in combined
        )
    return False


def _compact_intent_summary_payload(
    *,
    payload: dict[str, Any],
    model: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    messages = payload.get("messages", [])
    user_text = (
        _extract_marked_block_from_messages(
            messages,
            "USER_INPUT",
            stop_markers=("UPLOADED_DOCUMENTS", "MODEL_TASK_OUTPUT", "CONTEXT", "SEGMENTED_RUNTIME_CONTEXT"),
        )
        or _extract_intent_user_input(messages)
    )
    runtime_context = _extract_segmented_runtime_context(messages)
    task_output = _extract_marked_block_from_messages(messages, "MODEL_TASK_OUTPUT", stop_markers=("CONTEXT", "SEGMENTED_RUNTIME_CONTEXT"))
    uploaded_documents = _extract_marked_block_from_messages(messages, "UPLOADED_DOCUMENTS", stop_markers=("MODEL_TASK_OUTPUT", "CONTEXT", "SEGMENTED_RUNTIME_CONTEXT"))
    system = (
        "You rewrite an intent confirmation summary. Return exactly one valid JSON object and nothing else. "
        "Do not execute the business task, do not query data, do not calculate, and do not invent facts. "
        "Return only this shape: {\"user_facing_intent_summary\":{\"business_goal\":\"...\","
        "\"task_list\":[\"...\"],\"data_scope\":\"...\",\"output_focus\":\"...\","
        "\"confirmation_question\":\"...\"}}. "
        "The value of user_facing_intent_summary must be an object, not a string. "
        "Use USER_INPUT as the new business goal. Use CONTEXT only to resolve references such as 'it' or 'above'. "
        "If MODEL_TASK_OUTPUT contains ready tasks, summarize those concrete tasks. "
        "Keep Chinese input in clear Chinese. task_list must contain concrete user-verifiable business items."
    )
    user_content = f"USER_INPUT:\n{user_text}"
    if uploaded_documents:
        user_content += f"\n\nUPLOADED_DOCUMENTS:\n{uploaded_documents}"
    if task_output:
        user_content += f"\n\nMODEL_TASK_OUTPUT:\n{task_output}"
    if runtime_context:
        user_content += f"\n\nCONTEXT:\n{runtime_context}"
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": policy.get("temperature", 0.1),
        "max_tokens": max(int(policy.get("max_output_tokens", 500) or 500), 1200),
        **({"thinking": {"type": "disabled"}} if (model or "").strip().lower().startswith("deepseek-v4") else {}),
    }


def _extract_marked_block_from_messages(messages: Any, marker: str, *, stop_markers: tuple[str, ...]) -> str:
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if not isinstance(item, dict):
            continue
        text = str(item.get("content") or "")
        value = _extract_marked_block(text, marker, stop_markers=stop_markers)
        if value:
            return value
    return ""


def _extract_intent_user_input(messages: Any) -> str:
    """Return the real user request, not injected runtime context."""
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        candidate = _clean_user_input_candidate(str(item.get("content") or ""))
        if candidate:
            return candidate
    for item in reversed(messages):
        if not isinstance(item, dict):
            continue
        candidate = _clean_user_input_candidate(str(item.get("content") or ""))
        if candidate:
            return candidate
    return _last_user_message(messages)


def _clean_user_input_candidate(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    if text.startswith("SEGMENTED_RUNTIME_CONTEXT:"):
        embedded = _extract_marked_block(text, "USER_INPUT", stop_markers=("CONTEXT",))
        return embedded if embedded and not embedded.startswith("SEGMENTED_RUNTIME_CONTEXT:") else ""
    marked = _extract_marked_block(text, "USER_INPUT", stop_markers=("CONTEXT", "SEGMENTED_RUNTIME_CONTEXT"))
    if marked:
        if marked.startswith("SEGMENTED_RUNTIME_CONTEXT:"):
            return ""
        return marked
    # Rendered full prompts contain the user text in a dedicated USER_INPUT
    # section. Plain user messages do not contain the structured prompt header.
    if "你是企业工作流平台的“意图分析与任务分配器”" in text:
        return ""
    return text


def _extract_segmented_runtime_context(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    for item in messages:
        if not isinstance(item, dict):
            continue
        text = str(item.get("content") or "").strip()
        if text.startswith("SEGMENTED_RUNTIME_CONTEXT:"):
            return text
        marker_index = text.find("SEGMENTED_RUNTIME_CONTEXT:")
        if marker_index >= 0:
            return text[marker_index:].strip()
    return ""


def _extract_marked_block(text: str, marker: str, *, stop_markers: tuple[str, ...]) -> str:
    pattern = re.compile(rf"(?im)^\s*{re.escape(marker)}\s*:\s*")
    matches = list(pattern.finditer(text))
    if not matches:
        return ""
    start = matches[-1].end()
    end = len(text)
    for stop_marker in stop_markers:
        stop_pattern = re.compile(rf"(?im)^\s*{re.escape(stop_marker)}\s*:\s*")
        stop_match = stop_pattern.search(text, start)
        if stop_match:
            end = min(end, stop_match.start())
    return text[start:end].strip()


def _last_user_message(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if isinstance(item, dict) and item.get("role") == "user":
            return str(item.get("content") or "")
    for item in reversed(messages):
        if isinstance(item, dict):
            return str(item.get("content") or "")
    return ""


def _record_failed_provider_call(
    *,
    payload: dict[str, Any],
    provider_name: str,
    model: str,
    base: str,
    provider_payload: dict[str, Any],
    provider: dict[str, Any],
    error: str,
    content: str,
    started: float,
) -> None:
    record_interface_call(
        trace_id=payload["trace_id"],
        source={"layer": "foundation", "module": "model-dispatcher"},
        target={"layer": "external_provider", "module": provider_name},
        capability="model.chat.completions",
        method="POST",
        url=f"{base}/chat/completions",
        request=provider_payload,
        response={
            "provider": provider_name,
            "model": provider.get("model", model),
            "error": error,
            "finish_reason": (provider.get("choices") or [{}])[0].get("finish_reason"),
            "usage": provider.get("usage", {}),
            "content_preview": content[:500],
            "content_length": len(content),
            "reasoning_length": len(str((provider.get("choices") or [{}])[0].get("message", {}).get("reasoning_content") or "").strip()),
        },
        status_code=502,
        duration_ms=(perf_counter() - started) * 1000,
    )


def _provider_config() -> tuple[str, str, str, str, float]:
    """Select the explicitly configured OpenAI-compatible provider."""
    requested = os.getenv("MODEL_PROVIDER", "doubao").strip().lower()
    providers = {
        "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_TIMEOUT_SECONDS", "https://api.deepseek.com", "deepseek-chat"),
        "doubao": ("DOUBAO_API_KEY", "DOUBAO_BASE_URL", "DOUBAO_MODEL", "DOUBAO_TIMEOUT_SECONDS", "https://ark.cn-beijing.volces.com/api/v3", ""),
    }
    if requested not in providers:
        raise ValueError(f"MODEL_PROVIDER_UNSUPPORTED: {requested}")
    key_name, base_name, model_name, timeout_name, default_base, default_model = providers[requested]
    api_key = os.getenv(key_name, "").strip()
    if not api_key:
        return "local-mock", "", "", "", 0.0
    model = os.getenv(model_name, default_model).strip()
    if not model:
        raise ValueError(f"{model_name} is required when MODEL_PROVIDER={requested}")
    base = os.getenv(base_name, default_base).strip().rstrip("/")
    timeout = float(os.getenv(timeout_name, "30"))
    return requested, api_key, base, model, timeout


def _parse_model_json(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        # Some OpenAI-compatible providers occasionally put literal newlines or
        # tabs inside a JSON string.  They are valid model text but strict JSON
        # parsing rejects them as "Invalid control character".
        payload = json.loads(text, strict=False)
    except json.JSONDecodeError:
        extracted = _extract_first_json_object(text)
        if not extracted:
            raise
        payload = json.loads(extracted, strict=False)
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("model output must be a JSON object", text, 0)
    return payload


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


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
