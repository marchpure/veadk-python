export type DemoScenarioStatus = "ready" | "not_initialized" | "blocked" | "error";

export interface DemoScenario {
  scenario_id: string;
  title: string;
  source: string;
  data_source?: string;
  skill_type: string;
  goal: string;
  status: DemoScenarioStatus;
  connection_status: string;
  skill_status: string;
  connection_id?: string;
  draft_id?: string;
  authoring_session_id?: string;
  publication_id?: string;
  revision_ids?: string[];
  artifact_ids?: string[];
  last_verified_at?: string | null;
  next_step: string;
}

export interface DemoManifest {
  enabled: boolean;
  status: "disabled" | "not_initialized" | "ready" | "blocked" | "error";
  seed_version?: string;
  source?: string;
  provenance?: string;
  next_step: string;
  scenarios: DemoScenario[];
}
