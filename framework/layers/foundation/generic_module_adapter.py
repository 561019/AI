from __future__ import annotations

from typing import Any

from framework.adapter_proxy import invoke_adapter
from framework.core import standard_response
from framework.module_catalog import MODULE_BY_CODE


def get_for(module_code: str, handler: Any) -> bool:
    module = MODULE_BY_CODE[module_code]
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in module.capabilities]})
        return True
    return False


def post_for(module_code: str, handler: Any, envelope: dict[str, Any]) -> None:
    module = MODULE_BY_CODE[module_code]
    if handler.path != module.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = (
        envelope.get("target", {}).get("capability")
        or envelope.get("action")
        or envelope.get("payload", {}).get("action")
        or module.capabilities[0]
    )
    if capability not in module.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={
            "code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE",
            "capability": capability,
            "provider_module": module.code,
        }))
        return
    payload = envelope.get("payload", {})
    upstream_status, upstream_data = invoke_adapter(module.code, capability, envelope)
    if upstream_status != 404:
        handler.send(200 if 200 <= upstream_status < 300 else upstream_status, standard_response(
            envelope,
            "success" if 200 <= upstream_status < 300 else "failed",
            data=upstream_data if 200 <= upstream_status < 300 else None,
            error=upstream_data.get("upstream_response", {}).get("error") if isinstance(upstream_data.get("upstream_response"), dict) else upstream_data,
        ))
        return
    handler.send(200, standard_response(envelope, "success", data={
        "state": "completed",
        "module": module.code,
        "module_name_cn": module.name_cn,
        "platform_capability": capability,
        "integration_status": module.integration_status,
        "delivery_root": module.delivery_root,
        "notes": module.notes,
        "received_payload": payload,
        "normalized_task": {
            "capability_code": capability,
            "source_action": payload.get("action") or envelope.get("action"),
            "interface": module.interface,
        },
        "adapter_message": "模块已进入 L1 标准入口。真实业务字段联调时可在该适配器内替换为交付模块真实调用。",
    }))
