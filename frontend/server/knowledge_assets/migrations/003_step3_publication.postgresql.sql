CREATE TABLE IF NOT EXISTS published_skill_versions (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL,
  skill_revision_id TEXT NOT NULL,
  semver TEXT NOT NULL,
  version_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

INSERT INTO schema_migrations(version, applied_at)
VALUES ('003_step3_publication', CURRENT_TIMESTAMP)
ON CONFLICT (version) DO NOTHING;
