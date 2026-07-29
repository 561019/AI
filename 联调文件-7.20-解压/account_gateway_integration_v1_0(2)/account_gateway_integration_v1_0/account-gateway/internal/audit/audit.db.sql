CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    policy_decision TEXT NOT NULL,
    policy_id TEXT,
    context_snapshot TEXT NOT NULL,
    version INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS audit_logs_no_update
BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is append-only: update rejected');
END;

CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete
BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is append-only: delete rejected');
END;

CREATE TABLE IF NOT EXISTS runtime_policies (
    policy_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    object TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    action TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'allow',
    owner_user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT '*',
    approval_id INTEGER,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_policies_approval_id
ON runtime_policies (approval_id);

CREATE INDEX IF NOT EXISTS idx_runtime_policies_tenant_id
ON runtime_policies (tenant_id);
