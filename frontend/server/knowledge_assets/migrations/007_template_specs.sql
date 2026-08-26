CREATE TABLE IF NOT EXISTS template_spec_versions (
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  digest TEXT NOT NULL UNIQUE,
  spec_json TEXT NOT NULL,
  spec_md TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (template_id, version, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_template_specs_workspace
  ON template_spec_versions (workspace_id, template_id, version);
