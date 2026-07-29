from __future__ import annotations

import time
import zipfile
from pathlib import Path
from typing import Any


EVIDENCE_FILES = [
    {
        "id": "ui-run-task",
        "name": "运行任务页截图",
        "path": "docs/evidence/ui-run-task.png",
        "type": "screenshot",
        "proves": "小界面 Demo 能提交沙箱任务，并展示 20 个汉和场景模板。",
    },
    {
        "id": "ui-verification",
        "name": "验收演示页截图",
        "path": "docs/evidence/ui-verification.png",
        "type": "screenshot",
        "proves": "现场验收页能展示 Docker 隔离、出站、浏览器、凭据和岗位场景验证项。",
    },
    {
        "id": "ui-monitor",
        "name": "沙箱监控页截图",
        "path": "docs/evidence/ui-monitor.png",
        "type": "screenshot",
        "proves": "监控页能查看沙箱实例、状态、权限、成本、审计和结果文件线索。",
    },
    {
        "id": "ui-tasks",
        "name": "执行记录页截图",
        "path": "docs/evidence/ui-tasks.png",
        "type": "screenshot",
        "proves": "任务记录页能复查输入、输出、运行限制、日志和平台链路证据。",
    },
    {
        "id": "ui-policy",
        "name": "安全边界与合规页截图",
        "path": "docs/evidence/ui-policy.png",
        "type": "screenshot",
        "proves": "合规页能展示研发方案覆盖情况和客观验收检查结果。",
    },
    {
        "id": "api-acceptance",
        "name": "验收接口快照",
        "path": "docs/evidence/api-acceptance.json",
        "type": "api_snapshot",
        "proves": "保存 /api/acceptance 的真实返回，用于复查 passed/future 口径。",
    },
    {
        "id": "api-compliance",
        "name": "合规接口快照",
        "path": "docs/evidence/api-compliance.json",
        "type": "api_snapshot",
        "proves": "保存 /api/compliance 的真实返回，用于复查研发方案覆盖项。",
    },
    {
        "id": "api-delivery-checklist",
        "name": "交付清单接口快照",
        "path": "docs/evidence/api-delivery-checklist.json",
        "type": "api_snapshot",
        "proves": "保存 /api/delivery/checklist 的真实返回，用于复查交付项状态。",
    },
    {
        "id": "api-role-scenario",
        "name": "岗位场景接口快照",
        "path": "docs/evidence/api-role-scenario.json",
        "type": "api_snapshot",
        "proves": "保存 /api/delivery/role-scenario 的真实返回，用于复查汉和岗位场景输入输出。",
    },
]


def delivery_checklist(project_root: Path | None = None) -> dict[str, Any]:
    evidence = delivery_evidence_manifest(project_root)
    evidence_status = "done" if evidence["summary"]["missing"] == 0 else "ready"
    evidence_text = (
        "docs/DELIVERY_EVIDENCE.md + docs/evidence/*"
        if evidence_status == "done"
        else "docs/evidence/* evidence files are defined and can be generated"
    )
    items = [
        done("模块说明", "docs/MODULE_SPEC.md"),
        done("边界说明", "docs/BOUNDARY_SPEC.md"),
        done("输入输出说明", "docs/MODULE_SPEC.md"),
        done("API/接口说明", "docs/API_SPEC.md"),
        done("小界面 Demo", "http://10.60.66.97:8765/"),
        done("场景测试数据", "scenario_templates/scenarios.json + mock ERP/OA payloads"),
        done("测试用例", "/api/verification and /api/acceptance"),
        done("测试结果文档", "docs/TEST_REPORT.md"),
        item("截图/证据", evidence_status, evidence_text),
        done("当前限制", "docs/MODULE_SPEC.md and docs/PLAN_COMPLIANCE.md"),
        done("后续模块集成说明", "docs/INTEGRATION_PREP_TABLE.md"),
        done("联调准备表", "docs/INTEGRATION_PREP_TABLE.md"),
    ]
    return {
        "module": "L1 1.14 执行沙箱",
        "delivery_form": "Docker-runtime capability package",
        "current_runtime": "DockerTemplateExecutor",
        "cube_position": "future stronger-isolation option, not current blocker",
        "evidence_summary": evidence["summary"],
        "summary": {
            "done": sum(1 for item in items if item["status"] == "done"),
            "ready": sum(1 for item in items if item["status"] == "ready"),
            "missing": sum(1 for item in items if item["status"] == "missing"),
        },
        "items": items,
    }


def delivery_evidence_manifest(project_root: Path | None = None) -> dict[str, Any]:
    files = []
    for spec in EVIDENCE_FILES:
        exists = False
        size_bytes = None
        updated_at = None
        if project_root is not None:
            target = project_root / spec["path"]
            exists = target.exists() and target.is_file()
            if exists:
                stat = target.stat()
                size_bytes = stat.st_size
                updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
        files.append({**spec, "exists": exists, "size_bytes": size_bytes, "updated_at": updated_at})

    missing = [file for file in files if not file["exists"]]
    return {
        "module": "L1 1.14 执行沙箱",
        "purpose": "formal delivery evidence bundle for demo, testing, verification, and later platform integration",
        "status": "done" if not missing else "ready",
        "summary": {
            "total": len(files),
            "present": len(files) - len(missing),
            "missing": len(missing),
        },
        "files": files,
        "report": "docs/DELIVERY_EVIDENCE.md",
        "generation_note": "Screenshots are generated from the running Demo UI; API snapshots are generated from live endpoints.",
    }


def delivery_package(project_root: Path | None = None) -> dict[str, Any]:
    export = delivery_export_manifest(project_root)
    return {
        "module": "L1 1.14 执行沙箱",
        "delivery_form": "Docker-runtime capability package",
        "current_runtime": "DockerTemplateExecutor",
        "runtime_decision": "Docker is accepted as the current delivery runtime; Cube Sandbox is tracked as a future stronger-isolation option.",
        "checklist": delivery_checklist(project_root),
        "evidence": delivery_evidence_manifest(project_root),
        "export": export,
        "role_scenario": role_scenario_spec(),
        "integration_contracts": integration_contracts(),
        "docs": delivery_docs(),
    }


def delivery_export_manifest(project_root: Path | None = None) -> dict[str, Any]:
    rel = "docs/evidence/delivery-package.zip"
    exists = False
    size_bytes = None
    updated_at = None
    if project_root is not None:
        target = project_root / rel
        exists = target.exists() and target.is_file()
        if exists:
            stat = target.stat()
            size_bytes = stat.st_size
            updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
    return {
        "status": "done" if exists else "ready",
        "path": rel,
        "download_url": "/api/delivery/export.zip",
        "exists": exists,
        "size_bytes": size_bytes,
        "updated_at": updated_at,
    }


def create_delivery_export(project_root: Path) -> dict[str, Any]:
    evidence = delivery_evidence_manifest(project_root)
    export_rel = "docs/evidence/delivery-package.zip"
    export_path = project_root / export_rel
    export_path.parent.mkdir(parents=True, exist_ok=True)
    package_json = json_safe(delivery_package(project_root))

    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("delivery-package.json", package_json)
        for rel in delivery_docs():
            add_if_exists(archive, project_root, rel)
        for file in evidence["files"]:
            add_if_exists(archive, project_root, file["path"])
        report_dir = project_root / "docs" / "evidence" / "reports"
        if report_dir.exists():
            for path in sorted(report_dir.glob("verification-report-*.*")):
                archive.write(path, path.relative_to(project_root).as_posix())

    stat = export_path.stat()
    return {
        "status": "done",
        "path": export_rel,
        "download_url": "/api/delivery/export.zip",
        "size_bytes": stat.st_size,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "included": {
            "docs": delivery_docs(),
            "evidence_files": [file["path"] for file in evidence["files"] if file["exists"]],
        },
    }


def delivery_docs() -> list[str]:
    return [
        "README.md",
        "docs/MODULE_SPEC.md",
        "docs/BOUNDARY_SPEC.md",
        "docs/API_SPEC.md",
        "docs/TEST_REPORT.md",
        "docs/PLAN_COMPLIANCE.md",
        "docs/INTEGRATION_PREP_TABLE.md",
        "docs/DELIVERY_EVIDENCE.md",
        "docs/DELIVERY_NOTES.md",
        "docs/ROADMAP.md",
    ]


def add_if_exists(archive: zipfile.ZipFile, project_root: Path, rel: str) -> None:
    target = project_root / rel
    if target.exists() and target.is_file():
        archive.write(target, rel)


def json_safe(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


def role_scenario_spec() -> dict[str, Any]:
    return {
        "id": "hanhe_sales_over_stock_e2e",
        "title": "销售/供应链跨部门同时下单超库存预警",
        "source_scenario": "s19_over_stock_warning",
        "role": {
            "actor": "sales-user",
            "department": "销售部",
            "job": "销售员",
            "permissions_required": ["inventory:read", "order:read"],
        },
        "business_problem": "雅拉御品 K2O_52%_25kg 库存 50 吨，三个部门同时下单合计 90 吨，若不能及时发现会造成找车、报计划、改单和沟通成本。",
        "input": {
            "scenario_id": "s19_over_stock_warning",
            "actor": "sales-user",
            "agent": "hanhe-supply-chain-agent",
            "timeout_seconds": 10,
            "memory_mb": 512,
            "cpu_cores": 1,
            "input": {},
        },
        "mock_business_data": {
            "inventory": 50,
            "orders": [
                {"department": "销售一部", "qty": 30},
                {"department": "销售二部", "qty": 30},
                {"department": "销售三部", "qty": 30},
            ],
        },
        "expected_result": {
            "total_order_qty": 90,
            "over_qty": 40,
            "status": "warning",
        },
        "proves": [
            "账号/岗位解析",
            "权限预检查",
            "mock ERP 库存和订单注入",
            "Docker 沙箱隔离执行",
            "结果收集",
            "成本记录",
            "审计留痕",
            "UI/API 可验证",
        ],
    }


def integration_contracts() -> dict[str, Any]:
    modules = [
        contract("1.4 驾驭机制", "决定任务是否允许执行、最大步数、人工审批、终止策略", "调用前置策略接口或在 POST /api/tasks 前给出 allow/deny 结论"),
        contract("1.5 大模型调度", "统一模型调用入口、模型凭据、模型调用限额", "沙箱内模型调用应通过 1.5 代理，不直连模型服务"),
        contract("1.8 账号网关", "用户、岗位、部门、租户、角色权限", "替换当前 mock account gateway，填充 actor 信息"),
        contract("1.9 安全合规", "出站白名单、凭据注入策略、审计策略、敏感数据规则", "替换当前 egress/credential validation broker，提供真实策略和密钥句柄"),
        contract("1.10 设备与系统接口", "ERP/OA/CRM/数据库适配器、测试账号、测试数据", "替换 mock ERP/OA 数据注入，所有业务系统访问经 1.10"),
        contract("1.12 成本管控", "成本计量接口、计费规则、看板字段", "接收每个沙箱任务的 CPU/内存/时长/任务数成本记录"),
        contract("L2 流程自动操作引擎", "按服务目录组装请求、携带追踪编号、任务编排、失败重试、轮询或回调方式", "经基础模块层接口调用 /api/v1/layer-interface/requests 并取回结果"),
    ]
    return {
        "module": "L1 1.14 执行沙箱",
        "preferred_platform_api": "/api/v1/layer-interface/requests",
        "current_api_options": ["/api/v1/layer-interface/requests", "/api/tasks", "/api/e2b/*"],
        "contracts": modules,
    }


def done(name: str, evidence: str) -> dict[str, str]:
    return item(name, "done", evidence)


def ready(name: str, evidence: str) -> dict[str, str]:
    return item(name, "ready", evidence)


def item(name: str, status: str, evidence: str) -> dict[str, str]:
    return {"name": name, "status": status, "evidence": evidence}


def contract(module: str, needs_from_module: str, sandbox_side: str) -> dict[str, str]:
    return {
        "module": module,
        "needs_from_module": needs_from_module,
        "sandbox_side": sandbox_side,
        "status": "ready_for_joint_debugging",
    }
