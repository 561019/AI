CREATE TABLE IF NOT EXISTS integration_sync_status (
    tenant_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    synced INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL,
    synced_at TEXT,
    actor_id TEXT NOT NULL,
    source TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_integration_sync_status_status
    ON integration_sync_status (tenant_id, status);
