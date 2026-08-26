import {
  AuthoringHttpError,
  cancelAuthoringOperation,
  followAuthoringOperation,
  retryAuthoringOperation,
  startAuthoringOperation,
} from "./client";
import type {
  AuthoringEvent,
  AuthoringStreamOptions,
  RuntimeErrorState,
  StartedAuthoringOperation,
  StartAuthoringInput,
  TimelineState,
} from "./contracts";
import { createTimelineState, reduceTimelineEvent } from "./timelineState";

type Listener = (state: TimelineState) => void;

export interface AgentRuntimeClients {
  start(
    input: StartAuthoringInput,
    options: AuthoringStreamOptions & { idempotencyKey?: string },
  ): Promise<StartedAuthoringOperation>;
  follow(
    operationId: string,
    options: AuthoringStreamOptions,
  ): AsyncGenerator<AuthoringEvent>;
  cancel(
    operationId: string,
    options?: AuthoringStreamOptions,
  ): Promise<unknown>;
  retry(
    operationId: string,
    options?: AuthoringStreamOptions,
  ): Promise<unknown>;
}

export interface RuntimeSnapshot {
  operationId: string;
  lastEventId?: string;
  events?: AuthoringEvent[];
  userPrompt?: string;
}

export interface RuntimeSnapshotStore {
  load(): RuntimeSnapshot | null;
  save(snapshot: RuntimeSnapshot): void;
  clear(): void;
}

export interface AgentRuntimeControllerOptions {
  baseUrl?: string;
  clients?: AgentRuntimeClients;
  retryDelaysMs?: readonly number[];
  snapshotStore?: RuntimeSnapshotStore;
  requestIdFactory?: () => string;
  idempotencyKeyFactory?: () => string;
  sleep?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}

const TERMINAL = new Set<TimelineState["status"]>([
  "completed",
  "awaiting_input",
  "failed",
  "cancelled",
]);

const defaultClients: AgentRuntimeClients = {
  start: startAuthoringOperation,
  follow: followAuthoringOperation,
  cancel: cancelAuthoringOperation,
  retry: retryAuthoringOperation,
};

function defaultSleep(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (milliseconds <= 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

function runtimeError(error: unknown): RuntimeErrorState {
  if (error instanceof AuthoringHttpError) {
    return {
      code: error.code ?? `HTTP_${error.status}`,
      message:
        error.status === 401 || error.status === 403
          ? "登录或访问权限已失效，请重新登录后继续。"
          : error.message,
      retryable: error.retryable,
      kind:
        error.status === 401 || error.status === 403
          ? "authentication"
          : "network",
      requestId: error.requestId,
    };
  }
  if (error instanceof SyntaxError) {
    return {
      code: "STREAM_PROTOCOL_ERROR",
      message: "服务返回了无法解析的事件，请重试连接。",
      retryable: true,
      kind: "protocol",
    };
  }
  return {
    code: "STREAM_DISCONNECTED",
    message: "连接已中断，回答内容已保留。可继续连接。",
    retryable: true,
    kind: "network",
  };
}

function isUncertainStartError(error: unknown): boolean {
  return error instanceof TypeError;
}

function replacementOperationId(value: unknown): string | undefined {
  if (!value || typeof value !== "object") return undefined;
  const response = value as Record<string, unknown>;
  const direct = response.operation_id ?? response.operationId;
  if (typeof direct === "string") return direct;
  const operation = response.operation;
  if (!operation || typeof operation !== "object") return undefined;
  const nested = operation as Record<string, unknown>;
  const id = nested.operation_id ?? nested.operationId;
  return typeof id === "string" ? id : undefined;
}

export class AgentRuntimeController {
  private readonly clients: AgentRuntimeClients;
  private readonly baseUrl?: string;
  private readonly retryDelaysMs: readonly number[];
  private readonly snapshotStore?: RuntimeSnapshotStore;
  private readonly requestIdFactory: () => string;
  private readonly idempotencyKeyFactory: () => string;
  private readonly sleep: (
    milliseconds: number,
    signal: AbortSignal,
  ) => Promise<void>;
  private readonly listeners = new Set<Listener>();
  private state = createTimelineState("");
  private streamAbort?: AbortController;
  private streamTask?: Promise<void>;
  private generationActive = false;
  private pendingStart?: {
    input: StartAuthoringInput;
    idempotencyKey: string;
  };

  constructor(options: AgentRuntimeControllerOptions = {}) {
    this.clients = options.clients ?? defaultClients;
    this.baseUrl = options.baseUrl;
    this.retryDelaysMs = options.retryDelaysMs ?? [250, 750, 1_500];
    this.snapshotStore = options.snapshotStore;
    this.requestIdFactory =
      options.requestIdFactory ?? (() => crypto.randomUUID());
    this.idempotencyKeyFactory =
      options.idempotencyKeyFactory ?? (() => crypto.randomUUID());
    this.sleep = options.sleep ?? defaultSleep;
  }

  getState = (): TimelineState => this.state;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  get active(): boolean {
    return this.generationActive;
  }

  async start(input: StartAuthoringInput): Promise<string> {
    if (this.generationActive) {
      throw new Error("当前对话已有回答正在生成，请先停止后再发送。");
    }
    const pendingStart = {
      input,
      idempotencyKey: this.idempotencyKeyFactory(),
    };
    this.pendingStart = pendingStart;
    return this.startPending(pendingStart);
  }

  private async startPending(pendingStart: {
    input: StartAuthoringInput;
    idempotencyKey: string;
  }): Promise<string> {
    const { input, idempotencyKey } = pendingStart;
    this.abortStream();
    this.generationActive = true;
    this.replaceState({
      ...createTimelineState("pending"),
      userPrompt: input.prompt,
      status: "connecting",
    });
    const controller = new AbortController();
    this.streamAbort = controller;
    let retryIndex = 0;
    try {
      let started: StartedAuthoringOperation;
      while (true) {
        try {
          started = await this.clients.start(input, {
            baseUrl: this.baseUrl,
            signal: controller.signal,
            requestId: this.requestIdFactory(),
            idempotencyKey,
          });
          this.pendingStart = undefined;
          break;
        } catch (error) {
          if (
            controller.signal.aborted ||
            !isUncertainStartError(error) ||
            retryIndex >= this.retryDelaysMs.length
          ) {
            throw error;
          }
          this.replaceState({
            ...this.state,
            warning: "启动连接中断，正在确认同一次请求…",
          });
          await this.sleep(this.retryDelaysMs[retryIndex], controller.signal);
          retryIndex += 1;
        }
      }
      this.replaceState({
        ...createTimelineState(started.operationId),
        userPrompt: input.prompt,
        status: "running",
      });
      this.persistSnapshot();
      this.streamTask = this.consumeWithReconnect(started.events, controller);
      return started.operationId;
    } catch (error) {
      if (controller.signal.aborted) throw error;
      this.generationActive = false;
      this.replaceState({
        ...this.state,
        status: "failed",
        error: runtimeError(error),
      });
      throw error;
    }
  }

  async restore(snapshot = this.snapshotStore?.load()): Promise<boolean> {
    if (!snapshot?.operationId || this.generationActive) return false;
    this.abortStream();
    let restoredState = createTimelineState(snapshot.operationId);
    for (const event of snapshot.events ?? []) {
      restoredState = reduceTimelineEvent(restoredState, event);
    }
    const restoredSnapshot = {
      ...restoredState,
      userPrompt: snapshot.userPrompt,
      lastEventId: snapshot.lastEventId ?? restoredState.lastEventId,
    };
    if (TERMINAL.has(restoredSnapshot.status)) {
      this.generationActive = false;
      this.replaceState(restoredSnapshot);
      return true;
    }
    this.generationActive = true;
    this.replaceState({
      ...restoredSnapshot,
      status: "connecting",
    });
    const controller = new AbortController();
    this.streamAbort = controller;
    this.streamTask = this.consumeWithReconnect(
      this.clients.follow(snapshot.operationId, {
        baseUrl: this.baseUrl,
        signal: controller.signal,
        lastEventId: snapshot.lastEventId,
        requestId: this.requestIdFactory(),
      }),
      controller,
    );
    return true;
  }

  async stop(): Promise<void> {
    const operationId = this.state.operationId;
    if (!this.generationActive || !operationId || operationId === "pending") {
      return;
    }
    this.replaceState({ ...this.state, status: "stopping" });
    try {
      await this.clients.cancel(operationId, {
        baseUrl: this.baseUrl,
        requestId: this.requestIdFactory(),
      });
      if (!TERMINAL.has(this.state.status)) {
        await this.resume();
      }
    } catch (error) {
      this.replaceState({
        ...this.state,
        status: "disconnected",
        error: runtimeError(error),
      });
    }
  }

  async retry(): Promise<string | undefined> {
    const operationId = this.state.operationId;
    if (!operationId || this.generationActive) return undefined;
    if (operationId === "pending" && this.pendingStart) {
      try {
        return await this.startPending(this.pendingStart);
      } catch {
        return undefined;
      }
    }
    this.generationActive = true;
    this.replaceState({ ...this.state, status: "connecting", error: undefined });
    try {
      const response = await this.clients.retry(operationId, {
        baseUrl: this.baseUrl,
        requestId: this.requestIdFactory(),
      });
      const replacementId = replacementOperationId(response);
      if (!replacementId) {
        throw new Error("Retry response did not identify its operation.");
      }
      const userPrompt = this.state.userPrompt;
      this.abortStream();
      this.replaceState({
        ...createTimelineState(replacementId),
        userPrompt,
        status: "connecting",
      });
      this.persistSnapshot();
      const controller = new AbortController();
      this.streamAbort = controller;
      this.streamTask = this.consumeWithReconnect(
        this.clients.follow(replacementId, {
          baseUrl: this.baseUrl,
          signal: controller.signal,
          requestId: this.requestIdFactory(),
        }),
        controller,
      );
      return replacementId;
    } catch (error) {
      this.generationActive = false;
      this.replaceState({
        ...this.state,
        status: "failed",
        error: runtimeError(error),
      });
      return undefined;
    }
  }

  async resume(): Promise<void> {
    const operationId = this.state.operationId;
    if (!operationId || operationId === "pending") return;
    this.abortStream();
    this.generationActive = true;
    this.replaceState({
      ...this.state,
      status: "connecting",
      error: undefined,
    });
    const controller = new AbortController();
    this.streamAbort = controller;
    this.streamTask = this.consumeWithReconnect(
      this.clients.follow(operationId, {
        baseUrl: this.baseUrl,
        signal: controller.signal,
        lastEventId: this.state.lastEventId,
        requestId: this.requestIdFactory(),
      }),
      controller,
    );
  }

  async waitForSettled(): Promise<void> {
    await this.streamTask;
  }

  dispose(): void {
    this.abortStream();
    this.generationActive = false;
    this.listeners.clear();
  }

  private async consumeWithReconnect(
    initial: AsyncGenerator<AuthoringEvent>,
    controller: AbortController,
  ): Promise<void> {
    let events = initial;
    let retryIndex = 0;
    while (!controller.signal.aborted) {
      try {
        let receivedTerminal = false;
        for await (const event of events) {
          if (controller.signal.aborted) return;
          this.replaceState(reduceTimelineEvent(this.state, event));
          this.persistSnapshot();
          if (event.terminal) {
            receivedTerminal = true;
            this.generationActive = false;
            return;
          }
        }
        if (receivedTerminal) return;
        throw new TypeError("Authoring stream ended before a terminal event.");
      } catch (error) {
        if (controller.signal.aborted) return;
        if (retryIndex >= this.retryDelaysMs.length) {
          this.generationActive = false;
          this.replaceState({
            ...this.state,
            status: "disconnected",
            error: runtimeError(error),
          });
          return;
        }
        this.replaceState({
          ...this.state,
          status: "reconnecting",
          warning: "连接中断，正在从上次事件继续…",
        });
        await this.sleep(this.retryDelaysMs[retryIndex], controller.signal);
        retryIndex += 1;
        events = this.clients.follow(this.state.operationId, {
          baseUrl: this.baseUrl,
          signal: controller.signal,
          lastEventId: this.state.lastEventId,
          requestId: this.requestIdFactory(),
        });
      }
    }
  }

  private replaceState(state: TimelineState): void {
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }

  private persistSnapshot(): void {
    if (!this.state.operationId || this.state.operationId === "pending") return;
    this.snapshotStore?.save({
      operationId: this.state.operationId,
      lastEventId: this.state.lastEventId,
      events: this.state.events,
      userPrompt: this.state.userPrompt,
    });
  }

  private abortStream(): void {
    this.streamAbort?.abort();
    this.streamAbort = undefined;
  }
}

export function createSessionSnapshotStore(
  key = "knowledge-agent-runtime.v1",
): RuntimeSnapshotStore {
  return {
    load() {
      try {
        const raw = sessionStorage.getItem(key);
        if (!raw) return null;
        const value = JSON.parse(raw) as Partial<RuntimeSnapshot>;
        return typeof value.operationId === "string"
          ? {
            operationId: value.operationId,
            lastEventId:
              typeof value.lastEventId === "string"
                ? value.lastEventId
                : undefined,
            events: Array.isArray(value.events)
              ? value.events as AuthoringEvent[]
              : undefined,
            userPrompt:
              typeof value.userPrompt === "string"
                ? value.userPrompt
                : undefined,
          }
          : null;
      } catch {
        return null;
      }
    },
    save(snapshot) {
      try {
        sessionStorage.setItem(key, JSON.stringify(snapshot));
      } catch {
        // Storage is an optimization; durable server state remains canonical.
      }
    },
    clear() {
      try {
        sessionStorage.removeItem(key);
      } catch {
        // Ignore unavailable browser storage.
      }
    },
  };
}
