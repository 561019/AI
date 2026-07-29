from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from .mock_data import SCENARIOS, TEMPLATES, USERS
from .store import registry_store


def result_id_for_task(task: dict[str, Any]) -> str:
    return task.get("result_id") or ("CPR-" + task["task_id"].split("-")[-1])


def create_registry(task: dict[str, Any]) -> dict[str, Any]:
    scenario = SCENARIOS[task["scenario_id"]]
    actor = USERS[task["actor_id"]]
    template = TEMPLATES.get(scenario["template_id"], {})
    registry_id = "REG-" + uuid.uuid4().hex[:8].upper()
    result_id = result_id_for_task(task)
    registry = {
        "registry_id": registry_id,
        "result_id": result_id,
        "task_id": task["task_id"],
        "trace_id": task["trace_id"],
        "content_type": scenario["content_type_label"],
        "title": task.get("drafts", [{}])[0].get("title", scenario["title"]),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "created_by": {
            "actor_id": task["actor_id"],
            "real_person_id": actor["real_person_id"],
            "name": actor["name"],
            "position": actor["position"],
        },
        "template": {
            "template_id": scenario["template_id"],
            "template_name": template.get("name"),
            "template_version": template.get("version"),
        },
        "status_group": {
            "data_status": "registered_mock",
            "workflow_status": "pending_review" if task.get("exit_type") == "pending_human_confirmation" else "completed",
            "review_status": task.get("review_status", "not_required"),
        },
        "file_store": {
            "uri": f"file://content-production/{result_id}.docx",
            "note": "v0.1 仅登记 mock 文件 URI，不生成真实业务文档。",
        },
        "structured_catalog": {
            "uri": f"catalog://content-production/{result_id}",
            "fields": {
                "content_type": scenario["content_type"],
                "risk_level": scenario["risk_level"],
                "template_id": scenario["template_id"],
                "source_material_refs": scenario["source_material_refs"],
                "draft_count": len(task.get("drafts", [])),
                "exit_type": task.get("exit_type"),
            },
        },
        "semantic_store": {
            "uri": f"semantic://content-production/{result_id}",
            "summary": task.get("semantic_summary", ""),
            "keywords": task.get("semantic_keywords", []),
        },
        "ai_labels": task.get("labels", {}),
        "audit_refs": {
            "model_task_id": task.get("model_dispatch", {}).get("model_task_id"),
            "prompt_version": task.get("prompt_context", {}).get("prompt_version"),
            "cost_record_id": task.get("cost_record", {}).get("cost_record_id"),
        },
    }
    data = registry_store.read()
    data[registry_id] = registry
    registry_store.write(data)
    return registry


def update_registry_status(registry_id: str, workflow_status: str, review_status: str, note: str) -> dict[str, Any] | None:
    data = registry_store.read()
    registry = data.get(registry_id)
    if not registry:
        return None
    registry["status_group"]["workflow_status"] = workflow_status
    registry["status_group"]["review_status"] = review_status
    registry.setdefault("status_history", []).append(
        {"time": datetime.now().isoformat(timespec="seconds"), "workflow_status": workflow_status, "review_status": review_status, "note": note}
    )
    data[registry_id] = registry
    registry_store.write(data)
    return registry
