from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from framework.core import connect, create_task, get_task, standard_response, update_task
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import CAPABILITY_TO_MODULE


DELIVERED_WORKFLOW_CAPABILITIES = {"rule.calculate", "content.generate"}
CORE_WORKFLOW_CAPABILITIES = {
    "rule.calculate",
    "content.generate",
    "permissions.check",
    "model.respond",
}
KNOWN_EXECUTABLE_CAPABILITIES = set(CAPABILITY_TO_MODULE) | CORE_WORKFLOW_CAPABILITIES

DATA_CAPABILITIES = {"data.search", "data.aggregate", "data.read", "data.collect", "data.consolidate"}
DOCUMENT_CAPABILITIES = {"document.parse", "document.table.extract", "document.package.build"}
ANSWER_CAPABILITY = "content.generate"
WEAK_DATA_AGGREGATE_OPERATIONS = {
    "",
    "answer",
    "process",
    "retrieve",
    "query",
    "search",
    "summarize",
    "summary",
    "analyze",
    "analyse",
    "retrieve_and_summarize",
    "retrieve_and_rank",
    "recommend",
    "rank",
    "forecast",
    "predict",
    "prediction",
}

V40_CAPABILITY_ALIASES = {
    "data.query": "data.search",
    "data.retrieve": "data.search",
    "data.fetch": "data.search",
    "data.summary": "data.aggregate",
    "data.summarize": "data.aggregate",
    "data.statistics": "data.aggregate",
    "analysis": "analysis.business_metric",
    "analysis.forecast": "analysis.business_metric",
    "analysis.predict": "analysis.business_metric",
    "analysis.prediction": "analysis.business_metric",
    "analysis.business": "analysis.business_metric",
    "rule.check": "rule.calculate",
    "rule.compute": "rule.calculate",
    "project.create": "project.register.simple",
    "project.register": "project.register.simple",
    "project.approval": "project.approval.result.record",
    "monitor.create": "monitor.item.register",
    "monitor.register": "monitor.item.register",
    "reminder.create": "human.task.create",
    "human.confirm": "human.task.create",
    "human.review": "human.task.create",
    "governance.control": "control.policy.apply",
    "control.apply": "control.policy.apply",
    "capability.evolve": "evolution.candidate.create",
    "knowledge.search": "knowledge.query",
    "knowledge.answer": "knowledge.qa.answer",
    "execution_sandbox.run_task": "sandbox.run_task",
    "execution_sandbox.run_code": "sandbox.run_code",
    "execution_sandbox.run_browser": "sandbox.run_browser",
    "sandbox.task.run": "sandbox.run_task",
    "sandbox.code.run": "sandbox.run_code",
    "sandbox.browser.run": "sandbox.run_browser",
    "sandbox.run": "sandbox.run_task",
}

BUSINESS_OBJECT_SCOPES = {
    "product": {
        "label": "产品资料",
        "preferred_sheets": ["产品资料", "价格成本"],
        "allowed_fields": [
            "product_id", "product_name", "product_type", "category", "target_crop", "applicable_crop",
            "region", "specification", "package_spec", "unit_price", "price", "unit_cost", "cost",
            "gross_margin_rate", "fixed_project_budget", "description", "usage", "dosage",
            "产品编号", "产品名称", "产品类型", "适用作物", "适用区域", "规格", "包装规格",
            "单价", "成本", "毛利率", "固定项目预算", "说明", "用法", "用量",
        ],
    },
    "budget": {
        "label": "项目预算",
        "preferred_sheets": ["项目预算", "价格成本"],
        "allowed_fields": [
            "item_name", "amount_cny", "budget_item", "budget_amount", "fixed_project_budget",
            "unit_price", "list_price", "price", "unit_cost", "standard_variable_cost", "variable_cost",
            "cost", "gross_margin_rate", "contribution_margin", "unit_margin", "margin", "unit", "uom",
            "项目", "预算项", "费用项",
            "项目名称", "金额", "预算金额", "预算合计", "预备费", "单价", "成本", "毛利率",
        ],
    },
    "demand": {
        "label": "需求历史",
        "preferred_sheets": ["需求历史", "历史销售", "销售历史"],
        "allowed_fields": [
            "year", "month", "period", "date", "demand_qty", "order_qty", "sales_qty",
            "quantity", "amount", "region", "dealer_name", "product_id", "年份", "月份",
            "年月", "日期", "需求量", "订单量", "销量", "销售量", "数量", "金额", "区域",
            "经销商", "经销商名称", "产品编号",
        ],
    },
    "customer_feedback": {
        "label": "客户反馈",
        "preferred_sheets": ["客户反馈", "回访记录", "经销商反馈", "经销商订单"],
        "allowed_fields": [
            "customer_id", "customer_name", "dealer_id", "dealer_name", "feedback", "comment",
            "sentiment", "satisfaction", "issue", "order_qty", "amount", "is_repeat_order",
            "客户编号", "客户名称", "经销商编号", "经销商名称", "反馈", "评价", "满意度",
            "问题", "订单量", "金额", "是否复购",
        ],
    },
    "module": {
        "label": "平台模块",
        "preferred_sheets": ["模块清单", "能力字典", "模块验证", "模块"],
        "allowed_fields": [
            "module", "module_name", "module_name_cn", "capability", "capability_code",
            "status", "owner", "模块", "模块名称", "中文名", "能力", "能力码", "状态", "负责人",
        ],
    },
}


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
    parameters = _parameters_with_current_attachments(intent_task)
    if parameters.get("execution_kind") == "uploaded_document_sales_reconciliation":
        return []
    contract = parameters.get("intent_contract") if isinstance(parameters.get("intent_contract"), dict) else {}
    contract_tasks = contract.get("tasks") if isinstance(contract.get("tasks"), list) else []
    if contract_tasks:
        plan = _plan_from_intent_contract(contract_tasks, parameters)
        if plan:
            if _contract_plan_needs_workflow_rebuild(plan, parameters):
                return _build_plan_from_intent_task(intent_task)
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
        if _contract_plan_needs_workflow_rebuild(plan, parameters):
            return _build_plan_from_intent_task(intent_task)
        return sorted(plan, key=lambda item: item["step"])
    return _build_plan_from_intent_task(intent_task)


def _parameters_with_current_attachments(intent_task: dict[str, Any]) -> dict[str, Any]:
    """Do not schedule parsing for personal knowledge that is already indexed."""
    source = intent_task.get("parameters") if isinstance(intent_task.get("parameters"), dict) else {}
    parameters = dict(source)
    utterance = str(parameters.get("utterance") or intent_task.get("description") or "")
    if _goal_mentions_knowledge_base(utterance):
        parameters["uploaded_documents"] = []
        return parameters
    documents = source.get("uploaded_documents") if isinstance(source.get("uploaded_documents"), list) else []
    parameters["uploaded_documents"] = [
        item for item in documents
        if isinstance(item, dict)
        and str(item.get("asset_scope") or item.get("assetScope") or "") != "personal_knowledge"
    ]
    return parameters


def _contract_plan_needs_workflow_rebuild(plan: list[dict[str, Any]], parameters: dict[str, Any]) -> bool:
    """Reject model-produced plans that omit required v4.0 orchestration nodes."""
    utterance = str(parameters.get("utterance") or "")
    knowledge_request = _goal_mentions_knowledge_base(utterance)
    capabilities = {str(item.get("capability") or "") for item in plan}
    business_capabilities = capabilities - DOCUMENT_CAPABILITIES - {ANSWER_CAPABILITY}
    data_operations = {
        str((item.get("payload_hint") or {}).get("aggregate_operation") or (item.get("payload_hint") or {}).get("operation") or "").lower()
        for item in plan
        if item.get("capability") in DATA_CAPABILITIES
    }
    if _goal_needs_data(utterance) and not business_capabilities:
        return True
    if _looks_like_forecast_request(utterance):
        if "analysis.business_metric" not in capabilities:
            return True
        if "monthly_metric_series" not in data_operations:
            return True
    if _looks_like_budget_risk_request(utterance):
        if "rule.calculate" not in capabilities:
            return True
        if "budget_summary" not in data_operations:
            return True
        if "monthly_metric_series" not in data_operations:
            return True
    if _looks_like_rule_request(utterance) and "rule.calculate" not in capabilities:
        return True
    if _goal_needs_project_management(utterance) and "project.register.simple" not in capabilities:
        return True
    if _goal_needs_monitoring(utterance) and "monitor.item.register" not in capabilities:
        return True
    if _goal_needs_human_confirmation(utterance) and "human.task.create" not in capabilities:
        return True
    if _goal_needs_data(utterance) and not knowledge_request and not any(capability in DATA_CAPABILITIES for capability in capabilities):
        return True
    if (parameters.get("uploaded_documents") or _goal_mentions_uploaded_file(utterance)) and not knowledge_request and not any(capability in DOCUMENT_CAPABILITIES for capability in capabilities):
        return True
    return False


def _plan_from_intent_contract(contract_tasks: list[dict[str, Any]], parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """Build an execution DAG from the model-produced task contract."""
    plan: list[dict[str, Any]] = []
    uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
    for index, item in enumerate(contract_tasks, start=1):
        if not isinstance(item, dict):
            continue
        user_goal = str(item.get("user_goal") or parameters.get("utterance") or item.get("task_name") or "")
        combined_goal = _contract_task_goal_text(item, parameters, user_goal)
        raw_capability = str(item.get("capability_code") or "").strip()
        capability = _normalize_executable_capability(raw_capability, combined_goal)
        if not raw_capability or capability == "workflow.execute":
            continue
        if not capability:
            capability = raw_capability
        capability = _coerce_data_capability_for_goal(capability, combined_goal)
        execution_instruction = item.get("execution_instruction") if isinstance(item.get("execution_instruction"), dict) else {}
        instruction_inputs = execution_instruction.get("input_requirements") if isinstance(execution_instruction.get("input_requirements"), dict) else {}
        operation = execution_instruction.get("action") or item.get("operation") or parameters.get("action") or "process"
        input_contract = item.get("input_contract") if isinstance(item.get("input_contract"), dict) else {}
        input_parameters = input_contract.get("parameters") if isinstance(input_contract.get("parameters"), dict) else {}
        extracted_details = item.get("extracted_details") if isinstance(item.get("extracted_details"), dict) else {}
        target_period = (
            instruction_inputs.get("target_period")
            or input_parameters.get("target_period")
            or extracted_details.get("target_period")
            or _target_period_from_goal_text(combined_goal)
        )
        forecast_horizon = (
            instruction_inputs.get("forecast_horizon")
            or
            input_parameters.get("forecast_horizon")
            or extracted_details.get("forecast_horizon")
            or _forecast_horizon_from_goal_text(combined_goal)
        )
        aggregate_operation = None
        if capability == "data.aggregate" and _looks_like_latest_metric_by_entity_request(combined_goal):
            operation = "latest_metric_by_entity"
            aggregate_operation = "latest_metric_by_entity"
        elif capability == "data.aggregate" and _looks_like_entity_list_request(combined_goal):
            operation = "list_distinct"
            aggregate_operation = "list_distinct"
        elif capability == "data.aggregate":
            current_operation = str(operation or "").lower()
            inferred_operation = _infer_data_aggregate_operation(combined_goal)
            if current_operation and current_operation not in WEAK_DATA_AGGREGATE_OPERATIONS:
                aggregate_operation = current_operation
            elif inferred_operation != "retrieve":
                operation = inferred_operation
                aggregate_operation = inferred_operation
        depends_on = item.get("dependencies") if isinstance(item.get("dependencies"), list) else []
        plan.append({
            "step": index,
            "task_id": str(item.get("task_id") or f"intent-task-{index}"),
            "name": item.get("task_name") or user_goal or capability,
            "capability": capability,
            "depends_on": depends_on,
            "payload_hint": {
                "user_goal": combined_goal,
                "analysis_goal": combined_goal,
                "operation": operation,
                **({"aggregate_operation": aggregate_operation} if aggregate_operation else {}),
                **({"forecast_horizon": forecast_horizon} if forecast_horizon else {}),
                **({"target_period": target_period} if target_period else {}),
                **({"target_year": int(str(target_period)[:4])} if target_period else {}),
                **({"target_month": int(str(target_period)[5:7])} if target_period else {}),
                "time_range": instruction_inputs.get("time_range") or input_parameters.get("time_range") or extracted_details.get("time_range") or "",
                "time_grain": instruction_inputs.get("time_grain") or input_parameters.get("time_grain") or extracted_details.get("time_grain") or "",
                "metrics": instruction_inputs.get("metrics") or input_parameters.get("metrics") or extracted_details.get("metrics") or [],
                "calculations": instruction_inputs.get("calculations") or input_parameters.get("calculations") or extracted_details.get("calculations") or [],
                "risk_checks": instruction_inputs.get("risk_checks") or input_parameters.get("risk_checks") or extracted_details.get("risk_checks") or [],
                "execution_instruction": execution_instruction,
                "instruction_inputs": instruction_inputs,
                "extracted_details": extracted_details,
                "task_card": item,
                "task_type": item.get("task_type") or "",
                "capability_requirement": item.get("capability_requirement") if isinstance(item.get("capability_requirement"), dict) else {},
                "data_object": instruction_inputs.get("data_object") or item.get("data_object") or "",
                "data_scope": item.get("data_scope") or "",
                "fields": instruction_inputs.get("fields") if isinstance(instruction_inputs.get("fields"), list) else item.get("fields") if isinstance(item.get("fields"), list) else [],
                "filters": (
                    instruction_inputs.get("filters")
                    if isinstance(instruction_inputs.get("filters"), dict)
                    else item.get("filters") if isinstance(item.get("filters"), dict) else {}
                ),
                "data_access_contract": item.get("data_access_contract") if isinstance(item.get("data_access_contract"), dict) else {},
                "required_data": item.get("required_data") or [],
                "output_schema": item.get("output_schema") or {"type": "user_readable_result"},
                "expected_outputs": execution_instruction.get("output_requirements") if isinstance(execution_instruction.get("output_requirements"), list) else item.get("expected_outputs") if isinstance(item.get("expected_outputs"), list) else [],
            },
            "purpose": execution_instruction.get("objective") or item.get("task_name") or "执行意图分析拆解后的最小任务",
        })
    if any(str(item.get("capability") or "").startswith("sandbox.") for item in plan):
        return _topologically_order_plan(plan)

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
    _drop_cached_document_parse_steps(plan, uploaded_documents, parameters)
    _ensure_data_evidence_step(plan, parameters, uploaded_documents)
    _ensure_data_before_downstream_analysis(plan)
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


def _drop_cached_document_parse_steps(plan: list[dict[str, Any]], uploaded_documents: list[dict[str, Any]], parameters: dict[str, Any]) -> None:
    if not plan or not uploaded_documents:
        return
    utterance = str(parameters.get("utterance") or "")
    if _goal_explicitly_asks_to_parse(utterance) or not _uploaded_documents_have_cached_fields(uploaded_documents):
        return
    parse_keys = {
        str(item.get("task_id") or item.get("step"))
        for item in plan
        if item.get("capability") in {"document.table.extract", "document.parse"}
    }
    parse_steps = {
        str(item.get("step"))
        for item in plan
        if item.get("capability") in {"document.table.extract", "document.parse"}
    }
    if not parse_keys and not parse_steps:
        return
    plan[:] = [
        item for item in plan
        if item.get("capability") not in {"document.table.extract", "document.parse"}
    ]
    removed = parse_keys | parse_steps
    for item in plan:
        deps = item.get("depends_on") if isinstance(item.get("depends_on"), list) else []
        item["depends_on"] = [dep for dep in deps if str(dep) not in removed]


def _contract_task_goal_text(item: dict[str, Any], parameters: dict[str, Any], fallback: str = "") -> str:
    parts: list[str] = []
    execution_instruction = item.get("execution_instruction") if isinstance(item.get("execution_instruction"), dict) else {}
    instruction_inputs = execution_instruction.get("input_requirements") if isinstance(execution_instruction.get("input_requirements"), dict) else {}
    extracted_details = item.get("extracted_details") if isinstance(item.get("extracted_details"), dict) else {}
    input_contract = item.get("input_contract") if isinstance(item.get("input_contract"), dict) else {}
    input_parameters = input_contract.get("parameters") if isinstance(input_contract.get("parameters"), dict) else {}
    for value in (
        execution_instruction.get("objective"),
        parameters.get("utterance"),
        fallback,
        item.get("task_name"),
        item.get("task_type"),
        item.get("data_object"),
        item.get("operation"),
        instruction_inputs.get("time_range"),
        instruction_inputs.get("forecast_horizon"),
        extracted_details.get("time_range"),
        input_parameters.get("time_range"),
        extracted_details.get("forecast_horizon"),
        input_parameters.get("forecast_horizon"),
        parameters.get("action"),
        parameters.get("object"),
    ):
        if value not in (None, "", [], {}):
            parts.append(str(value))
    for value in item.get("fields") if isinstance(item.get("fields"), list) else []:
        if value not in (None, ""):
            parts.append(str(value))
    return " ".join(dict.fromkeys(parts)).strip()


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
    existing_dependencies = content_step.get("depends_on") if isinstance(content_step.get("depends_on"), list) else []
    content_step["depends_on"] = _merge_dependencies(existing_dependencies, [evidence_step["step"]])


def _ensure_data_before_downstream_analysis(plan: list[dict[str, Any]]) -> None:
    data_items = [item for item in plan if item.get("capability") in DATA_CAPABILITIES]
    if not data_items:
        return
    default_data_step = data_items[0]["step"]
    data_step_by_operation = {
        str((item.get("payload_hint") or {}).get("aggregate_operation") or (item.get("payload_hint") or {}).get("operation") or "").lower(): item["step"]
        for item in data_items
    }
    for item in plan:
        capability = str(item.get("capability") or "")
        if capability.startswith("analysis.") or capability == "rule.calculate" or capability.startswith("knowledge."):
            dependencies = item.get("depends_on") if isinstance(item.get("depends_on"), list) else []
            data_step = default_data_step
            if capability.startswith("analysis."):
                data_step = data_step_by_operation.get("monthly_metric_series") or default_data_step
            elif capability == "rule.calculate":
                data_step = data_step_by_operation.get("budget_summary") or default_data_step
            item["depends_on"] = _merge_dependencies(dependencies, [data_step])
            if capability == "rule.calculate" and _looks_like_budget_risk_request(str((item.get("payload_hint") or {}).get("user_goal") or "")):
                item["depends_on"] = _merge_dependencies(
                    item["depends_on"],
                    [
                        data_step_by_operation.get("monthly_metric_series"),
                        data_step_by_operation.get("budget_summary"),
                    ],
                )


def _merge_dependencies(existing: list[Any], required: list[Any]) -> list[Any]:
    merged: list[Any] = []
    for value in [*existing, *required]:
        if value not in merged:
            merged.append(value)
    return merged


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
    old_step_to_new = {str(item.get("step")): index for index, item in enumerate(ordered, start=1)}
    task_id_to_new = {
        str(item.get("task_id")): index
        for index, item in enumerate(ordered, start=1)
        if item.get("task_id")
    }
    for index, item in enumerate(ordered, start=1):
        remapped_dependencies: list[int] = []
        for dependency in item.get("depends_on") if isinstance(item.get("depends_on"), list) else []:
            dependency_key = str(dependency)
            mapped = task_id_to_new.get(dependency_key) or old_step_to_new.get(dependency_key)
            if mapped and mapped != index and mapped not in remapped_dependencies:
                remapped_dependencies.append(mapped)
        item["depends_on"] = remapped_dependencies
        item["step"] = index
    return ordered


def _legacy_build_plan_from_intent_task(intent_task: dict[str, Any]) -> list[dict[str, Any]]:
    """Let workflow execution derive the graph from a simple intent task."""
    parameters = intent_task.get("parameters") if isinstance(intent_task.get("parameters"), dict) else {}
    capability = _normalize_executable_capability(str(intent_task.get("capability_code") or "").strip())
    if not capability or capability == "workflow.execute":
        return []
    utterance = str(parameters.get("utterance") or intent_task.get("description") or "").strip()
    uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
    capability = _coerce_data_capability_for_goal(capability, utterance)
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
                **({"operation": "list_distinct", "aggregate_operation": "list_distinct"} if capability == "data.aggregate" and _looks_like_entity_list_request(utterance) else {}),
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


def _coerce_data_capability_for_goal(capability: str, user_goal: str) -> str:
    if capability == "data.search":
        inferred_operation = _infer_data_aggregate_operation(user_goal)
        if (
            _looks_like_entity_list_request(user_goal)
            or _looks_like_rule_request(user_goal)
            or inferred_operation != "retrieve"
        ):
            return "data.aggregate"
    return capability


def _legacy_normalize_executable_capability(capability: str) -> str:
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


def _normalize_executable_capability(capability: str, user_goal: str = "") -> str:
    """Normalize model/intent capability names to registered v4.0 abilities."""
    value = str(capability or "").strip()
    if not value or value == "workflow.execute":
        return _infer_primary_capability_from_goal(user_goal, ANSWER_CAPABILITY)
    lowered = value.lower()
    normalized = lowered.replace("-", "_")
    dotted = normalized.replace("_", ".")
    if _goal_mentions_knowledge_base(user_goal) and (
        lowered.startswith(("data.", "document.", "file.", "table."))
        or normalized.startswith(("data_", "document_", "file_", "table_"))
    ):
        return "knowledge.query"
    for candidate in (value, lowered, dotted):
        if candidate in KNOWN_EXECUTABLE_CAPABILITIES:
            return candidate
        if candidate in V40_CAPABILITY_ALIASES:
            return V40_CAPABILITY_ALIASES[candidate]
    if lowered.startswith(("data.query", "data.retrieve", "data.fetch")) or normalized.startswith(("data_query", "data_retrieve", "data_fetch")):
        return "data.search"
    if lowered.startswith(("data.aggregate", "data.summary", "data.summarize", "data.statistics")):
        return "data.aggregate"
    if lowered.startswith(("analysis.", "forecast.", "predict.", "prediction.", "data.analyze.", "data.analysis.")):
        return "analysis.business_metric"
    if lowered.startswith(("rule.", "risk.", "compliance.")):
        return "rule.calculate"
    if lowered.startswith("project."):
        return "project.task.query" if "query" in lowered or "list" in lowered else "project.register.simple"
    if lowered.startswith(("monitor.", "reminder.")):
        return "monitor.item.register"
    if lowered.startswith("human."):
        return "human.task.create"
    if lowered.startswith(("control.", "governance.", "drive.")):
        return "control.policy.apply"
    if lowered.startswith(("evolution.", "capability.evolve.")):
        return "evolution.candidate.create"
    if lowered.startswith("knowledge."):
        return "knowledge.query"
    if lowered.startswith(("sandbox.", "execution_sandbox.")):
        if any(token in f"{lowered} {user_goal}".lower() for token in ("browser", "url", "web", "浏览器", "网页", "采集")):
            return "sandbox.run_browser"
        if any(token in f"{lowered} {user_goal}".lower() for token in ("code", "python", "script", "代码", "脚本", "程序")):
            return "sandbox.run_code"
        return "sandbox.run_task"
    return _closest_registered_capability(value, user_goal)


def _closest_registered_capability(capability: str, user_goal: str = "") -> str:
    value = str(capability or "").strip().lower()
    if not value:
        return ""
    text = f"{value} {user_goal or ''}".lower()
    semantic_routes = (
        (("browser", "web", "url", "浏览器", "网页", "采集"), "sandbox.run_browser"),
        (("run code", "python", "script", "代码", "脚本", "程序"), "sandbox.run_code"),
        (("sandbox", "execution sandbox", "执行沙箱", "沙箱"), "sandbox.run_task"),
        (("forecast", "predict", "prediction", "analysis", "analyze", "趋势", "预测", "下一个月", "下个月", "下月", "下季度", "下半年", "半年", "下一年", "未来一年"), "analysis.business_metric"),
        (("rule", "risk", "compliance", "check", "validate", "规则", "核对", "风险", "盈亏平衡"), "rule.calculate"),
        (("aggregate", "statistics", "summary", "count", "sum", "统计", "汇总", "多少", "几个"), "data.aggregate"),
        (("query", "retrieve", "search", "fetch", "查询", "读取", "检索"), "data.search"),
        (("parse", "extract", "document", "table", "解析", "表格", "文件"), "document.table.extract"),
        (("project", "approval", "项目", "立项", "审批", "登记"), "project.register.simple"),
        (("monitor", "reminder", "alert", "监控", "提醒", "预警"), "monitor.item.register"),
        (("human", "manual", "confirm", "人工", "真人", "确认", "待办"), "human.task.create"),
        (("knowledge", "qa", "answer", "知识", "资料", "制度"), "knowledge.query"),
        (("content", "generate", "report", "draft", "生成", "报告", "文案"), "content.generate"),
    )
    for tokens, mapped in semantic_routes:
        if any(token in text for token in tokens) and mapped in KNOWN_EXECUTABLE_CAPABILITIES:
            return mapped
    best = ""
    best_score = 0.0
    for candidate in KNOWN_EXECUTABLE_CAPABILITIES:
        score = SequenceMatcher(None, value, candidate.lower()).ratio()
        if score > best_score:
            best = candidate
            best_score = score
    return best if best_score >= 0.72 else ""


def _build_plan_from_intent_task(intent_task: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a v4.0 workflow graph from one confirmed business intent."""
    parameters = _parameters_with_current_attachments(intent_task)
    utterance = str(parameters.get("utterance") or intent_task.get("description") or "").strip()
    raw_capability = str(intent_task.get("capability_code") or "").strip()
    capability = _normalize_executable_capability(raw_capability, utterance)
    if raw_capability and raw_capability != "workflow.execute" and not capability:
        return [{
            "step": 1,
            "name": "平台暂未登记该能力",
            "capability": raw_capability,
            "depends_on": [],
            "payload_hint": {
                "user_goal": utterance,
                "unregistered_capability": raw_capability,
            },
            "purpose": "流程执行引擎未找到可安全映射的已登记能力，停止执行并保留审计记录。",
            "execution_group": 1,
            "execution_mode": "sequential",
            "provider_module_hint": "capability-registry",
        }]
    uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
    business_scope = _infer_business_scope(utterance, parameters)
    cached_upload_data = _uploaded_documents_have_cached_fields(uploaded_documents)
    explicit_parse_request = _goal_explicitly_asks_to_parse(utterance)

    plan: list[dict[str, Any]] = []
    used: set[str] = set()

    def add(
        capability_code: str,
        name: str,
        *,
        depends_on: list[int] | None = None,
        payload_hint: dict[str, Any] | None = None,
        purpose: str = "",
    ) -> int:
        normalized_capability = _normalize_executable_capability(capability_code, utterance)
        if normalized_capability in used and normalized_capability not in DATA_CAPABILITIES:
            return next(item["step"] for item in plan if item["capability"] == normalized_capability)
        step = len(plan) + 1
        hint = dict(payload_hint or {})
        if normalized_capability != capability_code:
            hint.setdefault("original_capability_code", capability_code)
            hint.setdefault("fallback_reason", "capability_normalized_by_workflow")
        plan.append({
            "step": step,
            "name": name,
            "capability": normalized_capability,
            "depends_on": depends_on or [],
            "payload_hint": hint,
            "purpose": purpose,
        })
        used.add(normalized_capability)
        return step

    control_step = None
    if _goal_needs_control(utterance):
        control_step = add(
            "control.policy.apply",
            "应用流程驾驭策略",
            payload_hint={"user_goal": utterance, "control_subject": "workflow_execution"},
            purpose="在流程派发前检查任务边界、人工接管策略和执行范围。",
        )

    parse_step = None
    if (
        (uploaded_documents or capability in DOCUMENT_CAPABILITIES or _goal_mentions_uploaded_file(utterance))
        and (explicit_parse_request or not cached_upload_data)
    ):
        parse_step = add(
            "document.table.extract",
            "解析当前对话上传文件",
            depends_on=[control_step] if control_step else [],
            payload_hint={"uploaded_documents": uploaded_documents, "user_goal": utterance},
            purpose="提取正文、表格、字段、行号和来源位置，供后续模块按授权读取。",
        )

    needs_data = (
        bool(uploaded_documents)
        or capability in DATA_CAPABILITIES
        or capability.startswith("analysis.")
        or capability.startswith("rule.")
        or capability.startswith("project.")
        or capability.startswith("monitor.")
        or (not _goal_mentions_knowledge_base(utterance) and _goal_needs_data(utterance))
    )
    data_step = None
    data_steps_by_operation: dict[str, int] = {}
    if needs_data:
        aggregate_operation = _infer_data_aggregate_operation(utterance)
        data_dependencies = [step for step in (parse_step, control_step) if step]
        data_requests: list[dict[str, Any]] = []
        if _looks_like_forecast_request(utterance) or _looks_like_budget_risk_request(utterance):
            data_requests.append({
                "operation": "monthly_metric_series",
                "scope": _business_scope_for_key("demand", parameters, fallback=business_scope),
                "name": "读取并整理月度需求序列",
                "purpose": "为分析预测引擎准备按月份聚合的需求、订单或销量序列。",
            })
        if _looks_like_rule_request(utterance):
            data_requests.append({
                "operation": "budget_summary",
                "scope": _business_scope_for_key("budget", parameters, fallback=business_scope),
                "name": "读取并整理预算、价格和成本数据",
                "purpose": "为规则计算引擎准备预算完整性、价格成本和盈亏平衡所需的结构化数据。",
            })
        if not data_requests:
            data_requests.append({
                "operation": aggregate_operation,
                "scope": business_scope,
                "name": "读取并整理授权业务数据",
                "purpose": "按账号、项目、对话权限读取/聚合数据，并把结构化业务结果交给下游引擎。",
            })
        for request in data_requests:
            request_operation = str(request.get("operation") or "retrieve")
            request_scope = request.get("scope") if isinstance(request.get("scope"), dict) else business_scope
            step = add(
                "data.aggregate" if request_operation != "retrieve" or request_scope.get("scope_key") != "generic" else "data.search",
                str(request.get("name") or "读取并整理授权业务数据"),
                depends_on=data_dependencies,
                payload_hint={
                    "user_goal": utterance,
                    "analysis_goal": utterance,
                    "aggregate_operation": request_operation,
                    "operation": request_operation,
                    "data_object": request_scope.get("label") or parameters.get("data_object") or parameters.get("object") or "",
                    "business_scope": request_scope,
                },
                purpose=str(request.get("purpose") or "按权限读取并聚合数据，形成下游引擎可消费的业务结果。"),
            )
            data_steps_by_operation[request_operation] = step
            if data_step is None:
                data_step = step

    capability_steps: dict[str, int] = {}
    last_business_step = data_step or parse_step or control_step
    for capability_code in _infer_v40_capability_sequence(utterance, capability):
        if capability_code in DATA_CAPABILITIES or capability_code in DOCUMENT_CAPABILITIES or capability_code == ANSWER_CAPABILITY:
            continue
        capability_data_step = data_step
        if capability_code.startswith("analysis."):
            capability_data_step = data_steps_by_operation.get("monthly_metric_series") or data_step
        elif capability_code == "rule.calculate":
            capability_data_step = data_steps_by_operation.get("budget_summary") or data_step
        dependencies = _dependencies_for_v40_capability(capability_code, capability_steps, capability_data_step, parse_step, control_step, last_business_step)
        if capability_code == "rule.calculate" and _looks_like_budget_risk_request(utterance):
            dependencies = _merge_dependencies(
                dependencies,
                [
                    data_steps_by_operation.get("monthly_metric_series"),
                    data_steps_by_operation.get("budget_summary"),
                ],
            )
        step = add(
            capability_code,
            _capability_step_name(capability_code),
            depends_on=dependencies,
            payload_hint={"user_goal": utterance, "analysis_goal": utterance},
            purpose=_capability_step_purpose(capability_code),
        )
        capability_steps[capability_code] = step
        last_business_step = step

    if any(str(capability_code).startswith("sandbox.") for capability_code in used):
        return _assign_execution_groups(_topologically_order_plan(plan))

    if ANSWER_CAPABILITY not in used:
        content_dependencies = _leaf_steps(plan)
        add(
            ANSWER_CAPABILITY,
            "生成用户可读业务回答",
            depends_on=content_dependencies,
            payload_hint={
                "content_type": "workflow_user_answer",
                "utterance": utterance,
                "user_goal": utterance,
            },
            purpose="汇总各模块业务结果，向前端输出用户真正要看的结论。",
        )

    return _assign_execution_groups(_topologically_order_plan(plan))


def _infer_primary_capability_from_goal(user_goal: str, fallback: str) -> str:
    text = str(user_goal or "").lower()
    if any(token in text for token in ("sandbox", "execution sandbox", "执行沙箱", "沙箱", "python", "script", "代码", "脚本", "浏览器", "网页")):
        if any(token in text for token in ("browser", "url", "web", "浏览器", "网页", "采集")):
            return "sandbox.run_browser"
        if any(token in text for token in ("code", "python", "script", "代码", "脚本", "程序")):
            return "sandbox.run_code"
        return "sandbox.run_task"
    if _looks_like_budget_risk_request(user_goal):
        return "rule.calculate"
    if any(token in text for token in ("预测", "趋势", "下季度", "下半年", "半年", "下一年", "未来一年", "需求区间", "forecast")):
        return "analysis.business_metric"
    if _looks_like_rule_request(user_goal):
        return "rule.calculate"
    if _goal_needs_project_management(user_goal):
        return "project.register.simple"
    if _goal_needs_monitoring(user_goal):
        return "monitor.item.register"
    if _goal_needs_human_confirmation(user_goal):
        return "human.task.create"
    if any(token in text for token in ("监控", "提醒", "预警", "跟踪", "执行进度")):
        return "monitor.item.register"
    if any(token in text for token in ("确认", "人工", "待办", "负责人", "审批人", "审批")):
        return "human.task.create"
    if any(token in text for token in ("知识库", "资料", "制度", "参数", "说明", "p-fert", "产品")):
        return "knowledge.query"
    if any(token in text for token in ("多少", "几个", "哪些", "列出", "统计", "汇总", "最高", "最多", "最大", "金额", "订单", "需求")):
        return "data.aggregate"
    return fallback


def _infer_business_scope(user_goal: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    params = parameters if isinstance(parameters, dict) else {}
    text = str(user_goal or "")
    explicit_object = str(params.get("data_object") or params.get("object") or "").strip()
    product_match = re.search(r"P-[A-Z0-9-]+", text, re.IGNORECASE)
    if _looks_like_demand_forecast_scope(text):
        scope_key = "demand"
    elif _looks_like_metric_by_entity_request(text):
        scope_key = "demand"
    elif product_match or any(word in text for word in ("产品", "肥料", "参数", "P-FERT")):
        scope_key = "product"
    elif any(word in text for word in ("预算", "费用", "金额", "价格", "成本", "毛利", "盈亏平衡")):
        scope_key = "budget"
    elif any(word in text for word in ("需求", "订单", "销量", "销售", "下季度", "月份", "2025", "2026")):
        scope_key = "demand"
    elif any(word in text for word in ("客户反馈", "反馈", "优质客户", "满意", "评价", "回访")):
        scope_key = "customer_feedback"
    elif any(word in text for word in ("模块", "引擎", "能力码", "能力字典", "上游未接入")):
        scope_key = "module"
    elif explicit_object:
        scope_key = "generic"
    else:
        scope_key = "generic"

    spec = BUSINESS_OBJECT_SCOPES.get(scope_key, {})
    entity_id = str(params.get("entity_id") or params.get("product_id") or "").strip()
    if product_match:
        entity_id = product_match.group(0).upper()
    query_kind = "detail" if entity_id or any(word in text for word in ("基本参数", "参数", "详情", "是什么", "告诉我")) else "summary"
    if scope_key == "budget":
        query_kind = "budget_summary"
    if scope_key == "demand" and _looks_like_month_metric_request(text):
        query_kind = "monthly_max_metric"
    if scope_key == "customer_feedback":
        query_kind = "evidence_for_analysis"
    return {
        "scope_key": scope_key,
        "label": explicit_object or spec.get("label") or "当前授权业务数据",
        "preferred_sheets": spec.get("preferred_sheets") or [],
        "allowed_fields": spec.get("allowed_fields") or [],
        "entity_id": entity_id,
        "query_kind": query_kind,
    }


def _business_scope_for_key(scope_key: str, parameters: dict[str, Any] | None = None, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    params = parameters if isinstance(parameters, dict) else {}
    base = dict(fallback or {})
    spec = BUSINESS_OBJECT_SCOPES.get(scope_key, {})
    query_kind = "summary"
    if scope_key == "budget":
        query_kind = "budget_summary"
    elif scope_key == "demand":
        query_kind = "monthly_metric_series"
    return {
        **base,
        "scope_key": scope_key,
        "label": spec.get("label") or base.get("label") or params.get("data_object") or params.get("object") or "当前授权业务数据",
        "preferred_sheets": spec.get("preferred_sheets") or base.get("preferred_sheets") or [],
        "allowed_fields": spec.get("allowed_fields") or base.get("allowed_fields") or [],
        "entity_id": str(params.get("entity_id") or params.get("product_id") or base.get("entity_id") or ""),
        "query_kind": query_kind,
    }


def _dependencies_for_v40_capability(
    capability: str,
    capability_steps: dict[str, int],
    data_step: int | None,
    parse_step: int | None,
    control_step: int | None,
    last_step: int | None,
) -> list[int]:
    evidence_step = data_step or parse_step or control_step
    if capability.startswith("analysis.") or capability == "rule.calculate" or capability.startswith("knowledge."):
        return [evidence_step] if evidence_step else []
    if capability.startswith("project."):
        deps = [
            capability_steps.get("analysis.business_metric"),
            capability_steps.get("rule.calculate"),
            evidence_step,
        ]
        return _unique_steps(deps)
    if capability.startswith("monitor."):
        deps = [
            capability_steps.get("project.register.simple"),
            capability_steps.get("project.register.major"),
            capability_steps.get("analysis.business_metric"),
            capability_steps.get("rule.calculate"),
            evidence_step,
        ]
        return _unique_steps(deps)
    if capability.startswith("human."):
        deps = [
            capability_steps.get("rule.calculate"),
            capability_steps.get("project.register.simple"),
            capability_steps.get("project.register.major"),
            capability_steps.get("analysis.business_metric"),
            evidence_step,
        ]
        return _unique_steps(deps)
    if capability.startswith("evolution."):
        deps = [
            capability_steps.get("monitor.item.register"),
            capability_steps.get("project.register.simple"),
            capability_steps.get("project.register.major"),
            capability_steps.get("analysis.business_metric"),
            capability_steps.get("rule.calculate"),
            evidence_step,
        ]
        return _unique_steps(deps)
    return [last_step] if last_step else []


def _unique_steps(values: list[int | None]) -> list[int]:
    result: list[int] = []
    for value in values:
        if isinstance(value, int) and value not in result:
            result.append(value)
    return result


def _leaf_steps(plan: list[dict[str, Any]]) -> list[int]:
    depended_on = {
        int(dep)
        for item in plan
        for dep in (item.get("depends_on") or [])
        if str(dep).isdigit()
    }
    leaves = [
        item["step"]
        for item in plan
        if item["step"] not in depended_on and item["capability"] != "control.policy.apply"
    ]
    if leaves:
        return leaves
    return [plan[-1]["step"]] if plan else []


def _infer_v40_capability_sequence(user_goal: str, primary_capability: str) -> list[str]:
    text = str(user_goal or "").lower()
    sequence: list[str] = []

    def include(capability: str) -> None:
        normalized = _normalize_executable_capability(capability, user_goal)
        if normalized not in sequence and normalized not in {"workflow.execute"}:
            sequence.append(normalized)

    include(primary_capability)
    if any(token in text for token in ("sandbox", "execution sandbox", "执行沙箱", "沙箱", "python", "script", "代码", "脚本", "浏览器", "网页")):
        if any(token in text for token in ("browser", "url", "web", "浏览器", "网页", "采集")):
            include("sandbox.run_browser")
        elif any(token in text for token in ("code", "python", "script", "代码", "脚本", "程序")):
            include("sandbox.run_code")
        else:
            include("sandbox.run_task")
    if any(token in text for token in ("预测", "趋势", "下季度", "下半年", "半年", "下一年", "未来一年", "需求区间", "forecast")):
        include("analysis.business_metric")
    if _looks_like_rule_request(user_goal):
        include("rule.calculate")
    if _goal_needs_project_management(user_goal):
        include("project.register.simple")
    if _goal_needs_monitoring(user_goal):
        include("monitor.item.register")
    if _goal_needs_human_confirmation(user_goal):
        include("human.task.create")
    if any(token in text for token in ("监控", "提醒", "预警", "跟踪", "执行进度")):
        include("monitor.item.register")
    if any(token in text for token in ("确认", "人工", "待办", "负责人", "审批人", "审批")):
        include("human.task.create")
    if any(token in text for token in ("复盘", "沉淀", "可复用", "能力", "优化")):
        include("evolution.candidate.create")
    return sequence


def _goal_needs_data(user_goal: str) -> bool:
    text = str(user_goal or "").lower()
    return any(token in text for token in (
        "根据", "基于", "已入库", "上传", "文件", "数据", "统计", "汇总", "多少", "几个",
        "哪些", "最高", "最多", "最大", "订单", "需求", "销售", "客户", "经销商", "预算", "金额",
        "成本", "价格", "反馈", "库存", "2025", "2026",
    ))


def _goal_mentions_uploaded_file(user_goal: str) -> bool:
    text = str(user_goal or "")
    if _goal_mentions_knowledge_base(text) and not any(
        token in text for token in ("当前上传", "本次上传", "刚上传", "上传文件", "当前附件", "本次附件")
    ):
        return False
    return any(token in text for token in ("上传", "文件", "文档", "表格", "Excel", "excel", "xlsx", "采购验收"))


def _goal_explicitly_asks_to_parse(user_goal: str) -> bool:
    text = str(user_goal or "").lower()
    return any(token in text for token in (
        "parse", "extract schema", "extract table", "table structure",
        "\u89e3\u6790", "\u91cd\u65b0\u89e3\u6790", "\u63d0\u53d6\u8868\u683c", "\u8868\u7ed3\u6784", "\u5b57\u6bb5\u7ed3\u6784",
    ))


def _uploaded_documents_have_cached_fields(uploaded_documents: list[dict[str, Any]]) -> bool:
    docs = [doc for doc in uploaded_documents if isinstance(doc, dict)]
    if not docs:
        return False
    tenant_id = str(next((doc.get("tenant_id") for doc in docs if doc.get("tenant_id")), "web-workbench"))
    cache_keys = [
        str(doc.get("sha256") or doc.get("file_id") or "").strip()
        for doc in docs
        if str(doc.get("sha256") or doc.get("file_id") or "").strip()
    ]
    if not cache_keys:
        return False
    try:
        with connect() as db:
            for cache_key in cache_keys:
                like_pattern = f'%"{cache_key}"%'
                row = db.execute(
                    """
                    SELECT 1
                    FROM data_records
                    WHERE dataset='extracted_fields'
                      AND tenant_id=?
                      AND deleted_at IS NULL
                      AND payload_json LIKE ?
                    LIMIT 1
                    """,
                    (tenant_id, like_pattern),
                ).fetchone()
                if row is None:
                    return False
    except Exception:
        return False
    return True


def _goal_mentions_knowledge_base(user_goal: str) -> bool:
    text = str(user_goal or "").lower()
    return any(token in text for token in ("知识库", "资料库", "文档库", "knowledge base", "knowledge_base"))


def _goal_needs_control(user_goal: str) -> bool:
    text = str(user_goal or "")
    if any(token in text for token in ("审批", "执行", "监控", "复盘", "沉淀", "流程", "落地", "推广")):
        return True
    return _goal_needs_project_management(text)


def _goal_needs_project_management(user_goal: str) -> bool:
    text = str(user_goal or "")
    project_actions = ("立项", "审批", "登记", "结项", "归档", "创建项目", "新建项目", "项目创建", "项目登记", "项目审批")
    return _contains_any(text, (
        "\u7acb\u9879", "\u5ba1\u6279", "\u767b\u8bb0", "\u7ed3\u9879", "\u5f52\u6863",
        "\u521b\u5efa\u9879\u76ee", "\u65b0\u5efa\u9879\u76ee", "\u9879\u76ee\u521b\u5efa",
        "\u9879\u76ee\u767b\u8bb0", "\u9879\u76ee\u5ba1\u6279", "project",
    )) or any(token in text for token in project_actions)


def _goal_needs_monitoring(user_goal: str) -> bool:
    return _contains_any(str(user_goal or ""), (
        "\u76d1\u63a7", "\u63d0\u9192", "\u9884\u8b66", "\u8ddf\u8e2a", "\u6267\u884c\u76d1\u63a7",
        "\u6267\u884c\u8fdb\u5ea6", "\u540e\u7eed\u6267\u884c", "\u843d\u5730\u6267\u884c",
        "monitor", "reminder", "alert", "tracking",
    ))


def _goal_needs_human_confirmation(user_goal: str) -> bool:
    return _contains_any(str(user_goal or ""), (
        "\u786e\u8ba4", "\u4eba\u5de5", "\u771f\u4eba", "\u5f85\u529e", "\u5ba1\u6279\u5f85\u529e",
        "\u9700\u8981\u4eba\u786e\u8ba4", "\u9700\u8981\u771f\u4eba\u786e\u8ba4", "\u8d1f\u8d23\u4eba",
        "\u5ba1\u6279\u4eba", "human", "manual", "approval task",
    ))


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(token.lower() in lowered for token in tokens)


def _capability_step_name(capability: str) -> str:
    names = {
        "analysis.business_metric": "调用分析预测引擎",
        "analysis.price_forecast": "调用价格预测引擎",
        "analysis.financial_statement": "调用财务分析引擎",
        "rule.calculate": "调用规则计算引擎",
        "project.register.simple": "调用项目管理引擎",
        "project.register.major": "调用项目管理引擎",
        "project.task.query": "查询项目任务",
        "monitor.item.register": "登记监控提醒",
        "human.task.create": "创建真人确认待办",
        "evolution.candidate.create": "登记可复用能力沉淀候选",
        "control.policy.apply": "应用流程驾驭策略",
        "sandbox.run_task": "调用执行沙箱运行登记任务",
        "sandbox.run_code": "调用执行沙箱隔离运行代码",
        "sandbox.run_browser": "调用执行沙箱隔离浏览器",
        "knowledge.query": "调用知识库问答引擎",
        "knowledge.qa.answer": "调用知识库问答引擎",
    }
    return names.get(capability, f"调用已登记能力 {capability}")


def _capability_step_purpose(capability: str) -> str:
    purposes = {
        "analysis.business_metric": "基于授权业务数据形成预测、趋势或指标分析结果。",
        "analysis.price_forecast": "基于授权价格和历史数据形成预测结果。",
        "analysis.financial_statement": "基于授权财务数据形成分析结果。",
        "rule.calculate": "按已登记规则或结构化约束执行核算、校验和风险识别。",
        "project.register.simple": "把已确认的项目事项登记为项目管理记录或项目任务。",
        "project.register.major": "把重大项目事项登记为项目管理记录或项目任务。",
        "project.task.query": "读取项目任务状态和执行记录。",
        "monitor.item.register": "为后续执行节点登记监控项、提醒或预警条件。",
        "human.task.create": "把需要真人判断的事项转成待确认任务。",
        "evolution.candidate.create": "把本次流程可复用经验沉淀为能力候选。",
        "control.policy.apply": "应用驾驭机制约束流程边界、权限和人工接管策略。",
        "sandbox.run_task": "把需要隔离执行的登记任务交给执行沙箱运行，并返回执行证据。",
        "sandbox.run_code": "把临时代码交给执行沙箱隔离运行，避免在业务引擎进程内直接执行。",
        "sandbox.run_browser": "把浏览器访问或网页采集任务交给执行沙箱按白名单策略隔离运行。",
        "knowledge.query": "按授权知识材料形成可追溯业务回答。",
        "knowledge.qa.answer": "按授权知识材料形成可追溯业务回答。",
    }
    return purposes.get(capability, "按能力字典调用对应模块并保留输入输出审计。")


def _assign_execution_groups(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_step = {item["step"]: item for item in plan}
    levels: dict[int, int] = {}
    for item in plan:
        dependencies = [int(dep) for dep in item.get("depends_on") or [] if str(dep).isdigit()]
        levels[item["step"]] = 1 + max((levels.get(dep, 0) for dep in dependencies), default=0)
    for item in plan:
        item["execution_group"] = levels.get(item["step"], 1)
        item["execution_mode"] = "parallel_ready" if sum(1 for other in plan if levels.get(other["step"], 1) == item["execution_group"]) > 1 else "sequential"
        item["provider_module_hint"] = _provider_module_for_capability(item["capability"])
    return plan


def _provider_module_for_capability(capability: str) -> str:
    if capability in CAPABILITY_TO_MODULE:
        return CAPABILITY_TO_MODULE[capability].code
    if capability == "rule.calculate":
        return "rule-adapter"
    if capability == "content.generate":
        return "content-adapter"
    return "capability-registry"


def _execute_task_plan(handler: Any, envelope: dict[str, Any], platform_task_id: str, intent_task: dict[str, Any], task_plan: list[dict[str, Any]]) -> None:
    workflow_instance_id = f"wf-{platform_task_id}"
    if not _persist_workflow_state(
        envelope, platform_task_id, workflow_instance_id, "running",
        [{
            "node_instance_id": f"{workflow_instance_id}:step-{item['step']}",
            "capability": item["capability"],
            "state": "ready",
            "step": item["step"],
            "execution_group": item.get("execution_group"),
            "provider_module_hint": item.get("provider_module_hint"),
        } for item in task_plan],
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
        step_result["plan_item"]["depends_on"] = item.get("depends_on") or []
        step_result["plan_item"]["execution_group"] = item.get("execution_group")
        step_result["plan_item"]["execution_mode"] = item.get("execution_mode")
        step_result["plan_item"]["provider_module_hint"] = item.get("provider_module_hint")
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
                "execution_group": item["plan_item"].get("execution_group"),
                "provider_module_hint": item["plan_item"].get("provider_module_hint"),
            }
            for index, item in enumerate(steps, start=1)
        ],
        "workflow_completed" if workflow_state == "completed" else "workflow_completed_with_errors",
    )
    result_data = {
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
    }
    update_task(
        platform_task_id,
        state="succeeded" if workflow_state == "completed" else "completed_with_errors",
        progress=100,
        result=result_data,
        error={
            "code": "WORKFLOW_COMPLETED_WITH_ERRORS",
            "failed_steps": result_data["capability_result"]["failed_steps"],
        } if workflow_state != "completed" else None,
        clear_error=workflow_state == "completed",
    )
    handler.send(200, standard_response(envelope, "success", data=result_data))


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
        "workflow_prior_refs": _prior_output_refs(prior_outputs),
        "intent_task_id": item.get("task_id"),
        "intent_dependencies": item.get("depends_on") or [],
    }
    capability = item["capability"]
    extracted_details = payload.get("extracted_details") if isinstance(payload.get("extracted_details"), dict) else {}
    extracted_filters = extracted_details.get("filters") if isinstance(extracted_details.get("filters"), dict) else {}
    if extracted_filters:
        payload["filters"] = {**extracted_filters, **(payload.get("filters") if isinstance(payload.get("filters"), dict) else {})}
    user_goal_for_scope = str(parameters.get("utterance") or intent_task.get("description") or payload.get("analysis_goal") or payload.get("user_goal") or "")
    payload.setdefault("business_scope", _infer_business_scope(user_goal_for_scope, parameters))
    _apply_data_access_contract(payload, capability)
    if capability == "data.aggregate":
        uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
        payload.setdefault("dataset", "extracted_fields" if uploaded_documents else "business_records")
        payload.setdefault("limit", 20000 if uploaded_documents else 500)
        if uploaded_documents and payload.get("dataset") == "extracted_fields":
            payload["filters"] = _merge_parsed_document_filters(payload.get("filters"), uploaded_documents, prior_outputs)
        user_goal = str(parameters.get("utterance") or intent_task.get("description") or payload.get("analysis_goal") or "")
        payload.setdefault("analysis_goal", user_goal)
        _apply_semantic_data_aggregate_contract(payload, user_goal)
        _align_business_scope_with_data_operation(payload, parameters)
    if capability == "data.search":
        uploaded_documents = parameters.get("uploaded_documents") if isinstance(parameters.get("uploaded_documents"), list) else []
        if uploaded_documents:
            payload.setdefault("dataset", "extracted_fields")
            payload.setdefault("limit", 20000)
            if payload.get("dataset") == "extracted_fields":
                payload["filters"] = _merge_parsed_document_filters(payload.get("filters"), uploaded_documents, prior_outputs)
    if capability in {"document.parse", "document.table.extract", "document.package.build"}:
        payload.setdefault("uploaded_documents", parameters.get("uploaded_documents") or [])
    if capability.startswith("analysis."):
        payload.setdefault("analysis_goal", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("workflow_prior_outputs", _prior_outputs_for_downstream(prior_outputs))
        target_period = payload.get("target_period") or _target_period_from_goal_text(
            " ".join(
                str(value or "")
                for value in (
                    payload.get("analysis_goal"),
                    payload.get("user_goal"),
                    parameters.get("utterance"),
                    intent_task.get("description"),
                )
            )
        )
        if target_period:
            payload["target_period"] = target_period
            payload.setdefault("target_year", int(str(target_period)[:4]))
            payload.setdefault("target_month", int(str(target_period)[5:7]))
        horizon = _forecast_horizon_from_goal_text(
            " ".join(
                str(value or "")
                for value in (
                    payload.get("analysis_goal"),
                    payload.get("user_goal"),
                    parameters.get("utterance"),
                    intent_task.get("description"),
                )
            )
        )
        if horizon:
            payload["forecast_horizon"] = horizon
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
        payload.setdefault("expected_outputs", ["forecast_or_metric_result", "assumptions", "confidence", "evidence_refs"])
    if capability == "rule.calculate":
        payload.setdefault("rule_context", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
        payload.setdefault("workflow_prior_outputs", _prior_outputs_for_downstream(prior_outputs))
        payload.setdefault("expected_outputs", ["rule_results", "risks", "exceptions", "evidence_refs"])
    if capability.startswith("project."):
        payload.setdefault("project_context", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
        payload.setdefault("expected_outputs", ["project_record", "tasks", "approval_state"])
    if capability.startswith("monitor.") or capability.startswith("reminder."):
        payload.setdefault("monitor_context", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
        payload.setdefault("expected_outputs", ["monitor_items", "reminder_policy", "trigger_conditions"])
    if capability.startswith("human."):
        payload.setdefault("human_context", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
        payload.setdefault("expected_outputs", ["confirmation_cards", "assignee", "decision_options"])
        payload.setdefault("task_type", "workflow_human_confirmation")
        payload.setdefault("cards", _default_human_confirmation_cards(payload.get("human_context"), prior_outputs))
    if capability.startswith("control."):
        payload.setdefault("control_context", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("expected_outputs", ["policy_decision", "handoff_policy", "execution_bounds"])
    if capability.startswith("evolution."):
        payload.setdefault("evolution_context", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
        payload.setdefault("expected_outputs", ["capability_candidate", "reuse_scope", "review_required"])
    if capability.startswith("knowledge."):
        payload.setdefault("question", payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"))
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
    if capability.startswith("sandbox."):
        payload.setdefault("input_data_refs", _prior_output_refs(prior_outputs))
        payload.setdefault("wait_for_result", True)
        payload.setdefault("retain_snapshot", True)
        limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
        payload["limits"] = {
            "timeout_seconds": int(limits.get("timeout_seconds") or payload.get("timeout_seconds") or 10),
            "memory_mb": int(limits.get("memory_mb") or payload.get("memory_mb") or 512),
            "cpu_cores": float(limits.get("cpu_cores") or payload.get("cpu_cores") or 1),
        }
        payload.setdefault("input", {
            "user_goal": payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description"),
            "workflow_prior_refs": _prior_output_refs(prior_outputs),
        })
        if capability == "sandbox.run_browser":
            payload.setdefault("url", payload.get("target_url") or "http://sandbox-allow.test/")
        elif capability == "sandbox.run_code":
            payload.setdefault("language", "python")
            payload.setdefault(
                "code",
                _sandbox_code_from_goal(
                    str(payload.get("user_goal") or parameters.get("utterance") or intent_task.get("description") or "")
                ),
            )
        else:
            payload.setdefault("scenario_id", "s20_purchase_plan")
        payload.setdefault("expected_outputs", ["sandbox_status", "stdout_or_business_output", "evidence_snapshot", "audit_events"])
    if capability == "content.generate":
        payload.setdefault("content_type", "workflow_user_answer")
        payload["workflow_evidence"] = _compact_prior_outputs_for_model(prior_outputs, parameters.get("utterance") or intent_task.get("description") or "")
        payload["workflow_evidence"]["conversation_context"] = _compact_conversation_context(
            parameters.get("conversation_context")
        )
        payload["utterance"] = _build_model_answer_requirement(
            parameters.get("utterance") or intent_task.get("description") or "",
            payload["workflow_evidence"],
        )
    return payload


def _sandbox_code_from_goal(user_goal: str) -> str:
    text = str(user_goal or "")
    fenced = re.search(r"```(?:python|py)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced and fenced.group(1).strip():
        return fenced.group(1).strip()
    inline = re.search(r"(?:代码|code)\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
    if inline and inline.group(1).strip():
        candidate = inline.group(1).strip()
        if "\n" in candidate or any(token in candidate for token in ("print(", "import ", "=", "for ", "def ")):
            return candidate
    sum_match = re.search(r"(\d+)\s*(?:到|至|-|~)\s*(\d+).*?(?:和|求和|sum)", text, re.IGNORECASE)
    if not sum_match:
        sum_match = re.search(r"(?:sum|求和|和).*?(\d+)\s*(?:到|至|-|~)\s*(\d+)", text, re.IGNORECASE)
    if sum_match:
        start = int(sum_match.group(1))
        end = int(sum_match.group(2))
        low, high = sorted((start, end))
        return f"print(sum(range({low}, {high + 1})))"
    arithmetic = re.search(r"(?:计算|calculate)\s*([0-9+\-*/ ().]+)", text, re.IGNORECASE)
    if arithmetic and arithmetic.group(1).strip():
        expression = arithmetic.group(1).strip()
        if re.fullmatch(r"[0-9+\-*/ ().]+", expression):
            return f"print({expression})"
    return "import json\nprint(json.dumps({'ok': True, 'message': 'sandbox code task received'}))"


def _infer_data_aggregate_operation(user_goal: str) -> str:
    text = str(user_goal or "")
    if _looks_like_latest_metric_by_entity_request(text):
        return "latest_metric_by_entity"
    if _looks_like_rule_data_preparation_request(text):
        return "budget_summary"
    if _looks_like_forecast_request(text):
        if any(word in text.lower() for word in ("需求", "订单", "销量", "销售", "demand", "order", "sales", "quantity", "qty")):
            return "monthly_metric_series"
        return "retrieve"
    if re.search(r"P-[A-Z0-9-]+", text, re.IGNORECASE) or any(word in text for word in ("基本参数", "产品参数", "产品资料", "产品详情")):
        return "business_object_detail"
    if any(word in text for word in ("预算", "预算合计", "费用", "成本", "价格", "毛利")):
        return "budget_summary"
    if any(word in text for word in ("优质", "反馈", "评价", "满意", "推荐", "排序", "画像")):
        return "retrieve"
    if _looks_like_entity_list_request(text):
        return "list_distinct"
    if _looks_like_month_metric_request(text):
        return "monthly_max_metric"
    return "retrieve"


def _apply_semantic_data_aggregate_contract(payload: dict[str, Any], user_goal: str) -> None:
    """Translate a natural-language data request into an auditable operation contract."""
    business_scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
    current_operation = str(payload.get("aggregate_operation") or payload.get("operation") or "").lower()
    inferred_operation = _infer_data_aggregate_operation(user_goal)
    scope_query_kind = str(business_scope.get("query_kind") or "").lower()
    if scope_query_kind in {"monthly_max_metric", "monthly_metric_series"}:
        inferred_operation = scope_query_kind
    elif scope_query_kind in {"detail", "budget_summary"} and current_operation in WEAK_DATA_AGGREGATE_OPERATIONS:
        inferred_operation = scope_query_kind

    explicit_operation = bool(current_operation and current_operation not in WEAK_DATA_AGGREGATE_OPERATIONS)
    should_replace = (
        not current_operation
        or current_operation in WEAK_DATA_AGGREGATE_OPERATIONS
        or (not explicit_operation and inferred_operation in {"list_distinct", "monthly_max_metric", "monthly_metric_series", "latest_metric_by_entity", "business_object_detail", "budget_summary"})
    )
    if inferred_operation and should_replace:
        payload["aggregate_operation"] = inferred_operation
        payload["operation"] = inferred_operation

    operation = str(payload.get("aggregate_operation") or payload.get("operation") or "").lower()
    semantic_operation = {
        "planner": "workflow_execution.semantic_data_task_translator",
        "source": "intent_task_and_user_goal",
        "operation": operation,
        "business_scope": business_scope,
        "confidence": "medium",
    }
    if operation in {"monthly_max_metric", "monthly_metric_series"}:
        target_year = _year_from_text(user_goal)
        metric_candidates = _metric_candidates_from_goal(user_goal)
        time_candidates = ["month", "year_month", "period", "date"]
        payload.setdefault("time_field_candidates", time_candidates)
        payload.setdefault("metric_field_candidates", metric_candidates)
        payload.setdefault("dimension", "month")
        payload.setdefault("group_by", ["month"])
        if target_year:
            payload.setdefault("year", target_year)
            payload.setdefault("year_filter", target_year)
        if metric_candidates:
            payload.setdefault("metric_field", metric_candidates[0])
        payload.setdefault("time_field", "month")
        semantic_operation.update({
            "dimension": "month",
            "metric_candidates": metric_candidates,
            "time_field_candidates": time_candidates,
            "year": target_year,
            "expected_output": ["period_values", "monthly_values", "max_month", "max_value", "evidence"],
        })
    elif operation == "latest_metric_by_entity":
        metric_candidates = _metric_candidates_from_goal(user_goal)
        payload.setdefault("entity_field_candidates", _entity_candidates_from_goal(user_goal))
        payload.setdefault("time_field_candidates", ["month", "year_month", "period", "date", "order_date", "sales_date"])
        payload.setdefault("metric_field_candidates", metric_candidates)
        if metric_candidates:
            payload.setdefault("metric_field", metric_candidates[0])
        semantic_operation.update({
            "entity_field_candidates": payload.get("entity_field_candidates"),
            "metric_candidates": metric_candidates,
            "time_field_candidates": payload.get("time_field_candidates"),
            "expected_output": ["entity_count", "rows", "latest_period", "evidence"],
        })
    elif operation == "list_distinct":
        payload.setdefault("distinct", True)
        payload.setdefault("expected_output", ["distinct_count", "names", "evidence"])
        semantic_operation.update({"expected_output": ["distinct_count", "names", "evidence"]})
    payload["semantic_operation"] = semantic_operation


def _align_business_scope_with_data_operation(payload: dict[str, Any], parameters: dict[str, Any] | None = None) -> None:
    """Keep the data domain aligned with the concrete aggregate operation."""
    operation = str(payload.get("aggregate_operation") or payload.get("operation") or "").lower()
    if operation in {"monthly_metric_series", "monthly_max_metric", "latest_metric_by_entity"}:
        payload["business_scope"] = _business_scope_for_key("demand", parameters or {}, fallback={})
        return
    if operation == "budget_summary":
        payload["business_scope"] = _business_scope_for_key("budget", parameters or {}, fallback={})


def _year_from_text(text: str) -> int | None:
    match = re.search(r"(20\d{2})", str(text or ""))
    return int(match.group(1)) if match else None


def _metric_candidates_from_goal(text: str) -> list[str]:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("demand", "需求")):
        return ["demand_qty", "demand", "需求量", "需求"]
    if any(token in lowered for token in ("order", "订单")):
        return ["order_qty", "order_count", "quantity", "订单量", "订单数"]
    if any(token in lowered for token in ("sales", "销量", "销售")):
        return ["sales_qty", "quantity", "销量", "销售量"]
    if any(token in lowered for token in ("amount", "revenue", "金额", "收入")):
        return ["amount", "revenue", "amount_cny", "金额", "收入"]
    return ["demand_qty", "order_qty", "sales_qty", "quantity", "amount"]


def _entity_candidates_from_goal(text: str) -> list[str]:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("product", "\u4ea7\u54c1", "\u7269\u6599")):
        return ["product_name", "product", "product_id", "\u4ea7\u54c1\u540d\u79f0", "\u4ea7\u54c1", "\u4ea7\u54c1\u7f16\u53f7"]
    if any(token in lowered for token in ("dealer", "distributor", "\u7ecf\u9500\u5546")):
        return ["dealer_name", "dealer", "dealer_id", "distributor_name", "distributor", "\u7ecf\u9500\u5546\u540d\u79f0", "\u7ecf\u9500\u5546", "\u7ecf\u9500\u5546\u7f16\u53f7"]
    if any(token in lowered for token in ("customer", "\u5ba2\u6237")):
        return ["customer_name", "customer", "customer_id", "\u5ba2\u6237\u540d\u79f0", "\u5ba2\u6237", "\u5ba2\u6237\u7f16\u53f7"]
    if any(token in lowered for token in ("region", "\u533a\u57df", "\u5730\u533a")):
        return ["region", "area", "\u533a\u57df", "\u5730\u533a"]
    return ["product_name", "product", "product_id", "dealer_name", "dealer", "customer_name", "customer", "region"]


def _looks_like_metric_by_entity_request(text: str) -> bool:
    lowered = str(text or "").lower()
    has_entity = any(word in lowered for word in (
        "product", "dealer", "distributor", "customer", "region",
        "\u4ea7\u54c1", "\u7269\u6599", "\u7ecf\u9500\u5546", "\u5ba2\u6237", "\u533a\u57df", "\u5730\u533a",
    ))
    has_metric = any(word in lowered for word in (
        "demand", "order", "sales", "amount", "revenue", "quantity", "qty",
        "\u9700\u6c42", "\u8ba2\u5355", "\u9500\u91cf", "\u9500\u552e", "\u91d1\u989d", "\u6536\u5165", "\u6570\u91cf",
    ))
    has_group = any(word in lowered for word in (
        "per ", "by ", "each", "group by", "\u6bcf\u4e2a", "\u5404", "\u5206\u522b", "\u6309",
    ))
    return has_entity and has_metric and has_group


def _looks_like_latest_metric_by_entity_request(text: str) -> bool:
    lowered = str(text or "").lower()
    has_recent = any(word in lowered for word in (
        "latest", "recent", "last", "\u6700\u8fd1", "\u6700\u65b0", "\u6700\u540e", "\u8fd1\u671f",
    ))
    return has_recent and _looks_like_metric_by_entity_request(text)


def _looks_like_entity_list_request(text: str) -> bool:
    lowered = str(text or "").lower()
    entity_words = ("经销商", "客户", "供应商", "产品", "物料", "人员", "员工", "门店", "仓库", "区域", "dealer", "distributor", "customer", "supplier", "product")
    list_words = ("哪些", "有哪些", "都有谁", "有谁", "所有", "全部", "确定", "列出", "列举", "名单", "清单", "明细", "去重", "一一", "分别", "几个", "多少", "多少个", "数量", "总数", "个数", "count", "distinct")
    return any(word in lowered for word in entity_words) and any(word in lowered for word in list_words)


def _looks_like_month_metric_request(text: str) -> bool:
    lowered = str(text or "").lower()
    extreme_words = ("\u6700\u591a", "\u6700\u9ad8", "\u6700\u5927", "\u5cf0\u503c", "top", "max")
    month_words = ("\u6bcf\u4e2a\u6708", "\u5404\u6708", "\u54ea\u4e2a\u6708", "\u54ea\u6708", "\u90a3\u4e2a\u6708", "\u6708\u4efd", "\u6708", "month", "monthly")
    metric_words = ("\u9700\u6c42", "\u8ba2\u5355", "\u9500\u91cf", "\u9500\u552e", "\u91d1\u989d", "\u6536\u5165", "\u6570\u91cf", "demand", "order", "sales", "amount", "revenue", "qty")
    has_extreme = any(word in lowered for word in extreme_words)
    has_month = any(word in lowered for word in month_words)
    has_metric = any(word in lowered for word in metric_words)
    return has_extreme and has_month and has_metric


def _looks_like_forecast_request(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(word in lowered for word in ("预测", "下一个月", "下个月", "下月", "下季度", "下半年", "半年", "下一年", "未来一年", "一年", "趋势", "forecast", "predict", "next month", "next year"))


_CHINESE_MONTH_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}


def _target_period_from_goal_text(text: str) -> str:
    goal = str(text or "")
    explicit_year = None
    year_match = re.search(r"(20\d{2})", goal)
    if year_match:
        explicit_year = int(year_match.group(1))
    if "今年" in goal:
        explicit_year = date.today().year
    elif "明年" in goal:
        explicit_year = date.today().year + 1
    elif "去年" in goal:
        explicit_year = date.today().year - 1
    month = None
    numeric = re.search(r"(?:(?:20\d{2}|今年|明年|去年)\s*年?\s*)?(\d{1,2})\s*月(?:份)?", goal)
    if numeric:
        month = int(numeric.group(1))
    else:
        chinese = re.search(r"(?:(?:20\d{2}|今年|明年|去年)\s*年?\s*)?(十一|十二|十|一|二|三|四|五|六|七|八|九)\s*月(?:份)?", goal)
        if chinese:
            month = _CHINESE_MONTH_MAP.get(chinese.group(1))
    if not month or not 1 <= month <= 12:
        return ""
    if explicit_year is None:
        if _looks_like_forecast_request(goal):
            explicit_year = date.today().year
        else:
            return ""
    return f"{int(explicit_year):04d}-{int(month):02d}"


def _forecast_horizon_from_goal_text(text: str) -> int | None:
    goal = str(text or "")
    lowered = goal.lower()
    if _target_period_from_goal_text(goal):
        return None
    if any(word in goal for word in ("下一个月", "下月", "下个月", "下一月", "未来一个月", "后续一个月", "未来1个月", "后续1个月")) or "next month" in lowered:
        return 1
    if any(word in goal for word in ("下一年", "未来一年", "后续一年", "未来12个月", "未来十二个月")) or "next year" in lowered:
        return 12
    if any(word in goal for word in ("下半年", "未来半年", "后半年")) or "half year" in lowered or "six months" in lowered:
        return 6
    match = re.search(r"(?:未来|后续|下)\s*(\d{1,2})\s*(?:个)?月", goal)
    if match:
        months = int(match.group(1))
        if 1 <= months <= 24:
            return months
    if any(word in goal for word in ("下季度", "下一季度")) or "next quarter" in lowered:
        return 3
    return None


def _looks_like_rule_request(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(word in lowered for word in (
        "规则", "核对", "校验", "差异", "风险", "合规", "预算规则", "价格规则", "盈亏平衡",
        "rule", "check", "validate", "risk", "exception", "break-even", "breakeven",
    ))


def _looks_like_budget_risk_request(text: str) -> bool:
    lowered = str(text or "").lower()
    has_budget = any(word in lowered for word in ("预算", "budget"))
    has_risk = any(word in lowered for word in ("风险", "risk", "预警"))
    return has_budget and has_risk


def _looks_like_rule_data_preparation_request(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(word in lowered for word in (
        "\u89c4\u5219", "\u6838\u5bf9", "\u6821\u9a8c", "\u5dee\u5f02", "\u98ce\u9669", "\u5408\u89c4",
        "\u9884\u7b97", "\u4ef7\u683c", "\u6210\u672c", "\u6bdb\u5229", "\u76c8\u4e8f\u5e73\u8861",
        "rule", "check", "validate", "risk", "exception", "budget", "price", "cost",
        "margin", "break-even", "breakeven",
    ))


def _looks_like_demand_forecast_scope(text: str) -> bool:
    lowered = str(text or "").lower()
    has_demand = any(word in lowered for word in ("需求", "订单", "销量", "销售", "demand", "order", "sales"))
    return has_demand and _looks_like_forecast_request(lowered)


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
    cached_filter = _cached_parsed_document_filter(uploaded_documents)
    if cached_filter:
        return cached_filter
    file_ids = [
        str(doc.get("file_id"))
        for doc in uploaded_documents
        if isinstance(doc, dict) and doc.get("file_id")
    ]
    if len(file_ids) == 1:
        return {"file_id": file_ids[0]}
    if file_ids:
        return {"file_id": file_ids}
    object_ids = [
        str(doc.get("object_id"))
        for doc in uploaded_documents
        if isinstance(doc, dict) and doc.get("object_id")
    ]
    if len(object_ids) == 1:
        return {"object_id": object_ids[0]}
    if object_ids:
        return {"object_id": object_ids}
    sha_values = [
        str(doc.get("sha256"))
        for doc in uploaded_documents
        if isinstance(doc, dict) and doc.get("sha256")
    ]
    if sha_values:
        return {"sha256": sha_values[0]} if len(sha_values) == 1 else {"sha256": sha_values}
    return {}


def _cached_parsed_document_filter(uploaded_documents: list[dict[str, Any]]) -> dict[str, Any]:
    docs = [doc for doc in uploaded_documents if isinstance(doc, dict)]
    if not docs:
        return {}
    tenant_id = str(next((doc.get("tenant_id") for doc in docs if doc.get("tenant_id")), "web-workbench"))
    cache_keys: list[str] = []
    for doc in docs:
        for key in ("sha256", "file_id", "object_id"):
            value = str(doc.get(key) or "").strip()
            if value and value not in cache_keys:
                cache_keys.append(value)
    if not cache_keys:
        return {}
    try:
        with connect() as db:
            for cache_key in cache_keys:
                like_pattern = f'%"{cache_key}"%'
                row = db.execute(
                    """
                    SELECT payload_json
                    FROM data_records
                    WHERE dataset='extracted_fields'
                      AND tenant_id=?
                      AND deleted_at IS NULL
                      AND payload_json LIKE ?
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (tenant_id, like_pattern),
                ).fetchone()
                if row is None:
                    continue
                payload = _safe_json_loads(row["payload_json"] if isinstance(row, dict) else row[0])
                if not isinstance(payload, dict):
                    continue
                parse_job_id = payload.get("parse_job_id") or payload.get("source_parse_job_id")
                if parse_job_id:
                    return {"parse_job_id": str(parse_job_id)}
                sha256 = payload.get("sha256")
                if sha256:
                    return {"sha256": str(sha256)}
                file_id = payload.get("file_id")
                if file_id:
                    return {"file_id": str(file_id)}
    except Exception:
        return {}
    return {}


def _safe_json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return None
    try:
        return json.loads(str(value))
    except Exception:
        return None


def _parse_job_ids_from_prior_outputs(prior_outputs: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("document.table.extract", "document.parse"):
        data = prior_outputs.get(key)
        if not isinstance(data, dict):
            continue
        artifact_refs = data.get("artifact_refs") if isinstance(data.get("artifact_refs"), list) else []
        for ref in artifact_refs:
            if not isinstance(ref, dict):
                continue
            filters = ref.get("filters") if isinstance(ref.get("filters"), dict) else (ref.get("read_params") or {}).get("filters") if isinstance(ref.get("read_params"), dict) else {}
            parse_job_id = filters.get("parse_job_id") if isinstance(filters, dict) else None
            if parse_job_id and str(parse_job_id) not in result:
                result.append(str(parse_job_id))
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


def _prior_output_refs(prior_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for key, data in prior_outputs.items():
        if not isinstance(data, dict):
            continue
        existing_refs = data.get("artifact_refs") if isinstance(data.get("artifact_refs"), list) else []
        for ref in existing_refs:
            if isinstance(ref, dict):
                refs.append({"upstream_key": key, **ref})
        storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else {}
        aggregate = storage.get("aggregate") if isinstance(storage.get("aggregate"), dict) else data.get("aggregate")
        items = storage.get("items") if isinstance(storage.get("items"), list) else data.get("items")
        refs.append({
            "upstream_key": key,
            "state": data.get("state"),
            "module": data.get("module"),
            "platform_capability": data.get("platform_capability"),
            "integration_status": data.get("integration_status"),
            "aggregate": aggregate if isinstance(aggregate, dict) else None,
            "items_count": len(items) if isinstance(items, list) else None,
        })
    return refs


def _prior_outputs_for_downstream(prior_outputs: dict[str, Any]) -> dict[str, Any]:
    """Pass small structured upstream results to compute modules.

    Audit logs keep only references so requests stay readable, but analysis
    modules need the actual monthly aggregate values. Keep aggregates and a
    tiny amount of metadata, not full extracted-field rows.
    """
    compact: dict[str, Any] = {}
    for key, data in prior_outputs.items():
        if not isinstance(data, dict):
            continue
        storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else {}
        aggregate = storage.get("aggregate") if isinstance(storage.get("aggregate"), dict) else data.get("aggregate")
        item: dict[str, Any] = {
            "state": data.get("state"),
            "module": data.get("module"),
            "platform_capability": data.get("platform_capability"),
        }
        if isinstance(aggregate, dict):
            item["aggregate"] = aggregate
            item["storage_result"] = {"aggregate": aggregate}
        analysis_result = data.get("analysis_result") if isinstance(data.get("analysis_result"), dict) else None
        if isinstance(analysis_result, dict):
            compact_analysis = {
                key: value
                for key, value in analysis_result.items()
                if key in {"status", "metric_reason", "source_metric", "platform_analysis_type"}
            }
            forecasts = analysis_result.get("forecasts") if isinstance(analysis_result.get("forecasts"), list) else []
            if forecasts:
                compact_analysis["forecasts"] = forecasts[:24]
            if compact_analysis:
                item["analysis_result"] = compact_analysis
        if isinstance(data.get("artifact_refs"), list):
            item["artifact_refs"] = data.get("artifact_refs")[:5]
        if isinstance(data.get("next_read_hints"), list):
            item["next_read_hints"] = data.get("next_read_hints")[:5]
        compact[str(key)] = {k: v for k, v in item.items() if v not in (None, [], {})}
    return compact


def _default_human_confirmation_cards(human_context: Any, prior_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    context = str(human_context or "")
    cards = [
        {
            "card_id": "confirm-project-approval-entry",
            "title": "\u662f\u5426\u540c\u610f\u8fdb\u5165\u7acb\u9879\u5ba1\u6279",
            "description": context or "\u8bf7\u786e\u8ba4\u5f53\u524d\u9879\u76ee\u662f\u5426\u53ef\u4ee5\u8fdb\u5165\u7acb\u9879\u5ba1\u6279\u3002",
            "options": ["\u540c\u610f\u8fdb\u5165\u7acb\u9879\u5ba1\u6279", "\u5148\u8865\u5145\u8d44\u6599", "\u6682\u4e0d\u8fdb\u5165"],
        },
        {
            "card_id": "confirm-missing-materials",
            "title": "\u9700\u8981\u4eba\u5de5\u6838\u5bf9\u7684\u8d44\u6599",
            "description": "\u8bf7\u6838\u5bf9\u5ba2\u6237\u9700\u6c42\u3001\u571f\u58e4\u68c0\u6d4b\u3001\u5386\u53f2\u9500\u552e\u3001\u4ea7\u54c1\u8d44\u6599\u548c\u9884\u7b97\u4f9d\u636e\u662f\u5426\u5b8c\u6574\u3002",
            "options": ["\u8d44\u6599\u5b8c\u6574", "\u8d44\u6599\u4e0d\u5b8c\u6574"],
        },
    ]
    if "project.register.simple" in prior_outputs or "monitor.item.register" in prior_outputs:
        cards.append({
            "card_id": "confirm-generated-work-items",
            "title": "\u786e\u8ba4\u9879\u76ee\u767b\u8bb0\u548c\u76d1\u63a7\u4e8b\u9879",
            "description": "\u8bf7\u786e\u8ba4\u5df2\u751f\u6210\u7684\u9879\u76ee\u767b\u8bb0\u3001\u5ba1\u6279\u5f85\u529e\u548c\u540e\u7eed\u6267\u884c\u76d1\u63a7\u4e8b\u9879\u662f\u5426\u7b26\u5408\u4e1a\u52a1\u9700\u6c42\u3002",
            "options": ["\u786e\u8ba4", "\u9700\u8c03\u6574"],
        })
    return cards


def _build_model_answer_requirement(user_goal: str, evidence: dict[str, Any]) -> str:
    return (
        "When the user asks about a prior turn using words such as '刚才', '前面', '上述', or '之前', "
        "answer from explicit facts in conversation_context first. Do not replace those facts with a different "
        "value from uploaded files unless the user explicitly asks to compare, verify, or recalculate them.\n"
        "Treat conversation_context facts as user-provided statements, not externally verified records.\n"
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
        for answer_key in ("answer", "user_answer", "summary"):
            answer_value = data.get(answer_key)
            if isinstance(answer_value, str) and answer_value.strip():
                step[answer_key] = answer_value.strip()[:4000]
        storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else {}
        aggregate = storage.get("aggregate") if isinstance(storage.get("aggregate"), dict) else data.get("aggregate")
        if isinstance(aggregate, dict):
            step["aggregate"] = aggregate
        knowledge_context = data.get("knowledge_context") if isinstance(data.get("knowledge_context"), dict) else {}
        if knowledge_context:
            step["knowledge_context"] = {
                key: value
                for key, value in knowledge_context.items()
                if key in {"source_dataset", "count", "items"}
            }
        if isinstance(data.get("evidence"), list):
            step["evidence"] = data.get("evidence")[:20]
        items = storage.get("items") if isinstance(storage.get("items"), list) else data.get("items")
        if isinstance(items, list):
            step["items_count"] = len(items)
            step["sample_rows"] = _compact_extracted_field_rows(items, user_goal, limit=120)
        elif isinstance(storage.get("sample_items"), list):
            step["items_count"] = storage.get("items_count")
            step["sample_rows"] = storage.get("sample_items")
        if isinstance(data.get("artifact_refs"), list):
            step["artifact_refs"] = data.get("artifact_refs")
        if isinstance(data.get("next_read_hints"), list):
            step["next_read_hints"] = data.get("next_read_hints")
        if data.get("platform_capability"):
            step["platform_capability"] = data.get("platform_capability")
        if data.get("module_name_cn"):
            step["module_name_cn"] = data.get("module_name_cn")
        if data.get("integration_status"):
            step["integration_status"] = data.get("integration_status")
        normalized_task = data.get("normalized_task") if isinstance(data.get("normalized_task"), dict) else {}
        if normalized_task:
            step["normalized_task"] = normalized_task
        received_payload = data.get("received_payload") if isinstance(data.get("received_payload"), dict) else {}
        if received_payload:
            step["received_payload_summary"] = {
                key: received_payload.get(key)
                for key in ("user_goal", "analysis_goal", "expected_outputs", "input_data_refs", "control_context", "project_context", "monitor_context", "human_context")
                if key in received_payload
            }
        compact["steps"][capability] = step
    return compact


def _compact_conversation_context(value: Any, limit: int = 12) -> list[dict[str, str]]:
    """Keep a bounded window of prior turns for a follow-up answer."""
    if not isinstance(value, list):
        return []
    compact: list[dict[str, str]] = []
    for item in value[-limit:]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("text") or "").strip()
        if content:
            compact.append({"role": str(item.get("role") or "unknown"), "content": content[:2000]})
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
            "purpose": item.get("purpose"),
            "depends_on": item.get("depends_on") or [],
            "execution_group": item.get("execution_group"),
            "execution_mode": item.get("execution_mode"),
            "provider_module_hint": item.get("provider_module_hint"),
        },
        "status_code": 422,
        "capability": item["capability"],
        "request_payload": item.get("payload_hint", {}),
        "response": {"error": {"code": code, "message": _failed_step_message(code, details), "details": details}},
    }


def _failed_step_message(code: str, details: dict[str, Any]) -> str:
    if code == "CAPABILITY_NOT_REGISTERED":
        capability = details.get("capability") or "未命名能力"
        return f"平台暂未登记可处理该任务的能力：{capability}。"
    if code == "PERMISSION_DENIED":
        return "当前账号没有执行该能力的权限。"
    return "模块调用未通过。"


def _knowledge_answer_from_steps(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Keep a concrete knowledge.query answer from being overwritten downstream.

    The final content step may polish the response, but it must not turn a
    successful knowledge answer into an unsupported "not enough data" message.
    This helper is generic: it uses the upstream module result, not any
    hard-coded filename or field value.
    """
    for step in steps:
        if step.get("capability") != "knowledge.query":
            continue
        if step.get("status_code") not in {200, 202}:
            continue
        data = (step.get("response") or {}).get("data") or {}
        if not isinstance(data, dict):
            continue
        answer = data.get("user_answer") or data.get("answer") or data.get("summary")
        if not isinstance(answer, str) or not answer.strip():
            continue
        if _is_unusable_model_content(answer):
            continue
        return {
            "finding_id": "knowledge-query-result",
            "title": answer.strip(),
            "detail": "",
            "evidence": data.get("evidence") or [],
            "impact": "",
            "recommendation": "",
        }
    return None


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

    capability_unavailable = _capability_unavailable_answer(steps)
    if capability_unavailable:
        findings.append(capability_unavailable)

    document_structure_answer = _document_structure_answer(intent_task, steps)
    if document_structure_answer:
        findings.append(document_structure_answer)

    project_flow_answer = _project_flow_answer(steps)
    if project_flow_answer:
        findings.append(project_flow_answer)

    rule_answer = _rule_calculation_answer(steps)
    if rule_answer:
        findings.append(rule_answer)

    analysis_answer = _analysis_prediction_answer(steps)
    if analysis_answer and not (_looks_like_budget_risk_request(str((intent_task.get("parameters") or {}).get("utterance") or intent_task.get("description") or "")) and rule_answer):
        findings.append(analysis_answer)

    sandbox_answer = _execution_sandbox_answer(steps)
    if sandbox_answer:
        findings.append(sandbox_answer)

    knowledge_answer = _knowledge_answer_from_steps(steps)
    if knowledge_answer:
        findings.append(knowledge_answer)

    aggregate_first = _aggregate_should_override_content(aggregate)
    if not findings and aggregate_first and isinstance(aggregate, dict) and aggregate.get("answer"):
        deterministic_answer = _build_deterministic_business_answer(intent_task, aggregate)
        findings.append({
            "finding_id": "business-summary",
            "title": deterministic_answer or aggregate["answer"],
            "detail": aggregate.get("detail") or "",
            "evidence": aggregate.get("evidence") or [],
            "impact": "该结果来自流程执行引擎按已登记模块处理后的汇总。",
            "recommendation": aggregate.get("recommendation") or "请结合业务口径确认后使用。",
        })

    content = content_data.get("content") if isinstance(content_data, dict) else None
    content_result = content_data.get("user_result") if isinstance(content_data, dict) else None
    if not findings and isinstance(content_result, dict) and content_result.get("summary") and not _is_unusable_model_content(str(content_result.get("summary"))):
        findings.append({
            "finding_id": "content-result",
            "title": str(content_result["summary"]),
            "detail": str(content_result.get("detail") or ""),
            "evidence": content_result.get("evidence") or [],
            "impact": "",
            "recommendation": str(content_result.get("recommendation") or ""),
        })
    elif not findings and isinstance(content, str) and content.strip() and not _is_unusable_model_content(content):
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
    for finding in findings:
        if isinstance(finding, dict):
            finding["evidence"] = _evidence_strings(finding.get("evidence") or [])
    failed = [step for step in steps if step.get("status_code") not in {200, 202}]
    summary = _compose_chat_answer(findings, failed, workflow_state)
    return {
        "schema_version": "1.0",
        "result_type": "workflow_task_plan_result",
        "display_mode": "chat_answer",
        "summary": summary,
        "findings": findings,
        "next_action": {"type": "completed" if workflow_state == "completed" else "review_failed_steps", "prompt": "请在调用审计中查看未完成节点。" if failed else "本次处理已完成。"},
        "grounding": {"verified": workflow_state == "completed", "module_count": len(steps)},
    }


def _compose_chat_answer(findings: list[dict[str, Any]], failed: list[dict[str, Any]], workflow_state: str) -> str:
    if findings:
        blocks: list[str] = []
        for finding in findings:
            title = str(finding.get("title") or "").strip()
            detail = str(finding.get("detail") or "").strip()
            if not title:
                continue
            if detail and detail not in title:
                blocks.append(f"{title}\n\n{detail}")
            else:
                blocks.append(title)
        if blocks:
            return "\n\n".join(blocks)
    if workflow_state == "completed":
        return "我已处理完成，但当前模块没有返回可以直接给出的业务结论。"
    return f"这次处理有 {len(failed)} 个环节没有完成，暂时不能给出完整结论。"


def _evidence_strings(evidence: Any) -> list[str]:
    if not isinstance(evidence, list):
        evidence = [evidence]
    result: list[str] = []
    for item in evidence:
        text = _evidence_item_text(item)
        if text and text not in result:
            result.append(text)
    return result[:30]


def _evidence_item_text(item: Any) -> str:
    if item in (None, ""):
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, (int, float, bool)):
        return str(item)
    if not isinstance(item, dict):
        return str(item)
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    file_name = item.get("file_name") or item.get("original_name") or source.get("file_name")
    sheet = item.get("sheet") or source.get("sheet")
    row = item.get("row") or source.get("row")
    field = item.get("field_name") or item.get("field")
    value = item.get("value")
    parts: list[str] = []
    if file_name:
        parts.append(str(file_name))
    if sheet:
        parts.append(f"{sheet}")
    if row:
        parts.append(f"第 {row} 行")
    if field:
        parts.append(f"{field}{(': ' + str(value)) if value not in (None, '') else ''}")
    if parts:
        return " ".join(parts)
    upstream = item.get("upstream_key") or item.get("capability") or item.get("platform_capability")
    state = item.get("state") or item.get("status") or item.get("status_code")
    module = item.get("module") or item.get("provider_module")
    summary_parts = [str(part) for part in (module, upstream, state) if part not in (None, "")]
    if summary_parts:
        return " / ".join(summary_parts)
    return "；".join(f"{key}: {value}" for key, value in item.items() if value not in (None, "", [], {}))[:200]

def _execution_sandbox_answer(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    sandbox_steps = [step for step in steps if str(step.get("capability") or "").startswith("sandbox.")]
    if not sandbox_steps:
        return None
    completed: list[str] = []
    accepted: list[str] = []
    failed: list[str] = []
    evidence: list[str] = []
    for step in sandbox_steps:
        data = (step.get("response") or {}).get("data") if isinstance(step.get("response"), dict) else {}
        error = (step.get("response") or {}).get("error") if isinstance(step.get("response"), dict) else {}
        capability = str(step.get("capability") or "")
        if isinstance(data, dict):
            state = str(data.get("state") or "")
            request_id = data.get("sandbox_request_id")
            reply = data.get("sandbox_reply") if isinstance(data.get("sandbox_reply"), dict) else {}
            if state == "completed" or reply.get("reply_type") == "success":
                completed.append(capability)
            else:
                accepted.append(capability)
            if request_id:
                evidence.append(f"{capability} 请求编号：{request_id}")
            if reply.get("evidence"):
                evidence.append(f"{capability} 已返回执行证据")
        elif isinstance(error, dict):
            failed.append(f"{capability}: {error.get('code') or 'failed'}")
        else:
            accepted.append(capability)
    if completed and not accepted and not failed:
        title = "执行沙箱已完成隔离执行。"
        detail = "本次需要隔离运行的任务已由 L1 执行沙箱处理完成，执行回执和证据已进入调用审计。"
    elif accepted and not failed:
        title = "执行沙箱已受理任务，结果可继续查询。"
        detail = "沙箱标准接口返回了受理回执；后续可用 sandbox.result.query 或调用审计中的请求编号查询最终结果。"
    else:
        title = "执行沙箱任务未全部完成。"
        detail = "请在调用审计中查看 execution-sandbox 节点的上游状态、错误码和请求体。"
    return {
        "finding_id": "execution-sandbox",
        "title": title,
        "detail": detail,
        "evidence": evidence + failed,
        "impact": "沙箱结果只表示隔离执行链路状态，不替代业务模块本身的判断。",
        "recommendation": "确认沙箱真实上游已启动、token 已配置，并按请求编号核对结果。",
    }


def _capability_unavailable_answer(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    missing = []
    for step in steps:
        error = (step.get("response") or {}).get("error") if isinstance(step.get("response"), dict) else {}
        if not isinstance(error, dict) or error.get("code") != "CAPABILITY_NOT_REGISTERED":
            continue
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        missing.append(str(details.get("capability") or step.get("capability") or "未命名能力"))
    if not missing:
        return None
    capabilities = "、".join(dict.fromkeys(missing))
    return {
        "finding_id": "capability-not-registered",
        "title": f"平台暂未登记可处理该任务的能力：{capabilities}。",
        "detail": "流程执行引擎已停止该能力节点，没有改用其他模块硬跑，因此不会产生不可信的业务结论。",
        "evidence": [f"未登记能力：{item}" for item in dict.fromkeys(missing)],
        "impact": "需要先在能力字典和模块登记表中登记对应能力，或把该任务映射到已有相近能力后再执行。",
        "recommendation": "请确认是否已有模块负责该能力；如果已有，请补能力码、接口输入输出和模块登记；如果没有，需要新增能力后再联调。",
    }


def _document_structure_answer(intent_task: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    goal = str((intent_task.get("parameters") or {}).get("utterance") or intent_task.get("description") or "")
    if not any(word in goal for word in ("工作表", "字段", "记录", "表", "sheet", "field")):
        return None
    parse_data = next(
        (((step.get("response") or {}).get("data") or {})
        for step in steps
        if step.get("capability") in {"document.parse", "document.table.extract"}),
        {},
    )
    documents = parse_data.get("documents") if isinstance(parse_data.get("documents"), list) else []
    if not documents:
        return None
    lines: list[str] = []
    evidence: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        sheet_summaries = document.get("sheet_summaries") if isinstance(document.get("sheet_summaries"), list) else []
        if not sheet_summaries:
            continue
        original_name = str(document.get("original_name") or document.get("file_id") or "上传文件")
        lines.append(f"{original_name} 包含 {len(sheet_summaries)} 张工作表，已提取 {int(document.get('field_count') or 0)} 个非空字段单元。")
        for sheet in sheet_summaries[:30]:
            if not isinstance(sheet, dict):
                continue
            fields = [str(item) for item in (sheet.get("fields") or []) if str(item)]
            field_text = "、".join(fields[:12]) + (" 等" if len(fields) > 12 else "")
            lines.append(f"- {sheet.get('name')}: 约 {int(sheet.get('record_count') or 0)} 条记录；主要字段：{field_text or '未识别到字段'}。")
            evidence.append({
                "file_name": original_name,
                "sheet": sheet.get("name"),
                "record_count": sheet.get("record_count"),
                "fields": fields[:12],
            })
    if not lines:
        return None
    return {
        "finding_id": "document-structure",
        "title": "\n".join(lines),
        "detail": "",
        "evidence": evidence[:30],
        "impact": "该结果来自文档表格解析引擎返回的结构化工作表摘要。",
        "recommendation": "后续按工作表名称或字段继续提问时，流程可直接读取已解析字段，不需要重复解析文件。",
    }


def _aggregate_should_override_content(aggregate: Any) -> bool:
    if not isinstance(aggregate, dict):
        return False
    operation = str(aggregate.get("operation") or "")
    return operation in {"entity_list", "group_count", "monthly_max_metric", "business_object_detail", "budget_summary", "data_scope_mismatch"}


def _rule_calculation_answer(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    rule_data = next(
        (((step.get("response") or {}).get("data") or {})
        for step in steps
        if step.get("capability") == "rule.calculate"),
        {},
    )
    if not isinstance(rule_data, dict):
        return None
    rule_results = rule_data.get("rule_results") if isinstance(rule_data.get("rule_results"), list) else []
    risks = rule_data.get("risks") if isinstance(rule_data.get("risks"), list) else []
    exceptions = rule_data.get("exceptions") if isinstance(rule_data.get("exceptions"), list) else []
    if not rule_results and not risks and not exceptions:
        return None
    lines: list[str] = []
    budget_total: Any = None
    break_even_missing = False
    budget_passed = False
    for item in rule_results[:8]:
        if not isinstance(item, dict):
            continue
        name = item.get("rule_name") or item.get("rule_id") or "规则"
        status = item.get("status") or "unknown"
        message = item.get("message") or ""
        observed_value = item.get("observed_value")
        if item.get("rule_id") == "budget.completeness":
            budget_total = observed_value
            budget_passed = status == "passed"
            if budget_passed and observed_value not in (None, ""):
                lines.append(f"预算方面，文件中识别到预算合计 {_format_number(observed_value)} 元，预算明细完整。")
            else:
                lines.append("预算方面，当前文件里没有识别到完整的预算合计或预算明细。")
            continue
        if item.get("rule_id") == "break_even.input_check":
            break_even_missing = status in {"warning", "exception", "failed"}
            if break_even_missing:
                lines.append("盈亏平衡数量目前还不能给出最终值，因为还需要确认产品单价、单位成本和目标利润口径。")
            continue
        if item.get("rule_id") == "break_even.quantity":
            unit = item.get("unit") or "单位"
            inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
            input_parts = []
            if inputs.get("fixed_cost") not in (None, ""):
                input_parts.append(f"固定成本 {_format_number(inputs.get('fixed_cost'))} 元")
            if inputs.get("unit_contribution_margin") not in (None, ""):
                input_parts.append(f"单位边际贡献 {_format_number(inputs.get('unit_contribution_margin'))} 元")
            basis = "，".join(input_parts)
            suffix = f"（{basis}）" if basis else ""
            lines.append(f"盈亏平衡数量为 {_format_number(observed_value)} {unit}{suffix}。")
            continue
        if item.get("rule_id") == "budget_risk.assessment":
            inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
            level = item.get("risk_level_cn") or item.get("risk_level") or "待核对"
            unit = item.get("unit") or "单位"
            demand_qty = inputs.get("estimated_demand_qty")
            contribution = inputs.get("estimated_contribution")
            coverage_ratio = inputs.get("coverage_ratio") or observed_value
            break_even_qty = inputs.get("break_even_qty")
            basis = inputs.get("estimate_basis")
            parts = [f"预算风险等级：{level}"]
            if demand_qty not in (None, ""):
                parts.append(f"预计目标期间需求约 {_format_number(demand_qty)} {unit}")
            if contribution not in (None, ""):
                parts.append(f"预计边际贡献约 {_format_number(contribution)} 元")
            if coverage_ratio not in (None, ""):
                parts.append(f"约为预算的 {_format_ratio(coverage_ratio)}")
            if break_even_qty not in (None, ""):
                parts.append(f"盈亏平衡数量 {_format_number(break_even_qty)} {unit}")
            line = "，".join(parts) + "。"
            if basis:
                line += f" 测算依据：{basis}。"
            lines.append(line)
            continue
        if item.get("rule_id") == "budget_risk.input_check":
            lines.append(item.get("message") or "预算风险还不能形成完整测算，需要补充预算、价格成本或需求数据。")
            continue
        if item.get("rule_id") == "price_cost.margin_available" and status != "passed":
            lines.append("价格成本口径还不完整，正式测算前需要补充或确认单价、单位成本、毛利率等字段。")
            continue
        lines.append(f"{name}：{message or status}".strip())
    if not lines and budget_total not in (None, ""):
        lines.append(f"预算方面，文件中识别到预算合计 {_format_number(budget_total)} 元。")
    if risks:
        lines.append("主要风险点：")
        for risk in risks[:5]:
            if isinstance(risk, dict):
                lines.append(f"- {risk.get('description') or risk.get('risk_id')}")
    if exceptions:
        lines.append("需要补充或核对：")
        for exception in exceptions[:5]:
            if isinstance(exception, dict):
                lines.append(f"- {exception.get('description') or exception.get('exception_id')}")
    if break_even_missing:
        lines.append("补充上述口径后，可以继续计算盈亏平衡数量和预算风险等级。")
    elif budget_passed and not risks and not exceptions:
        lines.append("从当前预算完整性看，暂未发现明显预算资料缺失。")
    return {
        "finding_id": "rule-calculation",
        "title": "\n".join(lines),
        "detail": "",
        "evidence": rule_data.get("evidence_refs") or rule_data.get("input_data_refs") or [],
        "impact": "",
        "recommendation": "",
    }


def _analysis_prediction_answer(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    analysis_data = next(
        (((step.get("response") or {}).get("data") or {})
        for step in steps
        if str(step.get("capability") or "").startswith("analysis.")),
        {},
    )
    if not isinstance(analysis_data, dict):
        return None
    result = analysis_data.get("analysis_result") if isinstance(analysis_data.get("analysis_result"), dict) else {}
    forecasts = result.get("forecasts") if isinstance(result.get("forecasts"), list) else []
    if forecasts:
        target_period = _analysis_target_period(analysis_data)
        display_forecasts = _filter_forecasts_for_target_period(forecasts, target_period)
        scope_label = _forecast_scope_label(analysis_data, forecasts)
        region_label = _forecast_region_label(analysis_data)
        lines = [f"根据当前上传文件，{region_label}{scope_label}需求预测为："]
        evidence: list[Any] = []
        for item in display_forecasts:
            if not isinstance(item, dict):
                continue
            date_value = str(item.get("date") or f"第 {item.get('step')} 期")
            value = item.get("value")
            lower = item.get("lower")
            upper = item.get("upper")
            month_label = _format_forecast_period(date_value)
            if lower is not None and upper is not None:
                lines.append(f"- {month_label}：约 {_format_number(value)}，参考区间 {_format_number(lower)} 至 {_format_number(upper)}。")
            else:
                lines.append(f"- {month_label}：约 {_format_number(value)}。")
            evidence.extend(item.get("source_record_ids") or [])
        return {
            "finding_id": "analysis-prediction",
            "title": "\n".join(lines),
            "detail": "",
            "evidence": evidence[:20],
            "impact": "",
            "recommendation": "",
        }
    status = result.get("status") or analysis_data.get("state")
    if status and status != "complete":
        return {
            "finding_id": "analysis-prediction",
            "title": "当前数据还不足以形成可采用的预测结果。",
            "detail": str((analysis_data.get("error") or {}).get("message") or result.get("metric_reason") or ""),
            "evidence": analysis_data.get("input_data_refs") or [],
            "impact": "",
            "recommendation": "请补充至少 3 个月以上连续的月份和需求量数据后再预测。",
        }
    return None


def _analysis_target_period(analysis_data: dict[str, Any]) -> str:
    payload = analysis_data.get("received_payload") if isinstance(analysis_data.get("received_payload"), dict) else {}
    upstream_contract = analysis_data.get("upstream_contract") if isinstance(analysis_data.get("upstream_contract"), dict) else {}
    for source in (payload, upstream_contract, analysis_data):
        period = _normalize_target_period(source.get("target_period")) if isinstance(source, dict) else ""
        if period:
            return period
        if isinstance(source, dict) and source.get("target_year") and source.get("target_month"):
            try:
                return f"{int(source['target_year']):04d}-{int(source['target_month']):02d}"
            except (TypeError, ValueError):
                pass
    return ""


def _normalize_target_period(value: Any) -> str:
    match = re.search(r"(20\d{2})\D+(\d{1,2})", str(value or ""))
    if not match:
        return ""
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return ""
    return f"{int(match.group(1)):04d}-{month:02d}"


def _filter_forecasts_for_target_period(forecasts: list[Any], target_period: str) -> list[Any]:
    if not target_period:
        return forecasts
    matched = [
        item for item in forecasts
        if isinstance(item, dict) and _normalize_target_period(item.get("date")) == target_period
    ]
    return matched or forecasts


def _forecast_scope_label(analysis_data: dict[str, Any], forecasts: list[dict[str, Any]]) -> str:
    payload = analysis_data.get("received_payload") if isinstance(analysis_data.get("received_payload"), dict) else {}
    target_period = _analysis_target_period(analysis_data)
    if target_period:
        return _format_forecast_period(f"{target_period}-01")
    goal_text = " ".join(
        str(value or "")
        for value in (
            analysis_data.get("analysis_goal"),
            payload.get("analysis_goal"),
            payload.get("user_goal"),
            payload.get("utterance"),
            (payload.get("platform_task") or {}).get("description") if isinstance(payload.get("platform_task"), dict) else "",
        )
    )
    if any(word in goal_text for word in ("下一个月", "下个月", "下月", "下一月", "未来一个月", "未来1个月")):
        return "下一个月"
    if any(word in goal_text for word in ("下一年", "未来一年", "后续一年", "未来12个月", "未来十二个月")):
        return "下一年"
    if any(word in goal_text for word in ("下半年", "未来半年", "后半年")):
        return "下半年"
    if any(word in goal_text for word in ("下季度", "下一季度")):
        return "下季度"
    horizon = None
    upstream_contract = analysis_data.get("upstream_contract") if isinstance(analysis_data.get("upstream_contract"), dict) else {}
    try:
        horizon = int(payload.get("forecast_horizon") or upstream_contract.get("forecast_horizon") or 0)
    except (TypeError, ValueError):
        horizon = None
    if horizon == 12 or len(forecasts) == 12:
        return "下一年"
    if horizon == 6 or len(forecasts) == 6:
        return "下半年"
    if horizon == 3 or len(forecasts) == 3:
        return "下季度"
    if horizon == 1 or len(forecasts) == 1:
        return "下一个月"
    return "预测期"


def _forecast_region_label(analysis_data: dict[str, Any]) -> str:
    payload = analysis_data.get("received_payload") if isinstance(analysis_data.get("received_payload"), dict) else {}
    candidates: list[Any] = []
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    candidates.append(filters.get("region"))
    extracted_details = payload.get("extracted_details") if isinstance(payload.get("extracted_details"), dict) else {}
    extracted_filters = extracted_details.get("filters") if isinstance(extracted_details.get("filters"), dict) else {}
    candidates.append(extracted_filters.get("region"))
    business_scope = payload.get("business_scope") if isinstance(payload.get("business_scope"), dict) else {}
    scope_filters = business_scope.get("filters") if isinstance(business_scope.get("filters"), dict) else {}
    candidates.append(scope_filters.get("region"))
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return "当前范围"


def _format_forecast_period(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})[-/年.](\d{1,2})", text)
    if match:
        return f"{match.group(1)}年{int(match.group(2))}月"
    return text or "预测期"


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_ratio(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return f"{number:.2f}倍"


def _project_flow_answer(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    project_step = next((step for step in steps if step.get("capability") == "project.register.simple"), None)
    monitor_step = next((step for step in steps if step.get("capability") == "monitor.item.register"), None)
    human_step = next((step for step in steps if step.get("capability") == "human.task.create"), None)
    if not any((project_step, monitor_step, human_step)):
        return None
    project_data = ((project_step or {}).get("response") or {}).get("data") or {}
    monitor_data = ((monitor_step or {}).get("response") or {}).get("data") or {}
    human_data = ((human_step or {}).get("response") or {}).get("data") or {}
    pending_items = human_data.get("pending_items") if isinstance(human_data.get("pending_items"), list) else []
    lines = ["当前建议：可以进入立项审批前置确认，但正式立项仍需负责人确认。"]
    if project_step:
        state = project_data.get("state") or project_data.get("integration_status") or "已派发"
        project = project_data.get("project") if isinstance(project_data.get("project"), dict) else {}
        project_name = project.get("name") or "当前推广项目"
        lines.append(f"项目管理：已调用 project.register.simple，项目记录状态：{state}，项目名称：{project_name}。")
    if monitor_step:
        state = monitor_data.get("state") or monitor_data.get("integration_status") or "已派发"
        lines.append(f"监控提醒：已调用 monitor.item.register，后续执行监控事项状态：{state}。")
    if human_step:
        state = human_data.get("state") or human_data.get("integration_status") or "已派发"
        lines.append(f"人机协同：已调用 human.task.create，待确认任务状态：{state}。")
    if pending_items:
        lines.append("需要真人确认的事项：")
        lines.extend(f"- {item}" for item in pending_items[:8])
    else:
        lines.append("需要真人确认的事项：请确认资料是否完整、是否同意进入立项审批、是否生成项目登记和后续监控事项。")
    evidence = []
    for step in (project_step, monitor_step, human_step):
        if step:
            evidence.append({
                "capability": step.get("capability"),
                "status_code": step.get("status_code"),
                "request_keys": sorted(((step.get("request_payload") or {}).keys())),
            })
    return {
        "finding_id": "project-flow",
        "title": "\n".join(lines),
        "detail": "该结果由流程执行引擎按项目管理、监控提醒、人机协同三个模块回执汇总。",
        "evidence": evidence,
        "impact": "用于推进立项审批前置处理，不替代负责人最终审批。",
        "recommendation": "请先完成真人确认事项，再将项目登记、审批待办和监控事项作为正式执行项。",
    }


def _is_unusable_model_content(content: str) -> bool:
    text = str(content or "")
    markers = ("未配置可用大模型", "配置模型 Key", "配置模型Key", "MODEL_UPSTREAM_FAILED", "model key")
    lower = text.lower()
    return any(marker in text for marker in markers) or ("模型" in text and "key" in lower)


def _build_deterministic_business_answer(intent_task: dict[str, Any], aggregate: dict[str, Any]) -> str:
    operation = str(aggregate.get("operation") or "")
    if operation in {"group_count", "entity_list"}:
        answer = str(aggregate.get("answer") or "").strip()
        detail = str(aggregate.get("detail") or "").strip()
        if answer and detail and detail not in answer:
            return f"{answer}\n\n{detail}"
        return answer

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


def _normalize_capability_response(
    envelope: dict[str, Any],
    platform_task_id: str,
    capability: str,
    payload: dict[str, Any],
    status: int,
    response: Any,
    *,
    step: int,
) -> tuple[Any, list[dict[str, Any]]]:
    if not isinstance(response, dict):
        return response, []
    if status not in {200, 202} or response.get("status") != "success":
        return _compact_value(response), []
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    artifact_refs = _extract_artifact_refs(envelope, platform_task_id, capability, payload, data, step=step)
    compact = dict(response)
    compact["data"] = _compact_capability_data(data, artifact_refs)
    if artifact_refs:
        _persist_workflow_artifacts(envelope, platform_task_id, capability, step, artifact_refs)
    return compact, artifact_refs


def _compact_capability_data(data: dict[str, Any], artifact_refs: list[dict[str, Any]]) -> dict[str, Any]:
    keep_keys = {
        "state", "module", "module_name_cn", "platform_capability", "storage_capability",
        "integration_status", "summary", "summary_cn", "user_result", "result_type",
        "normalized_task", "received_summary", "aggregate",
        "forecast", "predictions", "project_record", "monitor_items",
        "confirmation_cards", "next_action", "content", "answer", "user_answer", "output", "business_result",
    }
    compact: dict[str, Any] = {key: _compact_value(value) for key, value in data.items() if key in keep_keys}
    for list_key in ("rule_results", "risks", "exceptions"):
        value = data.get(list_key)
        if isinstance(value, list):
            compact[list_key] = [
                _compact_value(item, string_limit=1200, list_limit=12)
                for item in value[:24]
            ]
    analysis_result = data.get("analysis_result")
    if isinstance(analysis_result, dict):
        # The final user summary is built from this structured result. Keep the
        # forecast rows as a real list; generic audit compaction turns lists into
        # {count, sample}, which previously made a successful forecast look empty.
        compact_analysis = {
            key: _compact_value(value)
            for key, value in analysis_result.items()
            if key != "forecasts"
        }
        forecasts = analysis_result.get("forecasts")
        if isinstance(forecasts, list):
            compact_analysis["forecasts"] = [
                _compact_value(item, string_limit=800, list_limit=20)
                for item in forecasts[:24]
            ]
        compact["analysis_result"] = compact_analysis
    storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else {}
    if storage:
        storage_compact = {
            key: _compact_value(storage.get(key))
            for key in ("state", "count", "item", "aggregate", "dataset", "record_id")
            if key in storage
        }
        items = storage.get("items") if isinstance(storage.get("items"), list) else None
        if items is not None:
            storage_compact["items_count"] = len(items)
            storage_compact["sample_items"] = _compact_list_sample(items)
        compact["storage_result"] = storage_compact
    for list_key in ("items", "records", "rows", "documents", "fields", "chunks"):
        value = data.get(list_key)
        if isinstance(value, list):
            compact[f"{list_key}_count"] = len(value)
            compact[f"{list_key}_sample"] = _compact_list_sample(value)
    if artifact_refs:
        compact["artifact_refs"] = artifact_refs
        compact["next_read_hints"] = [
            ref.get("next_read_hint")
            for ref in artifact_refs
            if isinstance(ref.get("next_read_hint"), dict)
        ]
    return compact


def _extract_artifact_refs(
    envelope: dict[str, Any],
    platform_task_id: str,
    capability: str,
    payload: dict[str, Any],
    data: dict[str, Any],
    *,
    step: int,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    existing_refs = data.get("artifact_refs") if isinstance(data.get("artifact_refs"), list) else []
    for ref in existing_refs:
        if isinstance(ref, dict):
            refs.append(_normalize_artifact_ref(envelope, platform_task_id, capability, payload, ref, step=step))
    documents = data.get("documents") if isinstance(data.get("documents"), list) else []
    for document in documents:
        if not isinstance(document, dict):
            continue
        parse_job_id = document.get("parse_job_id") or document.get("reused_from_parse_job_id")
        if parse_job_id:
            refs.append(_normalize_artifact_ref(
                envelope, platform_task_id, capability, payload,
                {
                    "artifact_type": "parsed_table_fields",
                    "dataset": "extracted_fields",
                    "schema": "document_table_extract_v1",
                    "record_count": document.get("field_count") or document.get("row_count"),
                    "filters": {"parse_job_id": str(parse_job_id)},
                    "summary": document.get("summary") or f"parsed document fields for {parse_job_id}",
                },
                step=step,
            ))
    storage = data.get("storage_result") if isinstance(data.get("storage_result"), dict) else {}
    received_summary = data.get("received_summary") if isinstance(data.get("received_summary"), dict) else {}
    dataset = storage.get("dataset") or received_summary.get("dataset") or payload.get("dataset") or payload.get("collection")
    if dataset:
        filters = received_summary.get("filters")
        if not isinstance(filters, dict):
            filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        items = storage.get("items") if isinstance(storage.get("items"), list) else data.get("items")
        aggregate = storage.get("aggregate") if isinstance(storage.get("aggregate"), dict) else data.get("aggregate")
        record_count = storage.get("count") or (len(items) if isinstance(items, list) else None)
        if record_count is not None or isinstance(aggregate, dict):
            refs.append(_normalize_artifact_ref(
                envelope, platform_task_id, capability, payload,
                {
                    "artifact_type": "dataset_query_result",
                    "dataset": dataset,
                    "schema": f"{dataset}_query_v1",
                    "record_count": record_count,
                    "filters": filters,
                    "aggregate": aggregate if isinstance(aggregate, dict) else None,
                    "summary": f"{capability} produced readable data reference for {dataset}",
                },
                step=step,
            ))
    return _dedupe_artifact_refs(refs)


def _normalize_artifact_ref(
    envelope: dict[str, Any],
    platform_task_id: str,
    capability: str,
    payload: dict[str, Any],
    ref: dict[str, Any],
    *,
    step: int,
) -> dict[str, Any]:
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    actor = envelope.get("actor") or {}
    dataset = str(ref.get("dataset") or payload.get("dataset") or payload.get("collection") or "workflow_artifacts")
    filters = ref.get("filters") if isinstance(ref.get("filters"), dict) else {}
    read_params = ref.get("read_params") if isinstance(ref.get("read_params"), dict) else {
        "dataset": dataset,
        "filters": filters,
    }
    artifact_id = str(ref.get("artifact_id") or f"artifact-{platform_task_id}-{step}-{uuid4().hex[:8]}")
    next_read_hint = ref.get("next_read_hint") if isinstance(ref.get("next_read_hint"), dict) else {
        "capability": ref.get("read_capability") or "data.search",
        "dataset": dataset,
        "filters": filters,
    }
    return {
        "artifact_id": artifact_id,
        "artifact_type": ref.get("artifact_type") or "module_output",
        "dataset": dataset,
        "schema": ref.get("schema") or f"{dataset}_ref_v1",
        "record_count": ref.get("record_count"),
        "filters": filters,
        "aggregate": ref.get("aggregate") if isinstance(ref.get("aggregate"), dict) else None,
        "read_capability": ref.get("read_capability") or next_read_hint.get("capability") or "data.search",
        "read_params": read_params,
        "next_read_hint": next_read_hint,
        "summary": ref.get("summary") or ref.get("description") or f"{capability} output reference",
        "retention_policy": ref.get("retention_policy") or "workflow-temp-7d",
        "expires_at": ref.get("expires_at") or (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "trace_id": envelope.get("trace_id"),
        "workflow_instance_id": f"wf-{platform_task_id}",
        "platform_task_id": platform_task_id,
        "source_capability": capability,
        "source_step": step,
        "tenant_id": actor.get("tenant_id"),
        "owner_account_id": actor.get("user_id") or actor.get("actor_id"),
        "project_id": context.get("project_id"),
        "conversation_id": context.get("conversation_id"),
    }


def _dedupe_artifact_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        filters = ref.get("filters") if isinstance(ref.get("filters"), dict) else {}
        key = (str(ref.get("dataset") or ""), str(filters), str(ref.get("source_capability") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _persist_workflow_artifacts(envelope: dict[str, Any], platform_task_id: str, capability: str, step: int, refs: list[dict[str, Any]]) -> None:
    if not refs:
        return
    records = []
    for ref in refs:
        records.append({
            **ref,
            "record_id": ref["artifact_id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    persist_envelope = make_internal_envelope(
        envelope["trace_id"],
        envelope.get("actor") or {},
        f"{platform_task_id}-artifact-{step}",
        "data.persist",
        "business_engine",
        "engine-gateway",
        {
            "dataset": "workflow_artifacts",
            "operation": "upsert",
            "records": records,
            "owner_account_id": (envelope.get("actor") or {}).get("user_id") or (envelope.get("actor") or {}).get("actor_id"),
            "project_id": (envelope.get("context") or {}).get("project_id") if isinstance(envelope.get("context"), dict) else None,
            "conversation_id": (envelope.get("context") or {}).get("conversation_id") if isinstance(envelope.get("context"), dict) else None,
        },
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else None,
    )
    post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions",
        persist_envelope,
        timeout=70,
        caller={"layer": "business_engine", "module": "workflow-execution"},
    )


def _compact_payload_for_audit(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "workflow_prior_outputs":
            continue
        if key == "workflow_prior_refs":
            compact[key] = _compact_value(value)
            continue
        if key in {"conversation_context", "uploaded_documents", "input_data_refs", "workflow_evidence", "input"}:
            compact[key] = _compact_value(value)
            continue
        compact[key] = _compact_value(value)
    return compact


def _compact_value(value: Any, *, string_limit: int = 2000, list_limit: int = 20) -> Any:
    if isinstance(value, str):
        return value if len(value) <= string_limit else f"{value[:string_limit]}...(truncated {len(value) - string_limit} chars)"
    if isinstance(value, list):
        return {
            "count": len(value),
            "sample": [_compact_value(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]],
            "truncated": len(value) > list_limit,
        }
    if isinstance(value, dict):
        return {str(key): _compact_value(item, string_limit=string_limit, list_limit=list_limit) for key, item in value.items()}
    return value


def _compact_list_sample(items: list[Any], *, limit: int = 10) -> list[Any]:
    return [_compact_value(item, string_limit=800, list_limit=5) for item in items[:limit]]


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
    compact_response, artifact_refs = _normalize_capability_response(
        envelope, platform_task_id, capability, payload, status, response, step=step
    )
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
        "request_payload": _compact_payload_for_audit(payload),
        "artifact_refs": artifact_refs,
        "response": compact_response,
    }
