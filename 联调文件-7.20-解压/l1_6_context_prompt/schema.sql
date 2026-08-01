CREATE TABLE IF NOT EXISTS context_memory (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  scope_level TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  context_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  content TEXT,
  content_ref TEXT,
  memory_engine_ref TEXT,
  source_type TEXT,
  source_id TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_memory_scope
  ON context_memory(scope_level, scope_id, status);

CREATE INDEX IF NOT EXISTS idx_context_memory_type
  ON context_memory(context_type, status);

CREATE TABLE IF NOT EXISTS prompt_template (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  prompt_code TEXT NOT NULL,
  scope_level TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  active_version_id TEXT,
  owner_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(prompt_code, scope_level, scope_id)
);

CREATE TABLE IF NOT EXISTS prompt_version (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  version_no INTEGER NOT NULL,
  content TEXT NOT NULL,
  variables_schema TEXT,
  change_note TEXT,
  env TEXT NOT NULL DEFAULT 'test',
  status TEXT NOT NULL DEFAULT 'draft',
  created_by TEXT NOT NULL,
  published_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(template_id) REFERENCES prompt_template(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_version_no
  ON prompt_version(template_id, version_no);

CREATE TABLE IF NOT EXISTS prompt_platform_binding (
  id TEXT PRIMARY KEY,
  prompt_version_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  platform_prompt_id TEXT,
  platform_prompt_name TEXT,
  platform_version TEXT,
  platform_url TEXT,
  sync_status TEXT NOT NULL DEFAULT 'local_only',
  metadata TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(prompt_version_id) REFERENCES prompt_version(id)
);

CREATE INDEX IF NOT EXISTS idx_prompt_platform_binding_version
  ON prompt_platform_binding(prompt_version_id, platform);

CREATE TABLE IF NOT EXISTS prompt_run_trace (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL DEFAULT 'langfuse',
  platform_trace_id TEXT,
  prompt_version_id TEXT,
  project_id TEXT,
  session_id TEXT,
  operation TEXT NOT NULL,
  input_json TEXT,
  output_text TEXT,
  status TEXT NOT NULL DEFAULT 'success',
  score REAL,
  score_reason TEXT,
  latency_ms INTEGER,
  total_tokens INTEGER,
  cost_amount REAL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(prompt_version_id) REFERENCES prompt_version(id),
  FOREIGN KEY(session_id) REFERENCES conversation_session(id)
);

CREATE INDEX IF NOT EXISTS idx_prompt_run_trace_scope
  ON prompt_run_trace(project_id, session_id, operation, created_at);

CREATE TABLE IF NOT EXISTS audit_event (
  id TEXT PRIMARY KEY,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT,
  scope_level TEXT,
  scope_id TEXT,
  permission_result TEXT NOT NULL,
  trace_id TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_session (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  capacity_limit INTEGER NOT NULL,
  used_units INTEGER NOT NULL DEFAULT 0,
  capacity_ratio REAL NOT NULL DEFAULT 0,
  auto_handoff_done INTEGER NOT NULL DEFAULT 0,
  locked INTEGER NOT NULL DEFAULT 0,
  next_session_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  summary TEXT,
  open_todos TEXT,
  decisions TEXT,
  risks TEXT,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_session_project
  ON conversation_session(project_id, status);

CREATE TABLE IF NOT EXISTS conversation_message (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  token_estimate INTEGER NOT NULL DEFAULT 0,
  model_provider TEXT,
  model_name TEXT,
  trace_id TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_session(id),
  FOREIGN KEY(trace_id) REFERENCES prompt_run_trace(id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_message_session
  ON conversation_message(session_id, created_at);

CREATE TABLE IF NOT EXISTS handoff_run (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  old_session_id TEXT NOT NULL,
  new_session_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'started',
  user_message_id TEXT,
  assistant_message_id TEXT,
  trace_id TEXT,
  work_report_id TEXT,
  handoff_file_id TEXT,
  sync_package_id TEXT,
  user_text TEXT NOT NULL,
  assistant_text TEXT,
  llm_meta TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(old_session_id) REFERENCES conversation_session(id),
  FOREIGN KEY(new_session_id) REFERENCES conversation_session(id),
  FOREIGN KEY(user_message_id) REFERENCES conversation_message(id),
  FOREIGN KEY(assistant_message_id) REFERENCES conversation_message(id),
  FOREIGN KEY(trace_id) REFERENCES prompt_run_trace(id),
  FOREIGN KEY(work_report_id) REFERENCES work_report(id),
  FOREIGN KEY(handoff_file_id) REFERENCES handoff_package(id),
  FOREIGN KEY(sync_package_id) REFERENCES sync_package(id)
);

CREATE INDEX IF NOT EXISTS idx_handoff_run_old_session
  ON handoff_run(old_session_id, created_at);

CREATE TABLE IF NOT EXISTS capacity_event (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  capacity_ratio REAL NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_session(id)
);

CREATE INDEX IF NOT EXISTS idx_capacity_event_session
  ON capacity_event(session_id, created_at);

CREATE TABLE IF NOT EXISTS context_compaction (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  strategy TEXT NOT NULL,
  tokens_before INTEGER NOT NULL,
  tokens_after INTEGER NOT NULL,
  messages_before INTEGER NOT NULL DEFAULT 0,
  messages_after INTEGER NOT NULL DEFAULT 0,
  summary TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_session(id)
);

CREATE INDEX IF NOT EXISTS idx_context_compaction_session
  ON context_compaction(session_id, created_at);

CREATE TABLE IF NOT EXISTS artifact_file (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  project_id TEXT NOT NULL,
  session_id TEXT,
  artifact_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  storage_ref TEXT NOT NULL,
  download_ref TEXT,
  content TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_session(id)
);

CREATE INDEX IF NOT EXISTS idx_artifact_file_project
  ON artifact_file(project_id, artifact_type, created_at);

CREATE TABLE IF NOT EXISTS work_report (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  prompt_version_id TEXT,
  artifact_file_id TEXT,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'generated',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_session(id),
  FOREIGN KEY(artifact_file_id) REFERENCES artifact_file(id)
);

CREATE TABLE IF NOT EXISTS handoff_package (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  prompt_version_id TEXT,
  artifact_file_id TEXT,
  package_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'generated',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_session(id),
  FOREIGN KEY(artifact_file_id) REFERENCES artifact_file(id)
);

CREATE TABLE IF NOT EXISTS sync_package (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  version_no INTEGER NOT NULL,
  package_type TEXT NOT NULL DEFAULT 'project_master',
  source_work_report_id TEXT,
  source_session_id TEXT,
  prompt_version_id TEXT,
  prompt_source TEXT NOT NULL,
  prompt_name TEXT NOT NULL,
  prompt_label TEXT,
  prompt_platform_version TEXT,
  langfuse_prompt_id TEXT,
  trace_id TEXT,
  artifact_file_id TEXT,
  content TEXT NOT NULL,
  structured_json TEXT,
  session_index TEXT,
  file_index TEXT,
  topic_index TEXT,
  pending_tasks TEXT,
  next_actions TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(source_work_report_id) REFERENCES work_report(id),
  FOREIGN KEY(source_session_id) REFERENCES conversation_session(id),
  FOREIGN KEY(trace_id) REFERENCES prompt_run_trace(id),
  FOREIGN KEY(artifact_file_id) REFERENCES artifact_file(id)
);

CREATE INDEX IF NOT EXISTS idx_sync_package_project_latest
  ON sync_package(project_id, created_at);

CREATE TABLE IF NOT EXISTS cross_project_reference (
  id TEXT PRIMARY KEY,
  target_project_id TEXT NOT NULL,
  source_project_id TEXT NOT NULL,
  source_session_id TEXT,
  source_record_type TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_excerpt TEXT NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cross_project_reference_target
  ON cross_project_reference(target_project_id, status, created_at);

CREATE TABLE IF NOT EXISTS control_center_message (
  id TEXT PRIMARY KEY,
  scope_level TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  meta TEXT,
  result_json TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_control_center_message_scope
  ON control_center_message(scope_level, scope_id, status, created_at);
