# -*- coding: utf-8 -*-
"""数字资产引擎 MVP 的服务端治理内核。

本模块只负责资产登记、权限判定、固定审批、版本、留痕、知识源状态和
功能登记；不冒充文档解析引擎、计算引擎或业务数据权限系统。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    from .fixed_tools import TOOL_DEFINITIONS, execute_fixed_tool, public_tool_definitions, tool_checksum
except ImportError:  # 兼容直接执行 python engine.py
    from fixed_tools import TOOL_DEFINITIONS, execute_fixed_tool, public_tool_definitions, tool_checksum


ASSET_TYPES = {
    "agent": "Agent",
    "skill": "技能",
    "knowledge_base": "知识库",
}

# 教师最终口径：登记册只有三类一级数字资产。历史 material 行会在
# 初始化时迁移成隐藏的附件兼容记录，避免删除已有演示数据。
LEGACY_ATTACHMENT_TYPE = "legacy_attachment"

SCOPES = {
    "personal": "个人岗位级",
    "department": "部门级",
    "company": "公司级",
}

STATUS_LABELS = {
    "draft": "草稿",
    "personal_active": "个人启用",
    "adopted": "已采纳归档",
    "pending_publish": "待发布审批",
    "published": "已发布",
    "disabled": "已停用",
    "deleted": "已逻辑删除",
}

WORKFLOW_LABELS = {
    "adoption": "部门采纳",
    "department_publish": "部门发布",
    "company_publish": "公司发布",
}

ACTION_LABELS = {
    "read_state": "读取工作台",
    "read_asset": "查看资产",
    "query_asset_registry": "查询资产登记册",
    "create": "创建资产",
    "update": "修改草稿",
    "activate_personal": "个人启用",
    "submit_adoption": "提交部门采纳",
    "submit_publish": "提交发布审批",
    "approve_workflow": "批准工作流",
    "reject_workflow": "驳回工作流",
    "disable": "停用资产",
    "delete_draft": "删除草稿",
    "add_source": "登记知识源",
    "parse_source": "登记解析结果",
    "register_knowledge_source_result": "登记知识源处理回执",
    "request_l1_knowledge_base": "申请L1知识库实例",
    "register_l1_knowledge_base": "登记L1知识库实例回执",
    "register_source_index": "登记知识源索引回执",
    "sync_registry": "同步功能登记库",
    "bind_skill_implementation": "绑定技能实现",
    "submit_skill_development": "提交 Skill 研发需求",
    "register_skill_candidate": "登记 Skill 候选实现",
    "validate_skill": "验证技能绑定",
    "register_skill_model_evaluation": "登记技能主备模型评测",
    "process_flow_task": "接收流程执行引擎任务",
    "execute_skill": "执行技能",
    "execute_agent": "执行 Agent",
    "confirm_execution": "真人确认执行结果",
    "upload_material_file": "上传素材文件",
    "download_material_file": "下载素材文件",
    "upload_knowledge_source": "上传知识库原件",
    "download_knowledge_source": "下载知识库原件",
    "execute_l4_capability": "执行L4真实能力请求",
    "invoke_l4_scenario": "处理 L4 场景请求",
    "reset_demo": "重置演示数据",
}

FUNCTION_TYPES = {"agent", "skill"}

# 对外服务目录。service_code 是流程执行引擎派发本模块任务时使用的
# 路由标识；action 是任务语义。保留早期 digital_asset.create 仅用于
# 旧网页兼容，新增联调一律使用 l2.digital_asset.*。
FLOW_SERVICE_CATALOG = {
    "l2.digital_asset.asset.create": "asset.create",
    "l2.digital_asset.asset.update": "asset.update",
    "l2.digital_asset.asset.delete": "asset.delete",
    "l2.digital_asset.asset.query": "asset.query",
    "l2.digital_asset.skill.model_evaluation.register": "skill.model_evaluation.register",
    "l2.digital_asset.skill.development.request": "skill.development.request",
    "l2.digital_asset.skill.implementation.register": "skill.implementation.register",
    "l2.digital_asset.knowledge_source.register": "knowledge_source.register",
    "l2.digital_asset.knowledge_source.result.register": "knowledge_source.result.register",
}
FLOW_SERVICE_ALIASES = {
    "digital_asset.create": "l2.digital_asset.asset.create",
}

# 《数据流转、对接与通信交互规范 v0.3》规定的正式 L2 对内任务信封。
# 这些字段不能由本引擎临时补齐：它们属于上游流程执行引擎对一次派发的
# 责任声明，也是后续回调、审计和幂等恢复的依据。
FLOW_REQUIRED_TOP_LEVEL = {
    "protocol_version",
    "message_id",
    "trace_id",
    "request_id",
    "parent_message_id",
    "source",
    "target",
    "channel",
    "route_type",
    "action",
    "capability_id",
    "capability_dictionary_version",
    "registry_version",
    "actor",
    "context",
    "idempotency_key",
    "deadline_at",
    "payload",
}
FLOW_REQUIRED_CONTEXT = {"workflow_instance_id", "node_id", "task_id", "data_refs"}

L4_SCENARIOS = {
    "build_process_kb": {
        "title": "工艺资料建设知识库",
        "l4_application": "知识管理人员在资料上传/知识管理界面提出建库或更新请求",
        "request_mode": "natural_language",
        "interface": "L4 对话框 + 资料上传界面",
        "service_code": "asset.knowledge_base.build",
        # Keep the L4 walkthrough isolated from the editable knowledge-base
        # draft used elsewhere in the governance demo.  A user can submit that
        # draft for publication, which must not silently make the L4 scenario
        # stop working or mutate the user's own workflow.
        "target_asset_id": "asset_demo_l4_kb_draft",
        "operation": "build_asset",
        "downstream": "文档表格解析引擎 → L1 1.7 数据模块",
        "default_request": "把发酵、分离、提纯相关资料建设成可检索的工艺知识库",
    },
    "use_fermentation_skill": {
        "title": "调用可执行发酵异常检查技能",
        "l4_application": "研发人员在业务工作台发起批次异常检查",
        "request_mode": "natural_language",
        "interface": "L4 业务工作台对话框",
        "service_code": "function.skill.fermentation_anomaly",
        "target_asset_id": "asset_demo_executable_skill",
        "operation": "resolve_function",
        "downstream": "固定工具适配器 / fermentation_anomaly_checker@1.0.0",
        "default_request": "检查当前批次的发酵参数是否异常，并返回需要人工复核的项目",
    },
    "use_company_agent": {
        "title": "调用部门发酵巡检 Agent",
        "l4_application": "研发人员在批次巡检界面请求 Agent 检查发酵参数",
        "request_mode": "formatted",
        "interface": "L4 业务表单",
        "service_code": "function.agent.fermentation_inspection",
        "target_asset_id": "asset_demo_fermentation_agent",
        "operation": "resolve_function",
        "downstream": "Agent → 发酵参数异常检查技能 → 固定工具适配器",
        "default_request": "检查当前批次的温度、pH 和溶氧，异常时转交真人确认",
    },
    "commission_skill_gap": {
        "title": "销售提成：Skill 能力缺失处理",
        "l4_application": "员工在销售结算工作台提出 2026 年 6 月销售提成计算请求",
        "request_mode": "natural_language",
        "interface": "L4 销售结算对话框",
        "service_code": "rule.evaluate",
        "target_asset_id": None,
        "operation": "capability_gap",
        "downstream": "规则计算引擎 →（经流程执行）数据操作引擎 / 数字资产引擎",
        "default_request": "帮我计算 2026 年 6 月销售提成。",
    },
}

SCOPE_POLICIES = {
    "personal": {
        "label": "个人岗位级",
        "activation": "创建人完成后仅个人启用，不发布",
        "visibility": "仅创建人可见；部门负责人只有在被分配采纳申请时可审阅申请内容",
        "deletion": "草稿可逻辑删除；启用后只能停用",
    },
    "department": {
        "label": "部门级",
        "activation": "固定模板定位部门审批岗位，真人批准后发布",
        "visibility": "本部门成员可发现和调用资源；底层数据仍独立判权",
        "deletion": "发布后不可硬删，由维护人停用",
    },
    "company": {
        "label": "公司级",
        "activation": "固定模板定位公司审批岗位，真人批准后发布",
        "visibility": "本公司成员可发现资源；底层数据不因资源公开而自动开放",
        "deletion": "发布后不可硬删，由维护人停用",
    },
}


class EngineError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "BUSINESS_REJECTED"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Actor:
    user_id: str
    name: str
    role: str
    department: str
    company: str
    position_code: str
    active: bool

    @property
    def is_department_approver(self) -> bool:
        return self.role == "department_approver"

    @property
    def is_company_approver(self) -> bool:
        return self.role == "company_approver"

    @property
    def is_platform_operator(self) -> bool:
        return self.role == "platform_operator"


class DigitalAssetEngine:
    """SQLite 是演示版唯一状态源；所有读取和写入都在这里判权。"""

    DEFAULT_ACTOR = "tester_a"

    def __init__(self, db_path: str | Path, *, seed_demo: bool = True):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._seed_users()
        if seed_demo:
            self._seed_demo_data()
            self._ensure_l4_demo_seed()
            self._ensure_knowledge_base_demo_seed()
            self._ensure_executable_demo_seed()
        self._ensure_teacher_registry_evidence()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with closing(self.connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    department TEXT NOT NULL,
                    company TEXT NOT NULL,
                    position_code TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS action_registry (
                    action TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    asset_type TEXT NOT NULL,
                    asset_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    owner_real_id TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    contributor_id TEXT,
                    maintainer_id TEXT NOT NULL,
                    owner_department TEXT NOT NULL,
                    owner_company TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_version INTEGER NOT NULL DEFAULT 1,
                    derived_from_asset_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    config_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS asset_versions (
                    version_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    result_asset_id TEXT,
                    target_scope TEXT NOT NULL,
                    submitter_id TEXT NOT NULL,
                    approval_position TEXT NOT NULL,
                    approver_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    submitted_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    object_uri TEXT,
                    stored_name TEXT,
                    content_type TEXT,
                    size_bytes INTEGER,
                    checksum_sha256 TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    storage_status TEXT NOT NULL,
                    parse_status TEXT NOT NULL,
                    parser_service TEXT NOT NULL,
                    parse_result_json TEXT NOT NULL DEFAULT '{}',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_base_instances (
                    binding_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL UNIQUE,
                    requested_by TEXT NOT NULL,
                    target_module TEXT NOT NULL,
                    status TEXT NOT NULL,
                    l1_kb_id TEXT,
                    namespace TEXT,
                    provider TEXT,
                    callback_mode TEXT,
                    requested_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_source_indexes (
                    index_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL UNIQUE,
                    asset_id TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    vector_count INTEGER NOT NULL DEFAULT 0,
                    index_version TEXT,
                    callback_mode TEXT,
                    updated_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS function_registry (
                    function_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL UNIQUE,
                    function_name TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    sync_status TEXT NOT NULL,
                    examples_json TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_registry (
                    tool_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    handler TEXT NOT NULL,
                    input_schema_json TEXT NOT NULL,
                    output_schema_json TEXT NOT NULL,
                    rules_json TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(tool_id, version)
                );

                CREATE TABLE IF NOT EXISTS skill_validations (
                    validation_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    tool_version TEXT NOT NULL,
                    test_case_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    expected_json TEXT NOT NULL,
                    actual_json TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_development_requests (
                    development_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    submitter_id TEXT NOT NULL,
                    target_system TEXT NOT NULL,
                    requirement_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    candidate_tool_id TEXT,
                    candidate_tool_version TEXT,
                    candidate_artifact_uri TEXT,
                    candidate_test_report_uri TEXT,
                    callback_mode TEXT,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL UNIQUE,
                    actor_id TEXT NOT NULL,
                    agent_asset_id TEXT,
                    skill_asset_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    tool_version TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requires_human_review INTEGER NOT NULL,
                    confirmation_status TEXT NOT NULL,
                    confirmed_by TEXT,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS material_files (
                    file_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    checksum_sha256 TEXT NOT NULL,
                    object_uri TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    uploaded_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS asset_tags (
                    asset_id TEXT NOT NULL,
                    tag_key TEXT NOT NULL,
                    tag_value TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(asset_id, tag_key, tag_value)
                );

                CREATE TABLE IF NOT EXISTS skill_model_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    model_role TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    dataset_ref TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    conclusion TEXT NOT NULL,
                    asset_version INTEGER NOT NULL DEFAULT 1,
                    evaluated_by TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS foundation_calls (
                    call_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    asset_id TEXT,
                    account_gateway_result TEXT NOT NULL,
                    permission_result TEXT NOT NULL,
                    compliance_result TEXT NOT NULL,
                    adapter_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS flow_tasks (
                    task_id TEXT PRIMARY KEY,
                    workflow_instance_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    source_layer TEXT NOT NULL,
                    service_code TEXT NOT NULL,
                    target_engine TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l4_requests (
                    request_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL UNIQUE,
                    actor_id TEXT NOT NULL,
                    scenario_code TEXT NOT NULL,
                    request_mode TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    source_layer TEXT NOT NULL,
                    service_code TEXT NOT NULL,
                    target_engine TEXT NOT NULL,
                    asset_id TEXT,
                    response_type TEXT NOT NULL,
                    decision_code TEXT NOT NULL,
                    decision_reason TEXT NOT NULL,
                    route_json TEXT NOT NULL,
                    decisions_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    log_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    asset_id TEXT,
                    workflow_id TEXT,
                    asset_before TEXT,
                    asset_after TEXT,
                    decision_result TEXT NOT NULL,
                    deny_reason TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            source_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
            source_migrations = {
                "stored_name": "TEXT",
                "content_type": "TEXT",
                "size_bytes": "INTEGER",
                "checksum_sha256": "TEXT",
                "description": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in source_migrations.items():
                if column not in source_columns:
                    conn.execute(f"ALTER TABLE sources ADD COLUMN {column} {definition}")
            model_eval_columns = {row["name"] for row in conn.execute("PRAGMA table_info(skill_model_evaluations)")}
            if "asset_version" not in model_eval_columns:
                conn.execute(
                    "ALTER TABLE skill_model_evaluations ADD COLUMN asset_version INTEGER NOT NULL DEFAULT 1"
                )
            flow_task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(flow_tasks)")}
            if "idempotency_key" not in flow_task_columns:
                conn.execute("ALTER TABLE flow_tasks ADD COLUMN idempotency_key TEXT")
                conn.execute("UPDATE flow_tasks SET idempotency_key=task_id WHERE idempotency_key IS NULL OR idempotency_key='' ")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_flow_tasks_actor_idempotency "
                "ON flow_tasks(actor_id, idempotency_key)"
            )
            for action, label in ACTION_LABELS.items():
                conn.execute(
                    "INSERT OR REPLACE INTO action_registry(action, label, enabled) VALUES (?, ?, 1)",
                    (action, label),
                )
            # v0.3 起“数字员工”统一称为 Agent；只迁移类型码，不改用户资产内容。
            conn.execute("UPDATE assets SET asset_type='agent' WHERE asset_type='digital_employee'")
            conn.execute("UPDATE function_registry SET asset_type='agent' WHERE asset_type='digital_employee'")
            conn.execute(
                "UPDATE assets SET asset_type=? WHERE asset_type='material'",
                (LEGACY_ATTACHMENT_TYPE,),
            )
            for definition in public_tool_definitions():
                conn.execute(
                    """
                    INSERT INTO tool_registry(tool_id, version, tool_name, handler,
                        input_schema_json, output_schema_json, rules_json, checksum, enabled, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(tool_id, version) DO UPDATE SET
                        tool_name=excluded.tool_name, handler=excluded.handler,
                        input_schema_json=excluded.input_schema_json,
                        output_schema_json=excluded.output_schema_json,
                        rules_json=excluded.rules_json, checksum=excluded.checksum, enabled=1
                    """,
                    (
                        definition["tool_id"], definition["version"], definition["tool_name"],
                        definition["handler"], self._json(definition["input_schema"]),
                        self._json(definition["output_schema"]), self._json(definition["rules"]),
                        definition["checksum"], self._now(),
                    ),
                )
            conn.commit()

    def _ensure_teacher_registry_evidence(self) -> None:
        """Migrate old demo rows without deleting user-created data.

        Tags are descriptive/searchable metadata only.  Existing executable
        demo skills receive clearly labelled migration evaluation evidence so
        old demonstrations keep running; newly created skills must register
        their own primary and backup model evaluations before activation.
        """
        with closing(self.connect()) as conn:
            now = self._now()
            rows = list(conn.execute(
                "SELECT * FROM assets WHERE asset_type IN ('agent','skill','knowledge_base')"
            ))
            for row in rows:
                system_tags = (
                    ("asset_type", row["asset_type"]),
                    ("department", row["owner_department"]),
                    ("nature", row["scope"]),
                )
                for key, value in system_tags:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO asset_tags(asset_id, tag_key, tag_value, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (row["asset_id"], key, value, row["creator_id"], now),
                    )
                if row["asset_type"] == "agent":
                    config = self._decode(row["config_json"], {})
                    if config.get("material_ids") and not config.get("attachment_refs"):
                        config["attachment_refs"] = list(config.get("material_ids") or [])
                        config.pop("material_ids", None)
                        conn.execute(
                            "UPDATE assets SET config_json=? WHERE asset_id=?",
                            (self._json(config), row["asset_id"]),
                        )
                if row["asset_type"] != "skill" or row["status"] not in {"personal_active", "published"}:
                    continue
                for role, model_id, metric in (
                    ("primary", "demo-primary-model", 0.93),
                    ("backup", "demo-backup-model", 0.89),
                ):
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO skill_model_evaluations(
                            evaluation_id, asset_id, model_role, model_id, model_version,
                            dataset_ref, metric_name, metric_value, conclusion, asset_version,
                            evaluated_by, evaluated_at)
                        VALUES (?, ?, ?, ?, 'demo-v1', 'migration://legacy-demo-fixed-tests',
                            'pass_rate', ?, 'passed', ?, ?, ?)
                        """,
                        (f"eval_{row['asset_id']}_{role}", row["asset_id"], role, model_id,
                         metric, int(row["current_version"]), row["maintainer_id"], now),
                    )
            conn.commit()

    def _seed_users(self) -> None:
        company = "南宁汉和生物科技股份有限公司"
        users = [
            ("tester_a", "测试员甲", "employee", "生物制造研发中心", company, "POS-RD-STAFF-A", 1),
            ("tester_b", "测试员乙", "department_approver", "生物制造研发中心", company, "POS-RD-DEPT-HEAD", 1),
            ("tester_c", "测试员丙", "employee", "行政部", company, "POS-ADM-STAFF-C", 1),
            ("u_staff", "研发助理工程师", "employee", "生物制造研发中心", company, "POS-RD-STAFF", 1),
            ("u_legal_lead", "研发资料负责人", "department_approver", "生物制造研发中心", company, "POS-RD-DEPT-DOC", 1),
            ("u_dept_backup", "研发中心副负责人", "department_approver", "生物制造研发中心", company, "POS-RD-DEPT-DEPUTY", 1),
            ("u_admin_lead", "行政部负责人", "department_approver", "行政部", company, "POS-ADM-DEPT-HEAD", 1),
            ("u_company_approver", "公司资产审批人甲", "company_approver", "公司治理办公室", company, "POS-COMPANY-ASSET-A", 1),
            ("u_company_approver_2", "公司资产审批人乙", "company_approver", "公司治理办公室", company, "POS-COMPANY-ASSET-B", 1),
            ("engine_admin", "数字资产管理员", "platform_operator", "AI平台组", company, "POS-PLATFORM-OPS", 1),
            ("u_engine_admin", "陈宗贤", "platform_operator", "AI平台组", company, "POS-PLATFORM-OPS-2", 1),
            ("u_guest", "未入岗测试员", "unassigned", "外部", company, "NO-POSITION", 0),
        ]
        with closing(self.connect()) as conn:
            conn.executemany(
                """
                INSERT INTO users(user_id, name, role, department, company, position_code, active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name=excluded.name, role=excluded.role, department=excluded.department,
                    company=excluded.company, position_code=excluded.position_code, active=excluded.active
                """,
                users,
            )
            conn.commit()

    def _seed_demo_data(self, conn: sqlite3.Connection | None = None) -> None:
        """为老师演示提供最小但能覆盖权限边界的数据集。"""
        own_conn = conn is None
        conn = conn or self.connect()
        try:
            if conn.execute("SELECT 1 FROM assets LIMIT 1").fetchone():
                return
            now = self._now()
            company = "南宁汉和生物科技股份有限公司"
            demo_assets = [
                (
                    "asset_demo_personal_draft", "skill", "个人发酵参数检查草稿", "仅创建人可见的个人草稿",
                    "tester_a", "tester_a", "tester_a", "tester_a", "生物制造研发中心", company,
                    "personal", "draft", None, {"tool_ref": "fermentation_check_v1"},
                ),
                (
                    "asset_demo_personal_active", "skill", "个人批次异常标注技能", "已个人启用并主动提交部门采纳",
                    "tester_a", "tester_a", "tester_a", "tester_a", "生物制造研发中心", company,
                    "personal", "personal_active", None, {"tool_ref": "batch_anomaly_v1"},
                ),
                (
                    "asset_demo_department", "skill", "部门发酵异常识别技能", "本部门可调用，数据读取另行判权",
                    "tester_b", "tester_b", "tester_b", "tester_b", "生物制造研发中心", company,
                    "department", "published", None,
                    {"tool_ref": "fermentation_anomaly_v2", "data_access": {"departments": ["生物制造研发中心"]}},
                ),
                (
                    "asset_demo_company", "agent", "公司农业技术服务 Agent", "公司可发现资源，底层业务数据不自动开放",
                    "u_company_approver", "u_company_approver", "u_company_approver", "u_company_approver",
                    "公司治理办公室", company, "company", "published", None, {"agent_ref": "agri_service_v1"},
                ),
                (
                    "asset_demo_kb", "knowledge_base", "微生物肥料工艺知识库", "知识库是容器，原文和解析由其他模块承担",
                    "tester_b", "tester_b", "tester_b", "tester_b", "生物制造研发中心", company,
                    "department", "published", None,
                    {"data_access": {"departments": ["生物制造研发中心"]}},
                ),
                (
                    "asset_demo_kb_draft", "knowledge_base", "发酵工艺资料待建知识库", "供知识源登记与外部解析链路验证的部门级草稿",
                    "tester_b", "tester_b", "tester_b", "tester_b", "生物制造研发中心", company,
                    "department", "draft", None,
                    {"data_access": {"departments": ["生物制造研发中心"]}},
                ),
                (
                    "asset_demo_l4_kb_draft", "knowledge_base", "L4 演示·工艺资料待建知识库",
                    "仅用于验证 L4 建库请求受理、知识源登记和外部解析状态回调；不承载业务人员的实际草稿。",
                    "tester_b", "tester_b", "tester_b", "tester_b", "生物制造研发中心", company,
                    "department", "draft", None,
                    {"data_access": {"departments": ["生物制造研发中心"]}, "demo_only": True},
                ),
            ]
            for row in demo_assets:
                (
                    asset_id, asset_type, name, description, owner, creator, contributor, maintainer,
                    department, owner_company, scope, status, derived_from, config,
                ) = row
                conn.execute(
                    """
                    INSERT INTO assets(asset_id, asset_type, asset_name, description, owner_real_id,
                        creator_id, contributor_id, maintainer_id, owner_department, owner_company,
                        scope, status, current_version, derived_from_asset_id, created_at, updated_at, config_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        asset_id, asset_type, name, description, owner, creator, contributor, maintainer,
                        department, owner_company, scope, status, derived_from, now, now, self._json(config),
                    ),
                )
                self._snapshot(conn, asset_id, creator, "演示种子版本", bump=False)
            conn.execute(
                """
                INSERT INTO workflows(workflow_id, kind, asset_id, result_asset_id, target_scope,
                    submitter_id, approval_position, approver_id, status, reason, submitted_at, resolved_at)
                VALUES ('wf_demo_adoption', 'adoption', 'asset_demo_personal_active', NULL, 'department',
                    'tester_a', '部门数字资产审批岗位', 'tester_b', 'pending',
                    '员工主动申请部门采纳', ?, NULL)
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO sources(source_id, asset_id, file_name, source_type, object_uri,
                    storage_status, parse_status, parser_service, parse_result_json,
                    created_by, created_at, updated_at)
                VALUES ('src_demo_kb', 'asset_demo_kb', '发酵工艺规程.pdf', 'document',
                    'minio://demo/fermentation-process.pdf', 'registered', 'success',
                    'document_table_parser', ?, 'tester_b', ?, ?)
                """,
                (self._json({"note": "外部解析引擎 Mock 返回成功"}), now, now),
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def _ensure_l4_demo_seed(self) -> None:
        """Add the stable L4 demo target to an existing user-owned demo database.

        `_seed_demo_data` intentionally never overwrites a non-empty database.
        This tiny migration therefore adds only the dedicated L4 target when it
        is missing; it never resets or changes a user's assets or workflows.
        """
        with closing(self.connect()) as conn:
            exists = conn.execute(
                "SELECT 1 FROM assets WHERE asset_id='asset_demo_l4_kb_draft'"
            ).fetchone()
            if exists:
                return
            now = self._now()
            company = "南宁汉和生物科技股份有限公司"
            conn.execute(
                """
                INSERT INTO assets(asset_id, asset_type, asset_name, description, owner_real_id,
                    creator_id, contributor_id, maintainer_id, owner_department, owner_company,
                    scope, status, current_version, derived_from_asset_id, created_at, updated_at, config_json)
                VALUES (?, 'knowledge_base', ?, ?, 'tester_b', 'tester_b', 'tester_b', 'tester_b',
                    '生物制造研发中心', ?, 'department', 'draft', 1, NULL, ?, ?, ?)
                """,
                (
                    "asset_demo_l4_kb_draft", "L4 演示·工艺资料待建知识库",
                    "仅用于验证 L4 建库请求受理、知识源登记和外部解析状态回调；不承载业务人员的实际草稿。",
                    company, now, now,
                    self._json({"data_access": {"departments": ["生物制造研发中心"]}, "demo_only": True}),
                ),
            )
            self._snapshot(conn, "asset_demo_l4_kb_draft", "tester_b", "L4 演示种子版本", bump=False)
            conn.commit()

    def _ensure_knowledge_base_demo_seed(self) -> None:
        """只给稳定演示知识库补充 L2→L1 映射证据，不改用户创建的知识库。"""
        with closing(self.connect()) as conn:
            asset = conn.execute(
                "SELECT 1 FROM assets WHERE asset_id='asset_demo_kb' AND asset_type='knowledge_base'"
            ).fetchone()
            if not asset:
                return
            now = self._now()
            conn.execute(
                """
                INSERT OR IGNORE INTO knowledge_base_instances(binding_id, asset_id, requested_by,
                    target_module, status, l1_kb_id, namespace, provider, callback_mode, requested_at, updated_at)
                VALUES ('kbbind_demo_kb', 'asset_demo_kb', 'tester_b', 'L1 1.13 知识库模块',
                    'ready', 'l1kb_demo_fermentation', 'hanhe.demo.fermentation',
                    'L1 1.13 知识库模块 Mock', 'mock', ?, ?)
                """,
                (now, now),
            )
            source = conn.execute("SELECT 1 FROM sources WHERE source_id='src_demo_kb'").fetchone()
            if source:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO knowledge_source_indexes(index_id, source_id, asset_id,
                        binding_id, status, chunk_count, vector_count, index_version, callback_mode,
                        updated_by, created_at, updated_at)
                    VALUES ('idx_demo_kb', 'src_demo_kb', 'asset_demo_kb', 'kbbind_demo_kb',
                        'indexed', 18, 18, 'demo-v1', 'mock', 'engine_admin', ?, ?)
                    """,
                    (now, now),
                )
            conn.commit()

    def _ensure_executable_demo_seed(self) -> None:
        """幂等增加真实可运行的技能和 Agent，不重置用户已有演示数据。"""
        with closing(self.connect()) as conn:
            now = self._now()
            company = "南宁汉和生物科技股份有限公司"
            tool = TOOL_DEFINITIONS[("fermentation_anomaly_checker", "1.0.0")]
            skill_id = "asset_demo_executable_skill"
            if not conn.execute("SELECT 1 FROM assets WHERE asset_id=?", (skill_id,)).fetchone():
                config = {
                    "tool_id": tool["tool_id"],
                    "tool_version": tool["version"],
                    "tool_checksum": tool_checksum(tool),
                    "validation_status": "passed",
                    "validated_at": now,
                    "input_schema": tool["input_schema"],
                    "output_schema": tool["output_schema"],
                    "human_review_rule": "异常结果必须由发酵工艺岗位真人确认，不自动调整工艺参数。",
                    "data_access": {"departments": ["生物制造研发中心"]},
                }
                conn.execute(
                    """
                    INSERT INTO assets(asset_id, asset_type, asset_name, description, owner_real_id,
                        creator_id, contributor_id, maintainer_id, owner_department, owner_company,
                        scope, status, current_version, derived_from_asset_id, created_at, updated_at, config_json)
                    VALUES (?, 'skill', ?, ?, 'tester_b', 'tester_b', 'tester_b', 'tester_b',
                        '生物制造研发中心', ?, 'department', 'published', 1, NULL, ?, ?, ?)
                    """,
                    (
                        skill_id, "发酵参数异常检查技能",
                        "绑定固定版本工具，输入温度、pH、溶氧后返回确定性异常项；异常必须真人确认。",
                        company, now, now, self._json(config),
                    ),
                )
                self._snapshot(conn, skill_id, "tester_b", "可执行技能演示种子", bump=False)
                for case in tool["test_cases"]:
                    actual = execute_fixed_tool(tool["tool_id"], tool["version"], case["input"])
                    passed = all(actual.get(key) == value for key, value in case["expected"].items())
                    conn.execute(
                        """
                        INSERT INTO skill_validations(validation_id, asset_id, tool_id, tool_version,
                            test_case_name, input_json, expected_json, actual_json, passed, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester_b', ?)
                        """,
                        (
                            self._new_id("val"), skill_id, tool["tool_id"], tool["version"], case["name"],
                            self._json(case["input"]), self._json(case["expected"]), self._json(actual),
                            1 if passed else 0, now,
                        ),
                    )
                self._upsert_registry(conn, self._asset_dict(self._asset_row(conn, skill_id)))

            agent_id = "asset_demo_fermentation_agent"
            if not conn.execute("SELECT 1 FROM assets WHERE asset_id=?", (agent_id,)).fetchone():
                agent_config = {
                    "skill_ids": [skill_id],
                    "entry_skill_id": skill_id,
                    "knowledge_base_ids": ["asset_demo_kb"],
                    "material_ids": [],
                    "responsibility": "接收批次参数并编排发酵异常检查技能；不自行计算、不自动调整设备。",
                    "human_review_rule": "技能返回异常时转交发酵工艺岗位真人确认。",
                    "data_access": {"departments": ["生物制造研发中心"]},
                }
                conn.execute(
                    """
                    INSERT INTO assets(asset_id, asset_type, asset_name, description, owner_real_id,
                        creator_id, contributor_id, maintainer_id, owner_department, owner_company,
                        scope, status, current_version, derived_from_asset_id, created_at, updated_at, config_json)
                    VALUES (?, 'agent', ?, ?, 'tester_b', 'tester_b', 'tester_b', 'tester_b',
                        '生物制造研发中心', ?, 'department', 'published', 1, NULL, ?, ?, ?)
                    """,
                    (
                        agent_id, "发酵巡检 Agent",
                        "面向 L4 发酵巡检场景的组合入口，调用已发布技能并保留执行证据。",
                        company, now, now, self._json(agent_config),
                    ),
                )
                self._snapshot(conn, agent_id, "tester_b", "可执行 Agent 演示种子", bump=False)
            existing_agent = self._asset_row(conn, agent_id)
            existing_agent_config = self._decode(existing_agent["config_json"])
            if existing_agent_config.get("skill_ids") and not existing_agent_config.get("entry_skill_id"):
                existing_agent_config["entry_skill_id"] = existing_agent_config["skill_ids"][0]
                existing_agent_config.setdefault("knowledge_base_ids", ["asset_demo_kb"])
                existing_agent_config.setdefault("material_ids", [])
                conn.execute(
                    "UPDATE assets SET config_json=?, updated_at=? WHERE asset_id=?",
                    (self._json(existing_agent_config), now, agent_id),
                )
            self._upsert_registry(conn, self._asset_dict(self._asset_row(conn, agent_id)))

            company_skill_id = "asset_demo_company_executable_skill"
            if not conn.execute("SELECT 1 FROM assets WHERE asset_id=?", (company_skill_id,)).fetchone():
                company_skill_config = {
                    "tool_id": tool["tool_id"], "tool_version": tool["version"],
                    "tool_checksum": tool_checksum(tool), "validation_status": "passed",
                    "validated_at": now, "input_schema": tool["input_schema"],
                    "output_schema": tool["output_schema"],
                    "human_review_rule": "异常结果由公司发酵质量岗位真人确认。",
                    "data_access": {"actors": ["u_company_approver"]},
                }
                conn.execute(
                    """
                    INSERT INTO assets(asset_id, asset_type, asset_name, description, owner_real_id,
                        creator_id, contributor_id, maintainer_id, owner_department, owner_company,
                        scope, status, current_version, derived_from_asset_id, created_at, updated_at, config_json)
                    VALUES (?, 'skill', ?, ?, 'u_company_approver', 'u_company_approver',
                        'u_company_approver', 'u_company_approver', '公司治理办公室', ?,
                        'company', 'published', 1, NULL, ?, ?, ?)
                    """,
                    (
                        company_skill_id, "公司发酵参数异常检查技能",
                        "公司级固定工具能力；资源可发现不等于所有人可读取批次数据。",
                        company, now, now, self._json(company_skill_config),
                    ),
                )
                self._snapshot(conn, company_skill_id, "u_company_approver", "公司级可执行技能演示种子", bump=False)
                for case in tool["test_cases"]:
                    actual = execute_fixed_tool(tool["tool_id"], tool["version"], case["input"])
                    passed = all(actual.get(key) == value for key, value in case["expected"].items())
                    conn.execute(
                        """
                        INSERT INTO skill_validations(validation_id, asset_id, tool_id, tool_version,
                            test_case_name, input_json, expected_json, actual_json, passed, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'u_company_approver', ?)
                        """,
                        (
                            self._new_id("val"), company_skill_id, tool["tool_id"], tool["version"], case["name"],
                            self._json(case["input"]), self._json(case["expected"]), self._json(actual),
                            1 if passed else 0, now,
                        ),
                    )
                self._upsert_registry(conn, self._asset_dict(self._asset_row(conn, company_skill_id)))

            company_agent = conn.execute("SELECT * FROM assets WHERE asset_id='asset_demo_company'").fetchone()
            if company_agent:
                current_config = self._decode(company_agent["config_json"])
                if not current_config.get("skill_ids"):
                    current_config = {
                        "skill_ids": [company_skill_id],
                        "entry_skill_id": company_skill_id,
                        "knowledge_base_ids": [],
                        "material_ids": [],
                        "responsibility": "编排公司发酵质量检查技能；不自行计算。",
                        "human_review_rule": "异常结果由公司发酵质量岗位真人确认。",
                        "data_access": {"actors": ["u_company_approver"]},
                    }
                    conn.execute(
                        "UPDATE assets SET asset_type='agent', asset_name=?, description=?, config_json=?, updated_at=? WHERE asset_id='asset_demo_company'",
                        ("公司发酵质量巡检 Agent", "公司级 Agent；调用固定技能，底层批次数据仍按真人授权。", self._json(current_config), now),
                    )
                    self._snapshot(conn, "asset_demo_company", "u_company_approver", "数字员工迁移为可执行 Agent", bump=True)
                elif not current_config.get("entry_skill_id"):
                    current_config["entry_skill_id"] = current_config["skill_ids"][0]
                    current_config.setdefault("knowledge_base_ids", [])
                    current_config.setdefault("material_ids", [])
                    conn.execute(
                        "UPDATE assets SET config_json=?, updated_at=? WHERE asset_id='asset_demo_company'",
                        (self._json(current_config), now),
                    )
                self._upsert_registry(conn, self._asset_dict(self._asset_row(conn, "asset_demo_company")))
            # 旧版本把文字配置也同步为功能；升级后清理这些虚假可执行登记。
            for legacy_id in ("asset_demo_personal_active", "asset_demo_department"):
                conn.execute("DELETE FROM function_registry WHERE asset_id=?", (legacy_id,))
            conn.commit()

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(value: str | None, fallback: Any = None) -> Any:
        if not value:
            return {} if fallback is None else fallback
        return json.loads(value)

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise EngineError(f"标准任务信封缺少 {field}", 400, "MISSING_FLOW_ENVELOPE_FIELD")
        return text

    def _validate_standard_flow_envelope(
        self, actor_id: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """验证正式 L2 对内任务信封；不为上游补造追踪、幂等或责任字段。"""
        missing = sorted(field for field in FLOW_REQUIRED_TOP_LEVEL if field not in payload)
        if missing:
            raise EngineError(
                f"标准任务信封缺少必填字段：{', '.join(missing)}",
                400,
                "MISSING_FLOW_ENVELOPE_FIELD",
            )
        if payload.get("protocol_version") != "1.0":
            raise EngineError("仅支持 protocol_version=1.0 的标准任务信封", 400, "UNSUPPORTED_PROTOCOL_VERSION")
        if payload.get("route_type") != "task.dispatch":
            raise EngineError("数字资产引擎只接收 route_type=task.dispatch 的流程派发", 400, "BAD_ROUTE_TYPE")
        for field in (
            "message_id", "trace_id", "request_id", "parent_message_id", "channel",
            "action", "capability_id", "capability_dictionary_version", "registry_version",
            "idempotency_key", "deadline_at",
        ):
            self._required_text(payload.get(field), field)
        source = payload.get("source")
        target = payload.get("target")
        actor = payload.get("actor")
        context = payload.get("context")
        if not isinstance(source, dict) or not isinstance(target, dict) or not isinstance(actor, dict) or not isinstance(context, dict):
            raise EngineError("source、target、actor、context 必须是对象", 400, "BAD_FLOW_ENVELOPE_OBJECT")
        for field in ("layer", "service_code"):
            self._required_text(source.get(field), f"source.{field}")
            self._required_text(target.get(field), f"target.{field}")
        person_id = self._required_text(actor.get("person_id"), "actor.person_id")
        self._required_text(actor.get("tenant_id"), "actor.tenant_id")
        if person_id != actor_id:
            raise EngineError("任务信封中的责任真人与请求真人不一致", 403, "ACTOR_MISMATCH")
        missing_context = sorted(field for field in FLOW_REQUIRED_CONTEXT if field not in context)
        if missing_context:
            raise EngineError(
                f"标准任务 context 缺少必填字段：{', '.join(missing_context)}",
                400,
                "MISSING_FLOW_CONTEXT_FIELD",
            )
        for field in ("workflow_instance_id", "node_id", "task_id"):
            self._required_text(context.get(field), f"context.{field}")
        if not isinstance(context.get("data_refs"), list):
            raise EngineError("context.data_refs 必须是数组", 400, "BAD_DATA_REFS")
        if not isinstance(payload.get("payload"), dict):
            raise EngineError("payload 必须是对象", 400, "BAD_FLOW_ACTION_PAYLOAD")
        return source, target, context

    def _actor_from_conn(self, conn: sqlite3.Connection, user_id: str) -> Actor:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row["active"]:
            raise EngineError("当前真人不存在、未入岗或账号已停用", 401, "ACTOR_NOT_AVAILABLE")
        return Actor(
            user_id=row["user_id"], name=row["name"], role=row["role"],
            department=row["department"], company=row["company"],
            position_code=row["position_code"], active=bool(row["active"]),
        )

    def actor(self, user_id: str | None = None) -> Actor:
        with closing(self.connect()) as conn:
            return self._actor_from_conn(conn, user_id or self.DEFAULT_ACTOR)

    def _asset_row(self, conn: sqlite3.Connection, asset_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if not row:
            raise EngineError("资产不存在", 404, "ASSET_NOT_FOUND")
        return row

    def _workflow_row(self, conn: sqlite3.Connection, workflow_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
        if not row:
            raise EngineError("工作流不存在", 404, "WORKFLOW_NOT_FOUND")
        return row

    def _source_row(self, conn: sqlite3.Connection, source_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
        if not row:
            raise EngineError("知识源记录不存在", 404, "SOURCE_NOT_FOUND")
        return row

    def _kb_instance_for_asset(self, conn: sqlite3.Connection, asset_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM knowledge_base_instances WHERE asset_id=?", (asset_id,)
        ).fetchone()

    def _kb_instance_row(self, conn: sqlite3.Connection, binding_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM knowledge_base_instances WHERE binding_id=?", (binding_id,)
        ).fetchone()
        if not row:
            raise EngineError("L1知识库实例申请不存在", 404, "L1_KB_BINDING_NOT_FOUND")
        return row

    def _source_index_for_source(self, conn: sqlite3.Connection, source_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM knowledge_source_indexes WHERE source_id=?", (source_id,)
        ).fetchone()

    def _material_file_row(self, conn: sqlite3.Connection, file_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM material_files WHERE file_id=?", (file_id,)).fetchone()
        if not row:
            raise EngineError("素材文件不存在", 404, "MATERIAL_FILE_NOT_FOUND")
        return row

    def _asset_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["config"] = self._decode(item.pop("config_json", "{}"))
        item["asset_type_label"] = ASSET_TYPES.get(item["asset_type"], item["asset_type"])
        item["scope_label"] = SCOPES.get(item["scope"], item["scope"])
        item["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
        return item

    def _asset_tags(self, conn: sqlite3.Connection, asset_id: str) -> list[dict[str, str]]:
        return [
            {"key": row["tag_key"], "value": row["tag_value"]}
            for row in conn.execute(
                "SELECT tag_key, tag_value FROM asset_tags WHERE asset_id=? ORDER BY tag_key, tag_value",
                (asset_id,),
            )
        ]

    def _replace_asset_tags(
        self, conn: sqlite3.Connection, asset: sqlite3.Row, actor_id: str,
        tags: list[dict[str, Any]] | list[str] | None,
    ) -> None:
        normalized: set[tuple[str, str]] = {
            ("asset_type", asset["asset_type"]),
            ("department", asset["owner_department"]),
            ("nature", asset["scope"]),
        }
        for item in tags or []:
            if isinstance(item, str):
                key, value = "label", item
            else:
                key = str(item.get("key") or "label").strip()
                value = str(item.get("value") or "").strip()
            if key and value:
                normalized.add((key[:40], value[:100]))
        conn.execute("DELETE FROM asset_tags WHERE asset_id=?", (asset["asset_id"],))
        now = self._now()
        for key, value in sorted(normalized):
            conn.execute(
                """
                INSERT INTO asset_tags(asset_id, tag_key, tag_value, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (asset["asset_id"], key, value, actor_id, now),
            )

    def _skill_model_evaluations(self, conn: sqlite3.Connection, asset_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute(
            """
            SELECT * FROM skill_model_evaluations
            WHERE asset_id=? ORDER BY model_role, evaluated_at DESC
            """,
            (asset_id,),
        )]

    def _record_foundation_call(
        self, conn: sqlite3.Connection, request_id: str, actor_id: str, action: str,
        asset_id: str | None, decision: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO foundation_calls(call_id, request_id, actor_id, action, asset_id,
                account_gateway_result, permission_result, compliance_result, adapter_mode, created_at)
            VALUES (?, ?, ?, ?, ?, 'authenticated', ?, 'recorded', 'L1 Mock adapter', ?)
            """,
            (self._new_id("foundation"), request_id, actor_id, action, asset_id, decision, self._now()),
        )

    def _workflow_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["kind_label"] = WORKFLOW_LABELS.get(item["kind"], item["kind"])
        return item

    def _development_request_row(self, conn: sqlite3.Connection, development_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM skill_development_requests WHERE development_id=?",
            (development_id,),
        ).fetchone()
        if not row:
            raise EngineError("Skill 研发任务不存在", 404, "SKILL_DEVELOPMENT_NOT_FOUND")
        return row

    def _development_request_dict(self, row: sqlite3.Row, *, metadata_only: bool = False) -> dict[str, Any]:
        item = dict(row)
        item["requirement"] = self._decode(item.pop("requirement_json", "{}"), {})
        item["metadataOnly"] = metadata_only
        if metadata_only:
            item["requirement"] = {}
        return item

    def _active_development_request(self, conn: sqlite3.Connection, asset_id: str) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM skill_development_requests
            WHERE asset_id=? AND status IN ('submitted', 'candidate_received', 'ready_to_bind')
            ORDER BY submitted_at DESC LIMIT 1
            """,
            (asset_id,),
        ).fetchone()

    def _l4_request_row(self, conn: sqlite3.Connection, request_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM l4_requests WHERE request_id=?", (request_id,)).fetchone()
        if not row:
            raise EngineError("L4 请求记录不存在", 404, "L4_REQUEST_NOT_FOUND")
        return row

    def _l4_request_dict(self, row: sqlite3.Row, *, metadata_only: bool = False) -> dict[str, Any]:
        item = dict(row)
        item["route"] = self._decode(item.pop("route_json", "[]"), [])
        item["decisions"] = self._decode(item.pop("decisions_json", "{}"), {})
        item["standard_response"] = self._decode(item.pop("response_json", "{}"), {})
        item["metadataOnly"] = metadata_only
        if metadata_only:
            item["request_text"] = "受限 L4 业务请求"
            item["route"] = [
                {"seq": step.get("seq"), "layer": step.get("layer"), "component": step.get("component")}
                for step in item["route"]
            ]
            item["decisions"] = {}
            item["standard_response"] = {
                "type": item["response_type"],
                "code": item["decision_code"],
                "message": "仅技术元数据可见",
            }
        return item

    @staticmethod
    def _public_l4_scenarios() -> list[dict[str, Any]]:
        """前端可选场景不暴露内部目标资产编号，服务端按场景代码解析。"""
        return [
            {
                "code": code,
                "title": scenario["title"],
                "l4_application": scenario["l4_application"],
                "request_mode": scenario["request_mode"],
                "interface": scenario["interface"],
                "service_code": scenario["service_code"],
                "downstream": scenario["downstream"],
                "default_request": scenario["default_request"],
            }
            for code, scenario in L4_SCENARIOS.items()
        ]

    def _action_enabled(self, conn: sqlite3.Connection, action: str) -> None:
        row = conn.execute("SELECT enabled FROM action_registry WHERE action=?", (action,)).fetchone()
        if not row or not row["enabled"]:
            raise EngineError("动作未登记或已停用，默认拒绝", 403, "ACTION_NOT_REGISTERED")

    def _assert_mutable_state(self, asset: sqlite3.Row) -> None:
        if asset["status"] == "disabled":
            raise EngineError("资产已停用，禁止全部变更", 409, "ASSET_DISABLED")
        if asset["status"] == "deleted":
            raise EngineError("资产已逻辑删除，禁止全部变更", 409, "ASSET_DELETED")
        if asset["status"] == "adopted":
            raise EngineError("个人源资产已采纳归档，禁止继续变更", 409, "ASSET_ADOPTED")

    def _audit(
        self, conn: sqlite3.Connection, actor_id: str, action: str, request_id: str,
        result: str, asset_id: str | None = None, workflow_id: str | None = None,
        before: Any = None, after: Any = None, reason: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_log(log_id, request_id, actor_id, action, asset_id, workflow_id,
                asset_before, asset_after, decision_result, deny_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._new_id("log"), request_id, actor_id, action, asset_id, workflow_id,
                self._json(before) if before is not None else None,
                self._json(after) if after is not None else None,
                result, reason, self._now(),
            ),
        )

    def _write_deny(
        self, actor_id: str, action: str, request_id: str, exc: EngineError,
        asset_id: str | None = None, workflow_id: str | None = None, before: Any = None,
    ) -> None:
        with closing(self.connect()) as conn:
            self._record_foundation_call(conn, request_id, actor_id, action, asset_id, "DENY")
            self._audit(conn, actor_id, action, request_id, "DENY", asset_id, workflow_id, before, None, exc.message)
            conn.commit()

    @staticmethod
    def _audit_asset_summary(asset: dict[str, Any] | None) -> dict[str, Any] | None:
        """审计只保留资产身份与状态，不复制业务配置、正文或完整页面状态。"""
        if not asset:
            return None
        return {
            key: asset.get(key)
            for key in (
                "asset_id", "asset_type", "scope", "status", "current_version",
                "owner_real_id", "creator_id", "maintainer_id", "updated_at",
            )
            if key in asset
        }

    def _audit_result_summary(self, action: str, result: Any) -> dict[str, Any] | None:
        """将动作结果压缩为不可递归的审计摘要。

        ``read_state`` 返回页面、资产、版本和审计日志的组合；绝不能将它整体再写回
        ``audit_log``，否则会发生日志嵌套并使 SQLite 文件指数膨胀。
        """
        if not isinstance(result, dict):
            return {"result_type": type(result).__name__}
        if action == "read_state":
            stats = result.get("stats") or {}
            return {
                "kind": "workspace_read",
                "visible_asset_count": stats.get("visibleAssetCount", 0),
                "visible_workflow_count": len(result.get("workflows") or []),
                "visible_source_count": len(result.get("sources") or []),
            }
        summary = {
            key: result.get(key)
            for key in (
                "asset_id", "source_id", "workflow_id", "kind", "target_scope",
                "file_id", "version_no", "size_bytes",
                "scope", "status", "current_version", "parse_status", "sync_status", "reset",
                "trace_id", "execution_id", "response_type", "decision_code", "scenario_code",
                "development_id", "target_system", "candidate_tool_id", "candidate_tool_version",
                "binding_id", "l1_kb_id", "namespace", "index_id", "chunk_count", "vector_count",
            )
            if key in result
        }
        if result.get("result_asset"):
            summary["result_asset"] = self._audit_asset_summary(result["result_asset"])
        return summary or {"result_type": "operation_complete"}

    def _run(
        self, actor_id: str | None, action: str, fn: Callable[[sqlite3.Connection, Actor], dict[str, Any]],
        *, asset_id: str | None = None, workflow_id: str | None = None, request_id: str | None = None,
    ) -> dict[str, Any]:
        actor_id = actor_id or self.DEFAULT_ACTOR
        request_id = request_id or self._new_id("req")
        before = None
        try:
            with closing(self.connect()) as conn:
                actor = self._actor_from_conn(conn, actor_id)
                self._action_enabled(conn, action)
                if asset_id:
                    before = self._audit_asset_summary(self._asset_dict(self._asset_row(conn, asset_id)))
                result = fn(conn, actor)
                self._record_foundation_call(conn, request_id, actor.user_id, action, asset_id, "ALLOW")
                self._audit(
                    conn, actor.user_id, action, request_id, "ALLOW", asset_id, workflow_id,
                    before, self._audit_result_summary(action, result),
                )
                conn.commit()
                return result
        except EngineError as exc:
            self._write_deny(actor_id, action, request_id, exc, asset_id, workflow_id, before)
            raise

    def _snapshot(self, conn: sqlite3.Connection, asset_id: str, actor_id: str, summary: str, *, bump: bool) -> None:
        row = self._asset_row(conn, asset_id)
        version = int(row["current_version"]) + (1 if bump else 0)
        if bump:
            conn.execute(
                "UPDATE assets SET current_version=?, updated_at=? WHERE asset_id=?",
                (version, self._now(), asset_id),
            )
            row = self._asset_row(conn, asset_id)
        conn.execute(
            """
            INSERT INTO asset_versions(version_id, asset_id, version_no, snapshot_json,
                change_summary, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (self._new_id("ver"), asset_id, version, self._json(self._asset_dict(row)), summary, actor_id, self._now()),
        )

    def _can_create_scope(self, actor: Actor, scope: str) -> bool:
        if actor.role == "employee":
            return scope == "personal"
        if actor.is_department_approver:
            return scope in {"personal", "department"}
        if actor.is_company_approver:
            return scope in {"personal", "company"}
        return False

    def _assigned_pending_workflow(self, conn: sqlite3.Connection, actor: Actor, asset_id: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM workflows WHERE asset_id=? AND approver_id=? AND status='pending' ORDER BY submitted_at DESC LIMIT 1",
            (asset_id, actor.user_id),
        ).fetchone()

    def _pool_visible(self, actor: Actor, asset: sqlite3.Row) -> bool:
        if asset["status"] != "published":
            return False
        if asset["scope"] == "department":
            return asset["owner_department"] == actor.department
        if asset["scope"] == "company":
            return asset["owner_company"] == actor.company
        return False

    def _discoverable(self, conn: sqlite3.Connection, actor: Actor, asset: sqlite3.Row) -> bool:
        if asset["status"] == "deleted":
            return asset["creator_id"] == actor.user_id
        if actor.is_platform_operator:
            return True
        if actor.user_id in {asset["creator_id"], asset["owner_real_id"], asset["maintainer_id"]}:
            return True
        if self._pool_visible(actor, asset):
            return True
        return self._assigned_pending_workflow(conn, actor, asset["asset_id"]) is not None

    def _resource_callable(self, actor: Actor, asset: sqlite3.Row) -> bool:
        if actor.is_platform_operator or asset["asset_type"] not in FUNCTION_TYPES:
            return False
        config = self._decode(asset["config_json"])
        if asset["asset_type"] == "skill" and not (
            config.get("validation_status") == "passed" and config.get("tool_id")
            and config.get("tool_version") and config.get("tool_checksum")
        ):
            return False
        if asset["asset_type"] == "agent" and not config.get("skill_ids"):
            return False
        if asset["scope"] == "personal":
            return asset["status"] == "personal_active" and asset["owner_real_id"] == actor.user_id
        return self._pool_visible(actor, asset)

    def _data_readable(self, conn: sqlite3.Connection, actor: Actor, asset: sqlite3.Row) -> bool:
        """Compatibility name for the external permission Mock's content decision.

        It deliberately does not inspect tags or an asset-carried ACL.  Business
        data permissions are outside this engine and are never represented here.
        """
        if actor.is_platform_operator:
            return False
        if actor.user_id in {asset["owner_real_id"], asset["maintainer_id"]}:
            return True
        if self._assigned_pending_workflow(conn, actor, asset["asset_id"]):
            return True
        return self._pool_visible(actor, asset)

    def _capabilities(self, conn: sqlite3.Connection, actor: Actor, asset: sqlite3.Row) -> dict[str, bool]:
        is_personal_owner = asset["scope"] == "personal" and asset["owner_real_id"] == actor.user_id
        is_maintainer = asset["maintainer_id"] == actor.user_id
        assigned = self._assigned_pending_workflow(conn, actor, asset["asset_id"]) is not None
        has_pending_workflow = self._pending_for_asset(conn, asset["asset_id"])
        locked = asset["status"] in {"disabled", "deleted", "adopted", "pending_publish"}
        can_modify = False
        if asset["status"] == "draft":
            can_modify = is_personal_owner if asset["scope"] == "personal" else is_maintainer
        content_allowed = self._data_readable(conn, actor, asset)
        asset_config = self._decode(asset["config_json"])
        has_skill_implementation = bool(asset_config.get("tool_id") and asset_config.get("tool_version"))
        active_development = self._active_development_request(conn, asset["asset_id"])
        has_active_development = active_development is not None
        kb_instance = self._kb_instance_for_asset(conn, asset["asset_id"]) if asset["asset_type"] == "knowledge_base" else None
        can_modify_content = can_modify and not has_active_development
        can_bind_skill = can_modify and (
            not has_active_development or active_development["status"] == "ready_to_bind"
        )
        function_ready = True
        if asset["asset_type"] in FUNCTION_TYPES | {"knowledge_base"}:
            try:
                self._assert_function_ready(conn, asset)
            except EngineError:
                function_ready = False
        return {
            "viewMetadata": self._discoverable(conn, actor, asset),
            # 由外部权限模块 Mock 按当前真人判定；标签不参与权限推导。
            "viewContent": content_allowed,
            "modify": can_modify_content,
            "bindSkillImplementation": asset["asset_type"] == "skill" and can_bind_skill,
            "submitSkillDevelopment": (
                asset["asset_type"] == "skill" and can_modify_content
                and not has_skill_implementation and not has_active_development
            ),
            "validateSkill": asset["asset_type"] == "skill" and can_modify_content and has_skill_implementation,
            "registerModelEvaluation": asset["asset_type"] == "skill" and can_modify_content,
            "activatePersonal": is_personal_owner and asset["status"] == "draft" and function_ready,
            "submitAdoption": is_personal_owner and asset["status"] == "personal_active" and not has_pending_workflow,
            "submitPublish": is_maintainer and asset["scope"] in {"department", "company"} and asset["status"] == "draft" and function_ready and not has_pending_workflow,
            "disable": (
                not locked and (
                    (is_personal_owner and asset["status"] == "personal_active")
                    or (is_maintainer and asset["status"] == "published")
                )
            ),
            "deleteDraft": is_personal_owner and asset["status"] == "draft" and not has_active_development,
            "addSource": asset["asset_type"] == "knowledge_base" and asset["status"] == "draft" and (
                is_personal_owner if asset["scope"] == "personal" else is_maintainer
            ),
            "requestL1KnowledgeBase": (
                asset["asset_type"] == "knowledge_base"
                and asset["status"] == "draft"
                and kb_instance is None
                and (is_personal_owner if asset["scope"] == "personal" else is_maintainer)
            ),
            "reviewAssignedWorkflow": assigned,
        }

    def _present_asset(self, conn: sqlite3.Connection, actor: Actor, row: sqlite3.Row) -> dict[str, Any]:
        item = self._asset_dict(row)
        content_allowed = self._data_readable(conn, actor, row)
        metadata_only = actor.is_platform_operator or not content_allowed
        if actor.is_platform_operator:
            item["asset_name"] = "受限业务资产"
        if metadata_only:
            item["description"] = ""
            item["config"] = {}
        item["redacted"] = metadata_only
        item["metadataOnly"] = metadata_only
        item["resourceCallable"] = self._resource_callable(actor, row)
        item["permissionDecision"] = {
            "adapter": "L1 权限管理 Mock",
            "viewMetadata": self._discoverable(conn, actor, row),
            "viewContent": content_allowed,
            "use": self._resource_callable(actor, row),
        }
        item["tags"] = self._asset_tags(conn, row["asset_id"])
        item["modelEvaluations"] = (
            self._skill_model_evaluations(conn, row["asset_id"])
            if row["asset_type"] == "skill" and not metadata_only else []
        )
        item["capabilities"] = self._capabilities(conn, actor, row)
        item["capabilities"]["resourceCallable"] = item["resourceCallable"]
        return item

    def _resolve_approver(self, conn: sqlite3.Connection, submitter: Actor, scope: str) -> tuple[str, str]:
        if scope == "department":
            role = "department_approver"
            position = "部门数字资产审批岗位"
            row = conn.execute(
                """
                SELECT * FROM users WHERE role=? AND department=? AND active=1 AND user_id<>?
                ORDER BY CASE WHEN position_code LIKE '%HEAD' THEN 0 ELSE 1 END,
                    position_code, user_id LIMIT 1
                """,
                (role, submitter.department, submitter.user_id),
            ).fetchone()
        elif scope == "company":
            role = "company_approver"
            position = "公司数字资产审批岗位"
            row = conn.execute(
                """
                SELECT * FROM users WHERE role=? AND company=? AND active=1 AND user_id<>?
                ORDER BY position_code, user_id LIMIT 1
                """,
                (role, submitter.company, submitter.user_id),
            ).fetchone()
        else:
            raise EngineError("个人岗位级资产不走发布审批，只允许个人启用", 400, "PERSONAL_NOT_PUBLISHABLE")
        if not row:
            raise EngineError("固定模板审批岗位当前无人，流程必须暂停", 409, "APPROVAL_POSITION_VACANT")
        return position, row["user_id"]

    def _pending_for_asset(self, conn: sqlite3.Connection, asset_id: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM workflows WHERE asset_id=? AND status='pending' LIMIT 1", (asset_id,)
        ).fetchone() is not None

    def _insert_skill_model_evaluation(
        self, conn: sqlite3.Connection, actor: Actor, asset: sqlite3.Row, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if asset["asset_type"] != "skill":
            raise EngineError("只有技能资产需要登记主备模型评测", 400, "MODEL_EVALUATION_REQUIRES_SKILL")
        role = str(payload.get("model_role") or "").strip()
        if role not in {"primary", "backup"}:
            raise EngineError("模型角色必须是 primary 或 backup", 400, "BAD_MODEL_ROLE")
        required = {
            "model_id": str(payload.get("model_id") or "").strip(),
            "model_version": str(payload.get("model_version") or "").strip(),
            "dataset_ref": str(payload.get("dataset_ref") or "").strip(),
            "metric_name": str(payload.get("metric_name") or "").strip(),
            "conclusion": str(payload.get("conclusion") or "").strip(),
        }
        if any(not value for value in required.values()):
            raise EngineError("模型、版本、评测集、指标和结论必须完整登记", 400, "INCOMPLETE_MODEL_EVALUATION")
        if required["conclusion"] not in {"passed", "failed"}:
            raise EngineError("评测结论只能是 passed 或 failed", 400, "BAD_MODEL_CONCLUSION")
        try:
            metric_value = float(payload.get("metric_value"))
        except (TypeError, ValueError) as exc:
            raise EngineError("评测指标值必须是数字", 400, "BAD_MODEL_METRIC") from exc
        evaluation_id = self._new_id("eval")
        conn.execute(
            """
            INSERT INTO skill_model_evaluations(
                evaluation_id, asset_id, model_role, model_id, model_version,
                dataset_ref, metric_name, metric_value, conclusion, asset_version,
                evaluated_by, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id, asset["asset_id"], role, required["model_id"],
                required["model_version"], required["dataset_ref"], required["metric_name"],
                metric_value, required["conclusion"], int(asset["current_version"]),
                actor.user_id, self._now(),
            ),
        )
        return dict(conn.execute(
            "SELECT * FROM skill_model_evaluations WHERE evaluation_id=?", (evaluation_id,)
        ).fetchone())

    def register_skill_model_evaluation(
        self, actor_id: str, asset_id: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["status"] != "draft" or not self._capabilities(conn, actor, asset)["modify"]:
                raise EngineError("只有技能草稿维护人可登记模型评测", 403, "NO_MODEL_EVALUATION_PERMISSION")
            result = self._insert_skill_model_evaluation(conn, actor, asset, payload)
            self._snapshot(conn, asset_id, actor.user_id, f"登记{payload.get('model_role')}模型评测", bump=False)
            return result

        return self._run(
            actor_id, "register_skill_model_evaluation", work,
            asset_id=asset_id, request_id=payload.get("request_id"),
        )

    def create_asset(self, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset_type = payload.get("asset_type")
            if asset_type == "digital_employee":  # 兼容旧页面或旧请求，统一落库为 Agent。
                asset_type = "agent"
            if asset_type not in ASSET_TYPES:
                raise EngineError("资产类型不合法", 400, "BAD_ASSET_TYPE")
            name = str(payload.get("asset_name") or "").strip()
            if not name:
                raise EngineError("资产名称不能为空", 400, "MISSING_NAME")
            scope = payload.get("scope") or "personal"
            if scope not in SCOPES:
                raise EngineError("资产范围不合法", 400, "BAD_SCOPE")
            if not self._can_create_scope(actor, scope):
                raise EngineError("当前真人无权在该层级创建草稿", 403, "NO_CREATE_SCOPE_PERMISSION")
            asset_id = self._new_id("asset")
            now = self._now()
            config = dict(payload.get("config") or {})
            for protected in ("validation_status", "validated_at", "tool_checksum"):
                config.pop(protected, None)
            if asset_type == "skill":
                tool_id = str(config.get("tool_id") or "").strip()
                tool_version = str(config.get("tool_version") or "").strip()
                if bool(tool_id) != bool(tool_version):
                    raise EngineError("固定工具编号和版本必须同时填写", 400, "INCOMPLETE_SKILL_BINDING")
                if tool_id and tool_version:
                    tool_row = conn.execute(
                        "SELECT 1 FROM tool_registry WHERE tool_id=? AND version=? AND enabled=1",
                        (tool_id, tool_version),
                    ).fetchone()
                    if not tool_row or (tool_id, tool_version) not in TOOL_DEFINITIONS:
                        raise EngineError("只能绑定已登记且可执行的固定工具版本", 409, "SKILL_TOOL_UNAVAILABLE")
                    config.update(
                        {
                            "tool_id": tool_id,
                            "tool_version": tool_version,
                            "implementation_type": "fixed_tool",
                            "implementation_status": "bound",
                            "lifecycle_stage": "implementation_bound",
                            "validation_status": "not_validated",
                        }
                    )
                else:
                    config.pop("tool_id", None)
                    config.pop("tool_version", None)
                    config.update(
                        {
                            "implementation_type": "unassigned",
                            "implementation_status": "requested",
                            "lifecycle_stage": "requirement_draft",
                            "validation_status": "not_validated",
                            "candidate_source": config.get("candidate_source") or "undecided",
                        }
                    )
            conn.execute(
                """
                INSERT INTO assets(asset_id, asset_type, asset_name, description, owner_real_id,
                    creator_id, contributor_id, maintainer_id, owner_department, owner_company,
                    scope, status, current_version, derived_from_asset_id, created_at, updated_at, config_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, NULL, ?, ?, ?)
                """,
                (
                    asset_id, asset_type, name, str(payload.get("description") or "").strip(),
                    actor.user_id, actor.user_id, actor.user_id, actor.user_id,
                    actor.department, actor.company, scope, now, now,
                    self._json(config),
                ),
            )
            created_row = self._asset_row(conn, asset_id)
            self._replace_asset_tags(conn, created_row, actor.user_id, payload.get("tags"))
            for evaluation in list(payload.get("model_evaluations") or []):
                if asset_type != "skill":
                    break
                self._insert_skill_model_evaluation(conn, actor, created_row, evaluation)
            self._snapshot(conn, asset_id, actor.user_id, "创建资产草稿", bump=False)
            return self._present_asset(conn, actor, self._asset_row(conn, asset_id))
        return self._run(actor_id, "create", work, request_id=payload.get("request_id"))

    def query_asset_registry(self, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """按登记字段查询资产，不把标签或查询条件当作授权依据。"""
        payload = payload or {}

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset_id = str(payload.get("asset_id") or "").strip()
            asset_types: set[str] = set()
            allowed_statuses: set[str] = set()
            keyword = ""
            tag_filters: dict[str, Any] = {}
            if asset_id:
                asset = self._asset_row(conn, asset_id)
                if not self._discoverable(conn, actor, asset):
                    raise EngineError("当前真人无权查看该资产，不能通过资产编号绕过权限", 403, "NO_READ_PERMISSION")
                items = [self._present_asset(conn, actor, asset)]
            else:
                raw_types = payload.get("asset_types") or payload.get("asset_type") or []
                asset_types = {str(item) for item in (raw_types if isinstance(raw_types, list) else [raw_types]) if item}
                if asset_types and not asset_types.issubset({"agent", "skill", "knowledge_base"}):
                    raise EngineError("只能查询 Agent、Skill、知识库三类资产", 400, "BAD_ASSET_TYPE_FILTER")
                statuses = payload.get("statuses") or payload.get("status") or []
                allowed_statuses = {str(item) for item in (statuses if isinstance(statuses, list) else [statuses]) if item}
                keyword = str(payload.get("keyword") or "").strip().lower()
                tag_filters = payload.get("tags") or {}
                if not isinstance(tag_filters, dict):
                    raise EngineError("tags 查询条件必须是对象", 400, "BAD_TAG_FILTER")
                rows = conn.execute(
                    "SELECT * FROM assets WHERE asset_type IN ('agent','skill','knowledge_base') ORDER BY updated_at DESC"
                ).fetchall()
                items = []
                for row in rows:
                    if asset_types and row["asset_type"] not in asset_types:
                        continue
                    if allowed_statuses and row["status"] not in allowed_statuses:
                        continue
                    if keyword and keyword not in f"{row['asset_id']} {row['asset_name']} {row['description']}".lower():
                        continue
                    tags = self._asset_tags(conn, row["asset_id"])
                    if any(
                        not any(tag["key"] == str(key) and tag["value"] == str(value) for tag in tags)
                        for key, value in tag_filters.items()
                    ):
                        continue
                    if not self._discoverable(conn, actor, row):
                        continue
                    items.append(self._present_asset(conn, actor, row))
            return {
                "items": items,
                "count": len(items),
                "query": {
                    "asset_id": asset_id or None,
                    "asset_types": sorted(asset_types) if not asset_id else None,
                    "statuses": sorted(allowed_statuses) if not asset_id else None,
                    "keyword": keyword or None,
                    "tags": tag_filters,
                },
                "boundary": "查询条件和标签只用于定位登记信息；查看范围仍由外部权限模块按当前真人实时判定。",
            }

        return self._run(actor_id, "query_asset_registry", work, request_id=payload.get("request_id"))

    def register_knowledge_source_result(
        self, actor_id: str, source_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """登记经流程执行引擎转交的解析/索引摘要，不读取或保存文件正文。"""
        payload = payload or {}
        with closing(self.connect()) as conn:
            existing = conn.execute("SELECT asset_id FROM sources WHERE source_id=?", (source_id,)).fetchone()
        asset_id = existing["asset_id"] if existing else None

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            if not actor.is_platform_operator:
                raise EngineError("知识源处理回执只能由技术接入真人登记", 403, "NO_SOURCE_RESULT_CALLBACK_PERMISSION")
            source = self._source_row(conn, source_id)
            outcome = str(payload.get("processing_status") or payload.get("outcome") or "").lower()
            if outcome not in {"success", "failed"}:
                raise EngineError("处理回执状态只能是 success 或 failed", 400, "BAD_SOURCE_RESULT_STATUS")
            result = {
                "parser_task_ref": str(payload.get("parser_task_ref") or "").strip() or None,
                "knowledge_ref": str(payload.get("knowledge_ref") or "").strip() or None,
                "index_ref": str(payload.get("index_ref") or "").strip() or None,
                "result_summary": str(payload.get("result_summary") or "").strip(),
                "error_code": str(payload.get("error_code") or "").strip() or None,
                "callback_mode": str(payload.get("callback_mode") or "external"),
                "note": "仅登记文档表格解析引擎处理回执，不保存原文或向量内容。",
            }
            conn.execute(
                "UPDATE sources SET parse_status=?, parse_result_json=?, updated_at=? WHERE source_id=?",
                (outcome, self._json(result), self._now(), source_id),
            )
            item = dict(self._source_row(conn, source_id))
            item["parse_result"] = self._decode(item.pop("parse_result_json"))
            return item

        return self._run(actor_id, "register_knowledge_source_result", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def process_flow_task(self, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """处理流程执行引擎经 L2 对内通道派发的标准任务信封。

        本方法只做登记动作分派，绝不组织流程、直接调用同层引擎或读取业务数据。
        """
        payload = payload or {}
        source, target, context = self._validate_standard_flow_envelope(actor_id, payload)
        actor_info = payload["actor"]
        requested_action = str(payload.get("action") or "").strip()
        # 正式信封的 target 是引擎级地址（l2.digital_asset），具体服务由
        # action 唯一确定；service_code 仅保留给本地旧页面兼容，不能要求
        # 联调方额外传一个不在协议中的字段。
        raw_service_code = str(
            payload.get("service_code") or f"l2.digital_asset.{requested_action}"
        ).strip()
        service_code = FLOW_SERVICE_ALIASES.get(raw_service_code, raw_service_code)
        action = requested_action or str(FLOW_SERVICE_CATALOG.get(service_code) or "").strip()
        source_layer = str(source.get("layer") or "")
        source_service = str(source.get("service_code") or "")
        target_layer = str(target.get("layer") or "")
        target_service = str(target.get("service_code") or "")
        channel = str(payload.get("channel") or "")
        if source_layer != "L2" or source_service != "l2.workflow_execution" or channel != "l2_internal":
            raise EngineError("标准任务必须来自 L2 流程执行引擎并经 l2_internal 通道派发", 403, "BAD_TASK_SOURCE")
        if target_layer != "L2" or target_service != "l2.digital_asset":
            raise EngineError("标准任务目标必须是 L2 数字资产引擎", 400, "BAD_TASK_TARGET")
        expected_action = FLOW_SERVICE_CATALOG.get(service_code)
        if not expected_action:
            raise EngineError("未登记的数字资产服务代码", 400, "UNSUPPORTED_FLOW_SERVICE")
        if action != expected_action:
            raise EngineError("服务代码与 action 不一致", 400, "FLOW_ACTION_MISMATCH")

        task_id = str(context["task_id"])
        workflow_instance_id = str(context["workflow_instance_id"])
        trace_id = str(payload["trace_id"])
        request_id = str(payload["request_id"])
        idempotency_key = str(payload["idempotency_key"])
        action_payload = dict(payload.get("payload") or {})
        action_payload["request_id"] = request_id
        now = self._now()
        with closing(self.connect()) as conn:
            self._actor_from_conn(conn, actor_id)
            existing = conn.execute("SELECT * FROM flow_tasks WHERE task_id=?", (task_id,)).fetchone()
            existing_by_key = conn.execute(
                "SELECT * FROM flow_tasks WHERE actor_id=? AND idempotency_key=?",
                (actor_id, idempotency_key),
            ).fetchone()
            if existing_by_key and (not existing or existing_by_key["task_id"] != task_id):
                if existing_by_key["service_code"] != service_code:
                    raise EngineError("同一幂等键不能用于不同服务", 409, "IDEMPOTENCY_CONFLICT")
                response = self._decode(existing_by_key["response_json"])
                if response:
                    response["idempotent_replay"] = True
                    return response
            if existing:
                if (
                    existing["actor_id"] != actor_id
                    or existing["service_code"] != service_code
                    or existing["idempotency_key"] != idempotency_key
                ):
                    raise EngineError("task_id 或幂等键已被其他真人或服务使用", 409, "IDEMPOTENCY_CONFLICT")
                response = self._decode(existing["response_json"])
                if response:
                    response["idempotent_replay"] = True
                    return response
            conn.execute(
                """
                INSERT INTO flow_tasks(task_id, workflow_instance_id, trace_id, idempotency_key, source_layer,
                    service_code, target_engine, actor_id, payload_json, status,
                    response_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'L2_FLOW_EXECUTION', ?, 'digital_asset_engine', ?, ?, 'accepted', '{}', ?, ?)
                """,
                (task_id, workflow_instance_id, trace_id, idempotency_key, service_code, actor_id,
                 self._json(action_payload), now, now),
            )
            conn.commit()

        try:
            if action == "asset.create":
                if action_payload.get("name") and not action_payload.get("asset_name"):
                    action_payload["asset_name"] = action_payload["name"]
                owner = str(action_payload.get("owner_person_id") or "").strip()
                if owner and owner != actor_id:
                    raise EngineError("资产责任真人必须与当前请求真人一致；不能替他人创建登记", 403, "OWNER_ACTOR_MISMATCH")
                result = self.create_asset(actor_id, action_payload)
            elif action == "asset.update":
                asset_id = str(action_payload.pop("asset_id", "")).strip()
                if action_payload.get("name") and not action_payload.get("asset_name"):
                    action_payload["asset_name"] = action_payload.pop("name")
                if not asset_id:
                    raise EngineError("asset.update 缺少 asset_id", 400, "MISSING_ASSET_ID")
                result = self.update_asset(actor_id, asset_id, action_payload)
            elif action == "asset.delete":
                asset_id = str(action_payload.get("asset_id") or "").strip()
                if not asset_id:
                    raise EngineError("asset.delete 缺少 asset_id", 400, "MISSING_ASSET_ID")
                result = self.delete_draft(actor_id, asset_id, action_payload)
            elif action == "asset.query":
                result = self.query_asset_registry(actor_id, action_payload)
            elif action == "skill.model_evaluation.register":
                asset_id = str(action_payload.pop("asset_id", action_payload.pop("asset_ref", ""))).strip()
                if not asset_id:
                    raise EngineError("技能模型评测缺少 asset_id", 400, "MISSING_ASSET_ID")
                result = self.register_skill_model_evaluation(actor_id, asset_id, action_payload)
            elif action == "skill.development.request":
                asset_id = str(action_payload.get("asset_id") or "").strip()
                if not asset_id:
                    raise EngineError("Skill 研发需求缺少 asset_id", 400, "MISSING_ASSET_ID")
                result = self.submit_skill_development(actor_id, asset_id, action_payload)
            elif action == "skill.implementation.register":
                development_id = str(action_payload.get("development_id") or "").strip()
                if not development_id:
                    raise EngineError("候选实现回执缺少 development_id", 400, "MISSING_DEVELOPMENT_ID")
                result = self.register_skill_candidate(actor_id, development_id, action_payload)
            elif action == "knowledge_source.register":
                asset_id = str(action_payload.pop("knowledge_base_ref", action_payload.pop("asset_id", ""))).strip()
                artifact_ref = str(action_payload.pop("artifact_ref", action_payload.get("object_uri") or "")).strip()
                if not asset_id:
                    raise EngineError("知识源登记缺少 knowledge_base_ref", 400, "MISSING_KNOWLEDGE_BASE_REF")
                if not artifact_ref:
                    raise EngineError("知识源登记缺少 artifact_ref", 400, "MISSING_ARTIFACT_REF")
                action_payload.setdefault("object_uri", artifact_ref)
                action_payload.setdefault("file_name", artifact_ref.rsplit("/", 1)[-1] or artifact_ref)
                result = self.add_source(actor_id, asset_id, action_payload)
            elif action == "knowledge_source.result.register":
                source_id = str(action_payload.get("source_id") or "").strip()
                if not source_id:
                    raise EngineError("知识源处理回执缺少 source_id", 400, "MISSING_SOURCE_ID")
                parent_task_id = str(action_payload.get("parent_task_id") or "").strip()
                artifact_ref = str(action_payload.get("artifact_ref") or "").strip()
                if not parent_task_id or not artifact_ref:
                    raise EngineError(
                        "知识源处理回执必须携带 parent_task_id 和 artifact_ref",
                        400,
                        "MISSING_KNOWLEDGE_SOURCE_CORRELATION",
                    )
                with closing(self.connect()) as conn:
                    parent = conn.execute("SELECT * FROM flow_tasks WHERE task_id=?", (parent_task_id,)).fetchone()
                    source_row = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
                if not parent or parent["trace_id"] != trace_id or parent["service_code"] != "l2.digital_asset.knowledge_source.register":
                    raise EngineError("知识源处理回执与原登记任务不匹配", 409, "KNOWLEDGE_SOURCE_CALLBACK_MISMATCH")
                if not source_row or str(source_row["object_uri"] or "") != artifact_ref:
                    raise EngineError("知识源处理回执的 artifact_ref 与原知识源不一致", 409, "KNOWLEDGE_SOURCE_ARTIFACT_MISMATCH")
                result = self.register_knowledge_source_result(actor_id, source_id, action_payload)
            else:  # 防御性分支，理论上已被服务目录阻止。
                raise EngineError("未实现的数字资产任务动作", 400, "UNSUPPORTED_FLOW_ACTION")
            is_async = action == "knowledge_source.register"
            reply_type = "accepted" if is_async else "success"
            receipt = {
                # reply_type 是跨模块正式协议字段；type 仅保留给旧控制台读取。
                "reply_type": reply_type,
                "type": reply_type,
                "code": "FLOW_TASK_ACCEPTED" if is_async else "FLOW_TASK_SUCCEEDED",
                "message": (
                    "知识源登记已受理，等待文档表格解析引擎经流程执行引擎回调"
                    if is_async else f"数字资产引擎已完成 {action} 登记任务"
                ),
                "task_id": task_id,
                "workflow_instance_id": workflow_instance_id,
                "trace_id": trace_id,
                "message_id": payload["message_id"],
                "parent_message_id": payload["parent_message_id"],
                "idempotency_key": idempotency_key,
                "service_code": service_code,
                "action": action,
                "result": result,
            }
            if is_async:
                receipt["callback_expected"] = True
                receipt["callback_action"] = "knowledge_source.result.register"
                receipt["correlation"] = {
                    "trace_id": trace_id,
                    "parent_task_id": task_id,
                    "source_id": result.get("source_id"),
                    "artifact_ref": action_payload.get("artifact_ref") or action_payload.get("object_uri"),
                }
            status = "accepted" if is_async else "completed"
        except EngineError as exc:
            receipt = {
                "reply_type": "failed", "type": "failed", "code": exc.code, "message": exc.message,
                "task_id": task_id, "workflow_instance_id": workflow_instance_id,
                "trace_id": trace_id, "service_code": service_code, "action": action,
                "message_id": payload["message_id"], "parent_message_id": payload["parent_message_id"],
                "idempotency_key": idempotency_key, "retryable": False,
            }
            status = "rejected"
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE flow_tasks SET status=?, response_json=?, updated_at=? WHERE task_id=?",
                (status, self._json(receipt), self._now(), task_id),
            )
            conn.commit()
        return receipt

    def update_asset(self, actor_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if not self._capabilities(conn, actor, asset)["modify"]:
                raise EngineError("当前真人无权修改该草稿；管理岗位也不能直接修改员工个人资产", 403, "NO_UPDATE_PERMISSION")
            name = str(payload.get("asset_name", asset["asset_name"])).strip()
            description = str(payload.get("description", asset["description"])).strip()
            current_config = self._decode(asset["config_json"])
            incoming_config = dict(payload.get("config") or {})
            if asset["asset_type"] == "skill":
                # 工具实现只能通过专用绑定动作修改，防止普通 update 绕过工具注册和版本校验。
                for protected in (
                    "tool_id", "tool_version", "implementation_type", "implementation_status",
                    "lifecycle_stage", "validation_status", "validated_at", "tool_checksum",
                    "input_schema", "output_schema", "bound_at", "bound_by",
                ):
                    incoming_config.pop(protected, None)
            config = {**current_config, **incoming_config}
            if asset["asset_type"] == "skill":
                # 任意草稿变更都使旧验证失效，防止“验证 A、发布 B”。
                config["validation_status"] = "not_validated"
                config["implementation_status"] = "bound" if config.get("tool_id") else "requested"
                config["lifecycle_stage"] = "implementation_bound" if config.get("tool_id") else "requirement_draft"
                config.pop("validated_at", None)
                config.pop("tool_checksum", None)
            conn.execute(
                "UPDATE assets SET asset_name=?, description=?, config_json=?, updated_at=? WHERE asset_id=?",
                (name, description, self._json(config), self._now(), asset_id),
            )
            if "tags" in payload:
                self._replace_asset_tags(conn, self._asset_row(conn, asset_id), actor.user_id, payload.get("tags"))
            self._snapshot(conn, asset_id, actor.user_id, payload.get("change_summary") or "修改草稿", bump=True)
            return self._asset_dict(self._asset_row(conn, asset_id))
        return self._run(actor_id, "update", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def submit_skill_development(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["asset_type"] != "skill":
                raise EngineError("只有 Skill 需求可以提交研发", 400, "DEVELOPMENT_REQUIRES_SKILL")
            if asset["status"] != "draft" or not self._capabilities(conn, actor, asset)["modify"]:
                raise EngineError("只有 Skill 草稿维护人可以提交研发", 403, "NO_SKILL_DEVELOPMENT_PERMISSION")
            config = self._decode(asset["config_json"])
            if config.get("tool_id") or config.get("tool_version"):
                raise EngineError("该 Skill 已绑定实现，无需重复提交研发", 409, "SKILL_IMPLEMENTATION_ALREADY_BOUND")
            if self._active_development_request(conn, asset_id):
                raise EngineError("该 Skill 已有进行中的研发任务", 409, "SKILL_DEVELOPMENT_ALREADY_ACTIVE")
            requirement = dict(config.get("requirement") or {})
            required_fields = ("input_definition", "output_definition", "acceptance_criteria")
            if any(not str(requirement.get(field) or "").strip() for field in required_fields):
                raise EngineError("提交研发前必须完整填写输入、输出和验收标准", 400, "INCOMPLETE_SKILL_REQUIREMENT")
            candidate_source = str(config.get("candidate_source") or "undecided")
            target_system = {
                "evolution": "L1进化机制",
                "developer": "研发任务队列",
                "existing_api": "外部系统对接队列",
                "workflow": "流程执行引擎",
                "undecided": "待分派研发队列",
            }.get(candidate_source, "待分派研发队列")
            development_id = self._new_id("dev")
            now = self._now()
            conn.execute(
                """
                INSERT INTO skill_development_requests(
                    development_id, asset_id, submitter_id, target_system, requirement_json,
                    status, submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'submitted', ?, ?)
                """,
                (development_id, asset_id, actor.user_id, target_system, self._json(requirement), now, now),
            )
            config.update(
                {
                    "development_id": development_id,
                    "implementation_status": "development_submitted",
                    "lifecycle_stage": "development_submitted",
                }
            )
            conn.execute(
                "UPDATE assets SET config_json=?, updated_at=? WHERE asset_id=?",
                (self._json(config), now, asset_id),
            )
            self._snapshot(conn, asset_id, actor.user_id, f"提交 Skill 研发任务 {development_id}", bump=True)
            return self._development_request_dict(self._development_request_row(conn, development_id))

        return self._run(
            actor_id,
            "submit_skill_development",
            work,
            asset_id=asset_id,
            request_id=payload.get("request_id"),
        )

    def register_skill_candidate(self, actor_id: str, development_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            development = self._development_request_row(conn, development_id)
            development_asset_id = development["asset_id"]

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            if not actor.is_platform_operator:
                raise EngineError("候选回传接口仅允许演示环境技术接入身份调用", 403, "NO_CANDIDATE_CALLBACK_PERMISSION")
            development = self._development_request_row(conn, development_id)
            if development["status"] != "submitted":
                raise EngineError("研发任务当前状态不接受重复候选回传", 409, "DEVELOPMENT_NOT_ACCEPTING_CANDIDATE")
            tool_id = str(payload.get("tool_id") or "").strip()
            tool_version = str(payload.get("tool_version") or "").strip()
            tool_row = conn.execute(
                "SELECT * FROM tool_registry WHERE tool_id=? AND version=? AND enabled=1",
                (tool_id, tool_version),
            ).fetchone()
            if not tool_row or (tool_id, tool_version) not in TOOL_DEFINITIONS:
                raise EngineError("候选实现尚未进入可执行固定工具登记库", 409, "CANDIDATE_TOOL_NOT_REGISTERED")
            callback_mode = str(payload.get("callback_mode") or "mock")
            if callback_mode not in {"mock", "external"}:
                raise EngineError("候选回传模式不合法", 400, "BAD_CANDIDATE_CALLBACK_MODE")
            now = self._now()
            artifact_uri = str(payload.get("artifact_uri") or f"mock://skill-candidates/{development_id}/{tool_id}@{tool_version}")
            test_report_uri = str(payload.get("test_report_uri") or f"mock://skill-candidate-tests/{development_id}")
            conn.execute(
                """
                UPDATE skill_development_requests
                SET status='ready_to_bind', candidate_tool_id=?, candidate_tool_version=?,
                    candidate_artifact_uri=?, candidate_test_report_uri=?, callback_mode=?, updated_at=?
                WHERE development_id=?
                """,
                (tool_id, tool_version, artifact_uri, test_report_uri, callback_mode, now, development_id),
            )
            asset = self._asset_row(conn, development["asset_id"])
            config = self._decode(asset["config_json"])
            config.update(
                {
                    "lifecycle_stage": "candidate_ready",
                    "implementation_status": "candidate_ready",
                    "candidate": {
                        "development_id": development_id,
                        "tool_id": tool_id,
                        "tool_version": tool_version,
                        "callback_mode": callback_mode,
                    },
                }
            )
            conn.execute(
                "UPDATE assets SET config_json=?, updated_at=? WHERE asset_id=?",
                (self._json(config), now, development["asset_id"]),
            )
            self._snapshot(
                conn, development["asset_id"], actor.user_id,
                f"登记候选实现 {tool_id}@{tool_version}（{callback_mode}）", bump=True,
            )
            return self._development_request_dict(self._development_request_row(conn, development_id))

        return self._run(
            actor_id,
            "register_skill_candidate",
            work,
            asset_id=development_asset_id,
            request_id=payload.get("request_id"),
        )

    def bind_skill_implementation(self, actor_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["asset_type"] != "skill":
                raise EngineError("只有 Skill 资产可以绑定实现", 400, "BINDING_REQUIRES_SKILL")
            if asset["status"] != "draft" or not self._capabilities(conn, actor, asset)["bindSkillImplementation"]:
                raise EngineError("只有 Skill 草稿维护人可以绑定实现", 403, "NO_SKILL_BIND_PERMISSION")
            tool_id = str(payload.get("tool_id") or "").strip()
            tool_version = str(payload.get("tool_version") or "").strip()
            if not tool_id or not tool_version:
                raise EngineError("必须选择已登记工具及版本", 400, "MISSING_SKILL_IMPLEMENTATION")
            tool_row = conn.execute(
                "SELECT * FROM tool_registry WHERE tool_id=? AND version=? AND enabled=1",
                (tool_id, tool_version),
            ).fetchone()
            if not tool_row or (tool_id, tool_version) not in TOOL_DEFINITIONS:
                raise EngineError("该工具版本未登记、已停用或不可执行", 409, "SKILL_TOOL_UNAVAILABLE")

            config = self._decode(asset["config_json"])
            config.update(
                {
                    "tool_id": tool_id,
                    "tool_version": tool_version,
                    "implementation_type": "fixed_tool",
                    "implementation_status": "bound",
                    "lifecycle_stage": "implementation_bound",
                    "validation_status": "not_validated",
                    "bound_at": self._now(),
                    "bound_by": actor.user_id,
                }
            )
            for stale in ("validated_at", "tool_checksum", "input_schema", "output_schema"):
                config.pop(stale, None)
            conn.execute(
                "UPDATE assets SET config_json=?, updated_at=? WHERE asset_id=?",
                (self._json(config), self._now(), asset_id),
            )
            conn.execute(
                """
                UPDATE skill_development_requests
                SET status='bound', updated_at=?
                WHERE asset_id=? AND status IN ('submitted', 'candidate_received', 'ready_to_bind')
                  AND (candidate_tool_id IS NULL OR (candidate_tool_id=? AND candidate_tool_version=?))
                """,
                (self._now(), asset_id, tool_id, tool_version),
            )
            self._snapshot(conn, asset_id, actor.user_id, f"绑定 Skill 实现 {tool_id}@{tool_version}", bump=True)
            return self._asset_dict(self._asset_row(conn, asset_id))

        return self._run(
            actor_id,
            "bind_skill_implementation",
            work,
            asset_id=asset_id,
            request_id=payload.get("request_id"),
        )

    def activate_personal(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if not (
                asset["scope"] == "personal"
                and asset["owner_real_id"] == actor.user_id
                and asset["status"] == "draft"
            ):
                raise EngineError("只有创建人可将自己的个人草稿设为个人启用", 403, "NO_PERSONAL_ACTIVATE_PERMISSION")
            self._assert_function_ready(conn, asset)
            conn.execute("UPDATE assets SET status='personal_active', updated_at=? WHERE asset_id=?", (self._now(), asset_id))
            self._snapshot(conn, asset_id, actor.user_id, "个人启用（非发布）", bump=True)
            result = self._asset_dict(self._asset_row(conn, asset_id))
            if result["asset_type"] in FUNCTION_TYPES:
                self._upsert_registry(conn, result)
            return result
        return self._run(actor_id, "activate_personal", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def submit_adoption(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if not self._capabilities(conn, actor, asset)["submitAdoption"]:
                raise EngineError("只有创建人可提交已个人启用资产的部门采纳申请", 403, "NO_ADOPTION_PERMISSION")
            if self._pending_for_asset(conn, asset_id):
                raise EngineError("该资产已有待处理工作流", 409, "WORKFLOW_ALREADY_PENDING")
            position, approver_id = self._resolve_approver(conn, actor, "department")
            workflow_id = self._new_id("wf")
            conn.execute(
                """
                INSERT INTO workflows(workflow_id, kind, asset_id, result_asset_id, target_scope,
                    submitter_id, approval_position, approver_id, status, reason, submitted_at, resolved_at)
                VALUES (?, 'adoption', ?, NULL, 'department', ?, ?, ?, 'pending', ?, ?, NULL)
                """,
                (workflow_id, asset_id, actor.user_id, position, approver_id, payload.get("reason"), self._now()),
            )
            return self._workflow_dict(self._workflow_row(conn, workflow_id))
        return self._run(actor_id, "submit_adoption", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def submit_publish(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if not (
                asset["maintainer_id"] == actor.user_id
                and asset["scope"] in {"department", "company"}
                and asset["status"] == "draft"
                and not self._pending_for_asset(conn, asset_id)
            ):
                raise EngineError("只有部门/公司草稿维护人可提交发布审批", 403, "NO_SUBMIT_PUBLISH_PERMISSION")
            self._assert_function_ready(conn, asset)
            if self._pending_for_asset(conn, asset_id):
                raise EngineError("该资产已有待处理工作流", 409, "WORKFLOW_ALREADY_PENDING")
            position, approver_id = self._resolve_approver(conn, actor, asset["scope"])
            kind = "department_publish" if asset["scope"] == "department" else "company_publish"
            workflow_id = self._new_id("wf")
            conn.execute("UPDATE assets SET status='pending_publish', updated_at=? WHERE asset_id=?", (self._now(), asset_id))
            conn.execute(
                """
                INSERT INTO workflows(workflow_id, kind, asset_id, result_asset_id, target_scope,
                    submitter_id, approval_position, approver_id, status, reason, submitted_at, resolved_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 'pending', ?, ?, NULL)
                """,
                (workflow_id, kind, asset_id, asset["scope"], actor.user_id, position, approver_id, payload.get("reason"), self._now()),
            )
            return self._workflow_dict(self._workflow_row(conn, workflow_id))
        return self._run(actor_id, "submit_publish", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def _workflow_capabilities(self, actor: Actor, workflow: sqlite3.Row) -> dict[str, bool]:
        can_decide = workflow["status"] == "pending" and workflow["approver_id"] == actor.user_id and workflow["submitter_id"] != actor.user_id
        return {"approve": can_decide, "reject": can_decide}

    def approve_workflow(self, actor_id: str, workflow_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            workflow = self._workflow_row(conn, workflow_id)
            if not self._workflow_capabilities(actor, workflow)["approve"]:
                raise EngineError("只有固定模板定位的当前审批真人可批准，且提交人与审批人必须分离", 403, "NO_WORKFLOW_APPROVAL_PERMISSION")
            asset = self._asset_row(conn, workflow["asset_id"])
            self._assert_mutable_state(asset)
            result_asset_id = None
            if workflow["kind"] == "adoption":
                if asset["scope"] != "personal" or asset["status"] != "personal_active":
                    raise EngineError("采纳源资产必须仍为个人启用状态", 409, "ADOPTION_SOURCE_STATE_CHANGED")
                result_asset_id = self._new_id("asset")
                now = self._now()
                source_config = self._decode(asset["config_json"])
                derived_config = {**source_config, "adoption_source": asset["asset_id"], "adoption_workflow": workflow_id}
                conn.execute(
                    """
                    INSERT INTO assets(asset_id, asset_type, asset_name, description, owner_real_id,
                        creator_id, contributor_id, maintainer_id, owner_department, owner_company,
                        scope, status, current_version, derived_from_asset_id, created_at, updated_at, config_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'department', 'draft', 1, ?, ?, ?, ?)
                    """,
                    (
                        result_asset_id, asset["asset_type"], asset["asset_name"], asset["description"],
                        asset["owner_real_id"], asset["creator_id"], asset["owner_real_id"], actor.user_id,
                        asset["owner_department"], asset["owner_company"], asset["asset_id"], now, now,
                        self._json(derived_config),
                    ),
                )
                self._snapshot(conn, result_asset_id, actor.user_id, "采纳通过，生成独立部门草稿", bump=False)
                conn.execute("UPDATE assets SET status='adopted', updated_at=? WHERE asset_id=?", (self._now(), asset["asset_id"]))
                conn.execute("DELETE FROM function_registry WHERE asset_id=?", (asset["asset_id"],))
                self._snapshot(conn, asset["asset_id"], actor.user_id, "部门采纳通过，个人源资产归档", bump=True)
            else:
                if asset["status"] != "pending_publish":
                    raise EngineError("待审批资产状态已变化", 409, "PUBLISH_SOURCE_STATE_CHANGED")
                conn.execute("UPDATE assets SET status='published', updated_at=? WHERE asset_id=?", (self._now(), asset["asset_id"]))
                self._snapshot(conn, asset["asset_id"], actor.user_id, "固定审批通过并发布", bump=True)
                published = self._asset_dict(self._asset_row(conn, asset["asset_id"]))
                if published["asset_type"] in FUNCTION_TYPES:
                    self._upsert_registry(conn, published)
                result_asset_id = asset["asset_id"]
            conn.execute(
                "UPDATE workflows SET status='approved', result_asset_id=?, reason=?, resolved_at=? WHERE workflow_id=?",
                (result_asset_id, payload.get("reason"), self._now(), workflow_id),
            )
            result = self._workflow_dict(self._workflow_row(conn, workflow_id))
            result["result_asset"] = self._asset_dict(self._asset_row(conn, result_asset_id))
            return result
        workflow = None
        with closing(self.connect()) as conn:
            workflow = conn.execute("SELECT * FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
        asset_id = workflow["asset_id"] if workflow else None
        return self._run(actor_id, "approve_workflow", work, asset_id=asset_id, workflow_id=workflow_id, request_id=payload.get("request_id"))

    def reject_workflow(self, actor_id: str, workflow_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            workflow = self._workflow_row(conn, workflow_id)
            if not self._workflow_capabilities(actor, workflow)["reject"]:
                raise EngineError("只有固定模板定位的当前审批真人可驳回", 403, "NO_WORKFLOW_REJECT_PERMISSION")
            reason = str(payload.get("reason") or "").strip()
            if not reason:
                raise EngineError("驳回必须填写原因", 400, "MISSING_REJECT_REASON")
            if workflow["kind"] != "adoption":
                conn.execute("UPDATE assets SET status='draft', updated_at=? WHERE asset_id=?", (self._now(), workflow["asset_id"]))
            conn.execute(
                "UPDATE workflows SET status='rejected', reason=?, resolved_at=? WHERE workflow_id=?",
                (reason, self._now(), workflow_id),
            )
            return self._workflow_dict(self._workflow_row(conn, workflow_id))
        workflow = None
        with closing(self.connect()) as conn:
            workflow = conn.execute("SELECT * FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone()
        asset_id = workflow["asset_id"] if workflow else None
        return self._run(actor_id, "reject_workflow", work, asset_id=asset_id, workflow_id=workflow_id, request_id=payload.get("request_id"))

    def disable_asset(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if not self._capabilities(conn, actor, asset)["disable"]:
                raise EngineError("当前真人无权停用该资产", 403, "NO_DISABLE_PERMISSION")
            conn.execute("UPDATE assets SET status='disabled', updated_at=? WHERE asset_id=?", (self._now(), asset_id))
            conn.execute("DELETE FROM function_registry WHERE asset_id=?", (asset_id,))
            self._snapshot(conn, asset_id, actor.user_id, payload.get("reason") or "停用资产", bump=True)
            return self._asset_dict(self._asset_row(conn, asset_id))
        return self._run(actor_id, "disable", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def delete_draft(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if not self._capabilities(conn, actor, asset)["deleteDraft"]:
                raise EngineError("只有创建人可逻辑删除自己的个人草稿", 403, "NO_DELETE_DRAFT_PERMISSION")
            conn.execute("UPDATE assets SET status='deleted', updated_at=? WHERE asset_id=?", (self._now(), asset_id))
            self._snapshot(conn, asset_id, actor.user_id, "逻辑删除个人草稿", bump=True)
            return self._asset_dict(self._asset_row(conn, asset_id))
        return self._run(actor_id, "delete_draft", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def add_source(self, actor_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["asset_type"] != "knowledge_base":
                raise EngineError("只有知识库容器可以登记待解析知识源", 400, "SOURCE_REQUIRES_KB")
            if not self._capabilities(conn, actor, asset)["addSource"]:
                raise EngineError("当前真人无权向该知识库登记知识源", 403, "NO_ADD_SOURCE_PERMISSION")
            file_name = str(payload.get("file_name") or "").strip()
            if not file_name:
                raise EngineError("文件名不能为空", 400, "MISSING_FILE_NAME")
            source_id = self._new_id("src")
            now = self._now()
            conn.execute(
                """
                INSERT INTO sources(source_id, asset_id, file_name, source_type, object_uri,
                    description, storage_status, parse_status, parser_service, parse_result_json,
                    created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'registered', 'pending', 'document_table_parser', '{}', ?, ?, ?)
                """,
                (
                    source_id, asset_id, file_name, payload.get("source_type") or "document",
                    payload.get("object_uri"), str(payload.get("description") or "").strip(),
                    actor.user_id, now, now,
                ),
            )
            self._snapshot(conn, asset_id, actor.user_id, "登记知识源", bump=True)
            return dict(self._source_row(conn, source_id))
        return self._run(actor_id, "add_source", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def parse_source(self, actor_id: str, source_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        with closing(self.connect()) as conn:
            source = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
        asset_id = source["asset_id"] if source else None
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            source_row = self._source_row(conn, source_id)
            asset = self._asset_row(conn, source_row["asset_id"])
            self._assert_mutable_state(asset)
            capabilities = self._capabilities(conn, actor, asset)
            if not capabilities["addSource"]:
                raise EngineError("当前真人无权触发该知识源解析任务", 403, "NO_PARSE_SOURCE_PERMISSION")
            outcome = payload.get("outcome") or "success"
            if outcome not in {"success", "failed"}:
                raise EngineError("解析结果只能是 success 或 failed", 400, "BAD_PARSE_OUTCOME")
            result = payload.get("result") or {
                "parser": "文档表格解析引擎 Mock",
                "note": "数字资产引擎仅登记解析状态，不执行真实解析",
            }
            conn.execute(
                "UPDATE sources SET parse_status=?, parse_result_json=?, updated_at=? WHERE source_id=?",
                (outcome, self._json(result), self._now(), source_id),
            )
            item = dict(self._source_row(conn, source_id))
            item["parse_result"] = self._decode(item.pop("parse_result_json"))
            return item
        return self._run(actor_id, "parse_source", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def request_l1_knowledge_base(
        self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """为 L2 知识库资产申请一个 L1 知识库实例；申请本身不代表建库成功。"""
        payload = payload or {}

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["asset_type"] != "knowledge_base":
                raise EngineError("只有知识库资产可以申请 L1 知识库实例", 400, "L1_KB_REQUIRES_KB_ASSET")
            if not self._capabilities(conn, actor, asset)["requestL1KnowledgeBase"]:
                raise EngineError("当前真人无权为该资产申请 L1 知识库实例，或申请已经存在", 403, "NO_L1_KB_REQUEST_PERMISSION")
            binding_id = self._new_id("kbbind")
            now = self._now()
            conn.execute(
                """
                INSERT INTO knowledge_base_instances(binding_id, asset_id, requested_by, target_module,
                    status, l1_kb_id, namespace, provider, callback_mode, requested_at, updated_at)
                VALUES (?, ?, ?, 'L1 1.13 知识库模块', 'requested', NULL, NULL, NULL, NULL, ?, ?)
                """,
                (binding_id, asset_id, actor.user_id, now, now),
            )
            return dict(self._kb_instance_row(conn, binding_id))

        return self._run(
            actor_id, "request_l1_knowledge_base", work, asset_id=asset_id,
            request_id=payload.get("request_id"),
        )

    def register_l1_knowledge_base(
        self, actor_id: str, binding_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """登记 L1 模块的建库回执；只有技术接入身份可以写回。"""
        payload = payload or {}
        with closing(self.connect()) as conn:
            existing = conn.execute(
                "SELECT asset_id FROM knowledge_base_instances WHERE binding_id=?", (binding_id,)
            ).fetchone()
        asset_id = existing["asset_id"] if existing else None

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            if not actor.is_platform_operator:
                raise EngineError("只有 L1 技术接入身份可以登记建库回执", 403, "NO_L1_KB_CALLBACK_PERMISSION")
            binding = self._kb_instance_row(conn, binding_id)
            if binding["status"] != "requested":
                raise EngineError("该建库申请已经处理，不能重复回调", 409, "L1_KB_ALREADY_RESOLVED")
            outcome = str(payload.get("outcome") or "ready")
            if outcome not in {"ready", "failed"}:
                raise EngineError("建库回执只能是 ready 或 failed", 400, "BAD_L1_KB_OUTCOME")
            callback_mode = str(payload.get("callback_mode") or "external")
            if callback_mode not in {"external", "mock"}:
                raise EngineError("回调方式只能是 external 或 mock", 400, "BAD_CALLBACK_MODE")
            l1_kb_id = str(payload.get("l1_kb_id") or "").strip()
            namespace = str(payload.get("namespace") or "").strip()
            provider = str(payload.get("provider") or "L1 1.13 知识库模块").strip()
            if outcome == "ready" and (not l1_kb_id or not namespace):
                raise EngineError("成功回执必须包含 L1 实例编号和命名空间", 400, "MISSING_L1_KB_IDENTITY")
            conn.execute(
                """
                UPDATE knowledge_base_instances
                SET status=?, l1_kb_id=?, namespace=?, provider=?, callback_mode=?, updated_at=?
                WHERE binding_id=?
                """,
                (outcome, l1_kb_id or None, namespace or None, provider, callback_mode, self._now(), binding_id),
            )
            return dict(self._kb_instance_row(conn, binding_id))

        return self._run(
            actor_id, "register_l1_knowledge_base", work, asset_id=asset_id,
            request_id=payload.get("request_id"),
        )

    def register_source_index(
        self, actor_id: str, source_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """登记 L1 对某个知识源的切片/向量索引回执；不在本引擎内执行向量化。"""
        payload = payload or {}
        with closing(self.connect()) as conn:
            existing = conn.execute("SELECT asset_id FROM sources WHERE source_id=?", (source_id,)).fetchone()
        asset_id = existing["asset_id"] if existing else None

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            if not actor.is_platform_operator:
                raise EngineError("只有 L1 技术接入身份可以登记索引回执", 403, "NO_INDEX_CALLBACK_PERMISSION")
            source = self._source_row(conn, source_id)
            if source["parse_status"] != "success":
                raise EngineError("文档解析尚未成功，不能登记向量索引结果", 409, "SOURCE_NOT_PARSED")
            binding = self._kb_instance_for_asset(conn, source["asset_id"])
            if not binding or binding["status"] != "ready":
                raise EngineError("尚未获得可用的 L1 知识库实例，不能登记索引结果", 409, "L1_KB_NOT_READY")
            outcome = str(payload.get("outcome") or "indexed")
            if outcome not in {"indexed", "failed"}:
                raise EngineError("索引回执只能是 indexed 或 failed", 400, "BAD_INDEX_OUTCOME")
            callback_mode = str(payload.get("callback_mode") or "external")
            if callback_mode not in {"external", "mock"}:
                raise EngineError("回调方式只能是 external 或 mock", 400, "BAD_CALLBACK_MODE")
            chunk_count = int(payload.get("chunk_count") or 0)
            vector_count = int(payload.get("vector_count") or 0)
            if outcome == "indexed" and (chunk_count <= 0 or vector_count <= 0):
                raise EngineError("成功索引回执必须包含正数切片量和向量量", 400, "MISSING_INDEX_EVIDENCE")
            now = self._now()
            index_id = self._new_id("idx")
            conn.execute(
                """
                INSERT INTO knowledge_source_indexes(index_id, source_id, asset_id, binding_id, status,
                    chunk_count, vector_count, index_version, callback_mode, updated_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    binding_id=excluded.binding_id, status=excluded.status,
                    chunk_count=excluded.chunk_count, vector_count=excluded.vector_count,
                    index_version=excluded.index_version, callback_mode=excluded.callback_mode,
                    updated_by=excluded.updated_by, updated_at=excluded.updated_at
                """,
                (
                    index_id, source_id, source["asset_id"], binding["binding_id"], outcome,
                    chunk_count, vector_count, str(payload.get("index_version") or "v1"),
                    callback_mode, actor.user_id, now, now,
                ),
            )
            return dict(self._source_index_for_source(conn, source_id))

        return self._run(
            actor_id, "register_source_index", work, asset_id=asset_id,
            request_id=payload.get("request_id"),
        )

    def upload_knowledge_source(self, actor_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """接收知识库原件，保存到对象存储适配目录并登记待解析任务。"""

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["asset_type"] != "knowledge_base":
                raise EngineError("只有知识库可以接收知识源文件", 400, "SOURCE_REQUIRES_KB")
            if not self._capabilities(conn, actor, asset)["addSource"]:
                raise EngineError("当前真人无权向该知识库上传知识源", 403, "NO_ADD_SOURCE_PERMISSION")
            original_name = Path(str(payload.get("file_name") or "").strip()).name
            if not original_name:
                raise EngineError("知识源文件名不能为空", 400, "MISSING_FILE_NAME")
            extension = Path(original_name).suffix.lower()
            allowed = {".docx", ".xlsx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".txt"}
            if extension not in allowed:
                raise EngineError("知识源类型不支持", 400, "KNOWLEDGE_SOURCE_TYPE_REJECTED")
            try:
                content = base64.b64decode(str(payload.get("data_base64") or ""), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise EngineError("知识源内容不是有效 Base64", 400, "BAD_KNOWLEDGE_SOURCE_DATA") from exc
            if not content:
                raise EngineError("不能上传空知识源", 400, "EMPTY_KNOWLEDGE_SOURCE")
            if len(content) > 10 * 1024 * 1024:
                raise EngineError("MVP 单个知识源不能超过 10 MB", 413, "KNOWLEDGE_SOURCE_TOO_LARGE")

            source_id = self._new_id("src")
            stored_name = f"{source_id}{extension}"
            store_dir = self.db_path.parent / "object_store" / "knowledge_sources"
            store_dir.mkdir(parents=True, exist_ok=True)
            storage_path = (store_dir / stored_name).resolve()
            if store_dir.resolve() not in storage_path.parents:
                raise EngineError("知识源存储路径非法", 400, "BAD_KNOWLEDGE_STORAGE_PATH")
            storage_path.write_bytes(content)
            checksum = hashlib.sha256(content).hexdigest()
            now = self._now()
            object_uri = f"local-object://knowledge-sources/{stored_name}"
            content_type = str(payload.get("content_type") or "application/octet-stream")
            conn.execute(
                """
                INSERT INTO sources(source_id, asset_id, file_name, source_type, object_uri,
                    stored_name, content_type, size_bytes, checksum_sha256, description,
                    storage_status, parse_status, parser_service, parse_result_json,
                    created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'registered', 'pending',
                    'document_table_parser', '{}', ?, ?, ?)
                """,
                (
                    source_id, asset_id, original_name, extension.lstrip("."), object_uri,
                    stored_name, content_type, len(content), checksum,
                    str(payload.get("description") or "").strip(), actor.user_id, now, now,
                ),
            )
            self._snapshot(conn, asset_id, actor.user_id, f"上传知识源：{original_name}", bump=True)
            item = dict(self._source_row(conn, source_id))
            item["parse_result"] = self._decode(item.pop("parse_result_json", "{}"))
            item.pop("stored_name", None)
            return item

        return self._run(actor_id, "upload_knowledge_source", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def knowledge_source_for_download(self, actor_id: str, source_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            existing = conn.execute("SELECT asset_id FROM sources WHERE source_id=?", (source_id,)).fetchone()
        asset_id = existing["asset_id"] if existing else None

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            row = self._source_row(conn, source_id)
            asset = self._asset_row(conn, row["asset_id"])
            if not self._discoverable(conn, actor, asset) or not self._data_readable(conn, actor, asset):
                raise EngineError("当前真人无权下载该知识源原件", 403, "NO_KNOWLEDGE_SOURCE_DOWNLOAD_PERMISSION")
            if not row["stored_name"]:
                raise EngineError("该知识源仅登记了外部对象引用，本地没有原件", 404, "KNOWLEDGE_SOURCE_OBJECT_EXTERNAL")
            store_dir = (self.db_path.parent / "object_store" / "knowledge_sources").resolve()
            storage_path = (store_dir / row["stored_name"]).resolve()
            if store_dir not in storage_path.parents or not storage_path.is_file():
                raise EngineError("知识源原件在对象存储中不存在", 404, "KNOWLEDGE_SOURCE_OBJECT_MISSING")
            item = dict(row)
            item["original_name"] = item["file_name"]
            item["storage_path"] = str(storage_path)
            return item

        return self._run(actor_id, "download_knowledge_source", work, asset_id=asset_id)

    def upload_material_file(self, actor_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """保存素材原件到本地对象存储适配目录，并只在引擎登记引用与校验信息。"""

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["asset_type"] != "material":
                raise EngineError("只有素材资产可以上传素材文件", 400, "FILE_REQUIRES_MATERIAL")
            if not self._capabilities(conn, actor, asset)["uploadMaterial"]:
                raise EngineError("当前真人无权向该素材上传文件或新版本", 403, "NO_MATERIAL_UPLOAD_PERMISSION")

            original_name = Path(str(payload.get("file_name") or "").strip()).name
            if not original_name:
                raise EngineError("文件名不能为空", 400, "MISSING_FILE_NAME")
            extension = Path(original_name).suffix.lower()
            allowed = {".docx", ".xlsx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".txt"}
            if extension not in allowed:
                raise EngineError("素材文件类型不支持；允许 Word、Excel、PPT、PDF、图片和 TXT", 400, "MATERIAL_FILE_TYPE_REJECTED")
            encoded = str(payload.get("data_base64") or "")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise EngineError("素材文件内容不是有效 Base64", 400, "BAD_MATERIAL_FILE_DATA") from exc
            if not content:
                raise EngineError("不能上传空文件", 400, "EMPTY_MATERIAL_FILE")
            if len(content) > 10 * 1024 * 1024:
                raise EngineError("MVP 单个素材文件不能超过 10 MB", 413, "MATERIAL_FILE_TOO_LARGE")

            file_id = self._new_id("matfile")
            stored_name = f"{file_id}{extension}"
            store_dir = self.db_path.parent / "object_store" / "materials"
            store_dir.mkdir(parents=True, exist_ok=True)
            storage_path = (store_dir / stored_name).resolve()
            if store_dir.resolve() not in storage_path.parents:
                raise EngineError("素材存储路径非法", 400, "BAD_MATERIAL_STORAGE_PATH")
            storage_path.write_bytes(content)
            checksum = hashlib.sha256(content).hexdigest()
            version_no = int(conn.execute(
                "SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version FROM material_files WHERE asset_id=?",
                (asset_id,),
            ).fetchone()["next_version"])
            now = self._now()
            object_uri = f"local-object://materials/{stored_name}"
            conn.execute(
                """
                INSERT INTO material_files(file_id, asset_id, original_name, stored_name, content_type,
                    size_bytes, checksum_sha256, object_uri, version_no, uploaded_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id, asset_id, original_name, stored_name,
                    str(payload.get("content_type") or "application/octet-stream"), len(content),
                    checksum, object_uri, version_no, actor.user_id, now,
                ),
            )
            self._snapshot(conn, asset_id, actor.user_id, f"上传素材文件 v{version_no}：{original_name}", bump=True)
            return {
                "file_id": file_id, "asset_id": asset_id, "original_name": original_name,
                "content_type": str(payload.get("content_type") or "application/octet-stream"),
                "size_bytes": len(content), "checksum_sha256": checksum,
                "object_uri": object_uri, "version_no": version_no,
                "uploaded_by": actor.user_id, "created_at": now,
            }

        return self._run(actor_id, "upload_material_file", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def material_file_for_download(self, actor_id: str, file_id: str) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            existing = conn.execute("SELECT asset_id FROM material_files WHERE file_id=?", (file_id,)).fetchone()
        asset_id = existing["asset_id"] if existing else None

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            row = self._material_file_row(conn, file_id)
            asset = self._asset_row(conn, row["asset_id"])
            if not self._discoverable(conn, actor, asset) or not self._data_readable(conn, actor, asset):
                raise EngineError("当前真人无权下载该素材文件", 403, "NO_MATERIAL_DOWNLOAD_PERMISSION")
            storage_path = (self.db_path.parent / "object_store" / "materials" / row["stored_name"]).resolve()
            store_dir = (self.db_path.parent / "object_store" / "materials").resolve()
            if store_dir not in storage_path.parents or not storage_path.is_file():
                raise EngineError("素材原件在对象存储中不存在", 404, "MATERIAL_OBJECT_MISSING")
            item = dict(row)
            item["storage_path"] = str(storage_path)
            return item

        return self._run(actor_id, "download_material_file", work, asset_id=asset_id)

    def _assert_skill_ready(self, conn: sqlite3.Connection, asset: sqlite3.Row) -> dict[str, Any]:
        config = self._decode(asset["config_json"])
        tool_id = str(config.get("tool_id") or "")
        version = str(config.get("tool_version") or "")
        if not tool_id or not version:
            raise EngineError(
                "技能只有文字说明，尚未绑定固定工具和版本，不能启用或发布",
                409,
                "SKILL_TOOL_NOT_BOUND",
            )
        row = conn.execute(
            "SELECT * FROM tool_registry WHERE tool_id=? AND version=? AND enabled=1",
            (tool_id, version),
        ).fetchone()
        if not row:
            raise EngineError("技能绑定的固定工具不存在、已停用或版本不匹配", 409, "SKILL_TOOL_UNAVAILABLE")
        if config.get("validation_status") != "passed" or config.get("tool_checksum") != row["checksum"]:
            raise EngineError("技能尚未通过当前工具版本的测试验证，不能启用或发布", 409, "SKILL_NOT_VALIDATED")
        evaluations = list(conn.execute(
            """
            SELECT e.* FROM skill_model_evaluations e
            JOIN (
                SELECT model_role, MAX(evaluated_at) AS latest_at
                FROM skill_model_evaluations WHERE asset_id=? GROUP BY model_role
            ) latest ON latest.model_role=e.model_role AND latest.latest_at=e.evaluated_at
            WHERE e.asset_id=?
            """,
            (asset["asset_id"], asset["asset_id"]),
        ))
        by_role = {item["model_role"]: item for item in evaluations}
        if set(by_role) != {"primary", "backup"}:
            raise EngineError("技能尚未完整登记主力模型与备用模型评测", 409, "SKILL_MODEL_EVALUATIONS_REQUIRED")
        if any(item["conclusion"] != "passed" for item in by_role.values()):
            raise EngineError("主备模型评测未通过", 409, "SKILL_MODEL_EVALUATION_FAILED")
        return config

    @staticmethod
    def _dependency_scope_compatible(asset: sqlite3.Row, dependency: sqlite3.Row) -> bool:
        if asset["scope"] == "personal":
            return (
                (dependency["scope"] == "personal" and dependency["owner_real_id"] == asset["owner_real_id"])
                or (dependency["scope"] == "department" and dependency["owner_department"] == asset["owner_department"])
                or (dependency["scope"] == "company" and dependency["owner_company"] == asset["owner_company"])
            )
        if asset["scope"] == "department":
            return (
                (dependency["scope"] == "department" and dependency["owner_department"] == asset["owner_department"])
                or (dependency["scope"] == "company" and dependency["owner_company"] == asset["owner_company"])
            )
        if asset["scope"] == "company":
            return dependency["scope"] == "company" and dependency["owner_company"] == asset["owner_company"]
        return False

    def _assert_agent_ready(self, conn: sqlite3.Connection, asset: sqlite3.Row) -> dict[str, Any]:
        config = self._decode(asset["config_json"])
        skill_ids = list(config.get("skill_ids") or [])
        if not skill_ids:
            raise EngineError("Agent 尚未关联任何可执行技能，不能启用或发布", 409, "AGENT_SKILL_REQUIRED")
        entry_skill_id = str(config.get("entry_skill_id") or skill_ids[0])
        if entry_skill_id not in {str(item) for item in skill_ids}:
            raise EngineError("Agent 入口Skill不在可用Skill清单中", 409, "AGENT_ENTRY_SKILL_INVALID")
        for skill_id in skill_ids:
            skill = self._asset_row(conn, str(skill_id))
            if skill["asset_type"] != "skill" or skill["status"] not in {"personal_active", "published"}:
                raise EngineError("Agent 依赖的技能未启用或未发布", 409, "AGENT_SKILL_INACTIVE")
            if not self._dependency_scope_compatible(asset, skill):
                raise EngineError("Agent 与依赖技能的发布范围不兼容，目标用户将无法调用", 409, "AGENT_SKILL_SCOPE_MISMATCH")
            self._assert_skill_ready(conn, skill)
        for key, expected_type, label in (
            ("knowledge_base_ids", "knowledge_base", "知识库"),
        ):
            for dependency_id in list(config.get(key) or []):
                dependency = self._asset_row(conn, str(dependency_id))
                if dependency["asset_type"] != expected_type:
                    raise EngineError(f"Agent 关联的{label}类型错误", 409, "AGENT_DEPENDENCY_TYPE_MISMATCH")
                if dependency["status"] not in {"personal_active", "published"}:
                    raise EngineError(f"Agent 关联的{label}尚未启用或发布", 409, "AGENT_DEPENDENCY_INACTIVE")
                if not self._dependency_scope_compatible(asset, dependency):
                    raise EngineError(f"Agent 与关联{label}的范围不兼容", 409, "AGENT_DEPENDENCY_SCOPE_MISMATCH")
                if expected_type == "knowledge_base":
                    self._assert_knowledge_base_ready(conn, dependency)
        return config

    def _assert_knowledge_base_ready(self, conn: sqlite3.Connection, asset: sqlite3.Row) -> None:
        binding = self._kb_instance_for_asset(conn, asset["asset_id"])
        if not binding or binding["status"] != "ready":
            raise EngineError("知识库尚未获得 L1 1.13 实例回执，不能启用、发布或被 Agent 绑定", 409, "L1_KB_NOT_READY")
        indexed = conn.execute(
            "SELECT 1 FROM knowledge_source_indexes WHERE asset_id=? AND status='indexed' LIMIT 1",
            (asset["asset_id"],),
        ).fetchone()
        if not indexed:
            raise EngineError("知识库尚无完成索引的知识源，不能启用、发布或被 Agent 绑定", 409, "KB_SOURCE_NOT_INDEXED")

    def _assert_function_ready(self, conn: sqlite3.Connection, asset: sqlite3.Row) -> None:
        if asset["asset_type"] == "skill":
            self._assert_skill_ready(conn, asset)
        elif asset["asset_type"] == "agent":
            self._assert_agent_ready(conn, asset)
        elif asset["asset_type"] == "knowledge_base":
            self._assert_knowledge_base_ready(conn, asset)

    def validate_skill(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            self._assert_mutable_state(asset)
            if asset["asset_type"] != "skill":
                raise EngineError("只有技能资产需要执行工具绑定验证", 400, "VALIDATION_REQUIRES_SKILL")
            if asset["status"] != "draft" or not self._capabilities(conn, actor, asset)["modify"]:
                raise EngineError("只有草稿维护人可验证技能", 403, "NO_SKILL_VALIDATION_PERMISSION")
            config = self._decode(asset["config_json"])
            tool_id = str(config.get("tool_id") or "")
            version = str(config.get("tool_version") or "")
            definition = TOOL_DEFINITIONS.get((tool_id, version))
            tool_row = conn.execute(
                "SELECT * FROM tool_registry WHERE tool_id=? AND version=? AND enabled=1",
                (tool_id, version),
            ).fetchone()
            if not definition or not tool_row:
                raise EngineError("请选择已登记的固定工具及版本，不能使用自由文本工具引用", 409, "SKILL_TOOL_UNAVAILABLE")

            results = []
            all_passed = True
            for case in definition["test_cases"]:
                actual = execute_fixed_tool(tool_id, version, case["input"])
                passed = all(actual.get(key) == value for key, value in case["expected"].items())
                all_passed = all_passed and passed
                validation_id = self._new_id("val")
                conn.execute(
                    """
                    INSERT INTO skill_validations(validation_id, asset_id, tool_id, tool_version,
                        test_case_name, input_json, expected_json, actual_json, passed, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        validation_id, asset_id, tool_id, version, case["name"],
                        self._json(case["input"]), self._json(case["expected"]), self._json(actual),
                        1 if passed else 0, actor.user_id, self._now(),
                    ),
                )
                results.append({"validation_id": validation_id, "name": case["name"], "passed": passed, "actual": actual})

            config.update(
                {
                    "validation_status": "passed" if all_passed else "failed",
                    "implementation_status": "validated" if all_passed else "validation_failed",
                    "lifecycle_stage": "validation_passed" if all_passed else "validation_failed",
                    "validated_at": self._now(),
                    "tool_checksum": tool_row["checksum"],
                    "input_schema": self._decode(tool_row["input_schema_json"]),
                    "output_schema": self._decode(tool_row["output_schema_json"]),
                }
            )
            conn.execute(
                "UPDATE assets SET config_json=?, updated_at=? WHERE asset_id=?",
                (self._json(config), self._now(), asset_id),
            )
            self._snapshot(conn, asset_id, actor.user_id, "固定工具测试通过" if all_passed else "固定工具测试失败", bump=True)
            if not all_passed:
                raise EngineError("技能固定测试未通过", 409, "SKILL_VALIDATION_FAILED")
            return {
                "asset_id": asset_id,
                "status": "passed",
                "tool_id": tool_id,
                "tool_version": version,
                "tool_checksum": tool_row["checksum"],
                "results": results,
            }

        return self._run(actor_id, "validate_skill", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def _execution_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["input"] = self._decode(item.pop("input_json", "{}"))
        item["output"] = self._decode(item.pop("output_json", "{}"))
        item["requires_human_review"] = bool(item["requires_human_review"])
        return item

    def _execute_skill_in_conn(
        self, conn: sqlite3.Connection, actor: Actor, skill: sqlite3.Row,
        inputs: dict[str, Any], *, agent_asset_id: str | None = None, trace_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._resource_callable(actor, skill):
            raise EngineError("当前真人无权调用该技能资源", 403, "NO_SKILL_CALL_PERMISSION")
        # 本引擎只校验技能资源调用。业务数据若来自数据操作引擎，必须由
        # 数据操作引擎再次调用权限模块判定，不能复用本资产的可用结论。
        config = self._assert_skill_ready(conn, skill)
        try:
            output = execute_fixed_tool(config["tool_id"], config["tool_version"], inputs)
        except (ValueError, KeyError) as exc:
            raise EngineError(str(exc), 400, "BAD_SKILL_INPUT") from exc
        execution_id = self._new_id("exec")
        trace_id = trace_id or self._new_id("trace")
        needs_review = bool(output.get("requires_human_review"))
        conn.execute(
            """
            INSERT INTO executions(execution_id, trace_id, actor_id, agent_asset_id, skill_asset_id,
                tool_id, tool_version, input_json, output_json, status, requires_human_review,
                confirmation_status, confirmed_by, created_at, confirmed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'succeeded', ?, ?, NULL, ?, NULL)
            """,
            (
                execution_id, trace_id, actor.user_id, agent_asset_id, skill["asset_id"],
                config["tool_id"], config["tool_version"], self._json(inputs), self._json(output),
                1 if needs_review else 0, "pending" if needs_review else "not_required", self._now(),
            ),
        )
        result = self._execution_dict(conn.execute("SELECT * FROM executions WHERE execution_id=?", (execution_id,)).fetchone())
        result["route"] = [
            "L4 业务输入",
            "L2 层接口 / 当前真人判定",
            f"Agent {agent_asset_id}" if agent_asset_id else "技能直接调用",
            f"技能 {skill['asset_id']}",
            f"固定工具 {config['tool_id']}@{config['tool_version']}",
            "标准结果 / 真人确认",
        ]
        return result

    def execute_skill(self, actor_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            skill = self._asset_row(conn, asset_id)
            if skill["asset_type"] != "skill":
                raise EngineError("目标资产不是技能", 400, "EXECUTION_REQUIRES_SKILL")
            return self._execute_skill_in_conn(conn, actor, skill, dict(payload.get("input") or {}))
        return self._run(actor_id, "execute_skill", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def execute_agent(self, actor_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            agent = self._asset_row(conn, asset_id)
            if agent["asset_type"] != "agent":
                raise EngineError("目标资产不是 Agent", 400, "EXECUTION_REQUIRES_AGENT")
            if not self._resource_callable(actor, agent):
                raise EngineError("当前真人无权调用该 Agent", 403, "NO_AGENT_CALL_PERMISSION")
            config = self._assert_agent_ready(conn, agent)
            entry_skill_id = str(config.get("entry_skill_id") or config["skill_ids"][0])
            skill = self._asset_row(conn, entry_skill_id)
            return self._execute_skill_in_conn(
                conn, actor, skill, dict(payload.get("input") or {}), agent_asset_id=asset_id,
            )
        return self._run(actor_id, "execute_agent", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def execute_l4_capability(self, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """用一个真实请求串起 L4、层接口、功能登记、Agent/Skill和固定工具。"""
        request_id = str(payload.get("request_id") or self._new_id("l4exec"))
        trace_id = str(payload.get("trace_id") or self._new_id("trace"))
        target_asset_id = str(payload.get("target_asset_id") or "").strip()

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            if str(payload.get("source_layer") or "").upper() != "L4":
                raise EngineError("能力执行请求只能由 L4 发起", 403, "SOURCE_LAYER_NOT_ALLOWED")
            if not target_asset_id:
                raise EngineError("L4 请求缺少目标功能资产", 400, "MISSING_TARGET_ASSET")
            target = self._asset_row(conn, target_asset_id)
            if target["asset_type"] not in FUNCTION_TYPES:
                raise EngineError("L4 目标必须是已登记 Agent 或 Skill", 400, "TARGET_NOT_FUNCTION")
            registry = conn.execute(
                "SELECT * FROM function_registry WHERE asset_id=? AND sync_status='synced'",
                (target_asset_id,),
            ).fetchone()
            if not registry:
                raise EngineError("目标功能未同步到功能登记库", 409, "FUNCTION_NOT_REGISTERED")

            inputs = dict(payload.get("input") or {})
            if target["asset_type"] == "agent":
                if not self._resource_callable(actor, target):
                    raise EngineError("当前真人无权调用该 Agent", 403, "NO_AGENT_CALL_PERMISSION")
                config = self._assert_agent_ready(conn, target)
                entry_skill_id = str(config.get("entry_skill_id") or config["skill_ids"][0])
                skill = self._asset_row(conn, entry_skill_id)
                execution = self._execute_skill_in_conn(
                    conn, actor, skill, inputs, agent_asset_id=target_asset_id, trace_id=trace_id,
                )
            else:
                execution = self._execute_skill_in_conn(conn, actor, target, inputs, trace_id=trace_id)

            route = [
                {"seq": 1, "layer": "L4", "component": "业务操作界面", "result": "发起格式化能力请求"},
                {"seq": 2, "layer": "L2接口", "component": "请求接收端", "result": "确认L4来源并生成追踪编号"},
                {"seq": 3, "layer": "L1", "component": "1.8账号网关 + 1.1权限管理", "result": f"当前真人 {actor.name} 判定通过"},
                {"seq": 4, "layer": "L2", "component": "功能登记库", "result": f"流程执行适配 Mock 按登记定位 {registry['function_id']}"},
                {"seq": 5, "layer": "L2", "component": "数字资产引擎", "result": f"返回 {target['asset_type']} 登记与 implementation_ref"},
                {"seq": 6, "layer": "下游执行适配 Mock", "component": "固定工具适配器", "result": f"{execution['tool_id']}@{execution['tool_version']} 在本地受控执行完成"},
                {"seq": 7, "layer": "L2接口", "component": "标准回复", "result": "结果回传L4；异常时等待真人确认"},
            ]
            decisions = {
                "sourceLayer": {"allowed": True, "reason": "请求来源为L4"},
                "identity": {"allowed": True, "reason": f"1.8确认当前真人 {actor.user_id}"},
                "resourceCallable": {"allowed": True, "reason": "资源范围与状态允许调用"},
                "businessDataBoundary": {"allowed": True, "reason": "本请求未读取业务数据；若需取数必须另交数据操作引擎判权"},
                "functionRegistered": {"allowed": True, "reason": registry["function_id"]},
            }
            standard_response = {
                "type": "immediate", "code": "EXECUTION_SUCCEEDED",
                "message": "固定工具已在本地受控执行；跨引擎执行链当前为联调 Mock，不等同于数字资产引擎执行了业务任务",
                "trace_id": trace_id,
                "execution_id": execution["execution_id"],
                "confirmation_status": execution["confirmation_status"],
            }
            now = self._now()
            conn.execute(
                """
                INSERT INTO l4_requests(request_id, trace_id, actor_id, scenario_code, request_mode,
                    request_text, source_layer, service_code, target_engine, asset_id,
                    response_type, decision_code, decision_reason, route_json, decisions_json,
                    response_json, created_at)
                VALUES (?, ?, ?, 'execute_registered_capability', 'formatted', ?, 'L4', ?,
                    'execution_adapter_mock', ?, 'immediate', 'EXECUTION_SUCCEEDED', ?, ?, ?, ?, ?)
                """,
                (
                    request_id, trace_id, actor.user_id,
                    str(payload.get("request_text") or "执行已登记数字资产能力"),
                    str(payload.get("service_code") or registry["function_id"]), target_asset_id,
                    "资源、数据和固定工具版本均校验通过", self._json(route),
                    self._json(decisions), self._json(standard_response), now,
                ),
            )
            execution["request_id"] = request_id
            execution["route"] = [step["component"] for step in route]
            execution["l4_route"] = route
            execution["decisions"] = decisions
            execution["standard_response"] = standard_response
            return execution

        return self._run(
            actor_id, "execute_l4_capability", work, asset_id=target_asset_id or None,
            request_id=request_id,
        )

    def confirm_execution(self, actor_id: str, execution_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}

        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            row = conn.execute("SELECT * FROM executions WHERE execution_id=?", (execution_id,)).fetchone()
            if not row:
                raise EngineError("执行记录不存在", 404, "EXECUTION_NOT_FOUND")
            if row["actor_id"] != actor.user_id:
                raise EngineError("只有本次执行真人可确认结果", 403, "NO_EXECUTION_CONFIRM_PERMISSION")
            if row["confirmation_status"] != "pending":
                raise EngineError("该结果不需要确认或已经确认", 409, "EXECUTION_NOT_CONFIRMABLE")
            conn.execute(
                "UPDATE executions SET confirmation_status='confirmed', confirmed_by=?, confirmed_at=? WHERE execution_id=?",
                (actor.user_id, self._now(), execution_id),
            )
            return self._execution_dict(conn.execute("SELECT * FROM executions WHERE execution_id=?", (execution_id,)).fetchone())

        return self._run(actor_id, "confirm_execution", work, request_id=payload.get("request_id"))

    def _upsert_registry(self, conn: sqlite3.Connection, asset: dict[str, Any]) -> None:
        if asset["asset_type"] not in FUNCTION_TYPES:
            return
        conn.execute(
            """
            INSERT INTO function_registry(function_id, asset_id, function_name, asset_type, scope,
                sync_status, examples_json, synced_at)
            VALUES (?, ?, ?, ?, ?, 'synced', ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET function_name=excluded.function_name,
                asset_type=excluded.asset_type, scope=excluded.scope,
                sync_status='synced', examples_json=excluded.examples_json, synced_at=excluded.synced_at
            """,
            (
                f"fn_{asset['asset_id']}", asset["asset_id"], asset["asset_name"],
                asset["asset_type"], asset["scope"],
                self._json([f"调用{asset['asset_name']}"]), self._now(),
            ),
        )

    def sync_registry(self, actor_id: str, asset_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            if asset["asset_type"] not in FUNCTION_TYPES:
                raise EngineError("只有 Agent 和技能进入功能登记库", 400, "NOT_FUNCTION_ASSET")
            if asset["status"] not in {"personal_active", "published"}:
                raise EngineError("只有个人启用或已发布功能可登记", 409, "FUNCTION_NOT_ACTIVE")
            if actor.user_id not in {asset["owner_real_id"], asset["maintainer_id"]}:
                raise EngineError("仅资产责任人或维护人可同步功能登记", 403, "NO_SYNC_PERMISSION")
            self._assert_function_ready(conn, asset)
            item = self._asset_dict(asset)
            self._upsert_registry(conn, item)
            return {"asset_id": asset_id, "sync_status": "synced"}
        return self._run(actor_id, "sync_registry", work, asset_id=asset_id, request_id=payload.get("request_id"))

    def invoke_l4_scenario(self, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """处理一个可审计的 L4 场景请求，但不冒充下游业务执行引擎。

        这里验证的是：L4 来源、真人、服务目录和资产登记治理能否形成
        一条可追踪链路。真实文档解析、问答、内容生成或计算只在回复中标明
        下游去向，本方法不伪造其业务结果；业务数据由数据操作引擎另行判权。
        """
        request_id = str(payload.get("request_id") or self._new_id("l4req"))
        trace_id = str(payload.get("trace_id") or self._new_id("trace"))
        source_layer = str(payload.get("source_layer") or "L4").upper()
        scenario_code = str(payload.get("scenario_code") or "").strip()
        request_mode = str(payload.get("request_mode") or "").strip()
        before = None
        try:
            with closing(self.connect()) as conn:
                actor = self._actor_from_conn(conn, actor_id)
                self._action_enabled(conn, "invoke_l4_scenario")
                if source_layer != "L4":
                    raise EngineError("数字资产引擎的场景入口只接受 L4 层请求", 403, "SOURCE_LAYER_NOT_ALLOWED")
                scenario = L4_SCENARIOS.get(scenario_code)
                if not scenario:
                    raise EngineError("未登记的 L4 场景或服务代码，默认拒绝", 404, "L4_SCENARIO_NOT_REGISTERED")
                request_mode = request_mode or scenario["request_mode"]
                if request_mode not in {"natural_language", "formatted"}:
                    raise EngineError("L4 请求类型只能是自然语言或格式化请求", 400, "BAD_L4_REQUEST_MODE")
                request_text = str(payload.get("request_text") or scenario["default_request"]).strip()
                if not request_text:
                    raise EngineError("L4 请求内容不能为空", 400, "MISSING_L4_REQUEST")

                # “能力缺失”是一个受控的跨引擎联调场景：此时尚未存在可定位
                # 的 Skill，不能虚构资产、更不能提前读取销售/回款等业务数据。
                # 规则计算引擎只返回前置查询需求；流程执行引擎才会分别派给
                # 数据操作引擎和本引擎。本引擎在此只负责登记册查询结果。
                is_capability_gap = scenario["operation"] == "capability_gap"
                asset = None
                capabilities: dict[str, bool] = {}
                config: dict[str, Any] = {}
                if not is_capability_gap:
                    asset = self._asset_row(conn, scenario["target_asset_id"])
                    capabilities = self._capabilities(conn, actor, asset)
                    config = self._decode(asset["config_json"])
                registry = None
                if scenario["operation"] == "resolve_function":
                    registry = conn.execute(
                        "SELECT * FROM function_registry WHERE asset_id=? AND sync_status='synced'",
                        (asset["asset_id"],),
                    ).fetchone()
                service_matched = is_capability_gap or scenario["operation"] == "build_asset" or registry is not None
                if is_capability_gap:
                    resource_allowed = True
                    resource_reason = "这是能力缺失确认场景；尚未读取或暴露任何业务数据与既有资产内容"
                elif scenario["operation"] == "build_asset":
                    resource_allowed = bool(capabilities["modify"] or capabilities["addSource"])
                    resource_reason = (
                        "当前真人是目标知识库草稿的维护人，可继续登记知识源"
                        if resource_allowed else "当前真人不是目标知识库草稿的责任人或维护人"
                    )
                else:
                    resource_allowed = bool(self._resource_callable(actor, asset))
                    resource_reason = (
                        "资源层级允许当前真人调用"
                        if resource_allowed else "资源层级或发布状态不允许当前真人调用"
                    )
                if not service_matched:
                    response_type = "rejected"
                    decision_code = "SERVICE_NOT_REGISTERED"
                    decision_reason = "服务目录未找到已同步的功能登记"
                elif not resource_allowed:
                    response_type = "rejected"
                    decision_code = "RESOURCE_PERMISSION_DENIED"
                    decision_reason = resource_reason
                elif scenario["operation"] == "build_asset":
                    response_type = "accepted"
                    decision_code = "ACCEPTED_FOR_PROCESSING"
                    decision_reason = "建库请求已受理，等待知识源登记与外部解析状态回调"
                elif is_capability_gap:
                    response_type = "accepted"
                    decision_code = "CAPABILITY_GAP_CONFIRM_REQUIRED"
                    decision_reason = "规则与参数的存在性需由数据操作引擎查询；当前数字资产登记册未定位到已验证、可正式调用的销售提成计算 Skill"
                else:
                    response_type = "immediate"
                    decision_code = "ASSET_RESOLVED"
                    decision_reason = "已定位可调用资产，可将配置与依赖转交下游执行引擎"

                decisions = {
                    "sourceAllowed": {"allowed": True, "reason": "L2 接口只接受 L4 白名单来源"},
                    "actorResolved": {"allowed": True, "reason": f"已定位当前真人 {actor.name} / {actor.position_code}"},
                    "serviceMatched": {"allowed": service_matched, "reason": scenario["service_code"]},
                    "resourceCallable": {"allowed": resource_allowed, "reason": resource_reason},
                    "businessDataBoundary": {
                        "allowed": True,
                        "reason": "能力缺失阶段不读取销售额、回款额等业务数据；仅在真人确认受控试算后，由数据操作引擎另行判权取数"
                        if is_capability_gap else "数字资产请求不携带业务数据权限；取数须转数据操作引擎另行判定",
                    },
                }
                route = [
                    {
                        "seq": 1, "layer": "L4", "component": scenario["interface"],
                        "action": "发起业务请求", "result": f"携带真人 {actor.user_id} 与追踪编号 {trace_id}",
                    },
                    {
                        "seq": 2, "layer": "L2 层接口", "component": "接口控制模块",
                        "action": "校验来源白名单、真人身份并留痕", "result": "L4 来源通过",
                    },
                    {
                        "seq": 3, "layer": "L2", 
                        "component": "意图分析引擎（Mock）" if request_mode == "natural_language" else "服务目录直接分派",
                        "action": "识别场景并匹配服务目录" if request_mode == "natural_language" else "按格式化服务代码分派",
                        "result": scenario["service_code"] if service_matched else "未匹配",
                    },
                ]
                if is_capability_gap:
                    route.extend([
                        {
                            "seq": 4, "layer": "L2", "component": "流程执行引擎",
                            "action": "派发 rule.evaluate", "result": "规则计算引擎仅返回前置查询需求，不自行取数",
                        },
                        {
                            "seq": 5, "layer": "L2", "component": "规则计算引擎",
                            "action": "返回规则、参数、业务数据与执行实现的查询需求", "result": "不直接查询数据库，也不直接调用数字资产引擎",
                        },
                        {
                            "seq": 6, "layer": "L2", "component": "流程执行引擎",
                            "action": "分别派发 data.query 与 asset.query", "result": "确认前只查询规则/参数存在性与 Skill 登记状态",
                        },
                        {
                            "seq": 7, "layer": "L2", "component": "数字资产引擎",
                            "action": "查询三类资产登记册", "result": "未找到已验证 implementation_ref 的销售提成计算 Skill",
                        },
                    ])
                else:
                    route.extend([
                        {
                            "seq": 4, "layer": "L2", "component": "流程执行引擎",
                            "action": "按服务目录组织任务并经本层对内通道派发", "result": "派发数字资产任务",
                        },
                        {
                            "seq": 5, "layer": "L2", "component": "数字资产引擎",
                            "action": "定位登记资产并接收外部权限模块判定", "result": decision_code,
                        },
                    ])
                if response_type != "rejected":
                    route.append({
                        "seq": len(route) + 1,
                        "layer": "L2 → L1" if scenario["operation"] == "build_asset" else "L2 → L4" if is_capability_gap else "L2 执行方",
                        "component": scenario["downstream"],
                        "action": "登记对象引用和处理状态" if scenario["operation"] == "build_asset" else "返回能力缺失与真人确认卡" if is_capability_gap else "接收资产配置与依赖",
                        "result": (
                            "仅登记编排状态；真实解析完成后回调"
                            if scenario["operation"] == "build_asset"
                            else "未读取业务数据；确认后才可创建 Skill 研发登记并进行候选试算"
                            if is_capability_gap
                            else "本 MVP 不执行真实问答、生成或计算"
                        ),
                    })
                route.append({
                    "seq": len(route) + 1, "layer": "L4", "component": "结果/通知接收",
                    "action": "接收标准回复", "result": response_type,
                })

                if response_type == "accepted":
                    response_message = (
                        "已定位《销售提成制度》和参数表（本场景前提），但未找到已验证、可正式调用的销售提成计算 Skill。"
                        "尚未读取销售额或回款额。请由真人确认是否发起 Skill 研发，并在后续进行受控候选试算。"
                        if is_capability_gap else
                        "请求已受理：目标知识库草稿已定位。请继续登记知识源；解析由文档表格解析引擎承担，完成后回调处理状态。"
                    )
                elif response_type == "immediate":
                    response_message = "已返回资产登记与依赖：资源权限通过，可转交下游执行引擎；业务数据如需读取须由数据操作引擎另行判权。"
                else:
                    response_message = f"请求被拒绝：{decision_reason}"
                standard_response = {
                    "type": response_type,
                    "code": decision_code,
                    "message": response_message,
                    "callback_expected": response_type == "accepted",
                }

                expose_asset = resource_allowed and asset is not None
                resolved_asset = None
                if expose_asset:
                    resolved_asset = {
                        "asset_id": asset["asset_id"],
                        "asset_name": asset["asset_name"],
                        "asset_type": asset["asset_type"],
                        "scope": asset["scope"],
                        "status": asset["status"],
                        "current_version": asset["current_version"],
                    }
                    resolved_asset["execution_ref"] = (
                        f"{config.get('tool_id')}@{config.get('tool_version')}"
                        if asset["asset_type"] == "skill"
                        else config.get("skill_ids")
                    )
                    if registry:
                        resolved_asset["function_id"] = registry["function_id"]

                now = self._now()
                conn.execute(
                    """
                    INSERT INTO l4_requests(request_id, trace_id, actor_id, scenario_code, request_mode,
                        request_text, source_layer, service_code, target_engine, asset_id,
                        response_type, decision_code, decision_reason, route_json, decisions_json,
                        response_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'digital_asset_engine', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id, trace_id, actor.user_id, scenario_code, request_mode,
                        request_text, source_layer, scenario["service_code"], asset["asset_id"] if asset else None,
                        response_type, decision_code, decision_reason, self._json(route),
                        self._json(decisions), self._json(standard_response), now,
                    ),
                )
                audit_result = "DENY" if response_type == "rejected" else "ALLOW"
                audit_after = {
                    "request_id": request_id, "trace_id": trace_id,
                    "scenario_code": scenario_code, "response_type": response_type,
                    "decision_code": decision_code,
                }
                self._audit(
                    conn, actor.user_id, "invoke_l4_scenario", trace_id, audit_result,
                    asset["asset_id"] if asset else None, None, None, audit_after,
                    decision_reason if audit_result == "DENY" else None,
                )
                conn.commit()
                item = self._l4_request_dict(self._l4_request_row(conn, request_id))
                item["scenario"] = self._public_l4_scenarios()[list(L4_SCENARIOS).index(scenario_code)]
                item["resolved_asset"] = resolved_asset
                item["execution_boundary"] = "数字资产引擎只返回受治理的资产与调用边界，不执行真实解析、问答、内容生成或计算；真实业务执行由下游引擎承担"
                return item
        except EngineError as exc:
            self._write_deny(actor_id, "invoke_l4_scenario", trace_id, exc, None, None, before)
            raise

    def get_asset_for_actor(self, actor_id: str, asset_id: str, request_id: str | None = None) -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            asset = self._asset_row(conn, asset_id)
            if not self._discoverable(conn, actor, asset):
                raise EngineError("当前真人无权查看该资产，不能通过资产编号绕过权限", 403, "NO_READ_PERMISSION")
            return self._present_asset(conn, actor, asset)
        return self._run(actor_id, "read_asset", work, asset_id=asset_id, request_id=request_id)

    def _present_workflow(self, actor: Actor, row: sqlite3.Row) -> dict[str, Any]:
        item = self._workflow_dict(row)
        if actor.is_platform_operator:
            item["reason"] = None
            item["metadataOnly"] = True
        else:
            item["metadataOnly"] = False
        item["capabilities"] = self._workflow_capabilities(actor, row)
        return item

    def _build_state(self, conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
        asset_rows = list(conn.execute(
            "SELECT * FROM assets WHERE asset_type IN ('agent','skill','knowledge_base') ORDER BY updated_at DESC"
        ))
        visible_rows = [row for row in asset_rows if self._discoverable(conn, actor, row)]
        assets = [self._present_asset(conn, actor, row) for row in visible_rows]
        visible_ids = {row["asset_id"] for row in visible_rows}

        workflow_rows = list(conn.execute("SELECT * FROM workflows ORDER BY submitted_at DESC"))
        workflows = []
        for row in workflow_rows:
            if actor.is_platform_operator or actor.user_id in {row["submitter_id"], row["approver_id"]}:
                workflows.append(self._present_workflow(actor, row))

        sources = []
        by_id = {row["asset_id"]: row for row in visible_rows}
        for row in conn.execute("SELECT * FROM sources ORDER BY updated_at DESC"):
            asset = by_id.get(row["asset_id"])
            if not asset:
                continue
            if actor.is_platform_operator:
                item = dict(row)
                item["file_name"] = "受限文件"
                item["object_uri"] = None
                item["parse_result_json"] = "{}"
                item["metadataOnly"] = True
            elif self._data_readable(conn, actor, asset):
                item = dict(row)
                item["metadataOnly"] = False
            else:
                continue
            has_local_object = bool(item.get("stored_name"))
            item.pop("stored_name", None)
            item["parse_result"] = self._decode(item.pop("parse_result_json", "{}"))
            binding = self._kb_instance_for_asset(conn, row["asset_id"])
            index_row = self._source_index_for_source(conn, row["source_id"])
            item["metadata_status"] = "registered"
            if index_row:
                item["vector_status"] = index_row["status"]
                item["index_evidence"] = {
                    "index_id": index_row["index_id"],
                    "binding_id": index_row["binding_id"],
                    "chunk_count": index_row["chunk_count"],
                    "vector_count": index_row["vector_count"],
                    "index_version": index_row["index_version"],
                    "callback_mode": index_row["callback_mode"],
                    "updated_at": index_row["updated_at"],
                }
            elif row["parse_status"] == "success" and binding and binding["status"] == "ready":
                item["vector_status"] = "ready_to_index"
                item["index_evidence"] = None
            elif row["parse_status"] == "success":
                item["vector_status"] = "blocked_no_l1"
                item["index_evidence"] = None
            else:
                item["vector_status"] = "not_started"
                item["index_evidence"] = None
            item["capabilities"] = {
                "parse": (not actor.is_platform_operator and self._capabilities(conn, actor, asset)["addSource"]),
                "download": (not actor.is_platform_operator and has_local_object),
                "viewMetadata": True,
                "registerIndexResult": (
                    actor.is_platform_operator
                    and row["parse_status"] == "success"
                    and binding is not None
                    and binding["status"] == "ready"
                    and (index_row is None or index_row["status"] != "indexed")
                ),
            }
            sources.append(item)

        knowledge_base_instances = []
        for row in conn.execute("SELECT * FROM knowledge_base_instances ORDER BY requested_at DESC"):
            asset = by_id.get(row["asset_id"])
            if not asset:
                continue
            if not actor.is_platform_operator and not self._data_readable(conn, actor, asset):
                continue
            item = dict(row)
            item["metadataOnly"] = actor.is_platform_operator
            item["capabilities"] = {
                "registerInstance": actor.is_platform_operator and row["status"] == "requested",
            }
            knowledge_base_instances.append(item)

        attachments = []
        legacy_assets = {
            row["asset_id"]: row for row in conn.execute(
                "SELECT * FROM assets WHERE asset_type=?", (LEGACY_ATTACHMENT_TYPE,)
            )
        }
        for row in conn.execute("SELECT * FROM material_files ORDER BY created_at DESC"):
            asset = legacy_assets.get(row["asset_id"])
            if not asset:
                continue
            if actor.is_platform_operator:
                item = {
                    "file_id": row["file_id"], "asset_id": row["asset_id"],
                    "original_name": "受限素材文件", "content_type": row["content_type"],
                    "size_bytes": row["size_bytes"], "checksum_sha256": row["checksum_sha256"],
                    "version_no": row["version_no"], "uploaded_by": row["uploaded_by"],
                    "created_at": row["created_at"], "metadataOnly": True,
                    "capabilities": {"download": False},
                }
            elif actor.user_id in {asset["owner_real_id"], asset["maintainer_id"], row["uploaded_by"]}:
                item = dict(row)
                item.pop("stored_name", None)
                item["metadataOnly"] = False
                item["capabilities"] = {"download": True}
            else:
                continue
            item["attachment_kind"] = "legacy_output_template"
            item["legacy_asset_id"] = row["asset_id"]
            attachments.append(item)

        foundation_calls = []
        for row in conn.execute("SELECT * FROM foundation_calls ORDER BY created_at DESC LIMIT 100"):
            if row["actor_id"] == actor.user_id:
                foundation_calls.append(dict(row))
            elif actor.is_platform_operator:
                foundation_calls.append({
                    "call_id": row["call_id"], "request_id": row["request_id"],
                    "action": row["action"], "asset_id": row["asset_id"],
                    "adapter_mode": row["adapter_mode"], "created_at": row["created_at"],
                    "metadataOnly": True,
                })

        flow_tasks = []
        for row in conn.execute("SELECT * FROM flow_tasks ORDER BY created_at DESC LIMIT 50"):
            if row["actor_id"] == actor.user_id:
                item = dict(row)
                item["payload"] = self._decode(item.pop("payload_json", "{}"), {})
                item["response"] = self._decode(item.pop("response_json", "{}"), {})
                flow_tasks.append(item)
            elif actor.is_platform_operator:
                flow_tasks.append({
                    "task_id": row["task_id"], "workflow_instance_id": row["workflow_instance_id"],
                    "trace_id": row["trace_id"], "service_code": row["service_code"],
                    "target_engine": row["target_engine"], "status": row["status"],
                    "created_at": row["created_at"], "metadataOnly": True,
                })

        registry = []
        for row in conn.execute("SELECT * FROM function_registry ORDER BY synced_at DESC"):
            asset = by_id.get(row["asset_id"])
            if not asset:
                continue
            if not (actor.is_platform_operator or self._resource_callable(actor, asset) or actor.user_id in {asset["owner_real_id"], asset["maintainer_id"]}):
                continue
            item = dict(row)
            item["examples"] = [] if actor.is_platform_operator else self._decode(item.pop("examples_json", "[]"), [])
            if "examples_json" in item:
                item.pop("examples_json")
            item["metadataOnly"] = actor.is_platform_operator
            item["resourceCallable"] = self._resource_callable(actor, asset)
            registry.append(item)

        l4_requests = []
        for row in conn.execute("SELECT * FROM l4_requests ORDER BY created_at DESC LIMIT 50"):
            if actor.is_platform_operator:
                l4_requests.append(self._l4_request_dict(row, metadata_only=True))
            elif row["actor_id"] == actor.user_id:
                l4_requests.append(self._l4_request_dict(row, metadata_only=False))

        tools = []
        for row in conn.execute("SELECT * FROM tool_registry WHERE enabled=1 ORDER BY tool_name, version"):
            item = dict(row)
            item["input_schema"] = self._decode(item.pop("input_schema_json", "{}"))
            item["output_schema"] = self._decode(item.pop("output_schema_json", "{}"))
            item["rules"] = self._decode(item.pop("rules_json", "{}"))
            tools.append(item)

        development_requests = []
        for row in conn.execute("SELECT * FROM skill_development_requests ORDER BY submitted_at DESC"):
            asset = by_id.get(row["asset_id"])
            if not asset:
                continue
            if actor.is_platform_operator:
                item = self._development_request_dict(row, metadata_only=True)
            elif actor.user_id in {row["submitter_id"], asset["owner_real_id"], asset["maintainer_id"]}:
                item = self._development_request_dict(row, metadata_only=False)
            else:
                continue
            item["capabilities"] = {
                "registerCandidate": actor.is_platform_operator and row["status"] == "submitted",
                "bindCandidate": (
                    not actor.is_platform_operator
                    and actor.user_id == asset["maintainer_id"]
                    and row["status"] == "ready_to_bind"
                ),
            }
            development_requests.append(item)

        validations = []
        for row in conn.execute("SELECT * FROM skill_validations ORDER BY created_at DESC LIMIT 100"):
            if row["asset_id"] not in visible_ids:
                continue
            item = dict(row)
            item["input"] = self._decode(item.pop("input_json", "{}"))
            item["expected"] = self._decode(item.pop("expected_json", "{}"))
            item["actual"] = self._decode(item.pop("actual_json", "{}"))
            item["passed"] = bool(item["passed"])
            validations.append(item)

        executions = []
        for row in conn.execute("SELECT * FROM executions ORDER BY created_at DESC LIMIT 100"):
            if row["actor_id"] == actor.user_id:
                executions.append(self._execution_dict(row))
            elif actor.is_platform_operator:
                executions.append({
                    "execution_id": row["execution_id"], "trace_id": row["trace_id"],
                    "skill_asset_id": row["skill_asset_id"], "agent_asset_id": row["agent_asset_id"],
                    "tool_id": row["tool_id"], "tool_version": row["tool_version"],
                    "status": row["status"], "confirmation_status": row["confirmation_status"],
                    "created_at": row["created_at"], "metadataOnly": True,
                })

        versions = []
        for row in conn.execute("SELECT * FROM asset_versions ORDER BY created_at DESC"):
            asset = by_id.get(row["asset_id"])
            if not asset:
                continue
            if actor.is_platform_operator:
                versions.append({
                    "version_id": row["version_id"], "asset_id": row["asset_id"],
                    "version_no": row["version_no"], "change_summary": "受限变更",
                    "created_by": row["created_by"], "created_at": row["created_at"], "metadataOnly": True,
                })
            elif actor.user_id in {asset["creator_id"], asset["maintainer_id"]} or self._assigned_pending_workflow(conn, actor, asset["asset_id"]):
                item = dict(row)
                item["snapshot"] = self._decode(item.pop("snapshot_json"))
                item["metadataOnly"] = False
                versions.append(item)

        logs = []
        for row in conn.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200"):
            if actor.is_platform_operator:
                logs.append({
                    "log_id": row["log_id"], "request_id": row["request_id"], "actor_id": row["actor_id"],
                    "action": row["action"], "asset_id": row["asset_id"], "workflow_id": row["workflow_id"],
                    "decision_result": row["decision_result"], "deny_reason": None,
                    "created_at": row["created_at"], "metadataOnly": True,
                })
            elif row["actor_id"] == actor.user_id:
                item = dict(row)
                item["asset_before"] = self._decode(item["asset_before"]) if item["asset_before"] else None
                item["asset_after"] = self._decode(item["asset_after"]) if item["asset_after"] else None
                item["metadataOnly"] = False
                logs.append(item)

        actor_rows = list(conn.execute("SELECT * FROM users WHERE active=1 ORDER BY name"))
        actors = [
            {
                "userId": row["user_id"], "name": row["name"], "role": row["role"],
                "department": row["department"], "company": row["company"],
                "positionCode": row["position_code"], "isCurrent": row["user_id"] == actor.user_id,
            }
            for row in actor_rows
        ]
        current_actor = {
            "userId": actor.user_id, "name": actor.name, "role": actor.role,
            "department": actor.department, "company": actor.company,
            "positionCode": actor.position_code, "metadataOnly": actor.is_platform_operator,
            "allowedCreateScopes": [scope for scope in SCOPES if self._can_create_scope(actor, scope)],
        }
        return {
            "currentActor": current_actor,
            "actors": actors,
            "assets": assets,
            "workflows": workflows,
            "sources": sources,
            "knowledgeBaseInstances": knowledge_base_instances,
            "attachments": attachments,
            "foundationCalls": foundation_calls,
            "flowTasks": flow_tasks,
            "registry": registry,
            "l4Requests": l4_requests,
            "l4Scenarios": self._public_l4_scenarios(),
            "tools": tools,
            "developmentRequests": development_requests,
            "validations": validations,
            "executions": executions,
            # 兼容旧页面字段；两者来自同一 SQLite 查询结果，并非第二套状态。
            "function_registry": registry,
            "versions": versions,
            "logs": logs,
            "stats": {
                "visibleAssetCount": len(assets),
                "personalActiveCount": sum(a["status"] == "personal_active" for a in assets),
                "publishedCount": sum(a["status"] == "published" for a in assets),
                "pendingWorkflowCount": sum(w["status"] == "pending" for w in workflows),
                "l4RequestCount": len(l4_requests),
                "executionCount": len(executions),
                "denyCount": sum(l["decision_result"] == "DENY" for l in logs),
            },
            "scopePolicies": SCOPE_POLICIES,
            "labels": {
                "assetTypes": ASSET_TYPES, "scopes": SCOPES,
                "statuses": STATUS_LABELS, "workflows": WORKFLOW_LABELS,
            },
        }

    def state(self, actor_id: str | None = None) -> dict[str, Any]:
        actor_id = actor_id or self.DEFAULT_ACTOR
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            return self._build_state(conn, actor)
        return self._run(actor_id, "read_state", work)

    def reset_demo(self, actor_id: str = "engine_admin") -> dict[str, Any]:
        def work(conn: sqlite3.Connection, actor: Actor) -> dict[str, Any]:
            if not actor.is_platform_operator:
                raise EngineError("仅演示环境平台运维身份可重置演示数据", 403, "NO_RESET_PERMISSION")
            conn.executescript(
                """
                DELETE FROM function_registry;
                DELETE FROM flow_tasks;
                DELETE FROM foundation_calls;
                DELETE FROM skill_model_evaluations;
                DELETE FROM asset_tags;
                DELETE FROM executions;
                DELETE FROM skill_validations;
                DELETE FROM skill_development_requests;
                DELETE FROM knowledge_source_indexes;
                DELETE FROM knowledge_base_instances;
                DELETE FROM material_files;
                DELETE FROM sources;
                DELETE FROM workflows;
                DELETE FROM asset_versions;
                DELETE FROM assets;
                DELETE FROM l4_requests;
                DELETE FROM audit_log;
                """
            )
            self._seed_demo_data(conn)
            return {"reset": True}
        result = self._run(actor_id, "reset_demo", work)
        self._ensure_knowledge_base_demo_seed()
        self._ensure_executable_demo_seed()
        self._ensure_teacher_registry_evidence()
        return result


def demo_db_path() -> Path:
    """使用新库，避免旧 demo.db 的宽权限结构污染。"""
    override = os.environ.get("DA_ENGINE_DB_PATH")
    return Path(override).expanduser().resolve() if override else Path(__file__).resolve().parent / "demo_v2.db"


if __name__ == "__main__":
    engine = DigitalAssetEngine(demo_db_path())
    print(json.dumps(engine.state(), ensure_ascii=False, indent=2))
