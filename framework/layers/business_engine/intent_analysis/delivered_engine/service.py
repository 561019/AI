from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from framework.envelope import make_internal_envelope
from framework.http import post_json


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
                    + "\n意图分析边界：只识别任务，不执行任务，不生成业务结论。"
                    "USER_INPUT 是唯一的业务目标来源；CONVERSATION_CONTEXT 只用于补全指代；"
                    "AUTHORIZED_DATA_SCOPE 只用于限制可读资料范围，不能被当作已经解析出的业务事实。"
                    "必须返回任务清单和任务之间的依赖。每个任务要保留 task_type、task_description、action、object、"
                    "capability_code、data_object、data_scope、fields、operation、filters、output_schema、expected_outputs。"
                    "无法确定的关键字段放入 missing_inputs，不要猜测。"
                ),
            })
        envelope = make_internal_envelope(
            self.trace_id, self.actor, self.task_id, "model.respond", "foundation", "foundation-gateway",
            {
                "task_type": "intent_analysis", "messages": model_messages,
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
    result = outcome.result
    if result is None:
        handler.send(422, {"success": False, "error": {"code": "DELIVERED_INTENT_REJECTED", "reasons": outcome.rejection_reasons}, "engine_meta": {"delivery_root": str(DELIVERY_ROOT), "component": "LLMTaskAnalyzer"}}); return
    handler.send(200, {
        "success": True,
        "data": result.model_dump(mode="json"),
        "validation": {"rejection_reasons": outcome.rejection_reasons, "contract_corrections": outcome.contract_corrections, "contract_errors": outcome.contract_errors},
        "engine_meta": {"delivery_root": str(DELIVERY_ROOT), "component": "LLMTaskAnalyzer", "source": "user-delivered-module", "provider": gateway.last_model.get("provider"), "model": gateway.last_model.get("model"), "model_call_id": gateway.last_model.get("model_call_id"), "fallback_used": gateway.last_model.get("fallback_used", False), "model_output": gateway.last_model.get("output") or {}},
    })


def _build_runtime_context(
    uploaded_documents: Any,
    conversation_context: Any = None,
    project_context: Any = None,
    historical_projects: Any = None,
) -> str:
    """Expose authorization/context boundaries without presenting them as user wording."""
    documents = uploaded_documents if isinstance(uploaded_documents, list) else []
    readable = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        name = str(document.get("file_name") or document.get("name") or "未命名文件").strip()
        file_type = str(document.get("file_type") or document.get("mime_type") or "").strip()
        readable.append(f"- 文件名：{name}" + (f"；类型：{file_type}" if file_type else ""))
    if not readable:
        readable.append("- 当前对话没有上传文件")
    return "\n".join([
        "AUTHORIZED_DATA_SCOPE:",
        *readable,
        "CONVERSATION_CONTEXT:",
        json.dumps(conversation_context if isinstance(conversation_context, list) else [], ensure_ascii=False),
        "PROJECT_CONTEXT:",
        json.dumps(project_context if isinstance(project_context, list) else [], ensure_ascii=False),
        "HISTORICAL_PROJECT_CONTEXT:",
        json.dumps(historical_projects if isinstance(historical_projects, list) else [], ensure_ascii=False),
        "以上内容是运行上下文，不是用户原话；只能用于补全指代和限制资料范围，不能据此声称数据已找到、已解析或已有统计结果。",
    ])
