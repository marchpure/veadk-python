import assert from "node:assert/strict";
import test from "node:test";

import {
  classifyFailedRequest,
  evaluateEvidenceGate,
} from "../scripts/knowledge_step3b_w4_v2152_visual_evidence.mjs";

function entry(overrides = {}) {
  return {
    viewport: "desktop-1920",
    state: "home",
    checks: {
      layoutFailures: [],
      consoleErrors: [],
      pageErrors: [],
      responseErrors: [],
      failedRequests: [],
      keyboardFailures: [],
      agentPaneFailures: [],
      ...(overrides.checks ?? {}),
    },
    ...overrides,
  };
}

test("critical knowledge-assets API abort fails the evidence gate", () => {
  const gate = evaluateEvidenceGate([
    entry({
      checks: {
        failedRequests: [
          {
            url: "http://127.0.0.1:5179/api/knowledge-assets/v1/bootstrap",
            failure: "net::ERR_ABORTED",
            method: "GET",
            resourceType: "fetch",
            action: "playwright-navigation:agent-pane-width",
          },
        ],
      },
    }),
  ], { status: "pass" });

  assert.equal(gate.status, "fail");
  assert.equal(gate.failedRequestsTotal, 1);
  assert.equal(gate.unhandledFailedRequests.length, 1);
  assert.match(gate.failures.join("\n"), /critical business API aborted/);
});

test("unclassified requestfailed events fail the evidence gate", () => {
  const gate = evaluateEvidenceGate([
    entry({
      checks: {
        failedRequests: [
          {
            url: "http://127.0.0.1:5179/assets/app.js",
            failure: "net::ERR_FAILED",
            method: "GET",
            resourceType: "script",
            action: "initial-capture",
          },
        ],
      },
    }),
  ], { status: "pass" });

  assert.equal(gate.status, "fail");
  assert.match(gate.failures.join("\n"), /request failed/);
});

test("console and page errors fail the evidence gate", () => {
  const gate = evaluateEvidenceGate([
    entry({
      checks: {
        consoleErrors: ["boom from console"],
        pageErrors: ["unhandled rejection"],
      },
    }),
  ], { status: "pass" });

  assert.equal(gate.status, "fail");
  assert.match(gate.failures.join("\n"), /console boom from console/);
  assert.match(gate.failures.join("\n"), /page unhandled rejection/);
});

test("only explicitly documented non-business navigation aborts can be ignored", () => {
  const ignored = classifyFailedRequest({
    url: "http://127.0.0.1:5179/__vite_ping",
    failure: "net::ERR_ABORTED",
    method: "GET",
    resourceType: "other",
    action: "playwright-navigation:agent-pane-width",
  });
  const critical = classifyFailedRequest({
    url: "http://127.0.0.1:5179/api/knowledge-assets/v1/bootstrap",
    failure: "net::ERR_ABORTED",
    method: "GET",
    resourceType: "fetch",
    action: "playwright-navigation:agent-pane-width",
  });

  assert.equal(ignored.ignored, true);
  assert.match(ignored.reason, /dev-server navigation abort/);
  assert.equal(critical.ignored, false);
  assert.match(critical.reason, /critical business API aborted/);
});

test("top-level status is consistent with internal failed request gates", () => {
  const gate = evaluateEvidenceGate([
    entry({
      checks: {
        failedRequests: [
          {
            url: "http://127.0.0.1:5179/__w4_v2152_artifacts/draft.html",
            failure: "net::ERR_ABORTED",
            method: "GET",
            resourceType: "fetch",
            action: "page-close-after-capture",
          },
        ],
      },
    }),
  ], { status: "pass" });

  assert.equal(gate.status, "fail");
  assert.equal(gate.ignoredRequestsTotal, 0);
  assert.match(gate.failures.join("\n"), /request failed/);
});
