CREATE TABLE IF NOT EXISTS skill_view_shares (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL,
  skill_view_revision_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  grant_json JSONB NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO schema_migrations(version, applied_at)
VALUES ('004_step3_shares', CURRENT_TIMESTAMP)
ON CONFLICT (version) DO NOTHING;
