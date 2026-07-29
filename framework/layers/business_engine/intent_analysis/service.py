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
}

CAPABILITY_ALIASES = {
    "data.query": "data.search",
    "data.retrieve": "data.search",
    "data_query": "data.search",
    "data_retrieve": "data.search",
    "data.analysis": "data.aggregate",
    "data.analysis.problem": "data.aggregate",
    "data.analysis.summary": "data.aggregate",
    "data.analysis.aggregate": "data.aggregate",
    "data_analysis": "data.aggregate",
    "data_analysis.problem": "data.aggregate",
    "data_analysis_problem": "data.aggregate",
    "data-analysis": "data.aggregate",
    "data-analysis.problem": "data.aggregate",
    "knowledge.answer": "knowledge.qa.answer",
    "knowledge_qa.answer": "knowledge.qa.answer",
    "knowledge.answer.contextual": "knowledge.qa.contextual_answer",
}


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
        return "data.aggregate"
    if normalized in {"data_query", "data_retrieve"}:
        return "data.search"
    return CAPABILITY_ALIASES.get(value, value)


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
        "conversation_context": (
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
    status, delivered = post_json(
        "http://127.0.0.1:8003/api/v1/delivered-intent/analyze", request,
        timeout=55, caller={"layer": "business_engine", "module": "intent-adapter"},
    )
    if status != 200 or not delivered.get("success"):
        if _send_local_fallback(handler, envelope, utterance, uploaded_documents, "delivered_engine_failed"):
            return
        handler.send(502, standard_response(envelope, "failed", error={"code": "DELIVERED_INTENT_ENGINE_FAILED", "details": delivered, "retryable": True})); return

    original = delivered.get("data") or {}
    meta = delivered.get("engine_meta") or {}
    raw_model_output = meta.get("model_output") if isinstance(meta.get("model_output"), dict) else {}
    raw_result = raw_model_output.get("result") if isinstance(raw_model_output.get("result"), dict) else raw_model_output
    raw_tasks = raw_result.get("tasks") if isinstance(raw_result, dict) and isinstance(raw_result.get("tasks"), list) else []
    platform_tasks = []
    # Python treats Chinese characters as ``\w``. Guard only against adjacent
    # digits/decimal points so values such as "金额1200元" are not discarded.
    numeric_values = [float(value) for value in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", utterance)]
    for task_index, task in enumerate(original.get("tasks", [])):
        raw_task = raw_tasks[task_index] if task_index < len(raw_tasks) and isinstance(raw_tasks[task_index], dict) else {}
        task = {**raw_task, **task}
        task_type = task.get("task_type", "")
        model_capability = str(task.get("capability_code") or "").strip()
        capability = _normalize_capability_alias(
            model_capability or TASK_CAPABILITY_MAP.get(task_type, f"unmapped.{task_type.lower()}")
        )
        original_capability = capability
        if capability.startswith("unmapped."):
            capability = "data.aggregate" if _looks_like_data_backed_task(task, uploaded_documents) else "content.generate"
        parameters = {
            "action": task.get("action"), "object": task.get("object"),
            "required_inputs": task.get("required_inputs", []), "missing_inputs": task.get("missing_inputs", []),
            "values": numeric_values if capability == "rule.calculate" else [], "utterance": utterance,
            "original_task_type": task_type,
            "original_capability_code": original_capability,
            "fallback_reason": "capability_not_mapped" if original_capability.startswith("unmapped.") else None,
            "uploaded_documents": uploaded_documents,
            "data_object": task.get("data_object") or task.get("object") or "",
            "data_scope": task.get("data_scope") or "",
            "fields": task.get("fields") if isinstance(task.get("fields"), list) else [],
            "operation": task.get("operation") or "",
            "filters": task.get("filters") if isinstance(task.get("filters"), dict) else {},
            "output_schema": task.get("output_schema") if isinstance(task.get("output_schema"), dict) else {},
            "expected_outputs": task.get("expected_outputs") if isinstance(task.get("expected_outputs"), list) else [],
        }
        parameters = _normalize_parameters_for_context(utterance, capability, parameters, uploaded_documents)
        parameters["workflow_hints"] = _build_workflow_hints(utterance, capability, parameters, uploaded_documents)
        parameters["intent_summary"] = _build_intent_summary(utterance, capability, parameters, uploaded_documents)
        platform_tasks.append({
            "task_id": task.get("task_id"),
            "description": _normalize_task_description(task.get("task_description"), utterance, capability, parameters),
            "capability_code": capability, "dependencies": task.get("dependencies", []),
            "parameters": parameters, "confidence": task.get("confidence", original.get("overall_confidence", .8)),
        })
    platform_tasks = _build_intent_contract(platform_tasks, utterance, uploaded_documents)
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
        platform_tasks[-1]["parameters"]["workflow_hints"] = _build_workflow_hints(
            utterance, platform_tasks[-1]["capability_code"], platform_tasks[-1]["parameters"], uploaded_documents
        )
        platform_tasks[-1]["parameters"]["intent_summary"] = _build_intent_summary(
            utterance, platform_tasks[-1]["capability_code"], platform_tasks[-1]["parameters"], uploaded_documents
        )
    if not platform_tasks:
        model_output = meta.get("model_output") or {}
        capability = _normalize_capability_alias(str(model_output.get("capability_code") or "").strip())
        if capability:
            capability = _normalize_capability_for_context(utterance, capability, uploaded_documents)
            model_parameters = model_output.get("parameters") if isinstance(model_output.get("parameters"), dict) else {}
            model_parameters = _normalize_parameters_for_context(utterance, capability, model_parameters, uploaded_documents)
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
    if not platform_tasks and _send_local_fallback(
        handler, envelope, utterance, uploaded_documents, "model_returned_no_usable_task"
    ):
        return
    data = {
        "tasks": platform_tasks,
        "clarification_required": bool(original.get("clarification_required", False)) and any((task.get("parameters") or {}).get("missing_inputs") for task in platform_tasks),
        "required_inputs": original.get("clarification_questions", []) if any((task.get("parameters") or {}).get("missing_inputs") for task in platform_tasks) else [],
        "intent_confirmation_required": True,
        "model_call": {"model_call_id": meta.get("model_call_id"), "provider": meta.get("provider"), "model": meta.get("model"), "fallback_used": meta.get("fallback_used", False)},
        "intent_engine": {"source": meta.get("source"), "component": meta.get("component"), "original_analysis_level": original.get("analysis_level"), "validation": delivered.get("validation")},
        "uploaded_documents": uploaded_documents,
    }
    handler.send(200, standard_response(envelope, "success", data=data))


def _normalize_capability_for_context(utterance: str, capability: str, uploaded_documents: list[dict[str, Any]]) -> str:
    return capability


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


def _build_intent_contract(
    tasks: list[dict[str, Any]],
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize model output into a portable, execution-oriented task graph."""
    if not tasks:
        return tasks
    normalized: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        parameters = task.get("parameters") if isinstance(task.get("parameters"), dict) else {}
        capability = str(task.get("capability_code") or "content.generate").strip()
        description = _normalize_task_description(task.get("description"), utterance, capability, parameters)
        data_access_contract = _build_data_access_contract(utterance, capability, parameters, uploaded_documents)
        contract = {
            "task_id": str(task.get("task_id") or f"intent-task-{index}"),
            "task_name": description,
            "intent_type": str(parameters.get("original_task_type") or "USER_REQUEST"),
            "capability_code": capability,
            "data_object": parameters.get("data_object") or parameters.get("object") or "",
            "data_scope": parameters.get("data_scope") or (
                "conversation_uploads" if uploaded_documents else "authorized_project_data"
            ),
            "fields": parameters.get("fields") if isinstance(parameters.get("fields"), list) else [],
            "input_refs": parameters.get("input_refs") or [{"type": "conversation", "id": "current"}],
            "required_data": parameters.get("required_data") or (
                [{"type": "uploaded_documents", "count": len(uploaded_documents)}]
                if uploaded_documents else [{"type": "authorized_project_data"}]
            ),
            "operation": parameters.get("operation") or parameters.get("action") or "process",
            "filters": parameters.get("filters") if isinstance(parameters.get("filters"), dict) else {},
            "output_schema": parameters.get("output_schema") or {"type": "user_readable_result"},
            "expected_outputs": parameters.get("expected_outputs") if isinstance(parameters.get("expected_outputs"), list) else [],
            "dependencies": task.get("dependencies") if isinstance(task.get("dependencies"), list) else [],
            "user_goal": utterance,
            "data_access_contract": data_access_contract,
        }
        parameters = {
            **parameters,
            "utterance": utterance,
            "uploaded_documents": uploaded_documents,
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
    graph = {
        "schema_version": "1.0",
        "user_goal": utterance,
        "data_scope": "conversation_uploads" if uploaded_documents else "authorized_project_data",
        "tasks": [item["parameters"]["task_contract"] for item in normalized],
        "source": "intent_analysis",
    }
    normalized[0]["parameters"]["intent_contract"] = graph
    summary = _build_confirmation_summary_from_contract(graph, utterance, uploaded_documents)
    for item in normalized:
        item["parameters"]["intent_summary"] = summary
    return normalized


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


def _send_local_fallback(
    handler: Any,
    envelope: dict[str, Any],
    utterance: str,
    uploaded_documents: list[dict[str, Any]],
    reason: str,
) -> bool:
    """Use deterministic routing only after the delivered model cannot provide a usable task."""
    fallback_tasks = _quick_platform_tasks(utterance, uploaded_documents)
    if not fallback_tasks:
        parameters = {
            "action": "respond_to_user_request",
            "object": "user_business_request",
            "required_inputs": [],
            "missing_inputs": [],
            "values": [],
            "utterance": utterance,
            "original_task_type": "LOCAL_GENERIC_FALLBACK",
            "original_capability_code": "content.generate",
            "uploaded_documents": uploaded_documents,
            "fallback_reason": reason,
        }
        parameters["workflow_hints"] = _build_workflow_hints(
            utterance, "content.generate", parameters, uploaded_documents
        )
        parameters["intent_summary"] = _build_intent_summary(
            utterance, "content.generate", parameters, uploaded_documents
        )
        fallback_tasks = [{
            "task_id": "local-generic-fallback-1",
            "description": utterance,
            "capability_code": "content.generate",
            "dependencies": [],
            "parameters": parameters,
            "confidence": 0.3,
        }]
    for task in fallback_tasks:
        parameters = task.get("parameters")
        if isinstance(parameters, dict):
            parameters["fallback_reason"] = reason
    data = {
        "tasks": fallback_tasks,
        "clarification_required": False,
        "required_inputs": [],
        "intent_confirmation_required": True,
        "model_call": {
            "provider": "local-fallback",
            "model": "rule-intent-router",
            "fallback_used": True,
            "fallback_reason": reason,
        },
        "intent_engine": {
            "source": "platform-intent-adapter",
            "component": "local_fallback",
            "original_analysis_level": "business_intent_only",
        },
        "uploaded_documents": uploaded_documents,
    }
    handler.send(200, standard_response(envelope, "success", data=data))
    return True


def _looks_like_uploaded_reconciliation(text: str) -> bool:
    return any(word in text for word in ("对账", "核对", "销售对账", "案例二", "合同登记", "发票一致", "采购", "验收", "发票", "风险点"))


def _quick_platform_tasks(utterance: str, uploaded_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not uploaded_documents or not _looks_like_month_demand_summary(utterance):
        return []
    parameters = {
        "action": "aggregate",
        "object": _infer_business_goal(utterance, "data.aggregate"),
        "required_inputs": ["uploaded_documents"],
        "missing_inputs": [],
        "values": [],
        "utterance": utterance,
        "original_task_type": "LOCAL_FAST_MONTH_DEMAND_SUMMARY",
        "original_capability_code": "data.aggregate",
        "uploaded_documents": uploaded_documents,
    }
    parameters["workflow_hints"] = _build_workflow_hints(utterance, "data.aggregate", parameters, uploaded_documents)
    parameters["intent_summary"] = _build_intent_summary(utterance, "data.aggregate", parameters, uploaded_documents)
    return [{
        "task_id": "local-fast-month-demand-summary-1",
        "description": parameters["intent_summary"]["business_goal"],
        "capability_code": "data.aggregate",
        "dependencies": [],
        "parameters": parameters,
        "confidence": 0.9,
    }]


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
    needs_forecast = any(word in text for word in ("预测", "下季度", "需求区间", "趋势"))
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
    elif any(word in text for word in ("预测", "下季度", "需求区间", "趋势")):
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
    if any(word in utterance for word in ("预测", "下季度", "趋势")):
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
    list_words = ("哪些", "有哪些", "都有谁", "有谁", "所有", "全部", "确定", "列出", "列举", "名单", "清单", "明细", "去重", "一一", "分别", "几个", "多少个", "数量")
    return any(word in lowered for word in entity_words) and any(word in lowered for word in list_words)
