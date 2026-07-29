CREATE TABLE IF NOT EXISTS data_records (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    owner_person_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    business_tags TEXT NOT NULL DEFAULT '[]',
    storage_refs TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    allowed_actions TEXT NOT NULL DEFAULT '["read","fetch","store","update"]',
    basis TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_data_records_owner
ON data_records (owner_person_id, owner_user_id, tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_data_records_tenant
ON data_records (tenant_id, status);
