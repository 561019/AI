"""L1.6 context lifecycle service.

Normal conversations remain isolated.  This service only prepares explicitly
imported material for intent analysis, owns the 80/85% lifecycle, and records
the three handoff artefacts.  It never reads SQLite directly: all records go
through the foundation gateway and foundation-data service.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from framework.core import standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json


CAPABILITIES = {
    "context.intent.prepare", "context.capacity.evaluate", "context.handoff.generate",
    "context.handoff.import", "context.project.search", "context.account.search",
    "context.reference.import",
}
WARNING_RATIO = 0.80
HANDOFF_RATIO = 0.85


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in sorted(CAPABILITIES)]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != "/api/v1/context-prompts/instructions":
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = str((envelope.get("target") or {}).get("capability") or envelope.get("action") or "")
    if capability not in CAPABILITIES:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_SUPPORTED", "capability": capability}))
        return
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    try:
        if capability == "context.intent.prepare":
            data = _prepare_intent_context(envelope, payload)
        elif capability == "context.capacity.evaluate":
            data = _evaluate_capacity(envelope, payload)
        elif capability == "context.handoff.generate":
            data = _generate_handoff(envelope, payload)
        elif capability == "context.handoff.import":
            data = _import_material(envelope, payload, cross_project=False)
        elif capability == "context.reference.import":
            data = _import_material(envelope, payload, cross_project=True)
        elif capability == "context.project.search":
            data = _search(envelope, payload, account_scope=False)
        else:
            data = _search(envelope, payload, account_scope=True)
    except ContextError as exc:
        handler.send(exc.status, standard_response(envelope, "failed", error={"code": exc.code, "message": exc.message, "retryable": exc.retryable}))
        return
    handler.send(200, standard_response(envelope, "success", data=data))


class ContextError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 422, retryable: bool = False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


def _identity(envelope: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str, str, str]:
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
    tenant_id = str(actor.get("tenant_id") or "")
    owner = str(actor.get("user_id") or actor.get("actor_id") or "")
    project_id = str(payload.get("project_id") or context.get("project_id") or "")
    conversation_id = str(payload.get("conversation_id") or context.get("conversation_id") or "")
    if not tenant_id or not owner:
        raise ContextError("ACCOUNT_CONTEXT_REQUIRED", "上下文操作需要当前员工的真实账号身份", status=403)
    return tenant_id, owner, project_id, conversation_id


def _foundation(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    task_id = str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4())
    inner = make_internal_envelope(
        str(envelope.get("trace_id") or uuid4()), actor, task_id, capability,
        "foundation", "foundation-gateway", payload,
        source_layer="foundation", source_module="context-prompt-management",
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else {},
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions", inner, timeout=120 if capability == "foundation_data.write" else 45,
        caller={"layer": "foundation", "module": "context-prompt-management"},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        raise ContextError("CONTEXT_FOUNDATION_CALL_FAILED", f"上下文模块调用 {capability} 失败", status=502, retryable=True)
    return response.get("data") if isinstance(response.get("data"), dict) else {}


def _query(envelope: dict[str, Any], dataset: str, filters: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    data = _foundation(envelope, "foundation_data.query", {"dataset": dataset, "filters": filters, "limit": limit, "compact": dataset == "conversation_messages"})
    return data.get("items") if isinstance(data.get("items"), list) else []


def _write(envelope: dict[str, Any], dataset: str, record: dict[str, Any]) -> None:
    _foundation(envelope, "foundation_data.write", {"dataset": dataset, "operation": "upsert", "records": [record]})


def _prepare_intent_context(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    _, owner, project_id, conversation_id = _identity(envelope, payload)
    if not project_id or not conversation_id:
        raise ContextError("CONVERSATION_CONTEXT_REQUIRED", "意图分析需要当前 Project 和普通对话框")
    imports = _query(envelope, "context_imports", {"target_conversation_id": conversation_id, "owner_account_id": owner}, 100)
    materials = [
        {key: item.get(key) for key in ("source_record_type", "source_record_id", "title", "content", "source_project_id", "imported_at")}
        for item in imports if str(item.get("target_project_id") or project_id) == project_id
    ]
    return {"scope": "conversation", "conversation_id": conversation_id, "project_id": project_id, "materials": materials, "context_ref": f"ctx-import:{conversation_id}"}


def _evaluate_capacity(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id, owner, project_id, conversation_id = _identity(envelope, payload)
    if not project_id or not conversation_id:
        raise ContextError("CONVERSATION_CONTEXT_REQUIRED", "容量评估需要当前 Project 和普通对话框")
    ratio = payload.get("capacity_ratio")
    if ratio is None:
        messages = _query(envelope, "conversation_messages", {"conversation_id": conversation_id}, 500)
        used = sum(max(1, len(str(item.get("content_text") or item.get("text") or "")) // 4) for item in messages)
        limit = max(int(payload.get("capacity_limit") or 8000), 1)
        ratio = min(used / limit, 1.0)
    try:
        ratio = max(0.0, float(ratio))
    except (TypeError, ValueError) as exc:
        raise ContextError("CAPACITY_RATIO_INVALID", "容量占用必须是数字") from exc
    state = "normal" if ratio < WARNING_RATIO else "warning" if ratio < HANDOFF_RATIO else "handoff_required"
    event = {
        "event_id": f"ctx-cap-{uuid4().hex[:16]}", "record_id": f"ctx-cap-{uuid4().hex[:16]}",
        "tenant_id": tenant_id, "owner_account_id": owner, "project_id": project_id, "conversation_id": conversation_id,
        "state": state, "capacity_ratio": ratio, "threshold_warning": WARNING_RATIO, "threshold_handoff": HANDOFF_RATIO,
        "created_at": _now(), "storage_class": "temporary", "retention_policy": "session-lifecycle",
    }
    _write(envelope, "context_capacity_events", event)
    return {"conversation_id": conversation_id, "capacity_ratio": ratio, "state": state, "next_action": "generate_handoff" if state == "handoff_required" else "warn" if state == "warning" else "continue"}


def _generate_handoff(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id, owner, project_id, conversation_id = _identity(envelope, payload)
    if not project_id or not conversation_id:
        raise ContextError("CONVERSATION_CONTEXT_REQUIRED", "生成三件套需要当前 Project 和普通对话框")
    messages = _query(envelope, "conversation_messages", {"conversation_id": conversation_id}, 500)
    old_packages = _query(envelope, "context_inheritance_packages", {"project_id": project_id, "owner_account_id": owner}, 10)
    source = {"project_id": project_id, "conversation_id": conversation_id, "messages": messages[-120:], "previous_package": old_packages[0] if old_packages else None}
    report = _generate_artifact(envelope, "work_report", source)
    handoff = _generate_artifact(envelope, "handoff_file", source)
    package = _generate_artifact(envelope, "inheritance_package", {**source, "work_report": report, "handoff_file": handoff})
    version = max([int(item.get("version_no") or 0) for item in old_packages] or [0]) + 1
    records = [
        ("context_work_reports", {"report_id": f"report-{uuid4().hex[:16]}", "content": report, "title": "工作汇报", "source_record_type": "work_report"}),
        ("context_handoff_files", {"handoff_id": f"handoff-{uuid4().hex[:16]}", "content": handoff, "title": "工作交接文件", "source_record_type": "handoff_file"}),
        ("context_inheritance_packages", {"package_id": f"package-{uuid4().hex[:16]}", "content": package, "title": f"传承包 v{version}", "version_no": version, "source_record_type": "inheritance_package"}),
    ]
    generated = []
    for dataset, item in records:
        item.update({"record_id": item.get("report_id") or item.get("handoff_id") or item.get("package_id"), "tenant_id": tenant_id, "owner_account_id": owner, "project_id": project_id, "conversation_id": conversation_id, "created_at": _now(), "storage_class": "fixed", "retention_policy": "context-handoff-history"})
        _write(envelope, dataset, item)
        generated.append({"type": item["source_record_type"], "record_id": item["record_id"], "title": item["title"]})
    return {"conversation_id": conversation_id, "project_id": project_id, "generated_files": generated, "next_action": "create_or_switch_next_session"}


def _generate_artifact(envelope: dict[str, Any], kind: str, source: dict[str, Any]) -> str:
    instructions = {
        "work_report": "生成工作汇报。只保留已完成事项、关键结论、产出、风险和建议写入传承包事项。返回 JSON: {content:string}。",
        "handoff_file": "生成工作交接文件。只保留未完成事项、下一步、必读文件、风险和必要背景。返回 JSON: {content:string}。",
        "inheritance_package": "升级 Project 传承包。合并旧传承包和本轮工作汇报，保留项目主线、关键结论、文件索引、待办和风险。返回 JSON: {content:string}。",
    }
    request = {"task_type": "context_handoff_generation", "messages": [{"role": "system", "content": instructions[kind]}, {"role": "user", "content": json.dumps(source, ensure_ascii=False)}], "model_policy": {"temperature": 0.1, "max_output_tokens": 2500, "allow_fallback": False}}
    data = _foundation(envelope, "model.respond", request)
    if str(data.get("provider") or "") == "local-mock":
        raise ContextError("MODEL_UNAVAILABLE_FOR_CONTEXT_HANDOFF", "模型未就绪，不能生成可信的收口材料", status=503, retryable=True)
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    content = str(output.get("content") or "").strip()
    if not content:
        raise ContextError("CONTEXT_ARTIFACT_GENERATION_FAILED", "模型没有返回有效的收口材料", status=502, retryable=True)
    return content


def _import_material(envelope: dict[str, Any], payload: dict[str, Any], *, cross_project: bool) -> dict[str, Any]:
    tenant_id, owner, project_id, _ = _identity(envelope, payload)
    target_conversation_id = str(payload.get("target_conversation_id") or "")
    source_record_id = str(payload.get("source_record_id") or "")
    source_record_type = str(payload.get("source_record_type") or "")
    source_project_id = str(payload.get("source_project_id") or project_id)
    if not project_id or not target_conversation_id or not source_record_id or not source_record_type:
        raise ContextError("CONTEXT_IMPORT_FIELDS_REQUIRED", "导入需要目标对话、来源记录和来源类型")
    if not cross_project and source_project_id != project_id:
        raise ContextError("CROSS_PROJECT_IMPORT_REQUIRES_REFERENCE", "跨 Project 材料必须先在总指挥中心确认引用", status=403)
    dataset = "context_cross_project_references" if cross_project else "context_imports"
    record_id = f"ctx-import-{uuid4().hex[:16]}"
    record = {"record_id": record_id, "import_id": record_id, "reference_id": record_id, "tenant_id": tenant_id, "owner_account_id": owner, "project_id": project_id, "target_project_id": project_id, "target_conversation_id": target_conversation_id, "source_project_id": source_project_id, "source_record_id": source_record_id, "source_record_type": source_record_type, "title": str(payload.get("title") or source_record_type), "content": str(payload.get("content") or ""), "imported_at": _now(), "storage_class": "fixed", "retention_policy": "context-import-history"}
    _write(envelope, dataset, record)
    if cross_project:
        _write(envelope, "context_imports", record)
    return {"import_id": record_id, "target_conversation_id": target_conversation_id, "source_record_id": source_record_id, "state": "imported"}


def _search(envelope: dict[str, Any], payload: dict[str, Any], *, account_scope: bool) -> dict[str, Any]:
    _, owner, project_id, _ = _identity(envelope, payload)
    visible = payload.get("visible_project_ids") if isinstance(payload.get("visible_project_ids"), list) else [project_id]
    allowed_projects = {str(item) for item in visible if str(item)} if account_scope else {project_id}
    datasets = ("conversation_messages", "context_work_reports", "context_handoff_files", "context_inheritance_packages")
    query = str(payload.get("query") or "").strip().lower()
    matches: list[dict[str, Any]] = []
    for dataset in datasets:
        for item in _query(envelope, dataset, {"owner_account_id": owner}, 500):
            if str(item.get("project_id") or "") not in allowed_projects:
                continue
            text = " ".join(str(item.get(key) or "") for key in ("title", "content", "content_text", "text"))
            if query and query not in text.lower():
                continue
            record_id = str(item.get("record_id") or item.get("message_id") or "")
            matches.append({"dataset": dataset, "record_id": record_id, "project_id": item.get("project_id"), "conversation_id": item.get("conversation_id"), "message_id": item.get("message_id"), "title": item.get("title") or item.get("original_name") or dataset, "snippet": text[:240], "jump_target": {"project_id": item.get("project_id"), "conversation_id": item.get("conversation_id"), "message_id": item.get("message_id")}})
    return {"scope": "account" if account_scope else "project", "matches": matches[:50], "count": min(len(matches), 50)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
