from __future__ import annotations

import re
from typing import Any

from framework.core import standard_response
from framework.http import post_json


TASK_CAPABILITY_MAP = {
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
}

CAPABILITY_ALIASES = {
    "knowledge.answer": "knowledge.qa.answer",
    "knowledge_qa.answer": "knowledge.qa.answer",
    "knowledge.answer.contextual": "knowledge.qa.contextual_answer",
}


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/intent/analyze":
        handler.send(404); return
    utterance = str(envelope.get("payload", {}).get("utterance", "")).strip()
    uploaded_documents = envelope.get("payload", {}).get("uploaded_documents") or []
    if not utterance:
        handler.send(422, {"error": {"code": "PRECONDITION_REQUIRED"}}); return
    request = {
        "text": utterance,
        "user_id": envelope["actor"].get("actor_id") or envelope["actor"].get("user_id") or "unknown",
        "conversation_id": envelope.get("context", {}).get("conversation_id"),
        "project_id": envelope.get("context", {}).get("project_id"),
        "trace_id": envelope["trace_id"], "actor": envelope["actor"],
        "platform_task_id": envelope.get("payload", {}).get("platform_task_id"),
        "uploaded_documents": uploaded_documents,
    }
    status, delivered = post_json(
        "http://127.0.0.1:8003/api/v1/delivered-intent/analyze", request,
        timeout=55, caller={"layer": "business_engine", "module": "intent-adapter"},
    )
    if status != 200 or not delivered.get("success"):
        handler.send(502, standard_response(envelope, "failed", error={"code": "DELIVERED_INTENT_ENGINE_FAILED", "details": delivered, "retryable": True})); return

    original = delivered.get("data") or {}
    meta = delivered.get("engine_meta") or {}
    platform_tasks = []
    # Python treats Chinese characters as ``\w``. Guard only against adjacent
    # digits/decimal points so values such as "金额1200元" are not discarded.
    numeric_values = [float(value) for value in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", utterance)]
    for task in original.get("tasks", []):
        task_type = task.get("task_type", "")
        capability = TASK_CAPABILITY_MAP.get(task_type, f"unmapped.{task_type.lower()}")
        parameters = {
            "action": task.get("action"), "object": task.get("object"),
            "required_inputs": task.get("required_inputs", []), "missing_inputs": task.get("missing_inputs", []),
            "values": numeric_values if capability == "rule.calculate" else [], "utterance": utterance,
            "original_task_type": task_type,
            "uploaded_documents": uploaded_documents,
        }
        platform_tasks.append({
            "task_id": task.get("task_id"), "description": task.get("task_description", utterance),
            "capability_code": capability, "dependencies": task.get("dependencies", []),
            "parameters": parameters, "confidence": task.get("confidence", original.get("overall_confidence", .8)),
        })
    if not platform_tasks and uploaded_documents and _looks_like_uploaded_reconciliation(utterance):
        platform_tasks.append({
            "task_id": "uploaded-document-reconciliation-1",
            "description": utterance,
            "capability_code": "data.aggregate",
            "dependencies": [],
            "parameters": {
                "action": "reconcile_uploaded_documents",
                "object": "sales_reconciliation",
                "scenario_id": "architecture-v3.9-case2-sales-reconciliation",
                "execution_kind": "uploaded_document_sales_reconciliation",
                "required_inputs": ["uploaded_documents"],
                "missing_inputs": [],
                "values": [],
                "utterance": utterance,
                "original_task_type": "UPLOADED_DOCUMENT_RECONCILIATION",
                "uploaded_documents": uploaded_documents,
            },
            "confidence": original.get("overall_confidence", .78),
        })
    if not platform_tasks:
        model_output = meta.get("model_output") or {}
        capability = CAPABILITY_ALIASES.get(str(model_output.get("capability_code") or "").strip(), str(model_output.get("capability_code") or "").strip())
        if capability:
            model_parameters = model_output.get("parameters") if isinstance(model_output.get("parameters"), dict) else {}
            platform_tasks.append({
                "task_id": "model-output-adapted-1",
                "description": model_output.get("description") or utterance,
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
    data = {
        "tasks": platform_tasks,
        "clarification_required": bool(original.get("clarification_required", False)),
        "required_inputs": original.get("clarification_questions", []),
        "intent_confirmation_required": True,
        "model_call": {"model_call_id": meta.get("model_call_id"), "provider": meta.get("provider"), "model": meta.get("model"), "fallback_used": meta.get("fallback_used", False)},
        "intent_engine": {"source": meta.get("source"), "component": meta.get("component"), "original_analysis_level": original.get("analysis_level"), "validation": delivered.get("validation")},
        "uploaded_documents": uploaded_documents,
    }
    handler.send(200, standard_response(envelope, "success", data=data))


def _looks_like_uploaded_reconciliation(text: str) -> bool:
    return any(word in text for word in ("对账", "核对", "销售对账", "案例二", "合同登记", "发票一致"))
