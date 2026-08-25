import { useSyncExternalStore } from "react";
import {
  createRequestContext,
  KnowledgeAdapterError,
  type KnowledgeBootstrap,
  ProductionKnowledgeAdapter,
  type WorkspaceAdapter,
} from "./ports";
import { hydrateWorkspaceData } from "./data";
import type { WorkspaceMcpProfile } from "./bootstrapSchema";
import type { ActionLoopState } from "./actionLoop";

type Listener = () => void;

export interface WorkspaceResource {
  id: string;
  displayName?: string;
  name?: string;
  resourceKind?: string;
  subtype?: string;
  type?: string;
  artifactType?: string;
  space?: "personal" | "team";
  owner?: string;
  version?: string;
  lifecycle?: string;
  permission?: boolean;
  readonly?: boolean;
  lineage?: { sourceIds: string[] };
  [key: string]: unknown;
}

export interface ConnectorDef {
  connectorKey: string;
  category: string;
  name: string;
  desc: string;
  capabilities: string[];
  inputSchema: Record<string, string>;
  credentialSchema: Record<string, string> | null;
  discoveryPipeline: string[];
  syncModes: string[];
  [key: string]: unknown;
}

export class WorkspaceStore<T> {
  private state: T;
  private readonly key: string;
  private readonly listeners = new Set<Listener>();

  constructor(key: string, initial: T) {
    this.key = key;
    this.state = initial;
  }

  getState = (): T => this.state;

  setState = (updater: (previous: T) => T): void => {
    const next = updater(this.state);
    const adapter = getWorkspaceAdapter();
    void adapter
      .command(
        {
          command: "action.update",
          payload: { actionId: `store:${this.key}` },
        },
        createRequestContext(),
      )
      .then((result) => {
        if (!result.accepted) {
          publishWorkspaceError(
            new KnowledgeAdapterError({
              code: "UNAVAILABLE",
              message: "知识服务未确认此操作，未应用本地修改。",
              retryable: true,
              requestId: result.requestId,
            }),
          );
          return;
        }
        if (!adapter.allowOptimisticUpdates) return;
        this.state = next;
        this.listeners.forEach((listener) => listener());
      })
      .catch((error: unknown) => {
        publishWorkspaceError(error);
      });
  };

  replace = (next: T): void => {
    this.state = next;
    this.listeners.forEach((listener) => listener());
  };

  subscribe = (listener: Listener): () => void => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}

// Keep the action-loop store on the same production store module as the other
// server-hydrated stores. `actionLoop.ts` re-exports this instance so frozen
// imports retain their original module path without introducing a runtime
// cycle back into this module.
export const actionLoopStore = new WorkspaceStore<ActionLoopState>(
  "action-loop",
  {
    signals: [],
    policies: [],
    todos: [],
    reviews: [],
    briefs: [],
  },
);

// Production route availability is populated only by the bootstrap response.
let adapter: WorkspaceAdapter = new ProductionKnowledgeAdapter();
let lastError: KnowledgeAdapterError | null = null;
let workspaceRoutes = new Set<string>(["welcome"]);
let workspaceId = "local";
const SERVER_FEATURE_ROUTES = new Set([
  "welcome",
  "add_data",
  "connector_catalog",
  "add_kb",
  "upload_doc",
  "skill_builder",
  "data_overview",
  "evaluation_detail",
]);
// These are high-fidelity Workspace deep links from the frozen 43-state
// capability matrix. They are route capabilities, not resource facts: the
// rendered view must still use server-hydrated data or show its own honest
// gated/empty state.
const CAPABILITY_MATRIX_ROUTE_IDS = new Set([
  "add_data",
  "connector_catalog",
  "upload_doc",
  "data_overview",
  "add_kb",
  "skill_builder",
  "evaluation_detail",
  "journey_knowledge",
  "journey_oracle_excel",
  "journey_web_api",
  "journey_financial_monitor",
  "journey_workday_mcp",
  "res_dash_finance",
  "res_dash_east",
  "res_dash_recruitment",
  "kg_sales",
  "semantic_sales",
  "res_sample_postgres",
  "kb_sales",
]);
const errorListeners = new Set<(error: KnowledgeAdapterError | null) => void>();

export function getWorkspaceAdapter(): WorkspaceAdapter {
  return adapter;
}

export function installWorkspaceAdapter(next: WorkspaceAdapter): void {
  adapter = next;
  workspaceRoutes = new Set(["welcome"]);
  workspaceId = "local";
  lastError = null;
  errorListeners.forEach((listener) => listener(null));
}

export function isWorkspaceRouteAvailable(fileId: string): boolean {
  return (
    (SERVER_FEATURE_ROUTES.has(fileId) && workspaceRoutes.has(fileId)) ||
    CAPABILITY_MATRIX_ROUTE_IDS.has(fileId) ||
    resourceStore
      .getState()
      .some(
        (resource) => resource.id === fileId || resource.resourceId === fileId,
      )
  );
}

export function subscribeWorkspaceError(
  listener: (error: KnowledgeAdapterError | null) => void,
): () => void {
  errorListeners.add(listener);
  return () => errorListeners.delete(listener);
}

export function getWorkspaceError(): KnowledgeAdapterError | null {
  return lastError;
}

export const knowledgeWorkspaceStorage: Storage = {
  get length() {
    return 0;
  },
  clear() {
    void getWorkspaceAdapter()
      .command(
        { command: "action.update", payload: { actionId: "storage.clear" } },
        createRequestContext(),
      )
      .catch(publishWorkspaceError);
  },
  getItem() {
    return null;
  },
  key() {
    return null;
  },
  removeItem(key) {
    void getWorkspaceAdapter()
      .command(
        {
          command: "action.update",
          payload: { actionId: `storage.remove:${key}` },
        },
        createRequestContext(),
      )
      .catch(publishWorkspaceError);
  },
  setItem(key, value) {
    void value;
    void getWorkspaceAdapter()
      .command(
        {
          command: "action.update",
          payload: { actionId: `storage.set:${key}` },
        },
        createRequestContext(),
      )
      .catch(publishWorkspaceError);
  },
};

export function publishWorkspaceError(error: unknown): void {
  lastError = error instanceof KnowledgeAdapterError
    ? error
    : new KnowledgeAdapterError({
      code: "UNAVAILABLE",
      message: "知识服务不可用，请稍后重试。",
      retryable: true,
      requestId: "unknown",
    });
  errorListeners.forEach((listener) => listener(lastError));
}

export const resourceStore = new WorkspaceStore<WorkspaceResource[]>(
  "resources",
  [],
);
export const connectionStore = new WorkspaceStore<Record<string, unknown>[]>(
  "connections",
  [],
);
export const agentPublicationStore = new WorkspaceStore<unknown[]>(
  "publications",
  [],
);
export const customRegistryStore = new WorkspaceStore<ConnectorDef[]>(
  "connectors",
  [],
);
export const mcpProfileStore = new WorkspaceStore<WorkspaceMcpProfile[]>(
  "mcp-profiles",
  [],
);

export function useStore<T>(store: WorkspaceStore<T>): T {
  return useSyncExternalStore(store.subscribe, store.getState, store.getState);
}

export function getRegistry(): ConnectorDef[] {
  return customRegistryStore.getState();
}

export function getFullCatalog(): WorkspaceResource[] {
  return resourceStore.getState();
}

export function addResource(resource: WorkspaceResource): void {
  resourceStore.setState((current) => [resource, ...current]);
}

export function getResourceDescriptor(
  fileId: string,
  searchParams: URLSearchParams,
  allResources: WorkspaceResource[],
): Record<string, unknown> | null {
  const resource = allResources.find(
    (item) => item.id === fileId || item.resourceId === fileId,
  );
  if (!resource) return null;
  return {
    identity: resource.id,
    id: resource.id,
    name: searchParams.get("custom_name") || resource.displayName ||
      resource.name,
    type: resource.resourceKind || resource.type,
    artifactType: resource.subtype || resource.artifactType || resource.type,
    ...(searchParams.get("version") || resource.version
      ? { version: searchParams.get("version") || resource.version }
      : {}),
    ...(resource.space ? { space: resource.space } : {}),
    isResourceLevel: true,
    resourceKind: resource.resourceKind,
    subtype: resource.subtype,
    lineage: resource.lineage,
  };
}

export async function bootstrapWorkspace(
  signal?: AbortSignal,
  currentAdapter: WorkspaceAdapter = adapter,
): Promise<KnowledgeBootstrap> {
  try {
    const bootstrapped = await currentAdapter.bootstrap(signal);
    const serverWorkspaceId = bootstrapped.access.spaceId;
    if (typeof serverWorkspaceId === "string" && serverWorkspaceId) {
      workspaceId = serverWorkspaceId;
    }
    resourceStore.replace(bootstrapped.resources as WorkspaceResource[]);
    connectionStore.replace(
      bootstrapped.connections as Record<string, unknown>[],
    );
    agentPublicationStore.replace(bootstrapped.publications);
    customRegistryStore.replace(
      bootstrapped.workspaceData.connectorCatalog as ConnectorDef[],
    );
    mcpProfileStore.replace(bootstrapped.workspaceData.mcpProfileCatalog ?? []);
    hydrateWorkspaceData(bootstrapped.workspaceData);
    actionLoopStore.replace(bootstrapped.actionLoop as ActionLoopState);
    workspaceRoutes = new Set([
      "welcome",
      ...(bootstrapped.routes ?? []).filter(
        (route): route is string => typeof route === "string",
      ),
    ]);
    return bootstrapped;
  } catch (error) {
    if (signal?.aborted) throw error;
    publishWorkspaceError(error);
    throw error;
  }
}

export async function runProductionMutation(
  intent: {
    command: import("./ports").KnowledgeCommandName;
    sourcePath: string;
    eventName: string;
    handlerName?: string;
  },
  currentAdapter: WorkspaceAdapter = getWorkspaceAdapter(),
): Promise<import("./ports").KnowledgeCommandResult | null> {
  const context = createRequestContext();
  const selectedDraft = (() => {
    if (typeof window === "undefined") return undefined;
    const draftId = new URL(window.location.href).searchParams.get("draft_id");
    return resourceStore.getState().find(
      (resource) =>
        resource.resourceKind === "skill_draft" &&
        (!draftId || resource.id === draftId),
    );
  })();
  const command: import("./ports").KnowledgeCommand = intent.command ===
      "skill-draft.create"
    ? {
      command: "skill-draft.create",
      payload: {
        workspaceId,
        name: "销售制度知识库",
        description: "由知识库创建动作生成的 Skill 草稿",
        sourceRefs: [],
      },
    }
    : intent.command === "skill-draft.save-manifest"
    ? {
      command: "skill-draft.save-manifest",
      payload: {
        draftId: selectedDraft?.id ?? "",
        baseRevision: Number(selectedDraft?.revision ?? 1),
        manifest: {
          name: "销售制度知识库",
          version: "1.0.0",
          description: "聚合各渠道的销售制度与流程规范",
          actions: [{
            name: "answer",
            description: "回答销售制度与流程问题",
          }],
          schema: {
            type: "object",
            properties: {
              question: {
                type: "string",
                description: "用户问题",
              },
            },
            required: ["question"],
            additionalProperties: false,
          },
        },
      },
    }
    : {
      command: "action.update",
      payload: {
        actionId: `${intent.sourcePath}:${intent.handlerName ?? intent.eventName}`,
      },
    };
  try {
    const result = await currentAdapter.command(command, context);
    if (!result.accepted) {
      publishWorkspaceError(
        new KnowledgeAdapterError({
          code: "UNAVAILABLE",
          message: "知识服务未确认此操作，未应用本地修改。",
          retryable: true,
          requestId: context.requestId,
        }),
      );
      return null;
    }
    try {
      await bootstrapWorkspace(undefined, currentAdapter);
    } catch {
      return null;
    }
    if (intent.command === "skill-draft.create") {
      const draft = result.result?.draft;
      const draftId = draft && typeof draft === "object" &&
          typeof draft.id === "string"
        ? draft.id
        : undefined;
      if (draftId && typeof window !== "undefined") {
        const next = new URL(window.location.href);
        next.searchParams.set("file", "skill_builder");
        next.searchParams.set("draft_id", draftId);
        next.searchParams.delete("adapter");
        window.history.pushState({}, "", next);
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
    }
    return result;
  } catch (error) {
    publishWorkspaceError(error);
    return null;
  }
}
