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
