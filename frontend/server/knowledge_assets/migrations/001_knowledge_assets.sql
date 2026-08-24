CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_drafts (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  manifest_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS skill_draft_revisions (
  draft_id TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  manifest_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (draft_id, revision),
  FOREIGN KEY (draft_id) REFERENCES skill_drafts(id)
);

CREATE TABLE IF NOT EXISTS object_pointers (
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  current_revision INTEGER,
  last_good_revision INTEGER,
  PRIMARY KEY (object_type, object_id)
);

CREATE TABLE IF NOT EXISTS contract_objects (
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  relation_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  PRIMARY KEY (object_type, object_id)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  result_json TEXT NOT NULL,
  PRIMARY KEY (scope, key)
);

CREATE TABLE IF NOT EXISTS operations (
  operation_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  result_json TEXT,
  error_json TEXT
);

CREATE TABLE IF NOT EXISTS operation_events (
  operation_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_json TEXT NOT NULL,
  PRIMARY KEY (operation_id, sequence),
  FOREIGN KEY (operation_id) REFERENCES operations(operation_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  profile TEXT NOT NULL CHECK (profile IN ('production', 'demo', 'test')),
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL,
  lease_owner TEXT,
  lease_expires_at TEXT,
  heartbeat_at TEXT,
  next_attempt_at TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  outbox_sequence INTEGER NOT NULL DEFAULT 0,
  payload_ref_json TEXT,
  UNIQUE(profile, idempotency_key)
);

CREATE TABLE IF NOT EXISTS job_events (
  job_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  payload_ref_json TEXT,
  PRIMARY KEY (job_id, sequence),
  FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS dead_letters (
  job_id TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  payload_ref_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS outbox_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_json TEXT NOT NULL,
  published_at TEXT,
  UNIQUE(aggregate_type, aggregate_id, sequence)
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('001_knowledge_assets', CURRENT_TIMESTAMP);

CREATE INDEX IF NOT EXISTS audit_events_operation_idx
  ON audit_events(operation_id, id);
