import type { JsonObject } from "../domain/types";
import type { ApiEnvelope, ConnectionJobWaitOptions, JobResult } from "./client";

export class ConnectionJobPollError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly retryable: boolean,
    readonly details?: JsonObject,
  ) {
    super(message);
    this.name = "ConnectionJobPollError";
  }
}

export async function waitForConnectionJob(
  initial: ApiEnvelope<JobResult>,
  fetchJob: (jobId: string, signal?: AbortSignal) => Promise<ApiEnvelope<JobResult>>,
  options: ConnectionJobWaitOptions = {},
): Promise<ApiEnvelope<JobResult>> {
  const timeoutMs = options.timeoutMs ?? 120_000;
  const pollIntervalMs = options.pollIntervalMs ?? 750;
  const retryAttempts = options.retryAttempts ?? 2;
  const wait = options.wait ?? abortableDelay;
  const deadline = Date.now() + timeoutMs;
  let current = initial;
  let retryCount = 0;

  while (current.data.status === "queued" || current.data.status === "running") {
    if (Date.now() >= deadline) {
      throw new ConnectionJobPollError(
        "连接任务等待超时，请重试。",
        "CONNECTION_JOB_TIMEOUT",
        true,
      );
    }
    await wait(
      Math.min(pollIntervalMs, Math.max(0, deadline - Date.now())),
      options.signal,
    );
    try {
      current = await fetchJob(current.data.job_id, options.signal);
      retryCount = 0;
    } catch (error) {
      if (options.signal?.aborted) throw options.signal.reason;
      const retryable = (
        error instanceof Error
        && "retryable" in error
        && error.retryable === true
      );
      if (!retryable || retryCount >= retryAttempts) throw error;
      retryCount += 1;
    }
  }

  if (current.data.status === "failed") {
    const message = typeof current.data.error?.message === "string"
      ? current.data.error.message
      : "连接任务失败，请重试。";
    const code = typeof current.data.error?.code === "string"
      ? current.data.error.code
      : "CONNECTION_JOB_FAILED";
    throw new ConnectionJobPollError(message, code, true, current.data.error);
  }
  return current;
}

function abortableDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(signal.reason);
  return new Promise((resolve, reject) => {
    const timeout = AbortSignal.timeout(milliseconds);
    const onTimeout = () => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    };
    const onAbort = () => {
      timeout.removeEventListener("abort", onTimeout);
      reject(signal?.reason ?? new DOMException("已取消", "AbortError"));
    };
    timeout.addEventListener("abort", onTimeout, { once: true });
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
