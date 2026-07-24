from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import urllib.error
import urllib.request
from typing import Any

from framework.core import connect
from framework.data_catalog import DATASETS
from framework.module_catalog import MODULE_BY_CODE
from framework.run_services import SERVICES


CORE_MODULES: dict[str, dict[str, str]] = {
    "application": {"name_cn": "应用网关", "layer": "business_application", "kind": "platform_gateway"},
    "engine": {"name_cn": "业务引擎网关", "layer": "business_engine", "kind": "platform_gateway"},
    "foundation": {"name_cn": "基础能力网关", "layer": "foundation", "kind": "platform_gateway"},
    "intent": {"name_cn": "意图分析适配器", "layer": "business_engine", "kind": "platform_adapter"},
    "intent_original": {"name_cn": "意图分析交付引擎", "layer": "business_engine", "kind": "delivered_engine"},
    "workflow": {"name_cn": "流程执行适配器", "layer": "business_engine", "kind": "platform_adapter"},
    "workflow_original": {"name_cn": "流程执行交付引擎", "layer": "business_engine", "kind": "delivered_engine"},
    "rule": {"name_cn": "规则计算适配器", "layer": "business_engine", "kind": "platform_adapter"},
    "rule_original": {"name_cn": "规则计算交付引擎", "layer": "business_engine", "kind": "delivered_engine"},
    "content": {"name_cn": "内容生产适配器", "layer": "business_engine", "kind": "platform_adapter"},
    "content_original": {"name_cn": "内容生产交付引擎", "layer": "business_engine", "kind": "delivered_engine"},
    "permission": {"name_cn": "权限适配器", "layer": "foundation", "kind": "platform_core"},
    "model": {"name_cn": "模型调度器", "layer": "foundation", "kind": "platform_core"},
    "registry": {"name_cn": "能力登记中心", "layer": "foundation", "kind": "platform_core"},
    "template": {"name_cn": "流程模板管理", "layer": "foundation", "kind": "platform_core"},
}


def build_overview() -> dict[str, Any]:
    modules = _module_entries()
    with ThreadPoolExecutor(max_workers=12) as executor:
        health = dict(executor.map(lambda item: (item["service"], _health(item["health_url"])), modules))
    for module in modules:
        module["health"] = health[module["service"]]

    with connect() as db:
        capability_rows = db.execute(
            "SELECT provider_module, COUNT(*) AS count FROM capabilities WHERE enabled = 1 GROUP BY provider_module"
        ).fetchall()
        capability_counts = {row["provider_module"]: row["count"] for row in capability_rows}
        recent_calls = [dict(row) for row in db.execute(
            """SELECT call_id, trace_id, source_module, target_module, capability, method, url, status_code, duration_ms, created_at
               FROM interface_calls ORDER BY created_at DESC LIMIT 80"""
        ).fetchall()]
        task_rows = db.execute("SELECT state, COUNT(*) AS count FROM tasks GROUP BY state").fetchall()

    for module in modules:
        module["registered_capability_count"] = capability_counts.get(module["provider_module"], 0)

    task_counts = {row["state"]: row["count"] for row in task_rows}
    online = sum(1 for item in modules if item["health"]["state"] == "online")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "service_count": len(modules),
            "online_count": online,
            "offline_count": len(modules) - online,
            "capability_count": sum(item["registered_capability_count"] for item in modules),
            "task_counts": task_counts,
        },
        "modules": modules,
        "recent_calls": recent_calls,
        "datasets": [
            {
                "name": item.code,
                "owner_module": item.owner_module,
                "classification": item.classification,
                "retention_policy": item.retention_policy,
                "sensitive": item.sensitive,
            }
            for item in DATASETS
        ],
    }


def _module_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for service, (implementation, port) in SERVICES.items():
        catalog = MODULE_BY_CODE.get(service.replace("_", "-"))
        core = CORE_MODULES.get(service, {})
        layer = catalog.layer if catalog else core.get("layer", _layer_from_implementation(implementation))
        entries.append({
            "service": service,
            "code": service.replace("_", "-"),
            "name_cn": catalog.name_cn if catalog else core.get("name_cn", service),
            "layer": layer,
            "kind": core.get("kind", "module"),
            "port": port,
            "interface": catalog.interface if catalog else "/health",
            "health_url": f"http://127.0.0.1:{port}/health",
            "provider_module": catalog.code if catalog else service.replace("_", "-"),
            "integration_status": catalog.integration_status if catalog else "platform_core",
            "capabilities": list(catalog.capabilities) if catalog else [],
        })
    return entries


def _layer_from_implementation(implementation: str) -> str:
    if ".business_application." in implementation:
        return "business_application"
    if ".business_engine." in implementation:
        return "business_engine"
    return "foundation"


def _health(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=0.8) as response:
            return {"state": "online" if response.status == 200 else "degraded", "status_code": response.status}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"state": "offline", "status_code": None, "detail": str(exc)}
