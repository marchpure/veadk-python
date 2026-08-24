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

CREATE TABLE IF NOT EXISTS source_revisions (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  content_ref_json TEXT NOT NULL,
  schema_ref_json TEXT,
  permission_ref_json TEXT NOT NULL,
  source_digest TEXT NOT NULL,
  source_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_runs (
  id TEXT PRIMARY KEY,
  source_revision_id TEXT NOT NULL,
  status TEXT NOT NULL,
  sample_ref_json TEXT,
  report_ref_json TEXT,
  quality_score REAL,
  error_code TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  FOREIGN KEY (source_revision_id) REFERENCES source_revisions(id)
);

CREATE TABLE IF NOT EXISTS cleaning_recipes (
  id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  operations_json TEXT NOT NULL,
  source_revision_id TEXT NOT NULL,
  recipe_digest TEXT NOT NULL,
  FOREIGN KEY (source_revision_id) REFERENCES source_revisions(id)
);

CREATE TABLE IF NOT EXISTS clean_runs (
  id TEXT PRIMARY KEY,
  source_revision_id TEXT NOT NULL,
  recipe_id TEXT NOT NULL,
  status TEXT NOT NULL,
  output_ref_json TEXT,
  quality_report_ref_json TEXT,
  error_code TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  FOREIGN KEY (source_revision_id) REFERENCES source_revisions(id),
  FOREIGN KEY (recipe_id) REFERENCES cleaning_recipes(id)
);

CREATE TABLE IF NOT EXISTS golden_asset_revisions (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  asset_kind TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_ref_json TEXT NOT NULL,
  storage_ref_json TEXT NOT NULL,
  source_revision_refs_json TEXT NOT NULL,
  recipe_ref TEXT,
  quality_run_ref TEXT,
  owner_json TEXT NOT NULL,
  permissions_ref_json TEXT NOT NULL,
  lineage_digest TEXT NOT NULL,
  freshness_at TEXT NOT NULL,
  last_good INTEGER NOT NULL DEFAULT 1
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('001_knowledge_assets', CURRENT_TIMESTAMP);

CREATE INDEX IF NOT EXISTS audit_events_operation_idx
  ON audit_events(operation_id, id);
