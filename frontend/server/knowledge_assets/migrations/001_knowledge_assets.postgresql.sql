CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_drafts (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS skill_draft_revisions (
  draft_id TEXT NOT NULL REFERENCES skill_drafts(id),
  skill_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  manifest_json JSONB NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (draft_id, revision)
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
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  relation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL,
  PRIMARY KEY (object_type, object_id)
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  result_json JSONB NOT NULL,
  PRIMARY KEY (scope, key)
);

CREATE TABLE IF NOT EXISTS operations (
  operation_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  result_json JSONB,
  error_json JSONB
);

CREATE TABLE IF NOT EXISTS operation_events (
  operation_id TEXT NOT NULL REFERENCES operations(operation_id),
  sequence INTEGER NOT NULL,
  event_json JSONB NOT NULL,
  PRIMARY KEY (operation_id, sequence)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL PRIMARY KEY,
  request_id TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL
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
  lease_expires_at TIMESTAMPTZ,
  heartbeat_at TIMESTAMPTZ,
  next_attempt_at TIMESTAMPTZ,
  cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
  outbox_sequence INTEGER NOT NULL DEFAULT 0,
  payload_ref_json JSONB,
  UNIQUE(profile, idempotency_key)
);

CREATE TABLE IF NOT EXISTS job_events (
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  payload_ref_json JSONB,
  PRIMARY KEY (job_id, sequence)
);

CREATE TABLE IF NOT EXISTS dead_letters (
  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
  reason TEXT NOT NULL,
  payload_ref_json JSONB,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_events (
  id BIGSERIAL PRIMARY KEY,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_json JSONB NOT NULL,
  published_at TIMESTAMPTZ,
  UNIQUE(aggregate_type, aggregate_id, sequence)
);

CREATE INDEX IF NOT EXISTS audit_events_operation_idx
  ON audit_events(operation_id, id);

INSERT INTO schema_migrations(version, applied_at)
VALUES ('001_knowledge_assets', CURRENT_TIMESTAMP)
ON CONFLICT (version) DO NOTHING;
