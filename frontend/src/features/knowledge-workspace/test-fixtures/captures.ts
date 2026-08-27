/**
 * Visual regression input only. This module is never imported by production
 * pages; it records the prototype's 22 state URLs and the production route
 * state they exercise.
 */
export const KNOWLEDGE_CAPTURE_STATES = [
  { stateUrl: "/?file=welcome", route: "welcome" },
  { stateUrl: "/?file=draft_dash_anta", route: "draft", runState: "default" },
  { stateUrl: "/?file=draft_dash_anta&run_state=success", route: "draft", runState: "success" },
  { stateUrl: "/?file=draft_dash_anta&run_state=success&modal=publish", route: "draft", runState: "success", modal: "publish" },
  { stateUrl: "/?file=draft_dash_anta&run_state=failed", route: "draft", runState: "failed" },
  { stateUrl: "/?file=draft_dash_anta&state=permission", route: "draft", state: "permission" },
  { stateUrl: "/?file=draft_dash_anta&state=connection_error", route: "draft", state: "connection_error" },
  { stateUrl: "/?file=draft_dash_anta&state=upgrade", route: "draft", state: "upgrade" },
  { stateUrl: "/?file=draft_dash_anta&modal=advanced", route: "draft", modal: "advanced" },
  { stateUrl: "/?file=draft_dash_anta&modal=test_records", route: "draft", modal: "test_records" },
  { stateUrl: "/?file=draft_dash_anta&modal=tools", route: "draft", modal: "tools" },
  { stateUrl: "/?file=pub_dash_anta", route: "published" },
  { stateUrl: "/?file=pub_dash_anta&modal=agent", route: "published", modal: "agent" },
  { stateUrl: "/?file=pub_dash_anta&modal=share_run", route: "published", modal: "share_run" },
  { stateUrl: "/?file=pub_dash_anta&modal=instructions", route: "published", modal: "instructions" },
  { stateUrl: "/?file=pub_dash_anta&modal=versions", route: "published", modal: "versions" },
  { stateUrl: "/?file=draft_sop_bluetooth", route: "draft", resource: "sop_bluetooth" },
  { stateUrl: "/?file=draft_sop_haidilao", route: "draft", resource: "sop_haidilao" },
  { stateUrl: "/?file=skill_new", route: "skill_new" },
  { stateUrl: "/?file=skill_new&scenario=anta", route: "skill_new", scenario: "server-state" },
  { stateUrl: "/?file=skill_new&scenario=zhiji", route: "skill_new", scenario: "server-state" },
  { stateUrl: "/?file=skill_new&scenario=haidilao", route: "skill_new", scenario: "server-state" },
] as const;
