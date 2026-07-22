from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from framework.core import get_trace_calls
from framework.http import post_json
from framework.module_catalog import BUSINESS_MODULES, FOUNDATION_MODULES, ModuleSpec


ACTOR = {"tenant_id": "demo-tenant", "user_id": "module-validator", "actor_id": "module-validator", "authenticated": True}


@dataclass(frozen=True)
class VerificationCase:
    case_id: str
    layer: str
    layer_cn: str
    module_code: str
    module_name_cn: str
    service_name: str
    port: int
    endpoint: str
    capability: str
    payload_kind: str
    description: str
    all_capabilities: tuple[str, ...]


CORE_CASES: tuple[VerificationCase, ...] = (
    VerificationCase("l2-intent", "business_engine", "L2 业务引擎层", "intent-adapter", "意图分析引擎", "intent", 8000, "/api/v1/intent/analyze", "intent.analyze", "envelope", "自然语言识别为平台能力", ("intent.analyze",)),
    VerificationCase("l2-workflow", "business_engine", "L2 业务引擎层", "workflow-execution", "流程执行引擎", "workflow", 8020, "/api/v1/workflows/executions", "workflow.execute", "envelope", "创建流程执行实例并返回受理回执", ("workflow.execute",)),
    VerificationCase("l2-content", "business_engine", "L2 业务引擎层", "content-adapter", "内容产出引擎", "content", 8011, "/api/v1/content/instructions", "content.generate", "envelope", "生成一段验证用通知文本", ("content.generate",)),
    VerificationCase("l2-rule", "business_engine", "L2 业务引擎层", "rule-adapter", "规则计算引擎", "rule", 8010, "/api/v1/rules/instructions", "rule.calculate", "envelope", "计算 100 + 268.5", ("rule.calculate",)),
    VerificationCase("l1-permission", "foundation", "L1 基础模块层", "permission-adapter", "权限管理", "permission", 8001, "/api/v1/permissions/check", "permissions.check", "permission", "检查当前验证账号是否可调用能力", ("permissions.check",)),
    VerificationCase("l1-model", "foundation", "L1 基础模块层", "model-dispatcher", "大模型调度", "model", 8002, "/api/v1/models/responses", "model.respond", "model", "通过统一模型调度接口完成一次最小模型请求", ("model.respond",)),
    VerificationCase("l1-template", "foundation", "L1 基础模块层", "template-management", "流程模板管理", "template", 8004, "/api/v1/templates/instructions", "template.list", "template", "查询流程模板列表", ("template.retrieve", "template.list", "template.validate", "template.register_draft", "template.update_draft", "template.publish", "template.disable")),
)


def list_cases() -> list[dict[str, Any]]:
    cases = list(CORE_CASES)
    cases.extend(_module_case("l2", "L2 业务引擎层", item) for item in BUSINESS_MODULES)
    cases.extend(_module_case("l1", "L1 基础模块层", item) for item in FOUNDATION_MODULES)
    return [_case_public(item) for item in cases]


def run_case(case_id: str) -> dict[str, Any]:
    case = _case_by_id(case_id)
    trace_id = str(uuid4())
    request = _build_request(case, trace_id)
    url = f"http://127.0.0.1:{case.port}{case.endpoint}"
    try:
        status, response = post_json(
            url,
            request,
            timeout=75 if case.module_code in {"intent-adapter", "content-adapter"} else 10,
            caller={"layer": "business_application", "module": "module-verification-page"},
        )
    except Exception as exc:  # noqa: BLE001 - verification must report unavailable modules instead of crashing the page.
        status, response = 599, {"error": {"code": "PLATFORM_SERVICE_UNAVAILABLE", "message": str(exc), "url": url}}
    calls = get_trace_calls(trace_id)
    return {
        "case": _case_public(case),
        "trace_id": trace_id,
        "request_url": url,
        "request": request,
        "http_status": status,
        "response": response,
        "result_status": _classify(status, response),
        "calls": calls,
    }


def _module_case(prefix: str, layer_cn: str, module: ModuleSpec) -> VerificationCase:
    return VerificationCase(
        case_id=f"{prefix}-{module.code}",
        layer=module.layer,
        layer_cn=layer_cn,
        module_code=module.code,
        module_name_cn=module.name_cn,
        service_name=module.code.replace("-", "_"),
        port=module.port,
        endpoint=module.interface,
        capability=module.capabilities[0],
        payload_kind="envelope",
        description=module.notes,
        all_capabilities=module.capabilities,
    )


def _case_by_id(case_id: str) -> VerificationCase:
    for item in list_cases():
        if item["case_id"] == case_id:
            return VerificationCase(**{key: item[key] for key in VerificationCase.__dataclass_fields__})
    raise KeyError(case_id)


def _case_public(case: VerificationCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "layer": case.layer,
        "layer_cn": case.layer_cn,
        "module_code": case.module_code,
        "module_name_cn": case.module_name_cn,
        "service_name": case.service_name,
        "port": case.port,
        "endpoint": case.endpoint,
        "capability": case.capability,
        "payload_kind": case.payload_kind,
        "description": case.description,
        "all_capabilities": case.all_capabilities,
    }


def _build_request(case: VerificationCase, trace_id: str) -> dict[str, Any]:
    if case.payload_kind == "permission":
        return {"trace_id": trace_id, "actor": ACTOR, "action": "module.verify", "resource": {"type": "capability", "id": case.capability}, "scope": {"purpose": "module-verification"}}
    if case.payload_kind == "model":
        return {
            "trace_id": trace_id,
            "actor": ACTOR,
            "task_type": "module_verification",
            "messages": [{"role": "user", "content": "请返回一个 JSON，说明模型调度模块已收到验证请求。"}],
            "model_policy": {"temperature": 0.1, "max_output_tokens": 120},
        }
    payload = _sample_payload(case)
    return {
        "protocol_version": "1.0",
        "message_id": str(uuid4()),
        "request_id": str(uuid4()),
        "trace_id": trace_id,
        "parent_request_id": None,
        "source": _source_for(case),
        "target": {"layer": case.layer, "module": case.module_code, "capability": case.capability},
        "actor": ACTOR,
        "context": {"project_id": "module-verification", "conversation_id": f"verify-{case.case_id}", "locale": "zh-CN"},
        "request_type": "execute",
        "action": case.capability,
        "payload": payload,
        "expected_response": {"mode": "sync"},
        "idempotency_key": f"verify-{case.case_id}-{uuid4()}",
        "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    }


def _source_for(case: VerificationCase) -> dict[str, str]:
    if case.module_code == "template-management":
        return {"layer": "business_engine", "module": "workflow-execution-engine-original"}
    return {"layer": "business_application", "module": "module-verification-page"}


def _sample_payload(case: VerificationCase) -> dict[str, Any]:
    common = {"verification_mode": True, "adapter_timeout_seconds": 0.6, "description": f"验证 {case.module_name_cn} 标准接口"}
    if case.capability == "intent.analyze":
        return {"utterance": "计算两笔销售业绩合计，金额分别为100元和268.5元"}
    if case.capability == "workflow.execute":
        return {"execution_kind": "verification", "intent_task": {"capability_code": "data.search", "description": "验证流程执行引擎受理流程"}}
    if case.capability == "content.generate":
        return {**common, "utterance": "写一段30字左右的模块验收说明", "content_type": "generic_text_draft"}
    if case.capability == "rule.calculate":
        return {"rule_ref": {"id": "verification.sum", "version": "1.0"}, "data_refs": [{"id": "verification.inline", "authorized": True}], "parameters": {"values": [100, 268.5]}, "expected_unit": "CNY"}
    if case.capability == "template.list":
        return {"filters": {"status": "published"}, "limit": 10}
    if case.module_code == "account-gateway":
        return {**common, "name": "module-validator", "account": {"name": "module-validator"}}
    if case.module_code == "knowledge-base":
        return {**common, "query": "模块验收", "top_k": 3}
    if case.module_code == "foundation-data":
        return {**common, "dataset": "verification", "query": {"limit": 1}}
    return {**common, "sample_input": {"text": f"{case.module_name_cn} 验证请求", "capability": case.capability}}


def _classify(status: int, response: Any) -> str:
    if 200 <= status < 300:
        if isinstance(response, dict) and response.get("status") == "failed":
            return "failed"
        return "passed"
    if isinstance(response, dict) and "UPSTREAM_UNAVAILABLE" in str(response):
        return "upstream_unavailable"
    return "failed"
