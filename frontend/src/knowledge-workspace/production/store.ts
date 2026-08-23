import { useSyncExternalStore } from "react";
import {
  createRequestContext,
  KnowledgeAdapterError,
  ProductionKnowledgeAdapter,
  type KnowledgeBootstrap,
  type WorkspaceAdapter,
} from "./ports";

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
      .command("workspace.store-update", { store: this.key, value: next }, createRequestContext())
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

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}

let adapter: WorkspaceAdapter = new ProductionKnowledgeAdapter();
let lastError: KnowledgeAdapterError | null = null;
const errorListeners = new Set<(error: KnowledgeAdapterError | null) => void>();

export function getWorkspaceAdapter(): WorkspaceAdapter {
  return adapter;
}

export function installWorkspaceAdapter(next: WorkspaceAdapter): void {
  adapter = next;
  lastError = null;
  errorListeners.forEach((listener) => listener(null));
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
      .command("workspace.store-update", { operation: "clear" }, createRequestContext())
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
        "workspace.store-update",
        { operation: "remove", key },
        createRequestContext(),
      )
      .catch(publishWorkspaceError);
  },
  setItem(key, value) {
    void getWorkspaceAdapter()
      .command(
        "workspace.store-update",
        { operation: "set", key, value },
        createRequestContext(),
      )
      .catch(publishWorkspaceError);
  },
};

export function publishWorkspaceError(error: unknown): void {
  lastError =
    error instanceof KnowledgeAdapterError
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
    name: searchParams.get("custom_name") || resource.displayName || resource.name,
    type: resource.resourceKind || resource.type,
    artifactType: resource.subtype || resource.artifactType || resource.type,
    version: searchParams.get("version") || resource.version || "V1.0",
    space: resource.space || "personal",
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
    resourceStore.replace(bootstrapped.resources as WorkspaceResource[]);
    connectionStore.replace(bootstrapped.connections as Record<string, unknown>[]);
    agentPublicationStore.replace(bootstrapped.publications);
    return bootstrapped;
  } catch (error) {
    publishWorkspaceError(error);
    throw error;
  }
}

export async function runProductionMutation(
  intent: {
    command: import("./ports").KnowledgeCommand;
    sourcePath: string;
    eventName: string;
    handlerName?: string;
  },
  currentAdapter: WorkspaceAdapter = getWorkspaceAdapter(),
): Promise<boolean> {
  const context = createRequestContext();
  try {
    const result = await currentAdapter.command(intent.command, intent, context);
    if (!result.accepted) {
      publishWorkspaceError(
        new KnowledgeAdapterError({
          code: "UNAVAILABLE",
          message: "知识服务未确认此操作，未应用本地修改。",
          retryable: true,
          requestId: context.requestId,
        }),
      );
      return false;
    }
    try {
      await bootstrapWorkspace(undefined, currentAdapter);
    } catch {
      return false;
    }
    return true;
  } catch (error) {
    publishWorkspaceError(error);
    return false;
  }
}
