from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import CAPABILITY_TO_MODULE


DELIVERY_ROOT = Path(__file__).resolve().parents[5] / "联调文件-7.20-解压" / "intent-analysis-engine-release-20260728-103356"
BACKEND_ROOT = DELIVERY_ROOT / "backend"
STRUCTURED_PROMPT = Path(__file__).resolve().parents[1] / "structured_intent_prompt.txt"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.intent_analysis_engine.llm import LLMTaskAnalyzer  # noqa: E402
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog  # noqa: E402
from app.services.model_gateway.schemas.llm_response import LLMResponse  # noqa: E402


class PlatformModelGateway:
    """Connects the delivered engine to the platform model gateway over HTTP."""

    def __init__(
        self,
        *,
        trace_id: str,
        actor: dict[str, Any],
        task_id: str,
        runtime_context: str = "",
    ) -> None:
        self.trace_id = trace_id
        self.actor = actor
        self.task_id = task_id
        self.runtime_context = runtime_context
        self.last_model: dict[str, Any] = {}

    def analyze(self, messages: list[dict[str, str]], response_schema: dict[str, Any] | None = None) -> LLMResponse:
        model_messages = list(messages)
        if self.runtime_context:
            model_messages.insert(1 if model_messages and model_messages[0].get("role") == "system" else 0, {
                "role": "system",
                "content": (
                    self.runtime_context
                    + "\n意图分析边界：只识别任务并分配能力，不执行任务，不生成业务结论。\n"
                    "USER_INPUT 是唯一的新业务目标来源；CURRENT_CONTEXT 只能补全指代；MEMORY 只能做背景参考。\n"
                    "AUTHORIZED_DATA_SCOPE 只表示允许读取的资料范围，不能当成已经解析出的业务事实。\n"
                    "每个任务必须从候选 task_type 中选择，并写出可映射到平台能力表的 capability_code。\n"
                    "不能确定的信息放入 missing_inputs，不要猜测，不要补默认范围。\n"
                ),
            })
        envelope = make_internal_envelope(
            self.trace_id, self.actor, self.task_id, "model.respond", "foundation", "foundation-gateway",
            {
                "task_type": "intent_analysis", "messages": model_messages,
                "response_schema": _schema_with_user_facing_summary(response_schema or {"type": "object"}),
                # Intent analysis returns a compact task list, not a report.
                # Keeping this bounded prevents a small user request from
                # reserving a multi-thousand-token model response.
                "model_policy": {"quality_level": "high", "allow_fallback": False, "sensitive_data": False, "temperature": 0.1, "max_output_tokens": 1024},
            },
            source_module="intent-analysis-engine-original",
        )
        status, response = post_json(
            "http://127.0.0.1:8300/api/v1/foundation/instructions", envelope,
            # This must exceed the gateway timeout, otherwise intent analysis
            # would end early even when the model is still responding.
            timeout=195, caller={"layer": "business_engine", "module": "intent-analysis-engine-original"},
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
    gateway = PlatformModelGateway(
        trace_id=request["trace_id"],
        actor=request["actor"],
        task_id=request.get("platform_task_id", request["trace_id"]),
        runtime_context=_build_runtime_context(
            request.get("uploaded_documents"),
            request.get("conversation_context"),
            request.get("project_context"),
            request.get("historical_projects"),
        ),
    )
    analyzer = LLMTaskAnalyzer(
        model_gateway=gateway,
        registry=FunctionRegistryCatalog(),
        prompt_path=STRUCTURED_PROMPT,
        confidence_threshold=0.0,
    )
    try:
        outcome = analyzer.analyze_with_validation(
            text,
            user_id=request.get("user_id", "unknown"),
            context={
                "current_conversation": {
                    "items": request.get("conversation_context") if isinstance(request.get("conversation_context"), list) else [],
                },
                "current_project": {
                    "items": request.get("project_context") if isinstance(request.get("project_context"), list) else [],
                },
                "historical_projects": {
                    "items": request.get("historical_projects") if isinstance(request.get("historical_projects"), list) else [],
                },
            },
        )
    except RuntimeError as exc:
        message = str(exc)
        if "ModelNotOpen" in message or "InvalidEndpointOrModel.NotFound" in message:
            handler.send(422, {
                "success": False,
                "error": {
                    "code": "DOUBAO_MODEL_UNAVAILABLE",
                    "message": "当前豆包模型不存在，或你的账号尚未开通它。",
                    "details": {
                        "suggestion": "请在火山方舟控制台开通 DOUBAO_MODEL 对应的模型服务，或填写已开通的推理接入点 ID。不要填写未开通的公开模型名称。",
                        "raw_message": message,
                    },
                    "retryable": False,
                },
                "engine_meta": {
                    "delivery_root": str(DELIVERY_ROOT),
                    "component": "LLMTaskAnalyzer",
                    "source": "user-delivered-module",
                },
            })
            return
        if "timed out" in message.lower() or "timeout" in message.lower():
            handler.send(504, {
                "success": False,
                "error": {
                    "code": "MODEL_RESPONSE_TIMEOUT",
                    "message": "豆包模型响应超时，当前请求尚未得到结果。",
                    "details": {
                        "suggestion": "系统会等待更长时间后再结束请求；若持续出现，请检查网络连接或豆包服务状态。",
                        "raw_message": message,
                    },
                    "retryable": True,
                },
                "engine_meta": {
                    "delivery_root": str(DELIVERY_ROOT),
                    "component": "LLMTaskAnalyzer",
                    "source": "user-delivered-module",
                },
            })
            return
        error = {
            "code": "MODEL_GATEWAY_UNAVAILABLE",
            "message": "模型网关当前不可用，意图分析没有拿到大模型结果。",
            "details": {
                "raw_message": message,
                "suggestion": "请检查本机网络、DNS、代理设置，以及 framework/config/model.env 中的 DEEPSEEK_BASE_URL、DEEPSEEK_MODEL 和模型 Key。",
            },
            "retryable": True,
        }
        if "getaddrinfo failed" in message:
            error["message"] = "模型供应商域名解析失败，当前机器无法访问大模型服务。"
            error["details"]["network_cause"] = "DNS_RESOLUTION_FAILED"
        handler.send(502, {
            "success": False,
            "error": error,
            "engine_meta": {
                "delivery_root": str(DELIVERY_ROOT),
                "component": "LLMTaskAnalyzer",
                "source": "user-delivered-module",
                "provider": gateway.last_model.get("provider"),
                "model": gateway.last_model.get("model"),
            },
        })
        return
    result = outcome.result
    if result is None:
        handler.send(422, {"success": False, "error": {"code": "DELIVERED_INTENT_REJECTED", "reasons": outcome.rejection_reasons}, "engine_meta": {"delivery_root": str(DELIVERY_ROOT), "component": "LLMTaskAnalyzer"}}); return
    model_record = dict(gateway.last_model)
    model_output = model_record.get("output") if isinstance(model_record.get("output"), dict) else {}
    if _summary_requires_model_refinement(model_output):
        refined_summary = _refine_user_facing_summary_with_model(
            gateway,
            text=text,
            uploaded_documents=request.get("uploaded_documents"),
            model_output=model_output,
        )
        refinement_record = dict(gateway.last_model)
        model_record["output"] = _model_output_with_summary(model_output, refined_summary) if refined_summary else model_output
        model_record["intent_summary_refinement"] = {
            "attempted": True,
            "accepted": bool(refined_summary),
            "provider": refinement_record.get("provider"),
            "model": refinement_record.get("model"),
            "model_call_id": refinement_record.get("model_call_id"),
        }
        gateway.last_model = model_record
    handler.send(200, {
        "success": True,
        "data": result.model_dump(mode="json"),
        "validation": {"rejection_reasons": outcome.rejection_reasons, "contract_corrections": outcome.contract_corrections, "contract_errors": outcome.contract_errors},
        "engine_meta": {"delivery_root": str(DELIVERY_ROOT), "component": "LLMTaskAnalyzer", "source": "user-delivered-module", "provider": gateway.last_model.get("provider"), "model": gateway.last_model.get("model"), "model_call_id": gateway.last_model.get("model_call_id"), "fallback_used": gateway.last_model.get("fallback_used", False), "intent_summary_refinement": gateway.last_model.get("intent_summary_refinement"), "model_output": gateway.last_model.get("output") or {}},
    })


def _build_runtime_context(
    uploaded_documents: Any,
    conversation_context: Any = None,
    project_context: Any = None,
    historical_projects: Any = None,
) -> str:
    """Expose segmented context without presenting it as user wording."""
    documents = uploaded_documents if isinstance(uploaded_documents, list) else []
    readable_documents = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        name = str(document.get("file_name") or document.get("name") or "未命名文件").strip()
        file_type = str(document.get("file_type") or document.get("mime_type") or "").strip()
        readable_documents.append({
            "file_name": name,
            "file_type": file_type,
            "source": document.get("source") or document.get("origin") or "current_upload",
        })
    segmented_context = {
        "AUTHORIZED_DATA_SCOPE": {
            "current_uploaded_documents": readable_documents,
            "note": "这只是可读取范围，不代表文件已经被解析或已经得到业务结果。",
        },
        "CURRENT_CONTEXT": {
            "conversation_items": conversation_context if isinstance(conversation_context, list) else [],
            "project_items": project_context if isinstance(project_context, list) else [],
            "usage_rule": "只能补全当前用户问题里的指代，不能生成新任务。",
        },
        "MEMORY": {
            "historical_project_items": historical_projects if isinstance(historical_projects, list) else [],
            "usage_rule": "只能做背景参考，不能生成新任务；与用户当前问题冲突时，以用户当前问题为准。",
        },
        "PLATFORM_CAPABILITY_CODES": sorted(CAPABILITY_TO_MODULE),
    }
    return "SEGMENTED_RUNTIME_CONTEXT:\n" + json.dumps(segmented_context, ensure_ascii=False)


def _schema_with_user_facing_summary(schema: dict[str, Any]) -> dict[str, Any]:
    """Allow the platform prompt to carry a model-written confirmation summary.

    The delivered IntentAnalysisResult contract ignores unknown fields after
    validation, so the platform adapter reads this field from raw model output.
    It still needs to be present in the response schema sent to the model.
    """
    patched = deepcopy(schema) if isinstance(schema, dict) else {"type": "object"}
    result_schema = (
        patched.get("properties", {}).get("result")
        if isinstance(patched.get("properties"), dict)
        else None
    )
    if not isinstance(result_schema, dict):
        return patched
    properties = result_schema.setdefault("properties", {})
    if not isinstance(properties, dict):
        return patched
    properties["user_facing_intent_summary"] = {
        "type": "object",
        "properties": {
            "business_goal": {"type": "string"},
            "task_list": {"type": "array", "items": {"type": "string"}},
            "data_scope": {"type": "string"},
            "output_focus": {"type": "string"},
            "confirmation_question": {"type": "string"},
        },
        "required": ["business_goal", "task_list", "data_scope", "output_focus", "confirmation_question"],
    }
    return patched


GENERIC_SUMMARY_TEXTS = {
    "",
    "基于前面统计分析结果生成后续执行意见",
    "处理当前对话中的业务请求",
    "根据现有资料生成内容",
    "汇总当前资料并输出结论",
    "执行识别到的业务能力",
    "按问题要求统计数量或汇总指标",
    "预测趋势或下周期业务指标",
    "调用对应模块处理任务",
    "生成用户可读回答",
}

GENERIC_SUMMARY_PREFIXES = (
    "回答用户问题：",
    "处理用户问题：",
    "处理当前问题：",
)


def _summary_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "user_facing_intent_summary": {
                "type": "object",
                "properties": {
                    "business_goal": {"type": "string"},
                    "task_list": {"type": "array", "items": {"type": "string"}},
                    "data_scope": {"type": "string"},
                    "output_focus": {"type": "string"},
                    "confirmation_question": {"type": "string"},
                },
                "required": ["business_goal", "task_list", "data_scope", "output_focus", "confirmation_question"],
            }
        },
        "required": ["user_facing_intent_summary"],
    }


def _summary_from_model_output(model_output: dict[str, Any]) -> dict[str, Any] | None:
    summary = model_output.get("user_facing_intent_summary")
    if isinstance(summary, dict):
        return summary
    result = model_output.get("result")
    if isinstance(result, dict):
        summary = result.get("user_facing_intent_summary")
        if isinstance(summary, dict):
            return summary
    return None


def _summary_requires_model_refinement(model_output: dict[str, Any]) -> bool:
    return not _summary_is_specific(_summary_from_model_output(model_output))


def _summary_is_specific(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    business_goal = str(summary.get("business_goal") or "").strip()
    task_list = summary.get("task_list") or summary.get("planned_steps")
    if not business_goal or not isinstance(task_list, list) or not task_list:
        return False
    for item in task_list:
        text = str(item or "").strip()
        if not text or text in GENERIC_SUMMARY_TEXTS or any(text.startswith(prefix) for prefix in GENERIC_SUMMARY_PREFIXES):
            return False
    joined = " ".join(str(item or "") for item in task_list)
    return len(joined) >= 12


def _model_output_with_summary(model_output: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    patched = deepcopy(model_output)
    result = patched.get("result")
    if isinstance(result, dict):
        result["user_facing_intent_summary"] = summary
    else:
        patched["user_facing_intent_summary"] = summary
    return patched


def _refine_user_facing_summary_with_model(
    gateway: PlatformModelGateway,
    *,
    text: str,
    uploaded_documents: Any,
    model_output: dict[str, Any],
) -> dict[str, Any] | None:
    documents = uploaded_documents if isinstance(uploaded_documents, list) else []
    document_brief = [
        {
            "file_name": item.get("file_name") or item.get("name"),
            "file_type": item.get("file_type") or item.get("mime_type"),
        }
        for item in documents
        if isinstance(item, dict)
    ]
    prompt = (
        "你是意图分析模块的质量自检步骤，只负责改写“给用户确认的意图摘要”，不执行业务任务。\n"
        "上一轮模型摘要过于泛化或缺失。请只根据 USER_INPUT、已识别任务和可用资料范围，重新输出更具体的 user_facing_intent_summary。\n"
        "必须返回严格 JSON 对象，格式只能是：\n"
        "{\"user_facing_intent_summary\":{\"business_goal\":\"...\",\"task_list\":[\"...\"],\"data_scope\":\"...\",\"output_focus\":\"...\",\"confirmation_question\":\"...\"}}\n"
        "user_facing_intent_summary 的值必须是对象，不能是字符串。\n"
        "要求：\n"
        "1. 中文输入必须输出清晰中文。\n"
        "2. task_list 必须逐项表达用户真正要确认的业务事项，不能写模块名、流程名、泛化动作。\n"
        "3. 禁止使用这些泛化句：处理当前对话中的业务请求、按问题要求统计数量或汇总指标、预测趋势或下周期业务指标、生成用户可读回答。\n"
        "4. 不要计算结果，不要声称数据已经找到，只描述准备理解和执行的意图。\n\n"
        f"USER_INPUT:\n{text}\n\n"
        f"UPLOADED_DOCUMENTS:\n{json.dumps(document_brief, ensure_ascii=False)}\n\n"
        f"MODEL_TASK_OUTPUT:\n{json.dumps(model_output, ensure_ascii=False)[:6000]}\n"
    )
    try:
        response = gateway.analyze(
            [{"role": "system", "content": prompt}],
            response_schema=_summary_response_schema(),
        )
    except Exception:
        return None
    payload = getattr(response, "parsed_json", None)
    if not isinstance(payload, dict):
        try:
            payload = json.loads(str(getattr(response, "content", "")))
        except Exception:
            return None
    summary = payload.get("user_facing_intent_summary") if isinstance(payload, dict) else None
    if isinstance(summary, str):
        summary = _coerce_summary_string_with_model(gateway, text=text, summary_text=summary)
    return summary if _summary_is_specific(summary) else None


def _coerce_summary_string_with_model(
    gateway: PlatformModelGateway,
    *,
    text: str,
    summary_text: str,
) -> dict[str, Any] | None:
    prompt = (
        "你是意图分析模块的格式修正步骤。下面 SUMMARY_TEXT 已经表达了用户意图，"
        "请只把它转换成严格 JSON 对象，不增加新业务含义，不执行业务任务。\n"
        "必须返回：{\"user_facing_intent_summary\":{\"business_goal\":\"...\",\"task_list\":[\"...\"],\"data_scope\":\"...\",\"output_focus\":\"...\",\"confirmation_question\":\"...\"}}\n"
        "task_list 必须拆成用户可确认的具体事项。\n\n"
        f"USER_INPUT:\n{text}\n\n"
        f"SUMMARY_TEXT:\n{summary_text}\n"
    )
    try:
        response = gateway.analyze(
            [{"role": "system", "content": prompt}],
            response_schema=_summary_response_schema(),
        )
    except Exception:
        return None
    payload = getattr(response, "parsed_json", None)
    if not isinstance(payload, dict):
        try:
            payload = json.loads(str(getattr(response, "content", "")))
        except Exception:
            return None
    summary = payload.get("user_facing_intent_summary") if isinstance(payload, dict) else None
    return summary if isinstance(summary, dict) else None
