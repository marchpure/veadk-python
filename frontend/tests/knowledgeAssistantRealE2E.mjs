import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import http from "node:http";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const frontendURL = process.env.KW_REAL_FRONTEND_URL || "http://127.0.0.1:5173";
const bffURL = process.env.KW_REAL_BFF_URL || "http://127.0.0.1:8017";
const draftId = process.env.KW_REAL_DRAFT_ID;
const evidenceDir = new URL(
  "../../docs/knowledge-workspace/evidence/assistant-ux/",
  import.meta.url,
);

assert.ok(draftId, "KW_REAL_DRAFT_ID is required");

let cutFirstEventStream = true;
const proxyRequests = [];
const proxy = http.createServer((request, response) => {
  const target = new URL(request.url || "/", bffURL);
  const headers = { ...request.headers, host: target.host };
  delete headers.origin;
  delete headers.referer;
  const upstream = http.request(target, {
    method: request.method,
    headers,
  }, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    const isEventStream = target.pathname.endsWith("/events");
    proxyRequests.push({
      eventStream: isEventStream,
      lastEventId: String(request.headers["last-event-id"] || "") || null,
    });
    if (!isEventStream || !cutFirstEventStream) {
      upstreamResponse.pipe(response);
      return;
    }
    cutFirstEventStream = false;
    let pending = "";
    let eventFrames = 0;
    upstreamResponse.setEncoding("utf8");
    upstreamResponse.on("data", (chunk) => {
      pending += chunk;
      for (;;) {
        const boundary = pending.indexOf("\n\n");
        if (boundary < 0) return;
        const frame = pending.slice(0, boundary + 2);
        pending = pending.slice(boundary + 2);
        response.write(frame);
        if (frame.startsWith("id: ")) eventFrames += 1;
        if (eventFrames >= 3) {
          response.destroy();
          upstreamResponse.destroy();
          return;
        }
      }
    });
    upstreamResponse.on("end", () => response.end(pending));
  });
  upstream.on("error", () => response.destroy());
  request.pipe(upstream);
});
await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));
const proxyAddress = proxy.address();
assert.ok(proxyAddress && typeof proxyAddress === "object");
const proxyURL = `http://127.0.0.1:${proxyAddress.port}`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();

await page.route("**/oauth2/userinfo", (route) => route.fulfill({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify({
    sub: "real-browser-e2e",
    email: "real-browser-e2e@example.invalid",
  }),
}));
await page.route("**/api/knowledge/v1/**", (route) => {
  const url = new URL(route.request().url());
  const target = new URL(proxyURL);
  url.protocol = target.protocol;
  url.hostname = target.hostname;
  url.port = target.port;
  const headers = { ...route.request().headers() };
  delete headers.origin;
  delete headers.referer;
  return route.continue({ url: url.toString(), headers });
});
try {
  await mkdir(evidenceDir, { recursive: true });
  await page.goto(
    `${frontendURL}/?view=knowledge-workspace&file=draft&draftId=${encodeURIComponent(draftId)}`,
  );
  const assistant = page.getByRole("complementary", { name: "分析助手" });
  await assistant.waitFor();
  const startButton = page.getByRole("button", { name: "开始", exact: true });
  await startButton.waitFor();
  await assert.doesNotReject(async () => {
    await startButton.waitFor({ state: "visible" });
    await page.waitForFunction(
      () => {
        const button = [...document.querySelectorAll("button")]
          .find((node) => node.textContent?.trim() === "开始");
        return button instanceof HTMLButtonElement && !button.disabled;
      },
      undefined,
      { timeout: 60_000 },
    );
  });
  const generateResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/skills/drafts/${draftId}/messages`)
      && response.request().method() === "POST",
    { timeout: 60_000 },
  );
  await startButton.click();
  assert.equal((await generateResponse).status(), 202);

  const turn = assistant.locator(".kw-conversation-turn").last();
  await turn.locator(".kw-activity").first().waitFor({ timeout: 240_000 });
  const beforeDisconnect = await turn.locator(".kw-activity").count();
  assert.ok(beforeDisconnect > 0);

  await turn.getByRole("button", { name: "继续接收" }).waitFor({ timeout: 30_000 });
  await turn.getByRole("button", { name: "继续接收" }).click();

  await turn.locator(".kw-assistant-message").waitFor({ timeout: 600_000 });
  await page.getByRole("button", { name: "停止" }).waitFor({
    state: "detached",
    timeout: 600_000,
  });

  const invocationId = await turn.getAttribute("data-invocation-id");
  assert.ok(invocationId);
  const beforeReload = {
    turns: await assistant.locator(".kw-conversation-turn").count(),
    activities: await turn.locator(".kw-activity").count(),
    assistantText: (await turn.locator(".kw-assistant-message").innerText()).trim(),
  };
  assert.ok(beforeReload.activities >= beforeDisconnect);
  assert.ok(beforeReload.assistantText.length > 0);
  assert.ok(
    await turn.locator(
      ".kw-assistant-message h1, .kw-assistant-message h2, .kw-assistant-message h3, "
      + ".kw-assistant-message ul, .kw-assistant-message ol, .kw-assistant-message table, "
      + ".kw-assistant-message pre",
    ).count(),
    "final answer was not rendered as Markdown",
  );

  const resumed = proxyRequests.find(
    (request) => request.eventStream && request.lastEventId !== null,
  );
  assert.ok(resumed, "reconnect did not send Last-Event-ID");
  assert.match(resumed.lastEventId, /^\d+$/);

  await page.screenshot({
    path: new URL("assistant-real-desktop-1440x900.png", evidenceDir).pathname,
  });
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.goto(
    `${frontendURL}/?view=knowledge-workspace&file=draft&draftId=${encodeURIComponent(draftId)}`,
    { waitUntil: "domcontentloaded" },
  );
  const restoredAssistant = page.getByRole("complementary", { name: "分析助手" });
  await restoredAssistant.waitFor({ timeout: 60_000 });
  const restoredTurn = restoredAssistant.locator(
    `.kw-conversation-turn[data-invocation-id="${invocationId}"]`,
  );
  await restoredTurn.locator(".kw-assistant-message").waitFor({ timeout: 60_000 });
  const afterReload = {
    turns: await restoredAssistant.locator(".kw-conversation-turn").count(),
    activities: await restoredTurn.locator(".kw-activity").count(),
    assistantText: (await restoredTurn.locator(".kw-assistant-message").innerText()).trim(),
  };
  assert.deepEqual(afterReload, beforeReload);
  const conversationSummary = await page.evaluate(async ({ id, invocationId }) => {
    const response = await fetch(
      `/api/knowledge/v1/skills/drafts/${encodeURIComponent(id)}/conversation`,
    );
    assertResponse(response);
    const payload = await response.json();
    const current = payload.data.find(
      (entry) => entry.invocation.invocation_id === invocationId,
    );
    if (!current) throw new Error("current invocation missing from conversation");
    const events = current.events;
    const types = events.map((event) => event.type).filter(Boolean);
    return {
      event_count: events.length,
      event_types: [...new Set(types)],
      upstream_turns: types.filter((type) => type === "turn.started").length,
      activity_started: types.filter((type) => type === "activity.started").length,
      activity_completed: types.filter((type) => type === "activity.completed").length,
      final_answers: types.filter((type) => type === "assistant.final").length,
    };

    function assertResponse(response) {
      if (!response.ok) throw new Error(`conversation returned HTTP ${response.status}`);
    }
  }, { id: draftId, invocationId });
  assert.ok(conversationSummary.upstream_turns >= 2);
  assert.equal(conversationSummary.final_answers, 1);

  await page.setViewportSize({ width: 390, height: 844 });
  await restoredAssistant.scrollIntoViewIfNeeded();
  const bounds = await restoredAssistant.boundingBox();
  assert.ok(bounds && bounds.width <= 390);
  const overflow = await restoredAssistant.evaluate((node) => ({
    clientWidth: node.clientWidth,
    scrollWidth: node.scrollWidth,
  }));
  assert.ok(overflow.scrollWidth <= overflow.clientWidth + 1, JSON.stringify(overflow));
  await page.screenshot({
    path: new URL("assistant-real-mobile-390x844.png", evidenceDir).pathname,
  });

  const evidence = {
    status: "PASS",
    official_autoskill: true,
    real_bff: true,
    viewport: ["1440x900", "390x844"],
    disconnect: {
      observed: true,
      forced_after_event_frames: 3,
      reconnect_last_event_id: resumed.lastEventId,
    },
    deduplication: {
      activities_before_reload: beforeReload.activities,
      activities_after_reload: afterReload.activities,
      turns_before_reload: beforeReload.turns,
      turns_after_reload: afterReload.turns,
    },
    semantic_sse: conversationSummary,
    durable_refresh_restore: true,
    browser_storage_cleared_before_restore: true,
    markdown_final: true,
    screenshots: [
      "assistant-real-desktop-1440x900.png",
      "assistant-real-mobile-390x844.png",
    ],
  };
  await writeFile(
    new URL("real-browser-e2e.json", evidenceDir),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  console.log(JSON.stringify(evidence));
} finally {
  await browser.close();
  await new Promise((resolve) => proxy.close(resolve));
}
