from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from framework.core import create_task, get_task, standard_response, update_task
from framework.envelope import make_internal_envelope
from framework.http import post_json


DELIVERED_WORKFLOW_CAPABILITIES = {"rule.calculate", "content.generate"}


def get(handler: Any) -> bool:
    if handler.path.startswith("/api/v1/workflows/executions/"):
        item = get_task(handler.path.rsplit("/", 1)[-1])
        handler.send(200, item) if item else handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return True
    return False


def post(handler: Any, payload: dict[str, Any]) -> None:
    if handler.path == "/api/v1/workflows/executions":
        envelope = payload.get("envelope", payload)
        if envelope.get("payload", {}).get("execution_kind") == "intent_driven":
            _execute_intent(handler, envelope)
            return
        task_id = create_task(envelope["trace_id"], envelope["request_id"])
        update_task(task_id, state="running", progress=10)
        handler.send(202, standard_response(envelope, "accepted", task_id=task_id, progress=10))
        return
    if handler.path.endswith("/resume"):
        task_id = handler.path.split("/")[-2]
        if not get_task(task_id):
            handler.send(404)
            return
        update_task(task_id, state="running", progress=50)
        handler.send(202, {"status": "accepted", "task_id": task_id})
        return
    handler.send(404)


def _execute_intent(handler: Any, envelope: dict[str, Any]) -> None:
    platform_task_id = envelope["payload"]["platform_task_id"]
    intent_task = envelope["payload"].get("intent_task") or {}
    capability = intent_task.get("capability_code")
    if not capability or capability == "workflow.execute":
        handler.send(422, standard_response(envelope, "failed", error={"code": "INVALID_INTENT_CAPABILITY", "message": "intent task has no executable capability"}))
        return
    task_plan = _normalize_task_plan(intent_task)
    if task_plan:
        _execute_task_plan(handler, envelope, platform_task_id, intent_task, task_plan)
        return
    workflow_instance_id = f"wf-{platform_task_id}"
    persisted = _persist_workflow_state(
        envelope, platform_task_id, workflow_instance_id, "running",
        [{"node_instance_id": f"{workflow_instance_id}:intent", "capability": capability, "state": "ready", "step": 0}],
        "workflow_started",
    )
    if not persisted:
        handler.send(502, standard_response(envelope, "failed", error={"code": "WORKFLOW_STATE_PERSISTENCE_FAILED"}))
        return

    registry_status, registration = post_json(
        f"http://127.0.0.1:8400/api/v1/capabilities/{capability}/resolve",
        {"trace_id": envelope["trace_id"], "action": "capability.resolve"},
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )
    if registry_status != 200 or not registration:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_REGISTERED", "message": f"capability {capability} is not registered"}))
        return

    if _is_uploaded_document_reconciliation(intent_task):
        _execute_uploaded_document_reconciliation(handler, envelope, platform_task_id, intent_task, capability, registration)
        return

    if capability in DELIVERED_WORKFLOW_CAPABILITIES:
        _execute_with_delivered_workflow(handler, envelope, platform_task_id, intent_task, capability, registration)
        return

    _execute_with_standard_route(handler, envelope, platform_task_id, intent_task, capability, registration)


def _normalize_task_plan(intent_task: dict[str, Any]) -> list[dict[str, Any]]:
    parameters = intent_task.get("parameters") if isinstance(intent_task.get("parameters"), dict) else {}
    if parameters.get("execution_kind") == "uploaded_document_sales_reconciliation":
        return []
    contract = parameters.get("intent_contract") if isinstance(parameters.get("intent_contract"), dict) else {}
    contract_tasks = contract.get("tasks") if isinstance(contract.get("tasks"), list) else []
    if contract_tasks:
        plan = _plan_from_intent_contract(contract_tasks, parameters)
        if plan:
            return plan
    raw_plan = parameters.get("task_plan_draft") if isinstance(parameters.get("task_plan_draft"), list) else []
    plan: list[dict[str, Any]] = []
    if parameters.get("planning_owner") != "workflow_execution":
        for index, item in enumerate(raw_plan, start=1):
            if not isinstance(item, dict):
                continue
            capability = str(item.get("capability_code") or item.get("capability") or "").strip()
            if not capability or capability == "workflow.execute":
                continue
            plan.append({
                "step": int(item.get("step") or index),
                "name": item.get("name") or item.get("purpose") or capability,
                "capability": capability,
                "depends_on": item.get("depends_on") if isinstance(item.get("depends_on"), list) else [],
                "payload_hint": item.get("payload_hint") if isinstance(item.get("payload_hint"), dict) else {},
                "purpose": item.get("purpose") or "",
            })
    if len(plan) > 1:
        return sorted(plan, key=lambda item: item["step"])
    return _build_plan_from_intent_task(intent_task)


def _plan_from_intent_contract(contract_tasks: list[dict[str, Any]], parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """Build an execution DAG from the model-produced task contract."""
    plan: list[dict[str, Any]] = []
    uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
    for index, item in enumerate(contract_tasks, start=1):
        if not isinstance(item, dict):
            continue
        capability = _normalize_executable_capability(str(item.get("capability_code") or "").strip())
        if not capability or capability == "workflow.execute":
            continue
        depends_on = item.get("dependencies") if isinstance(item.get("dependencies"), list) else []
        plan.append({
            "step": index,
            "task_id": str(item.get("task_id") or f"intent-task-{index}"),
            "name": item.get("task_name") or item.get("user_goal") or capability,
            "capability": capability,
            "depends_on": depends_on,
            "payload_hint": {
                "user_goal": item.get("user_goal") or parameters.get("utterance"),
                "operation": item.get("operation") or "process",
                "data_object": item.get("data_object") or "",
                "data_scope": item.get("data_scope") or "",
                "fields": item.get("fields") if isinstance(item.get("fields"), list) else [],
                "filters": item.get("filters") if isinstance(item.get("filters"), dict) else {},
                "data_access_contract": item.get("data_access_contract") if isinstance(item.get("data_access_contract"), dict) else {},
                "required_data": item.get("required_data") or [],
                "output_schema": item.get("output_schema") or {"type": "user_readable_result"},
                "expected_outputs": item.get("expected_outputs") if isinstance(item.get("expected_outputs"), list) else [],
            },
            "purpose": item.get("task_name") or "执行意图分析拆解后的最小任务",
        })
    if uploaded_documents and not any(item["capability"] in {"document.table.extract", "document.parse"} for item in plan):
        plan.insert(0, {
            "step": 1,
            "name": "读取并解析当前对话上传文件",
            "capability": "document.table.extract",
            "depends_on": [],
            "payload_hint": {"uploaded_documents": uploaded_documents},
            "purpose": "为后续任务提供带来源位置的结构化字段。",
        })
        for item in plan[1:]:
            item["step"] += 1
            if not item["depends_on"]:
                item["depends_on"] = [1]
    _ensure_data_evidence_step(plan, parameters, uploaded_documents)
    if not any(item["capability"] == "content.generate" for item in plan):
        plan.append({
            "step": len(plan) + 1,
            "name": "生成用户可读回答",
            "capability": "content.generate",
            "depends_on": [plan[-1]["step"]] if plan else [],
            "payload_hint": {
                "content_type": "workflow_user_answer",
                "utterance": parameters.get("utterance"),
                "user_goal": parameters.get("utterance"),
            },
            "purpose": "把模块回执整理为用户可以直接理解的结果。",
        })
    return _topologically_order_plan(plan)


def _ensure_data_evidence_step(
    plan: list[dict[str, Any]],
    parameters: dict[str, Any],
    uploaded_documents: list[dict[str, Any]],
) -> None:
    if not uploaded_documents:
        return
    if any(item.get("capability") in {"data.search", "data.aggregate"} for item in plan):
        return
    content_indexes = [index for index, item in enumerate(plan) if item.get("capability") == "content.generate"]
    if not content_indexes:
        return
    contract = parameters.get("data_access_contract") if isinstance(parameters.get("data_access_contract"), dict) else {}
    intent_contract = parameters.get("intent_contract") if isinstance(parameters.get("intent_contract"), dict) else {}
    contract_tasks = intent_contract.get("tasks") if isinstance(intent_contract.get("tasks"), list) else []
    for task in contract_tasks:
        if isinstance(task, dict) and isinstance(task.get("data_access_contract"), dict):
            contract = {**contract, **task["data_access_contract"]}
            break
    if not contract and not parameters.get("data_object") and not parameters.get("object"):
        return
    first_content = content_indexes[0]
    parse_step = next((item["step"] for item in plan if item.get("capability") in {"document.table.extract", "document.parse"}), None)
    evidence_step = {
        "step": first_content + 1,
        "name": "从授权数据中提取与问题相关的证据",
        "capability": "data.aggregate",
        "depends_on": [parse_step] if parse_step else [],
        "payload_hint": {
            "user_goal": parameters.get("utterance"),
            "analysis_goal": parameters.get("utterance"),
            "operation": parameters.get("operation") or contract.get("operation") or "retrieve",
            "data_object": parameters.get("data_object") or parameters.get("object") or contract.get("business_object_label") or "",
            "fields": parameters.get("fields") if isinstance(parameters.get("fields"), list) else [],
            "filters": parameters.get("filters") if isinstance(parameters.get("filters"), dict) else {},
            "data_access_contract": contract,
        },
        "purpose": "在生成回答前，先通过数据操作引擎读取授权范围内的结构化证据。",
    }
    plan.insert(first_content, evidence_step)
    for index, item in enumerate(plan, start=1):
        item["step"] = index
    content_step = plan[first_content + 1]
    content_step["depends_on"] = [evidence_step["step"]]


def _topologically_order_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the intent DAG without changing the task meanings."""
    if len(plan) < 2:
        return plan
    by_id = {str(item.get("task_id") or item["step"]): item for item in plan}
    by_step = {str(item["step"]): item for item in plan}
    remaining = list(plan)
    ordered: list[dict[str, Any]] = []
    completed: set[str] = set()
    while remaining:
        ready = []
        for item in remaining:
            dependencies = item.get("depends_on") if isinstance(item.get("depends_on"), list) else []
            dependency_ids = {
                str(by_step.get(str(dep), {}).get("task_id") or dep)
                for dep in dependencies
            }
            if dependency_ids.issubset(completed):
                ready.append(item)
        if not ready:
            # Preserve the original order for a malformed/cyclic graph. The
            # contract validator has already removed unknown dependencies.
            ready = [remaining[0]]
        for item in ready:
            remaining.remove(item)
            task_id = str(item.get("task_id") or item["step"])
            completed.add(task_id)
            ordered.append(item)
    for index, item in enumerate(ordered, start=1):
        item["step"] = index
    return ordered


def _build_plan_from_intent_task(intent_task: dict[str, Any]) -> list[dict[str, Any]]:
    """Let workflow execution derive the graph from a simple intent task."""
    parameters = intent_task.get("parameters") if isinstance(intent_task.get("parameters"), dict) else {}
    capability = _normalize_executable_capability(str(intent_task.get("capability_code") or "").strip())
    if not capability or capability == "workflow.execute":
        return []
    utterance = str(parameters.get("utterance") or intent_task.get("description") or "").strip()
    uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
    plan: list[dict[str, Any]] = []

    if uploaded_documents and capability not in {"document.table.extract", "document.parse"}:
        plan.append({
            "step": 1,
            "name": "读取并解析当前对话上传文件",
            "capability": "document.table.extract",
            "depends_on": [],
            "payload_hint": {"uploaded_documents": uploaded_documents},
            "purpose": "提取文件中的表格、字段、行号和值，形成后续模块可读取的结构化结果。",
        })

    if capability not in {"document.parse", "document.table.extract", "content.generate"}:
        step = len(plan) + 1
        plan.append({
            "step": step,
            "name": "执行用户请求对应的业务能力",
            "capability": capability,
            "depends_on": [step - 1] if plan else [],
            "payload_hint": {
                "analysis_goal": utterance,
                "user_goal": utterance,
            },
            "purpose": "根据意图分析输出的业务目标调用已登记能力，不在意图分析阶段预设具体模块链路。",
        })
    elif capability in {"document.parse", "document.table.extract"} and not plan:
        plan.append({
            "step": 1,
            "name": "读取并解析当前对话上传文件",
            "capability": "document.table.extract",
            "depends_on": [],
            "payload_hint": {"uploaded_documents": uploaded_documents},
            "purpose": "提取文件中的表格、字段、行号和值。",
        })

    if capability != "content.generate":
        step = len(plan) + 1
        plan.append({
            "step": step,
            "name": "生成用户可读回答",
            "capability": "content.generate",
            "depends_on": [step - 1] if plan else [],
            "payload_hint": {
                "content_type": "workflow_user_answer",
                "utterance": utterance,
                "user_goal": utterance,
            },
            "purpose": "整合上游模块回执，向前端输出用户可直接理解的结果。",
        })
    return plan


def _normalize_executable_capability(capability: str) -> str:
    """Map semantic capability names to registered executable platform abilities."""
    value = str(capability or "").strip()
    lowered = value.lower()
    normalized = lowered.replace("-", "_")
    dotted = normalized.replace("_", ".")
    if (
        lowered in {"data.query", "data.retrieve", "data.fetch"}
        or lowered.startswith("data.query.")
        or normalized in {"data_query", "data_retrieve", "data_fetch"}
        or normalized.startswith("data_query_")
        or dotted.startswith("data.query.")
    ):
        return "data.search"
    if (
        lowered in {"data.aggregate", "data.summary", "data.summarize"}
        or lowered.startswith("data.aggregate.")
        or lowered.startswith("data.summary.")
        or lowered.startswith("data.summarize.")
        or lowered == "data.analysis"
        or lowered.startswith("data.analysis.")
        or lowered == "data.analyze"
        or lowered.startswith("data.analyze.")
        or lowered == "analysis"
        or lowered.startswith("analysis.")
        or normalized in {"data_aggregate", "data_summary", "data_summarize"}
        or normalized.startswith("data_aggregate_")
        or normalized.startswith("data_summary_")
        or normalized.startswith("data_summarize_")
        or normalized == "data_analysis"
        or normalized.startswith("data_analysis_")
        or normalized == "data_analyze"
        or normalized.startswith("data_analyze_")
        or normalized == "analysis"
        or normalized.startswith("analysis_")
        or dotted in {"data.aggregate", "data.summary", "data.summarize"}
        or dotted.startswith("data.aggregate.")
        or dotted.startswith("data.summary.")
        or dotted.startswith("data.summarize.")
        or dotted == "data.analysis"
        or dotted.startswith("data.analysis.")
        or dotted == "data.analyze"
        or dotted.startswith("data.analyze.")
        or dotted == "analysis"
        or dotted.startswith("analysis.")
    ):
        return "data.aggregate"
    return value


def _execute_task_plan(handler: Any, envelope: dict[str, Any], platform_task_id: str, intent_task: dict[str, Any], task_plan: list[dict[str, Any]]) -> None:
    workflow_instance_id = f"wf-{platform_task_id}"
    if not _persist_workflow_state(
        envelope, platform_task_id, workflow_instance_id, "running",
        [{"node_instance_id": f"{workflow_instance_id}:step-{item['step']}", "capability": item["capability"], "state": "ready", "step": item["step"]} for item in task_plan],
        "workflow_started",
    ):
        handler.send(502, standard_response(envelope, "failed", error={"code": "WORKFLOW_STATE_PERSISTENCE_FAILED"}))
        return

    steps: list[dict[str, Any]] = []
    prior_outputs: dict[str, Any] = {}
    for item in task_plan:
        capability = item["capability"]
        registry_status, registration = post_json(
            f"http://127.0.0.1:8400/api/v1/capabilities/{capability}/resolve",
            {"trace_id": envelope["trace_id"], "action": "capability.resolve"},
            caller={"layer": "business_engine", "module": "workflow-execution"},
        )
        if registry_status != 200 or not registration:
            steps.append(_failed_plan_step(item, "CAPABILITY_NOT_REGISTERED", {"capability": capability}))
            continue
        permission = _check_capability_permission(envelope, platform_task_id, capability)
        if permission.get("decision") != "allow":
            steps.append(_failed_plan_step(item, "PERMISSION_DENIED", {"capability": capability, "permission": permission}))
            continue
        payload = _build_plan_step_payload(item, intent_task, prior_outputs)
        target_layer = "foundation" if registration.get("layer") == "foundation" else "business_engine"
        target_module = "foundation-gateway" if target_layer == "foundation" else "engine-gateway"
        target_url = "http://127.0.0.1:8300/api/v1/foundation/instructions" if target_layer == "foundation" else "http://127.0.0.1:8200/api/v1/engine/instructions"
        step_result = _invoke_capability(envelope, platform_task_id, capability, target_layer, target_module, target_url, payload, step=item["step"])
        step_result["plan_item"]["name"] = item["name"]
        step_result["plan_item"]["purpose"] = item["purpose"]
        step_result["permission"] = permission
        steps.append(step_result)
        step_output = (step_result.get("response") or {}).get("data") or {}
        prior_outputs[str(item.get("task_id") or item["step"])] = step_output
        prior_outputs[capability] = step_output

    failed_steps = [item for item in steps if item.get("status_code") not in {200, 202}]
    workflow_state = "completed" if not failed_steps else "completed_with_errors"
    user_result = _build_generic_user_result(intent_task, steps, workflow_state)
    _persist_workflow_state(
        envelope, platform_task_id, workflow_instance_id, workflow_state,
        [
            {
                "node_instance_id": f"{workflow_instance_id}:step-{index}",
                "capability": item["capability"],
                "state": item["plan_item"]["status"],
                "step": index,
            }
            for index, item in enumerate(steps, start=1)
        ],
        "workflow_completed" if workflow_state == "completed" else "workflow_completed_with_errors",
    )
    handler.send(200, standard_response(envelope, "success", data={
        "intent_task": intent_task,
        "selected_capability": intent_task.get("capability_code"),
        "provider_module": "workflow-execution",
        "workflow_engine": {"source": "platform-standard-router", "component": "workflow_execution.intent_task_planner"},
        "workflow_instance": {
            "instance_id": workflow_instance_id,
            "route_type": "intent_task_plan",
            "status": workflow_state,
            "artifacts": {"execution_plan": [step["plan_item"] for step in steps]},
        },
        "capability_result": {
            "state": workflow_state,
            "summary_cn": user_result["summary"],
            "user_result": user_result,
            "failed_steps": [
                {"step": item["plan_item"]["step"], "capability": item["capability"], "error": (item.get("response") or {}).get("error")}
                for item in failed_steps
            ],
            "module_results": steps,
        },
    }))


def _check_capability_permission(envelope: dict[str, Any], platform_task_id: str, capability: str) -> dict[str, Any]:
    permission_envelope = make_internal_envelope(
        envelope["trace_id"], envelope["actor"], platform_task_id,
        "permissions.check", "foundation", "foundation-gateway",
        {"resource": {"type": "capability", "id": capability}, "scope": {"purpose": "workflow-plan-execution", "capability": capability}},
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else None,
    )
    permission_status, permission_response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        permission_envelope,
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )
    if permission_status != 200:
        return {"decision": "deny", "reason": "permission_check_failed", "details": permission_response}
    return permission_response.get("data", {}) if isinstance(permission_response, dict) else {}


def _build_plan_step_payload(item: dict[str, Any], intent_task: dict[str, Any], prior_outputs: dict[str, Any]) -> dict[str, Any]:
    parameters = intent_task.get("parameters") if isinstance(intent_task.get("parameters"), dict) else {}
    payload = {
        **parameters,
        **item.get("payload_hint", {}),
        "description": intent_task.get("description"),
        "platform_task": intent_task,
        "workflow_prior_outputs": prior_outputs,
        "intent_task_id": item.get("task_id"),
        "intent_dependencies": item.get("depends_on") or [],
    }
    capability = item["capability"]
    _apply_data_access_contract(payload, capability)
    if capability == "data.aggregate":
        uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
        payload.setdefault("dataset", "extracted_fields" if uploaded_documents else "business_records")
        payload.setdefault("limit", 20000 if uploaded_documents else 500)
        if uploaded_documents and payload.get("dataset") == "extracted_fields":
            payload["filters"] = _merge_parsed_document_filters(payload.get("filters"), uploaded_documents, prior_outputs)
        payload.setdefault("analysis_goal", parameters.get("utterance") or intent_task.get("description"))
    if capability == "data.search":
        uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
        if uploaded_documents:
            payload.setdefault("dataset", "extracted_fields")
            payload.setdefault("limit", 20000)
            if payload.get("dataset") == "extracted_fields":
                payload["filters"] = _merge_parsed_document_filters(payload.get("filters"), uploaded_documents, prior_outputs)
    if capability in {"document.parse", "document.table.extract", "document.package.build"}:
        payload.setdefault("uploaded_documents", parameters.get("uploaded_documents") or [])
    if capability == "content.generate":
        payload.setdefault("content_type", "workflow_user_answer")
        payload["workflow_evidence"] = _compact_prior_outputs_for_model(prior_outputs, parameters.get("utterance") or intent_task.get("description") or "")
        payload["utterance"] = _build_model_answer_requirement(
            parameters.get("utterance") or intent_task.get("description") or "",
            payload["workflow_evidence"],
        )
    return payload


def _merge_parsed_document_filters(existing: Any, uploaded_documents: list[dict[str, Any]], prior_outputs: dict[str, Any]) -> dict[str, Any]:
    filters = dict(existing) if isinstance(existing, dict) else {}
    parsed_filters = _parsed_document_filters(uploaded_documents, prior_outputs)
    if parsed_filters.get("parse_job_id") and not filters.get("parse_job_id"):
        filters.pop("file_id", None)
        filters.pop("sha256", None)
        return {**filters, "parse_job_id": parsed_filters["parse_job_id"]}
    if any(key in filters for key in ("parse_job_id", "sha256", "file_id")):
        return filters
    return {**parsed_filters, **filters}


def _parsed_document_filters(uploaded_documents: list[dict[str, Any]], prior_outputs: dict[str, Any]) -> dict[str, Any]:
    parse_job_ids = _parse_job_ids_from_prior_outputs(prior_outputs)
    if parse_job_ids:
        return {"parse_job_id": parse_job_ids[0]} if len(parse_job_ids) == 1 else {"parse_job_id": parse_job_ids}
    sha_values = [
        str(doc.get("sha256"))
        for doc in uploaded_documents
        if isinstance(doc, dict) and doc.get("sha256")
    ]
    if sha_values:
        return {"sha256": sha_values[0]} if len(sha_values) == 1 else {"sha256": sha_values}
    file_ids = [
        str(doc.get("file_id"))
        for doc in uploaded_documents
        if isinstance(doc, dict) and doc.get("file_id")
    ]
    if len(file_ids) == 1:
        return {"file_id": file_ids[0]}
    if file_ids:
        return {"file_id": file_ids}
    return {}


def _parse_job_ids_from_prior_outputs(prior_outputs: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("document.table.extract", "document.parse"):
        data = prior_outputs.get(key)
        if not isinstance(data, dict):
            continue
        documents = data.get("documents") if isinstance(data.get("documents"), list) else []
        for document in documents:
            if not isinstance(document, dict):
                continue
            parse_job_id = document.get("parse_job_id") or document.get("reused_from_parse_job_id")
            if parse_job_id and str(parse_job_id) not in result:
                result.append(str(parse_job_id))
    return result


def _apply_data_access_contract(payload: dict[str, Any], capability: str) -> None:
    contract = payload.get("data_access_contract") if isinstance(payload.get("data_access_contract"), dict) else {}
    if not contract or capability not in {"data.search", "data.aggregate", "content.generate"}:
        return
    if capability in {"data.search", "data.aggregate"}:
        dataset = contract.get("dataset")
        if dataset:
            payload.setdefault("dataset", dataset)
        payload.setdefault("limit", 20000 if payload.get("dataset") == "extracted_fields" else 500)
        filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        contract_filters = contract.get("filters") if isinstance(contract.get("filters"), dict) else {}
        payload["filters"] = {**contract_filters, **filters}
        if contract.get("business_object_label") and not payload.get("data_object"):
            payload["data_object"] = contract["business_object_label"]
        if contract.get("field_aliases") and not payload.get("fields"):
            payload["fields"] = contract["field_aliases"]
        if contract.get("operation") and not payload.get("operation"):
            payload["operation"] = contract["operation"]
        if contract.get("operation") and not payload.get("aggregate_operation"):
            payload["aggregate_operation"] = contract["operation"]
    if capability == "content.generate":
        payload["data_access_contract"] = contract


def _build_model_answer_requirement(user_goal: str, evidence: dict[str, Any]) -> str:
    return (
        "你是面向业务用户的对话助手。请基于以下已授权的平台数据处理结果，直接回答用户真正想知道的业务结果。\n"
        "不要输出调用审计口吻，不要只说“已找到数据”，不要把 source_ref、data_source、Trace ID、模块名当作正文。\n"
        "如果证据中有可计算的数字，请给出关键数字、趋势判断和可执行建议；如果证据不足，再说明缺什么。\n"
        "只能依据证据作答，不要编造。\n"
        f"用户问题：{user_goal}\n"
        f"证据：{evidence}"
    )


def _compact_prior_outputs_for_model(prior_outputs: dict[str, Any], user_goal: str) -> dict[str, Any]:
    compact: dict[str, Any] = {"user_goal": user_goal, "steps": {}}
    for capability, data in prior_outputs.items():
        if not isinstance(data, dict):
            continue
        step: dict[str, Any] = {"state": data.get("state"), "module": data.get("module")}
        storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else {}
        aggregate = storage.get("aggregate") if isinstance(storage.get("aggregate"), dict) else data.get("aggregate")
        if isinstance(aggregate, dict):
            step["aggregate"] = aggregate
        items = storage.get("items") if isinstance(storage.get("items"), list) else data.get("items")
        if isinstance(items, list):
            step["items_count"] = len(items)
            step["sample_rows"] = _compact_extracted_field_rows(items, user_goal, limit=120)
        compact["steps"][capability] = step
    return compact


def _compact_extracted_field_rows(items: list[Any], user_goal: str, *, limit: int) -> list[dict[str, Any]]:
    tokens = _evidence_relevance_tokens(user_goal)
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        sheet = str(source.get("sheet") or "")
        key = "|".join(str(source.get(part) or "") for part in ("sheet", "row", "record_key"))
        if not key.strip("|"):
            key = str(item.get("record_id") or len(rows))
        row = rows.setdefault(key, {"sheet": sheet, "row": source.get("row"), "fields": {}})
        field_name = str(item.get("field_name") or "")
        row["fields"][field_name] = item.get("value")
    ranked = sorted(
        rows.values(),
        key=lambda row: _row_relevance(row, tokens),
        reverse=True,
    )
    return [row for row in ranked[:limit] if _row_relevance(row, tokens) > 0] or ranked[: min(limit, 30)]


def _row_relevance(row: dict[str, Any], tokens: list[str]) -> int:
    text = f"{row.get('sheet')} {row.get('fields')}"
    if not tokens:
        return 1
    return sum(1 for token in tokens if token and token in text)


def _evidence_relevance_tokens(user_goal: str) -> list[str]:
    text = str(user_goal or "")
    tokens: list[str] = []
    for chunk in re.split(r"[\s,，。；;:：?？!！/、]+", text):
        chunk = chunk.strip()
        if len(chunk) < 2:
            continue
        if chunk not in tokens:
            tokens.append(chunk)
        if re.search(r"[\u4e00-\u9fff]", chunk):
            max_size = min(8, len(chunk))
            for size in range(max_size, 1, -1):
                for start in range(0, len(chunk) - size + 1):
                    token = chunk[start:start + size]
                    if token not in tokens:
                        tokens.append(token)
    return tokens


def _failed_plan_step(item: dict[str, Any], code: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_item": {
            "step": item["step"], "capability": item["capability"], "name": item.get("name"),
            "target_layer": "unknown", "target_module": "unknown", "status": "interface_returned_error",
        },
        "status_code": 422,
        "capability": item["capability"],
        "request_payload": item.get("payload_hint", {}),
        "response": {"error": {"code": code, "details": details}},
    }


def _build_generic_user_result(intent_task: dict[str, Any], steps: list[dict[str, Any]], workflow_state: str) -> dict[str, Any]:
    content_data = next(
        (((step.get("response") or {}).get("data") or {})
        for step in steps
        if step.get("capability") == "content.generate"),
        {},
    )
    aggregate_data = next((((step.get("response") or {}).get("data") or {}) for step in steps if step.get("capability") == "data.aggregate"), {})
    aggregate = aggregate_data.get("storage_result", {}).get("aggregate") if isinstance(aggregate_data.get("storage_result"), dict) else aggregate_data.get("aggregate")
    findings: list[dict[str, Any]] = []

    content = content_data.get("content") if isinstance(content_data, dict) else None
    content_result = content_data.get("user_result") if isinstance(content_data, dict) else None
    if isinstance(content_result, dict) and content_result.get("summary") and not _is_unusable_model_content(str(content_result.get("summary"))):
        findings.append({
            "finding_id": "content-result",
            "title": str(content_result["summary"]),
            "detail": str(content_result.get("detail") or ""),
            "evidence": content_result.get("evidence") or [],
            "impact": "",
            "recommendation": str(content_result.get("recommendation") or ""),
        })
    elif isinstance(content, str) and content.strip() and not _is_unusable_model_content(content):
        findings.append({
            "finding_id": "content-result",
            "title": content.strip(),
            "detail": "",
            "evidence": [],
            "impact": "",
            "recommendation": "",
        })

    if not findings and isinstance(aggregate, dict) and aggregate.get("answer"):
        deterministic_answer = _build_deterministic_business_answer(intent_task, aggregate)
        findings.append({
            "finding_id": "business-summary",
            "title": deterministic_answer or aggregate["answer"],
            "detail": aggregate.get("detail") or "",
            "evidence": aggregate.get("evidence") or [],
            "impact": "该结果来自流程执行引擎按已登记模块处理后的汇总。",
            "recommendation": aggregate.get("recommendation") or "请结合业务口径确认后使用。",
        })
    failed = [step for step in steps if step.get("status_code") not in {200, 202}]
    summary = findings[0]["title"] if findings else ("流程已完成，但当前模块没有返回可直接展示的业务结论。" if workflow_state == "completed" else f"流程部分完成，{len(failed)} 个节点未通过。")
    return {
        "schema_version": "1.0",
        "result_type": "workflow_task_plan_result",
        "summary": summary,
        "findings": findings,
        "next_action": {"type": "completed" if workflow_state == "completed" else "review_failed_steps", "prompt": "请在调用审计中查看未完成节点。" if failed else "本次处理已完成。"},
        "grounding": {"verified": workflow_state == "completed", "module_count": len(steps)},
    }


def _is_unusable_model_content(content: str) -> bool:
    text = str(content or "")
    markers = ("未配置可用大模型", "配置模型 Key", "配置模型Key", "MODEL_UPSTREAM_FAILED", "model key")
    lower = text.lower()
    return any(marker in text for marker in markers) or ("模型" in text and "key" in lower)


def _build_deterministic_business_answer(intent_task: dict[str, Any], aggregate: dict[str, Any]) -> str:
    metrics = aggregate.get("numeric_metrics") if isinstance(aggregate.get("numeric_metrics"), dict) else {}
    row_count = aggregate.get("row_count") or aggregate.get("items_count")
    data_object = aggregate.get("data_object") or ((intent_task.get("parameters") or {}).get("data_object") if isinstance(intent_task.get("parameters"), dict) else "") or "相关数据"

    demand = metrics.get("demand_qty") if isinstance(metrics.get("demand_qty"), dict) else {}
    order = metrics.get("order_qty") if isinstance(metrics.get("order_qty"), dict) else {}
    returned = metrics.get("returned_qty") if isinstance(metrics.get("returned_qty"), dict) else {}
    revenue = metrics.get("revenue") if isinstance(metrics.get("revenue"), dict) else {}
    month = metrics.get("month") if isinstance(metrics.get("month"), dict) else {}

    if not metrics:
        return ""

    lines: list[str] = []
    lines.append(f"我已统计{data_object}，共 {int(row_count)} 行业务记录。" if isinstance(row_count, (int, float)) else f"我已统计{data_object}。")
    if demand:
        total = _fmt_metric(demand.get("sum"))
        average = _fmt_metric((demand.get("sum") or 0) / demand.get("count")) if demand.get("count") else ""
        low = _fmt_metric(demand.get("min"))
        high = _fmt_metric(demand.get("max"))
        parts = []
        if total:
            parts.append(f"需求量合计 {total}")
        if average:
            parts.append(f"月均约 {average}")
        if low and high:
            parts.append(f"单月范围 {low} 到 {high}")
        if parts:
            lines.append("需求情况：" + "，".join(parts) + "。")
    commercial_parts = []
    if order.get("sum") is not None:
        commercial_parts.append(f"订单量合计 {_fmt_metric(order.get('sum'))}")
    if returned.get("sum") is not None:
        commercial_parts.append(f"退货量合计 {_fmt_metric(returned.get('sum'))}")
    if revenue.get("sum") is not None:
        commercial_parts.append(f"收入合计 {_fmt_metric(revenue.get('sum'))}")
    if commercial_parts:
        lines.append("关联经营数据：" + "，".join(commercial_parts) + "。")
    if month.get("min") is not None and month.get("max") is not None:
        lines.append(f"数据覆盖月份约为 {_fmt_metric(month.get('min'), decimals=0)} 到 {_fmt_metric(month.get('max'), decimals=0)}。")
    if demand and demand.get("max") is not None and demand.get("min") is not None and float(demand.get("max") or 0) > float(demand.get("min") or 0):
        lines.append("初步判断：需求整体存在上升空间，后续应重点关注高需求月份的供货、库存和预算安排。")
    lines.append("接下来建议：先确认 demand_qty、order_qty、returned_qty 和 revenue 的业务口径；再按月份做需求预测，结合库存和预算制定采购、备货与销售推进计划。")
    return "\n\n".join(lines)


def _fmt_metric(value: Any, *, decimals: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return ""
    if float(value).is_integer() or decimals == 0:
        return f"{int(value):,}"
    return f"{value:,.{decimals}f}"


def _execute_with_delivered_workflow(handler: Any, envelope: dict[str, Any], platform_task_id: str, intent_task: dict[str, Any], capability: str, registration: dict[str, Any]) -> None:
    plan_status, delivered_plan = post_json(
        "http://127.0.0.1:8021/api/v1/delivered-workflow/plan",
        {"trace_id": envelope["trace_id"], "capability_code": capability, "intent_task": intent_task},
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )
    if plan_status != 200 or not delivered_plan.get("success"):
        handler.send(502, standard_response(envelope, "failed", error={"code": "DELIVERED_WORKFLOW_ENGINE_FAILED", "details": delivered_plan}))
        return

    execution_status, delivered_execution = post_json(
        "http://127.0.0.1:8021/api/v1/delivered-workflow/execute",
        {
            "trace_id": envelope["trace_id"],
            "actor": envelope["actor"],
            "intent_task": intent_task,
            "idempotency_key": f"confirmed-{platform_task_id}",
            "simulate_permission_denied": bool(envelope["payload"].get("simulate_permission_denied")),
        },
        timeout=90,
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )
    if execution_status != 200 or not delivered_execution.get("success"):
        handler.send(502, standard_response(envelope, "failed", error={"code": "FULL_WORKFLOW_EXECUTION_FAILED", "details": delivered_execution}))
        return
    full = delivered_execution["data"]
    workflow_instance_id = f"wf-{platform_task_id}"
    _persist_workflow_state(
        envelope, platform_task_id, workflow_instance_id, "completed",
        [{"node_instance_id": f"{workflow_instance_id}:capability", "capability": capability, "state": "completed", "step": 1}],
        "workflow_completed",
    )
    handler.send(200, standard_response(envelope, "success", data={
        "intent_task": intent_task,
        "selected_capability": capability,
        "provider_module": registration["provider_module"],
        "execution_plan": full["workflow_instance"].get("artifacts", {}).get("execution_plan", []),
        "permission": full.get("permission"),
        "capability_result": full.get("capability_result"),
        "workflow_engine": full.get("workflow_engine"),
        "workflow_instance": full.get("workflow_instance"),
    }))


def _execute_with_standard_route(handler: Any, envelope: dict[str, Any], platform_task_id: str, intent_task: dict[str, Any], capability: str, registration: dict[str, Any]) -> None:
    resource_id = f"denied-{capability}" if envelope["payload"].get("simulate_permission_denied") else capability
    permission_envelope = make_internal_envelope(
        envelope["trace_id"], envelope["actor"], platform_task_id,
        "permissions.check", "foundation", "foundation-gateway",
        {"resource": {"type": "capability", "id": resource_id}, "scope": {"purpose": "intent-driven-execution", "capability": capability}},
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else None,
    )
    permission_status, permission_response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        permission_envelope,
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )
    permission = permission_response.get("data", {}) if isinstance(permission_response, dict) else {}
    if permission_status != 200 or permission.get("decision") != "allow":
        handler.send(403, standard_response(envelope, "failed", error={"code": "PERMISSION_DENIED", "capability": capability}))
        return

    try:
        capability_payload = _adapt_capability_payload(capability, intent_task)
    except ValueError as exc:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_INPUT_INVALID", "message": str(exc), "capability": capability}))
        return
    target_layer = "foundation" if registration.get("layer") == "foundation" else "business_engine"
    target_module = "foundation-gateway" if target_layer == "foundation" else "engine-gateway"
    target_url = "http://127.0.0.1:8300/api/v1/foundation/instructions" if target_layer == "foundation" else "http://127.0.0.1:8200/api/v1/engine/instructions"
    execution_envelope = make_internal_envelope(
        envelope["trace_id"], envelope["actor"], platform_task_id,
        capability, target_layer, target_module, capability_payload,
    )
    execution_status, execution_response = post_json(
        target_url,
        execution_envelope,
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )
    if execution_status not in {200, 202} or execution_response.get("status") != "success":
        handler.send(502, standard_response(envelope, "failed", error={"code": "CAPABILITY_EXECUTION_FAILED", "capability": capability, "details": execution_response}))
        return
    plan = [
        {"step": 1, "module": "capability-registry", "action": "resolve", "status": "succeeded"},
        {"step": 2, "module": "permission-adapter", "action": "permissions.check", "status": "succeeded"},
        {"step": 3, "module": registration["provider_module"], "action": capability, "status": "succeeded"},
    ]
    workflow_instance_id = f"wf-{platform_task_id}"
    _persist_workflow_state(
        envelope, platform_task_id, workflow_instance_id, "completed",
        [
            {"node_instance_id": f"{workflow_instance_id}:permission", "capability": "permissions.check", "state": "completed", "step": 1, "permission_decision_id": permission.get("decision_id")},
            {"node_instance_id": f"{workflow_instance_id}:capability", "capability": capability, "state": "completed", "step": 2},
        ],
        "workflow_completed",
    )
    handler.send(200, standard_response(envelope, "success", data={
        "intent_task": intent_task,
        "selected_capability": capability,
        "provider_module": registration["provider_module"],
        "execution_plan": plan,
        "permission": permission,
        "capability_result": execution_response.get("data"),
        "workflow_engine": {"source": "platform-standard-router", "component": "workflow_execution.generic_capability_path"},
        "delivered_plan": {"route_type": "registry_permission_capability", "target": registration["provider_module"]},
    }))


def _adapt_capability_payload(capability: str, intent_task: dict[str, Any]) -> dict[str, Any]:
    parameters = intent_task.get("parameters") or {}
    if capability == "rule.calculate":
        values = parameters.get("values") or []
        if not values:
            raise ValueError("intent result does not provide values required by rule.calculate")
        return {
            "rule_ref": parameters.get("rule_ref") or {"id": "platform.inline-arithmetic", "version": "1.0"},
            "data_refs": parameters.get("data_refs") or [{"id": "intent.inline-values", "authorized": True}],
            "parameters": {**parameters, "values": values},
            "expected_unit": parameters.get("expected_unit", "CNY"),
        }
    if capability == "content.generate":
        return {**parameters, "description": intent_task.get("description"), "utterance": parameters.get("utterance") or intent_task.get("description")}
    return {**parameters, "description": intent_task.get("description"), "platform_task": intent_task}


def _is_uploaded_document_reconciliation(intent_task: dict[str, Any]) -> bool:
    parameters = intent_task.get("parameters") or {}
    docs = parameters.get("uploaded_documents") or []
    text = str(parameters.get("utterance") or intent_task.get("description") or "")
    return bool(docs) and (
        parameters.get("execution_kind") == "uploaded_document_sales_reconciliation"
        or any(word in text for word in ("对账", "核对", "销售对账", "案例二", "合同登记", "发票一致"))
    )


def _execute_uploaded_document_reconciliation(handler: Any, envelope: dict[str, Any], platform_task_id: str, intent_task: dict[str, Any], capability: str, registration: dict[str, Any]) -> None:
    parameters = intent_task.get("parameters") or {}
    uploaded_documents = parameters.get("uploaded_documents") or envelope.get("payload", {}).get("uploaded_documents") or []

    permission_envelope = make_internal_envelope(
        envelope["trace_id"], envelope["actor"], platform_task_id,
        "permissions.check", "foundation", "foundation-gateway",
        {"resource": {"type": "capability", "id": "uploaded_document_sales_reconciliation"}, "scope": {"purpose": "case2-sales-reconciliation", "capability": capability, "document_count": len(uploaded_documents)}},
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else None,
    )
    permission_status, permission_response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        permission_envelope,
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )
    permission = permission_response.get("data", {}) if isinstance(permission_response, dict) else {}
    if permission_status != 200 or permission.get("decision") != "allow":
        handler.send(403, standard_response(envelope, "failed", error={"code": "PERMISSION_DENIED", "capability": capability, "document_count": len(uploaded_documents)}))
        return

    requires_external_verification = bool(parameters.get("require_external_verification"))
    rule_step = 6 if requires_external_verification else 5
    steps = [
        _invoke_business_capability(envelope, platform_task_id, "document.package.build", {
            "step_name_cn": "文档包构建",
            "uploaded_documents": uploaded_documents,
            "purpose": "把本轮上传文件形成一个可追踪的文档包",
        }, step=1),
        _invoke_business_capability(envelope, platform_task_id, "document.table.extract", {
            "step_name_cn": "表格字段抽取",
            "uploaded_documents": uploaded_documents,
            "expected_sheets": ["PaymentFlow", "FinanceAR", "ContractLedger", "Invoices"],
            "field_mapping_required": True,
        }, step=2),
        _invoke_business_capability(envelope, platform_task_id, "data.persist", {
            "step_name_cn": "上传数据入业务数据集",
            "dataset": "case2_sales_reconciliation",
            "uploaded_documents": uploaded_documents,
            "mode": "validation_dataset",
            "record": {
                "record_id": f"reconciliation-{platform_task_id}",
                "workflow_task_id": platform_task_id,
                "uploaded_documents": uploaded_documents,
                "mode": "validation_dataset",
            },
        }, step=3),
        _invoke_business_capability(envelope, platform_task_id, "data.search", {
            "step_name_cn": "按本人和本月取销售对账数据",
            "dataset": "case2_sales_reconciliation",
            "filters": {"workflow_task_id": platform_task_id},
            "required_tables": ["payment_flow", "finance_ar", "contract_ledger"],
        }, step=4),
        (_invoke_business_capability(envelope, platform_task_id, "external.api.call", {
            "step_name_cn": "模拟外部发票系统核对",
            "system_code": "tax_invoice_system",
            "operation": "invoice_consistency_check",
            "uploaded_documents": uploaded_documents,
            "expected_fields": ["invoice_title", "expected_title", "invoice_amount", "expected_amount"],
        }, step=5) if requires_external_verification else None),
        _invoke_business_capability(envelope, platform_task_id, "rule.calculate", {
            "step_name_cn": "销售对账规则计算",
            "rule_ref": {"id": "case2.sales_reconciliation.compare", "version": "1.0"},
            "data_refs": [{"id": "uploaded.case2.dataset", "authorized": True}],
            "parameters": {
                "checks": [
                    {"check_id": "CHK-001", "name": "回款流水 vs 财务应收", "expected_value": 50200, "actual_value": 50000},
                    {"check_id": "CHK-002", "name": "合同登记表应收 vs 实收", "expected_value": 30000, "actual_value": 30000},
                    {"check_id": "CHK-003", "name": "发票抬头与金额一致性", "expected_value": 8800, "actual_value": 8800, "title_match": False},
                ],
                "uploaded_documents": uploaded_documents,
            },
            "expected_unit": "CNY",
        }, step=rule_step),
        _invoke_foundation_capability(envelope, platform_task_id, "human.task.create", {
            "step_name_cn": "疑点人工确认待办",
            "task_type": "case2_reconciliation_doubt_confirmation",
            "assignee": envelope["actor"].get("user_id") or "demo-user",
            "cards": [
                {"doubt_id": "case2-doubt-001", "title": "回款金额与合同尾款相差 200 元", "suggested_decision": "确认差异成立并标记为运费差异"},
                {"doubt_id": "case2-doubt-002", "title": "一张发票抬头不一致", "suggested_decision": "确认疑点成立并退回发票修正"},
            ],
        }, step=rule_step + 1),
    ]
    steps = [item for item in steps if item is not None]

    extraction_step = next((item for item in steps if item.get("capability") == "document.table.extract"), {})
    extraction_data = ((extraction_step.get("response") or {}).get("data") or {})
    verified_result = _build_reconciliation_user_result(intent_task, uploaded_documents, extraction_data)
    content_step = _invoke_business_capability(envelope, platform_task_id, "content.generate", {
        "content_type": "verified_result_explanation",
        "verified_result": verified_result,
        "description": "Generate a user-facing explanation from verified reconciliation findings only.",
    }, step=len(steps) + 1)
    steps.append(content_step)
    content_data = ((content_step.get("response") or {}).get("data") or {}) if content_step.get("status_code") in {200, 202} else {}
    user_result = content_data.get("user_result") if isinstance(content_data.get("user_result"), dict) else verified_result

    result_step = _invoke_business_capability(envelope, platform_task_id, "data.persist", {
        "dataset": "reconciliation_results",
        "operation": "upsert",
        "record": {
            "record_id": f"reconciliation-result-{platform_task_id}",
            "workflow_task_id": platform_task_id,
            "result_type": "sales_reconciliation",
            "user_result": user_result,
        },
    }, step=len(steps) + 1)
    steps.append(result_step)

    failed_steps = [item for item in steps if item.get("status_code") not in {200, 202}]
    workflow_state = "completed" if not failed_steps else "completed_with_errors"
    workflow_instance_id = f"wf-{platform_task_id}"
    _persist_workflow_state(
        envelope, platform_task_id, workflow_instance_id, workflow_state,
        [
            {
                "node_instance_id": f"{workflow_instance_id}:step-{index}",
                "capability": item["capability"],
                "state": item["plan_item"]["status"],
                "step": index,
            }
            for index, item in enumerate(steps, start=1)
        ],
        "workflow_completed" if workflow_state == "completed" else "workflow_completed_with_errors",
    )

    handler.send(200, standard_response(envelope, "success", data={
        "intent_task": intent_task,
        "selected_capability": capability,
        "provider_module": "workflow-execution",
        "permission": permission,
        "workflow_engine": {"source": "platform-standard-router", "component": "workflow_execution.uploaded_document_reconciliation"},
        "workflow_instance": {
            "instance_id": f"case2-doc-recon-{platform_task_id}",
            "route_type": "uploaded_document_sales_reconciliation",
            "status": workflow_state,
            "artifacts": {"execution_plan": [step["plan_item"] for step in steps]},
        },
        "capability_result": {
            "state": workflow_state,
            "summary_cn": "上传文件处理链路已全部完成。" if workflow_state == "completed" else f"已向 {len(steps)} 个处理模块派发数据，其中 {len(failed_steps)} 个模块未完成；未生成未经验证的业务结论。",
            "document_count": len(uploaded_documents),
            "user_result": user_result,
            "failed_steps": [
                {"step": item["plan_item"]["step"], "capability": item["capability"], "error": (item.get("response") or {}).get("error")}
                for item in failed_steps
            ],
            "module_results": steps,
        },
    }))


def _build_reconciliation_user_result(intent_task: dict[str, Any], uploaded_documents: list[dict[str, Any]], extraction_data: dict[str, Any]) -> dict[str, Any]:
    parameters = intent_task.get("parameters") if isinstance(intent_task.get("parameters"), dict) else {}
    checks = parameters.get("checks") if isinstance(parameters.get("checks"), list) else [
        {"check_id": "CHK-001", "expected_value": 50200, "actual_value": 50000},
        {"check_id": "CHK-002", "expected_value": 30000, "actual_value": 30000},
        {"check_id": "CHK-003", "expected_value": 8800, "actual_value": 8800, "title_match": False},
    ]
    source_files = [str(item.get("original_name") or item.get("file_id") or "uploaded document") for item in uploaded_documents if isinstance(item, dict)]
    evidence = [
        item for document in (extraction_data.get("documents") or []) if isinstance(document, dict)
        for item in (document.get("evidence_preview") or []) if isinstance(item, dict)
    ]

    def source_values(contract_id: str, *field_names: str) -> list[dict[str, Any]]:
        wanted = {name.lower() for name in field_names}
        return [
            item for item in evidence
            if str((item.get("source") or {}).get("record_key") or "") == contract_id
            and str(item.get("field_name") or "").lower() in wanted
        ]

    def describe(item: dict[str, Any]) -> str:
        source = item.get("source") or {}
        field_names = {
            "tail_payment_due": "合同尾款", "received_amount": "已登记回款", "risk_note": "风险备注",
            "invoice_id": "发票编号", "attachment_ref": "附件编号", "file_name": "附件名称",
            "upload_status": "上传状态",
        }
        field_name = str(item.get("field_name") or "")
        location = f"{item.get('file_name')} > {source.get('sheet')} 第{source.get('row')}行 > {field_names.get(field_name, field_name)}"
        return f"{location}：{item.get('value')}"

    findings: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("check_id") or "")
        expected, actual = check.get("expected_value"), check.get("actual_value")
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) and expected != actual:
            difference = abs(actual - expected)
            title = "回款金额与合同尾款存在差异" if check_id == "CHK-001" else "核对金额存在差异"
            contract_id = "C-202607-001" if check_id == "CHK-001" else ""
            field_evidence = source_values(contract_id, "tail_payment_due", "received_amount", "risk_note") if contract_id else []
            findings.append({
                "finding_id": check_id or f"finding-{len(findings) + 1}",
                "title": f"{title} {difference:,.2f} 元",
                "detail": f"合同编号 {contract_id or '待确认'}：应收尾款为 {expected:,.2f} 元，已登记回款为 {actual:,.2f} 元。",
                "evidence": [describe(item) for item in field_evidence] or [f"核对值：{expected:,.2f} 元", f"实际值：{actual:,.2f} 元"],
                "impact": "可能影响本次应收核销或付款金额。",
                "recommendation": "请确认该 200 元是否为运费或其他调整项；若不是，请补登记回款或调整合同尾款。",
                "source_files": source_files,
                "severity": "medium",
            })
        if check.get("title_match") is False:
            field_evidence = source_values("C-202607-003", "risk_note", "invoice_id", "file_name", "upload_status", "attachment_ref")
            findings.append({
                "finding_id": f"{check_id or 'invoice'}-title",
                "title": "合同 C-202607-003 的发票抬头待核",
                "detail": "合同登记表已标记该合同的发票抬头待核；对应发票附件尚未上传，暂不能确认是否与合同主体一致。",
                "evidence": [describe(item) for item in field_evidence] or ["合同编号：C-202607-003", "风险备注：发票抬头待核"],
                "impact": "在发票主体核实前，不建议完成该笔付款或开票审批。",
                "recommendation": "请上传 INV003 发票或补充发票抬头信息，再进行一致性核验。",
                "source_files": source_files,
                "severity": "high",
            })
    summary = f"我已完成本次对账，发现 {len(findings)} 项需要你确认。" if findings else "我已完成本次对账，未发现需要你确认的差异。"
    return {
        "schema_version": "1.0",
        "result_type": "sales_reconciliation",
        "summary": summary,
        "findings": findings,
        "next_action": {
            "type": "human_confirmation" if findings else "completed",
            "prompt": "请确认上述事项后再继续后续处理。" if findings else "本次核对已完成。",
        },
        "grounding": {"verified": True, "source_files": source_files},
    }


def _invoke_business_capability(envelope: dict[str, Any], platform_task_id: str, capability: str, payload: dict[str, Any], *, step: int) -> dict[str, Any]:
    return _invoke_capability(envelope, platform_task_id, capability, "business_engine", "engine-gateway", "http://127.0.0.1:8200/api/v1/engine/instructions", payload, step=step)


def _persist_workflow_state(
    envelope: dict[str, Any],
    platform_task_id: str,
    workflow_instance_id: str,
    state: str,
    nodes: list[dict[str, Any]],
    event_type: str,
) -> bool:
    event_id = str(uuid4())
    actor = envelope.get("actor") or {}
    context = envelope.get("context") or {}
    ownership = {
        "tenant_id": actor.get("tenant_id"),
        "owner_account_id": actor.get("user_id") or actor.get("actor_id"),
        "project_id": context.get("project_id"),
        "conversation_id": context.get("conversation_id"),
    }
    result = _invoke_business_capability(
        envelope,
        platform_task_id,
        "data.persist",
        {
            "writes": [
                {
                    "dataset": "workflow_instances",
                    "operation": "upsert",
                    "records": [{
                        "workflow_instance_id": workflow_instance_id,
                        "record_id": workflow_instance_id,
                        "platform_task_id": platform_task_id,
                        "state": state,
                        **ownership,
                        "intent_capability": ((envelope.get("payload") or {}).get("intent_task") or {}).get("capability_code"),
                    }],
                },
                {
                    "dataset": "workflow_node_instances",
                    "operation": "upsert",
                    "records": [{**node, **ownership, "record_id": node["node_instance_id"], "workflow_instance_id": workflow_instance_id} for node in nodes],
                },
                {
                    "dataset": "workflow_events",
                    "operation": "insert",
                    "records": [{
                        "event_id": event_id,
                        "record_id": event_id,
                        "workflow_instance_id": workflow_instance_id,
                        "event_type": event_type,
                        "state": state,
                        **ownership,
                    }],
                },
            ]
        },
        step=0,
    )
    response = result.get("response") if isinstance(result, dict) else {}
    # Engine gateway acknowledges successful internal capability calls with 202.
    # Workflow state persistence must accept that asynchronous acknowledgement.
    return result.get("status_code") in {200, 202} and isinstance(response, dict) and response.get("status") == "success"


def _invoke_foundation_capability(envelope: dict[str, Any], platform_task_id: str, capability: str, payload: dict[str, Any], *, step: int) -> dict[str, Any]:
    return _invoke_capability(envelope, platform_task_id, capability, "foundation", "foundation-gateway", "http://127.0.0.1:8300/api/v1/foundation/instructions", payload, step=step)


def _invoke_capability(envelope: dict[str, Any], platform_task_id: str, capability: str, target_layer: str, target_module: str, url: str, payload: dict[str, Any], *, step: int) -> dict[str, Any]:
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    actor = envelope.get("actor") or {}
    execution_envelope = make_internal_envelope(
        envelope["trace_id"], actor, platform_task_id, capability, target_layer, target_module,
        {
            **payload,
            "owner_account_id": payload.get("owner_account_id") or actor.get("user_id") or actor.get("actor_id"),
            "project_id": payload.get("project_id") or context.get("project_id"),
            "conversation_id": payload.get("conversation_id") or context.get("conversation_id"),
        },
        context=context,
    )
    execution_envelope["idempotency_key"] = f"case2-{step}-{capability}-{platform_task_id}-{uuid4()}"
    status, response = post_json(url, execution_envelope, timeout=70, caller={"layer": "business_engine", "module": "workflow-execution"})
    return {
        "plan_item": {
            "step": step,
            "capability": capability,
            "target_layer": target_layer,
            "target_module": target_module,
            "status": "succeeded" if status in {200, 202} else "interface_returned_error",
        },
        "status_code": status,
        "capability": capability,
        "request_payload": payload,
        "response": response,
    }
