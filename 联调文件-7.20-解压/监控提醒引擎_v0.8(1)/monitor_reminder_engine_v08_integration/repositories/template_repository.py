from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "template_library.json"
)

DEFAULT_TEMPLATE_BY_SCENE = {
    "purchase_node": "TPL_PURCHASE_NODE",
    "metric_warning": "TPL_METRIC_WARNING",
    "complaint_time_limit": "TPL_COMPLAINT_TIME_LIMIT",
    "general": "TPL_GENERAL_WARNING",
}

DEFAULT_TEMPLATE_BY_OBJECT_TYPE = {
    "purchase_plan": "TPL_PURCHASE_NODE",
    "business_metric": "TPL_METRIC_WARNING",
    "complaint": "TPL_COMPLAINT_TIME_LIMIT",
}


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def load_template_library() -> dict[str, Any]:
    with TEMPLATE_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("模板库格式错误：根节点必须是对象")

    templates = data.get("templates")
    if not isinstance(templates, list):
        raise ValueError("模板库格式错误：templates 必须是数组")

    return data


def list_templates() -> list[dict[str, Any]]:
    return list(load_template_library()["templates"])


def get_template(
    template_id: str,
    template_version: str = "",
) -> dict[str, Any] | None:
    candidates = [
        template
        for template in list_templates()
        if template.get("template_id") == template_id
        and template.get("status") == "active"
    ]

    if template_version:
        candidates = [
            template
            for template in candidates
            if template.get("template_version") == template_version
        ]

    if not candidates:
        return None

    return candidates[-1]


def default_template_id(
    *,
    scene_type: str = "",
    object_type: str = "",
) -> str:
    if scene_type in DEFAULT_TEMPLATE_BY_SCENE:
        return DEFAULT_TEMPLATE_BY_SCENE[scene_type]

    if object_type in DEFAULT_TEMPLATE_BY_OBJECT_TYPE:
        return DEFAULT_TEMPLATE_BY_OBJECT_TYPE[object_type]

    return DEFAULT_TEMPLATE_BY_SCENE["general"]


def resolve_template(
    *,
    template_id: str = "",
    template_version: str = "",
    scene_type: str = "",
    object_type: str = "",
) -> dict[str, Any]:
    resolved_id = template_id or default_template_id(
        scene_type=scene_type,
        object_type=object_type,
    )
    template = get_template(resolved_id, template_version)

    if template is None:
        version_text = template_version or "当前生效版本"
        raise ValueError(
            f"固定模板不存在或未启用：{resolved_id}/{version_text}"
        )

    return template


def render_template(
    template: dict[str, Any],
    values: dict[str, Any],
) -> str:
    text = template.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError("固定模板文本为空")

    normalized = {
        key: "" if value is None else value
        for key, value in values.items()
    }
    return text.format_map(_SafeFormatDict(normalized))
