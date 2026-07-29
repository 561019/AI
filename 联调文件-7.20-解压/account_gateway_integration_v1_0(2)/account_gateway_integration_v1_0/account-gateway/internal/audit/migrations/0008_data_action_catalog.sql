CREATE TABLE IF NOT EXISTS data_actions (
    action TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'normal',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_data_actions_enabled
ON data_actions (enabled, risk_level);

INSERT OR IGNORE INTO data_actions (action, description, risk_level, enabled, created_by, created_at) VALUES
('create', '创建数据记录', 'normal', 1, 'system', '2026-07-10T00:00:00Z'),
('read', '读取数据', 'normal', 1, 'system', '2026-07-10T00:00:00Z'),
('fetch', '取用数据', 'normal', 1, 'system', '2026-07-10T00:00:00Z'),
('use', '使用数据', 'normal', 1, 'system', '2026-07-10T00:00:00Z'),
('store', '存入数据', 'normal', 1, 'system', '2026-07-10T00:00:00Z'),
('update', '修改数据', 'normal', 1, 'system', '2026-07-10T00:00:00Z'),
('delete', '删除数据', 'high', 1, 'system', '2026-07-10T00:00:00Z'),
('approve', '批准数据放行', 'high', 1, 'system', '2026-07-10T00:00:00Z'),
('delegate', '转授数据权限', 'high', 1, 'system', '2026-07-10T00:00:00Z'),
('export', '外发或导出数据', 'high', 1, 'system', '2026-07-10T00:00:00Z'),
('disable', '禁用数据', 'high', 1, 'system', '2026-07-10T00:00:00Z'),
('freeze', '临时冻结数据', 'high', 1, 'system', '2026-07-10T00:00:00Z'),
('unfreeze', '解冻数据', 'high', 1, 'system', '2026-07-10T00:00:00Z');
