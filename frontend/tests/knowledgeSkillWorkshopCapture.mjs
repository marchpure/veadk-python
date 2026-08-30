import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const baseURL = process.env.KW_PREVIEW_URL || "http://127.0.0.1:5174";
const evidenceDir = path.resolve(
  process.env.KW_SCREENSHOT_DIR
    || "../docs/knowledge-workspace/evidence/skill-workshop-v220121",
);

const now = "2026-08-30T08:00:00Z";
const connection = {
  connection_id: "conn-workshop",
  connector_key: "oracle",
  display_name: "华东门店业务库",
  scope: "team",
  status: "ready",
  definition_version: "1",
  created_at: now,
  updated_at: now,
};
const unavailableConnection = {
  ...connection,
  connection_id: "conn-validating",
  display_name: "正在验证的数据仓库",
  status: "validating",
};
const revokedConnection = {
  ...connection,
  connection_id: "conn-revoked",
  display_name: "已撤销的数据仓库",
  status: "revoked",
};
const resource = {
  resource_id: "resource-workshop",
  kind: "files",
  display_name: "门店巡检标准.xlsx",
  scope: "personal",
  status: "verified",
  created_at: now,
  updated_at: now,
};
const unavailableResource = {
  ...resource,
  resource_id: "resource-error",
  display_name: "解析失败的巡检表.xlsx",
  status: "error",
};
const draft = {
  draft_id: "draft-workshop",
  goal: "分析华东区域异常",
  template_key: "generic",
  template_config: { mode: "auto" },
  connection_ids: [connection.connection_id],
  resource_ids: [],
  lifecycle: "ready_to_publish",
  current_revision_id: "revision-workshop",
  active_invocation_id: "invocation-workshop",
  created_at: now,
  updated_at: now,
};
const revision = {
  revision_id: "revision-workshop",
  draft_id: draft.draft_id,
  number: 1,
  skill_name: "华东区域异常分析",
  template_key: "dashboard",
  template_config: { mode: "interactive_dashboard" },
  sha256: "a".repeat(64),
  created_from_invocation: "invocation-workshop",
  created_at: now,
};
const artifact = {
  artifact_id: "artifact-workshop",
  revision_id: revision.revision_id,
  invocation_id: "invocation-workshop",
  media_type: "text/html",
  uri: `${baseURL}/api/knowledge/v1/artifacts/artifact-workshop/content`,
  sha256: "b".repeat(64),
  title: "华东区域异常看板",
  lineage: { template_key: "dashboard", revision_id: revision.revision_id },
  csp: "default-src 'none'; style-src 'unsafe-inline'",
  sandbox: "",
  created_at: now,
};
const invocation = {
  invocation_id: "invocation-workshop",
  kind: "generate",
  status: "running",
  message: draft.goal,
  event_url: "/api/knowledge/v1/invocations/invocation-workshop/events",
  created_at: now,
};
const conversation = [{
  invocation: { ...invocation, status: "succeeded", finished_at: "2026-08-30T08:00:06Z" },
  events: [
    event("start", 1, "run.started", { kind: "generate", status: "running", draft_id: draft.draft_id }),
    event("plan", 2, "activity.started", { activity_id: "plan", activity_kind: "planning", title: "规划分析步骤", status: "running", steps: [{ id: "one", label: "读取真实门店数据", status: "completed" }] }),
    event("tool", 3, "activity.completed", { activity_id: "tool", activity_kind: "tool", title: "查询区域指标", tool_name: "query", status: "succeeded", output_summary: "发现 3 个异常门店" }),
    event("final", 4, "assistant.final", { content: "已完成华东区域异常分析，并生成右侧分析看板。重点关注退货率和客流转化率。" }),
    event("artifact", 5, "artifact.created", { artifact_id: artifact.artifact_id, revision_id: artifact.revision_id, media_type: artifact.media_type, sha256: artifact.sha256, title: artifact.title }),
    event("revision", 6, "revision.created", { revision_id: revision.revision_id, draft_id: draft.draft_id, number: 1, sha256: revision.sha256, skill_name: revision.skill_name }),
    event("done", 7, "run.completed", { status: "succeeded", finished_at: "2026-08-30T08:00:06Z", artifact_ids: [artifact.artifact_id], revision_id: revision.revision_id }),
  ],
}];

function event(id, cursor, type, data) {
  return { id, cursor: String(cursor), type, invocation_id: "invocation-workshop", occurred_at: now, data };
}
function envelope(data) {
  return JSON.stringify({ data, meta: { request_id: "req-workshop" } });
}

async function main() {
  await mkdir(evidenceDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const missingAssets = [];
  let createCalls = 0;
  let generateCalls = 0;
  let publishCalls = 0;
  let agentDirectoryCalls = 0;
  let created = false;
  let retryScenario = false;
  let retryGenerateFailed = false;
  let retryPatchBody = null;
  const layoutMetrics = {};

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() === 404) missingAssets.push(response.url());
  });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/oauth2/userinfo") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ sub: "workshop-user", email: "workshop@example.com" }) });
    if (url.pathname === "/web/auth-config") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ providers: [] }) });
    if (url.pathname === "/web/runtimes") {
      agentDirectoryCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          runtimes: [{
            name: "门店运营 Agent",
            runtimeId: "runtime-workshop",
            status: "RUNNING",
            region: "cn-beijing",
            author: "workshop-user",
            isMine: true,
            canDelete: false,
          }],
          nextToken: "",
        }),
      });
    }
    if (!url.pathname.startsWith("/api/knowledge/v1")) return route.continue();
    const ok = (data, headers = {}) => route.fulfill({ status: 200, headers, contentType: "application/json", body: envelope(data) });
    if (url.pathname.endsWith("/content")) {
      return route.fulfill({
        status: 200,
        contentType: "text/html",
        headers: { "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'" },
        body: "<!doctype html><style>body{font-family:system-ui;margin:32px;color:#172033}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{padding:20px;border:1px solid #e2e8f0;border-radius:12px}b{font-size:28px;display:block;margin-top:8px}</style><h1>华东区域异常看板</h1><p>基于真实 Artifact 响应展示</p><div class=cards><div class=card>异常门店<b>3</b></div><div class=card>退货率<b>+18%</b></div><div class=card>客流转化<b>-7%</b></div></div>",
      });
    }
    if (url.pathname === "/api/knowledge/v1/connector-definitions") return ok([]);
    if (url.pathname === "/api/knowledge/v1/connections") return ok([connection, unavailableConnection, revokedConnection]);
    if (url.pathname === `/api/knowledge/v1/connections/${connection.connection_id}`) {
      return ok(connection, { ETag: "connection-v1" });
    }
    if (url.pathname === "/api/knowledge/v1/resources") return ok([resource, unavailableResource]);
    if (url.pathname === `/api/knowledge/v1/resources/${resource.resource_id}`) {
      return ok(resource, { ETag: "resource-v1" });
    }
    if (url.pathname === "/api/knowledge/v1/publications") {
      return ok(publishCalls ? [{
        publication_id: "publication-workshop",
        revision_id: revision.revision_id,
        target_space: "personal",
        status: "published",
        created_at: now,
      }] : []);
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "GET") {
      return ok(created ? [{ ...draft, lifecycle: publishCalls ? "published" : draft.lifecycle }] : []);
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "POST") {
      createCalls += 1;
      const body = JSON.parse(request.postData() || "{}");
      assert.equal(body.goal, retryScenario ? "分析华东区域首次异常" : draft.goal);
      assert.deepEqual(body.connection_ids, [connection.connection_id]);
      assert.equal(body.template_key, "generic");
      assert.deepEqual(body.template_config, { mode: "auto" });
      created = true;
      return route.fulfill({
        status: 201,
        headers: { ETag: "draft-v1" },
        contentType: "application/json",
        body: envelope({ ...draft, goal: body.goal }),
      });
    }
    if (
      url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}`
      && request.method() === "PATCH"
    ) {
      retryPatchBody = JSON.parse(request.postData() || "{}");
      return route.fulfill({
        status: 200,
        headers: { ETag: "draft-v2" },
        contentType: "application/json",
        body: envelope({ ...draft, ...retryPatchBody }),
      });
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}`) {
      return ok({ ...draft, lifecycle: publishCalls ? "published" : draft.lifecycle }, { ETag: "draft-v1" });
    }
    if (url.pathname.endsWith("/revisions")) return ok([revision]);
    if (url.pathname.endsWith("/conversation")) return ok(conversation);
    if (url.pathname.endsWith("/generate")) {
      generateCalls += 1;
      if (retryScenario && !retryGenerateFailed) {
        retryGenerateFailed = true;
        return route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "AUTOSKILL_UNAVAILABLE",
              message: "fixture generation interruption",
              retryable: true,
            },
            meta: { request_id: "req-workshop" },
          }),
        });
      }
      return route.fulfill({ status: 202, contentType: "application/json", body: envelope(invocation) });
    }
    if (url.pathname.endsWith("/events")) {
      const frames = conversation[0].events.map((item) => `id: ${item.cursor}\nevent: ${item.type}\ndata: ${JSON.stringify(item)}\n\n`).join("");
      return route.fulfill({ status: 200, headers: { "Content-Type": "text/event-stream" }, body: frames });
    }
    if (url.pathname === `/api/knowledge/v1/artifacts/${artifact.artifact_id}`) return ok(artifact, { ETag: "artifact-v1" });
    if (url.pathname.endsWith("/publish")) {
      publishCalls += 1;
      return route.fulfill({ status: 201, contentType: "application/json", body: envelope({ publication_id: "publication-workshop", revision_id: revision.revision_id, target_space: "personal", status: "published", created_at: now }) });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "NOT_FOUND", message: "fixture route missing", retryable: false }, meta: { request_id: "req-workshop" } }) });
  });

  const capture = async (name) => {
    layoutMetrics[name] = await page.evaluate(() => ({
      viewport: { width: innerWidth, height: innerHeight },
      body: { width: document.body.scrollWidth, height: document.body.scrollHeight },
      create: document.querySelector(".kw-skill-create-content")?.getBoundingClientRect().toJSON(),
      drawer: document.querySelector(".kw-data-tool-drawer")?.getBoundingClientRect().toJSON(),
      rail: document.querySelector(".kw-invocation-rail")?.getBoundingClientRect().toJSON(),
      chat: document.querySelector(".kw-skill-conversation")?.getBoundingClientRect().toJSON(),
      artifact: document.querySelector(".kw-artifact-workspace")?.getBoundingClientRect().toJSON(),
      composer: document.querySelector(".kw-workshop-composer")?.getBoundingClientRect().toJSON(),
      modal: document.querySelector("[data-state-modal]")?.getBoundingClientRect().toJSON(),
    }));
    await page.screenshot({ path: path.join(evidenceDir, name), fullPage: false });
  };

  const creatorSnapshot = async () => page.locator(".kw-main").evaluate((node) => ({
    text: node.textContent,
    classes: [...node.querySelectorAll("*")].map((element) => element.className),
    controls: [...node.querySelectorAll("button, textarea")].map((element) => ({
      tag: element.tagName,
      text: element.textContent,
      label: element.getAttribute("aria-label"),
      value: "value" in element ? element.value : null,
    })),
  }));
  await page.goto(`${baseURL}/?view=knowledge-workspace`);
  await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
  const canonicalSnapshot = await creatorSnapshot();
  const canonicalScreenshot = await page.screenshot({
    path: path.join(evidenceDir, "08-default-root-1440x1000.png"),
  });
  assert.equal(new URL(page.url()).search, "?view=knowledge-workspace");

  await page.goto(`${baseURL}/?view=knowledge-workspace&file=skill_new`);
  await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
  assert.deepEqual(await creatorSnapshot(), canonicalSnapshot);
  const compatibleScreenshot = await page.screenshot({
    path: path.join(evidenceDir, "09-compatible-skill-new-1440x1000.png"),
  });
  assert.deepEqual(compatibleScreenshot, canonicalScreenshot);

  await page.goto(`${baseURL}/?view=knowledge-workspace&file=welcome`);
  await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
  await page.waitForURL(`${baseURL}/?view=knowledge-workspace`);
  assert.deepEqual(await creatorSnapshot(), canonicalSnapshot);

  await page.getByLabel("描述业务任务").fill("保留详情返回中的任务");
  await page.getByRole("button", { name: "添加数据与工具" }).click();
  const defaultDataDrawer = page.getByRole("dialog", { name: "添加数据与工具" });
  await defaultDataDrawer.getByRole("button", { name: /华东门店业务库/ }).click();
  await page.getByRole("button", { name: "确认选择" }).click();
  await page.getByRole("button", { name: "添加数据与工具" }).click();
  await defaultDataDrawer.getByRole("button", { name: "查看" }).click();
  await page.getByRole("button", { name: "返回选择" }).click();
  await defaultDataDrawer.waitFor();
  await page.getByRole("button", { name: "取消" }).click();
  assert.equal(await page.getByLabel("描述业务任务").inputValue(), "保留详情返回中的任务");
  await page.getByLabel("当前数据与工具").getByText("华东门店业务库", { exact: true }).waitFor();

  await page.locator(".kw-studio-links").getByText("创建", { exact: true }).click();
  assert.equal(await page.getByLabel("描述业务任务").inputValue(), "");
  assert.equal(await page.getByLabel("当前数据与工具").count(), 0);
  assert.match(await page.locator(".kw-template-trigger").innerText(), /Auto/);
  assert.equal(new URL(page.url()).search, "?view=knowledge-workspace");

  await page.getByLabel("描述业务任务").fill("浏览器历史中的任务");
  await page.getByRole("complementary").getByText(connection.display_name, { exact: true }).click();
  await page.getByRole("heading", { name: connection.display_name }).waitFor();
  await page.goBack();
  await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
  assert.equal(await page.getByLabel("描述业务任务").inputValue(), "浏览器历史中的任务");
  await page.goForward();
  await page.getByRole("heading", { name: connection.display_name }).waitFor();
  await page.goBack();
  await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();

  await page.getByLabel("描述业务任务").fill("侧栏新建前的任务");
  await page.getByRole("button", { name: "添加数据与工具" }).click();
  await defaultDataDrawer.getByRole("button", { name: /华东门店业务库/ }).click();
  await page.getByRole("button", { name: "确认选择" }).click();
  await page.getByRole("complementary").getByRole("button", { name: "新建 Skill" }).click();
  assert.equal(await page.getByLabel("描述业务任务").inputValue(), "");
  assert.equal(await page.getByLabel("当前数据与工具").count(), 0);

  for (const entry of [
    [`?view=knowledge-workspace&file=connection&connectionId=${connection.connection_id}`, connection.display_name],
    [`?view=knowledge-workspace&file=resource&resourceId=${resource.resource_id}`, resource.display_name],
    [`?view=knowledge-workspace&file=draft&draftId=${draft.draft_id}`, "Skill 对话"],
    [`?view=knowledge-workspace&file=published&draftId=${draft.draft_id}`, "Skill 对话"],
  ]) {
    await page.goto(`${baseURL}/${entry[0]}`);
    if (entry[1] === "Skill 对话") {
      await page.getByRole("region", { name: entry[1] }).waitFor();
    } else {
      await page.getByRole("heading", { name: entry[1] }).waitFor();
    }
  }

  for (const viewport of [
    { width: 1280, height: 800, name: "10-default-root-1280x800.png" },
    { width: 390, height: 844, name: "11-default-root-390x844.png" },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`${baseURL}/?view=knowledge-workspace`);
    await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
      true,
    );
    await page.screenshot({ path: path.join(evidenceDir, viewport.name) });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });

  retryScenario = true;
  await page.goto(`${baseURL}/?view=knowledge-workspace&file=skill_new`);
  await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
  await page.getByLabel("描述业务任务").fill("分析华东区域首次异常");
  await page.getByRole("button", { name: "添加数据与工具" }).click();
  let dataDrawer = page.getByRole("dialog", { name: "添加数据与工具" });
  await dataDrawer.getByRole("button", { name: /华东门店业务库/ }).click();
  await page.getByRole("button", { name: "确认选择" }).click();
  await page.getByRole("button", { name: "发送" }).click();
  await page.getByRole("alert").filter({ hasText: "Skill 服务暂不可用，请稍后重试。" }).first().waitFor();
  await page.getByLabel("描述业务任务").fill("分析华东区域最新异常");
  await page.getByRole("button", { name: "发送" }).click();
  await page.waitForURL(/file=draft&draftId=draft-workshop/);
  assert.equal(createCalls, 1);
  assert.equal(generateCalls, 2);
  assert.deepEqual(retryPatchBody, {
    goal: "分析华东区域最新异常",
    template_key: "generic",
    template_config: { mode: "auto" },
    connection_ids: [connection.connection_id],
    resource_ids: [],
    trial_task: "",
    upload_ids: [],
  });
  assert.deepEqual(consoleErrors, [
    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
  ]);

  retryScenario = false;
  retryGenerateFailed = false;
  retryPatchBody = null;
  createCalls = 0;
  generateCalls = 0;
  created = false;
  consoleErrors.length = 0;
  await page.goto(`${baseURL}/?view=knowledge-workspace&file=skill_new`);
  await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
  await capture("01-new-empty-1440x1000.png");
  await page.getByRole("button", { name: "分析华东区域异常" }).click();
  assert.equal(await page.getByLabel("描述业务任务").inputValue(), draft.goal);
  await page.getByRole("button", { name: "发送" }).click();
  await dataDrawer.waitFor();
  await page.getByText("请先选择至少一个可用的 Connection 或 Resource。").waitFor();
  assert.equal(await dataDrawer.getByRole("button", { name: /正在验证的数据仓库/ }).isDisabled(), true);
  assert.equal(await dataDrawer.getByRole("button", { name: /已撤销的数据仓库/ }).isDisabled(), true);
  await dataDrawer.getByText("已撤销", { exact: true }).waitFor();
  await capture("02-data-tools-1440x1000.png");
  await dataDrawer.getByRole("button", { name: "查看" }).click();
  await page.getByRole("button", { name: "返回选择" }).click();
  await dataDrawer.waitFor();
  await page.getByRole("button", { name: "取消" }).click();
  assert.equal(await page.getByLabel("描述业务任务").inputValue(), draft.goal);
  await page.getByRole("button", { name: "添加数据与工具" }).click();
  await dataDrawer.getByRole("button", { name: /华东门店业务库/ }).click();
  await page.getByRole("button", { name: "确认选择" }).click();
  await page.getByRole("button", { name: "发送" }).click();
  await page.waitForURL(/file=draft&draftId=draft-workshop/);
  await page.getByText("已完成华东区域异常分析").waitFor();
  await page.getByRole("region", { name: "HTML Artifact" }).waitFor();
  assert.equal(createCalls, 1);
  assert.equal(generateCalls, 1);
  await capture("03-workshop-1440x1000.png");
  await page.getByRole("button", { name: "发布 Skill" }).click();
  await page.getByRole("button", { name: "发布到个人" }).click();
  await page.waitForURL(/file=published/);
  await page.getByRole("button", { name: /已发布/ }).waitFor();
  await capture("04-published-1440x1000.png");
  await page.reload();
  await page.getByRole("button", { name: /已发布/ }).waitFor();
  const directoryCallsBeforeModal = agentDirectoryCalls;
  await page.getByRole("button", { name: "添加到 Agent" }).click();
  await page.getByText("门店运营 Agent").waitFor();
  await page.getByText("当前服务尚未提供 Skill-to-Agent 绑定 API").waitFor();
  assert.ok(agentDirectoryCalls > directoryCallsBeforeModal);
  await capture("05-bind-agent-1440x1000.png");
  await page.getByRole("dialog").getByRole("button", { name: "关闭" }).click();
  await page.getByRole("button", { name: "分享" }).click();
  await page.getByText("尚无服务端快照分享 API").waitFor();
  assert.equal(await page.getByRole("button", { name: "分享 API 未开放" }).isDisabled(), true);
  await page.getByRole("dialog").getByRole("button", { name: "关闭" }).click();

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${baseURL}/?view=knowledge-workspace&file=draft&draftId=${draft.draft_id}`);
  await page.getByRole("region", { name: "HTML Artifact" }).waitFor();
  await capture("06-workshop-1280x800.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole("region", { name: "Skill 对话" }).waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
  await capture("07-workshop-390x844.png");

  const metrics = layoutMetrics["07-workshop-390x844.png"];
  assert.deepEqual(consoleErrors, []);
  assert.deepEqual(pageErrors, []);
  assert.deepEqual(missingAssets, []);
  assert.equal(publishCalls, 1);
  await writeFile(path.join(evidenceDir, "metrics.json"), JSON.stringify({
    createCalls,
    generateCalls,
    publishCalls,
    agentDirectoryCalls,
    consoleErrors,
    pageErrors,
    missingAssets,
    layoutMetrics,
    metrics,
  }, null, 2));
  console.log(JSON.stringify({ evidenceDir, createCalls, generateCalls, publishCalls, metrics }));
  await browser.close();
}

await main();
