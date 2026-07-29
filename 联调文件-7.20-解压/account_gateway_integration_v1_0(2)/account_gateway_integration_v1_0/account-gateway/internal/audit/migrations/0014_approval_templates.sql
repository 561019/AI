CREATE TABLE IF NOT EXISTS approval_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    approval_type TEXT NOT NULL,
    approver_position_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approval_templates_tenant_active
    ON approval_templates (tenant_id, active, approval_type);
