from __future__ import annotations

from datetime import datetime
from typing import Any

from .mock_data import ACTION_CATALOG, SOURCE_MATERIALS, TEMPLATES, USERS
from .audit_log import write_log


def _object_name(data_object_id: str) -> str:
    if data_object_id in SOURCE_MATERIALS:
        return SOURCE_MATERIALS[data_object_id]["name"]
    if data_object_id in TEMPLATES:
        return TEMPLATES[data_object_id]["name"]
    if data_object_id.startswith("TASK-"):
        return "内容产出任务"
    if data_object_id.startswith("DRAFT-") or data_object_id.startswith("CPR-"):
        return "内容成果"
    return data_object_id


def check_permission(actor_id: str, data_object_id: str, action: str, task_id: str | None = None) -> dict[str, Any]:
    actor = USERS.get(actor_id)
    action_meta = ACTION_CATALOG.get(action, {"label": action, "registered": False, "risk": "unknown"})
    result = "deny"
    reason = "无明确依据，默认禁止。"

    if not actor:
        reason = "当前真人不存在，无法完成权限判定。"
    elif not action_meta.get("registered"):
        reason = f"动作 {action} 未登记到动作清单，按默认禁止处理。"
    elif not actor["permissions"].get(action, False):
        reason = f"当前真人 {actor['name']}（{actor['position']}）不具备动作“{action_meta['label']}”权限。"
    elif data_object_id in SOURCE_MATERIALS and action not in SOURCE_MATERIALS[data_object_id].get("allowed_actions", []):
        reason = f"数据对象“{SOURCE_MATERIALS[data_object_id]['name']}”未开放动作“{action_meta['label']}”。"
    elif data_object_id in TEMPLATES and action != "use_template":
        reason = f"模板对象只允许通过 use_template 动作取用，当前动作不匹配。"
    elif data_object_id in TEMPLATES and TEMPLATES[data_object_id]["state"] != "active":
        reason = f"模板“{TEMPLATES[data_object_id]['name']}”状态为 {TEMPLATES[data_object_id]['state']}，不可取用。"
    else:
        result = "allow"
        reason = f"四要素通过：当前时间、真人 {actor['name']}、数据对象“{_object_name(data_object_id)}”、动作“{action_meta['label']}”均满足。"

    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "actor_id": actor_id,
        "actor_name": actor["name"] if actor else "",
        "real_person_id": actor["real_person_id"] if actor else "",
        "position": actor["position"] if actor else "",
        "data_object_id": data_object_id,
        "data_object_name": _object_name(data_object_id),
        "action": action,
        "action_label": action_meta["label"],
        "registered_action": bool(action_meta.get("registered")),
        "risk": action_meta.get("risk", "unknown"),
        "result": result,
        "reason": reason,
    }
    write_log(task_id, actor_id, f"permission:{action}", data_object_id, result, reason, layer="L1-1.1")
    return record
