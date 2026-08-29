import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const baseURL = process.env.KW_PREVIEW_URL || "http://127.0.0.1:5174";
const viewport = {
  width: Number(process.env.KW_VIEWPORT_WIDTH || 1440),
  height: Number(process.env.KW_VIEWPORT_HEIGHT || 900),
};
const screenshotName = process.env.KW_SCREENSHOT || "assistant-desktop-1440x900.png";
const screenshotDir = process.env.KW_SCREENSHOT_DIR
  ? path.resolve(process.env.KW_SCREENSHOT_DIR)
  : new URL("../../docs/knowledge-workspace/evidence/assistant-ux/", import.meta.url).pathname;

const draft = {
  draft_id: "draft-assistant-evidence",
  goal: "分析告警并生成安全的处置建议",
  trial_task: "检查最近的支付告警",
  template_key: "sop",
  template_config: { mode: "evidence_sop" },
  connection_ids: ["conn-evidence"],
  resource_ids: [],
  lifecycle: "generated",
  current_revision_id: "revision-evidence",
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:02:00Z",
};
const connection = {
  connection_id: "conn-evidence",
  connector_key: "evidence",
  display_name: "生产指标",
  scope: "team",
  status: "ready",
  definition_version: "1",
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
};
const revision = {
  revision_id: "revision-evidence",
  draft_id: draft.draft_id,
  number: 1,
  skill_name: "incident-analysis",
  template_key: draft.template_key,
  template_config: draft.template_config,
  sha256: "a".repeat(64),
  created_at: "2026-08-28T00:02:00Z",
};

function envelope(data) {
  return JSON.stringify({ data, meta: { request_id: "request-evidence" } });
}

function event(invocationId, id, cursor, type, data, parentId) {
  return {
    id,
    cursor: String(cursor),
    type,
    invocation_id: invocationId,
    occurred_at: `2026-08-28T00:00:${String(cursor).padStart(2, "0")}Z`,
    ...(parentId ? { parent_id: parentId } : {}),
    data,
  };
}

const firstInvocation = {
  invocation_id: "invocation-first",
  kind: "run",
  status: "succeeded",
  message: "检查最近的支付告警",
  model: "doubao-seed",
  event_url: "/api/knowledge/v1/invocations/invocation-first/events",
  started_at: "2026-08-28T00:00:00Z",
  finished_at: "2026-08-28T00:00:05Z",
  created_at: "2026-08-28T00:00:00Z",
};
const secondInvocation = {
  invocation_id: "invocation-second",
  kind: "update",
  status: "succeeded",
  message: "补充表格和可执行步骤",
  model: "doubao-seed",
  event_url: "/api/knowledge/v1/invocations/invocation-second/events",
  started_at: "2026-08-28T00:01:00Z",
  finished_at: "2026-08-28T00:01:08Z",
  created_at: "2026-08-28T00:01:00Z",
};

const conversation = [
  {
    invocation: firstInvocation,
    events: [
      event("invocation-first", "turn-1", 1, "turn.started", {
        turn_number: 1,
        title: "查询支付告警",
        status: "running",
      }),
      event("invocation-first", "plan-1", 2, "activity.started", {
        activity_id: "plan-1",
        activity_kind: "planning",
        title: "定位异常订单",
        status: "running",
        steps: [{ id: "step-1", label: "读取告警摘要", status: "running" }],
      }, "turn-1"),
      event("invocation-first", "action-1", 3, "activity.started", {
        activity_id: "call-1",
        activity_kind: "tool",
        call_id: "call-1",
        tool_name: "查询生产指标",
        status: "running",
        input_summary: "查询最近 15 分钟的聚合指标",
      }, "turn-1"),
      event("invocation-first", "observation-1", 4, "activity.completed", {
        activity_id: "call-1",
        activity_kind: "tool",
        call_id: "call-1",
        status: "succeeded",
        output_summary: "发现支付成功率低于基线",
        duration_ms: 1830,
      }, "call-1"),
      event("invocation-first", "final-1", 5, "assistant.final", {
        content: "## 初步结论\n\n支付成功率出现下降，建议继续核对渠道分布。",
      }),
      event("invocation-first", "summary-1", 6, "request.summary", {
        status: "succeeded",
        model: "doubao-seed",
        skills: { used: 1, created: 0, updated: 0 },
        usage: { total_tokens: 428 },
      }),
      event("invocation-first", "state-1", 7, "state.updated", {
        remote_saved: true,
      }),
      event("invocation-first", "complete-1", 8, "run.completed", {
        status: "succeeded",
        finished_at: "2026-08-28T00:00:05Z",
      }),
    ],
  },
  {
    invocation: secondInvocation,
    events: [
      event("invocation-second", "turn-2", 1, "turn.started", {
        turn_number: 2,
        title: "生成处置建议",
        status: "running",
      }),
      event("invocation-second", "action-2", 2, "activity.started", {
        activity_id: "call-2",
        activity_kind: "tool",
        call_id: "call-2",
        tool_name: "读取渠道分布",
        status: "running",
      }, "turn-2"),
      event("invocation-second", "observation-2", 3, "activity.completed", {
        activity_id: "call-2",
        activity_kind: "tool",
        call_id: "call-2",
        status: "succeeded",
        output_summary: "异常集中在渠道 B",
        duration_ms: 2240,
      }, "call-2"),
      event("invocation-second", "final-2", 4, "assistant.final", {
        content: [
          "# 处置建议",
          "",
          "| 优先级 | 动作 |",
          "| --- | --- |",
          "| P0 | 暂停渠道 B 的异常路由 |",
          "| P1 | 对账并回补失败订单 |",
          "",
          "```sql",
          "SELECT channel, COUNT(*) FROM payments GROUP BY channel;",
          "```",
          "",
          "[查看已持久化报告](/api/knowledge/v1/artifacts/artifact-evidence/content)",
          "",
          "长链接换行验证：https://example.com/reports/this/is/a/very/long/path/that/must/not/overflow/the/assistant/sidebar",
        ].join("\n"),
      }),
      event("invocation-second", "summary-2", 5, "request.summary", {
        status: "succeeded",
        model: "doubao-seed",
        skills: { used: 1, created: 0, updated: 1 },
        usage: { total_tokens: 812, total_input_tokens: 500, total_output_tokens: 312 },
      }),
      event("invocation-second", "state-2", 6, "state.updated", {
        remote_saved: true,
      }),
      event("invocation-second", "complete-2", 7, "run.completed", {
        status: "succeeded",
        finished_at: "2026-08-28T00:01:08Z",
      }),
    ],
  },
];

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/oauth2/userinfo") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ sub: "evidence-user", email: "evidence@example.com" }),
      });
      return;
    }
    if (url.pathname === "/web/auth-config") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ providers: [] }),
      });
      return;
    }
    if (!url.pathname.startsWith("/api/knowledge/v1")) {
      await route.continue();
      return;
    }
    const response = (data, headers = {}) => route.fulfill({
      status: 200,
      headers,
      contentType: "application/json",
      body: envelope(data),
    });
    if (url.pathname === "/api/knowledge/v1/connector-definitions") return response([]);
    if (url.pathname === "/api/knowledge/v1/connections") return response([connection]);
    if (url.pathname === "/api/knowledge/v1/skills/drafts") return response([draft]);
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}`) {
      return response(draft, { ETag: "draft-evidence-v1" });
    }
    if (url.pathname.endsWith("/revisions")) return response([revision]);
    if (url.pathname.endsWith("/conversation")) return response(conversation);
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "NOT_FOUND", message: "evidence route missing", retryable: false },
        meta: { request_id: "request-evidence" },
      }),
    });
  });

  await page.goto(
    `${baseURL}/?view=knowledge-workspace&file=draft&draftId=${draft.draft_id}`,
  );
  const assistant = page.getByRole("complementary", { name: "分析助手" });
  await assistant.getByRole("heading", { name: "处置建议" }).waitFor();
  assert.equal(await assistant.locator(".kw-user-message").count(), 2);
  assert.equal(await assistant.locator(".kw-activity").count(), 5);
  assert.equal(await assistant.locator("script").count(), 0);
  assert.equal(await assistant.locator(".kw-activity-timeline[open]").count(), 0);
  assert.equal(
    await assistant.getByRole("link", { name: "查看已持久化报告" }).getAttribute("href"),
    "/api/knowledge/v1/artifacts/artifact-evidence/content",
  );
  const toolSummaries = assistant.locator(".kw-activity-timeline > summary");
  await toolSummaries.last().click();
  assert.equal(await assistant.locator(".kw-activity-timeline[open]").count(), 1);

  const box = await assistant.boundingBox();
  assert.ok(box);
  if (viewport.width >= 900) {
    assert.ok(box.width >= 379 && box.width <= 381, JSON.stringify(box));
  } else {
    await assistant.scrollIntoViewIfNeeded();
    assert.ok(box.width <= viewport.width, JSON.stringify(box));
  }
  const overflow = await assistant.evaluate((node) => ({
    clientWidth: node.clientWidth,
    scrollWidth: node.scrollWidth,
  }));
  assert.ok(
    overflow.scrollWidth <= overflow.clientWidth + 1,
    JSON.stringify(overflow),
  );

  await page.screenshot({
    path: path.join(screenshotDir, screenshotName),
    fullPage: false,
  });
  console.log(JSON.stringify({
    contract_fixture: true,
    viewport: `${viewport.width}x${viewport.height}`,
    screenshot: path.join(screenshotDir, screenshotName),
    turns: 2,
    merged_tool_activities: 2,
    markdown: ["heading", "table", "code", "artifact-link", "long-url"],
  }));
  await browser.close();
}

await main();
