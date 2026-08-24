/**
 * Deterministic adapter for contract/reference tests only.
 *
 * This file is intentionally outside src and is never imported by the
 * production entrypoint or the Vite graph.
 */
export function createDeterministicContractAdapter(seed = "knowledge-contract") {
  const resources = [
    {
      id: `${seed}-dashboard`,
      displayName: "Contract Dashboard",
      resourceKind: "artifact",
      subtype: "dashboard",
      space: "personal",
      version: "V1.0",
    },
  ];
  const commands = [];
  return {
    kind: "contract",
    allowOptimisticUpdates: true,
    commands,
    async bootstrap() {
      return {
        resources,
        connections: [],
        publications: [],
        workspaceData: {
          connectorCatalog: [],
          datasetFields: [],
          dashboard: { kpis: [], trendData: [] },
          knowledgeGraph: { entities: [], mappings: [] },
        },
        actionLoop: {
          signals: [],
          policies: [],
          todos: [],
          reviews: [],
          briefs: [],
        },
        access: { spaceId: `${seed}-space`, role: "editor", capabilities: [] },
        serverTime: "2026-01-01T00:00:00.000Z",
      };
    },
    async command(command, payload, context) {
      commands.push({ command, payload, context });
      return { accepted: true, requestId: context.requestId, version: "V1.0" };
    },
    async stream(command, payload, context) {
      commands.push({ command, payload, context });
      return {
        async *events() {
          yield {
            schema_version: "knowledge-workspace.transport.v1",
            stream_id: `${seed}-stream`,
            event_id: `${seed}-event-1`,
            sequence: 1,
            occurred_at: "2026-01-01T00:00:00.000Z",
            type: "terminal",
            payload: { ok: true },
            terminal: true,
          };
        },
        async cancel() {},
      };
    },
  };
}
