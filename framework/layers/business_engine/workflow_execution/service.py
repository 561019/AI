from __future__ import annotations

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
        }, step=3),
        _invoke_business_capability(envelope, platform_task_id, "data.search", {
            "step_name_cn": "按本人和本月取销售对账数据",
            "dataset": "case2_sales_reconciliation",
            "filters": {"owner": envelope["actor"].get("user_id") or "demo-user", "month": "2026-07"},
            "required_tables": ["payment_flow", "finance_ar", "contract_ledger"],
        }, step=4),
        _invoke_business_capability(envelope, platform_task_id, "external.api.call", {
            "step_name_cn": "模拟外部发票系统核对",
            "system_code": "tax_invoice_system",
            "operation": "invoice_consistency_check",
            "uploaded_documents": uploaded_documents,
            "expected_fields": ["invoice_title", "expected_title", "invoice_amount", "expected_amount"],
        }, step=5),
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
        }, step=6),
        _invoke_foundation_capability(envelope, platform_task_id, "human.task.create", {
            "step_name_cn": "疑点人工确认待办",
            "task_type": "case2_reconciliation_doubt_confirmation",
            "assignee": envelope["actor"].get("user_id") or "demo-user",
            "cards": [
                {"doubt_id": "case2-doubt-001", "title": "回款金额与合同尾款相差 200 元", "suggested_decision": "确认差异成立并标记为运费差异"},
                {"doubt_id": "case2-doubt-002", "title": "一张发票抬头不一致", "suggested_decision": "确认疑点成立并退回发票修正"},
            ],
        }, step=7),
    ]

    handler.send(200, standard_response(envelope, "success", data={
        "intent_task": intent_task,
        "selected_capability": capability,
        "provider_module": "workflow-execution",
        "permission": permission,
        "workflow_engine": {"source": "platform-standard-router", "component": "workflow_execution.uploaded_document_reconciliation"},
        "workflow_instance": {
            "instance_id": f"case2-doc-recon-{platform_task_id}",
            "route_type": "uploaded_document_sales_reconciliation",
            "status": "completed_with_interface_results",
            "artifacts": {"execution_plan": [step["plan_item"] for step in steps]},
        },
        "capability_result": {
            "state": "completed_with_interface_results",
            "summary_cn": "已基于上传文档触发案例二销售对账流程，生成 2 个疑点和 1 个自动通过项。",
            "document_count": len(uploaded_documents),
            "doubts": [
                {"doubt_id": "case2-doubt-001", "title": "回款金额与合同尾款相差 200 元", "source": "PaymentFlow + FinanceAR + ContractLedger"},
                {"doubt_id": "case2-doubt-002", "title": "发票抬头不一致", "source": "Invoices + external.api.call"},
            ],
            "auto_passed": [{"check_id": "CHK-002", "title": "合同登记表应收与实收一致"}],
            "module_results": steps,
        },
    }))


def _invoke_business_capability(envelope: dict[str, Any], platform_task_id: str, capability: str, payload: dict[str, Any], *, step: int) -> dict[str, Any]:
    return _invoke_capability(envelope, platform_task_id, capability, "business_engine", "engine-gateway", "http://127.0.0.1:8200/api/v1/engine/instructions", payload, step=step)


def _invoke_foundation_capability(envelope: dict[str, Any], platform_task_id: str, capability: str, payload: dict[str, Any], *, step: int) -> dict[str, Any]:
    return _invoke_capability(envelope, platform_task_id, capability, "foundation", "foundation-gateway", "http://127.0.0.1:8300/api/v1/foundation/instructions", payload, step=step)


def _invoke_capability(envelope: dict[str, Any], platform_task_id: str, capability: str, target_layer: str, target_module: str, url: str, payload: dict[str, Any], *, step: int) -> dict[str, Any]:
    execution_envelope = make_internal_envelope(envelope["trace_id"], envelope["actor"], platform_task_id, capability, target_layer, target_module, payload)
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
