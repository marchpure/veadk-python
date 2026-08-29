import type { ConnectionProfile } from "../domain/types";

export type OAuthFlowStatus = "pending" | "processing" | "connected" | "provider_error" | "error" | "expired";

export interface OAuthStatus {
  service: string;
  connectionName: string;
  status: OAuthFlowStatus;
}

export interface OAuthFlowPollOptions {
  timeoutMs?: number;
  pollIntervalMs?: number;
  wait?: (milliseconds: number) => Promise<void>;
  isPopupClosed?: () => boolean;
  onStatus?: (status: OAuthStatus) => void;
}

export class OAuthFlowPollError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = "OAuthFlowPollError";
  }
}

export async function waitForOAuthConnection(
  service: string,
  connectionName: string,
  getStatus: () => Promise<OAuthStatus>,
  listConnections: () => Promise<ConnectionProfile[]>,
  options: OAuthFlowPollOptions = {},
): Promise<ConnectionProfile> {
  const timeoutMs = options.timeoutMs ?? 15 * 60 * 1000;
  const pollIntervalMs = options.pollIntervalMs ?? 750;
  const wait = options.wait ?? delay;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const status = await getStatus();
    options.onStatus?.(status);
    if (status.service !== service || status.connectionName !== connectionName) {
      throw new OAuthFlowPollError(
        "OAuth authorization status does not match this connection.",
        "OAUTH_STATUS_MISMATCH",
        false,
      );
    }
    if (status.status === "provider_error") {
      throw new OAuthFlowPollError(
        "飞书返回了授权错误，请检查应用权限和发布状态。",
        "OAUTH_PROVIDER_ERROR",
        false,
      );
    }
    if (status.status === "error") {
      throw new OAuthFlowPollError("连接未能完成，请重试。", "OAUTH_COMPLETION_FAILED", true);
    }
    if (status.status === "expired") {
      throw new OAuthFlowPollError("授权已超时，请重新发起 OAuth。", "OAUTH_TIMEOUT", true);
    }
    if (status.status === "connected") {
      const connection = (await listConnections()).find(
        (item) =>
          item.connector_key === service
          && item.display_name === connectionName
          && item.status !== "revoked",
      );
      if (connection) return connection;
    } else if (status.status === "pending" && options.isPopupClosed?.()) {
      throw new OAuthFlowPollError(
        "授权窗口已关闭，连接尚未创建。",
        "OAUTH_CANCELLED",
        false,
      );
    }
    await wait(Math.min(pollIntervalMs, Math.max(1, deadline - Date.now())));
  }
  throw new OAuthFlowPollError("授权已超时，请重新发起 OAuth。", "OAUTH_TIMEOUT", true);
}

async function delay(milliseconds: number): Promise<void> {
  await new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}
