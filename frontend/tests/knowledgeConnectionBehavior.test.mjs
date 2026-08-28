import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

async function loadModule(path) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(path, import.meta.url))],
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    write: false,
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].contents).toString("base64")}`);
}

const jobs = await loadModule("../src/features/knowledge-workspace/api/connectionJobs.ts");
const schemas = await loadModule("../src/features/knowledge-workspace/domain/connectionSchema.ts");

function envelope(status, extra = {}) {
  return {
    data: { job_id: "job-1", status, ...extra },
    meta: { request_id: "request-1" },
  };
}

test("connection polling follows queued to running to succeeded", async () => {
  const states = [envelope("running"), envelope("succeeded", { result: { actions: [] } })];
  const calls = [];
  const result = await jobs.waitForConnectionJob(
    envelope("queued"),
    async (jobId) => {
      calls.push(jobId);
      return states.shift();
    },
    { pollIntervalMs: 1, timeoutMs: 1_000, wait: async () => {} },
  );
  assert.equal(result.data.status, "succeeded");
  assert.deepEqual(calls, ["job-1", "job-1"]);
});

test("connection polling surfaces failed terminal jobs as retryable", async () => {
  await assert.rejects(
    jobs.waitForConnectionJob(
      envelope("running"),
      async () => envelope("failed", { error: { code: "bad_credentials", message: "Rejected" } }),
      { pollIntervalMs: 1, wait: async () => {} },
    ),
    (error) => error.code === "bad_credentials" && error.retryable === true,
  );
});

test("connection polling times out as retryable", async () => {
  await assert.rejects(
    jobs.waitForConnectionJob(envelope("running"), async () => envelope("running"), {
      timeoutMs: 0,
      wait: async () => {},
    }),
    (error) => error.code === "CONNECTION_JOB_TIMEOUT" && error.retryable === true,
  );
});

test("connection polling honors abort", async () => {
  const controller = new AbortController();
  controller.abort(new DOMException("cancelled", "AbortError"));
  await assert.rejects(
    jobs.waitForConnectionJob(envelope("queued"), async () => envelope("queued"), {
      signal: controller.signal,
    }),
    (error) => error.name === "AbortError",
  );
});

test("connection polling retries transient request failures", async () => {
  let calls = 0;
  const result = await jobs.waitForConnectionJob(
    envelope("queued"),
    async () => {
      calls += 1;
      if (calls === 1) throw Object.assign(new Error("temporary"), { retryable: true });
      return envelope("succeeded");
    },
    { pollIntervalMs: 1, retryAttempts: 1, wait: async () => {} },
  );
  assert.equal(result.data.status, "succeeded");
  assert.equal(calls, 2);
});

test("auth oneOf exposes method selection and fields for the selected method", () => {
  const schema = {
    oneOf: [
      {
        type: "object",
        properties: {
          _auth_type: { const: "api_key", title: "API key" },
          apiKey: { type: "string", format: "password" },
        },
        required: ["apiKey"],
      },
      {
        type: "object",
        properties: {
          _auth_type: { const: "oauth2", title: "OAuth 2.0" },
        },
      },
    ],
  };
  assert.deepEqual(schemas.authSchemaOptions(schema).map((option) => option.value), ["api_key", "oauth2"]);
  assert.deepEqual(
    schemas.schemaProperties(schemas.schemaForAuth(schema, "api_key")).map(([name]) => name),
    ["apiKey"],
  );
});

test("config oneOf selects non-secret fields for the chosen auth method", () => {
  const schema = {
    oneOf: [
      {
        type: "object",
        "x-auth-type": "api_key",
        properties: { baseUrl: { type: "string" } },
        required: ["baseUrl"],
      },
      {
        type: "object",
        "x-auth-type": "custom_credential",
        properties: {
          baseUrl: { type: "string" },
          username: { type: "string" },
        },
        required: ["baseUrl", "username"],
      },
    ],
  };
  assert.deepEqual(
    schemas.schemaProperties(schemas.schemaForAuth(schema, "custom_credential")).map(([name]) => name),
    ["baseUrl", "username"],
  );
});
