/**
 * Contract-fixture browser evidence for STEP 2A.
 *
 * This file is test-only. It intercepts the same-origin BFF contract in
 * Playwright; no fixture endpoint or fallback is shipped in production.
 */
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";
const { chromium } = playwright;

const baseURL = process.env.KW_PREVIEW_URL || "http://127.0.0.1:5174";
const viewport = {
  width: Number(process.env.KW_VIEWPORT_WIDTH || 1440),
  height: Number(process.env.KW_VIEWPORT_HEIGHT || 900),
};
const screenshotName = process.env.KW_SCREENSHOT || "knowledge-workspace-desktop.png";
const screenshotDir = new URL("../../docs/knowledge-workspace/evidence/", import.meta.url);

const connection = {
  connection_id: "conn-contract",
  connector_key: "contract-http",
  display_name: "Contract API",
  scope: "personal",
  status: "ready",
  definition_version: "1",
  profile: { account: "contract-fixture" },
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
};
const draft = {
  draft_id: "draft-contract",
  goal: "让支持工程师排查线上告警并给出处理建议",
  trial_task: "查询最近一条告警",
  connection_ids: [connection.connection_id],
  lifecycle: "generated",
  current_revision_id: "revision-contract",
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
};
const revision = {
  revision_id: "revision-contract",
  draft_id: draft.draft_id,
  number: 1,
  skill_name: "support-skill",
  sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  created_at: "2026-08-27T00:00:00Z",
};
const artifact = {
  artifact_id: "artifact-contract",
  revision_id: revision.revision_id,
  invocation_id: "invocation-contract",
  media_type: "text/html",
  uri: `${baseURL}/api/knowledge/v1/artifacts/artifact-contract/content`,
  sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  title: "Contract run",
  created_at: "2026-08-27T00:00:00Z",
};

function envelope(data) {
  return JSON.stringify({ data, meta: { request_id: "req-contract" } });
}

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport });
  const calls = [];
  let published = false;
  let invocationCount = 0;
  let eventStreamCalls = 0;
  let uploadedIds = [];

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    calls.push(`${request.method()} ${url.pathname}`);

    if (url.pathname === "/oauth2/userinfo") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ sub: "contract-user", email: "contract@example.com" }) });
      return;
    }
    if (url.pathname === "/web/auth-config") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ providers: [] }) });
      return;
    }
    if (!url.pathname.startsWith("/api/knowledge/v1")) {
      await route.continue();
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connector-definitions") {
      await route.fulfill({
        status: 200,
        headers: { ETag: "connectors-v1" },
        contentType: "application/json",
        body: envelope([{
          connector_key: "contract-http",
          version: "1",
          display_name: "Contract API",
          category: "HTTP",
          status: "verified",
          capabilities: ["validate", "discover", "action", "api_key", "http"],
          config_schema: { type: "object", properties: { base_url: { title: "服务地址", type: "string" } } },
          auth_schema: { type: "object", properties: { api_key: { title: "API Key", type: "string", format: "password" } } },
        }]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connections" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([connection]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connections" && request.method() === "POST") {
      await route.fulfill({ status: 201, headers: { ETag: "connection-v1" }, contentType: "application/json", body: envelope(connection) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/uploads" && request.method() === "POST") {
      uploadedIds = ["upload-contract"];
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: envelope({
          upload_id: "upload-contract",
          filename: "incident.txt",
          sha256: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          size_bytes: 12,
          media_type: "text/plain",
        }),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([draft]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}");
      assert.deepEqual(body.upload_ids, uploadedIds);
      await route.fulfill({ status: 201, headers: { ETag: "draft-v1" }, contentType: "application/json", body: envelope(draft) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}`) {
      await route.fulfill({ status: 200, headers: { ETag: "draft-v1" }, contentType: "application/json", body: envelope(draft) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/revisions`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([revision]) });
      return;
    }
    if (url.pathname.endsWith("/generate")) {
      invocationCount += 1;
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope({
        invocation_id: "invocation-contract",
        kind: "generate",
        status: "running",
        event_url: "/api/knowledge/v1/invocations/invocation-contract/events",
        created_at: "2026-08-27T00:00:00Z",
      }) });
      return;
    }
    if (url.pathname.endsWith("/messages")) {
      invocationCount += 1;
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope({
        invocation_id: "invocation-contract",
        kind: "update",
        status: "running",
        event_url: "/api/knowledge/v1/invocations/invocation-contract/events",
        created_at: "2026-08-27T00:00:00Z",
      }) });
      return;
    }
    if (url.pathname.endsWith("/events")) {
      eventStreamCalls += 1;
      const reconnectOnlyFrames = eventStreamCalls === 1;
      const failedFrames = eventStreamCalls === 3;
      const frames = [
        `id: evt-1\nevent: run.started\ndata: ${JSON.stringify({ id: "evt-1", type: "run.started", invocation_id: "invocation-contract", occurred_at: "2026-08-27T00:00:00Z", data: { kind: "generate", status: "running" } })}\n\n`,
        `id: evt-2\nevent: plan.updated\ndata: ${JSON.stringify({ id: "evt-2", type: "plan.updated", invocation_id: "invocation-contract", occurred_at: "2026-08-27T00:00:00Z", data: { steps: [{ id: "step-1", label: "读取真实连接", status: "completed" }] } })}\n\n`,
        `id: evt-3\nevent: assistant.delta\ndata: ${JSON.stringify({ id: "evt-3", type: "assistant.delta", invocation_id: "invocation-contract", occurred_at: "2026-08-27T00:00:00Z", data: { text: reconnectOnlyFrames ? "连接中断，等待重连。" : failedFrames ? "本次运行即将失败。" : "已完成真实连接试跑。", sequence: 0 } })}\n\n`,
        `id: evt-4\nevent: artifact.created\ndata: ${JSON.stringify({ id: "evt-4", type: "artifact.created", invocation_id: "invocation-contract", occurred_at: "2026-08-27T00:00:00Z", data: { artifact_id: artifact.artifact_id, revision_id: artifact.revision_id, media_type: artifact.media_type, sha256: artifact.sha256 } })}\n\n`,
        `id: evt-5\nevent: revision.created\ndata: ${JSON.stringify({ id: "evt-5", type: "revision.created", invocation_id: "invocation-contract", occurred_at: "2026-08-27T00:00:00Z", data: { revision_id: revision.revision_id, draft_id: draft.draft_id, number: 1, sha256: revision.sha256 } })}\n\n`,
        failedFrames
          ? `id: evt-6\nevent: run.failed\ndata: ${JSON.stringify({ id: "evt-6", type: "run.failed", invocation_id: "invocation-contract", occurred_at: "2026-08-27T00:00:00Z", data: { status: "failed", finished_at: "2026-08-27T00:00:01Z", error: { code: "AUTOSKILL_UNAVAILABLE", message: "试跑服务暂不可用。", retryable: true } } })}\n\n`
          : `id: evt-6\nevent: run.completed\ndata: ${JSON.stringify({ id: "evt-6", type: "run.completed", invocation_id: "invocation-contract", occurred_at: "2026-08-27T00:00:00Z", data: { status: "succeeded", finished_at: "2026-08-27T00:00:01Z", revision_id: revision.revision_id, artifact_ids: [artifact.artifact_id] } })}\n\n`,
      ].slice(0, reconnectOnlyFrames ? 3 : undefined).join("");
      await route.fulfill({ status: 200, headers: { "Content-Type": "text/event-stream" }, body: frames });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/artifacts/${artifact.artifact_id}`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope(artifact) });
      return;
    }
    if (url.pathname.endsWith("/publish")) {
      published = true;
      await route.fulfill({ status: 201, contentType: "application/json", body: envelope({
        publication_id: "publication-contract",
        revision_id: revision.revision_id,
        target_space: "personal",
        status: "published",
        created_at: "2026-08-27T00:00:00Z",
      }) });
      return;
    }
    if (url.pathname.endsWith("/content")) {
      await route.fulfill({ status: 200, headers: { "Content-Security-Policy": "default-src 'none'" }, contentType: "text/html", body: "<!doctype html><title>Contract Artifact</title><p>real lineage</p>" });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "NOT_FOUND", message: "fixture route missing", retryable: false }, meta: { request_id: "req-contract" } }) });
  });

  await page.goto(`${baseURL}/?view=knowledge-workspace&file=welcome`);
  await page.getByRole("complementary").getByRole("button", { name: "添加连接" }).click();
  await page.getByRole("combobox", { name: "连接类型" }).selectOption("contract-http");
  await page.getByLabel("显示名称").fill("Contract API");
  await page.getByLabel("服务地址").fill("https://contract.invalid");
  await page.getByLabel("API Key").fill("redacted-in-test");
  await page.getByRole("button", { name: "保存并验证" }).click();
  await page.getByRole("button", { name: "新建 Skill" }).click();
  await page.getByRole("checkbox", { name: /Contract API/ }).check();
  await page.getByLabel("谁使用，解决什么问题？").fill("让支持工程师排查线上告警并给出处理建议");
  await page.getByLabel("可选：先试一句真实任务").fill("查询最近一条告警");
  await page.locator('input[type="file"]').setInputFiles({
    name: "incident.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("incident data"),
  });
  await page.getByText(/incident\.txt/).waitFor();
  await page.getByRole("button", { name: "生成并试用 Skill" }).click();
  await page.getByRole("button", { name: /重连/ }).waitFor();
  assert.equal(eventStreamCalls, 1);
  await page.getByRole("button", { name: /重连/ }).click();
  await page.getByText("已完成真实连接试跑。").waitFor();
  await page.getByPlaceholder("描述修改，或输入任务试跑…").fill("再次检查");
  await page.getByRole("button", { name: "试跑" }).click();
  await page.getByRole("button", { name: "重试本次运行" }).waitFor();
  await page.getByRole("button", { name: "重试本次运行" }).click();
  await page.getByText("已完成真实连接试跑。").waitFor();
  await page.getByRole("button", { name: "版本" }).click();
  await page.getByText("v1 · support-skill").waitFor();
  await page.getByRole("button", { name: "关闭" }).click();
  await page.getByRole("button", { name: "发布" }).click();
  await page.getByRole("button", { name: "发布到个人" }).click();
  await page.waitForURL(/file=published/);
  await page.reload();
  await page.getByRole("button", { name: "返回工作台" }).waitFor();
  await page.screenshot({ path: new URL(screenshotName, screenshotDir).pathname, fullPage: true });
  await page.getByRole("button", { name: "返回工作台" }).click();
  await page.getByText("让 Agent 帮你解决一个真实问题").waitFor();
  assert.match(new URL(page.url()).search, /file=welcome/);

  assert.equal(invocationCount, 3);
  assert.equal(eventStreamCalls, 4);
  assert.equal(published, true);
  assert.ok(calls.some((call) => call.includes("/events")));
  assert.ok(calls.some((call) => call.includes("/publish")));
  console.log(JSON.stringify({
    contract_fixture: true,
    viewport: `${viewport.width}x${viewport.height}`,
    clicked: ["添加连接", "多选连接", "生成", "SSE 对话", "失败重连", "版本", "发布", "刷新恢复", "右栏布局"],
    screenshot: `docs/knowledge-workspace/evidence/${screenshotName}`,
    invocation_count: invocationCount,
    published,
  }));
  await browser.close();
}

await main();
