from __future__ import annotations

import re
from datetime import date
from typing import Any

from framework.core import standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import CAPABILITY_TO_MODULE


TASK_CAPABILITY_MAP = {
    "GENERAL_TASK": "content.generate",
    "RULE_CALCULATION_GENERAL": "rule.calculate",
    "RULE_CALCULATION_COMMISSION": "rule.calculate",
    "QUESTION_ANSWER": "knowledge.query",
    "PROCESS_HANDLE": "project.task.query",
    "WORKFLOW_START": "project.task.query",
    "DOCUMENT_TABLE_PARSE": "document.parse",
    "FILE_STRUCTURE_EXTRACT": "document.parse",
    "DATA_QUERY_FETCH": "data.search",
    "DATA_AGGREGATION_SUMMARY": "data.aggregate",
    "DATA_ANALYSIS_GROUP_SUM": "data.aggregate",
    "DATA_ANALYSIS_PIVOT": "data.aggregate",
    "DATA_ANALYSIS_PROBLEM": "data.aggregate",
    "DATA_ANALYSIS_FORECAST": "analysis.business_metric",
    "DATA_FILTER": "data.search",
    "DATA_SORT": "data.search",
    "CONTENT_GENERATE": "content.generate",
    "DOCUMENT_GENERATE": "content.generate",
    "MULTIMEDIA_GENERATE": "multimedia.generate",
    "MONITORING_REMINDER": "reminder.handle",
    "PROJECT_MANAGEMENT": "project.query",
    "PROJECT_CREATE": "project.register.simple",
    "PROJECT_QUERY": "project.query",
    "ANALYSIS_PREDICTION": "analysis.business_metric",
    "FINANCIAL_ANALYSIS": "analysis.financial_statement",
    "PRICE_FORECAST": "analysis.price_forecast",
    "DIGITAL_ASSET": "asset.query",
    "HUMAN_COLLABORATION": "human.task.create",
    "SECURITY_COMPLIANCE": "security.guardrail.check",
    "EXECUTION_SANDBOX": "sandbox.run_task",
    "EXECUTION_SANDBOX_CODE": "sandbox.run_code",
    "EXECUTION_SANDBOX_BROWSER": "sandbox.run_browser",
    "CONTEXT_HANDOFF": "context.handoff.generate",
    "CONTEXT_HISTORY_SEARCH": "context.project.search",
    "CONTEXT_ACCOUNT_SEARCH": "context.account.search",
    "CONTEXT_IMPORT": "context.handoff.import",
}

CAPABILITY_ALIASES = {
    "file.structure.extract": "document.table.extract",
    "file_structure_extract": "document.table.extract",
    "document.structure.extract": "document.table.extract",
    "document_structure_extract": "document.table.extract",
    "document.table.parse": "document.table.extract",
    "document_table_parse": "document.table.extract",
    "data.query": "data.search",
    "data.retrieve": "data.search",
    "data_query": "data.search",
    "data_retrieve": "data.search",
    "data.analysis": "analysis.business_metric",
    "data.analysis.problem": "analysis.business_metric",
    "data.analysis.summary": "data.aggregate",
    "data.analysis.aggregate": "data.aggregate",
    "data_analysis": "analysis.business_metric",
    "data_analysis.problem": "analysis.business_metric",
    "data_analysis_problem": "analysis.business_metric",
    "data-analysis": "analysis.business_metric",
    "data-analysis.problem": "analysis.business_metric",
    "knowledge.answer": "knowledge.qa.answer",
    "knowledge_qa.answer": "knowledge.qa.answer",
    "knowledge.answer.contextual": "knowledge.qa.contextual_answer",
    "execution_sandbox.run_task": "sandbox.run_task",
    "execution_sandbox.run_code": "sandbox.run_code",
    "execution_sandbox.run_browser": "sandbox.run_browser",
    "sandbox.task.run": "sandbox.run_task",
    "sandbox.code.run": "sandbox.run_code",
    "sandbox.browser.run": "sandbox.run_browser",
    "sandbox.run": "sandbox.run_task",
    "context.handoff": "context.handoff.generate",
    "context.search": "context.project.search",
    "context.import": "context.handoff.import",
}


REGISTERED_CAPABILITIES = set(CAPABILITY_TO_MODULE) | {"content.generate"}


def _normalize_capability_alias(capability: str) -> str:
    value = str(capability or "").strip()
    if not value:
        return value
    lowered = value.lower()
    normalized = lowered.replace("-", "_")
    if normalized in CAPABILITY_ALIASES:
        return CAPABILITY_ALIASES[normalized]
    dotted = normalized.replace("_", ".")
    if dotted in CAPABILITY_ALIASES:
        return CAPABILITY_ALIASES[dotted]
    if normalized in {"data_analysis"} or normalized.startswith("data_analysis_") or lowered.startswith("data_analysis."):
        if any(token in normalized for token in ("aggregate", "summary", "statistics", "count", "sum")):
            return "data.aggregate"
        return "analysis.business_metric"
    if normalized in {"data_query", "data_retrieve"}:
        return "data.search"
    return CAPABILITY_ALIASES.get(value, value)


def _resolve_registered_capability(capability: str, task: dict[str, Any], utterance: str) -> dict[str, Any]:
    value = _normalize_capability_alias(capability)
    if value in REGISTERED_CAPABILITIES:
        return {"capability": value, "status": "matched", "original_capability": capability}
    closest = _closest_registered_capability(value, task, utterance)
    if closest:
        return {
            "capability": closest,
            "status": "nearest_matched",
            "original_capability": capability,
            "message": f"已将模型返回的能力 {capability or '空'} 映射为平台已登记能力 {closest}。",
        }
    return {
        "capability": "",
        "status": "unregistered",
        "original_capability": capability,
        "message": f"平台暂未登记可处理该任务的能力：{capability or task.get('task_type') or '未命名能力'}。",
    }


def _closest_registered_capability(capability: str, task: dict[str, Any], utterance: str) -> str:
    text = " ".join(str(part or "") for part in (
        capability,
        task.get("task_type"),
        task.get("task_description"),
        task.get("action"),
        task.get("object"),
        task.get("data_object"),
        utterance,
    )).lower()
    value = str(capability or "").lower()
    task_type = str(task.get("task_type") or "").upper()
    task_action = str(task.get("action") or "").lower()
    if (
        value.startswith(("file.", "document.", "table."))
        or task_type in {"FILE_STRUCTURE_EXTRACT", "DOCUMENT_TABLE_PARSE", "DOCUMENT_PARSE"}
        or task_action in {"parse", "extract"}
    ):
        return "document.table.extract" if "document.table.extract" in REGISTERED_CAPABILITIES else "document.parse"
    if value.startswith(("data.query", "data.retrieve", "data.fetch")):
        return "data.search"
    if value.startswith(("data.aggregate", "data.summary", "data.summarize", "data.statistics")):
        return "data.aggregate"
    if value.startswith(("analysis.", "forecast.", "predict.", "prediction.", "data.analyze.", "data.analysis.")):
        return "analysis.business_metric"
    if value.startswith(("rule.", "risk.", "compliance.")):
        return "rule.calculate"
    if value.startswith("project."):
        return "project.task.query" if any(token in value for token in ("query", "list", "search")) else "project.register.simple"
    if value.startswith(("monitor.", "reminder.")):
        return "monitor.item.register" if any(token in text for token in ("监控", "提醒", "预警", "跟踪", "monitor", "reminder", "alert")) else "reminder.handle"
    if value.startswith("human."):
        return "human.task.create"
    if value.startswith(("knowledge.", "qa.", "question.")):
        return "knowledge.query"
    if value.startswith(("asset.", "digital_asset.")):
        return "asset.query"
    if value.startswith(("sandbox.", "execution_sandbox.")):
        if any(token in text for token in ("browser", "url", "web", "浏览器", "网页", "采集")):
            return "sandbox.run_browser"
        if any(token in text for token in ("code", "python", "script", "代码", "脚本", "程序")):
            return "sandbox.run_code"
        return "sandbox.run_task"
    if any(token in text for token in ("sandbox", "execution sandbox", "执行沙箱", "沙箱")):
        if any(token in text for token in ("browser", "url", "web", "浏览器", "网页", "采集")):
            return "sandbox.run_browser"
        if any(token in text for token in ("code", "python", "script", "代码", "脚本", "程序")):
            return "sandbox.run_code"
        return "sandbox.run_task"
    if any(token in text for token in ("预测", "趋势", "下一个月", "下个月", "下月", "下季度", "下半年", "下一年", "未来一年", "forecast", "predict")):
        return "analysis.business_metric"
    if any(token in text for token in ("规则", "核对", "校验", "风险", "盈亏平衡", "rule", "risk", "check")):
        return "rule.calculate"
    if any(token in text for token in ("统计", "汇总", "多少", "几个", "最高", "最多", "去重", "count", "sum", "aggregate")):
        return "data.aggregate"
    if any(token in text for token in ("查询", "读取", "检索", "列表", "search", "query", "retrieve")):
        return "data.search"
    if any(token in text for token in ("知识库", "资料", "制度", "参数", "说明", "knowledge")):
        return "knowledge.query"
    if any(token in text for token in ("生成", "写", "草案", "报告", "文案", "content", "generate")):
        return "content.generate"
    return ""


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/intent/analyze":
        handler.send(404); return
    utterance = str(envelope.get("payload", {}).get("utterance", "")).strip()
    uploaded_documents = envelope.get("payload", {}).get("uploaded_documents") or []
    if not utterance:
        handler.send(422, {"error": {"code": "PRECONDITION_REQUIRED"}}); return
    context_envelope = make_internal_envelope(
        envelope["trace_id"], envelope["actor"], str(envelope.get("payload", {}).get("platform_task_id") or envelope["request_id"]),
        "context.intent.prepare", "foundation", "context-prompt-management", {},
        source_layer="business_engine", source_module="intent-adapter",
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else {},
    )
    context_status, context_response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions", context_envelope,
        timeout=30, caller={"layer": "business_engine", "module": "intent-adapter"},
    )
    if context_status not in {200, 202} or not isinstance(context_response, dict) or context_response.get("status") != "success":
        handler.send(502, standard_response(envelope, "failed", error={"code": "CONTEXT_PREPARE_FAILED", "details": context_response, "retryable": True})); return
    prepared_context = context_response.get("data") if isinstance(context_response.get("data"), dict) else {}
    request = {
        "text": utterance,
        "user_id": envelope["actor"].get("actor_id") or envelope["actor"].get("user_id") or "unknown",
        "conversation_id": envelope.get("context", {}).get("conversation_id"),
        "project_id": envelope.get("context", {}).get("project_id"),
        "trace_id": envelope["trace_id"], "actor": envelope["actor"],
        "platform_task_id": envelope.get("payload", {}).get("platform_task_id"),
        "uploaded_documents": uploaded_documents,
        "conversation_context": prepared_context.get("materials") or (
            envelope.get("payload", {}).get("conversation_context")
            or envelope.get("context", {}).get("conversation_context")
            or []
        ),
        "project_context": (
            envelope.get("payload", {}).get("project_context")
            or envelope.get("context", {}).get("project_context")
            or []
        ),
        "historical_projects": (
            envelope.get("payload", {}).get("historical_projects")
            or envelope.get("context", {}).get("historical_projects")
            or []
        ),
    }
    explicit_sandbox_capability = _explicit_sandbox_capability_from_utterance(utterance)
    status, delivered = post_json(
        "http://127.0.0.1:8003/api/v1/delivered-intent/analyze", request,
        timeout=55, caller={"layer": "business_engine", "module": "intent-adapter"},
    )
    if status != 200 or not delivered.get("success"):
        if explicit_sandbox_capability:
            _send_explicit_sandbox_intent_result(handler, envelope, request, utterance, uploaded_documents, explicit_sandbox_capability)
            return
        handler.send(502, standard_response(envelope, "failed", error={"code": "DELIVERED_INTENT_ENGINE_FAILED", "details": delivered, "retryable": True})); return

    original = delivered.get("data") or {}
    meta = delivered.get("engine_meta") or {}
    raw_model_output = meta.get("model_output") if isinstance(meta.get("model_output"), dict) else {}
    raw_result = raw_model_output.get("result") if isinstance(raw_model_output.get("result"), dict) else raw_model_output
    raw_tasks = raw_result.get("tasks") if isinstance(raw_result, dict) and isinstance(raw_result.get("tasks"), list) else []
    model_intent_summary = _extract_model_intent_summary(raw_model_output, utterance, uploaded_documents)
    if not model_intent_summary and explicit_sandbox_capability:
        model_intent_summary = _build_explicit_sandbox_intent_summary(utterance, explicit_sandbox_capability)
    if not model_intent_summary:
        handler.send(502, standard_response(envelope, "failed", error={
            "code": "INTENT_MODEL_SUMMARY_NOT_SPECIFIC",
            "message": "意图分析大模型没有返回合格的用户确认摘要；平台已拒绝使用本地通用话术兜底。",
            "retryable": True,
            "details": {
                "model_call_id": meta.get("model_call_id"),
                "provider": meta.get("provider"),
                "model": meta.get("model"),
                "fallback_used": meta.get("fallback_used", False),
                "intent_summary_refinement": meta.get("intent_summary_refinement"),
            },
        })); return
    platform_tasks = []
    # Python treats Chinese characters as ``\w``. Guard only against adjacent
    # digits/decimal points so values such as "金额1200元" are not discarded.
    numeric_values = [float(value) for value in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", utterance)]
    extracted_details = _extract_intent_details(utterance, uploaded_documents)
    for task_index, task in enumerate(original.get("tasks", [])):
        raw_task = raw_tasks[task_index] if task_index < len(raw_tasks) and isinstance(raw_tasks[task_index], dict) else {}
        task = {**raw_task, **task}
        task_type = task.get("task_type", "")
        model_capability = str(task.get("capability_code") or "").strip()
        capability_candidate = _normalize_capability_alias(
            model_capability or TASK_CAPABILITY_MAP.get(task_type, f"unmapped.{task_type.lower()}")
        )
        capability_match = _resolve_registered_capability(capability_candidate, task, utterance)
        capability = str(capability_match.get("capability") or "")
        original_capability = str(capability_match.get("original_capability") or capability_candidate)
        if not capability:
            handler.send(422, standard_response(envelope, "failed", error={
                "code": "CAPABILITY_NOT_REGISTERED",
                "message": capability_match.get("message") or "平台暂未登记可处理该任务的能力。",
                "retryable": False,
                "details": {
                    "model_capability_code": model_capability,
                    "task_type": task_type,
                    "task_description": task.get("task_description"),
                    "available_capability_count": len(REGISTERED_CAPABILITIES),
                    "suggestion": "请先在能力字典和模块登记表中登记该能力，或让意图分析模型输出更接近已登记能力的能力码。",
                },
            }))
            return
        parameters = {
            "action": task.get("action"), "object": task.get("object"),
            "required_inputs": task.get("required_inputs", []), "missing_inputs": task.get("missing_inputs", []),
            "values": numeric_values if capability == "rule.calculate" else [], "utterance": utterance,
            "original_task_type": task_type,
            "original_capability_code": original_capability,
            "capability_match_status": capability_match.get("status"),
            "capability_match_message": capability_match.get("message"),
            "fallback_reason": None,
            "uploaded_documents": uploaded_documents,
            "conversation_context": request["conversation_context"],
            "data_object": task.get("data_object") or task.get("object") or "",
            "data_scope": task.get("data_scope") or "",
            "fields": task.get("fields") if isinstance(task.get("fields"), list) else [],
            "operation": task.get("operation") or "",
            "filters": task.get("filters") if isinstance(task.get("filters"), dict) else {},
            "output_schema": task.get("output_schema") if isinstance(task.get("output_schema"), dict) else {},
            "expected_outputs": task.get("expected_outputs") if isinstance(task.get("expected_outputs"), list) else [],
            "extracted_details": extracted_details,
        }
        if model_intent_summary:
            parameters["model_intent_summary"] = model_intent_summary
        parameters = _normalize_parameters_for_context(utterance, capability, parameters, uploaded_documents)
        parameters["workflow_hints"] = _build_workflow_hints(utterance, capability, parameters, uploaded_documents)
        parameters["intent_summary"] = _build_intent_summary(utterance, capability, parameters, uploaded_documents)
        platform_tasks.append({
            "task_id": task.get("task_id"),
            "description": _normalize_task_description(task.get("task_description"), utterance, capability, parameters),
            "capability_code": capability, "dependencies": task.get("dependencies", []),
            "parameters": parameters, "confidence": task.get("confidence", original.get("overall_confidence", .8)),
        })
    if explicit_sandbox_capability:
        platform_tasks = [_build_explicit_sandbox_platform_task(
            utterance,
            explicit_sandbox_capability,
            uploaded_documents,
            request["conversation_context"],
            extracted_details,
            model_intent_summary,
        )]
    platform_tasks = _build_intent_contract(platform_tasks, utterance, uploaded_documents)
    intent_card = _build_intent_card(utterance, uploaded_documents, platform_tasks, extracted_details)
    if not platform_tasks:
        model_output = meta.get("model_output") or {}
        capability_candidate = _normalize_capability_alias(str(model_output.get("capability_code") or "").strip())
        capability_match = _resolve_registered_capability(capability_candidate, model_output if isinstance(model_output, dict) else {}, utterance)
        capability = str(capability_match.get("capability") or "")
        if capability:
            capability = _normalize_capability_for_context(utterance, capability, uploaded_documents)
            model_parameters = model_output.get("parameters") if isinstance(model_output.get("parameters"), dict) else {}
            model_parameters = _normalize_parameters_for_context(utterance, capability, model_parameters, uploaded_documents)
            model_parameters["extracted_details"] = extracted_details
            if model_intent_summary:
                model_parameters["model_intent_summary"] = model_intent_summary
            model_parameters["original_capability_code"] = capability_match.get("original_capability") or capability_candidate
            model_parameters["capability_match_status"] = capability_match.get("status")
            model_parameters["capability_match_message"] = capability_match.get("message")
            platform_tasks.append({
                "task_id": "model-output-adapted-1",
                "description": _normalize_task_description(model_output.get("description"), utterance, capability, model_parameters),
                "capability_code": capability,
                "dependencies": [],
                "parameters": {
                    **model_parameters,
                    "values": numeric_values if capability == "rule.calculate" else model_parameters.get("values", []),
                    "utterance": utterance,
                    "original_task_type": "MODEL_GATEWAY_DIRECT",
                    "uploaded_documents": uploaded_documents,
                },
                "confidence": model_output.get("confidence", original.get("overall_confidence", .75)),
            })
            platform_tasks[-1]["parameters"]["workflow_hints"] = _build_workflow_hints(
                utterance, capability, platform_tasks[-1]["parameters"], uploaded_documents
            )
            platform_tasks[-1]["parameters"]["intent_summary"] = _build_intent_summary(
                utterance, capability, platform_tasks[-1]["parameters"], uploaded_documents
            )
            platform_tasks = _build_intent_contract(platform_tasks, utterance, uploaded_documents)
            intent_card = _build_intent_card(utterance, uploaded_documents, platform_tasks, extracted_details)
        elif capability_candidate:
            handler.send(422, standard_response(envelope, "failed", error={
                "code": "CAPABILITY_NOT_REGISTERED",
                "message": capability_match.get("message") or "平台暂未登记可处理该任务的能力。",
                "retryable": False,
                "details": {
                    "model_capability_code": capability_candidate,
                    "available_capability_count": len(REGISTERED_CAPABILITIES),
                    "suggestion": "请先在能力字典和模块登记表中登记该能力，或让意图分析模型输出更接近已登记能力的能力码。",
                },
            }))
            return
    if not platform_tasks:
        handler.send(502, standard_response(envelope, "failed", error={
            "code": "INTENT_MODEL_RETURNED_NO_USABLE_TASK",
            "message": "意图分析模型没有返回可执行任务，请检查模型输出、提示词和能力字典。",
            "retryable": True,
        })); return
    data = {
        "tasks": platform_tasks,
        "intent_card": intent_card,
        "extracted_details": extracted_details,
        "clarification_required": bool(original.get("clarification_required", False)) and any((task.get("parameters") or {}).get("missing_inputs") for task in platform_tasks),
        "required_inputs": original.get("clarification_questions", []) if any((task.get("parameters") or {}).get("missing_inputs") for task in platform_tasks) else [],
        "intent_confirmation_required": True,
        "model_call": {"model_call_id": meta.get("model_call_id"), "provider": meta.get("provider"), "model": meta.get("model"), "fallback_used": meta.get("fallback_used", False)},
        "intent_engine": {"source": meta.get("source"), "component": meta.get("component"), "original_analysis_level": original.get("analysis_level"), "validation": delivered.get("validation")},
                "uploaded_documents": uploaded_documents,
                "conversation_context": request["conversation_context"],
            }
    handler.send(200, standard_response(envelope, "success", data=data))


def _normalize_capability_for_context(utterance: str, capability: str, uploaded_documents: list[dict[str, Any]]) -> str:
    return capability


def _explicit_sandbox_capability_from_utterance(utterance: str) -> str:
    text = str(utterance or "").lower()
    if not _contains_any_text(text, (
        "sandbox",
        "execution sandbox",
        "\u6267\u884c\u6c99\u7bb1",
        "\u6c99\u7bb1",
        "python",
        "\u4ee3\u7801",
        "\u811a\u672c",
        "\u7a0b\u5e8f",
    )):
        return ""
    if _contains_any_text(text, ("browser", "url", "web", "\u6d4f\u89c8\u5668", "\u7f51\u9875", "\u91c7\u96c6")):
        return "sandbox.run_browser"
    if _contains_any_text(text, ("code", "python", "script", "\u4ee3\u7801", "\u811a\u672c", "\u7a0b\u5e8f", "\u8fd0\u884c")):
        return "sandbox.run_code"
    return "sandbox.run_task"


def _contains_any_text(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(token.lower() in lowered for token in tokens)


def _build_explicit_sandbox_intent_summary(utterance: str, capability: str) -> dict[str, Any]:
    if capability == "sandbox.run_browser":
        task = "\u5728\u6267\u884c\u6c99\u7bb1\u4e2d\u9694\u79bb\u6267\u884c\u6d4f\u89c8\u5668\u6216\u7f51\u9875\u8bbf\u95ee\u4efb\u52a1"
        output = "\u6d4f\u89c8\u5668\u6267\u884c\u72b6\u6001\u3001\u7ed3\u679c\u548c\u6c99\u7bb1\u8bc1\u636e"
    elif capability == "sandbox.run_code":
        task = "\u5728\u6267\u884c\u6c99\u7bb1\u4e2d\u9694\u79bb\u8fd0\u884c\u4ee3\u7801"
        output = "\u4ee3\u7801\u8fd0\u884c\u7ed3\u679c\u3001\u9000\u51fa\u72b6\u6001\u548c\u6c99\u7bb1\u8bc1\u636e"
    else:
        task = "\u5728\u6267\u884c\u6c99\u7bb1\u4e2d\u9694\u79bb\u6267\u884c\u767b\u8bb0\u4efb\u52a1"
        output = "\u4efb\u52a1\u6267\u884c\u72b6\u6001\u3001\u8f93\u51fa\u7ed3\u679c\u548c\u6c99\u7bb1\u8bc1\u636e"
    return {
        "source": "platform_explicit_sandbox_adapter",
        "business_goal": _clean_user_text(utterance) or task,
        "data_scope": "\u5f53\u524d\u5bf9\u8bdd\u8bf7\u6c42\uff0c\u4e0d\u9700\u8981\u4e0a\u4f20\u6587\u4ef6",
        "task_list": [task],
        "planned_steps": [task],
        "output_focus": output,
        "confirmation_question": "\u8bf7\u786e\u8ba4\u662f\u5426\u6309\u4ee5\u4e0a\u7406\u89e3\u7ee7\u7eed\u6267\u884c\u3002",
    }


def _build_explicit_sandbox_platform_task(
    utterance: str,
    capability: str,
    uploaded_documents: list[dict[str, Any]],
    conversation_context: list[dict[str, Any]],
    extracted_details: dict[str, Any],
    model_intent_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    parameters = {
        "action": "run_code" if capability == "sandbox.run_code" else "run",
        "object": "\u6267\u884c\u6c99\u7bb1",
        "required_inputs": [],
        "missing_inputs": [],
        "utterance": utterance,
        "original_task_type": "EXECUTION_SANDBOX_CODE" if capability == "sandbox.run_code" else "EXECUTION_SANDBOX",
        "original_capability_code": capability,
        "capability_match_status": "explicit_user_request",
        "uploaded_documents": uploaded_documents,
        "conversation_context": conversation_context,
        "data_object": "\u6267\u884c\u6c99\u7bb1",
        "data_scope": "current_conversation_request",
        "fields": [],
        "operation": "run_code" if capability == "sandbox.run_code" else "run_task",
        "filters": {},
        "output_schema": {"type": "sandbox_execution_result"},
        "expected_outputs": ["sandbox_status", "stdout_or_business_output", "evidence_snapshot", "audit_events"],
        "extracted_details": extracted_details,
        "planning_owner": "workflow_execution",
    }
    if model_intent_summary:
        parameters["model_intent_summary"] = model_intent_summary
    parameters["workflow_hints"] = _build_workflow_hints(utterance, capability, parameters, uploaded_documents)
    parameters["intent_summary"] = model_intent_summary or _build_explicit_sandbox_intent_summary(utterance, capability)
    return {
        "task_id": "explicit-sandbox-request-1",
        "description": _clean_user_text(utterance) or "\u8c03\u7528\u6267\u884c\u6c99\u7bb1",
        "capability_code": capability,
        "dependencies": [],
        "parameters": parameters,
        "confidence": 0.95,
    }


def _send_explicit_sandbox_intent_result(
    handler: Any,
    envelope: dict[str, Any],
    request: dict[str, Any],
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
    capability: str,
) -> None:
    extracted_details = _extract_intent_details(utterance, uploaded_documents)
    summary = _build_explicit_sandbox_intent_summary(utterance, capability)
    platform_tasks = [_build_explicit_sandbox_platform_task(
        utterance,
        capability,
        uploaded_documents,
        request.get("conversation_context") if isinstance(request.get("conversation_context"), list) else [],
        extracted_details,
        summary,
    )]
    platform_tasks = _build_intent_contract(platform_tasks, utterance, uploaded_documents)
    intent_card = _build_intent_card(utterance, uploaded_documents, platform_tasks, extracted_details)
    data = {
        "tasks": platform_tasks,
        "intent_card": intent_card,
        "extracted_details": extracted_details,
        "clarification_required": False,
        "required_inputs": [],
        "intent_confirmation_required": True,
        "model_call": {
            "model_call_id": None,
            "provider": None,
            "model": None,
            "fallback_used": False,
            "bypassed_reason": "explicit_platform_sandbox_request",
        },
        "intent_engine": {
            "source": "platform-intent-adapter",
            "component": "explicit_sandbox_intent_adapter",
            "validation": {"explicit_capability": capability},
        },
        "uploaded_documents": uploaded_documents,
        "conversation_context": request.get("conversation_context") if isinstance(request.get("conversation_context"), list) else [],
    }
    handler.send(200, standard_response(envelope, "success", data=data))


def _looks_like_data_backed_task(task: dict[str, Any], uploaded_documents: list[dict[str, Any]]) -> bool:
    if not uploaded_documents:
        return False
    task_type = str(task.get("task_type") or "").upper()
    capability = str(task.get("capability_code") or "").lower()
    operation = str(task.get("operation") or task.get("action") or "").lower()
    object_text = str(task.get("data_object") or task.get("object") or "")
    expected = " ".join(str(item) for item in (task.get("expected_outputs") or []))
    required = " ".join(str(item) for item in (task.get("required_inputs") or []))
    text = " ".join([task_type, capability, operation, object_text, expected, required]).lower()
    if task_type.startswith("DATA_") or capability.startswith("data."):
        return True
    if any(token in operation for token in ("retrieve", "query", "search", "analyze", "analyse", "summary", "count", "sum", "compare", "recommend", "检查", "统计", "分析", "查询", "列举", "判断")):
        return True
    return any(token in text for token in ("data", "source", "record", "asset", "数据", "记录", "表", "字段", "指标", "资产"))


def _normalize_parameters_for_context(
    utterance: str,
    capability: str,
    parameters: dict[str, Any],
    uploaded_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = dict(parameters)
    normalized["utterance"] = utterance
    normalized["uploaded_documents"] = uploaded_documents
    required = [item for item in normalized.get("required_inputs", []) if item not in {"data_source", "file", "uploaded_documents"}]
    missing = [item for item in normalized.get("missing_inputs", []) if item not in {"data_source", "file", "uploaded_documents"}]
    if uploaded_documents:
        required = [item for item in required if item not in {"dataset", "collection"}]
        missing = [item for item in missing if item not in {"dataset", "collection"}]
    if capability == "data.aggregate":
        normalized["action"] = normalized.get("action") or "aggregate"
        normalized["analysis_goal"] = normalized.get("analysis_goal") or utterance
    normalized["planning_owner"] = "workflow_execution"
    normalized["required_inputs"] = required
    normalized["missing_inputs"] = missing
    return normalized


def _build_data_access_contract(
    utterance: str,
    capability: str,
    parameters: dict[str, Any],
    uploaded_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe where later engines should read data without doing the read here."""
    raw_object = str(parameters.get("data_object") or parameters.get("object") or "").strip()
    explicit_fields = parameters.get("fields") if isinstance(parameters.get("fields"), list) else []
    dataset = "extracted_fields" if uploaded_documents else "business_records"
    file_ids = [str(doc.get("file_id")) for doc in uploaded_documents if isinstance(doc, dict) and doc.get("file_id")]
    filters: dict[str, Any] = {}
    if len(file_ids) == 1:
        filters["file_id"] = file_ids[0]
    elif file_ids:
        filters["file_id"] = file_ids
    operation = str(parameters.get("operation") or parameters.get("action") or "").strip() or "retrieve"
    return {
        "schema_version": "1.0",
        "dataset": dataset,
        "source_type": "uploaded_spreadsheet" if uploaded_documents else "authorized_platform_data",
        "file_ids": file_ids,
        "business_object": raw_object,
        "business_object_label": raw_object,
        "semantic_query": " ".join(part for part in (utterance, raw_object, " ".join(str(item) for item in explicit_fields)) if part),
        "sheet_name": "",
        "field_aliases": explicit_fields,
        "row_identity_fields": [],
        "filters": {**filters, **(parameters.get("filters") if isinstance(parameters.get("filters"), dict) else {})},
        "operation": operation,
        "requires_row_grouping": dataset == "extracted_fields",
        "allow_model_reasoning_after_retrieval": capability in {"content.generate", "data.search"} or operation in {"recommend", "rank", "analyze", "analyse", "summarize"},
    }


def _normalize_task_description(raw_description: Any, utterance: str, capability: str, parameters: dict[str, Any]) -> str:
    description = str(raw_description or "").strip()
    if not description:
        return _infer_business_goal(utterance, capability)
    if _looks_like_runtime_context(description):
        return _infer_business_goal(utterance, capability)
    if len(description) > max(len(utterance) * 3, 120) and utterance not in description:
        return _infer_business_goal(utterance, capability)
    return description


def _looks_like_runtime_context(text: str) -> bool:
    normalized = str(text or "")
    if any(token in normalized for token in (
        "AUTHORIZED_DATA_SCOPE",
        "CONVERSATION_CONTEXT",
        "PROJECT_CONTEXT",
        "HISTORICAL_PROJECT_CONTEXT",
        "USER_INPUT",
        "Intent analysis boundary",
        "意图分析边界",
        "运行上下文",
        "不是用户原话",
        "只能用于补全指代",
    )):
        return True
    if any(token in text for token in ("平台运行上下文", "当前对话已授权访问", "此上下文不是用户原话", "严格约束", "runtime context")):
        return True
    return any(token in text for token in ("平台运行上下文", "当前对话已授权访问", "此上下文不是用户原话", "runtime context"))


def _extract_intent_details(utterance: str, uploaded_documents: list[dict[str, Any]]) -> dict[str, Any]:
    text = str(utterance or "")
    time_detail = _extract_time_detail(text)
    details = {
        "schema_version": "1.0",
        "data_sources": _extract_data_sources(text, uploaded_documents),
        "business_objects": _extract_business_objects(text),
        "time_range": time_detail.get("time_range", ""),
        "time_grain": time_detail.get("time_grain", ""),
        "forecast_horizon": time_detail.get("forecast_horizon"),
        "target_year": time_detail.get("target_year"),
        "target_month": time_detail.get("target_month"),
        "target_period": time_detail.get("target_period"),
        "filters": _extract_filters(text),
        "metrics": _extract_metrics(text),
        "calculations": _extract_calculations(text),
        "risk_checks": _extract_risk_checks(text),
        "constraints": _extract_constraints(text, uploaded_documents),
        "output_expectation": _extract_output_expectation(text),
    }
    return {key: value for key, value in details.items() if value not in (None, "", [], {})}


def _extract_data_sources(text: str, uploaded_documents: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    if uploaded_documents or any(word in text for word in ("当前上传", "上传文件", "附件", "文件", "表格")):
        sources.append("current_uploaded_files")
    if any(word in text for word in ("已入库", "平台数据", "授权数据", "当前项目", "项目数据", "数据库")):
        sources.append("authorized_platform_data")
    if any(word in text for word in ("知识库", "制度", "资料库", "文档库")):
        sources.append("knowledge_base")
    return sources or ["current_conversation_or_authorized_data"]


def _extract_time_detail(text: str) -> dict[str, Any]:
    lowered = str(text or "").lower()
    absolute_month = _extract_absolute_month_detail(text)
    if absolute_month:
        return absolute_month
    if any(word in text for word in ("下一个月", "下月", "下个月", "下一月", "未来一个月", "后续一个月", "未来1个月", "后续1个月")) or "next month" in lowered:
        return {"time_range": "下一个月", "time_grain": "month", "forecast_horizon": 1}
    if any(word in text for word in ("下一年", "未来一年", "后续一年", "未来12个月", "未来十二个月")) or "next year" in lowered:
        return {"time_range": "下一年", "time_grain": "month", "forecast_horizon": 12}
    if any(word in text for word in ("下半年", "未来半年", "后半年", "未来6个月", "未来六个月")) or "half year" in lowered or "six months" in lowered:
        return {"time_range": "下半年", "time_grain": "month", "forecast_horizon": 6}
    match = re.search(r"(?:未来|后续|下)\s*(\d{1,2})\s*(?:个)?月", text)
    if match:
        months = int(match.group(1))
        if 1 <= months <= 24:
            return {"time_range": f"未来{months}个月", "time_grain": "month", "forecast_horizon": months}
    if any(word in text for word in ("下季度", "下一季度", "未来一季度")) or "next quarter" in lowered:
        return {"time_range": "下季度", "time_grain": "month", "forecast_horizon": 3}
    year = _year_from_text(text)
    if year:
        return {"time_range": f"{year}年", "time_grain": "month"}
    if "月" in text:
        return {"time_range": "按月份", "time_grain": "month"}
    if "季度" in text:
        return {"time_range": "按季度", "time_grain": "quarter"}
    return {}


_CHINESE_MONTH_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}


def _extract_absolute_month_detail(text: str) -> dict[str, Any]:
    value = str(text or "")
    explicit_year = _year_from_text(value)
    if "今年" in value:
        explicit_year = date.today().year
    elif "明年" in value:
        explicit_year = date.today().year + 1
    elif "去年" in value:
        explicit_year = date.today().year - 1
    month: int | None = None
    numeric = re.search(r"(?:(?:20\d{2}|今年|明年|去年)\s*年?\s*)?(\d{1,2})\s*月(?:份)?", value)
    if numeric:
        month = int(numeric.group(1))
    else:
        chinese = re.search(r"(?:(?:20\d{2}|今年|明年|去年)\s*年?\s*)?(十一|十二|十|一|二|三|四|五|六|七|八|九)\s*月(?:份)?", value)
        if chinese:
            month = _CHINESE_MONTH_MAP.get(chinese.group(1))
    if not month or not 1 <= month <= 12:
        return {}
    if explicit_year is None:
        if any(word in value for word in ("预测", "预计", "预估", "forecast", "predict")):
            explicit_year = date.today().year
        else:
            return {}
    target_period = f"{int(explicit_year):04d}-{int(month):02d}"
    return {
        "time_range": f"{int(explicit_year):04d}年{int(month):02d}月",
        "time_grain": "month",
        "target_year": int(explicit_year),
        "target_month": int(month),
        "target_period": target_period,
    }


def _extract_filters(text: str) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    region_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9_-]{1,12}(?:地区|区域|片区|省|市|县|区))", text)
    if region_match:
        region = region_match.group(1)
        region = re.sub(r"^(?:预测|分析|统计|计算|判断|查看|查询|基于|当前|上传|文件|请|帮我|告诉我)+", "", region)
        filters["region"] = region or region_match.group(1)
    year = _year_from_text(text)
    if year:
        filters["year"] = year
    return filters


def _extract_business_objects(text: str) -> list[str]:
    candidates = (
        "需求", "订单", "销量", "销售", "预算", "价格", "成本", "利润", "盈亏平衡",
        "风险", "客户", "经销商", "供应商", "产品", "库存", "项目", "合同", "发票", "验收",
    )
    return [item for item in candidates if item in text]


def _extract_metrics(text: str) -> list[str]:
    metrics = []
    for word, label in (
        ("需求", "需求量"),
        ("订单", "订单量"),
        ("销量", "销量"),
        ("销售", "销售额或销量"),
        ("金额", "金额"),
        ("收入", "收入"),
        ("利润", "利润"),
        ("库存", "库存量"),
        ("预算", "预算金额"),
    ):
        if word in text and label not in metrics:
            metrics.append(label)
    return metrics


def _extract_calculations(text: str) -> list[str]:
    calculations = []
    if "盈亏平衡" in text:
        calculations.append("盈亏平衡数量")
    if any(word in text for word in ("计算", "核算", "测算")) and not calculations:
        calculations.append("用户指定计算项")
    if any(word in text for word in ("预测", "趋势")):
        calculations.append("预测分析")
    return calculations


def _extract_risk_checks(text: str) -> list[str]:
    checks = []
    if "预算风险" in text:
        checks.append("预算风险")
    elif "风险" in text:
        checks.append("风险点")
    if any(word in text for word in ("合规", "异常", "差异", "缺失")):
        checks.append("异常或合规风险")
    return checks


def _extract_constraints(text: str, uploaded_documents: list[dict[str, Any]]) -> list[str]:
    constraints = []
    if uploaded_documents or any(word in text for word in ("基于当前上传文件", "当前上传文件", "上传文件")):
        constraints.append("优先基于当前对话上传文件")
    if any(word in text for word in ("不要", "不能", "仅", "只")):
        constraints.append("遵守用户显式限制")
    return constraints


def _extract_output_expectation(text: str) -> str:
    if any(word in text for word in ("摘要", "总结")):
        return "摘要和关键结论"
    if any(word in text for word in ("列出", "清单", "明细")):
        return "列表或明细"
    if any(word in text for word in ("预测", "计算", "风险")):
        return "结论、关键数值、依据和风险提示"
    return "与问题直接相关的业务结论和依据"


def _generic_task_type(capability: str, operation: Any, details: dict[str, Any]) -> str:
    text = str(operation or "").lower()
    if capability in {"document.table.extract", "document.parse"} or text in {"parse", "extract"}:
        return "parse"
    if capability == "data.search" or text in {"query", "search", "retrieve"}:
        return "retrieve"
    if capability == "data.aggregate" or text in {"aggregate", "sum", "count", "summarize", "summary"}:
        return "aggregate"
    if capability.startswith("analysis.") or "预测分析" in (details.get("calculations") or []):
        return "predict" if details.get("forecast_horizon") else "analyze"
    if capability == "rule.calculate":
        return "calculate" if details.get("calculations") else "risk_check"
    if capability.startswith("project."):
        return "register"
    if capability.startswith("monitor.") or capability.startswith("reminder."):
        return "monitor"
    if capability.startswith("human."):
        return "confirm"
    if capability == "content.generate":
        return "generate"
    return "analyze"


def _capability_category(capability: str) -> str:
    if capability in {"document.table.extract", "document.parse"}:
        return "document_table_parsing"
    if capability in {"data.search", "data.aggregate"}:
        return "data_operation"
    if capability.startswith("analysis."):
        return "analysis_prediction"
    if capability == "rule.calculate":
        return "rule_calculation"
    if capability.startswith("knowledge."):
        return "knowledge"
    if capability.startswith("project."):
        return "project_management"
    if capability.startswith("monitor.") or capability.startswith("reminder."):
        return "monitoring_reminder"
    if capability.startswith("human."):
        return "human_collaboration"
    if capability == "content.generate":
        return "content_generation"
    return "registered_platform_capability"


def _required_ability(task_type: str, details: dict[str, Any]) -> str:
    if task_type == "parse":
        return "extract_tables_fields_and_source_positions"
    if task_type == "retrieve":
        return "retrieve_authorized_relevant_records"
    if task_type == "aggregate":
        return "filter_group_aggregate_business_data"
    if task_type == "predict":
        return "forecast_metric_from_upstream_series"
    if task_type == "calculate":
        return "calculate_with_registered_rules"
    if task_type == "risk_check":
        return "check_business_risks_with_evidence"
    if task_type == "generate":
        return "generate_user_readable_business_answer"
    if task_type == "register":
        return "register_or_update_business_object"
    if task_type == "monitor":
        return "register_monitoring_or_reminder_items"
    if task_type == "confirm":
        return "create_human_confirmation_task"
    return "execute_registered_capability"


def _build_execution_instruction(
    *,
    utterance: str,
    task: dict[str, Any],
    task_name: str,
    capability: str,
    task_type: str,
    operation: str,
    input_parameters: dict[str, Any],
    parameters: dict[str, Any],
    extracted_details: dict[str, Any],
    uploaded_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the machine-readable instruction consumed by workflow execution."""
    model_instruction = task.get("execution_instruction")
    if not isinstance(model_instruction, dict):
        model_instruction = parameters.get("execution_instruction") if isinstance(parameters.get("execution_instruction"), dict) else {}
    filters = {}
    if isinstance(extracted_details.get("filters"), dict):
        filters.update(extracted_details["filters"])
    if isinstance(parameters.get("filters"), dict):
        filters.update(parameters["filters"])
    fields = parameters.get("fields") if isinstance(parameters.get("fields"), list) else []
    expected_outputs = parameters.get("expected_outputs") if isinstance(parameters.get("expected_outputs"), list) else []
    objective = (
        _clean_user_text(model_instruction.get("objective"))
        or _clean_user_text(task_name)
        or _clean_user_text(utterance)
        or "完成用户确认的业务任务"
    )
    output_requirements = model_instruction.get("output_requirements") if isinstance(model_instruction.get("output_requirements"), list) else []
    if not output_requirements:
        output_requirements = expected_outputs or [extracted_details.get("output_expectation") or "与用户问题直接相关的业务结论和依据"]
    constraints = model_instruction.get("constraints") if isinstance(model_instruction.get("constraints"), list) else []
    constraints = [
        *constraints,
        "不得编造未由上游数据或授权资料支持的业务事实",
        "不得改变用户明确指定的数据范围、筛选条件、时间范围或预测周期",
    ]
    if uploaded_documents:
        constraints.append("优先使用当前对话上传文件及其解析结果")
    return {
        "schema_version": "1.0",
        "objective": objective,
        "source_user_request": utterance,
        "action": model_instruction.get("action") or operation or task_type,
        "task_type": task_type,
        "target_capability": model_instruction.get("target_capability") or capability,
        "input_requirements": {
            "data_sources": extracted_details.get("data_sources") or (["current_uploaded_files"] if uploaded_documents else ["authorized_project_data"]),
            "data_object": parameters.get("data_object") or parameters.get("object") or "、".join(extracted_details.get("business_objects") or []),
            "fields": fields,
            "filters": filters,
            "time_range": input_parameters.get("time_range") or extracted_details.get("time_range") or "",
            "time_grain": input_parameters.get("time_grain") or extracted_details.get("time_grain") or "",
            "forecast_horizon": input_parameters.get("forecast_horizon") or extracted_details.get("forecast_horizon"),
            "target_year": input_parameters.get("target_year") or extracted_details.get("target_year"),
            "target_month": input_parameters.get("target_month") or extracted_details.get("target_month"),
            "target_period": input_parameters.get("target_period") or extracted_details.get("target_period"),
            "metrics": input_parameters.get("metrics") or extracted_details.get("metrics") or [],
            "calculations": input_parameters.get("calculations") or extracted_details.get("calculations") or [],
            "risk_checks": input_parameters.get("risk_checks") or extracted_details.get("risk_checks") or [],
            "uploaded_document_count": len(uploaded_documents),
        },
        "output_requirements": list(dict.fromkeys(str(item) for item in output_requirements if str(item or "").strip())),
        "constraints": list(dict.fromkeys(str(item) for item in constraints if str(item or "").strip())),
        "depends_on": task.get("dependencies") if isinstance(task.get("dependencies"), list) else [],
        "missing_inputs": parameters.get("missing_inputs") if isinstance(parameters.get("missing_inputs"), list) else [],
    }


def _build_intent_contract(
    tasks: list[dict[str, Any]],
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize model output into a portable, execution-oriented task graph."""
    if not tasks:
        return tasks
    normalized: list[dict[str, Any]] = []
    extracted_details = _extract_intent_details(utterance, uploaded_documents)
    for index, task in enumerate(tasks, start=1):
        parameters = task.get("parameters") if isinstance(task.get("parameters"), dict) else {}
        capability = str(task.get("capability_code") or "content.generate").strip()
        description = _normalize_task_description(task.get("description"), utterance, capability, parameters)
        task_type = _generic_task_type(capability, parameters.get("operation") or parameters.get("action"), extracted_details)
        data_access_contract = _build_data_access_contract(utterance, capability, parameters, uploaded_documents)
        task_parameters = {
            **(extracted_details.get("filters") if isinstance(extracted_details.get("filters"), dict) else {}),
            "metrics": extracted_details.get("metrics") or [],
            "time_range": extracted_details.get("time_range"),
            "time_grain": extracted_details.get("time_grain"),
            "forecast_horizon": extracted_details.get("forecast_horizon"),
            "business_objects": extracted_details.get("business_objects") or [],
            "calculations": extracted_details.get("calculations") or [],
            "risk_checks": extracted_details.get("risk_checks") or [],
        }
        task_parameters = {key: value for key, value in task_parameters.items() if value not in (None, "", [], {})}
        execution_instruction = _build_execution_instruction(
            utterance=utterance,
            task=task,
            task_name=description,
            capability=capability,
            task_type=task_type,
            operation=parameters.get("operation") or parameters.get("action") or "process",
            input_parameters=task_parameters,
            parameters=parameters,
            extracted_details=extracted_details,
            uploaded_documents=uploaded_documents,
        )
        contract = {
            "task_id": str(task.get("task_id") or f"intent-task-{index}"),
            "task_name": description,
            "task_type": task_type,
            "task_purpose": _required_ability(task_type, extracted_details),
            "execution_instruction": execution_instruction,
            "intent_type": str(parameters.get("original_task_type") or "USER_REQUEST"),
            "capability_code": capability,
            "capability_requirement": {
                "capability_category": _capability_category(capability),
                "required_ability": _required_ability(task_type, extracted_details),
                "must_use_registered_capability": True,
            },
            "data_object": parameters.get("data_object") or parameters.get("object") or "",
            "data_scope": parameters.get("data_scope") or (
                "conversation_uploads" if uploaded_documents else "authorized_project_data"
            ),
            "fields": parameters.get("fields") if isinstance(parameters.get("fields"), list) else [],
            "extracted_details": extracted_details,
            "input_refs": parameters.get("input_refs") or [{"type": "conversation", "id": "current"}],
            "required_data": parameters.get("required_data") or (
                [{"type": "uploaded_documents", "count": len(uploaded_documents)}]
                if uploaded_documents else [{"type": "authorized_project_data"}]
            ),
            "input_contract": {
                "required_inputs": parameters.get("required_inputs") if isinstance(parameters.get("required_inputs"), list) else [],
                "optional_inputs": [],
                "parameters": task_parameters,
                "data_refs": parameters.get("input_refs") or [{"type": "conversation", "id": "current"}],
            },
            "operation": parameters.get("operation") or parameters.get("action") or "process",
            "filters": parameters.get("filters") if isinstance(parameters.get("filters"), dict) else {},
            "output_contract": {
                "expected_outputs": parameters.get("expected_outputs") if isinstance(parameters.get("expected_outputs"), list) else [],
                "output_schema": parameters.get("output_schema") or {"type": "user_readable_result"},
                "evidence_required": True,
            },
            "output_schema": parameters.get("output_schema") or {"type": "user_readable_result"},
            "expected_outputs": parameters.get("expected_outputs") if isinstance(parameters.get("expected_outputs"), list) else [],
            "dependencies": task.get("dependencies") if isinstance(task.get("dependencies"), list) else [],
            "user_goal": utterance,
            "data_access_contract": data_access_contract,
            "human_confirmation_required": bool(parameters.get("missing_inputs")),
            "execution_policy": {
                "can_run_parallel": False,
                "must_audit": True,
                "must_use_registered_capability": True,
            },
        }
        parameters = {
            **parameters,
            "utterance": utterance,
            "uploaded_documents": uploaded_documents,
            "extracted_details": extracted_details,
            "execution_instruction": execution_instruction,
            "task_contract": contract,
            "data_access_contract": data_access_contract,
        }
        normalized.append({
            **task,
            "task_id": contract["task_id"],
            "description": description,
            "capability_code": capability,
            "dependencies": contract["dependencies"],
            "parameters": parameters,
        })
    sandbox_only = bool(normalized) and all(
        str(item.get("capability_code") or "").startswith("sandbox.")
        for item in normalized
    )
    if not sandbox_only:
        normalized = _ensure_required_generic_task_cards(normalized, utterance, uploaded_documents, extracted_details)
    graph = {
        "schema_version": "1.0",
        "user_goal": utterance,
        "extracted_details": extracted_details,
        "data_scope": "current_conversation_request" if sandbox_only else ("conversation_uploads" if uploaded_documents else "authorized_project_data"),
        "tasks": [item["parameters"]["task_contract"] for item in normalized],
        "source": "intent_analysis",
    }
    normalized[0]["parameters"]["intent_contract"] = graph
    explicit_summary = None
    if sandbox_only:
        first_parameters = normalized[0].get("parameters") if isinstance(normalized[0].get("parameters"), dict) else {}
        explicit_summary = first_parameters.get("model_intent_summary") if isinstance(first_parameters.get("model_intent_summary"), dict) else None
    summary = explicit_summary or _build_confirmation_summary_from_contract(graph, utterance, uploaded_documents)
    for item in normalized:
        item["parameters"]["intent_summary"] = summary
    return normalized


def _ensure_required_generic_task_cards(
    normalized: list[dict[str, Any]],
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
    extracted_details: dict[str, Any],
) -> list[dict[str, Any]]:
    capabilities = [str(item.get("capability_code") or "") for item in normalized]
    contracts = [
        (item.get("parameters") or {}).get("task_contract")
        for item in normalized
        if isinstance(item.get("parameters"), dict) and isinstance((item.get("parameters") or {}).get("task_contract"), dict)
    ]
    operations = [str((contract or {}).get("operation") or "").lower() for contract in contracts]

    parse_task_id = next((str(item.get("task_id")) for item in normalized if str(item.get("capability_code") or "") in {"document.table.extract", "document.parse"}), "")
    if uploaded_documents and not parse_task_id:
        parse = _generated_contract_task(
            utterance, uploaded_documents, extracted_details,
            task_id="intent-parse-uploaded-documents",
            capability="document.table.extract",
            task_type="parse",
            operation="extract",
            task_name="读取并解析当前对话上传文件",
            dependencies=[],
        )
        normalized.insert(0, parse)
        parse_task_id = parse["task_id"]
        capabilities.insert(0, "document.table.extract")
        operations.insert(0, "extract")

    forecast_horizon = extracted_details.get("forecast_horizon")
    target_period = extracted_details.get("target_period")
    data_series_task_id = next(
        (
            str(item.get("task_id"))
            for item in normalized
            if str(item.get("capability_code") or "") == "data.aggregate"
            and str(((item.get("parameters") or {}).get("task_contract") or {}).get("operation") or "").lower() == "monthly_metric_series"
        ),
        "",
    )
    if (forecast_horizon or target_period) and not data_series_task_id:
        data_series = _generated_contract_task(
            utterance, uploaded_documents, extracted_details,
            task_id="intent-aggregate-metric-series",
            capability="data.aggregate",
            task_type="aggregate",
            operation="monthly_metric_series",
            task_name="整理预测所需的时间序列数据",
            dependencies=[parse_task_id] if parse_task_id else [],
        )
        normalized.append(data_series)
        data_series_task_id = data_series["task_id"]
        capabilities.append("data.aggregate")
        operations.append("monthly_metric_series")

    if (forecast_horizon or target_period) and not any(capability.startswith("analysis.") for capability in capabilities):
        analysis = _generated_contract_task(
            utterance, uploaded_documents, extracted_details,
            task_id="intent-analysis-forecast",
            capability="analysis.business_metric",
            task_type="predict",
            operation="forecast",
            task_name="按用户指定周期进行指标预测",
            dependencies=[data_series_task_id] if data_series_task_id else ([parse_task_id] if parse_task_id else []),
        )
        normalized.append(analysis)
        capabilities.append("analysis.business_metric")
        operations.append("forecast")

    needs_rule = bool(extracted_details.get("calculations") or extracted_details.get("risk_checks"))
    budget_task_id = next(
        (
            str(item.get("task_id"))
            for item in normalized
            if str(item.get("capability_code") or "") == "data.aggregate"
            and str(((item.get("parameters") or {}).get("task_contract") or {}).get("operation") or "").lower() == "budget_summary"
        ),
        "",
    )
    if needs_rule and not budget_task_id:
        budget = _generated_contract_task(
            utterance, uploaded_documents, extracted_details,
            task_id="intent-aggregate-rule-data",
            capability="data.aggregate",
            task_type="aggregate",
            operation="budget_summary",
            task_name="整理计算和风险检查所需的数据",
            dependencies=[parse_task_id] if parse_task_id else [],
        )
        normalized.append(budget)
        budget_task_id = budget["task_id"]
        capabilities.append("data.aggregate")
        operations.append("budget_summary")

    if needs_rule and "rule.calculate" not in capabilities:
        rule = _generated_contract_task(
            utterance, uploaded_documents, extracted_details,
            task_id="intent-rule-calculate",
            capability="rule.calculate",
            task_type="calculate",
            operation="calculate",
            task_name="执行用户要求的计算和风险检查",
            dependencies=[budget_task_id] if budget_task_id else ([parse_task_id] if parse_task_id else []),
        )
        normalized.append(rule)
        capabilities.append("rule.calculate")
        operations.append("calculate")

    if "content.generate" not in capabilities:
        depended = {
            dep
            for item in normalized
            for dep in (((item.get("parameters") or {}).get("task_contract") or {}).get("dependencies") or [])
        }
        leaves = [str(item.get("task_id")) for item in normalized if str(item.get("task_id")) not in depended]
        content = _generated_contract_task(
            utterance, uploaded_documents, extracted_details,
            task_id="intent-generate-answer",
            capability="content.generate",
            task_type="generate",
            operation="generate",
            task_name="生成用户可读业务回答",
            dependencies=leaves,
        )
        normalized.append(content)
    return normalized


def _generated_contract_task(
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
    extracted_details: dict[str, Any],
    *,
    task_id: str,
    capability: str,
    task_type: str,
    operation: str,
    task_name: str,
    dependencies: list[str],
) -> dict[str, Any]:
    params = {
        "utterance": utterance,
        "uploaded_documents": uploaded_documents,
        "operation": operation,
        "action": operation,
        "extracted_details": extracted_details,
        "required_inputs": [],
        "missing_inputs": [],
        "expected_outputs": [],
        "fields": [],
        "filters": extracted_details.get("filters") if isinstance(extracted_details.get("filters"), dict) else {},
        "planning_owner": "workflow_execution",
        "generated_by": "intent_adapter.generic_task_completion",
    }
    data_access_contract = _build_data_access_contract(utterance, capability, params, uploaded_documents)
    input_parameters = {
        **(extracted_details.get("filters") if isinstance(extracted_details.get("filters"), dict) else {}),
        "metrics": extracted_details.get("metrics") or [],
        "time_range": extracted_details.get("time_range"),
        "time_grain": extracted_details.get("time_grain"),
        "forecast_horizon": extracted_details.get("forecast_horizon"),
        "target_year": extracted_details.get("target_year"),
        "target_month": extracted_details.get("target_month"),
        "target_period": extracted_details.get("target_period"),
        "business_objects": extracted_details.get("business_objects") or [],
        "calculations": extracted_details.get("calculations") or [],
        "risk_checks": extracted_details.get("risk_checks") or [],
    }
    input_parameters = {key: value for key, value in input_parameters.items() if value not in (None, "", [], {})}
    execution_instruction = _build_execution_instruction(
        utterance=utterance,
        task={"task_id": task_id, "task_name": task_name, "dependencies": dependencies},
        task_name=task_name,
        capability=capability,
        task_type=task_type,
        operation=operation,
        input_parameters=input_parameters,
        parameters=params,
        extracted_details=extracted_details,
        uploaded_documents=uploaded_documents,
    )
    contract = {
        "task_id": task_id,
        "task_name": task_name,
        "task_type": task_type,
        "task_purpose": _required_ability(task_type, extracted_details),
        "execution_instruction": execution_instruction,
        "intent_type": "GENERATED_GENERIC_TASK",
        "capability_code": capability,
        "capability_requirement": {
            "capability_category": _capability_category(capability),
            "required_ability": _required_ability(task_type, extracted_details),
            "must_use_registered_capability": True,
        },
        "data_object": "、".join(extracted_details.get("business_objects") or []),
        "data_scope": "conversation_uploads" if uploaded_documents else "authorized_project_data",
        "fields": [],
        "extracted_details": extracted_details,
        "input_refs": [{"type": "conversation", "id": "current"}],
        "required_data": [{"type": "uploaded_documents", "count": len(uploaded_documents)}] if uploaded_documents else [{"type": "authorized_project_data"}],
        "input_contract": {
            "required_inputs": [],
            "optional_inputs": [],
            "parameters": input_parameters,
            "data_refs": [{"type": "conversation", "id": "current"}],
        },
        "operation": operation,
        "filters": extracted_details.get("filters") if isinstance(extracted_details.get("filters"), dict) else {},
        "output_contract": {
            "expected_outputs": [],
            "output_schema": {"type": "user_readable_result"},
            "evidence_required": True,
        },
        "output_schema": {"type": "user_readable_result"},
        "expected_outputs": [],
        "dependencies": [dep for dep in dependencies if dep],
        "user_goal": utterance,
        "data_access_contract": data_access_contract,
        "human_confirmation_required": False,
        "execution_policy": {
            "can_run_parallel": False,
            "must_audit": True,
            "must_use_registered_capability": True,
        },
    }
    params["task_contract"] = contract
    params["data_access_contract"] = data_access_contract
    params["execution_instruction"] = execution_instruction
    return {
        "task_id": task_id,
        "description": task_name,
        "capability_code": capability,
        "dependencies": contract["dependencies"],
        "parameters": params,
        "confidence": 0.8,
    }


def _build_intent_card(
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
    platform_tasks: list[dict[str, Any]],
    extracted_details: dict[str, Any],
) -> dict[str, Any]:
    task_cards = []
    for item in platform_tasks:
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        contract = params.get("task_contract") if isinstance(params.get("task_contract"), dict) else {}
        if contract:
            task_cards.append(contract)
    summary = _build_confirmation_summary_from_contract(
        {"tasks": task_cards},
        utterance,
        uploaded_documents,
    )
    return {
        "schema_version": "1.0",
        "intent_type": "business_task",
        "user_goal": utterance,
        "understanding_summary": summary.get("business_goal") or utterance,
        "extracted_details": extracted_details,
        "tasks": task_cards,
        "missing_information": _missing_information_from_tasks(task_cards),
        "confirmation": {
            "required": True,
            "user_visible_text": summary,
            "editable_fields": ["understanding_summary", "extracted_details", "tasks"],
        },
    }


def _missing_information_from_tasks(task_cards: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for task in task_cards:
        input_contract = task.get("input_contract") if isinstance(task.get("input_contract"), dict) else {}
        for item in input_contract.get("required_inputs") or []:
            text = str(item or "").strip()
            if text and text not in {"data_source", "file", "uploaded_documents"} and text not in missing:
                missing.append(text)
    return missing


def _build_confirmation_summary_from_contract(
    contract: dict[str, Any],
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the confirmation card from business tasks, not module steps."""
    contract_tasks = contract.get("tasks") if isinstance(contract.get("tasks"), list) else []
    task_list: list[str] = []
    expected_outputs: list[str] = []
    for task in contract_tasks:
        if not isinstance(task, dict):
            continue
        label = _business_task_label(task, utterance)
        if label and label not in task_list:
            task_list.append(label)
        for output in task.get("expected_outputs") or []:
            output_text = str(output).strip()
            if output_text and output_text not in expected_outputs:
                expected_outputs.append(output_text)
    if not task_list:
        task_list = [_infer_business_goal(utterance, "content.generate")]
    return {
        "business_goal": _infer_business_goal(utterance, "content.generate"),
        "data_scope": f"当前对话上传的 {len(uploaded_documents)} 个文件" if uploaded_documents else "当前账号和项目授权资料",
        "task_list": task_list,
        "planned_steps": task_list,
        "output_focus": "、".join(expected_outputs) if expected_outputs else _infer_output_focus(utterance, "content.generate"),
        "confirmation_question": "请确认以上任务清单是否符合你的意图。",
    }


def _business_task_label(task: dict[str, Any], utterance: str) -> str:
    description = str(task.get("task_name") or "").strip()
    data_object = str(task.get("data_object") or "").strip()
    operation = str(task.get("operation") or "").strip().lower()
    capability = str(task.get("capability_code") or "").strip()
    fields = [str(item).strip() for item in (task.get("fields") or []) if str(item).strip()]
    generic_descriptions = {
        "",
        utterance,
        "处理当前对话中的业务请求",
        "根据现有资料生成内容",
        "汇总当前资料并输出结论",
        "执行识别到的业务能力",
    }
    if description not in generic_descriptions and not _looks_like_runtime_context(description):
        return description
    object_name = data_object or str(task.get("task_name") or "").strip() or "相关资料"
    if capability in {"document.parse", "document.table.extract"}:
        return f"从授权资料中定位与“{object_name}”相关的数据" if data_object else "定位本次问题需要使用的上传文件内容"
    if capability == "data.search" or operation in {"retrieve", "query", "search"}:
        return f"定位并读取“{object_name}”"
    if capability == "data.aggregate" or operation in {"count", "sum", "aggregate", "summarize", "compare"}:
        field_text = "、".join(fields[:4])
        return f"统计分析“{object_name}”" + (f"中的{field_text}" if field_text else "")
    if capability.startswith("analysis.") or operation in {"forecast", "analyze"}:
        return f"分析“{object_name}”并形成判断"
    if capability == "content.generate" or operation in {"recommend", "generate", "answer"}:
        return "基于前面统计分析结果生成后续执行意见"
    return f"处理“{object_name}”相关任务"


def _build_workflow_hints(
    utterance: str,
    capability: str,
    parameters: dict[str, Any],
    uploaded_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Expose intent facts without prescribing the workflow graph."""
    return {
        "user_goal": utterance,
        "primary_capability": capability,
        "data_scope": "conversation_uploads" if uploaded_documents else "authorized_project_data",
        "uploaded_document_count": len(uploaded_documents),
        "operation": parameters.get("action") or "answer",
        "object": parameters.get("object") or "",
        "planning_required": True,
        "planning_owner": "workflow_execution",
    }


def _looks_like_month_demand_summary(text: str) -> bool:
    has_month = any(word in text for word in ("哪个月", "哪月", "那个月", "月份", "月"))
    has_rank = any(word in text for word in ("最多", "最高", "最大", "最多的", "最高的"))
    has_metric = any(word in text for word in ("需求", "订单", "销量", "销售量", "数量"))
    return has_month and has_rank and has_metric


def _build_intent_summary(utterance: str, capability: str, parameters: dict[str, Any], uploaded_documents: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[str] = []
    if any(word in utterance for word in ("采购", "验收")):
        checks.extend(["采购金额", "合同编号", "发票信息", "验收状态"])
    if any(word in utterance for word in ("金额差异", "差异", "尾款", "付款", "回款")):
        checks.append("金额差异")
    if any(word in utterance for word in ("发票缺失", "附件", "未上传", "齐全")):
        checks.append("附件齐全性")
    if "抬头" in utterance:
        checks.append("发票抬头一致性")
    if any(word in utterance for word in ("风险", "风险点")):
        checks.append("风险点")
    if any(word in utterance for word in ("核对", "验收", "对账")):
        checks.append("需要人工核对的事项")
    deduped_checks = list(dict.fromkeys(checks)) or ["文件关键信息", "需要人工核对的事项", "风险点"]
    output_items: list[str] = []
    if any(word in utterance for word in ("摘要", "总结")):
        output_items.append("采购验收摘要")
    output_items.extend([f"{item}清单" for item in deduped_checks if item in {"采购金额", "需要人工核对的事项", "风险点"}])
    output_items = list(dict.fromkeys(output_items)) or ["处理结果摘要", "核对事项", "风险提示"]
    return {
        "business_goal": _infer_business_goal(utterance, capability),
        "data_scope": f"当前对话上传的 {len(uploaded_documents)} 个文件" if uploaded_documents else "当前对话和项目资料",
        "planned_steps": ["读取并解析上传文件", "提取关键字段", "按核对项检查异常", "生成用户可读结论"],
        "check_items": deduped_checks,
        "expected_outputs": output_items,
        "confirmation_question": "请确认是否按以上任务理解继续执行。",
    }


def _build_task_plan_draft(utterance: str, capability: str, parameters: dict[str, Any], uploaded_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = utterance or str(parameters.get("utterance") or "")
    plan: list[dict[str, Any]] = []
    if uploaded_documents:
        plan.append({
            "step": len(plan) + 1,
            "name": "读取并解析当前对话上传文件",
            "capability_code": "document.table.extract",
            "depends_on": [],
            "payload_hint": {"uploaded_documents": uploaded_documents},
            "purpose": "把文件中的表格、字段、来源位置提取出来，供后续分析使用",
        })
    needs_entity_list = _looks_like_entity_list_request(text)
    needs_aggregate = needs_entity_list or any(word in text for word in ("最多", "最高", "最大", "汇总", "统计", "哪个月", "哪月", "月份", "需求"))
    needs_forecast = any(word in text for word in ("预测", "下一个月", "下个月", "下月", "下季度", "需求区间", "趋势"))
    if needs_aggregate:
        plan.append({
            "step": len(plan) + 1,
            "name": "按业务条件汇总数据",
            "capability_code": "data.aggregate",
            "depends_on": [item["step"] for item in plan[-1:]],
            "payload_hint": {
                "dataset": "extracted_fields" if uploaded_documents else "business_records",
                "analysis_goal": text,
                **(
                    {"aggregate_operation": "list_distinct"}
                    if needs_entity_list
                    else {"aggregate_operation": "monthly_max_metric", "time_field": "month", "metric_field": "demand_qty"}
                ),
            },
            "purpose": "根据用户问题筛选年份、月份和需求字段，计算汇总结果",
        })
    elif needs_forecast:
        plan.append({
            "step": len(plan) + 1,
            "name": "进行业务指标预测",
            "capability_code": "analysis.business_metric",
            "depends_on": [item["step"] for item in plan[-1:]],
            "payload_hint": {"analysis_goal": text, "metric": "demand"},
            "purpose": "基于已授权数据形成预测或趋势判断",
        })
    elif capability not in {"document.parse", "document.table.extract"}:
        plan.append({
            "step": len(plan) + 1,
            "name": "执行识别到的业务能力",
            "capability_code": capability,
            "depends_on": [item["step"] for item in plan[-1:]],
            "payload_hint": {},
            "purpose": "按意图分析识别的能力处理用户请求",
        })
    plan.append({
        "step": len(plan) + 1,
        "name": "生成用户可读结论",
        "capability_code": "content.generate",
        "depends_on": [item["step"] for item in plan[-1:]],
        "payload_hint": {"content_type": "workflow_user_answer", "utterance": text},
        "purpose": "把模块结果整理成前端用户能直接理解的回答",
    })
    return plan


def _infer_business_goal(utterance: str, capability: str) -> str:
    if any(word in utterance for word in ("采购", "验收")):
        return "生成采购验收核对摘要"
    if any(word in utterance for word in ("对账", "核对")):
        return "核对上传文件中的业务数据并标出疑点"
    if capability == "content.generate":
        return "根据现有资料生成内容"
    if capability == "data.aggregate":
        return "汇总当前资料并输出结论"
    return "处理当前对话中的业务请求"


def _build_intent_summary(utterance: str, capability: str, parameters: dict[str, Any], uploaded_documents: list[dict[str, Any]]) -> dict[str, Any]:
    business_goal = _infer_business_goal(utterance, capability)
    data_scope = f"当前对话上传的 {len(uploaded_documents)} 个文件" if uploaded_documents else "当前对话和项目资料"
    return {
        "business_goal": business_goal,
        "data_scope": data_scope,
        "output_focus": _infer_output_focus(utterance, capability),
        "task_list": ["按当前对话和资料识别任务", "调用对应模块处理任务", "生成用户可读回答"],
        "confirmation_question": "请确认以上任务清单是否符合你的意图。",
    }


def _build_task_plan_draft(utterance: str, capability: str, parameters: dict[str, Any], uploaded_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = utterance or str(parameters.get("utterance") or "")
    plan: list[dict[str, Any]] = []
    if uploaded_documents:
        plan.append({
            "step": len(plan) + 1,
            "name": "读取并解析当前对话上传文件",
            "capability_code": "document.table.extract",
            "depends_on": [],
            "payload_hint": {"uploaded_documents": uploaded_documents},
            "purpose": "把文件中的工作表、字段、行号和值抽取出来，并保留来源位置。",
        })
    action = str(parameters.get("action") or "").strip().lower()
    object_name = str(parameters.get("object") or "").strip()
    # General questions are data-backed by default: current conversation files
    # are searched first, then the actor's authorized platform data. Knowledge
    # retrieval remains available only for capabilities explicitly planned for it.
    data_backed_question = capability == "knowledge.query"
    count_request = action in {"count", "统计", "计数"} or "数量" in object_name
    if capability == "data.aggregate" or _looks_like_month_demand_summary(text) or (data_backed_question and count_request):
        plan.append({
            "step": len(plan) + 1,
            "name": "按业务问题汇总数据",
            "capability_code": "data.aggregate",
            "depends_on": [item["step"] for item in plan[-1:]],
            "payload_hint": {
                "dataset": "extracted_fields" if uploaded_documents else "business_records",
                "analysis_goal": text,
                "aggregate_operation": "monthly_max_metric",
                "time_field": "month",
                "metric_field": "demand_qty",
            },
            "purpose": "根据用户问题筛选年份、月份和需求字段，计算汇总结果。",
        })
    elif data_backed_question:
        plan.append({
            "step": len(plan) + 1,
            "name": "在已授权数据中检索相关资料",
            "capability_code": "data.search",
            "depends_on": [item["step"] for item in plan[-1:]],
            "payload_hint": {
                "dataset": "extracted_fields" if uploaded_documents else "business_records",
                "query": text,
            },
            "purpose": "优先检索当前对话已上传文件；没有匹配内容时，再按账户、项目和对话权限检索平台业务数据。",
        })
    elif any(word in text for word in ("预测", "下一个月", "下个月", "下月", "下季度", "需求区间", "趋势")):
        plan.append({
            "step": len(plan) + 1,
            "name": "进行业务指标预测",
            "capability_code": "analysis.business_metric",
            "depends_on": [item["step"] for item in plan[-1:]],
            "payload_hint": {"analysis_goal": text, "metric": "demand"},
            "purpose": "基于已授权数据形成预测或趋势判断。",
        })
    elif capability not in {"document.parse", "document.table.extract"}:
        plan.append({
            "step": len(plan) + 1,
            "name": "执行识别到的业务能力",
            "capability_code": capability,
            "depends_on": [item["step"] for item in plan[-1:]],
            "payload_hint": {},
            "purpose": "按意图分析识别到的能力处理用户请求。",
        })
    plan.append({
        "step": len(plan) + 1,
        "name": "生成用户可读回答",
        "capability_code": "content.generate",
        "depends_on": [item["step"] for item in plan[-1:]],
        "payload_hint": {"content_type": "workflow_user_answer", "utterance": text},
        "purpose": "把模块结果整理成前端用户能直接理解的回答。",
    })
    return plan


def _infer_business_goal(utterance: str, capability: str) -> str:
    if "数字资产" in utterance and any(word in utterance for word in ("哪些", "有哪些", "列举", "清单", "明细")):
        return "查看上传文件中的数字资产清单"
    if "经销商" in utterance and any(word in utterance for word in ("几个", "多少个", "列举", "一一列举", "参与", "合作")):
        return "统计上传文件中的经销商数量并列出名称"
    if "需求" in utterance and any(word in utterance for word in ("最高", "最多", "月份", "月")):
        return "统计上传文件中的需求月份并找出最高月份"
    year = _year_from_text(utterance)
    if _looks_like_month_demand_summary(utterance):
        year_label = f"{year} 年" if year else "指定年份"
        return f"统计当前上传文件中 {year_label}需求最高的月份"
    if any(word in utterance for word in ("经销商", "客户", "供应商")) and any(
        word in utterance for word in ("几个", "多少", "数量", "列举", "名单", "名称")
    ):
        subject = "经销商" if "经销商" in utterance else ("客户" if "客户" in utterance else "供应商")
        return f"统计上传资料中的{subject}数量并列出名称"
    if any(word in utterance for word in ("几个", "多少个", "数量", "列举", "名单")):
        return "统计当前授权资料中的目标对象并输出明细"
    if any(word in utterance for word in ("采购", "验收")):
        return "生成采购验收摘要并列出需要核对的事项"
    if any(word in utterance for word in ("对账", "核对")):
        return "核对上传文件中的业务数据并标出疑点"
    if any(word in utterance for word in ("预测", "下一个月", "下个月", "下月", "下季度", "趋势")):
        return "分析业务数据并形成预测判断"
    if capability == "content.generate":
        return "根据现有资料生成内容"
    if capability == "data.aggregate":
        return "汇总当前资料并输出结论"
    return "处理当前对话中的业务请求"


def _infer_output_focus(utterance: str, capability: str) -> str:
    if _looks_like_month_demand_summary(utterance):
        return "最高月份、对应需求量、各月汇总明细和证据行"
    if any(word in utterance for word in ("采购", "验收")):
        return "采购验收摘要、金额信息、核对事项和风险点"
    if any(word in utterance for word in ("对账", "核对")):
        return "差异项、证据位置和需要人工确认的事项"
    return "与问题直接相关的业务结论和依据"


def _year_from_text(text: str) -> int | None:
    match = re.search(r"(20\d{2})", text)
    return int(match.group(1)) if match else None


def _infer_business_goal(utterance: str, capability: str) -> str:
    """Keep the user's wording as the business goal; do not invent a scenario."""
    text = str(utterance or "").strip()
    if text:
        return text
    return "处理当前对话中的业务请求"


def _build_intent_summary(utterance: str, capability: str, parameters: dict[str, Any], uploaded_documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Return user-facing intent confirmation as a task list."""
    business_goal = _infer_business_goal(utterance, capability)
    data_scope = f"当前对话上传的 {len(uploaded_documents)} 个文件" if uploaded_documents else "当前对话和项目授权资料"
    planned_steps = _infer_user_facing_task_steps(utterance, capability, uploaded_documents)
    return {
        "business_goal": business_goal,
        "data_scope": data_scope,
        "task_list": planned_steps,
        "planned_steps": planned_steps,
        "output_focus": _infer_output_focus(utterance, capability),
        "confirmation_question": "请确认以上任务清单是否符合你的意图。",
    }


def _infer_user_facing_task_steps(utterance: str, capability: str, uploaded_documents: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    if uploaded_documents:
        steps.append("读取并解析当前对话上传的文件")
        steps.append("从已解析内容中定位与问题直接相关的数据")
    else:
        steps.append("读取当前账号和项目有权限使用的数据")
    if capability in {"data.aggregate", "data.search", "rule.calculate"} or any(word in utterance for word in ("多少", "比例", "百分比", "占", "统计", "计算", "预算", "金额")):
        steps.append("按用户问题计算或推理所需指标")
    elif capability.startswith("knowledge"):
        steps.append("检索与问题相关的知识和材料")
    else:
        steps.append("调用已登记能力处理用户问题")
    steps.append("生成包含结论和依据的用户可读回答")
    return steps


def _looks_like_entity_list_request(text: str) -> bool:
    lowered = str(text or "").lower()
    entity_words = ("经销商", "客户", "供应商", "产品", "物料", "人员", "员工", "门店", "仓库", "区域", "dealer", "distributor", "customer", "supplier", "product")
    list_words = ("哪些", "有哪些", "都有谁", "有谁", "所有", "全部", "确定", "列出", "列举", "名单", "清单", "明细", "去重", "一一", "分别", "几个", "多少", "多少个", "数量", "总数", "个数")
    return any(word in lowered for word in entity_words) and any(word in lowered for word in list_words)


# Final user-facing overrides. Earlier compatibility functions are kept for old
# adapters, but the confirmation card should describe the user's intent, not
# expose a generic "content generation" fallback.
GENERIC_CONFIRMATION_LABELS = {
    "",
    "基于前面统计分析结果生成后续执行意见",
    "处理当前对话中的业务请求",
    "根据现有资料生成内容",
    "汇总当前资料并输出结论",
    "执行识别到的业务能力",
    "按问题要求统计数量或汇总指标",
    "预测趋势或下周期业务指标",
}

GENERIC_CONFIRMATION_PREFIXES = (
    "回答用户问题：",
    "处理用户问题：",
    "处理当前问题：",
)


def _extract_model_intent_summary(raw_result: Any, utterance: str, uploaded_documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(raw_result, dict):
        return None
    raw = (
        raw_result.get("user_facing_intent_summary")
        or raw_result.get("intent_summary")
        or raw_result.get("confirmation_summary")
    )
    nested_result = raw_result.get("result")
    if not isinstance(raw, dict) and isinstance(nested_result, dict):
        raw = (
            nested_result.get("user_facing_intent_summary")
            or nested_result.get("intent_summary")
            or nested_result.get("confirmation_summary")
        )
    if not isinstance(raw, dict):
        tasks = []
        if isinstance(raw_result.get("tasks"), list):
            tasks = raw_result.get("tasks") or []
        elif isinstance(nested_result, dict) and isinstance(nested_result.get("tasks"), list):
            tasks = nested_result.get("tasks") or []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            parameters = task.get("parameters") if isinstance(task.get("parameters"), dict) else {}
            raw = (
                task.get("user_facing_intent_summary")
                or task.get("intent_summary")
                or parameters.get("user_facing_intent_summary")
                or parameters.get("intent_summary")
                or parameters.get("model_intent_summary")
            )
            if isinstance(raw, dict):
                break
    if not isinstance(raw, dict):
        return None
    business_goal = _clean_user_text(raw.get("business_goal") or raw.get("goal") or raw.get("user_goal"))
    task_list_raw = raw.get("task_list") or raw.get("planned_steps") or raw.get("tasks") or []
    task_list = [
        _clean_user_text(item)
        for item in task_list_raw
        if _clean_user_text(item) and not _is_generic_confirmation_text(_clean_user_text(item))
    ] if isinstance(task_list_raw, list) else []
    output_focus = _clean_user_text(raw.get("output_focus") or raw.get("expected_output") or raw.get("expected_outputs"))
    data_scope = _clean_user_text(raw.get("data_scope"))
    confirmation_question = _clean_user_text(raw.get("confirmation_question")) or "请确认以上理解是否符合你的意图。"
    if not business_goal or _is_generic_confirmation_text(business_goal):
        business_goal = _clean_user_text(utterance)
    if not task_list:
        return None
    if not output_focus:
        output_focus = "与问题直接相关的业务结论和依据"
    if not data_scope:
        data_scope = f"当前对话上传的 {len(uploaded_documents)} 个文件" if uploaded_documents else "当前账号和项目授权数据"
    return {
        "source": "model",
        "business_goal": business_goal,
        "data_scope": data_scope,
        "task_list": task_list[:5],
        "planned_steps": task_list[:5],
        "output_focus": output_focus,
        "confirmation_question": confirmation_question,
    }


def _first_model_intent_summary(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in tasks:
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        summary = parameters.get("model_intent_summary")
        if isinstance(summary, dict) and summary.get("task_list"):
            return summary
    return None


def _clean_user_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:180]


def _is_generic_confirmation_text(text: str) -> bool:
    value = _clean_user_text(text)
    if value in GENERIC_CONFIRMATION_LABELS:
        return True
    return any(value.startswith(prefix) for prefix in GENERIC_CONFIRMATION_PREFIXES)


def _intent_goal_from_utterance(utterance: str, capability: str) -> str:
    text = _clean_user_text(utterance)
    if text:
        return text
    if capability.startswith("analysis."):
        return "分析授权业务数据并形成预测或判断"
    if capability == "rule.calculate":
        return "核对业务规则并标出风险点"
    if capability in {"data.search", "data.aggregate"}:
        return "查询或统计授权业务数据"
    if capability.startswith("knowledge."):
        return "查询授权知识资料并回答问题"
    return "处理当前对话中的业务请求"


def _business_task_label(task: dict[str, Any], utterance: str) -> str:
    description = _clean_user_text(task.get("task_name"))
    capability = str(task.get("capability_code") or "").strip()
    operation = str(task.get("operation") or "").strip().lower()
    data_object = _clean_user_text(task.get("data_object"))
    fields = [str(item).strip() for item in (task.get("fields") or []) if str(item).strip()]

    if capability in {"document.table.extract", "document.parse"} or operation in {"extract", "parse"}:
        return "读取并解析当前对话上传文件"
    if description and description not in GENERIC_CONFIRMATION_LABELS and description != _clean_user_text(utterance) and not _looks_like_runtime_context(description):
        return description
    if data_object and fields:
        return f"围绕“{data_object}”处理字段：{'、'.join(fields[:4])}"
    if data_object:
        if capability in {"data.search"} or operation in {"retrieve", "query", "search"}:
            return f"查询与“{data_object}”相关的数据"
        if capability == "data.aggregate" or operation in {"count", "sum", "aggregate", "summarize", "compare"}:
            return f"统计分析“{data_object}”"
        if capability.startswith("analysis."):
            return f"分析“{data_object}”并形成判断"
        if capability == "rule.calculate":
            return f"核对“{data_object}”相关规则和风险"
    return _task_label_from_utterance(utterance, capability)


def _task_label_from_utterance(utterance: str, capability: str) -> str:
    text = _clean_user_text(utterance)
    if capability == "content.generate":
        return f"回答用户问题：{text}" if text else "生成用户可读回答"
    return f"处理用户问题：{text}" if text else "处理当前业务问题"


def _infer_business_goal(utterance: str, capability: str) -> str:
    return _intent_goal_from_utterance(utterance, capability)


def _infer_output_focus(utterance: str, capability: str) -> str:
    return "与问题直接相关的业务结论和依据"


def _infer_user_facing_task_steps(utterance: str, capability: str, uploaded_documents: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    if uploaded_documents:
        steps.append("优先使用当前对话上传的文件")
    else:
        steps.append("使用当前账号和项目有权限的数据")
    steps.append(_task_label_from_utterance(utterance, capability))
    steps.append("整理成可以直接阅读的回答")
    return list(dict.fromkeys(step for step in steps if step and not _is_generic_confirmation_text(step)))


def _build_intent_summary(utterance: str, capability: str, parameters: dict[str, Any], uploaded_documents: list[dict[str, Any]]) -> dict[str, Any]:
    business_goal = _infer_business_goal(utterance, capability)
    data_scope = f"当前对话上传的 {len(uploaded_documents)} 个文件" if uploaded_documents else "当前账号和项目授权数据"
    planned_steps = _infer_user_facing_task_steps(utterance, capability, uploaded_documents)
    return {
        "business_goal": business_goal,
        "data_scope": data_scope,
        "task_list": planned_steps,
        "planned_steps": planned_steps,
        "output_focus": _infer_output_focus(utterance, capability),
        "confirmation_question": "请确认以上理解是否符合你的意图。",
    }


def _build_confirmation_summary_from_contract(
    contract: dict[str, Any],
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    contract_tasks = contract.get("tasks") if isinstance(contract.get("tasks"), list) else []
    task_list: list[str] = []
    capabilities: list[str] = []
    for task in contract_tasks:
        if not isinstance(task, dict):
            continue
        capability = str(task.get("capability_code") or "").strip()
        if capability:
            capabilities.append(capability)
        label = _business_task_label(task, utterance)
        if label and not _is_generic_confirmation_text(label) and label not in task_list:
            task_list.append(label)
    if not task_list:
        task_list = [_task_label_from_utterance(utterance, capabilities[0] if capabilities else "content.generate")]
    primary = capabilities[0] if capabilities else "content.generate"
    return {
        "business_goal": _infer_business_goal(utterance, primary),
        "data_scope": f"当前对话上传的 {len(uploaded_documents)} 个文件" if uploaded_documents else "当前账号和项目授权数据",
        "task_list": task_list[:8],
        "planned_steps": task_list[:8],
        "output_focus": _infer_output_focus(utterance, primary),
        "confirmation_question": "请确认以上理解是否符合你的意图。",
    }
