CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'personal_position',
    status TEXT NOT NULL DEFAULT 'active',
    owner_person_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    owner_position_id TEXT NOT NULL,
    department_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resources_type_id
ON resources (resource_type, id);

CREATE INDEX IF NOT EXISTS idx_resources_scope
ON resources (level, department_id, tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_resources_owner
ON resources (owner_person_id, owner_position_id, owner_user_id, status);

CREATE TABLE IF NOT EXISTS resource_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id TEXT NOT NULL,
    target_level TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    FOREIGN KEY (resource_id) REFERENCES resources(id)
);

CREATE INDEX IF NOT EXISTS idx_resource_publications_status
ON resource_publications (status, resource_id);

CREATE INDEX IF NOT EXISTS idx_resource_publications_resource
ON resource_publications (resource_id);
