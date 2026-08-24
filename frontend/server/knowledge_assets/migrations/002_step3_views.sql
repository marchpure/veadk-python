CREATE TABLE IF NOT EXISTS skill_results (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL,
  skill_revision INTEGER NOT NULL,
  result_json TEXT NOT NULL,
  result_ref_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_view_revisions (
  id TEXT PRIMARY KEY,
  skill_revision_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  view_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('002_step3_views', CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS evaluation_suites (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  skill_id TEXT NOT NULL,
  suite_json TEXT NOT NULL,
  PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
  id TEXT PRIMARY KEY,
  skill_revision_id TEXT NOT NULL,
  run_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_gate_results (
  id TEXT PRIMARY KEY,
  skill_revision_id TEXT NOT NULL,
  result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invocations (
  id TEXT PRIMARY KEY,
  skill_version_id TEXT NOT NULL,
  skill_view_revision_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  invocation_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
