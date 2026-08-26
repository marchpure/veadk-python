import {
  useCallback,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from "react";
import type {
  AgentRuntimeContext,
  StartAuthoringInput,
} from "./contracts";
import {
  AgentRuntimeController,
  createSessionSnapshotStore,
  type AgentRuntimeControllerOptions,
} from "./controller";

export interface UseAgentRuntimeOptions
  extends Omit<AgentRuntimeControllerOptions, "snapshotStore"> {
  context?: AgentRuntimeContext;
  restoreOnMount?: boolean;
  storageKey?: string;
}

export function useAgentRuntime(options: UseAgentRuntimeOptions = {}) {
  const {
    context = {},
    restoreOnMount = true,
    storageKey,
    ...controllerOptions
  } = options;
  const controller = useMemo(
    () =>
      new AgentRuntimeController({
        ...controllerOptions,
        snapshotStore:
          typeof window === "undefined"
            ? undefined
            : createSessionSnapshotStore(storageKey),
      }),
    // Runtime identity is intentionally fixed for the component lifetime.
    // Context can change between turns and is merged at submit time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      controllerOptions.baseUrl,
      controllerOptions.clients,
      controllerOptions.idempotencyKeyFactory,
      controllerOptions.requestIdFactory,
      controllerOptions.retryDelaysMs,
      controllerOptions.sleep,
      storageKey,
    ],
  );
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getState,
    controller.getState,
  );

  useEffect(() => {
    if (restoreOnMount) void controller.restore();
    return () => controller.dispose();
  }, [controller, restoreOnMount]);

  const send = useCallback(
    (prompt: string, overrides: AgentRuntimeContext = {}) =>
      controller.start({
        ...context,
        ...overrides,
        prompt,
      } as StartAuthoringInput),
    [context, controller],
  );

  return {
    state,
    active: controller.active,
    send,
    stop: useCallback(() => controller.stop(), [controller]),
    retry: useCallback(() => controller.retry(), [controller]),
    resume: useCallback(() => controller.resume(), [controller]),
    controller,
  };
}
