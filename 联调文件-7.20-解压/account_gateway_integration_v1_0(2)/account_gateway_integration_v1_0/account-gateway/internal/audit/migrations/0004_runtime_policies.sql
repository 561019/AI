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
