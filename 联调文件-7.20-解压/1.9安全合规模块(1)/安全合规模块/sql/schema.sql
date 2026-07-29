CREATE TABLE IF NOT EXISTS security_audit_log (
  audit_id TEXT PRIMARY KEY,
  request_id TEXT,
  trace_id TEXT,
  idempotency_key TEXT,
  callback_url TEXT,
  stage TEXT,
  caller_module TEXT,
  scene_code TEXT,
  account_id TEXT,
  real_person_id TEXT,
  active_position_id TEXT,
  domain_id TEXT,
  agent_id TEXT,
  responsible_person_id TEXT,
  action_type TEXT,
  operation TEXT,
  target_system TEXT,
  decision TEXT,
  code TEXT,
  reason TEXT,
  hit_policy_ids TEXT,
  need_masking INTEGER,
  need_human_confirm INTEGER,
  audit_level TEXT,
  risk_level TEXT,
  input_text TEXT,
  output_text TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_security_audit_trace ON security_audit_log(trace_id);
CREATE INDEX IF NOT EXISTS idx_security_audit_person ON security_audit_log(real_person_id);
CREATE INDEX IF NOT EXISTS idx_security_audit_scene ON security_audit_log(scene_code);

CREATE TABLE IF NOT EXISTS data_access_trace (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id TEXT,
  audit_id TEXT,
  data_id TEXT,
  data_owner_person_id TEXT,
  access_mode TEXT,
  located_success INTEGER,
  permission_checked INTEGER,
  data_released INTEGER,
  masked INTEGER,
  model_scope TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_data_access_trace ON data_access_trace(trace_id);
CREATE INDEX IF NOT EXISTS idx_data_access_data ON data_access_trace(data_id);

CREATE TABLE IF NOT EXISTS emergency_access_log (
  emergency_log_id TEXT PRIMARY KEY,
  audit_id TEXT,
  account_id TEXT,
  operator_person_id TEXT,
  action_type TEXT,
  target_data_id TEXT,
  target_person_id TEXT,
  reason TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS security_idempotency_cache (
  idempotency_key TEXT PRIMARY KEY,
  response_json TEXT NOT NULL,
  created_at TEXT
);


CREATE TABLE IF NOT EXISTS security_trace_span (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT,
  audit_id TEXT,
  parent_span_id TEXT,
  span_type TEXT,
  module TEXT,
  stage TEXT,
  decision TEXT,
  code TEXT,
  latency_ms INTEGER,
  input_json TEXT,
  output_json TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_security_trace_span_trace ON security_trace_span(trace_id);
CREATE INDEX IF NOT EXISTS idx_security_trace_span_audit ON security_trace_span(audit_id);

CREATE TABLE IF NOT EXISTS security_observation (
  observation_id TEXT PRIMARY KEY,
  span_id TEXT,
  trace_id TEXT,
  audit_id TEXT,
  observation_type TEXT,
  name TEXT,
  level TEXT,
  payload_json TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_security_observation_trace ON security_observation(trace_id);

CREATE TABLE IF NOT EXISTS security_rule_change_log (
  change_id TEXT PRIMARY KEY,
  rule_id TEXT,
  action TEXT,
  operator_person_id TEXT,
  reason TEXT,
  before_json TEXT,
  after_json TEXT,
  change_hash TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_rule_change_rule ON security_rule_change_log(rule_id);
