import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import playwright from "playwright";

const { chromium } = playwright;
const shouldRun = process.env.KW_RUN_W3_PLAYWRIGHT === "1";
const baseURL = process.env.KW_PREVIEW_URL || "http://127.0.0.1:5174";
const viewport = {
  width: Number(process.env.KW_VIEWPORT_WIDTH || 1440),
  height: Number(process.env.KW_VIEWPORT_HEIGHT || 900),
};
const isNarrow = viewport.width <= 720;
const screenshotName = process.env.KW_SCREENSHOT || `autoskill-creator-w3-${viewport.width}x${viewport.height}.png`;
const screenshotDir = new URL("../../docs/knowledge-workspace/evidence/w3/", import.meta.url);

const personalConnection = {
  connection_id: "conn-revenue",
  connector_key: "postgresql",
  display_name: "Revenue Warehouse",
  scope: "personal",
  status: "ready",
  definition_version: "1",
  profile: { warehouse: "retail" },
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z",
};
const teamConnection = {
  connection_id: "conn-feishu",
  connector_key: "feishu",
  display_name: "Team Feishu Docs",
  scope: "team",
  status: "ready",
  definition_version: "1",
  profile: { tenant: "team" },
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z",
};
const fileResource = {
  resource_id: "res-policy",
  kind: "files",
  display_name: "policy-notes.csv",
  scope: "personal",
  status: "verified",
  metadata: { upload_id: "upload-policy", rows: 12 },
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z",
};
const draft = {
  draft_id: "draft-w3",
  goal: "让区域经理查询门店毛利异常并解释退货率上升原因",
  trial_task: "查询本周毛利异常门店",
  template_key: "dashboard",
  template_config: { mode: "interactive_dashboard" },
  connection_ids: [personalConnection.connection_id],
  resource_ids: [fileResource.resource_id],
  lifecycle: "ready_to_publish",
  current_revision_id: "revision-w3",
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T00:00:00Z",
};
const revision = {
  revision_id: "revision-w3",
  draft_id: draft.draft_id,
  number: 1,
  skill_name: "store-margin-sentinel",
  template_key: draft.template_key,
  template_config: draft.template_config,
  sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  manifest: {
    root: "skillhub/store-margin-sentinel/",
    zip: {
      paths: [
        "skillhub/store-margin-sentinel/SKILL.md",
        "skillhub/store-margin-sentinel/scripts/run.py",
        "skillhub/store-margin-sentinel/tests/test_margin_skill.py",
      ],
    },
    source_files: [
      {
        path: "skillhub/store-margin-sentinel/SKILL.md",
        content: "# Store Margin Sentinel\n\nUse approved sales and return data to explain margin anomalies.",
      },
    ],
  },
  created_at: "2026-08-29T00:00:00Z",
};

function envelope(data) {
  return JSON.stringify({ data, meta: { request_id: "req-w3" } });
}

function invocation(invocationId, kind, message) {
  return {
    invocation_id: invocationId,
    kind,
    status: "running",
    message,
    event_url: `/api/knowledge/v1/invocations/${invocationId}/events`,
    created_at: "2026-08-29T00:00:00Z",
  };
}

function streamFrames(invocationId, kind, finalText, revisionNumber = 1) {
  const event = (id, type, data) => (
    `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify({
      id: `${invocationId}-${id}`,
      cursor: String(id),
      type,
      invocation_id: invocationId,
      occurred_at: "2026-08-29T00:00:00Z",
      data,
    })}\n\n`
  );
  return [
    event(1, "run.started", { kind, status: "running", draft_id: draft.draft_id }),
    event(2, "activity.started", {
      activity_id: `${invocationId}-tool`,
      activity_kind: "tool",
      title: "读取已授权 Connection",
      status: "running",
      call_id: `${invocationId}-call`,
      tool_name: "Revenue Warehouse",
      input_summary: "查询本周毛利与退货率",
    }),
    event(3, "activity.completed", {
      activity_id: `${invocationId}-tool`,
      activity_kind: "tool",
      title: "读取已授权 Connection",
      status: "succeeded",
      call_id: `${invocationId}-call`,
      tool_name: "Revenue Warehouse",
      output_summary: "返回 3 个异常门店",
      duration_ms: 128,
    }),
    event(4, "assistant.final", { content: finalText }),
    event(5, "revision.created", {
      revision_id: revision.revision_id,
      draft_id: draft.draft_id,
      number: revisionNumber,
      sha256: revision.sha256,
      skill_name: revision.skill_name,
    }),
    event(6, "run.completed", {
      status: "succeeded",
      finished_at: "2026-08-29T00:00:01Z",
      revision_id: revision.revision_id,
    }),
  ].join("");
}

async function installRoutes(page) {
  let invocationCount = 0;
  let revisionRuns = 0;
  let draftMessages = 0;
  let published = false;

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/oauth2/userinfo") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ sub: "w3-user", email: "w3@example.com" }) });
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
        contentType: "application/json",
        body: envelope([
          {
            connector_key: "postgresql",
            version: "1",
            display_name: "Postgres Warehouse",
            category: "database",
            status: "verified",
            capabilities: ["query", "schema"],
            config_schema: { type: "object", properties: { host: { title: "Host", type: "string" } }, required: ["host"] },
            auth_schema: { type: "object", properties: { password: { title: "Password", type: "string", format: "password" } }, required: ["password"] },
          },
          {
            connector_key: "feishu",
            version: "1",
            display_name: "Feishu Docs",
            category: "office",
            status: "beta",
            capabilities: ["document", "search"],
            config_schema: { type: "object", properties: { tenant: { title: "Tenant", type: "string" } } },
            auth_schema: { type: "object", properties: {} },
          },
        ]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connections" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([personalConnection, teamConnection]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/resources" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([fileResource]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([draft]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}");
      assert.equal(body.goal, draft.goal);
      assert.deepEqual(body.connection_ids, [personalConnection.connection_id]);
      assert.deepEqual(body.resource_ids, [fileResource.resource_id]);
      await route.fulfill({ status: 201, headers: { ETag: "draft-w3-etag" }, contentType: "application/json", body: envelope(draft) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}`) {
      await route.fulfill({ status: 200, headers: { ETag: "draft-w3-etag" }, contentType: "application/json", body: envelope(draft) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/revisions`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([revision]) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/conversation`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([]) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/generate`) {
      invocationCount += 1;
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope(invocation(`inv-generate-${invocationCount}`, "generate", draft.trial_task)) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/messages`) {
      draftMessages += 1;
      invocationCount += 1;
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope(invocation(`inv-update-${invocationCount}`, "update", "修改")) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skill-revisions/${revision.revision_id}/run`) {
      revisionRuns += 1;
      invocationCount += 1;
      const body = JSON.parse(request.postData() || "{}");
      assert.deepEqual(body.connection_ids, draft.connection_ids);
      assert.deepEqual(body.resource_ids, draft.resource_ids);
      await route.fulfill({ status: 202, contentType: "application/json", body: envelope(invocation(`inv-run-${invocationCount}`, "run", body.message)) });
      return;
    }
    if (url.pathname.endsWith("/events")) {
      const invocationId = url.pathname.split("/").at(-2);
      const isRun = invocationId?.startsWith("inv-run");
      const isUpdate = invocationId?.startsWith("inv-update");
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: streamFrames(
          invocationId || "inv-w3",
          isRun ? "run" : isUpdate ? "update" : "generate",
          isRun ? "试跑完成：异常集中在华东门店。" : isUpdate ? "已根据反馈生成新的 Skill Revision。" : "已生成可复用 Skill，并完成首轮校验。",
          isUpdate ? 2 : 1,
        ),
      });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skill-revisions/${revision.revision_id}/publish`) {
      published = true;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: envelope({
          publication_id: "publication-w3",
          revision_id: revision.revision_id,
          target_space: "team",
          status: "published",
          created_at: "2026-08-29T00:00:00Z",
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "NOT_FOUND", message: `missing fixture ${request.method()} ${url.pathname}`, retryable: false }, meta: { request_id: "req-w3" } }) });
  });

  return {
    counts: () => ({ invocationCount, revisionRuns, draftMessages, published }),
  };
}

test("W3 creator journey creates, runs, edits, publishes, and captures the workspace", { skip: !shouldRun }, async () => {
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport });
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const fixture = await installRoutes(page);

  try {
    await page.goto(`${baseURL}/?view=knowledge-workspace&file=welcome`);
    await page.getByRole("heading", { name: "连接数据，创建可复用 Skill" }).waitFor();
    assert.equal(await page.locator(".kw-shell").count(), 1);
    assert.equal(await page.getByText("Dashboard").count(), 1);
    assert.equal(await page.getByText("SOP").count(), 1);
    assert.equal(await page.getByText("Semantic").count(), 1);

    if (isNarrow) {
      await page.getByRole("button", { name: "添加连接" }).click();
    } else {
      await page.getByLabel("添加团队连接").click();
    }
    await page.getByLabel("搜索 Connection").fill("postgres");
    await page.locator(".kw-connector-card", { hasText: "Postgres Warehouse" }).waitFor();
    await page.getByLabel("Connection 分类").selectOption("办公协作");
    await page.getByText("当前 catalog 没有匹配的 Connection。").waitFor();
    await page.getByLabel("搜索 Connection").fill("");
    await page.locator(".kw-connector-card", { hasText: "Feishu Docs" }).waitFor();
    await page.getByRole("button", { name: "取消" }).click();

    await page.getByLabel("描述要创建的 Skill").fill(draft.goal);
    await page.getByRole("button", { name: "开始创建" }).click();
    await page.getByRole("heading", { name: "生成第一版 Skill" }).waitFor();
    await page.getByRole("checkbox", { name: /Revenue Warehouse/ }).check();
    await page.getByRole("checkbox", { name: /policy-notes\.csv/ }).check();
    await page.getByLabel("可选：先试一句真实任务").fill(draft.trial_task);
    await page.getByRole("button", { name: "生成并试用 Skill" }).click();
    await page.getByText("已生成可复用 Skill，并完成首轮校验。").waitFor();
    await page.getByTestId("skill-package").getByText("SKILL.md", { exact: true }).waitFor();
    await page.getByText("Store Margin Sentinel").waitFor();
    await page.getByText("skillhub/store-margin-sentinel/scripts/run.py").waitFor();
    await page.getByText("skillhub/store-margin-sentinel/tests/test_margin_skill.py").waitFor();
    await page.getByText("Revenue Warehouse · 可用").waitFor();
    await page.getByText("policy-notes.csv · files").waitFor();

    await page.getByTestId("skill-package").getByRole("button", { name: "试跑" }).click();
    await page.getByText("试跑完成：异常集中在华东门店。").waitFor();
    await page.getByPlaceholder("描述修改，或输入任务试跑…").fill("补充退货率解释模板");
    await page.getByRole("button", { name: "修改" }).click();
    await page.getByText("已根据反馈生成新的 Skill Revision。").waitFor();
    await page.getByRole("button", { name: "发布" }).click();
    await page.getByRole("button", { name: "发布到团队" }).click();
    await page.waitForURL(/file=published/);
    await page.reload();
    await page.getByRole("button", { name: "返回工作台" }).waitFor();
    await page.locator(".kw-selected-skill-layout .kw-chat").waitFor();
    await page.getByTestId("skill-package").getByRole("button", { name: "试跑" }).click();
    await page.getByText("试跑完成：异常集中在华东门店。").waitFor();

    await page.screenshot({ path: new URL(screenshotName, screenshotDir).pathname, fullPage: true });
    const counts = fixture.counts();
    assert.ok(counts.revisionRuns >= 2, JSON.stringify(counts));
    assert.equal(counts.draftMessages, 1);
    assert.equal(counts.published, true);
    assert.deepEqual(consoleErrors, []);
    assert.deepEqual(pageErrors, []);

    console.log(JSON.stringify({
      w3_fixture: true,
      viewport: `${viewport.width}x${viewport.height}`,
      screenshot: `docs/knowledge-workspace/evidence/w3/${screenshotName}`,
      revision_runs: counts.revisionRuns,
      draft_messages: counts.draftMessages,
      published: counts.published,
    }));
  } finally {
    await browser.close();
  }
});
