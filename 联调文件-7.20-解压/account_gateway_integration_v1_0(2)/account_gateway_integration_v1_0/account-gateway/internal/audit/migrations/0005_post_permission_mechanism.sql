CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    department_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS person_position_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    assigned_by TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    ended_by TEXT,
    ended_at TEXT,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

DROP INDEX IF EXISTS idx_person_position_active_person;

CREATE UNIQUE INDEX IF NOT EXISTS idx_person_position_active_position
ON person_position_assignments (position_id)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_person_position_user_active
ON person_position_assignments (user_id, person_id, tenant_id, status);

CREATE TABLE IF NOT EXISTS domains (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dsm_user_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS person_manager_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,
    manager_person_id TEXT NOT NULL,
    domain_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (domain_id) REFERENCES domains(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_person_manager_active_person
ON person_manager_edges (person_id)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_person_manager_domain
ON person_manager_edges (domain_id, status);

CREATE TABLE IF NOT EXISTS position_standard_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    action TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_position_standard_resource_unique
ON position_standard_resources (position_id, resource_type, resource_id, action, owner_user_id);

CREATE INDEX IF NOT EXISTS idx_position_standard_resource_validate
ON position_standard_resources (position_id, resource_type, resource_id, action);

CREATE TABLE IF NOT EXISTS delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_person_id TEXT NOT NULL,
    to_person_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    action TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    can_redelegate INTEGER NOT NULL DEFAULT 0,
    basis TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_delegations_validate
ON delegations (to_person_id, resource_type, resource_id, action);

CREATE INDEX IF NOT EXISTS idx_delegations_from
ON delegations (from_person_id, resource_type, resource_id, action);
