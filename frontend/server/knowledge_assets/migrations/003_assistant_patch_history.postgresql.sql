CREATE TABLE IF NOT EXISTS assistant_patch_history (
  patch_id TEXT PRIMARY KEY,
  undo_token TEXT NOT NULL UNIQUE,
  skill_id TEXT NOT NULL,
  base_revision INTEGER NOT NULL,
  operation TEXT NOT NULL,
  before_value TEXT NOT NULL,
  after_value TEXT NOT NULL
);

INSERT INTO schema_migrations(version, applied_at)
VALUES ('003_assistant_patch_history', CURRENT_TIMESTAMP)
ON CONFLICT (version) DO NOTHING;
