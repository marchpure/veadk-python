CREATE TABLE IF NOT EXISTS published_skill_versions (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL,
  skill_revision_id TEXT NOT NULL,
  semver TEXT NOT NULL,
  version_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('003_step3_publication', CURRENT_TIMESTAMP);
