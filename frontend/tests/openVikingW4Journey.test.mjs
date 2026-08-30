import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import playwright from "playwright";

const { chromium } = playwright;
const shouldRun = process.env.KW_RUN_W4_PLAYWRIGHT === "1";
const baseURL = process.env.KW_PREVIEW_URL || "http://127.0.0.1:5174";
const viewport = {
  width: Number(process.env.KW_VIEWPORT_WIDTH || 1440),
  height: Number(process.env.KW_VIEWPORT_HEIGHT || 900),
};
const screenshotName =
  process.env.KW_SCREENSHOT || `openviking-w4-${viewport.width}x${viewport.height}.png`;
const screenshotDir = new URL(
  "../../docs/knowledge-workspace/evidence/w4/browser/",
  import.meta.url,
);

const profile = {
  profile_id: "profile-w4",
  display_name: "Commercial Knowledge",
  workspace_uri: "viking://workspace/",
  root_resource_ref: "ovr_root.signature",
  status: "ready",
  base_url_configured: true,
  api_key_configured: true,
  last_validated_at: "2026-08-30T00:00:00Z",
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:00Z",
};

const folder = {
  uri: "viking://workspace/docs/",
  name: "docs",
  is_dir: true,
  isDir: true,
  size: "",
  size_bytes: null,
  sizeBytes: null,
  mod_time: "2026-08-30T00:00:00Z",
  modTime: "2026-08-30T00:00:00Z",
  abstract: "Commercial docs",
  overview: "Commercial docs",
  resource_ref: "ovr_docs.signature",
};

const document = {
  uri: "viking://workspace/docs/handbook.md",
  name: "handbook.md",
  is_dir: false,
  isDir: false,
  size: "128 B",
  size_bytes: 128,
  sizeBytes: 128,
  mod_time: "2026-08-30T00:00:00Z",
  modTime: "2026-08-30T00:00:00Z",
  abstract: "Commercial onboarding guide",
  overview: "Commercial onboarding guide",
  resource_ref: "ovr_doc.signature",
};

function draftFor(body = {}) {
  return {
    draft_id: "draft-w4",
    goal: body.goal || "Use Commercial Knowledge",
    connection_ids: [],
    resource_ids: [],
    upload_ids: [],
    knowledge_source_refs: body.knowledge_source_refs || [
      { provider: "openviking", profile_ref: "profile-w4" },
      { provider: "openviking", resource_ref: "ovr_root.signature" },
    ],
    template_key: body.template_key || "generic",
    template_config: body.template_config || {},
    lifecycle: "editing",
    created_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
  };
}

function envelope(data) {
  return JSON.stringify({ data, meta: { request_id: "req-w4" } });
}

function ovOperationResponse(operation, payload) {
  if (operation === "fs_list") {
    const ref = payload.resource_ref;
    const result = ref === "ovr_docs.signature" ? [document] : [folder];
    return { result };
  }
  if (operation === "fs_stat") {
    const ref = payload.resource_ref;
    return { result: ref === "ovr_doc.signature" ? document : folder };
  }
  if (operation === "content_read") {
    return {
      result: {
        uri: document.uri,
        resource_ref: document.resource_ref,
        content: "# Handbook\n\nUse Commercial Knowledge as approved context.",
      },
    };
  }
  if (operation === "find" || operation === "search") {
    return {
      result: {
        resources: [
          {
            uri: document.uri,
            resource_ref: document.resource_ref,
            context_type: "resource",
            level: 2,
            score: 0.92,
            abstract: "Commercial onboarding guide",
            overview: "Commercial onboarding guide",
            category: "docs",
            match_reason: "matched handbook",
          },
        ],
        memories: [],
        skills: [],
        total: 1,
      },
    };
  }
  return { result: [] };
}

async function installRoutes(page) {
  const observed = {
    createDraftPayloads: [],
    operations: [],
  };

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/oauth2/userinfo") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ sub: "w4-user", email: "w4@example.com" }),
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
    if (url.pathname === "/api/knowledge/v1/connector-definitions") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connections") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/resources") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/openviking/profiles" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([profile]),
      });
      return;
    }
    const operationMatch = url.pathname.match(
      /^\/api\/knowledge\/v1\/openviking\/profiles\/profile-w4\/operations\/([^/]+)$/,
    );
    if (operationMatch) {
      const body = JSON.parse(request.postData() || "{}");
      observed.operations.push({ operation: operationMatch[1], payload: body.payload || {} });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope(ovOperationResponse(operationMatch[1], body.payload || {})),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}");
      observed.createDraftPayloads.push(body);
      await route.fulfill({
        status: 201,
        headers: { ETag: "draft-w4-etag" },
        contentType: "application/json",
        body: envelope(draftFor(body)),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts/draft-w4" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        headers: { ETag: "draft-w4-etag" },
        contentType: "application/json",
        body: envelope(draftFor()),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts/draft-w4/revisions") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts/draft-w4/conversation") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/publications") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope([]),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts/draft-w4/generate") {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: envelope({
          invocation_id: "inv-w4",
          kind: "generate",
          status: "running",
          message: "Use Commercial Knowledge",
          event_url: "/api/knowledge/v1/invocations/inv-w4/events",
          created_at: "2026-08-30T00:00:00Z",
        }),
      });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/invocations/inv-w4/events") {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: [
          'id: 1\nevent: run.started\ndata: {"id":"e1","cursor":"1","type":"run.started","invocation_id":"inv-w4","occurred_at":"2026-08-30T00:00:00Z","data":{"status":"running"}}\n\n',
          'id: 2\nevent: assistant.final\ndata: {"id":"e2","cursor":"2","type":"assistant.final","invocation_id":"inv-w4","occurred_at":"2026-08-30T00:00:01Z","data":{"content":"已使用 Commercial Knowledge 生成 Skill。"}}\n\n',
          'id: 3\nevent: run.completed\ndata: {"id":"e3","cursor":"3","type":"run.completed","invocation_id":"inv-w4","occurred_at":"2026-08-30T00:00:02Z","data":{"status":"succeeded"}}\n\n',
        ].join(""),
      });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "NOT_FOUND",
          message: `missing fixture ${request.method()} ${url.pathname}`,
          retryable: false,
        },
        meta: { request_id: "req-w4" },
      }),
    });
  });

  return observed;
}

test("W4 OpenViking journey returns selected knowledge context to Skill creator", { skip: !shouldRun }, async () => {
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport });
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const observed = await installRoutes(page);

  try {
    await page.goto(`${baseURL}/?view=knowledge-workspace`);
    await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
    await page.getByRole("button", { name: /创建连接/ }).waitFor();
    await page.getByRole("button", { name: /创建知识库/ }).click();
    await page.locator(".openviking-studio").waitFor();
    await page.getByRole("button", { name: "加入 Skill 上下文" }).waitFor();
    await page.getByLabel("OpenViking context tree").waitFor();
    await page.getByRole("treeitem", { name: /docs/ }).click();
    await page.getByRole("treeitem", { name: /handbook\.md/ }).click();
    await page.getByText("Use Commercial Knowledge as approved context.").waitFor();
    await page.getByRole("button", { name: "Retrieval" }).click();
    await page.getByRole("textbox").fill("handbook");
    await page.keyboard.press("Enter");
    await page.getByText("Commercial onboarding guide").waitFor();
    await page.getByRole("button", { name: "加入 Skill 上下文" }).click();
    await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
    await page.getByText("Commercial Knowledge").waitFor();
    await page.getByLabel("描述业务任务").fill("Use Commercial Knowledge");
    await page.getByRole("button", { name: "发送" }).click();
    await page.getByText("已使用 Commercial Knowledge 生成 Skill。").waitFor();
    await page.screenshot({
      path: new URL(screenshotName, screenshotDir).pathname,
      fullPage: true,
    });

    assert.equal(observed.createDraftPayloads.length, 1);
    assert.equal(
      observed.createDraftPayloads[0].connection_ids?.length ?? 0,
      0,
    );
    assert.equal(observed.createDraftPayloads[0].resource_ids?.length ?? 0, 0);
    assert.deepEqual(observed.createDraftPayloads[0].knowledge_source_refs, [
      { provider: "openviking", profile_ref: "profile-w4" },
      { provider: "openviking", resource_ref: "ovr_root.signature" },
    ]);
    assert.ok(
      observed.operations.some((item) => item.operation === "content_read"),
      JSON.stringify(observed.operations),
    );
    assert.ok(
      observed.operations.some((item) => ["find", "search"].includes(item.operation)),
      JSON.stringify(observed.operations),
    );
    assert.deepEqual(consoleErrors, []);
    assert.deepEqual(pageErrors, []);

    console.log(JSON.stringify({
      w4_openviking_journey: true,
      viewport: `${viewport.width}x${viewport.height}`,
      screenshot: `docs/knowledge-workspace/evidence/w4/browser/${screenshotName}`,
      create_draft_payloads: observed.createDraftPayloads.length,
      operations: observed.operations.map((item) => item.operation),
    }));
  } finally {
    await browser.close();
  }
});
