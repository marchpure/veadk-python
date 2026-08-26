CREATE TABLE IF NOT EXISTS authoring_generation_leases (
  lane_key TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL
);
INSERT INTO schema_migrations(version, applied_at)
VALUES ('007_authoring_generation_leases', CURRENT_TIMESTAMP)
ON CONFLICT (version) DO NOTHING;
