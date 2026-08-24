CREATE TABLE IF NOT EXISTS authoring_operations (
  id TEXT PRIMARY KEY,
  payload_json JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS authoring_events (
  id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  payload_json JSONB NOT NULL,
  UNIQUE(operation_id, sequence)
);
CREATE TABLE IF NOT EXISTS authoring_drafts (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  workspace_id TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  UNIQUE(draft_id, revision)
);
CREATE TABLE IF NOT EXISTS authoring_requests (
  id TEXT PRIMARY KEY,
  payload_json JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS authoring_patches (
  id TEXT PRIMARY KEY,
  payload_json JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS authoring_idempotency (
  id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL
);
INSERT INTO schema_migrations(version, applied_at)
VALUES ('006_skill_authoring', CURRENT_TIMESTAMP)
ON CONFLICT (version) DO NOTHING;
