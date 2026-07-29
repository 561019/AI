from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from nl_parser import NaturalLanguageParser
from storage_adapters import SQLiteDataModuleAdapter, SQLiteMemoryManagementAdapter


UTC = timezone.utc
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DIMENSION_COLUMNS = {
    "company_code": "company_code",
    "company_name": "company_name",
    "period": "period",
    "department": "department",
    "product": "product",
}


class EngineError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class AggregationEngine:
    """A deterministic local vertical slice of the L2 data aggregation engine.

    SQLite is deliberately used as a local adapter for the platform's L1 1.7 data
    module. The public entry point remains the L2 formatted-request interface.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_dir = self.db_path.parent / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.nl_parser = NaturalLanguageParser()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()
        self.data_module = SQLiteDataModuleAdapter(self.conn, self.db_path.parent / "datasets")
        self.memory_module = SQLiteMemoryManagementAdapter(self.conn)
        if self.conn.execute("SELECT COUNT(*) FROM metric_definitions").fetchone()[0] == 0:
            self.reset_demo()

    def close(self) -> None:
        self.conn.close()

    def _create_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS service_directory (
                    request_type TEXT PRIMARY KEY,
                    service_name TEXT NOT NULL,
                    engine_key TEXT NOT NULL,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_catalog (
                    action_id TEXT PRIMARY KEY,
                    action_name TEXT NOT NULL,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actors (
                    actor_id TEXT PRIMARY KEY,
                    actor_name TEXT NOT NULL,
                    position_name TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    allowed_companies_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metric_definitions (
                    metric_id TEXT PRIMARY KEY,
                    metric_name TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    scale INTEGER NOT NULL,
                    aggregation TEXT NOT NULL,
                    additive INTEGER NOT NULL,
                    allowed_dimensions_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    owner TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS code_mappings (
                    domain TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    source_code TEXT NOT NULL,
                    unified_code TEXT NOT NULL,
                    unified_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    PRIMARY KEY(domain, source_system, source_code)
                );
                CREATE TABLE IF NOT EXISTS fact_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_system TEXT NOT NULL,
                    source_record_id TEXT NOT NULL,
                    source_ref TEXT NOT NULL UNIQUE,
                    payload_hash TEXT NOT NULL,
                    metric_id TEXT NOT NULL,
                    company_code TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    period TEXT NOT NULL,
                    department TEXT NOT NULL,
                    product TEXT NOT NULL,
                    value_minor INTEGER NOT NULL,
                    unit TEXT NOT NULL,
                    state TEXT NOT NULL,
                    ingested_by TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    UNIQUE(source_system, source_record_id),
                    FOREIGN KEY(metric_id) REFERENCES metric_definitions(metric_id)
                );
                CREATE TABLE IF NOT EXISTS rejected_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_system TEXT,
                    source_record_id TEXT,
                    reason_code TEXT NOT NULL,
                    reason_message TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    rejected_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL UNIQUE,
                    actor_id TEXT,
                    request_type TEXT,
                    status TEXT NOT NULL,
                    reason_code TEXT,
                    result_hash TEXT,
                    request_json TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS aggregate_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    dimensions_json TEXT NOT NULL,
                    value_minor INTEGER NOT NULL,
                    value_display TEXT NOT NULL,
                    source_count INTEGER NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES tasks(trace_id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    component TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_id TEXT,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS l4_interpretations (
                    parse_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason_code TEXT,
                    parsed_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    executed_trace_id TEXT
                );
                CREATE TABLE IF NOT EXISTS data_operation_results (
                    result_ref TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL UNIQUE,
                    actor_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    storage_class TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES tasks(trace_id)
                );
                CREATE TABLE IF NOT EXISTS flow_callbacks (
                    callback_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    delivery_attempts INTEGER NOT NULL DEFAULT 0,
                    acknowledged_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES tasks(trace_id)
                );
                CREATE TABLE IF NOT EXISTS data_assets (
                    data_ref TEXT PRIMARY KEY,
                    business_type TEXT NOT NULL,
                    data_labels_json TEXT NOT NULL,
                    company_scope_json TEXT NOT NULL,
                    storage_class TEXT NOT NULL,
                    source_ref TEXT,
                    knowledge_binding_json TEXT NOT NULL DEFAULT '{}',
                    business_context_json TEXT NOT NULL DEFAULT '{}',
                    owner_actor_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    created_trace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS l1_data_locations (
                    data_ref TEXT PRIMARY KEY,
                    storage_uri TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    physical_state TEXT NOT NULL,
                    stored_at TEXT NOT NULL,
                    FOREIGN KEY(data_ref) REFERENCES data_assets(data_ref)
                );
                CREATE TABLE IF NOT EXISTS data_asset_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_ref TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(data_ref) REFERENCES data_assets(data_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_fact_metric_period
                    ON fact_records(metric_id, period, company_code);
                CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_events(trace_id, id);
                CREATE INDEX IF NOT EXISTS idx_asset_events_ref ON data_asset_events(data_ref, id);
                """
            )
            columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(data_assets)")}
            if "knowledge_binding_json" not in columns:
                self.conn.execute(
                    "ALTER TABLE data_assets ADD COLUMN knowledge_binding_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "business_context_json" not in columns:
                self.conn.execute(
                    "ALTER TABLE data_assets ADD COLUMN business_context_json TEXT NOT NULL DEFAULT '{}'"
                )

    def reset_demo(self) -> dict[str, Any]:
        """Reset only this demo database and load deterministic synthetic data."""
        with self._lock, self.conn:
            for table in (
                "memories",
                "memory_candidates",
                "datasets",
                "data_operation_results",
                "flow_callbacks",
                "data_asset_events",
                "l1_data_object_versions",
                "l1_data_locations",
                "data_assets",
                "l4_interpretations",
                "aggregate_rows",
                "audit_events",
                "tasks",
                "rejected_records",
                "fact_records",
                "code_mappings",
                "metric_definitions",
                "actors",
                "action_catalog",
                "service_directory",
            ):
                self.conn.execute(f"DELETE FROM {table}")
            self.data_module.clear_artifacts()
            self.data_module.clear_business_objects()

            self.conn.execute(
                "INSERT INTO service_directory VALUES (?,?,?,?)",
                ("data.aggregate", "数据归集聚合（历史兼容）", "data_aggregation_engine", "legacy"),
            )
            self.conn.executemany(
                "INSERT INTO action_catalog VALUES (?,?,?)",
                [
                    ("data.ingest", "数据归集入库", "active"),
                    ("data.aggregate", "数据汇总查询", "active"),
                    ("data.read", "业务数据受控读取", "active"),
                    ("data.search", "业务数据按标签检索", "active"),
                    ("data.collect", "业务数据收集登记", "active"),
                    ("data.consolidate", "业务数据整合登记", "active"),
                    ("data.persist", "业务数据固定存档", "active"),
                    ("data.trace", "业务数据资产追溯", "active"),
                    ("data.update", "业务数据更新登记", "active"),
                    ("data.delete", "业务数据删除登记", "active"),
                    ("result.export", "汇总结果导出", "active"),
                ],
            )
            self.conn.executemany(
                "INSERT INTO actors VALUES (?,?,?,?,?,?,?)",
                [
                    ("tester_a", "测试账号一", "甲公司普通员工", 1, "2026-01-01", "2099-12-31", '["TEST-A"]'),
                    ("manager_all", "测试账号二", "集团经营负责人", 1, "2026-01-01", "2099-12-31", '["TEST-A","TEST-B","TEST-C"]'),
                    ("outsider", "测试账号三", "无数据权限测试员", 1, "2026-01-01", "2099-12-31", "[]"),
                    ("disabled_user", "停用账号", "离岗测试员", 0, "2026-01-01", "2099-12-31", '["TEST-A"]'),
                    ("system_bootstrap", "系统初始化", "本地测试系统", 1, "2026-01-01", "2099-12-31", '["TEST-A","TEST-B","TEST-C","CASE9-GZ"]'),
                    ("li-zhigang", "李志刚", "桂中大区经理（案例九本地测试）", 1, "2026-01-01", "2099-12-31", '["CASE9-GZ"]'),
                    ("fu-shengxian", "付盛贤", "桂中一线业务员（案例九本地测试）", 1, "2026-01-01", "2099-12-31", '["CASE9-GZ"]'),
                    ("case9-denied", "案例九无权限账号", "无权限对照账号", 1, "2026-01-01", "2099-12-31", '[]'),
                ],
            )
            allowed = canonical_json(list(DIMENSION_COLUMNS))
            self.conn.executemany(
                "INSERT INTO metric_definitions VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    ("sales_amount", "销售金额", "CNY", 2, "sum", 1, allowed, "active", "财务负责人（测试登记）"),
                    ("expense_amount", "费用金额", "CNY", 2, "sum", 1, allowed, "active", "财务负责人（测试登记）"),
                    ("frozen_metric", "已冻结测试指标", "CNY", 2, "sum", 1, allowed, "frozen", "测试登记"),
                ],
            )
            mappings = [
                ("company", "E10", "A01", "TEST-A", "甲公司", "active"),
                ("company", "CRM", "COMP-A", "TEST-A", "甲公司", "active"),
                ("company", "E10", "B01", "TEST-B", "乙公司", "active"),
                ("company", "CRM", "BETA", "TEST-B", "乙公司", "active"),
                ("company", "LEGACY", "C-OLD", "TEST-C", "丙公司", "active"),
            ]
            self.conn.executemany("INSERT INTO code_mappings VALUES (?,?,?,?,?,?)", mappings)

        records = [
            self._seed_record("E10", "A-S-001", "A01", "sales_amount", "1000.00", "华南销售部", "微生物肥料"),
            self._seed_record("CRM", "A-S-002", "COMP-A", "sales_amount", "500.50", "华南销售部", "农业技术服务"),
            self._seed_record("E10", "B-S-001", "B01", "sales_amount", "800.00", "华东销售部", "微生物肥料"),
            self._seed_record("CRM", "B-S-002", "BETA", "sales_amount", "199.50", "华东销售部", "发酵菌剂"),
            self._seed_record("LEGACY", "C-S-001", "C-OLD", "sales_amount", "700.00", "西南销售部", "微生物肥料"),
            self._seed_record("LEGACY", "C-S-002", "C-OLD", "sales_amount", "300.00", "西南销售部", "农业技术服务"),
            self._seed_record("E10", "A-E-001", "A01", "expense_amount", "400.00", "研发中心", "发酵工艺"),
            self._seed_record("E10", "B-E-001", "B01", "expense_amount", "250.00", "研发中心", "发酵工艺"),
            self._seed_record("LEGACY", "C-E-001", "C-OLD", "expense_amount", "200.00", "农技中心", "田间试验"),
            self._seed_record("E10", "A-S-001", "A01", "sales_amount", "1000.00", "华南销售部", "微生物肥料"),
            self._seed_record("LEGACY", "BAD-001", "UNKNOWN", "sales_amount", "88.00", "测试部门", "测试产品"),
        ]
        report = self.ingest_records("system_bootstrap", records, internal=True)
        return {"reset": True, "ingestion": report, "state": self.state()}

    @staticmethod
    def _seed_record(
        source_system: str,
        source_record_id: str,
        company_code: str,
        metric_id: str,
        value: str,
        department: str,
        product: str,
    ) -> dict[str, str]:
        return {
            "source_system": source_system,
            "source_record_id": source_record_id,
            "company_code": company_code,
            "metric_id": metric_id,
            "period": "2026-06",
            "value": value,
            "unit": "CNY",
            "department": department,
            "product": product,
        }

    def _audit(
        self,
        trace_id: str,
        layer: str,
        component: str,
        action: str,
        actor_id: str | None,
        status: str,
        detail: dict[str, Any],
    ) -> int:
        cursor = self.conn.execute(
            """INSERT INTO audit_events
               (trace_id, layer, component, action, actor_id, status, detail_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (trace_id, layer, component, action, actor_id, status, canonical_json(detail), now_iso()),
        )
        return int(cursor.lastrowid)

    def _action_is_active(self, action_id: str) -> None:
        row = self.conn.execute(
            "SELECT state FROM action_catalog WHERE action_id=?", (action_id,)
        ).fetchone()
        if row is None:
            raise EngineError("ACTION_NOT_REGISTERED", f"动作 {action_id} 未登记，默认禁止", 403)
        if row["state"] != "active":
            raise EngineError("ACTION_DISABLED", f"动作 {action_id} 当前不可用", 403)

    def _resolve_actor(self, actor_id: str, trace_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM actors WHERE actor_id=?", (actor_id,)).fetchone()
        if row is None:
            self._audit(trace_id, "L1", "1.8 账号网关适配器", "resolve_actor", actor_id, "rejected", {"reason": "actor_not_found"})
            raise EngineError("ACTOR_NOT_FOUND", "当前操作真人不存在", 403)
        today = datetime.now(UTC).date().isoformat()
        if not row["active"] or not (row["valid_from"] <= today <= row["valid_until"]):
            self._audit(trace_id, "L1", "1.8 账号网关适配器", "resolve_actor", actor_id, "rejected", {"reason": "actor_inactive_or_out_of_time"})
            raise EngineError("ACTOR_INACTIVE", "当前操作真人账号未启用或不在授权时间内", 403)
        self._audit(trace_id, "L1", "1.8 账号网关适配器", "resolve_actor", actor_id, "passed", {"actor_name": row["actor_name"], "position_name": row["position_name"]})
        return row

    def _authorize(self, actor_id: str, action_id: str, companies: Iterable[str], trace_id: str) -> sqlite3.Row:
        self._action_is_active(action_id)
        actor = self._resolve_actor(actor_id, trace_id)
        requested = set(companies)
        allowed = set(json.loads(actor["allowed_companies_json"]))
        denied = sorted(requested - allowed)
        if denied:
            self._audit(
                trace_id,
                "L1",
                "1.1 权限管理适配器",
                action_id,
                actor_id,
                "rejected",
                {"requested_companies": sorted(requested), "allowed_companies": sorted(allowed), "denied_companies": denied},
            )
            raise EngineError("PERMISSION_DENIED", f"当前真人无权访问公司范围：{', '.join(denied)}", 403)
        self._audit(
            trace_id,
            "L1",
            "1.1 权限管理适配器",
            action_id,
            actor_id,
            "passed",
            {"time": now_iso(), "actor": actor_id, "data_scope": sorted(requested), "action": action_id},
        )
        return actor

    def _normalise_record(self, raw: dict[str, Any]) -> dict[str, Any]:
        required = ("source_system", "source_record_id", "company_code", "metric_id", "period", "value", "unit")
        missing = [key for key in required if raw.get(key) in (None, "")]
        if missing:
            raise EngineError("MISSING_REQUIRED_FIELD", f"缺少必填字段：{', '.join(missing)}")
        source_system = str(raw["source_system"]).strip().upper()
        source_record_id = str(raw["source_record_id"]).strip()
        period = str(raw["period"]).strip()
        if not PERIOD_RE.match(period):
            raise EngineError("INVALID_PERIOD", "期间必须为 YYYY-MM")

        metric = self.conn.execute(
            "SELECT * FROM metric_definitions WHERE metric_id=?", (str(raw["metric_id"]),)
        ).fetchone()
        if metric is None:
            raise EngineError("METRIC_NOT_REGISTERED", "指标未登记")
        if metric["state"] != "active":
            raise EngineError("METRIC_NOT_ACTIVE", "指标自身状态不允许入库")
        if str(raw["unit"]).upper() != metric["unit"]:
            raise EngineError("UNIT_MISMATCH", f"单位必须为 {metric['unit']}")

        mapping = self.conn.execute(
            """SELECT unified_code, unified_name, state FROM code_mappings
               WHERE domain='company' AND source_system=? AND source_code=?""",
            (source_system, str(raw["company_code"]).strip()),
        ).fetchone()
        if mapping is None or mapping["state"] != "active":
            raise EngineError("COMPANY_MAPPING_MISSING", "来源公司编码没有有效统一编码对照")
        try:
            value = Decimal(str(raw["value"]))
        except InvalidOperation as exc:
            raise EngineError("INVALID_NUMBER", "数值字段不是有效数字") from exc
        scale = int(metric["scale"])
        quantum = Decimal(1).scaleb(-scale)
        value = value.quantize(quantum, rounding=ROUND_HALF_UP)
        value_minor = int(value * (10**scale))
        normalised = {
            "source_system": source_system,
            "source_record_id": source_record_id,
            "source_ref": f"{source_system}:{source_record_id}",
            "metric_id": metric["metric_id"],
            "company_code": mapping["unified_code"],
            "company_name": mapping["unified_name"],
            "period": period,
            "department": str(raw.get("department") or "未标注"),
            "product": str(raw.get("product") or "未标注"),
            "value_minor": value_minor,
            "unit": metric["unit"],
            "state": "active",
        }
        normalised["payload_hash"] = stable_hash(normalised)
        return normalised

    def ingest_records(
        self,
        actor_id: str,
        records: list[dict[str, Any]],
        *,
        internal: bool = False,
    ) -> dict[str, Any]:
        trace_id = f"ingest-{uuid.uuid4()}"
        accepted: list[str] = []
        duplicates: list[str] = []
        rejected: list[dict[str, str]] = []
        with self._lock, self.conn:
            if not internal:
                self._action_is_active("data.ingest")
                actor = self._resolve_actor(actor_id, trace_id)
                if not json.loads(actor["allowed_companies_json"]):
                    raise EngineError("PERMISSION_DENIED", "当前真人没有可归集的数据范围", 403)
            for raw in records:
                try:
                    item = self._normalise_record(raw)
                    if not internal:
                        self._authorize(actor_id, "data.ingest", [item["company_code"]], trace_id)
                    existing = self.conn.execute(
                        "SELECT payload_hash FROM fact_records WHERE source_system=? AND source_record_id=?",
                        (item["source_system"], item["source_record_id"]),
                    ).fetchone()
                    if existing:
                        if existing["payload_hash"] == item["payload_hash"]:
                            duplicates.append(item["source_ref"])
                            continue
                        raise EngineError("SOURCE_RECORD_CONFLICT", "同一来源记录编号的内容发生冲突")
                    self.conn.execute(
                        """INSERT INTO fact_records
                           (source_system, source_record_id, source_ref, payload_hash, metric_id,
                            company_code, company_name, period, department, product, value_minor,
                            unit, state, ingested_by, ingested_at, raw_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            item["source_system"], item["source_record_id"], item["source_ref"], item["payload_hash"],
                            item["metric_id"], item["company_code"], item["company_name"], item["period"],
                            item["department"], item["product"], item["value_minor"], item["unit"], item["state"],
                            actor_id, now_iso(), canonical_json(raw),
                        ),
                    )
                    accepted.append(item["source_ref"])
                except EngineError as exc:
                    source_system = str(raw.get("source_system") or "")
                    source_record_id = str(raw.get("source_record_id") or "")
                    self.conn.execute(
                        """INSERT INTO rejected_records
                           (source_system, source_record_id, reason_code, reason_message, raw_json, rejected_at)
                           VALUES (?,?,?,?,?,?)""",
                        (source_system, source_record_id, exc.code, exc.message, canonical_json(raw), now_iso()),
                    )
                    rejected.append({"source_ref": f"{source_system}:{source_record_id}", "reason_code": exc.code, "message": exc.message})
            self._audit(
                trace_id,
                "L2",
                "数据归集聚合引擎",
                "ingest_records",
                actor_id,
                "completed",
                {"input": len(records), "accepted": len(accepted), "duplicates": len(duplicates), "rejected": len(rejected)},
            )
        return {
            "trace_id": trace_id,
            "input_count": len(records),
            "accepted_count": len(accepted),
            "duplicate_count": len(duplicates),
            "rejected_count": len(rejected),
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected,
        }

    def parse_l4_request(self, actor_id: str, request_text: str) -> dict[str, Any]:
        """Parse but do not execute an L4 natural-language request."""
        parse_id = f"parse-{uuid.uuid4()}"
        text = str(request_text or "").strip()
        if not actor_id:
            raise EngineError("ACTOR_REQUIRED", "必须选择当前操作真人")
        if not text:
            raise EngineError("REQUEST_TEXT_REQUIRED", "请输入 L4 自然语言请求")
        if len(text) > 1000:
            raise EngineError("REQUEST_TEXT_TOO_LONG", "自然语言请求不得超过 1000 个字符")

        with self._lock, self.conn:
            try:
                actor = self._resolve_actor(actor_id, parse_id)
                metrics = [dict(row) for row in self.conn.execute(
                    "SELECT metric_id, metric_name, state FROM metric_definitions ORDER BY metric_id"
                )]
                interpretation = self.nl_parser.parse(text, metrics)
                structured_request = None
                if interpretation["status"] == "ready":
                    structured_request = {
                        "origin_layer": "L4",
                        "request_id": f"l4-{uuid.uuid4()}",
                        "request_type": "data.aggregate",
                        "actor_id": actor_id,
                        "payload": interpretation["payload"],
                    }
                response = {
                    "parse_id": parse_id,
                    "status": interpretation["status"],
                    "actor": {
                        "actor_id": actor["actor_id"],
                        "actor_name": actor["actor_name"],
                        "position_name": actor["position_name"],
                    },
                    "request_text": text,
                    "interpretation": interpretation,
                    "structured_request": structured_request,
                    "execution_started": False,
                }
                self.conn.execute(
                    """INSERT INTO l4_interpretations
                       (parse_id, actor_id, request_text, status, parsed_json, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (parse_id, actor_id, text, interpretation["status"], canonical_json(response), now_iso()),
                )
                self._audit(
                    parse_id,
                    "L4",
                    "L4 自然语言请求端",
                    "interpret_request",
                    actor_id,
                    "passed" if interpretation["status"] == "ready" else "clarification_required",
                    {
                        "parser_mode": interpretation["parser"]["mode"],
                        "confidence": interpretation["confidence"],
                        "unresolved_fields": [item["field"] for item in interpretation["unresolved"]],
                    },
                )
                return response
            except EngineError as exc:
                response = {
                    "parse_id": parse_id,
                    "status": "rejected",
                    "reason_code": exc.code,
                    "message": exc.message,
                    "request_text": text,
                    "execution_started": False,
                }
                self.conn.execute(
                    """INSERT INTO l4_interpretations
                       (parse_id, actor_id, request_text, status, reason_code, parsed_json, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (parse_id, actor_id, text, "rejected", exc.code, canonical_json(response), now_iso()),
                )
                return response

    def execute_l4_interpretation(self, parse_id: str, actor_id: str) -> dict[str, Any]:
        """Execute the server-stored structured request produced by a prior parse."""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM l4_interpretations WHERE parse_id=?", (parse_id,)
            ).fetchone()
            if row is None:
                raise EngineError("PARSE_NOT_FOUND", "找不到该自然语言解析记录", 404)
            if row["actor_id"] != actor_id:
                raise EngineError("PARSE_ACTOR_MISMATCH", "只能由发起解析的当前真人确认执行", 403)
            if row["status"] != "ready":
                raise EngineError("PARSE_NOT_READY", "请求仍有歧义，不能进入聚合执行")
            parsed = json.loads(row["parsed_json"])
            if row["executed_trace_id"]:
                task = self.conn.execute(
                    "SELECT response_json FROM tasks WHERE trace_id=?", (row["executed_trace_id"],)
                ).fetchone()
                if task and task["response_json"]:
                    response = json.loads(task["response_json"])
                    response["parse_id"] = parse_id
                    response["execution_replayed"] = True
                    return response
            request = parsed.get("structured_request")
            if not isinstance(request, dict):
                raise EngineError("PARSE_REQUEST_MISSING", "解析记录缺少可执行结构化请求")

        response = self.process_l2_request({**request, "legacy_compatibility": True})
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE l4_interpretations SET executed_trace_id=? WHERE parse_id=?",
                (response["trace_id"], parse_id),
            )
        response["parse_id"] = parse_id
        response["execution_replayed"] = False
        return response

    def parse_data_operation_intent(self, actor_id: str, request_text: str) -> dict[str, Any]:
        """Create a pending *data operation* intent; it never performs a read.

        This is the current manual-demo route.  It deliberately differs from the
        legacy aggregation route above: intent analysis only understands the
        request, and workflow execution starts only after the human confirms it.
        """
        parse_id = f"intent-{uuid.uuid4()}"
        trace_id = f"trace-{uuid.uuid4()}"
        text = str(request_text or "").strip()
        if not actor_id:
            raise EngineError("ACTOR_REQUIRED", "必须选择当前操作真人")
        if not text:
            raise EngineError("REQUEST_TEXT_REQUIRED", "请输入 L4 自然语言请求")
        if len(text) > 1000:
            raise EngineError("REQUEST_TEXT_TOO_LONG", "自然语言请求不得超过 1000 个字符")

        with self._lock, self.conn:
            try:
                actor = self._resolve_actor(actor_id, trace_id)
                metrics = [dict(row) for row in self.conn.execute(
                    "SELECT metric_id, metric_name, state FROM metric_definitions ORDER BY metric_id"
                )]
                legacy_fields = self.nl_parser.parse(text, metrics)
                unresolved = [item for item in legacy_fields["unresolved"] if item["field"] != "dimensions"]
                compact = re.sub(r"\s+", "", text)
                query_words = ("查询", "查找", "查看", "列出", "检索", "调取")
                if not any(word in compact for word in query_words):
                    unresolved.append({
                        "field": "operation",
                        "message": "当前演示仅受理明确的数据查询请求，不会把普通句子猜成数据操作",
                        "suggestions": ["查询甲公司2026年6月的销售额记录"],
                    })
                fields = legacy_fields["fields"]
                status = "waiting_user_confirmation" if not unresolved else "clarification_required"
                payload = None
                if status == "waiting_user_confirmation":
                    period = fields["period"]["value"]
                    payload = {
                        "metric_id": fields["metric_id"]["value"],
                        "filters": {
                            "company_codes": fields["company_codes"]["value"],
                            "period_from": period,
                            "period_to": period,
                        },
                    }
                interpretation = {
                    "intent": "data.search" if payload else None,
                    "confidence": legacy_fields["confidence"],
                    "fields": {
                        key: fields[key]
                        for key in ("metric_id", "company_codes", "period")
                    },
                    "unresolved": unresolved,
                    "warnings": [
                        "这是限定领域的本地意图分析模拟；未接入正式意图分析引擎。",
                        "数据操作引擎只负责受控查询和登记，不执行汇总、规则计算或自动记忆。",
                    ],
                    "parser": {
                        "mode": "explainable_local_domain_parser_mock",
                        "calculation_role": "none",
                    },
                }
                structured_request = None
                if payload:
                    structured_request = {
                        "protocol_version": "1.0",
                        "message_id": f"msg-{uuid.uuid4()}",
                        "trace_id": trace_id,
                        "origin_layer": "L4",
                        "target_layer": "L2.workflow_execution",
                        "route_type": "command.handoff",
                        "request_id": f"l4-{uuid.uuid4()}",
                        "request_type": "data.search",
                        "actor_id": actor_id,
                        "action_id": "data.search",
                        "capability_id": "CAP.DATA.SEARCH",
                        "payload": payload,
                        "idempotency_key": f"intent-confirm-{parse_id}",
                    }
                response = {
                    "parse_id": parse_id,
                    "trace_id": trace_id,
                    "status": status,
                    "actor": {
                        "actor_id": actor["actor_id"],
                        "actor_name": actor["actor_name"],
                        "position_name": actor["position_name"],
                    },
                    "request_text": text,
                    "interpretation": interpretation,
                    "structured_request": structured_request,
                    "execution_started": False,
                }
                self.conn.execute(
                    """INSERT INTO l4_interpretations
                       (parse_id, actor_id, request_text, status, parsed_json, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (parse_id, actor_id, text, status, canonical_json(response), now_iso()),
                )
                self._audit(trace_id, "L4", "L4 请求工作台", "submit_natural_language", actor_id, "accepted", {"parse_id": parse_id})
                self._audit(trace_id, "L2", "L2 层接口控制模块（本地模拟）", "receive_and_route", actor_id, "accepted", {"route": "intent.analyze"})
                self._audit(trace_id, "L2", "意图分析引擎（本地模拟）", "intent.analyze", actor_id, "waiting_user_confirmation" if payload else "clarification_required", {"intent": interpretation["intent"], "unresolved": [item["field"] for item in unresolved]})
                return response
            except EngineError as exc:
                return {
                    "parse_id": parse_id,
                    "trace_id": trace_id,
                    "status": "rejected",
                    "reason_code": exc.code,
                    "message": exc.message,
                    "request_text": text,
                    "execution_started": False,
                }

    def confirm_data_operation_intent(self, parse_id: str, actor_id: str) -> dict[str, Any]:
        """Let the original L4 actor confirm a pending intent and start workflow."""
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT * FROM l4_interpretations WHERE parse_id=?", (parse_id,)
            ).fetchone()
            if row is None:
                raise EngineError("INTENT_NOT_FOUND", "找不到该意图分析记录", 404)
            if row["actor_id"] != actor_id:
                raise EngineError("INTENT_ACTOR_MISMATCH", "只能由发起请求的当前真人确认", 403)
            if row["status"] != "waiting_user_confirmation":
                raise EngineError("INTENT_NOT_CONFIRMABLE", "该请求未处于待真人确认状态", 409)
            parsed = json.loads(row["parsed_json"])
            request = parsed.get("structured_request")
            if not isinstance(request, dict):
                raise EngineError("INTENT_COMMAND_MISSING", "意图记录缺少可执行的流程命令", 409)
            if row["executed_trace_id"]:
                old = self.conn.execute("SELECT response_json FROM tasks WHERE trace_id=?", (row["executed_trace_id"],)).fetchone()
                if old and old["response_json"]:
                    response = json.loads(old["response_json"])
                    response["parse_id"] = parse_id
                    response["execution_replayed"] = True
                    return response
        response = self._run_data_search_workflow(request)
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE l4_interpretations SET status=?, executed_trace_id=? WHERE parse_id=?",
                ("completed" if response["status"] == "success" else "failed", response["trace_id"], parse_id),
            )
        response["parse_id"] = parse_id
        response["execution_replayed"] = False
        return response

    def receive_workflow_task(self, request: dict[str, Any]) -> dict[str, Any]:
        """Official L2 entry point for a task dispatched by workflow execution.

        The endpoint intentionally returns `accepted`; terminal data or failure is
        delivered through a persisted `flow.callback` outbox record.  The outbox
        lets the local mock be replaced by a real workflow callback client later.
        """
        source = request.get("source") if isinstance(request.get("source"), dict) else {}
        actor = request.get("actor") if isinstance(request.get("actor"), dict) else {}
        trace_id = str(request.get("trace_id") or "")
        request_id = str(request.get("request_id") or "")
        actor_id = str(request.get("actor_id") or actor.get("person_id") or "")
        action_id = str(request.get("action_id") or request.get("action") or "")
        source_service = str(request.get("source_service") or source.get("service_code") or "")
        if source_service.casefold() != "l2.workflow_execution":
            raise EngineError("INVALID_TASK_SOURCE", "数据操作引擎只接收流程执行引擎派发的任务", 403)
        if request.get("channel") and request["channel"] != "l2_internal":
            raise EngineError("INVALID_TASK_CHANNEL", "任务必须通过 L2 对内通道派发", 400)
        if request.get("route_type") and request["route_type"] != "task.dispatch":
            raise EngineError("INVALID_TASK_ROUTE", "任务必须使用 task.dispatch 路由", 400)
        if not trace_id or not request_id or not actor_id or not action_id:
            raise EngineError("TASK_ENVELOPE_INVALID", "任务必须携带 trace_id、request_id、actor_id 和 action_id")
        supported_actions = {
            "data.search", "data.read", "data.collect", "data.consolidate",
            "data.persist", "data.update", "data.delete", "data.trace",
        }
        if action_id not in supported_actions:
            raise EngineError("ACTION_NOT_IMPLEMENTED", f"当前联调骨架尚未实现 {action_id}", 501)

        with self._lock, self.conn:
            existing = self.conn.execute(
                "SELECT response_json FROM tasks WHERE trace_id=?", (trace_id,)
            ).fetchone()
            if existing:
                callback = self.conn.execute(
                    "SELECT callback_id, status FROM flow_callbacks WHERE trace_id=? ORDER BY created_at DESC LIMIT 1",
                    (trace_id,),
                ).fetchone()
                return {
                    "reply_type": "accepted",
                    "status": "accepted",
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "idempotent_replay": True,
                    "callback_ref": callback["callback_id"] if callback else None,
                    "callback_status": callback["status"] if callback else "not_created",
                }
            self.conn.execute(
                """INSERT INTO tasks
                   (request_id, trace_id, actor_id, request_type, status, request_json, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (request_id, trace_id, actor_id, action_id, "accepted", canonical_json(request), now_iso()),
            )
            self._audit(trace_id, "L2", "数据操作引擎接口", "receive_workflow_task", actor_id, "accepted", {"source_service": source_service, "action_id": action_id})

        mock = request.get("mock") or {}
        if not isinstance(mock, dict):
            return self._workflow_task_failure(trace_id, request_id, actor_id, "MOCK_CONFIG_INVALID", "mock 必须为对象", 400)
        if mock.get("l1_7") in {"timeout", "unavailable"}:
            code = "L1_7_TIMEOUT" if mock["l1_7"] == "timeout" else "L1_7_UNAVAILABLE"
            return self._workflow_task_failure(trace_id, request_id, actor_id, code, "L1.7 数据模块模拟故障", 503)

        execution_request = {
            **request,
            "source_service": source_service,
            "actor_id": actor_id,
            "action_id": action_id,
            "request_type": action_id,
            "capability_id": request.get("capability_id") or {
                "data.search": "CAP.DATA.SEARCH",
                "data.read": "CAP.DATA.READ",
                "data.collect": "CAP.DATA.COLLECT",
                "data.consolidate": "CAP.DATA.CONSOLIDATE",
                "data.persist": "CAP.DATA.PERSIST",
                "data.update": "CAP.DATA.UPDATE",
                "data.delete": "CAP.DATA.DELETE",
                "data.trace": "CAP.DATA.TRACE",
            }[action_id],
            "dispatched_by_workflow": True,
        }
        handlers = {
            "data.search": self._run_data_search_workflow,
            "data.read": self._run_data_read_workflow,
            "data.collect": self._run_data_collect_workflow,
            "data.consolidate": self._run_data_consolidate_workflow,
            "data.persist": self._run_data_persist_workflow,
            "data.update": self._run_data_update_workflow,
            "data.delete": self._run_data_delete_workflow,
            "data.trace": self._run_data_trace_workflow,
        }
        response = handlers[action_id](execution_request)
        callback_ref = response.get("callback", {}).get("callback_id")
        return {
            "reply_type": "accepted",
            "status": "accepted",
            "trace_id": trace_id,
            "request_id": request_id,
            "task_status": "completed" if response.get("status") == "success" else "failed",
            "callback_ref": callback_ref,
            "callback_status": response.get("callback", {}).get("delivery_status"),
            "idempotent_replay": False,
        }

    def _workflow_task_failure(self, trace_id: str, request_id: str, actor_id: str, code: str, message: str, http_status: int) -> dict[str, Any]:
        with self._lock, self.conn:
            error = {
                "code": code,
                "message": message,
                "retryable": http_status >= 500,
                "details": {"trace_id": trace_id, "request_id": request_id},
            }
            callback = self._enqueue_flow_callback(
                trace_id, request_id, actor_id,
                {"reply_type": "failed", "status": "failed", "trace_id": trace_id, "request_id": request_id, "reason_code": code, "message": message, "error": error},
            )
            response = {"reply_type": "failed", "status": "failed", "trace_id": trace_id, "request_id": request_id, "reason_code": code, "message": message, "error": error, "callback": callback}
            self.conn.execute("UPDATE tasks SET status=?, reason_code=?, response_json=?, finished_at=? WHERE trace_id=?", ("failed", code, canonical_json(response), now_iso(), trace_id))
            self._audit(trace_id, "L2", "数据操作引擎", "flow.callback", actor_id, "failed", {"callback_id": callback["callback_id"], "reason_code": code})
            return {"reply_type": "accepted", "status": "accepted", "trace_id": trace_id, "request_id": request_id, "task_status": "failed", "callback_ref": callback["callback_id"], "callback_status": "pending", "idempotent_replay": False}

    def _enqueue_flow_callback(self, trace_id: str, request_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        callback_id = f"callback-{uuid.uuid4()}"
        self.conn.execute(
            """INSERT INTO flow_callbacks
               (callback_id, trace_id, request_id, actor_id, target_service, status, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (callback_id, trace_id, request_id, actor_id, "L2.workflow_execution", "pending", canonical_json(payload), now_iso()),
        )
        return {"event_type": "flow.callback", "callback_id": callback_id, "delivery_status": "pending", "target_service": "L2.workflow_execution"}

    def _finalize_workflow_success(self, trace_id: str, request_id: str, actor_id: str, action_id: str, result: dict[str, Any]) -> dict[str, Any]:
        """Persist terminal task state and one reference-first callback for any action."""
        result_hash = stable_hash(result)
        callback = self._enqueue_flow_callback(
            trace_id,
            request_id,
            actor_id,
            {
                "reply_type": "success",
                "status": "success",
                "trace_id": trace_id,
                "request_id": request_id,
                "action_id": action_id,
                "result_ref": result.get("result_ref") or result.get("data_ref"),
                "result_hash": result_hash,
                **({"downstream_task_hint": result["downstream_task_hint"]} if result.get("downstream_task_hint") else {}),
            },
        )
        response = {
            "reply_type": "success",
            "status": "success",
            "request_id": request_id,
            "trace_id": trace_id,
            "data": result,
            "callback": callback,
            "evidence": {"result_hash": result_hash, "transfer": "reference_first", "aggregation": "not_called", "memory_write": "not_called"},
        }
        self.conn.execute(
            "UPDATE tasks SET status=?, result_hash=?, response_json=?, finished_at=? WHERE trace_id=?",
            ("completed", result_hash, canonical_json(response), now_iso(), trace_id),
        )
        self._audit(trace_id, "L2", "数据操作引擎", "flow.callback", actor_id, "pending", {"callback_id": callback["callback_id"], "action_id": action_id, "transfer": "reference_first"})
        return response

    def list_flow_callbacks(self, trace_id: str, actor_id: str) -> list[dict[str, Any]]:
        self._validate_active_actor_for_read(actor_id)
        task = self.conn.execute("SELECT actor_id FROM tasks WHERE trace_id=?", (trace_id,)).fetchone()
        if task is None:
            raise EngineError("TASK_NOT_FOUND", "任务不存在", 404)
        if task["actor_id"] != actor_id:
            raise EngineError("TASK_NOT_VISIBLE", "当前真人不能查看其他人的回调", 403)
        rows = self.conn.execute("SELECT * FROM flow_callbacks WHERE trace_id=? ORDER BY created_at", (trace_id,)).fetchall()
        return [{"callback_id": row["callback_id"], "trace_id": row["trace_id"], "request_id": row["request_id"], "target_service": row["target_service"], "status": row["status"], "delivery_attempts": row["delivery_attempts"], "payload": json.loads(row["payload_json"]), "created_at": row["created_at"], "acknowledged_at": row["acknowledged_at"]} for row in rows]

    def acknowledge_flow_callback(self, callback_id: str, actor_id: str) -> dict[str, Any]:
        with self._lock, self.conn:
            row = self.conn.execute("SELECT * FROM flow_callbacks WHERE callback_id=?", (callback_id,)).fetchone()
            if row is None:
                raise EngineError("CALLBACK_NOT_FOUND", "回调不存在", 404)
            if row["actor_id"] != actor_id:
                raise EngineError("CALLBACK_NOT_VISIBLE", "当前真人不能确认其他人的回调", 403)
            if row["status"] == "acknowledged":
                return {"callback_id": callback_id, "status": "acknowledged", "idempotent_replay": True}
            self.conn.execute("UPDATE flow_callbacks SET status='acknowledged', delivery_attempts=delivery_attempts+1, acknowledged_at=? WHERE callback_id=?", (now_iso(), callback_id))
            self._audit(row["trace_id"], "L2", "流程执行引擎回调接收模拟", "acknowledge_flow_callback", actor_id, "acknowledged", {"callback_id": callback_id})
            return {"callback_id": callback_id, "status": "acknowledged", "idempotent_replay": False}

    def mock_l1_identity(self, actor_id: str, trace_id: str | None = None) -> dict[str, Any]:
        trace = trace_id or f"trace-{uuid.uuid4()}"
        with self._lock, self.conn:
            actor = self._resolve_actor(actor_id, trace)
            return {"status": "success", "trace_id": trace, "adapter": "L1.8 local mock", "actor": {"actor_id": actor["actor_id"], "actor_name": actor["actor_name"], "position_name": actor["position_name"], "active": bool(actor["active"]), "allowed_companies": json.loads(actor["allowed_companies_json"])}}

    def mock_l1_permission(self, actor_id: str, action_id: str, companies: list[str], trace_id: str | None = None) -> dict[str, Any]:
        trace = trace_id or f"trace-{uuid.uuid4()}"
        with self._lock, self.conn:
            try:
                self._authorize(actor_id, action_id, companies, trace)
                return {"status": "success", "decision": "allow", "trace_id": trace, "adapter": "L1.1 local mock", "action_id": action_id, "company_scope": sorted(companies)}
            except EngineError as exc:
                return {"status": "failed", "decision": "deny", "trace_id": trace, "adapter": "L1.1 local mock", "reason_code": exc.code, "message": exc.message}

    def mock_l1_security(self, actor_id: str, action_id: str, trace_id: str | None = None) -> dict[str, Any]:
        trace = trace_id or f"trace-{uuid.uuid4()}"
        with self._lock, self.conn:
            self._resolve_actor(actor_id, trace)
            self._audit(trace, "L1", "1.9 安全合规模拟适配器", "security_check", actor_id, "passed", {"action_id": action_id, "mode": "local_mock"})
            return {"status": "success", "decision": "allow", "trace_id": trace, "adapter": "L1.9 local mock", "action_id": action_id, "notice": "本地模拟仅验证调用顺序和审计，不替代正式安全合规服务。"}

    def mock_l1_data_search(self, actor_id: str, payload: dict[str, Any], trace_id: str | None = None) -> dict[str, Any]:
        trace = trace_id or f"trace-{uuid.uuid4()}"
        if not isinstance(payload, dict):
            raise EngineError("INVALID_PAYLOAD", "payload 必须为对象")
        metric_id = str(payload.get("metric_id") or "")
        filters = payload.get("filters") or {}
        companies = filters.get("company_codes") or []
        if not metric_id or not isinstance(companies, list) or not companies:
            raise EngineError("DATA_SEARCH_ENVELOPE_INVALID", "必须携带 metric_id 和 filters.company_codes")
        with self._lock, self.conn:
            metric = self.conn.execute("SELECT * FROM metric_definitions WHERE metric_id=?", (metric_id,)).fetchone()
            if metric is None or metric["state"] != "active":
                raise EngineError("RESOURCE_STATE_BLOCKED", "数据类型未登记或当前不可读取", 409)
            scope = sorted({str(item) for item in companies})
            self._authorize(actor_id, "data.read", scope, trace)
            records = self._select_records(metric_id, filters, scope)
            self._audit(trace, "L1", "1.7 数据模块本地适配器", "read_business_data", actor_id, "completed", {"record_count": len(records), "mode": "direct_mock_contract"})
            return {"status": "success", "trace_id": trace, "adapter": "L1.7 local mock", "record_count": len(records), "records": [{"source_ref": row["source_ref"], "company_code": row["company_code"], "period": row["period"], "value": self._display_minor(int(row["value_minor"]), int(metric["scale"])), "unit": row["unit"]} for row in records]}

    @staticmethod
    def integration_contract() -> dict[str, Any]:
        return {
            "version": "0.4.0-local-contract",
            "notice": "以下为数据操作引擎的可替换联调契约；L1 与流程执行端当前均为本地 Mock。",
            "interfaces": [
                {"method": "POST", "path": "/api/l2/tasks", "owner": "数据操作引擎", "purpose": "接收流程执行引擎派单", "supported_action": ["data.search", "data.read", "data.collect", "data.consolidate", "data.persist", "data.update", "data.delete", "data.trace"], "response": "accepted + callback_ref"},
                {"method": "GET", "path": "/api/flow/callbacks?trace_id=&actor_id=", "owner": "数据操作引擎", "purpose": "读取待流程执行引擎接收的 flow.callback"},
                {"method": "POST", "path": "/api/flow/callbacks/{callback_id}/ack", "owner": "流程执行引擎 mock", "purpose": "确认接收回调，幂等"},
                {"method": "POST", "path": "/api/mock/l1/identity", "owner": "L1.8 mock", "purpose": "当前真人核验"},
                {"method": "POST", "path": "/api/mock/l1/permission", "owner": "L1.1 mock", "purpose": "按真人、动作、范围判权"},
                {"method": "POST", "path": "/api/mock/l1/security", "owner": "L1.9 mock", "purpose": "安全校验占位与审计"},
                {"method": "POST", "path": "/api/mock/l1/data/search", "owner": "L1.7 mock", "purpose": "物理数据读取适配契约"},
            ],
            "required_envelope": ["protocol_version", "message_id", "trace_id", "request_id", "source_service", "actor_id", "action_id", "payload"],
            "structured_data_search": {
                "purpose": "从已登记业务记录表经 L1.7 受控读取后做过滤、分组、计数、排序。",
                "required_payload": ["company_codes", "business_context.tenant_id", "business_context.project_id", "business_context.permission_decision_id", "query_spec.resource_types", "query_spec.filters.tenant_id"],
                "allowed_aggregations": ["count", "count_distinct"],
                "forbidden": ["ratio", "trend", "root_cause", "forecast"],
            },
            "standard_status": ["accepted", "success", "failed"],
            "mock_faults": {"l1_7": ["timeout", "unavailable"]},
        }

    def _fixed_content_payload(self, payload: Any, action_id: str) -> dict[str, Any]:
        """Validate one persistent business-data write before L1.7 is called."""
        if not isinstance(payload, dict):
            raise EngineError("INVALID_PAYLOAD", "业务数据操作 payload 必须为对象", 400)
        business_type = str(payload.get("business_type") or "").strip()
        labels = payload.get("data_labels") or []
        companies = payload.get("company_codes") or []
        content = payload.get("content")
        artifact = payload.get("artifact")
        storage_class = str(payload.get("storage_class") or "")
        retention_basis_ref = str(payload.get("approval_ref") or payload.get("retention_policy_ref") or "").strip()
        if not business_type or not isinstance(labels, list) or not labels or not isinstance(companies, list) or not companies or not isinstance(content, dict):
            raise EngineError("PERSIST_ENVELOPE_INVALID", f"{action_id} 必须携带 business_type、data_labels、company_codes 和对象形式的 content", 400)
        if storage_class != "fixed":
            raise EngineError("STORAGE_CLASS_INVALID", "业务内容持久化只接受 fixed 存档", 400)
        if not retention_basis_ref:
            raise EngineError("RETENTION_BASIS_REQUIRED", "固定存档必须携带 approval_ref 或 retention_policy_ref", 400)
        if artifact is not None and not isinstance(artifact, dict):
            raise EngineError("ARTIFACT_ENVELOPE_INVALID", "artifact 如携带必须为对象", 400)
        knowledge_binding = self._normalize_knowledge_binding(
            payload.get("knowledge_binding"), business_type
        )
        business_context = self._normalize_business_context(payload.get("business_context"))
        return {
            "business_type": business_type,
            "data_labels": sorted({str(item).strip() for item in labels if str(item).strip()}),
            "company_scope": sorted({str(item).strip() for item in companies if str(item).strip()}),
            "content": content,
            "artifact": artifact,
            "retention_basis_ref": retention_basis_ref,
            "source_ref": str(payload.get("source_ref") or "").strip() or None,
            "knowledge_binding": knowledge_binding,
            "business_context": business_context,
        }

    @staticmethod
    def _normalize_business_context(value: Any) -> dict[str, Any]:
        """Keep project/tenant/correlation metadata in the L2 business ledger."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise EngineError("BUSINESS_CONTEXT_INVALID", "business_context 必须为对象", 400)
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).strip()
            if not name:
                continue
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized[name] = text
            elif isinstance(item, (int, float, bool, list, dict)):
                normalized[name] = item
            else:
                raise EngineError("BUSINESS_CONTEXT_INVALID", f"business_context.{name} 类型不受支持", 400)
        return normalized

    @staticmethod
    def _structured_query_context(context: dict[str, Any]) -> dict[str, str]:
        required = ("tenant_id", "project_id", "permission_decision_id")
        missing = [key for key in required if not str(context.get(key) or "").strip()]
        if missing:
            raise EngineError(
                "QUERY_CONTEXT_REQUIRED",
                "结构化取数任务必须携带 business_context.tenant_id、project_id、permission_decision_id",
                400,
            )
        return {key: str(context[key]).strip() for key in required}

    def _validate_runtime_decision_audit(self, prepared: dict[str, Any], actor_id: str) -> None:
        """Persist only a decision record and a result reference, never a result rewrite."""
        if prepared["business_type"] != "runtime_decision_audit":
            return
        self._structured_query_context(prepared["business_context"])
        for key in ("business_correlation_id", "parent_trace_id"):
            if not str(prepared["business_context"].get(key) or "").strip():
                raise EngineError("DECISION_AUDIT_CONTEXT_REQUIRED", f"决策审计必须携带 business_context.{key}", 400)
        content = prepared["content"]
        if set(content) - {"decision", "related_result_ref", "subject", "recorded_at"}:
            raise EngineError("DECISION_AUDIT_CONTENT_FORBIDDEN", "决策审计只能保存 decision、related_result_ref、subject、recorded_at，不能携带或覆盖业务结果", 400)
        decision = content.get("decision")
        if not isinstance(decision, dict):
            raise EngineError("DECISION_AUDIT_CONTENT_REQUIRED", "决策审计必须包含 decision 对象", 400)
        if not str(decision.get("decision_id") or "").strip() or str(decision.get("actor_id") or "").strip() != actor_id:
            raise EngineError("DECISION_AUDIT_INVALID", "decision 必须携带 decision_id，且 decision.actor_id 必须等于当前真人", 400)
        if str(decision.get("state") or "") not in {"confirmed", "rejected"}:
            raise EngineError("DECISION_AUDIT_INVALID", "decision.state 只能是 confirmed 或 rejected", 400)

    @staticmethod
    def _normalize_knowledge_binding(value: Any, business_type: str) -> dict[str, str]:
        """Keep knowledge-library targeting explicit at the data-operation boundary."""
        knowledge_types = {"knowledge_source_file", "parsed_document"}
        if business_type not in knowledge_types:
            if value is None:
                return {}
            if not isinstance(value, dict):
                raise EngineError("KNOWLEDGE_BINDING_INVALID", "knowledge_binding 必须为对象", 400)
            return {
                key: str(item).strip()
                for key, item in value.items()
                if str(key).strip() and str(item).strip()
            }
        if not isinstance(value, dict):
            raise EngineError(
                "KNOWLEDGE_BINDING_REQUIRED",
                "知识源和解析结果必须携带 knowledge_binding.kb_asset_id 与 kb_instance_ref",
                400,
            )
        binding = {
            "kb_asset_id": str(value.get("kb_asset_id") or "").strip(),
            "kb_instance_ref": str(value.get("kb_instance_ref") or "").strip(),
        }
        if not all(binding.values()):
            raise EngineError(
                "KNOWLEDGE_BINDING_REQUIRED",
                "知识源和解析结果必须携带 knowledge_binding.kb_asset_id 与 kb_instance_ref",
                400,
            )
        return binding

    @staticmethod
    def _knowledge_followup_hint(
        business_type: str,
        data_ref: str,
        version: int,
        lifecycle: str,
        knowledge_binding: dict[str, str],
        source_ref: str | None,
    ) -> dict[str, Any] | None:
        """Return the next workflow task, without directly calling another L2 engine."""
        if business_type not in {"knowledge_source_file", "parsed_document"}:
            return None
        binding = {
            "kb_asset_id": knowledge_binding["kb_asset_id"],
            "kb_instance_ref": knowledge_binding["kb_instance_ref"],
        }
        if business_type == "knowledge_source_file" and lifecycle != "deleted":
            return {
                "event_type": "knowledge.parse_required",
                "target_service": "L2.workflow_execution",
                "next_action": "document.parse",
                "operation": "parse" if lifecycle == "created" else "reparse",
                "source_data_ref": data_ref,
                "source_version": version,
                **binding,
                "notice": "流程执行引擎应先派文档表格解析引擎；原始文件不能直接建立知识库索引。",
            }
        operation = {
            "created": "load_or_rebuild",
            "updated": "rebuild",
            "deleted": "retire",
        }[lifecycle]
        return {
            "event_type": "knowledge.index_sync_required",
            "target_service": "L2.workflow_execution",
            "next_action": "asset.knowledge_source.sync",
            "operation": operation,
            "source_data_ref": source_ref or data_ref,
            "parsed_data_ref": data_ref if business_type == "parsed_document" else None,
            "parsed_version": version if business_type == "parsed_document" else None,
            "source_version": version if business_type == "knowledge_source_file" else None,
            **binding,
            "notice": "流程执行引擎应派发数字资产引擎；数字资产引擎再调用 L1.13 装载、重建或退役索引。",
        }

    def _store_fixed_business_asset(self, request: dict[str, Any], action_id: str, *, source_ref: str | None = None, event_extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """L2 asset registration followed by one replaceable L1.7 adapter write."""
        trace_id = str(request["trace_id"])
        request_id = str(request["request_id"])
        actor_id = str(request["actor_id"])
        prepared = self._fixed_content_payload(request.get("payload"), action_id)
        self._validate_runtime_decision_audit(prepared, actor_id)
        resolved_source_ref = source_ref if source_ref is not None else prepared["source_ref"]
        with self._lock, self.conn:
            self._action_is_active(action_id)
            self._authorize(actor_id, action_id, prepared["company_scope"], trace_id)
            self._audit(trace_id, "L1", "1.9 安全合规模块模拟适配器", "security_check", actor_id, "passed", {"mode": "local_mock", "action_id": action_id})
            data_ref = f"data-{uuid.uuid4()}"
            now = now_iso()
            self.conn.execute(
                """INSERT INTO data_assets
                   (data_ref, business_type, data_labels_json, company_scope_json, storage_class, source_ref, knowledge_binding_json, business_context_json, owner_actor_id, version, state, created_trace_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data_ref, prepared["business_type"], canonical_json(prepared["data_labels"]), canonical_json(prepared["company_scope"]), "fixed", resolved_source_ref, canonical_json(prepared["knowledge_binding"]), canonical_json(prepared["business_context"]), actor_id, 1, "active", trace_id, now, now),
            )
            try:
                warehouse = self.data_module.store_business_object(data_ref=data_ref, version=1, content=prepared["content"], artifact=prepared["artifact"])
            except ValueError as exc:
                raise EngineError("ARTIFACT_INVALID", f"L1.7 文件对象校验失败：{exc}", 400) from exc
            event_detail = {"version": 1, "storage_class": "fixed", "content_hash": warehouse["content_hash"], "source_ref": resolved_source_ref, "knowledge_binding": prepared["knowledge_binding"], "business_context": prepared["business_context"], "retention_basis_ref": prepared["retention_basis_ref"]}
            if event_extra:
                event_detail.update(event_extra)
            self.conn.execute(
                """INSERT INTO data_asset_events
                   (data_ref, trace_id, actor_id, action_id, detail_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (data_ref, trace_id, actor_id, action_id, canonical_json(event_detail), now),
            )
            self._audit(trace_id, "L2", "数据操作引擎", action_id, actor_id, "completed", {"data_ref": data_ref, "business_type": prepared["business_type"], "data_labels": prepared["data_labels"]})
            self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "store_business_data", actor_id, "completed", {"data_ref": data_ref, "storage_uri": warehouse["storage_uri"], "version": 1, "mode": "local_mock"})
            result = {
                "data_ref": data_ref,
                "business_type": prepared["business_type"],
                "data_labels": prepared["data_labels"],
                "company_scope": prepared["company_scope"],
                "storage_class": "fixed",
                "version": 1,
                "source_ref": resolved_source_ref,
                "knowledge_binding": prepared["knowledge_binding"],
                "business_context": prepared["business_context"],
                "l1_location_ref": warehouse["storage_uri"],
                "content_hash": warehouse["content_hash"],
                "artifact": warehouse["artifact"],
                "notice": "数据操作引擎登记业务资产账；L1.7 数据模块适配器保管内容本体和仓管账。",
            }
            hint = self._knowledge_followup_hint(
                prepared["business_type"], data_ref, 1, "created",
                prepared["knowledge_binding"], resolved_source_ref,
            )
            if prepared["business_type"] == "runtime_decision_audit":
                result["write_scope"] = "runtime_audit_only"
                result["notice"] = "仅登记确认审计和结果引用，不写入或覆盖任何业务结果。"
            return {**result, **({"downstream_task_hint": hint} if hint else {})}

    def _run_data_persist_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._store_fixed_business_asset(request, "data.persist")
            return self._finalize_workflow_success(str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"]), "data.persist", result)
        except EngineError as exc:
            return self._workflow_task_failure(str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"]), exc.code, exc.message, exc.http_status)

    def _run_data_collect_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            source_ref = str((request.get("payload") or {}).get("source_ref") or "").strip()
            if not source_ref:
                raise EngineError("SOURCE_REF_REQUIRED", "data.collect 必须声明产生内容的 source_ref", 400)
            result = self._store_fixed_business_asset(request, "data.collect", source_ref=source_ref, event_extra={"collection_mode": "registered"})
            return self._finalize_workflow_success(str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"]), "data.collect", result)
        except EngineError as exc:
            return self._workflow_task_failure(str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"]), exc.code, exc.message, exc.http_status)

    def _run_data_consolidate_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
            source_refs = payload.get("source_data_refs") or []
            if not isinstance(source_refs, list) or len(source_refs) < 2 or any(not str(item).strip() for item in source_refs):
                raise EngineError("SOURCE_DATA_REFS_REQUIRED", "data.consolidate 至少需要两个 source_data_refs", 400)
            prepared = self._fixed_content_payload(payload, "data.consolidate")
            with self._lock, self.conn:
                for ref in sorted({str(item).strip() for item in source_refs}):
                    source = self.conn.execute("SELECT state, company_scope_json FROM data_assets WHERE data_ref=?", (ref,)).fetchone()
                    if source is None or source["state"] != "active":
                        raise EngineError("SOURCE_DATA_NOT_AVAILABLE", f"源数据不可用：{ref}", 409)
                    if not set(json.loads(source["company_scope_json"])).issubset(set(prepared["company_scope"])):
                        raise EngineError("SOURCE_SCOPE_MISMATCH", "整合范围不能绕过源数据公司范围", 403)
            source_ref = "consolidated:" + stable_hash(sorted({str(item).strip() for item in source_refs}))[:20]
            result = self._store_fixed_business_asset(request, "data.consolidate", source_ref=source_ref, event_extra={"source_data_refs": sorted({str(item).strip() for item in source_refs}), "integration_rule_ref": payload.get("integration_rule_ref")})
            return self._finalize_workflow_success(str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"]), "data.consolidate", result)
        except EngineError as exc:
            return self._workflow_task_failure(str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"]), exc.code, exc.message, exc.http_status)

    def _run_data_read_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        trace_id, request_id, actor_id = str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"])
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        data_ref = str(payload.get("data_ref") or "").strip()
        if not data_ref:
            return self._workflow_task_failure(trace_id, request_id, actor_id, "DATA_REF_REQUIRED", "data.read 必须携带 data_ref", 400)
        if payload.get("include_artifact_content") is True:
            return self._workflow_task_failure(
                trace_id, request_id, actor_id,
                "ARTIFACT_INLINE_CONTENT_FORBIDDEN",
                "data.read 只返回文件元数据与 storage_uri；解析器应通过 L1.7 受控读取接口按 data_ref 读取文件本体",
                400,
            )
        try:
            with self._lock, self.conn:
                self._action_is_active("data.read")
                asset = self.conn.execute("SELECT * FROM data_assets WHERE data_ref=?", (data_ref,)).fetchone()
                if asset is None or asset["state"] != "active":
                    raise EngineError("DATA_ASSET_NOT_AVAILABLE", "数据资产不存在或已删除", 404)
                self._authorize(actor_id, "data.read", json.loads(asset["company_scope_json"]), trace_id)
                try:
                    object_data = self.data_module.read_business_object(
                        data_ref=data_ref,
                        version=payload.get("version"),
                        include_artifact_content=False,
                    )
                except KeyError:
                    raise EngineError("L1_OBJECT_NOT_FOUND", "L1.7 未找到数据内容本体", 404)
                except PermissionError:
                    raise EngineError("DATA_OBJECT_DELETED", "L1.7 数据内容已逻辑删除", 409)
                except FileNotFoundError:
                    raise EngineError("L1_ARTIFACT_MISSING", "L1.7 文件对象缺失", 500)
                except ValueError:
                    raise EngineError("L1_ARTIFACT_INTEGRITY_FAILED", "L1.7 文件对象哈希校验失败", 500)
                self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "read_business_object", actor_id, "completed", {"data_ref": data_ref, "version": object_data["version"], "mode": "local_mock"})
                result = {"data_ref": data_ref, "business_type": asset["business_type"], "version": object_data["version"], "content_hash": object_data["content_hash"], "content": object_data["content"], "artifact": object_data["artifact"], "knowledge_binding": json.loads(asset["knowledge_binding_json"] or "{}"), "business_context": json.loads(asset["business_context_json"] or "{}"), "storage_class": "fixed"}
                return self._finalize_workflow_success(trace_id, request_id, actor_id, "data.read", result)
        except EngineError as exc:
            return self._workflow_task_failure(trace_id, request_id, actor_id, exc.code, exc.message, exc.http_status)

    def _run_data_update_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        trace_id, request_id, actor_id = str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"])
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        data_ref = str(payload.get("data_ref") or "").strip()
        reason = str(payload.get("change_reason") or "").strip()
        retention_basis_ref = str(payload.get("approval_ref") or payload.get("retention_policy_ref") or "").strip()
        content = payload.get("content")
        artifact = payload.get("artifact")
        if not data_ref or not reason or not isinstance(content, dict) or not retention_basis_ref or (artifact is not None and not isinstance(artifact, dict)):
            return self._workflow_task_failure(trace_id, request_id, actor_id, "UPDATE_ENVELOPE_INVALID", "data.update 必须携带 data_ref、content、change_reason 及 approval_ref 或 retention_policy_ref", 400)
        try:
            with self._lock, self.conn:
                self._action_is_active("data.update")
                asset = self.conn.execute("SELECT * FROM data_assets WHERE data_ref=?", (data_ref,)).fetchone()
                if asset is None or asset["state"] != "active":
                    raise EngineError("DATA_ASSET_NOT_AVAILABLE", "数据资产不存在或已删除", 404)
                scope = json.loads(asset["company_scope_json"])
                self._authorize(actor_id, "data.update", scope, trace_id)
                next_version = int(asset["version"]) + 1
                labels = payload.get("data_labels")
                next_labels = sorted({str(item).strip() for item in labels if str(item).strip()}) if isinstance(labels, list) and labels else json.loads(asset["data_labels_json"])
                current_binding = json.loads(asset["knowledge_binding_json"] or "{}")
                next_binding = (
                    self._normalize_knowledge_binding(payload.get("knowledge_binding"), asset["business_type"])
                    if "knowledge_binding" in payload else current_binding
                )
                if asset["business_type"] in {"knowledge_source_file", "parsed_document"}:
                    next_binding = self._normalize_knowledge_binding(next_binding, asset["business_type"])
                try:
                    warehouse = self.data_module.store_business_object(data_ref=data_ref, version=next_version, content=content, artifact=artifact)
                except ValueError as exc:
                    raise EngineError("ARTIFACT_INVALID", f"L1.7 文件对象校验失败：{exc}", 400) from exc
                now = now_iso()
                self.conn.execute("UPDATE data_assets SET data_labels_json=?, knowledge_binding_json=?, version=?, updated_at=? WHERE data_ref=?", (canonical_json(next_labels), canonical_json(next_binding), next_version, now, data_ref))
                self.conn.execute("INSERT INTO data_asset_events (data_ref, trace_id, actor_id, action_id, detail_json, created_at) VALUES (?,?,?,?,?,?)", (data_ref, trace_id, actor_id, "data.update", canonical_json({"previous_version": next_version - 1, "version": next_version, "change_reason": reason, "retention_basis_ref": retention_basis_ref, "content_hash": warehouse["content_hash"], "knowledge_binding": next_binding}), now))
                self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "update_business_object", actor_id, "completed", {"data_ref": data_ref, "version": next_version, "mode": "local_mock"})
                result = {"data_ref": data_ref, "version": next_version, "data_labels": next_labels, "knowledge_binding": next_binding, "content_hash": warehouse["content_hash"], "artifact": warehouse["artifact"], "l1_location_ref": warehouse["storage_uri"], "change_reason": reason}
                hint = self._knowledge_followup_hint(asset["business_type"], data_ref, next_version, "updated", next_binding, asset["source_ref"])
                if hint:
                    result["downstream_task_hint"] = hint
                return self._finalize_workflow_success(trace_id, request_id, actor_id, "data.update", result)
        except EngineError as exc:
            return self._workflow_task_failure(trace_id, request_id, actor_id, exc.code, exc.message, exc.http_status)

    def _run_data_delete_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        trace_id, request_id, actor_id = str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"])
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        data_ref = str(payload.get("data_ref") or "").strip()
        reason = str(payload.get("delete_reason") or "").strip()
        retention_basis_ref = str(payload.get("approval_ref") or payload.get("retention_policy_ref") or "").strip()
        if not data_ref or not reason or not retention_basis_ref:
            return self._workflow_task_failure(trace_id, request_id, actor_id, "DELETE_ENVELOPE_INVALID", "data.delete 必须携带 data_ref、delete_reason 及 approval_ref 或 retention_policy_ref", 400)
        try:
            with self._lock, self.conn:
                self._action_is_active("data.delete")
                asset = self.conn.execute("SELECT * FROM data_assets WHERE data_ref=?", (data_ref,)).fetchone()
                if asset is None or asset["state"] != "active":
                    raise EngineError("DATA_ASSET_NOT_AVAILABLE", "数据资产不存在或已删除", 404)
                self._authorize(actor_id, "data.delete", json.loads(asset["company_scope_json"]), trace_id)
                binding = json.loads(asset["knowledge_binding_json"] or "{}")
                if asset["business_type"] in {"knowledge_source_file", "parsed_document"}:
                    binding = self._normalize_knowledge_binding(binding, asset["business_type"])
                try:
                    warehouse = self.data_module.mark_business_object_deleted(data_ref=data_ref)
                except KeyError:
                    raise EngineError("L1_OBJECT_NOT_FOUND", "L1.7 未找到数据内容本体", 404)
                now = now_iso()
                self.conn.execute("UPDATE data_assets SET state=?, updated_at=? WHERE data_ref=?", ("deleted", now, data_ref))
                self.conn.execute("INSERT INTO data_asset_events (data_ref, trace_id, actor_id, action_id, detail_json, created_at) VALUES (?,?,?,?,?,?)", (data_ref, trace_id, actor_id, "data.delete", canonical_json({"delete_reason": reason, "retention_basis_ref": retention_basis_ref, "physical_state": "deleted"}), now))
                self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "logical_delete_business_object", actor_id, "completed", {"data_ref": data_ref, "mode": "local_mock"})
                result = {"data_ref": data_ref, "state": "deleted", "delete_reason": reason, "l1_location_ref": warehouse["storage_uri"]}
                hint = self._knowledge_followup_hint(asset["business_type"], data_ref, int(asset["version"]), "deleted", binding, asset["source_ref"])
                if hint:
                    result["downstream_task_hint"] = hint
                return self._finalize_workflow_success(trace_id, request_id, actor_id, "data.delete", result)
        except EngineError as exc:
            return self._workflow_task_failure(trace_id, request_id, actor_id, exc.code, exc.message, exc.http_status)

    def _legacy_data_persist_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        """Register a fixed business-data asset, then write its L1.7 location record.

        This is a core framework validation action: the asset ledger and the
        physical ledger are separate tables joined only by `data_ref`.
        """
        trace_id = str(request["trace_id"])
        request_id = str(request["request_id"])
        actor_id = str(request["actor_id"])
        payload = request.get("payload")
        if not isinstance(payload, dict):
            return self._workflow_task_failure(trace_id, request_id, actor_id, "INVALID_PAYLOAD", "数据存档 payload 必须为对象", 400)
        business_type = str(payload.get("business_type") or "").strip()
        data_labels = payload.get("data_labels") or []
        companies = payload.get("company_codes") or []
        content = payload.get("content")
        storage_class = str(payload.get("storage_class") or "")
        if not business_type or not isinstance(data_labels, list) or not data_labels or not isinstance(companies, list) or not companies or not isinstance(content, dict):
            return self._workflow_task_failure(trace_id, request_id, actor_id, "PERSIST_ENVELOPE_INVALID", "data.persist 必须携带 business_type、data_labels、company_codes 和对象形式的 content", 400)
        if storage_class != "fixed":
            return self._workflow_task_failure(trace_id, request_id, actor_id, "STORAGE_CLASS_INVALID", "data.persist 只接受经真人确认的 fixed 存档", 400)

        with self._lock, self.conn:
            try:
                self._action_is_active("data.persist")
                scope = sorted({str(item) for item in companies})
                self._authorize(actor_id, "data.persist", scope, trace_id)
                self._audit(trace_id, "L1", "1.9 安全合规模拟适配器", "security_check", actor_id, "passed", {"mode": "local_mock", "action_id": "data.persist"})
                data_ref = f"data-{uuid.uuid4()}"
                content_hash = stable_hash(content)
                now = now_iso()
                self.conn.execute(
                    """INSERT INTO data_assets
                       (data_ref, business_type, data_labels_json, company_scope_json, storage_class, source_ref, owner_actor_id, version, state, created_trace_id, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (data_ref, business_type, canonical_json(sorted({str(item) for item in data_labels})), canonical_json(scope), "fixed", str(payload.get("source_ref") or "") or None, actor_id, 1, "active", trace_id, now, now),
                )
                storage_uri = f"l1mock://data-module/business-data/{data_ref}"
                self.conn.execute(
                    """INSERT INTO l1_data_locations
                       (data_ref, storage_uri, content_hash, physical_state, stored_at)
                       VALUES (?,?,?,?,?)""",
                    (data_ref, storage_uri, content_hash, "stored", now),
                )
                self.conn.execute(
                    """INSERT INTO data_asset_events
                       (data_ref, trace_id, actor_id, action_id, detail_json, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (data_ref, trace_id, actor_id, "data.persist", canonical_json({"version": 1, "storage_class": "fixed", "content_hash": content_hash, "source_ref": payload.get("source_ref")}), now),
                )
                self._audit(trace_id, "L2", "数据操作引擎", "data.persist", actor_id, "completed", {"data_ref": data_ref, "business_type": business_type, "data_labels": sorted({str(item) for item in data_labels})})
                self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "store_business_data", actor_id, "completed", {"data_ref": data_ref, "storage_uri": storage_uri, "mode": "local_mock"})
                result = {"data_ref": data_ref, "business_type": business_type, "data_labels": sorted({str(item) for item in data_labels}), "company_scope": scope, "storage_class": "fixed", "version": 1, "l1_location_ref": storage_uri, "content_hash": content_hash, "notice": "资产账由数据操作引擎登记；物理仓管账由 L1.7 SQLite Mock 记录。"}
                return self._finalize_workflow_success(trace_id, request_id, actor_id, "data.persist", result)
            except EngineError as exc:
                return self._workflow_task_failure(trace_id, request_id, actor_id, exc.code, exc.message, exc.http_status)

    def _run_data_trace_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return business meaning, physical-location reference and change evidence by data_ref."""
        trace_id = str(request["trace_id"])
        request_id = str(request["request_id"])
        actor_id = str(request["actor_id"])
        payload = request.get("payload")
        data_ref = str(payload.get("data_ref") or "") if isinstance(payload, dict) else ""
        if not data_ref:
            return self._workflow_task_failure(trace_id, request_id, actor_id, "DATA_REF_REQUIRED", "data.trace 必须携带 data_ref", 400)
        with self._lock, self.conn:
            try:
                self._action_is_active("data.trace")
                asset = self.conn.execute("SELECT * FROM data_assets WHERE data_ref=?", (data_ref,)).fetchone()
                if asset is None:
                    raise EngineError("DATA_ASSET_NOT_FOUND", "数据资产登记不存在", 404)
                scope = json.loads(asset["company_scope_json"])
                self._authorize(actor_id, "data.trace", scope, trace_id)
                location = self.conn.execute("SELECT * FROM l1_data_locations WHERE data_ref=?", (data_ref,)).fetchone()
                if location is None:
                    raise EngineError("L1_LOCATION_MISSING", "资产登记存在但 L1.7 仓管记录缺失", 500)
                events = self.conn.execute("SELECT * FROM data_asset_events WHERE data_ref=? ORDER BY id", (data_ref,)).fetchall()
                self._audit(trace_id, "L2", "数据操作引擎", "data.trace", actor_id, "completed", {"data_ref": data_ref, "event_count": len(events)})
                result = {
                    "data_ref": data_ref,
                    "business_type": asset["business_type"],
                    "data_labels": json.loads(asset["data_labels_json"]),
                    "company_scope": scope,
                    "storage_class": asset["storage_class"],
                    "source_ref": asset["source_ref"],
                    "business_context": json.loads(asset["business_context_json"] or "{}"),
                    "version": asset["version"],
                    "state": asset["state"],
                    "created_trace_id": asset["created_trace_id"],
                    "l1_location_ref": location["storage_uri"],
                    "content_hash": location["content_hash"],
                    "changes": [{"trace_id": row["trace_id"], "action_id": row["action_id"], "detail": json.loads(row["detail_json"]), "created_at": row["created_at"]} for row in events],
                }
                return self._finalize_workflow_success(trace_id, request_id, actor_id, "data.trace", result)
            except EngineError as exc:
                return self._workflow_task_failure(trace_id, request_id, actor_id, exc.code, exc.message, exc.http_status)

    def _legacy_metric_search_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        """Workflow mock: dispatch one data.search task and accept flow.callback only."""
        trace_id = str(request["trace_id"])
        request_id = str(request["request_id"])
        actor_id = str(request["actor_id"])
        payload = request.get("payload")
        if not isinstance(payload, dict):
            raise EngineError("INVALID_PAYLOAD", "数据查询 payload 必须为对象")

        with self._lock, self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO tasks
                   (request_id, trace_id, actor_id, request_type, status, request_json, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (request_id, trace_id, actor_id, "data.search", "accepted", canonical_json(request), now_iso()),
            )
            try:
                if not request.get("dispatched_by_workflow"):
                    self._audit(trace_id, "L2", "流程执行引擎（本地模拟）", "workflow.create", actor_id, "accepted", {"request_id": request_id, "capability_id": request.get("capability_id")})
                    self._audit(trace_id, "L2", "流程执行引擎（本地模拟）", "task.dispatch", actor_id, "accepted", {"target_engine": "数据操作引擎", "action_id": "data.search"})
                self._action_is_active("data.search")
                metric_id = str(payload.get("metric_id") or "")
                metric = self.conn.execute("SELECT * FROM metric_definitions WHERE metric_id=?", (metric_id,)).fetchone()
                if metric is None:
                    raise EngineError("METRIC_NOT_REGISTERED", "请求的数据类型未登记", 404)
                if metric["state"] != "active":
                    raise EngineError("RESOURCE_STATE_BLOCKED", "请求的数据类型当前不可读取", 409)
                filters = payload.get("filters") or {}
                companies = filters.get("company_codes") or []
                if not isinstance(companies, list) or not companies:
                    raise EngineError("COMPANY_SCOPE_REQUIRED", "必须明确公司数据范围，禁止默认全量查询")
                companies = sorted({str(item) for item in companies})
                self._authorize(actor_id, "data.read", companies, trace_id)
                self._audit(trace_id, "L1", "1.9 安全合规模拟适配器", "security_check", actor_id, "passed", {"mode": "local_mock", "action_id": "data.read"})
                records = self._select_records(metric_id, filters, companies)
                self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "read_business_data", actor_id, "completed", {"metric_id": metric_id, "record_count": len(records), "company_scope": companies, "mode": "local_mock"})
                if not records:
                    raise EngineError("DATA_NOT_FOUND", "授权范围内没有符合条件的业务数据", 404)
                rows = [
                    {
                        "source_ref": record["source_ref"],
                        "company_code": record["company_code"],
                        "company_name": record["company_name"],
                        "period": record["period"],
                        "department": record["department"],
                        "product": record["product"],
                        "value": self._display_minor(int(record["value_minor"]), int(metric["scale"])),
                        "unit": record["unit"],
                    }
                    for record in records
                ]
                result_ref = f"result-{uuid.uuid4()}"
                result = {
                    "result_ref": result_ref,
                    "storage_class": "temporary",
                    "metric": {"metric_id": metric_id, "metric_name": metric["metric_name"], "unit": metric["unit"]},
                    "filters": {"company_codes": companies, "period_from": filters.get("period_from"), "period_to": filters.get("period_to")},
                    "record_count": len(rows),
                    "records": rows,
                    "lineage_refs": [row["source_ref"] for row in rows],
                    "l1_notice": "由 SQLite 本地适配器模拟 L1.7 数据模块；不是生产数据模块联调。",
                }
                result_hash = stable_hash(result)
                self.conn.execute(
                    """INSERT INTO data_operation_results
                       (result_ref, trace_id, actor_id, action_id, storage_class, result_json, result_hash, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (result_ref, trace_id, actor_id, "data.search", "temporary", canonical_json(result), result_hash, now_iso()),
                )
                self._audit(trace_id, "L2", "数据操作引擎", "data.search", actor_id, "completed", {"result_ref": result_ref, "record_count": len(rows), "no_aggregation": True, "no_memory_write": True})
                callback = {"event_type": "flow.callback", "result_ref": result_ref, "consumer": "流程执行引擎", "route": "数据操作引擎 → 流程执行引擎 → L4"}
                if request.get("dispatched_by_workflow"):
                    callback = {**callback, **self._enqueue_flow_callback(trace_id, request_id, actor_id, {"reply_type": "success", "status": "success", "trace_id": trace_id, "request_id": request_id, "result_ref": result_ref, "result_hash": result_hash})}
                    self._audit(trace_id, "L2", "数据操作引擎", "flow.callback", actor_id, "pending", {"callback_id": callback["callback_id"], "result_ref": result_ref, "transfer": "reference_first"})
                else:
                    self._audit(trace_id, "L2", "数据操作引擎", "flow.callback", actor_id, "success", {"result_ref": result_ref, "transfer": "reference_first"})
                    self._audit(trace_id, "L2", "流程执行引擎（本地模拟）", "callback.accept", actor_id, "success", {"result_ref": result_ref})
                response = {
                    "reply_type": "success",
                    "status": "success",
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "workflow": {"status": "completed", "orchestrator": "流程执行引擎（本地模拟）", "callback_only": True},
                    "data": result,
                    "callback": callback,
                    "evidence": {"result_hash": result_hash, "permission_mode": "当前真人按动作实时判定（本地 Mock）", "memory_write": "not_called", "aggregation": "not_called"},
                }
                self.conn.execute("UPDATE tasks SET status=?, result_hash=?, response_json=?, finished_at=? WHERE trace_id=?", ("completed", result_hash, canonical_json(response), now_iso(), trace_id))
                return response
            except EngineError as exc:
                self._audit(trace_id, "L2", "数据操作引擎", "flow.callback", actor_id, "failed", {"reason_code": exc.code})
                response = {"reply_type": "failed", "status": "failed", "request_id": request_id, "trace_id": trace_id, "reason_code": exc.code, "message": exc.message, "callback": {"event_type": "flow.callback", "consumer": "流程执行引擎"}}
                self.conn.execute("UPDATE tasks SET status=?, reason_code=?, response_json=?, finished_at=? WHERE trace_id=?", ("failed", exc.code, canonical_json(response), now_iso(), trace_id))
                return response

    @staticmethod
    def _query_value_matches(actual: Any, expected: Any) -> bool:
        if isinstance(expected, dict):
            if "eq" in expected and actual != expected["eq"]:
                return False
            if "in" in expected:
                allowed = expected["in"]
                if not isinstance(allowed, list) or actual not in allowed:
                    return False
            if "gte" in expected and actual < expected["gte"]:
                return False
            if "lte" in expected and actual > expected["lte"]:
                return False
            return True
        if isinstance(expected, list):
            return actual in expected
        return actual == expected

    @classmethod
    def _record_matches_query_filters(cls, record: dict[str, Any], filters: dict[str, Any]) -> bool:
        return all(key in record and cls._query_value_matches(record[key], expected) for key, expected in filters.items())

    @staticmethod
    def _project_query_record(record: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        if not fields:
            return {key: value for key, value in record.items() if not key.startswith("_")}
        return {field: record.get(field) for field in fields if field in record}

    @staticmethod
    def _sort_query_rows(rows: list[dict[str, Any]], sort_rules: list[dict[str, str]]) -> list[dict[str, Any]]:
        ordered = list(rows)
        for rule in reversed(sort_rules):
            field = rule["field"]
            reverse = rule["direction"] == "desc"
            ordered.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=reverse)
        return ordered

    @staticmethod
    def _business_result_number(value: Decimal) -> int | float:
        """Return JSON-safe deterministic numeric output without string formatting."""
        if value == value.to_integral_value():
            return int(value)
        return float(value)

    @staticmethod
    def _assemble_extracted_field_rows(cells: list[dict[str, Any]], data_ref: str) -> list[dict[str, Any]]:
        """Turn cell-level parsed fields into rows without guessing any business meaning.

        `parse_job_id + sheet + row` is only a physical reassembly key.  The
        caller still supplies the business object, operation and projected
        fields in query_spec; this engine never infers a dealer, customer or
        other business entity from cell names.
        """
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            field_name = str(cell.get("field_name") or "").strip()
            row_number = cell.get("row")
            if not field_name or row_number is None:
                continue
            parse_job_id = str(cell.get("parse_job_id") or data_ref)
            sheet = str(cell.get("sheet") or cell.get("sheet_name") or "default")
            key = (parse_job_id, sheet, str(row_number))
            row = grouped.setdefault(
                key,
                {
                    "_evidence_ref": f"{data_ref}#parse={parse_job_id};sheet={sheet};row={row_number}",
                    "_field_names": [],
                },
            )
            row[field_name] = cell.get("value")
            row["_field_names"].append(field_name)
        return list(grouped.values())

    @classmethod
    def _content_records_for_query(cls, content: dict[str, Any], resource_type: str, data_ref: str) -> list[dict[str, Any]]:
        """Read either registered business rows or parser cell fields behind one seam."""
        candidates = content.get("records")
        if not isinstance(candidates, list):
            candidates = content.get("items")
        if resource_type == "extracted_fields":
            return cls._assemble_extracted_field_rows(candidates if isinstance(candidates, list) else [], data_ref)
        return [dict(item) for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []

    @staticmethod
    def _business_query_summary(operation: str, business_object: dict[str, Any], record_count: int, row_count: int) -> str:
        label = str(business_object.get("name") or business_object.get("code") or "业务对象")
        return f"已从获授权数据中读取 {record_count} 条原始记录，形成 {row_count} 条{label}业务结果（{operation}）。"

    def _run_structured_business_query(self, request: dict[str, Any]) -> dict[str, Any]:
        """Read registered record tables through L1.7, then only filter/group/count/sort.

        Ratios, trend calculations, contribution judgement and diagnosis are
        deliberately absent: they remain the rule-calculation or
        analysis-prediction module's responsibility.
        """
        trace_id, request_id, actor_id = str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"])
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        spec = payload.get("query_spec")
        if not isinstance(spec, dict):
            return self._workflow_task_failure(trace_id, request_id, actor_id, "QUERY_SPEC_INVALID", "query_spec 必须为对象", 400)
        resource_types = spec.get("resource_types") or []
        fields = spec.get("fields") or []
        filters = spec.get("filters") or {}
        group_by = spec.get("group_by") or []
        aggregations = spec.get("aggregations") or []
        sort_rules = spec.get("sort") or []
        requested_operation = str(spec.get("operation") or "").strip()
        requested_object = spec.get("business_object")
        companies = payload.get("company_codes") or []
        if (
            not isinstance(resource_types, list) or not resource_types
            or not isinstance(fields, list) or not isinstance(filters, dict)
            or not isinstance(group_by, list) or not isinstance(aggregations, list)
            or not isinstance(sort_rules, list) or not isinstance(companies, list) or not companies
        ):
            return self._workflow_task_failure(trace_id, request_id, actor_id, "QUERY_SPEC_INVALID", "结构化查询必须携带 resource_types、filters、company_codes，且字段、分组、聚合、排序均为数组", 400)
        try:
            scope = sorted({str(item).strip() for item in companies if str(item).strip()})
            if not scope:
                raise EngineError("COMPANY_SCOPE_REQUIRED", "必须明确公司数据范围，禁止默认全量查询", 400)
            normalized_resource_types = {str(item).strip() for item in resource_types if str(item).strip()}
            normalized_fields = [str(item).strip() for item in fields if str(item).strip()]
            normalized_group_by = [str(item).strip() for item in group_by if str(item).strip()]
            if not normalized_resource_types:
                raise EngineError("RESOURCE_TYPE_REQUIRED", "结构化查询必须指定 resource_types", 400)
            context = self._structured_query_context(
                self._normalize_business_context(payload.get("business_context"))
            )
            if filters.get("tenant_id") != context["tenant_id"]:
                raise EngineError("TENANT_FILTER_REQUIRED", "结构化查询必须以 filters.tenant_id 限定为当前租户", 400)
            legacy_contract_warnings: list[str] = []
            if not requested_operation:
                requested_operation = "group_metric" if group_by or aggregations else "detail_records"
                legacy_contract_warnings.append("QUERY_SPEC_OPERATION_DEFAULTED: 后续流程派单必须显式提供 operation。")
            allowed_operations = {"list_entity", "count_entity", "aggregate_metric", "group_metric", "max_metric", "min_metric", "detail_records"}
            forbidden_operations = {"ratio", "trend", "root_cause", "forecast", "diagnosis", "prediction"}
            if requested_operation in forbidden_operations:
                raise EngineError("BUSINESS_OPERATION_NOT_ALLOWED", "比例、趋势、归因、诊断和预测不属于数据操作引擎", 400)
            if requested_operation not in allowed_operations:
                raise EngineError("BUSINESS_OPERATION_INVALID", "operation 必须是已登记的基础业务结果类型", 400)
            if isinstance(requested_object, str) and requested_object.strip():
                business_object = {"code": requested_object.strip(), "name": requested_object.strip()}
            elif isinstance(requested_object, dict) and str(requested_object.get("code") or requested_object.get("name") or "").strip():
                business_object = {"code": str(requested_object.get("code") or requested_object.get("name")).strip(), "name": str(requested_object.get("name") or requested_object.get("code")).strip()}
            else:
                default_object = sorted(normalized_resource_types)[0]
                business_object = {"code": default_object, "name": default_object}
                legacy_contract_warnings.append("QUERY_SPEC_BUSINESS_OBJECT_DEFAULTED: 后续流程派单必须显式提供 business_object。")
            normalized_aggregations: list[dict[str, str]] = []
            aliases: set[str] = set()
            for item in aggregations:
                if not isinstance(item, dict):
                    raise EngineError("AGGREGATION_INVALID", "aggregations 中每项必须为对象", 400)
                operation = str(item.get("op") or "").strip()
                field = str(item.get("field") or "").strip()
                alias = str(item.get("as") or "").strip()
                if operation not in {"count", "count_distinct", "sum", "max", "min"}:
                    raise EngineError("AGGREGATION_NOT_ALLOWED", "数据操作引擎仅允许 count 和 count_distinct；比率和趋势必须交规则计算引擎", 400)
                if operation in {"count_distinct", "sum", "max", "min"} and not field:
                    raise EngineError("AGGREGATION_INVALID", "count_distinct 必须指定 field", 400)
                if not alias or alias in aliases:
                    raise EngineError("AGGREGATION_INVALID", "每个聚合必须有唯一 as", 400)
                aliases.add(alias)
                normalized_aggregations.append({"op": operation, "field": field, "as": alias})
            normalized_sort: list[dict[str, str]] = []
            for item in sort_rules:
                if not isinstance(item, dict):
                    raise EngineError("SORT_INVALID", "sort 中每项必须为对象", 400)
                field = str(item.get("field") or "").strip()
                direction = str(item.get("direction") or "asc").strip().lower()
                if not field or direction not in {"asc", "desc"}:
                    raise EngineError("SORT_INVALID", "sort 每项必须携带 field，direction 只能为 asc 或 desc", 400)
                normalized_sort.append({"field": field, "direction": direction})

            if requested_operation == "group_metric" and not normalized_group_by:
                raise EngineError("BUSINESS_OPERATION_INVALID", "group_metric 必须提供 group_by", 400)
            if requested_operation == "count_entity" and not any(item["op"] in {"count", "count_distinct"} for item in normalized_aggregations):
                raise EngineError("BUSINESS_OPERATION_INVALID", "count_entity 必须提供 count 或 count_distinct", 400)
            if requested_operation == "aggregate_metric" and not normalized_aggregations:
                raise EngineError("BUSINESS_OPERATION_INVALID", "aggregate_metric 必须提供确定性 aggregations", 400)
            if requested_operation == "max_metric" and not any(item["op"] == "max" for item in normalized_aggregations):
                raise EngineError("BUSINESS_OPERATION_INVALID", "max_metric 必须提供 max aggregation", 400)
            if requested_operation == "min_metric" and not any(item["op"] == "min" for item in normalized_aggregations):
                raise EngineError("BUSINESS_OPERATION_INVALID", "min_metric 必须提供 min aggregation", 400)

            with self._lock, self.conn:
                self._action_is_active("data.search")
                # The business task is data.search; physical data retrieval is data.read.
                self._authorize(actor_id, "data.read", scope, trace_id)
                self._audit(trace_id, "L1", "1.9 安全合规模块模拟适配器", "security_check", actor_id, "passed", {"mode": "local_mock", "action_id": "data.read"})
                assets = self.conn.execute("SELECT * FROM data_assets WHERE state='active' AND business_type='business_record_table' ORDER BY updated_at, data_ref").fetchall()
                records: list[dict[str, Any]] = []
                data_refs: list[str] = []
                source_refs: list[str] = []
                data_source_types: dict[str, set[str]] = defaultdict(set)
                for asset in assets:
                    asset_scope = set(json.loads(asset["company_scope_json"]))
                    if not asset_scope.issubset(set(scope)):
                        continue
                    asset_context = json.loads(asset["business_context_json"] or "{}")
                    if context and asset_context.get("tenant_id") != context["tenant_id"]:
                        continue
                    try:
                        object_data = self.data_module.read_business_object(data_ref=asset["data_ref"], include_artifact_content=False)
                    except KeyError as exc:
                        raise EngineError("L1_OBJECT_NOT_FOUND", "L1.7 未找到业务记录表对象", 404) from exc
                    content = object_data.get("content") or {}
                    resource_type = str(content.get("resource_type") or "")
                    table_records = self._content_records_for_query(content, resource_type, asset["data_ref"])
                    if resource_type not in normalized_resource_types or not table_records:
                        continue
                    data_refs.append(asset["data_ref"])
                    data_source_types[asset["data_ref"]].add(resource_type)
                    for raw_record in table_records:
                        if not isinstance(raw_record, dict) or not self._record_matches_query_filters(raw_record, filters):
                            continue
                        records.append(dict(raw_record))
                        source_ref = raw_record.get("source_ref") or raw_record.get("_evidence_ref")
                        if source_ref:
                            source_refs.append(str(source_ref))

                if not records:
                    raise EngineError("DATA_NOT_FOUND", "授权范围内没有符合结构化范围的业务记录", 404)
                self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "read_business_data", actor_id, "completed", {"record_count": len(records), "data_refs": sorted(set(data_refs)), "mode": "local_mock"})
                if normalized_group_by or normalized_aggregations:
                    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
                    if normalized_group_by:
                        for record in records:
                            groups[tuple(record.get(field) for field in normalized_group_by)].append(record)
                    else:
                        groups[()] = records
                    result_rows: list[dict[str, Any]] = []
                    for key, grouped_records in groups.items():
                        row = {field: key[index] for index, field in enumerate(normalized_group_by)}
                        for aggregation in normalized_aggregations:
                            if aggregation["op"] == "count":
                                row[aggregation["as"]] = len(grouped_records)
                            elif aggregation["op"] == "count_distinct":
                                row[aggregation["as"]] = len({record.get(aggregation["field"]) for record in grouped_records if aggregation["field"] in record})
                            elif aggregation["op"] == "sum":
                                try:
                                    row[aggregation["as"]] = self._business_result_number(sum((Decimal(str(record[aggregation["field"]])) for record in grouped_records if aggregation["field"] in record and record[aggregation["field"]] is not None), Decimal("0")))
                                except (InvalidOperation, ValueError) as exc:
                                    raise EngineError("AGGREGATION_FIELD_NOT_NUMERIC", f"sum 字段 {aggregation['field']} 存在非数值", 400) from exc
                            else:
                                values = [record[aggregation["field"]] for record in grouped_records if aggregation["field"] in record and record[aggregation["field"]] is not None]
                                if not values:
                                    row[aggregation["as"]] = None
                                elif aggregation["op"] == "max":
                                    row[aggregation["as"]] = max(values)
                                else:
                                    row[aggregation["as"]] = min(values)
                        result_rows.append(row)
                else:
                    result_rows = [self._project_query_record(record, normalized_fields) for record in records]
                if normalized_sort:
                    result_rows = self._sort_query_rows(result_rows, normalized_sort)
                limit = spec.get("limit", 1000)
                if not isinstance(limit, int) or limit < 1 or limit > 1000:
                    raise EngineError("QUERY_LIMIT_INVALID", "limit 必须是 1 到 1000 的整数", 400)
                result_rows = result_rows[:limit]
                result_ref = f"result-{uuid.uuid4()}"
                query_ref = f"query-{uuid.uuid4()}"
                source_data_refs = sorted(set(data_refs))
                evidence_refs = sorted(set(source_refs))
                result = {
                    "result_ref": result_ref,
                    "contract_version": "business-result.v1",
                    "result_type": "business_result",
                    "storage_class": "temporary",
                    "query": {
                        "scenario": spec.get("scenario"), "resource_types": sorted(normalized_resource_types),
                        "filters": filters, "fields": normalized_fields, "group_by": normalized_group_by,
                        "aggregations": normalized_aggregations, "sort": normalized_sort,
                        "company_codes": scope,
                    },
                    "business_result": {
                        "operation": requested_operation,
                        "business_object": business_object,
                        "summary": self._business_query_summary(requested_operation, business_object, len(records), len(result_rows)),
                        "items": result_rows,
                        "metrics": {"matched_record_count": len(records), "result_item_count": len(result_rows)},
                        "warnings": legacy_contract_warnings,
                    },
                    "evidence": {
                        "data_sources": [{"data_ref": ref, "resource_types": sorted(data_source_types[ref])} for ref in source_data_refs],
                        "evidence_refs": evidence_refs,
                        "permission": {"action_id": "data.read", "decision_id": context.get("permission_decision_id"), "mode": "local_mock"},
                    },
                    "raw_access": {
                        "query_ref": query_ref,
                        "raw_count": len(records),
                        "source_data_refs": source_data_refs,
                        "record_format": "row_assembled_from_extracted_fields" if "extracted_fields" in normalized_resource_types else "business_record_table",
                        "sample_preview": [self._project_query_record(record, normalized_fields) for record in records[:3]],
                    },
                    "notice": "仅返回获授权的原始记录或确定性分组/计数/排序结果；比率、归因和预测未执行。",
                }
                result_hash = stable_hash(result)
                self.conn.execute("INSERT INTO data_operation_results (result_ref, trace_id, actor_id, action_id, storage_class, result_json, result_hash, created_at) VALUES (?,?,?,?,?,?,?,?)", (result_ref, trace_id, actor_id, "data.search", "temporary", canonical_json(result), result_hash, now_iso()))
                self._audit(trace_id, "L2", "数据操作引擎", "data.search", actor_id, "completed", {"result_ref": result_ref, "query_ref": query_ref, "operation": requested_operation, "record_count": len(records), "row_count": len(result_rows), "query_mode": "business_result", "no_ratio_calculation": True, "no_analysis": True})
                return self._finalize_workflow_success(trace_id, request_id, actor_id, "data.search", result)
        except EngineError as exc:
            return self._workflow_task_failure(trace_id, request_id, actor_id, exc.code, exc.message, exc.http_status)

    def _run_data_search_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        """Search registered business-data assets by tag; metric lookup is compatibility-only."""
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        if payload.get("query_spec") is not None:
            return self._run_structured_business_query(request)
        if payload.get("metric_id"):
            return self._legacy_metric_search_workflow(request)
        trace_id, request_id, actor_id = str(request["trace_id"]), str(request["request_id"]), str(request["actor_id"])
        labels = payload.get("data_labels") or []
        companies = payload.get("company_codes") or []
        if not isinstance(labels, list) or not isinstance(companies, list) or not companies:
            return self._workflow_task_failure(trace_id, request_id, actor_id, "SEARCH_ENVELOPE_INVALID", "标签检索必须携带 data_labels（可为空数组）和明确的 company_codes", 400)
        try:
            with self._lock, self.conn:
                self._action_is_active("data.search")
                scope = sorted({str(item).strip() for item in companies if str(item).strip()})
                if not scope:
                    raise EngineError("COMPANY_SCOPE_REQUIRED", "必须明确公司数据范围，禁止默认全量查询", 400)
                self._authorize(actor_id, "data.search", scope, trace_id)
                required_labels = {str(item).strip() for item in labels if str(item).strip()}
                business_type = str(payload.get("business_type") or "").strip()
                rows = self.conn.execute("SELECT * FROM data_assets WHERE state='active' ORDER BY updated_at DESC").fetchall()
                items = []
                for asset in rows:
                    asset_scope = set(json.loads(asset["company_scope_json"]))
                    asset_labels = set(json.loads(asset["data_labels_json"]))
                    if not asset_scope.issubset(set(scope)) or not required_labels.issubset(asset_labels):
                        continue
                    if business_type and asset["business_type"] != business_type:
                        continue
                    items.append({"data_ref": asset["data_ref"], "business_type": asset["business_type"], "data_labels": sorted(asset_labels), "company_scope": sorted(asset_scope), "version": asset["version"], "source_ref": asset["source_ref"], "updated_at": asset["updated_at"]})
                result_ref = f"result-{uuid.uuid4()}"
                result = {"result_ref": result_ref, "storage_class": "temporary", "query": {"data_labels": sorted(required_labels), "business_type": business_type or None, "company_codes": scope}, "item_count": len(items), "items": items, "notice": "按标签返回资产登记信息；内容本体须再通过 data.read 受控读取。"}
                result_hash = stable_hash(result)
                self.conn.execute("INSERT INTO data_operation_results (result_ref, trace_id, actor_id, action_id, storage_class, result_json, result_hash, created_at) VALUES (?,?,?,?,?,?,?,?)", (result_ref, trace_id, actor_id, "data.search", "temporary", canonical_json(result), result_hash, now_iso()))
                self._audit(trace_id, "L2", "数据操作引擎", "data.search", actor_id, "completed", {"result_ref": result_ref, "item_count": len(items), "query_mode": "asset_tags"})
                return self._finalize_workflow_success(trace_id, request_id, actor_id, "data.search", result)
        except EngineError as exc:
            return self._workflow_task_failure(trace_id, request_id, actor_id, exc.code, exc.message, exc.http_status)

    def process_l2_request(self, request: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(request.get("trace_id") or f"trace-{uuid.uuid4()}")
        request_id = str(request.get("request_id") or f"req-{uuid.uuid4()}")
        request_type = str(request.get("request_type") or "")
        actor_id = str(request.get("actor_id") or "")
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO tasks
                   (request_id, trace_id, actor_id, request_type, status, request_json, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (request_id, trace_id, actor_id or None, request_type, "received", canonical_json(request), now_iso()),
            )
            self._audit(trace_id, "L2", "L2 层接口·请求接收端", "receive_request", actor_id or None, "received", {"request_id": request_id, "request_type": request_type, "origin_layer": request.get("origin_layer")})
            try:
                response = self._process_request(trace_id, request_id, request_type, actor_id, request)
                self.conn.execute(
                    """UPDATE tasks SET status='completed', result_hash=?, response_json=?, finished_at=?
                       WHERE trace_id=?""",
                    (response["evidence"]["result_hash"], canonical_json(response), now_iso(), trace_id),
                )
                self._audit(trace_id, "L2", "L2 层接口·请求发起端", "return_standard_reply", actor_id, "completed", {"reply_type": response["reply_type"], "request_id": request_id})
                return response
            except EngineError as exc:
                return self._rejected_response(trace_id, request_id, actor_id, exc)
            except Exception as exc:  # defensive boundary; details remain in the local audit only
                self._audit(trace_id, "L2", "数据归集聚合引擎", "unexpected_error", actor_id or None, "error", {"exception_type": type(exc).__name__, "message": str(exc)})
                return self._rejected_response(trace_id, request_id, actor_id, EngineError("INTERNAL_ERROR", "引擎执行失败，请按追踪编号排查", 500))

    def _process_request(
        self,
        trace_id: str,
        request_id: str,
        request_type: str,
        actor_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        if not request.get("legacy_compatibility"):
            raise EngineError("LEGACY_ENDPOINT_DISABLED", "旧 data.aggregate 入口仅保留给显式兼容演示；正式链路必须由流程执行引擎派发 /api/l2/tasks", 410)
        if request.get("origin_layer") != "L4":
            raise EngineError("INVALID_ORIGIN_LAYER", "L2 请求接收端只接收来源为 L4 的业务请求", 403)
        if not actor_id:
            raise EngineError("ACTOR_REQUIRED", "必须携带当前操作真人编号")
        service = self.conn.execute(
            "SELECT * FROM service_directory WHERE request_type=?", (request_type,)
        ).fetchone()
        if service is None or service["state"] not in {"active", "legacy"}:
            raise EngineError("SERVICE_NOT_REGISTERED", "请求类型未进入有效服务目录")
        self._audit(trace_id, "L2", "L2 服务目录", "dispatch", actor_id, "passed", {"request_type": request_type, "engine": service["engine_key"]})
        if request_type != "data.aggregate":
            raise EngineError("UNSUPPORTED_REQUEST_TYPE", "当前纵向切片只实现 data.aggregate")

        payload = request.get("payload")
        if not isinstance(payload, dict):
            raise EngineError("INVALID_PAYLOAD", "payload 必须为对象")
        metric_id = str(payload.get("metric_id") or "")
        metric = self.conn.execute(
            "SELECT * FROM metric_definitions WHERE metric_id=?", (metric_id,)
        ).fetchone()
        if metric is None:
            raise EngineError("METRIC_NOT_REGISTERED", "指标未登记")
        # Resource state is checked before actor permission, per v1.8.5.
        if metric["state"] != "active":
            self._audit(trace_id, "L1", "1.7 数据模块适配器", "check_resource_state", actor_id, "rejected", {"metric_id": metric_id, "state": metric["state"]})
            raise EngineError("RESOURCE_STATE_BLOCKED", "指标自身状态不允许执行汇总", 409)
        self._audit(trace_id, "L1", "1.7 数据模块适配器", "check_resource_state", actor_id, "passed", {"metric_id": metric_id, "state": metric["state"]})

        dimensions = payload.get("dimensions") or []
        if not isinstance(dimensions, list) or not dimensions:
            raise EngineError("DIMENSIONS_REQUIRED", "至少选择一个汇总维度")
        if len(dimensions) != len(set(dimensions)):
            raise EngineError("DUPLICATE_DIMENSION", "汇总维度不可重复")
        allowed_dimensions = set(json.loads(metric["allowed_dimensions_json"]))
        invalid_dims = [d for d in dimensions if d not in allowed_dimensions or d not in DIMENSION_COLUMNS]
        if invalid_dims:
            raise EngineError("DIMENSION_NOT_ALLOWED", f"未登记的汇总维度：{', '.join(invalid_dims)}")

        filters = payload.get("filters") or {}
        companies = filters.get("company_codes") or []
        if not isinstance(companies, list) or not companies:
            raise EngineError("COMPANY_SCOPE_REQUIRED", "必须明确公司数据范围，不允许隐式全量查询")
        companies = sorted({str(item) for item in companies})
        self._authorize(actor_id, "data.aggregate", companies, trace_id)

        records = self._select_records(metric_id, filters, companies)
        self._audit(trace_id, "L1", "1.7 数据模块适配器", "read_fixed_table", actor_id, "completed", {"metric_id": metric_id, "record_count": len(records), "company_scope": companies})
        if not records:
            raise EngineError("DATA_NOT_FOUND", "授权范围内没有符合条件的数据", 404)

        result_rows = self._aggregate_records(records, dimensions, metric)
        verification = self._verify_results(records, result_rows)
        if not verification["passed"]:
            raise EngineError("RESULT_VERIFICATION_FAILED", "汇总结果反向核验未通过", 500)

        destination = str(payload.get("result_destination") or "inline")
        result_file = None
        if destination == "csv":
            self._authorize(actor_id, "result.export", companies, trace_id)
            result_file = self._write_csv(trace_id, dimensions, result_rows)
        elif destination != "inline":
            raise EngineError("DESTINATION_NOT_SUPPORTED", "首版只支持 inline 或 csv 结果去向")

        result_hash = stable_hash({"metric_id": metric_id, "dimensions": dimensions, "rows": result_rows})
        for row in result_rows:
            self.conn.execute(
                """INSERT INTO aggregate_rows
                   (trace_id, dimensions_json, value_minor, value_display, source_count, source_refs_json)
                   VALUES (?,?,?,?,?,?)""",
                (trace_id, canonical_json(row["dimensions"]), row["value_minor"], row["value"], row["source_count"], canonical_json(row["source_refs"])),
            )
        period_label = filters.get("period_from") or filters.get("period_to") or "指定期间"
        source_refs = [record["source_ref"] for record in records]
        dataset = self.data_module.store_dataset(
            trace_id=trace_id,
            request_id=request_id,
            actor_id=actor_id,
            dataset_name=f"{period_label} {metric['metric_name']}归集结果",
            metric={
                "metric_id": metric_id,
                "metric_name": metric["metric_name"],
                "unit": metric["unit"],
                "scale": int(metric["scale"]),
            },
            dimensions=dimensions,
            rows=result_rows,
            source_refs=source_refs,
            verification=verification,
            result_hash=result_hash,
        )
        memory_candidate = self.memory_module.create_candidate(
            trace_id=trace_id,
            actor_id=actor_id,
            content={
                "preferred_metric_id": metric_id,
                "preferred_dimensions": dimensions,
                "preferred_result_destination": destination,
            },
            dataset_ref=dataset["dataset_ref"],
            result_hash=result_hash,
        )
        self._audit(trace_id, "L2", "数据归集聚合引擎", "deterministic_aggregate", actor_id, "completed", {"groups": len(result_rows), "source_records": len(records), "result_hash": result_hash})
        self._audit(trace_id, "L2", "结果核验与来源标注程序", "reverse_verify", actor_id, "passed", verification)
        self._audit(trace_id, "L1", "1.7 数据模块本地适配器", "store_dataset", actor_id, "completed", {"dataset_ref": dataset["dataset_ref"], "storage_uri": dataset["storage_uri"], "row_count": dataset["row_count"]})
        self._audit(trace_id, "L1", "1.15 记忆管理本地适配器", "create_memory_candidate", actor_id, "pending", {"candidate_id": memory_candidate["candidate_id"], "dataset_ref": dataset["dataset_ref"], "contains_business_values": False})

        return {
            "reply_type": "immediate_result",
            "request_id": request_id,
            "trace_id": trace_id,
            "status": "completed",
            "data": {
                "metric": {"metric_id": metric_id, "metric_name": metric["metric_name"], "unit": metric["unit"], "scale": metric["scale"]},
                "dimensions": dimensions,
                "rows": result_rows,
                "result_destination": destination,
                "result_file": result_file,
                "dataset": dataset,
                "source_records": [
                    {
                        "source_ref": record["source_ref"],
                        "company_code": record["company_code"],
                        "company_name": record["company_name"],
                        "period": record["period"],
                        "department": record["department"],
                        "product": record["product"],
                        "value": self._display_minor(int(record["value_minor"]), int(metric["scale"])),
                        "unit": record["unit"],
                    }
                    for record in records
                ],
            },
            "verification": verification,
            "memory": {
                "candidate": memory_candidate,
                "notice": "只生成待确认的聚合偏好候选；未保存业务数值、源记录或权限副本。",
            },
            "evidence": {
                "source_record_count": len(records),
                "lineage_coverage": 1.0,
                "result_hash": result_hash,
                "calculation_owner": "固定确定性程序（非大模型）",
                "l1_adapter_notice": "SQLite 本地测试适配器；未宣称接入真实 L1 服务",
            },
        }

    def _select_records(self, metric_id: str, filters: dict[str, Any], companies: list[str]) -> list[sqlite3.Row]:
        clauses = ["metric_id=?", "state='active'"]
        params: list[Any] = [metric_id]
        placeholders = ",".join("?" for _ in companies)
        clauses.append(f"company_code IN ({placeholders})")
        params.extend(companies)
        for key, operator in (("period_from", ">="), ("period_to", "<=")):
            value = filters.get(key)
            if value:
                if not PERIOD_RE.match(str(value)):
                    raise EngineError("INVALID_PERIOD_FILTER", f"{key} 必须为 YYYY-MM")
                clauses.append(f"period {operator} ?")
                params.append(str(value))
        for filter_key, column in (("departments", "department"), ("products", "product")):
            values = filters.get(filter_key)
            if values:
                if not isinstance(values, list):
                    raise EngineError("INVALID_FILTER", f"{filter_key} 必须为数组")
                marks = ",".join("?" for _ in values)
                clauses.append(f"{column} IN ({marks})")
                params.extend(str(v) for v in values)
        sql = "SELECT * FROM fact_records WHERE " + " AND ".join(clauses) + " ORDER BY source_ref"
        return list(self.conn.execute(sql, params).fetchall())

    def _aggregate_records(self, records: list[sqlite3.Row], dimensions: list[str], metric: sqlite3.Row) -> list[dict[str, Any]]:
        groups: dict[tuple[Any, ...], list[sqlite3.Row]] = defaultdict(list)
        for record in records:
            groups[tuple(record[DIMENSION_COLUMNS[d]] for d in dimensions)].append(record)
        scale = int(metric["scale"])
        rows: list[dict[str, Any]] = []
        for key in sorted(groups, key=lambda item: tuple(str(v) for v in item)):
            members = groups[key]
            value_minor = sum(int(row["value_minor"]) for row in members)
            rows.append(
                {
                    "dimensions": dict(zip(dimensions, key)),
                    "value_minor": value_minor,
                    "value": self._display_minor(value_minor, scale),
                    "unit": metric["unit"],
                    "source_count": len(members),
                    "source_refs": [row["source_ref"] for row in members],
                }
            )
        return rows

    @staticmethod
    def _display_minor(value_minor: int, scale: int) -> str:
        if scale == 0:
            return str(value_minor)
        sign = "-" if value_minor < 0 else ""
        digits = str(abs(value_minor)).rjust(scale + 1, "0")
        return f"{sign}{digits[:-scale]}.{digits[-scale:]}"

    @staticmethod
    def _verify_results(records: list[sqlite3.Row], rows: list[dict[str, Any]]) -> dict[str, Any]:
        source_total = sum(int(record["value_minor"]) for record in records)
        result_total = sum(int(row["value_minor"]) for row in rows)
        source_refs = {record["source_ref"] for record in records}
        lineage_refs = {ref for row in rows for ref in row["source_refs"]}
        passed = source_total == result_total and source_refs == lineage_refs
        return {
            "passed": passed,
            "source_total_minor": source_total,
            "result_total_minor": result_total,
            "source_record_count": len(source_refs),
            "lineage_record_count": len(lineage_refs),
            "method": "源记录整数最小单位求和与分组结果反向对账",
        }

    def _write_csv(self, trace_id: str, dimensions: list[str], rows: list[dict[str, Any]]) -> str:
        path = self.export_dir / f"{trace_id}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([*dimensions, "value", "unit", "source_count", "source_refs"])
            for row in rows:
                writer.writerow([*(row["dimensions"][d] for d in dimensions), row["value"], row["unit"], row["source_count"], " | ".join(row["source_refs"])])
        return str(path)

    def _rejected_response(
        self,
        trace_id: str,
        request_id: str,
        actor_id: str,
        error: EngineError,
    ) -> dict[str, Any]:
        response = {
            "reply_type": "rejected",
            "request_id": request_id,
            "trace_id": trace_id,
            "status": "rejected",
            "reason_code": error.code,
            "message": error.message,
        }
        self.conn.execute(
            """UPDATE tasks SET status='rejected', reason_code=?, response_json=?, finished_at=?
               WHERE trace_id=?""",
            (error.code, canonical_json(response), now_iso(), trace_id),
        )
        self._audit(trace_id, "L2", "L2 层接口·请求发起端", "return_standard_reply", actor_id or None, "rejected", {"reply_type": "rejected", "reason_code": error.code})
        return response

    def audits(self, trace_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if trace_id:
            rows = self.conn.execute(
                "SELECT * FROM audit_events WHERE trace_id=? ORDER BY id", (trace_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "trace_id": row["trace_id"],
                "layer": row["layer"],
                "component": row["component"],
                "action": row["action"],
                "actor_id": row["actor_id"],
                "status": row["status"],
                "detail": json.loads(row["detail_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def task_detail(self, trace_id: str, actor_id: str) -> dict[str, Any]:
        task = self.conn.execute("SELECT * FROM tasks WHERE trace_id=?", (trace_id,)).fetchone()
        if task is None:
            raise EngineError("TASK_NOT_FOUND", "任务不存在", 404)
        if task["actor_id"] != actor_id:
            raise EngineError("TASK_NOT_VISIBLE", "当前真人不能查看其他人的任务", 403)
        try:
            dataset = self.data_module.get_by_trace(trace_id, actor_id)
            memory_candidate = self.memory_module.get_candidate_by_trace(trace_id, actor_id)
        except PermissionError:
            raise EngineError("TASK_NOT_VISIBLE", "当前真人不能查看其他人的任务", 403)
        return {
            "task": {
                "request_id": task["request_id"],
                "trace_id": task["trace_id"],
                "actor_id": task["actor_id"],
                "request_type": task["request_type"],
                "status": task["status"],
                "reason_code": task["reason_code"],
                "result_hash": task["result_hash"],
                "created_at": task["created_at"],
                "finished_at": task["finished_at"],
            },
            "request": json.loads(task["request_json"]),
            "response": json.loads(task["response_json"]) if task["response_json"] else None,
            "dataset": dataset,
            "memory_candidate": memory_candidate,
            "audits": self.audits(trace_id),
        }

    def list_datasets(self, actor_id: str) -> list[dict[str, Any]]:
        self._validate_active_actor_for_read(actor_id)
        return self.data_module.list_datasets(actor_id)

    def dataset_detail(self, dataset_ref: str, actor_id: str) -> dict[str, Any]:
        self._validate_active_actor_for_read(actor_id)
        try:
            return self.data_module.get_dataset(dataset_ref, actor_id)
        except KeyError:
            raise EngineError("DATASET_NOT_FOUND", "数据集不存在", 404)
        except PermissionError:
            raise EngineError("DATASET_NOT_VISIBLE", "当前真人不能查看其他人的数据集", 403)
        except FileNotFoundError:
            raise EngineError("DATASET_ARTIFACT_MISSING", "数据集登记存在，但结果文件缺失", 500)

    def list_memory_candidates(self, actor_id: str) -> list[dict[str, Any]]:
        self._validate_active_actor_for_read(actor_id)
        return self.memory_module.list_candidates(actor_id)

    def list_memories(self, actor_id: str) -> list[dict[str, Any]]:
        self._validate_active_actor_for_read(actor_id)
        return self.memory_module.list_memories(actor_id)

    def decide_memory_candidate(self, candidate_id: str, actor_id: str, decision: str) -> dict[str, Any]:
        self._validate_active_actor_for_read(actor_id)
        with self._lock, self.conn:
            try:
                result = self.memory_module.decide(candidate_id, actor_id, decision)
            except KeyError:
                raise EngineError("MEMORY_CANDIDATE_NOT_FOUND", "记忆候选不存在", 404)
            except PermissionError:
                raise EngineError("MEMORY_CANDIDATE_NOT_VISIBLE", "当前真人不能处理其他人的记忆候选", 403)
            except ValueError as exc:
                code = str(exc)
                if code == "memory_decision_invalid":
                    raise EngineError("MEMORY_DECISION_INVALID", "记忆决定只能是 confirmed 或 rejected")
                raise EngineError("MEMORY_CANDIDATE_ALREADY_DECIDED", "该记忆候选已经处理，不能改变决定", 409)
            candidate = result["candidate"]
            self._audit(
                candidate["trace_id"],
                "L1",
                "1.15 记忆管理本地适配器",
                "decide_memory_candidate",
                actor_id,
                candidate["status"],
                {
                    "candidate_id": candidate_id,
                    "memory_ref": result["memory"]["memory_ref"] if result["memory"] else None,
                    "contains_business_values": False,
                },
            )
            return result

    def _validate_active_actor_for_read(self, actor_id: str) -> None:
        if not actor_id:
            raise EngineError("ACTOR_REQUIRED", "必须携带当前操作真人编号")
        row = self.conn.execute(
            "SELECT active, valid_from, valid_until FROM actors WHERE actor_id=?", (actor_id,)
        ).fetchone()
        current = now_iso()
        if row is None or not row["active"] or not (row["valid_from"] <= current <= row["valid_until"]):
            raise EngineError("ACTOR_INACTIVE", "当前真人不存在、停用或不在有效期", 403)

    def state(self, actor_id: str | None = None) -> dict[str, Any]:
        actor_scope: list[str] | None = None
        if actor_id:
            actor_row = self.conn.execute(
                "SELECT allowed_companies_json FROM actors WHERE actor_id=?", (actor_id,)
            ).fetchone()
            actor_scope = json.loads(actor_row["allowed_companies_json"]) if actor_row else []

        counts = {}
        for key, table in (
            ("fact_records", "fact_records"),
            ("rejected_records", "rejected_records"),
            ("tasks", "tasks"),
            ("audit_events", "audit_events"),
            ("datasets", "datasets"),
            ("memory_candidates", "memory_candidates"),
            ("memories", "memories"),
        ):
            counts[key] = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if actor_id:
            if actor_scope:
                marks = ",".join("?" for _ in actor_scope)
                counts["fact_records"] = self.conn.execute(
                    f"SELECT COUNT(*) FROM fact_records WHERE company_code IN ({marks})", actor_scope
                ).fetchone()[0]
            else:
                counts["fact_records"] = 0
            counts["rejected_records"] = counts["rejected_records"] if actor_id == "manager_all" else 0
            counts["tasks"] = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE actor_id=?", (actor_id,)
            ).fetchone()[0]
            counts["audit_events"] = self.conn.execute(
                "SELECT COUNT(*) FROM audit_events WHERE trace_id IN (SELECT trace_id FROM tasks WHERE actor_id=?)",
                (actor_id,),
            ).fetchone()[0]
            counts["datasets"] = self.conn.execute(
                "SELECT COUNT(*) FROM datasets WHERE owner_actor_id=?", (actor_id,)
            ).fetchone()[0]
            counts["memory_candidates"] = self.conn.execute(
                "SELECT COUNT(*) FROM memory_candidates WHERE actor_id=?", (actor_id,)
            ).fetchone()[0]
            counts["memories"] = self.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE actor_id=?", (actor_id,)
            ).fetchone()[0]
        metrics = [dict(row) for row in self.conn.execute("SELECT metric_id, metric_name, unit, scale, state, owner FROM metric_definitions ORDER BY metric_id")]
        actors = []
        for row in self.conn.execute("SELECT actor_id, actor_name, position_name, active, allowed_companies_json FROM actors WHERE actor_id != 'system_bootstrap' ORDER BY actor_id"):
            actors.append({
                "actor_id": row["actor_id"],
                "actor_name": row["actor_name"],
                "position_name": row["position_name"],
                "active": bool(row["active"]),
                "allowed_companies": json.loads(row["allowed_companies_json"]),
            })
        rejects = [
            dict(row)
            for row in self.conn.execute(
                "SELECT source_system, source_record_id, reason_code, reason_message, rejected_at FROM rejected_records ORDER BY id DESC LIMIT 20"
            )
        ] if not actor_id or actor_id == "manager_all" else []
        task_where = "WHERE actor_id=?" if actor_id else ""
        task_params: tuple[Any, ...] = (actor_id,) if actor_id else ()
        recent_tasks = [
            dict(row)
            for row in self.conn.execute(
                f"SELECT request_id, trace_id, actor_id, status, reason_code, result_hash, created_at, finished_at FROM tasks {task_where} ORDER BY id DESC LIMIT 20",
                task_params,
            )
        ]
        if actor_scope is None:
            source_rows = self.conn.execute(
                "SELECT source_system, metric_id, COUNT(*) AS record_count, SUM(value_minor) AS total_minor FROM fact_records GROUP BY source_system, metric_id ORDER BY source_system, metric_id"
            )
        elif actor_scope:
            marks = ",".join("?" for _ in actor_scope)
            source_rows = self.conn.execute(
                f"SELECT source_system, metric_id, COUNT(*) AS record_count, SUM(value_minor) AS total_minor FROM fact_records WHERE company_code IN ({marks}) GROUP BY source_system, metric_id ORDER BY source_system, metric_id",
                actor_scope,
            )
        else:
            source_rows = []
        source_breakdown = [dict(row) for row in source_rows]
        code_mappings = [
            dict(row)
            for row in self.conn.execute(
                "SELECT domain, source_system, source_code, unified_code, unified_name, state FROM code_mappings ORDER BY unified_code, source_system"
            )
        ]
        parse_where = "WHERE actor_id=?" if actor_id else ""
        parse_params: tuple[Any, ...] = (actor_id,) if actor_id else ()
        recent_interpretations = [
            dict(row)
            for row in self.conn.execute(
                f"SELECT parse_id, actor_id, request_text, status, reason_code, created_at, executed_trace_id FROM l4_interpretations {parse_where} ORDER BY created_at DESC LIMIT 20",
                parse_params,
            )
        ]
        return {
            "engine": "2.4 数据归集聚合引擎",
            "version": "0.3.0-demo",
            "architecture": "L4自然语言请求 -> 可解释解析与人工确认 -> L2层接口 -> 数据归集聚合引擎 -> L1.7数据集适配器 + L1.15记忆候选适配器",
            "counts": counts,
            "metrics": metrics,
            "actors": actors,
            "quality_rejects": rejects,
            "recent_tasks": recent_tasks,
            "recent_interpretations": recent_interpretations,
            "recent_datasets": self.data_module.list_datasets(actor_id) if actor_id else [],
            "memory_candidates": self.memory_module.list_candidates(actor_id) if actor_id else [],
            "memories": self.memory_module.list_memories(actor_id) if actor_id else [],
            "source_breakdown": source_breakdown,
            "code_mappings": code_mappings,
            "boundaries": [
                "L4 自然语言由限定领域的可解释本地解析器转成格式化请求；尚未接入真实大模型与意图分析引擎",
                "SQLite 是 L1 1.7 的本地测试适配器，不代表真实平台已对接",
                "归集结果登记为 dataset_ref；L1.15 只保存经真人确认的偏好，不保存业务数值和源记录",
                "全部测试数据为虚构数据",
                "数字由固定程序计算，大模型不参与算术",
            ],
        }
