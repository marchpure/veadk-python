/**
 * Contract-fixture browser evidence for STEP 2A.
 *
 * This file is test-only. It intercepts the same-origin BFF contract in
 * Playwright; no fixture endpoint or fallback is shipped in production.
 */
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
const screenshotName = process.env.KW_SCREENSHOT || "knowledge-workspace-desktop.png";
const screenshotDir = process.env.KW_SCREENSHOT_DIR
  ? path.resolve(process.env.KW_SCREENSHOT_DIR)
  : new URL("../../docs/knowledge-workspace/evidence/", import.meta.url).pathname;

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
  template_key: "sop",
  template_config: { mode: "evidence_sop" },
  connection_ids: [connection.connection_id],
  resource_ids: [],
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
  template_key: draft.template_key,
  template_config: draft.template_config,
  sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  manifest: {
    template_key: draft.template_key,
    template_config: draft.template_config,
    zip: {
      paths: [
        "skillhub/support-skill/SKILL.md",
        "skillhub/support-skill/scripts/run.py",
        "skillhub/support-skill/tests/test_skill.py",
      ],
    },
  },
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
  lineage: {
    template_key: draft.template_key,
    revision_id: revision.revision_id,
    invocation_id: "invocation-contract",
    source_refs: { connection_ids: draft.connection_ids, resource_ids: [], upload_ids: [] },
  },
  csp: "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'",
  sandbox: "allow-scripts",
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
  let validationCalls = 0;
  let currentInvocationId = "invocation-contract-0";
  let conversationCalls = 0;
  let nextRunShouldFail = false;
  const failedInvocationIds = new Set();

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
    if (url.pathname.endsWith("/validate") && request.method() === "POST") {
      validationCalls += 1;
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: envelope({ job_id: "validation-contract", status: "queued" }),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connection-jobs/validation-contract") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope({ job_id: "validation-contract", status: "succeeded" }),
      });
      return;
    }
    if (url.pathname.endsWith("/discover") && request.method() === "POST") {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: envelope({ job_id: "discovery-contract", status: "queued" }),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connector-definitions") {
      await route.fulfill({
        status: 200,
        headers: { ETag: "connectors-v1" },
        contentType: "application/json",
        body: envelope([{
          connector_key: "hackernews",
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
    if (url.pathname === `/api/knowledge/v1/connections/${connection.connection_id}` && request.method() === "GET") {
      await route.fulfill({ status: 200, headers: { ETag: "connection-v1" }, contentType: "application/json", body: envelope(connection) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/resources" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([]) });
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
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/conversation`) {
      conversationCalls += 1;
      const history = conversationCalls === 1
        ? [{
          invocation: {
            invocation_id: currentInvocationId,
            draft_id: draft.draft_id,
            kind: "generate",
            status: "running",
            message: draft.trial_task,
            event_url: `/api/knowledge/v1/invocations/${currentInvocationId}/events`,
            created_at: "2026-08-27T00:00:00Z",
          },
          events: [],
        }]
        : [];
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope(history) });
      return;
    }
    if (url.pathname.endsWith("/generate")) {
      invocationCount += 1;
      currentInvocationId = `invocation-contract-${invocationCount}`;
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope({
        invocation_id: currentInvocationId,
        kind: "generate",
        status: "running",
        event_url: `/api/knowledge/v1/invocations/${currentInvocationId}/events`,
        created_at: "2026-08-27T00:00:00Z",
      }) });
      return;
    }
    if (url.pathname.endsWith("/messages")) {
      invocationCount += 1;
      currentInvocationId = `invocation-contract-${invocationCount}`;
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope({
        invocation_id: currentInvocationId,
        kind: "update",
        status: "running",
        event_url: `/api/knowledge/v1/invocations/${currentInvocationId}/events`,
        created_at: "2026-08-27T00:00:00Z",
      }) });
      return;
    }
    if (url.pathname.endsWith("/run")) {
      invocationCount += 1;
      currentInvocationId = `invocation-contract-${invocationCount}`;
      if (nextRunShouldFail) {
        failedInvocationIds.add(currentInvocationId);
        nextRunShouldFail = false;
      }
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope({
        invocation_id: currentInvocationId,
        kind: "run",
        status: "running",
        event_url: `/api/knowledge/v1/invocations/${currentInvocationId}/events`,
        created_at: "2026-08-27T00:00:00Z",
      }) });
      return;
    }
    if (url.pathname.endsWith("/events")) {
      eventStreamCalls += 1;
      const reconnectOnlyFrames = eventStreamCalls === 1;
      const failedFrames = failedInvocationIds.has(currentInvocationId);
      const frames = [
        `id: 1\nevent: run.started\ndata: ${JSON.stringify({ id: "run-1", cursor: "1", type: "run.started", invocation_id: currentInvocationId, occurred_at: "2026-08-27T00:00:00Z", data: { kind: "generate", status: "running" } })}\n\n`,
        `id: 2\nevent: activity.started\ndata: ${JSON.stringify({ id: "plan-1", cursor: "2", type: "activity.started", invocation_id: currentInvocationId, occurred_at: "2026-08-27T00:00:00Z", data: { activity_id: "plan-1", activity_kind: "planning", title: "规划", status: "running", steps: [{ id: "step-1", label: "读取真实连接", status: "completed" }] } })}\n\n`,
        `id: 3\nevent: assistant.final\ndata: ${JSON.stringify({ id: "final-1", cursor: "3", type: "assistant.final", invocation_id: currentInvocationId, occurred_at: "2026-08-27T00:00:00Z", data: { content: failedFrames ? "本次运行即将失败。" : "已完成真实连接试跑。" } })}\n\n`,
        `id: 4\nevent: artifact.created\ndata: ${JSON.stringify({ id: "artifact-1", cursor: "4", type: "artifact.created", invocation_id: currentInvocationId, occurred_at: "2026-08-27T00:00:00Z", data: { artifact_id: artifact.artifact_id, revision_id: artifact.revision_id, media_type: artifact.media_type, sha256: artifact.sha256 } })}\n\n`,
        `id: 5\nevent: revision.created\ndata: ${JSON.stringify({ id: "revision-1", cursor: "5", type: "revision.created", invocation_id: currentInvocationId, occurred_at: "2026-08-27T00:00:00Z", data: { revision_id: revision.revision_id, draft_id: draft.draft_id, number: 1, sha256: revision.sha256 } })}\n\n`,
        failedFrames
          ? `id: 6\nevent: run.failed\ndata: ${JSON.stringify({ id: "failed-1", cursor: "6", type: "run.failed", invocation_id: currentInvocationId, occurred_at: "2026-08-27T00:00:00Z", data: { status: "failed", finished_at: "2026-08-27T00:00:01Z", error: { code: "AUTOSKILL_UNAVAILABLE", message: "试跑服务暂不可用。", retryable: true } } })}\n\n`
          : `id: 6\nevent: run.completed\ndata: ${JSON.stringify({ id: "complete-1", cursor: "6", type: "run.completed", invocation_id: currentInvocationId, occurred_at: "2026-08-27T00:00:00Z", data: { status: "succeeded", finished_at: "2026-08-27T00:00:01Z", revision_id: revision.revision_id, artifact_ids: [artifact.artifact_id] } })}\n\n`,
      ].slice(0, reconnectOnlyFrames ? 2 : undefined).join("");
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
  if (viewport.width >= 720) {
    await page.getByRole("button", { name: "创建", exact: true }).click();
  } else {
    await page.goto(`${baseURL}/?view=knowledge-workspace&file=skill_new`);
  }
  await page.getByRole("button", { name: /添加连接/ }).first().click();
  assert.equal(await page.getByRole("combobox", { name: "连接类型" }).count(), 0);
  await page.locator(".kw-connector-card").first().click();
  await page.getByLabel("显示名称").fill("Contract API");
  await page.getByLabel("服务地址").fill("https://contract.invalid");
  await page.getByLabel("API Key").fill("redacted-in-test");
  await page.getByRole("button", { name: "保存并验证" }).click();
  await page.getByRole("button", { name: "取消" }).click();
  await page.getByRole("heading", { name: "Contract API" }).waitFor();
  if (viewport.width >= 720) {
    await page.getByRole("complementary").getByRole("button", { name: "新建 Skill" }).click();
  } else {
    await page.goto(`${baseURL}/?view=knowledge-workspace&file=skill_new`);
  }
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
  await page.getByRole("button", { name: "继续接收" }).waitFor();
  assert.equal(eventStreamCalls, 1);
  await page.getByRole("button", { name: "继续接收" }).click();
  await page.getByText("已完成真实连接试跑。").first().waitFor();
  nextRunShouldFail = true;
  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("button", { name: "重试本次运行" }).waitFor();
  await page.getByRole("button", { name: "重试本次运行" }).click();
  await page.getByText("已完成真实连接试跑。").first().waitFor();
  await page.getByPlaceholder("描述修改，或输入任务试跑…").fill("再次检查");
  await page.getByRole("button", { name: "发送" }).click();
  await page.getByText("已完成真实连接试跑。").first().waitFor();
  await page.getByRole("button", { name: "版本" }).click();
  await page.getByText("v1 · SOP · support-skill").waitFor();
  await page.getByRole("button", { name: "关闭" }).click();
  await page.getByRole("button", { name: "发布" }).click();
  await page.getByRole("button", { name: "发布到个人" }).click();
  await page.waitForURL(/file=published/);
  await page.reload();
  await page.getByRole("button", { name: "返回工作台" }).waitFor();
  await page.getByRole("button", { name: "在 Agent 中使用" }).click();
  await page.getByText("暂无可绑定的 Agent").waitFor();
  const agentModalBox = await page.locator('[data-state-modal="agent"]').boundingBox();
  if (viewport.width >= 900) {
    assert.ok(agentModalBox && agentModalBox.width >= 880 && agentModalBox.width <= 900, JSON.stringify(agentModalBox));
  } else {
    assert.ok(agentModalBox && agentModalBox.width <= viewport.width - 24, JSON.stringify(agentModalBox));
  }
  await page.getByRole("dialog").getByRole("button", { name: "关闭" }).click();
  for (const modal of ["share_run", "instructions", "versions"]) {
    await page.goto(`${baseURL}/?view=knowledge-workspace&file=pub_dash_anta&draftId=${draft.draft_id}&modal=${modal}`);
    await page.locator(".kw-shell").waitFor({ state: "visible" });
    const dialog = page.locator(`[data-state-modal="${modal}"]`);
    await dialog.waitFor({ state: "visible" });
    if (modal === "share_run") {
      await page.getByText(/RunID:/).waitFor();
      await page.getByText("暂无分享链接").waitFor();
    } else if (modal === "instructions") {
      await page.getByText("业务用途").waitFor();
    } else {
      await dialog.locator("h2").getByText("来源与版本历史").waitFor();
      const versionModalBox = await dialog.boundingBox();
      if (viewport.width >= 900) {
        assert.ok(
          versionModalBox
          && versionModalBox.width >= 380
          && versionModalBox.width <= 388
          && versionModalBox.x + versionModalBox.width === viewport.width
          && versionModalBox.y === 0
          && versionModalBox.height === viewport.height,
          JSON.stringify(versionModalBox),
        );
      } else {
        assert.ok(versionModalBox && versionModalBox.width <= viewport.width - 24, JSON.stringify(versionModalBox));
      }
    }
    await dialog.getByRole("button", { name: "关闭" }).click();
  }
  await page.screenshot({ path: path.join(screenshotDir, screenshotName), fullPage: true });
  await page.getByRole("button", { name: "返回工作台" }).click();
  await page.getByRole("heading", { name: "我的 Skill" }).waitFor();
  assert.match(new URL(page.url()).search, /file=welcome/);

  assert.equal(invocationCount, 4);
  assert.equal(eventStreamCalls, 5);
  assert.equal(validationCalls, 1);
  assert.equal(published, true);
  assert.ok(calls.some((call) => call.includes("/events")));
  assert.ok(calls.some((call) => call.includes("/publish")));
  console.log(JSON.stringify({
    contract_fixture: true,
    viewport: `${viewport.width}x${viewport.height}`,
    clicked: ["添加连接", "多选连接", "生成", "主区试跑", "SSE 对话", "失败重连", "版本", "发布", "Agent 弹窗", "刷新恢复", "右栏布局"],
    screenshot: path.join(screenshotDir, screenshotName),
    invocation_count: invocationCount,
    published,
  }));
  await browser.close();
}

await main();
