import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import test from "node:test";

async function loadModule(path) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(path, import.meta.url))],
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "node20",
    write: false,
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].contents).toString("base64")}`);
}

const oauth = await loadModule("../src/features/knowledge-workspace/api/oauthFlow.ts");

function status(status) {
  return { service: "feishu", connectionName: "personal", status };
}

function connection() {
  return {
    connection_id: "connection-1",
    connector_key: "feishu",
    display_name: "personal",
    scope: "personal",
    status: "ready",
    definition_version: "1.0.0",
    profile: {},
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T00:00:00Z",
  };
}

test("OAuth polling waits for connected status and the real connection list", async () => {
  const states = [status("pending"), status("processing"), status("connected")];
  const calls = [];
  const result = await oauth.waitForOAuthConnection(
    "feishu",
    "personal",
    async () => states.shift(),
    async () => {
      calls.push("list");
      return [connection()];
    },
    { wait: async () => {} },
  );
  assert.equal(result.connection_id, "connection-1");
  assert.deepEqual(calls, ["list"]);
});

test("OAuth polling reports cancellation, provider errors, and timeout without success", async () => {
  await assert.rejects(
    oauth.waitForOAuthConnection(
      "feishu",
      "personal",
      async () => status("pending"),
      async () => [],
      { wait: async () => {}, isPopupClosed: () => true },
    ),
    (error) => error.code === "OAUTH_CANCELLED",
  );
  await assert.rejects(
    oauth.waitForOAuthConnection(
      "feishu",
      "personal",
      async () => status("provider_error"),
      async () => [],
      { wait: async () => {} },
    ),
    (error) => error.code === "OAUTH_PROVIDER_ERROR",
  );
  await assert.rejects(
    oauth.waitForOAuthConnection(
      "feishu",
      "personal",
      async () => status("pending"),
      async () => [],
      { timeoutMs: 0, wait: async () => {} },
    ),
    (error) => error.code === "OAUTH_TIMEOUT",
  );
});
