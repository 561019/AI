from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

from framework.envelope import make_internal_envelope
from framework.http import post_json

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "联调文件-7.20-解压" / "2.10流程引擎联调资料" / "流程引擎联调资料" / "实现参考"
STATE_PATH = ROOT / "framework" / "data" / "workflow_instances.json"
TEMPLATE_SERVICES = {
    "template.register_draft": {"request_type": "maintain", "description": "登记流程模板草稿"},
    "template.update_draft": {"request_type": "maintain", "description": "修改流程模板草稿"},
    "template.validate": {"request_type": "query", "description": "校验流程模板"},
    "template.publish": {"request_type": "maintain", "description": "发布流程模板"},
    "template.disable": {"request_type": "maintain", "description": "停用流程模板"},
    "template.retrieve": {"request_type": "query", "description": "读取流程模板"},
    "template.list": {"request_type": "query", "description": "查询流程模板"},
}
EXECUTION_CONTEXT: dict[str, dict[str, Any]] = {}


class PlatformDelegatedExecutor:
    """Original FlowExecutionEngine port backed by platform HTTP interfaces."""

    CAPABILITIES = {
        "rule_engine": "rule.calculate",
        "content": "content.generate",
    }

    def execute(self, service: Any, dispatch: dict[str, Any]) -> dict[str, Any]:
        context = EXECUTION_CONTEXT.get(dispatch["trace_id"], {})
        capability = self.CAPABILITIES.get(service.engine_id)
        if not capability:
            return {"ok": False, "summary": f"platform_capability_not_mapped:{service.engine_id}"}
        actor = context.get("actor") or {"tenant_id": "platform", "user_id": dispatch.get("requester_id"), "authenticated": True}
        resource_id = f"denied-{capability}" if context.get("simulate_permission_denied") else capability
        permission = make_internal_envelope(dispatch["trace_id"], actor, dispatch["task_id"], "permissions.check", "foundation", "foundation-gateway", {"resource": {"type": "capability", "id": resource_id}, "scope": {"purpose": "workflow-node-execution", "workflow_instance_id": dispatch["task_id"], "subtask_id": dispatch["subtask_id"], "capability": capability}})
        permission_status, permission_result = post_json("http://127.0.0.1:8300/api/v1/foundation/instructions", permission, caller={"layer": "business_engine", "module": "workflow-execution"})
        decision = permission_result.get("data", {}) if isinstance(permission_result, dict) else {}
        if permission_status != 200 or decision.get("decision") != "allow":
            return {"ok": False, "summary": "permission_denied", "permission": decision}
        intent_task = context.get("intent_task") or {}
        parameters = intent_task.get("parameters") or {}
        if capability == "rule.calculate":
            values = parameters.get("values") or []
            payload = {"rule_ref": parameters.get("rule_ref") or {"id": "platform.inline-arithmetic", "version": "1.0"}, "data_refs": parameters.get("data_refs") or [{"id": "intent.inline-values", "authorized": True}], "parameters": {**parameters, "values": values}, "expected_unit": parameters.get("expected_unit", "CNY")}
        else:
            payload = {**parameters, "description": intent_task.get("description"), "utterance": parameters.get("utterance") or intent_task.get("description")}
        envelope = make_internal_envelope(dispatch["trace_id"], actor, dispatch["task_id"], capability, "business_engine", "engine-gateway", payload)
        status, response = post_json("http://127.0.0.1:8200/api/v1/engine/instructions", envelope, timeout=70, caller={"layer": "business_engine", "module": "workflow-execution"})
        if status not in {200, 202} or response.get("status") != "success":
            return {"ok": False, "summary": "capability_execution_failed", "response": response}
        return {"ok": True, "summary": f"{capability} completed", "platform_capability": capability, "permission": decision, "data": response.get("data")}


class HttpTemplateClient:
    """L2 port: calls L1.2 only through the L1 foundation gateway."""

    def retrieve(self, template_id: str, trace_id: str) -> dict[str, Any]:
        result = self._call("template.retrieve", "query", {"template_id": template_id, "purpose": "new_start"}, trace_id, "workflow-execution")
        if not result.get("ok"): raise ValueError(result.get("error", {}).get("code") or "template_retrieve_failed")
        return result["result"]

    def forward_instruction(self, instruction: dict[str, Any]) -> dict[str, Any]:
        return self._call(str(instruction.get("service_name") or ""), str(instruction.get("request_type") or "query"), instruction.get("payload") or {}, str(instruction.get("trace_id") or "workflow-template-call"), str(instruction.get("actor_id") or "workflow-execution"))

    @staticmethod
    def _call(action: str, request_type: str, payload: dict[str, Any], trace_id: str, actor_id: str) -> dict[str, Any]:
        actor = {"tenant_id": "platform", "actor_id": actor_id, "user_id": actor_id, "authenticated": True}
        envelope = make_internal_envelope(trace_id, actor, f"template-{trace_id}", action, "foundation", "foundation-gateway", payload, source_module="workflow-execution-engine-original")
        envelope["request_type"] = "query" if request_type == "query" else "execute"
        status, response = post_json("http://127.0.0.1:8300/api/v1/foundation/instructions", envelope, timeout=15, caller={"layer": "business_engine", "module": "workflow-execution-engine-original"})
        if status != 200 or response.get("status") != "success": return {"ok": False, "error": response.get("error") or {"code": "template_interface_failed"}}
        return {"ok": True, "trace_id": trace_id, "service_name": action, "result": response.get("data")}


def _load_delivered_modules():
    # Only the L1.2 contract is visible in L2. The implementation lives in the L1 service process.
    contract = types.ModuleType("l1_2_template_management.template_management")
    contract.InMemoryTemplateRepository = object
    contract.TemplateManagementService = object
    contract.REGISTERED_SERVICES = TEMPLATE_SERVICES
    contract.seed_common_templates = lambda service: None
    package_l1 = types.ModuleType("l1_2_template_management"); package_l1.__path__ = []
    sys.modules["l1_2_template_management"] = package_l1
    sys.modules["l1_2_template_management.template_management"] = contract
    package = types.ModuleType("delivered_workflow"); package.__path__ = [str(SOURCE)]
    sys.modules["delivered_workflow"] = package
    loaded = {}
    for name in ("engine", "platform_adapter"):
        spec = importlib.util.spec_from_file_location(f"delivered_workflow.{name}", SOURCE / f"{name}.py")
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
        spec.loader.exec_module(module); loaded[name] = module
    return loaded["engine"], loaded["platform_adapter"]


ENGINE_MODULE, ADAPTER_MODULE = _load_delivered_modules()
ENGINE = ENGINE_MODULE.FlowExecutionEngine(repository=ENGINE_MODULE.JsonInstanceRepository(STATE_PATH), template_client=HttpTemplateClient(), executor=PlatformDelegatedExecutor())
ADAPTER = ADAPTER_MODULE.PlatformFlowExecutionAdapter(ENGINE)


def post(handler: Any, request: dict[str, Any]) -> None:
    if handler.path == "/api/v1/delivered-workflow/execute":
        intent_task = request.get("intent_task") or {}
        platform_capability = intent_task.get("capability_code")
        capability_id = {"rule.calculate": "CAP.RULE.PROCUREMENT.COMPARE", "content.generate": "CAP.CONTENT.DRAFT.GENERATE"}.get(platform_capability)
        if not capability_id:
            handler.send(422, {"success": False, "error": {"code": "CAPABILITY_NOT_MAPPED", "capability": platform_capability}}); return
        trace_id = request["trace_id"]
        EXECUTION_CONTEXT[trace_id] = {"actor": request.get("actor", {}), "intent_task": intent_task, "simulate_permission_denied": bool(request.get("simulate_permission_denied"))}
        try:
            instance = ENGINE.start({"trace_id": trace_id, "requester_id": request.get("actor", {}).get("actor_id") or request.get("actor", {}).get("user_id") or "unknown", "request_text": intent_task.get("description") or platform_capability, "idempotency_key": request.get("idempotency_key") or f"dialog-{trace_id}", "intent_result": {"task_type": "execution", "capability_ids": [capability_id], "requires_user_confirmation": False, "user_confirmed": True}})
        finally:
            EXECUTION_CONTEXT.pop(trace_id, None)
        node_result = next((node.get("output") for node in instance.get("nodes", []) if node.get("output", {}).get("platform_capability") == platform_capability), None)
        success = instance.get("status") == "completed" and bool(node_result and node_result.get("ok"))
        handler.send(200 if success else 502, {"success": success, "data": {"workflow_instance": instance, "selected_capability": platform_capability, "capability_result": (node_result or {}).get("data"), "permission": (node_result or {}).get("permission"), "workflow_engine": {"source": "user-delivered-module", "component": "FlowExecutionEngine", "state_repository": str(STATE_PATH)}}}); return
    if handler.path == "/api/v1/delivered-workflow/instructions":
        result = ADAPTER.handle(request); handler.send(200 if result.get("reply_type") != "failed" else 422, result); return
    if handler.path != "/api/v1/delivered-workflow/plan": handler.send(404); return
    capability = request.get("capability_code")
    service_ref = {"rule.calculate": "L2.rule_engine.procurement_compare", "content.generate": "L2.content.generate"}.get(capability, "L2.generic.execute")
    selected = ENGINE.registry.resolve(service_ref)
    handler.send(200, {"success": True, "plan": {"capability_code": capability, "service_ref": selected.service_name, "engine_id": selected.engine_id, "engine_name": selected.engine_name, "request_type": selected.request_type, "estimated_seconds": selected.estimated_seconds}, "engine_meta": {"source": "user-delivered-module", "component": "FlowExecutionEngine.ModuleRegistry", "delivery_root": str(SOURCE), "template_dependency": "http:L2->L1-gateway->L1.2", "state_repository": str(STATE_PATH)}})
