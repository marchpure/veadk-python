CREATE TABLE IF NOT EXISTS evaluation_quality_suites (
  suite_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (suite_id, version)
);
CREATE TABLE IF NOT EXISTS evaluation_quality_runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_quality_gates (
  gate_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_quality_fix_plans (
  plan_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('005_evaluation_quality', CURRENT_TIMESTAMP);
