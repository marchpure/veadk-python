export const SHELL_EVENTS = [
  "workspace_home_view",
  "workspace_menu_more_click",
  "skill_draft_view",
  "skill_primary_cta_click",
  "skill_build_detail_drawer_open",
  "skill_auth_error_shown",
  "skill_debug_view",
  "skill_debug_render_error_shown",
  "skill_eval_view",
  "skill_publish_submit",
  "skill_published_view",
  "skill_simulate_call_click",
  "skill_schema_drift_warning_shown",
] as const;

export type ShellEventName = (typeof SHELL_EVENTS)[number];
const telemetryWindow = (): Window & { __knowledgeWorkspaceViewEvents?: Set<string> } =>
  window as Window & { __knowledgeWorkspaceViewEvents?: Set<string> };

export const scenarioForRoute = (route: string): string => {
  if (/oracle/i.test(route)) return "oracle_excel";
  if (/web_api/i.test(route)) return "web_api";
  if (/financial/i.test(route)) return "financial_monitor";
  if (/workday/i.test(route)) return "workday_mcp";
  return "knowledge";
};

/**
 * The shell owns interaction telemetry, while the service owns business state.
 * A DOM event keeps this module independent from the product-wide TEA runtime;
 * the host can bridge it without making the UI invent an analytics contract.
 */
export function trackShellEvent(
  name: ShellEventName,
  payload: Record<string, string | number | boolean | undefined> = {},
): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("knowledge_workspace_telemetry", {
      detail: { name, payload, occurred_at: new Date().toISOString() },
    }),
  );
}

export function trackShellEventOnce(
  name: ShellEventName,
  semanticKey: string,
  payload: Record<string, string | number | boolean | undefined> = {},
): void {
  if (typeof window === "undefined") return;
  // React StrictMode can create two history keys during the initial mount.
  // The canonical URL is stable across those mounts and still changes on a
  // real route transition.
  const navigationKey = `${window.location.pathname}${window.location.search}`;
  const key = `${navigationKey}:${name}:${semanticKey}`;
  const emittedViewEvents =
    telemetryWindow().__knowledgeWorkspaceViewEvents ??
    (telemetryWindow().__knowledgeWorkspaceViewEvents = new Set<string>());
  if (emittedViewEvents.has(key)) return;
  emittedViewEvents.add(key);
  trackShellEvent(name, payload);
}
