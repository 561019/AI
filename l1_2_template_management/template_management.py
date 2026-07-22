from __future__ import annotations

import copy
from datetime import datetime, timezone
from threading import RLock
from typing import Any


REGISTERED_SERVICES = {
    "template.register_draft": {"request_type": "maintain", "description": "登记流程模板草稿"},
    "template.update_draft": {"request_type": "maintain", "description": "修改流程模板草稿并生成新版本"},
    "template.validate": {"request_type": "query", "description": "校验流程模板定义"},
    "template.publish": {"request_type": "maintain", "description": "发布指定模板版本"},
    "template.disable": {"request_type": "maintain", "description": "停用指定模板"},
    "template.retrieve": {"request_type": "query", "description": "读取流程模板版本"},
    "template.list": {"request_type": "query", "description": "查询流程模板"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryTemplateRepository:
    """Thread-safe versioned template repository used by the local full-flow runtime."""

    def __init__(self) -> None:
        self._items: dict[str, list[dict[str, Any]]] = {}
        self._lock = RLock()

    def save(self, template: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            versions = self._items.setdefault(template["template_id"], [])
            stored = copy.deepcopy(template)
            versions.append(stored)
            return copy.deepcopy(stored)

    def versions(self, template_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._items.get(template_id, []))

    def replace(self, template_id: str, version: int, value: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            versions = self._items.get(template_id, [])
            for index, item in enumerate(versions):
                if item["version"] == version:
                    versions[index] = copy.deepcopy(value)
                    return copy.deepcopy(value)
        raise KeyError("template_version_not_found")

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy([item for versions in self._items.values() for item in versions])


class TemplateManagementService:
    def __init__(self, repository: InMemoryTemplateRepository) -> None:
        self.repository = repository

    def handle_instruction(self, instruction: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(instruction.get("trace_id") or "")
        service = str(instruction.get("service_name") or "")
        payload = instruction.get("payload") if isinstance(instruction.get("payload"), dict) else {}
        registration = REGISTERED_SERVICES.get(service)
        if not registration:
            return self._error(trace_id, service, "service_not_registered")
        if instruction.get("request_type") != registration["request_type"]:
            return self._error(trace_id, service, f"request_type_must_be_{registration['request_type']}")
        try:
            if service == "template.register_draft": result = self._register(payload, instruction)
            elif service == "template.update_draft": result = self._update(payload, instruction)
            elif service == "template.validate": result = self.validate(payload.get("definition") or self._retrieve(payload)["definition"])
            elif service == "template.publish": result = self._transition(payload, "published", instruction)
            elif service == "template.disable": result = self._transition(payload, "disabled", instruction)
            elif service == "template.retrieve": result = self._retrieve(payload)
            else: result = self._list(payload)
        except (KeyError, ValueError) as exc:
            return self._error(trace_id, service, str(exc).strip("'"))
        return {"ok": True, "trace_id": trace_id, "service_name": service, "result": result}

    def _register(self, payload: dict[str, Any], instruction: dict[str, Any]) -> dict[str, Any]:
        template_id = str(payload.get("template_id") or "").strip()
        definition = payload.get("definition")
        if not template_id: raise ValueError("template_id_required")
        validation = self.validate(definition)
        if not validation["valid"]: raise ValueError("template_definition_invalid:" + ",".join(validation["errors"]))
        versions = self.repository.versions(template_id)
        version = max((item["version"] for item in versions), default=0) + 1
        now = _now()
        record = {"template_id": template_id, "version": version, "name": str(definition.get("name") or template_id), "category": str(definition.get("category") or "business_process"), "status": "draft", "definition": copy.deepcopy(definition), "created_by": str(instruction.get("actor_id") or "system"), "created_at": now, "updated_at": now}
        return self.repository.save(record)

    def _update(self, payload: dict[str, Any], instruction: dict[str, Any]) -> dict[str, Any]:
        return self._register(payload, instruction)

    def _transition(self, payload: dict[str, Any], status: str, instruction: dict[str, Any]) -> dict[str, Any]:
        record = self._retrieve({**payload, "purpose": "maintenance"})
        if status == "published":
            validation = self.validate(record["definition"])
            if not validation["valid"]: raise ValueError("template_definition_invalid")
            for item in self.repository.versions(record["template_id"]):
                if item["status"] == "published" and item["version"] != record["version"]:
                    item["status"] = "superseded"; item["updated_at"] = _now()
                    self.repository.replace(item["template_id"], item["version"], item)
        record["status"] = status
        record["updated_by"] = str(instruction.get("actor_id") or "system")
        record["updated_at"] = _now()
        return self.repository.replace(record["template_id"], record["version"], record)

    def _retrieve(self, payload: dict[str, Any]) -> dict[str, Any]:
        template_id = str(payload.get("template_id") or "")
        versions = self.repository.versions(template_id)
        if not versions: raise KeyError("template_not_found")
        if payload.get("version") is not None:
            record = next((item for item in versions if item["version"] == int(payload["version"])), None)
        elif payload.get("purpose") == "new_start":
            published = [item for item in versions if item["status"] == "published"]
            record = max(published, key=lambda item: item["version"], default=None)
        else:
            record = max(versions, key=lambda item: item["version"])
        if not record: raise KeyError("published_template_not_found")
        return record

    def _list(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self.repository.all()
        if payload.get("status"): items = [item for item in items if item["status"] == payload["status"]]
        if payload.get("category"): items = [item for item in items if item["category"] == payload["category"]]
        return {"items": sorted(items, key=lambda item: (item["template_id"], item["version"])), "count": len(items)}

    @staticmethod
    def validate(definition: Any) -> dict[str, Any]:
        errors: list[str] = []
        if not isinstance(definition, dict): return {"valid": False, "errors": ["definition_must_be_object"]}
        for field in ("template_id", "name", "owner_position", "steps"):
            if not definition.get(field): errors.append(f"{field}_required")
        steps = definition.get("steps")
        if not isinstance(steps, list) or not steps: errors.append("steps_must_be_non_empty_list"); steps = []
        ids: list[str] = []
        allowed = {"auto", "human_approval", "human_notify", "condition"}
        for index, step in enumerate(steps):
            if not isinstance(step, dict): errors.append(f"step_{index}_must_be_object"); continue
            step_id = str(step.get("step_id") or "")
            if not step_id: errors.append(f"step_{index}_id_required")
            elif step_id in ids: errors.append(f"duplicate_step_id:{step_id}")
            ids.append(step_id)
            if step.get("type") not in allowed: errors.append(f"unsupported_step_type:{step.get('type')}")
            if step.get("type") == "auto" and not (step.get("service_ref") or step.get("l2_engine_ref")): errors.append(f"service_ref_required:{step_id}")
            if step.get("type") == "human_approval" and not step.get("approval_position"): errors.append(f"approval_position_required:{step_id}")
        known = set(ids)
        for step in steps:
            if isinstance(step, dict):
                for dependency in step.get("depends_on") or []:
                    if dependency not in known: errors.append(f"unknown_dependency:{dependency}")
        return {"valid": not errors, "errors": errors, "step_count": len(steps)}

    @staticmethod
    def _error(trace_id: str, service: str, code: str) -> dict[str, Any]:
        return {"ok": False, "trace_id": trace_id, "service_name": service, "error": {"code": code, "message": code}}


def seed_common_templates(service: TemplateManagementService) -> None:
    templates = [
        ("monthly_commission_accrual", "月度提成计提", "finance_accrual_owner", [("calculate", "auto", "L2.rule_engine.contract_payment_match"), ("review", "human_approval", "finance_accrual_owner")]),
        ("procurement_plan_compare_contract", "采购计划比价", "procurement_template_owner", [("compare", "auto", "L2.rule_engine.procurement_compare"), ("review", "human_approval", "procurement_template_owner")]),
        ("procurement_order_review", "采购订单审核", "procurement_template_owner", [("review", "human_approval", "procurement_template_owner")]),
        ("supplier_payment_approval", "供应商付款审批", "procurement_payment_owner", [("match", "auto", "L2.rule_engine.contract_payment_match"), ("approve", "human_approval", "procurement_payment_owner")]),
        ("marketing_content_release_review", "营销内容发布审核", "marketing_template_owner", [("generate", "auto", "L2.content.generate"), ("review", "human_approval", "marketing_template_owner")]),
        ("attendance_exception_review", "考勤异常审核", "attendance_owner", [("review", "human_approval", "attendance_owner")]),
        ("invoice_after_payment_followup", "付款后发票跟进", "finance_owner", [("notify", "human_notify", "finance_owner")]),
    ]
    for template_id, name, owner, raw_steps in templates:
        steps = []
        for index, (step_id, kind, target) in enumerate(raw_steps):
            step = {"step_id": step_id, "type": kind, "name": step_id.replace("_", " "), "depends_on": [raw_steps[index - 1][0]] if index else []}
            if kind == "auto": step["service_ref"] = target
            elif kind == "human_approval": step["approval_position"] = target
            else: step["notify_position"] = target
            steps.append(step)
        definition = {"template_id": template_id, "name": name, "category": "fixed_business_process", "owner_position": owner, "applicable_scope": {"fixed_flow": True}, "version_policy": {"new_start": "latest_published", "in_flight": "keep_original_version"}, "rejection_policy": {"default": "end"}, "policy_file_refs": [], "steps": steps}
        registered = service.handle_instruction({"service_name": "template.register_draft", "request_type": "maintain", "actor_id": "system", "trace_id": f"seed-{template_id}", "payload": {"template_id": template_id, "definition": definition}})
        if registered.get("ok"):
            service.handle_instruction({"service_name": "template.publish", "request_type": "maintain", "actor_id": "system", "trace_id": f"seed-{template_id}", "payload": {"template_id": template_id, "version": registered["result"]["version"]}})
