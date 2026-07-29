from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS capabilities (
    capability_code TEXT PRIMARY KEY,
    scenario TEXT NOT NULL,
    capability_type TEXT NOT NULL,
    implementation_ref TEXT NOT NULL,
    capability_version TEXT NOT NULL,
    status TEXT NOT NULL,
    owner TEXT NOT NULL,
    required_action TEXT NOT NULL DEFAULT '',
    validation_ref TEXT NOT NULL DEFAULT '',
    input_schema_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rule_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability_code TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    parameter_version TEXT NOT NULL,
    treatment_rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(capability_code, rule_version, parameter_version)
);

CREATE TABLE IF NOT EXISTS receivables (
    receivable_id TEXT PRIMARY KEY,
    data_reference TEXT NOT NULL,
    business_object_id TEXT NOT NULL,
    period TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    amount TEXT NOT NULL,
    age_months INTEGER NOT NULL,
    source_row TEXT NOT NULL,
    source_system TEXT NOT NULL,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS business_datasets (
    data_reference TEXT PRIMARY KEY,
    business_object_id TEXT NOT NULL,
    period TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_description TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_records (
    execution_record_id TEXT PRIMARY KEY,
    parent_execution_record_id TEXT,
    trace_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    claimed_actor_id TEXT,
    operator_id TEXT NOT NULL,
    identity_verification_id TEXT,
    identity_context_digest TEXT NOT NULL,
    scenario TEXT NOT NULL,
    execution_path TEXT,
    state TEXT NOT NULL,
    handling_type TEXT,
    reason_code TEXT,
    versions_json TEXT,
    data_reference TEXT,
    request_data_references_json TEXT NOT NULL DEFAULT '[]',
    request_context_json TEXT NOT NULL DEFAULT '{}',
    input_digest TEXT NOT NULL,
    result_json TEXT,
    existing_system_reference_json TEXT,
    candidate_asset_reference_json TEXT,
    sandbox_execution_reference_json TEXT,
    model_analysis_json TEXT,
    routing_decision_json TEXT,
    validation_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_handling_records (
    handling_record_id TEXT PRIMARY KEY,
    execution_record_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    handler_id TEXT NOT NULL,
    identity_verification_id TEXT,
    identity_context_digest TEXT NOT NULL,
    action TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_version_governance (
    rule_version_id INTEGER PRIMARY KEY,
    source_basis TEXT NOT NULL,
    review_role TEXT NOT NULL,
    entered_by TEXT NOT NULL,
    tested_by TEXT,
    tested_at TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    effective_at TEXT
);

CREATE TABLE IF NOT EXISTS rule_version_transition_records (
    transition_record_id TEXT PRIMARY KEY,
    rule_version_id INTEGER NOT NULL,
    capability_code TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    caller_service_code TEXT NOT NULL,
    action TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    execution_record_id TEXT,
    reply_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (caller_service_code, action, idempotency_key)
);
"""


BAD_DEBT_RULE = {
    "bands": [
        {"label": "0-6 months", "min_months": 0, "max_months": 6, "rate": "0.01"},
        {"label": "6-12 months", "min_months": 6, "max_months": 12, "rate": "0.05"},
        {"label": "1-2 years", "min_months": 12, "max_months": 24, "rate": "0.20"},
        {"label": "2 years and above", "min_months": 24, "max_months": None, "rate": "0.50"},
    ],
    "treatment_rule": {
        "state": "waiting_human",
        "handling_type": "confirm_effective",
        "reason_code": "KEY_BUSINESS_RESULT",
        "message": "This is a key business result and requires designated human confirmation before taking effect.",
    },
}


ORDER_RANGE_RULE = {
    "product_rules": [
        {"product_type": "standard_a", "min_price": "80", "max_price": "120", "max_quantity": 500},
        {"product_type": "standard_b", "min_price": "150", "max_price": "220", "max_quantity": 300},
        {"product_type": "custom_c", "min_price": "300", "max_price": "520", "max_quantity": 80},
    ],
    "treatment_rule": {
        "default": {
            "state": "automatic_pass",
            "handling_type": None,
            "reason_code": None,
            "message": "All orders are within the published price and quantity ranges.",
        },
        "conditions": [
            {
                "result_field": "requires_handling_count",
                "operator": "gt",
                "value": 0,
                "state": "waiting_human",
                "handling_type": "exception_disposal",
                "reason_code": "ORDER_RANGE_EXCEPTION",
                "message": "The audit completed; orders outside the published range require responsible-person handling.",
            }
        ],
    },
}


POLICY_ALLOWANCE_RULE = {
    "rule_schema_version": "1.0",
    "parameter_tables": {
        "grade_rules": [
            {"grade": "grade_a", "daily_rate": "100.00", "max_eligible_days": 31},
            {"grade": "grade_b", "daily_rate": "80.00", "max_eligible_days": 31},
        ]
    },
    "operations": {
        "lookups": [
            {
                "name": "grade_rule",
                "type": "exact",
                "table": "grade_rules",
                "input_field": "grade",
                "match_field": "grade",
                "missing_reason_code": "GRADE_RULE_NOT_FOUND",
            }
        ],
        "formulas": [
            {
                "name": "allowance_amount",
                "operator": "multiply",
                "operands": [
                    {"field": "eligible_days"},
                    {"lookup": "daily_rate", "from": "grade_rule"},
                ],
                "scale": 2,
            }
        ],
        "conditions": [
            {
                "name": "eligible_days_limit",
                "left": {"field": "eligible_days"},
                "operator": "lte",
                "right": {"lookup": "max_eligible_days", "from": "grade_rule"},
                "reason_code": "MAX_ELIGIBLE_DAYS_EXCEEDED",
            }
        ],
        "line_outputs": {
            "employee_id": {"field": "employee_id"},
            "grade": {"field": "grade"},
            "eligible_days": {"field": "eligible_days"},
            "daily_rate": {"lookup": "daily_rate", "from": "grade_rule"},
            "allowance_amount": {"formula": "allowance_amount"},
            "matched_rule": {"lookup_record": "grade_rule"},
            "source_row": {"field": "source_row"},
        },
        "aggregates": [
            {
                "name": "total_allowance",
                "operator": "sum",
                "source_output": "allowance_amount",
                "include_when_decision": "passed",
                "scale": 2,
            }
        ],
    },
    "treatment_rule": {
        "default": {
            "state": "automatic_pass",
            "handling_type": None,
            "reason_code": None,
            "message": "The allowance calculation completed under the published rule version.",
        },
        "conditions": [
            {
                "result_field": "requires_handling_count",
                "operator": "gt",
                "value": 0,
                "state": "waiting_human",
                "handling_type": "exception_disposal",
                "reason_code": "ALLOWANCE_RULE_EXCEPTION",
                "message": "The calculation completed; rows outside the published conditions require responsible-person handling.",
            }
        ],
    },
}


EXTERNAL_PAYROLL_CALL_CONFIG = {
    "invocation": {
        "contract_version": "1.0",
        "authoritative_result_source": "finance-system",
    },
    "treatment_rule": {
        "state": "automatic_pass",
        "handling_type": None,
        "reason_code": None,
        "message": "The authoritative payroll result was returned and validated.",
    },
}


SEED_RECEIVABLES = [
    ("AR-001", "DS-RECEIVABLES-2026Q2", "ORG-001", "2026-Q2", "Customer A", "120000.00", 3, "receivables-1", "platform-test-data", "2026-07-15T00:00:00Z"),
    ("AR-002", "DS-RECEIVABLES-2026Q2", "ORG-001", "2026-Q2", "Customer B", "80000.00", 8, "receivables-2", "platform-test-data", "2026-07-15T00:00:00Z"),
    ("AR-003", "DS-RECEIVABLES-2026Q2", "ORG-001", "2026-Q2", "Customer C", "60000.00", 15, "receivables-3", "platform-test-data", "2026-07-15T00:00:00Z"),
    ("AR-004", "DS-RECEIVABLES-2026Q2", "ORG-001", "2026-Q2", "Customer D", "40000.00", 30, "receivables-4", "platform-test-data", "2026-07-15T00:00:00Z"),
]


SEED_ORDERS = [
    {"order_id": "ORD-001", "product_type": "standard_a", "unit_price": "100", "quantity": 200, "source_row": "orders-1"},
    {"order_id": "ORD-002", "product_type": "standard_b", "unit_price": "180", "quantity": 250, "source_row": "orders-2"},
    {"order_id": "ORD-003", "product_type": "standard_a", "unit_price": "130", "quantity": 100, "source_row": "orders-3"},
    {"order_id": "ORD-004", "product_type": "unregistered_d", "unit_price": "90", "quantity": 20, "source_row": "orders-4"},
]


SEED_MARGIN_ANALYSIS = [
    {
        "baseline_revenue": "500000.00",
        "revenue_change_rate": "0.026",
        "baseline_margin": "0.300000",
        "adjusted_margin": "0.281247563",
        "source_row": "margin-scenario-1",
    }
]


SEED_POLICY_ALLOWANCE = [
    {
        "employee_id": "EMP-ALLOW-001",
        "grade": "grade_a",
        "eligible_days": 20,
        "source_row": "allowance-1",
    },
    {
        "employee_id": "EMP-ALLOW-002",
        "grade": "grade_b",
        "eligible_days": 15,
        "source_row": "allowance-2",
    },
    {
        "employee_id": "EMP-ALLOW-003",
        "grade": "grade_a",
        "eligible_days": 32,
        "source_row": "allowance-3",
    },
]


@contextmanager
def connect(database_path: Path) -> Iterator[sqlite3.Connection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.executescript(SCHEMA)
        _ensure_column(connection, "execution_records", "identity_verification_id", "TEXT")
        _ensure_column(connection, "execution_records", "identity_context_digest", "TEXT")
        _ensure_column(connection, "execution_records", "claimed_actor_id", "TEXT")
        _ensure_column(connection, "human_handling_records", "identity_verification_id", "TEXT")
        _ensure_column(connection, "human_handling_records", "identity_context_digest", "TEXT")
        _ensure_column(connection, "capabilities", "validation_ref", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "capabilities", "input_schema_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(connection, "capabilities", "required_action", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "execution_records", "execution_path", "TEXT")
        _ensure_column(connection, "execution_records", "existing_system_reference_json", "TEXT")
        _ensure_column(connection, "execution_records", "parent_execution_record_id", "TEXT")
        _ensure_column(connection, "execution_records", "request_context_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(connection, "execution_records", "candidate_asset_reference_json", "TEXT")
        _ensure_column(connection, "execution_records", "sandbox_execution_reference_json", "TEXT")
        _ensure_column(connection, "execution_records", "model_analysis_json", "TEXT")
        _ensure_column(connection, "execution_records", "routing_decision_json", "TEXT")
        _ensure_column(connection, "execution_records", "request_data_references_json", "TEXT NOT NULL DEFAULT '[]'")
        connection.execute(
            """UPDATE capabilities SET validation_ref = ?, input_schema_json = ?, required_action = ?
               WHERE capability_code = ? AND validation_ref = ''""",
            (
                "bad_debt_provision_v1",
                json.dumps({"required_fields": ["receivable_id", "amount", "age_months"]}),
                "rule.calculate.bad_debt",
                "CAP-BAD-DEBT-PY",
            ),
        )
        connection.execute(
            "UPDATE capabilities SET required_action = ? WHERE capability_code = ? AND required_action = ''",
            ("rule.calculate.bad_debt", "CAP-BAD-DEBT-PY"),
        )
        connection.execute(
            "UPDATE capabilities SET required_action = ? WHERE capability_code = ? AND required_action = ''",
            ("rule.calculate.order_range", "CAP-ORDER-RANGE-PY"),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO capabilities
            (capability_code, scenario, capability_type, implementation_ref, capability_version,
             status, owner, required_action, validation_ref, input_schema_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "CAP-BAD-DEBT-PY",
                "bad_debt_provision",
                "fixed_python",
                "app.executors.BadDebtProvisionExecutor",
                "1.0.0",
                "published",
                "business-rule-owner",
                "rule.calculate.bad_debt",
                "bad_debt_provision_v1",
                json.dumps({"required_fields": ["receivable_id", "amount", "age_months"]}),
            ),
        )
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO rule_versions
            (capability_code, rule_version, parameter_version, treatment_rule_version, status, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "CAP-BAD-DEBT-PY",
                "RULE-BAD-DEBT-1.0",
                "PARAM-BAD-DEBT-2026Q2-1.0",
                "TREAT-BAD-DEBT-1.0",
                "published",
                json.dumps(BAD_DEBT_RULE),
            ),
        )
        rule_version_id = cursor.lastrowid or connection.execute(
            "SELECT id FROM rule_versions WHERE capability_code = ? AND rule_version = ?",
            ("CAP-BAD-DEBT-PY", "RULE-BAD-DEBT-1.0"),
        ).fetchone()["id"]
        connection.execute(
            """INSERT OR IGNORE INTO rule_version_governance
               (rule_version_id, source_basis, review_role, entered_by, reviewed_by, reviewed_at, effective_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rule_version_id, "Initial approved bad debt provision policy.", "designated_reviewer",
             "dsm_operator", "seed_approval", "2026-07-15T00:00:00Z", "2026-07-15T00:00:00Z"),
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO receivables VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            SEED_RECEIVABLES,
        )
        connection.execute(
            """INSERT OR IGNORE INTO business_datasets
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "DS-RECEIVABLES-2026Q2", "ORG-001", "2026-Q2", "platform-test-data",
                "Receivables detail dataset", json.dumps([
                    {
                        "receivable_id": row[0], "customer_name": row[4], "amount": row[5],
                        "age_months": row[6], "source_row": row[7]
                    }
                    for row in SEED_RECEIVABLES
                ]),
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO capabilities
               (capability_code, scenario, capability_type, implementation_ref, capability_version,
                status, owner, required_action, validation_ref, input_schema_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "CAP-ORDER-RANGE-PY", "order_range_audit", "fixed_python",
                "app.executors.OrderRangeAuditExecutor", "1.0.0", "published",
                "business-rule-owner", "rule.calculate.order_range", "order_range_audit_v1",
                json.dumps({"required_fields": ["order_id", "product_type", "unit_price", "quantity"]}),
            ),
        )
        order_version = connection.execute(
            """INSERT OR IGNORE INTO rule_versions
               (capability_code, rule_version, parameter_version, treatment_rule_version, status, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "CAP-ORDER-RANGE-PY", "RULE-ORDER-RANGE-1.0", "PARAM-ORDER-RANGE-1.0",
                "TREAT-ORDER-RANGE-1.0", "published", json.dumps(ORDER_RANGE_RULE),
            ),
        )
        order_version_id = order_version.lastrowid or connection.execute(
            "SELECT id FROM rule_versions WHERE capability_code = ? AND rule_version = ?",
            ("CAP-ORDER-RANGE-PY", "RULE-ORDER-RANGE-1.0"),
        ).fetchone()["id"]
        connection.execute(
            """INSERT OR IGNORE INTO rule_version_governance
               (rule_version_id, source_basis, review_role, entered_by, reviewed_by, reviewed_at, effective_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (order_version_id, "Approved order price and quantity range policy.", "designated_reviewer",
             "dsm_operator", "seed_approval", "2026-07-15T00:00:00Z", "2026-07-15T00:00:00Z"),
        )
        connection.execute(
            """INSERT OR IGNORE INTO business_datasets VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "DS-ORDERS-2026Q2", "ORG-001", "2026-Q2", "platform-test-data",
                "Order price and quantity test dataset", json.dumps(SEED_ORDERS),
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO business_datasets VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "DS-MARGIN-TEST", "ORG-001", "2026-Q2", "platform-test-data",
                "Temporary margin-analysis test dataset", json.dumps(SEED_MARGIN_ANALYSIS),
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO business_datasets VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "DS-ALLOWANCE-2026-07", "ORG-001", "2026-07", "platform-test-data",
                "Policy allowance declarative-rule test dataset",
                json.dumps(SEED_POLICY_ALLOWANCE),
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO capabilities
               (capability_code, scenario, capability_type, implementation_ref, capability_version,
                status, owner, required_action, validation_ref, input_schema_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "CAP-POLICY-ALLOWANCE-DECL", "policy_allowance_calculation", "declarative_rule",
                "app.executors.DeclarativeRuleExecutor", "1.0.0", "published",
                "business-rule-owner", "rule.calculate.policy_allowance", "declarative_rule_v1",
                json.dumps(
                    {
                        "required_fields": [
                            "employee_id", "grade", "eligible_days", "source_row"
                        ]
                    }
                ),
            ),
        )
        allowance_version = connection.execute(
            """INSERT OR IGNORE INTO rule_versions
               (capability_code, rule_version, parameter_version, treatment_rule_version, status, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "CAP-POLICY-ALLOWANCE-DECL", "RULE-POLICY-ALLOWANCE-1.0",
                "PARAM-POLICY-ALLOWANCE-1.0", "TREAT-POLICY-ALLOWANCE-1.0",
                "published", json.dumps(POLICY_ALLOWANCE_RULE),
            ),
        )
        allowance_version_id = allowance_version.lastrowid or connection.execute(
            "SELECT id FROM rule_versions WHERE capability_code = ? AND rule_version = ?",
            ("CAP-POLICY-ALLOWANCE-DECL", "RULE-POLICY-ALLOWANCE-1.0"),
        ).fetchone()["id"]
        connection.execute(
            """INSERT OR IGNORE INTO rule_version_governance
               (rule_version_id, source_basis, review_role, entered_by, reviewed_by, reviewed_at, effective_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                allowance_version_id,
                "Approved policy allowance lookup, formula, and condition test rule.",
                "designated_reviewer", "dsm_operator", "seed_approval",
                "2026-07-15T00:00:00Z", "2026-07-15T00:00:00Z",
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO capabilities
               (capability_code, scenario, capability_type, implementation_ref, capability_version,
                status, owner, required_action, validation_ref, input_schema_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "CAP-EXTERNAL-PAYROLL", "external_payroll_calculation", "existing_system",
                "finance-system.payroll.calculate", "1.0.0", "published",
                "finance-system-owner", "rule.calculate.external_payroll",
                "external_payroll_result_v1",
                json.dumps({"required_context_fields": ["business_object_id", "period"]}),
            ),
        )
        payroll_version = connection.execute(
            """INSERT OR IGNORE INTO rule_versions
               (capability_code, rule_version, parameter_version, treatment_rule_version, status, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "CAP-EXTERNAL-PAYROLL", "CALL-CONFIG-EXTERNAL-PAYROLL-1.0",
                "PARAM-EXTERNAL-PAYROLL-1.0", "TREAT-EXTERNAL-PAYROLL-1.0",
                "published", json.dumps(EXTERNAL_PAYROLL_CALL_CONFIG),
            ),
        )
        payroll_version_id = payroll_version.lastrowid or connection.execute(
            "SELECT id FROM rule_versions WHERE capability_code = ? AND rule_version = ?",
            ("CAP-EXTERNAL-PAYROLL", "CALL-CONFIG-EXTERNAL-PAYROLL-1.0"),
        ).fetchone()["id"]
        connection.execute(
            """INSERT OR IGNORE INTO rule_version_governance
               (rule_version_id, source_basis, review_role, entered_by, reviewed_by, reviewed_at, effective_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                payroll_version_id,
                "Approved external payroll service registration and result-treatment configuration.",
                "designated_reviewer", "dsm_operator", "seed_approval",
                "2026-07-15T00:00:00Z", "2026-07-15T00:00:00Z",
            ),
        )


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
