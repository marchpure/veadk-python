/**
 * Production-component browser evidence for W2 Artifact UX.
 *
 * The app is loaded through Vite and the same-origin BFF contract is
 * intercepted in Playwright. This is test-only evidence; it does not add any
 * production fixture or fallback HTML path.
 */
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const baseURL = process.env.KW_PREVIEW_URL || "http://127.0.0.1:5174";
const screenshotDir = process.env.KW_SCREENSHOT_DIR
  ? path.resolve(process.env.KW_SCREENSHOT_DIR)
  : new URL("../../docs/knowledge-workspace/evidence/assistant-ux/", import.meta.url).pathname;

const connection = {
  connection_id: "conn-artifact-evidence",
  connector_key: "artifact-evidence",
  display_name: "AutoSkill HTML Source",
  scope: "team",
  status: "ready",
  definition_version: "1",
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:00Z",
};
const draft = {
  draft_id: "draft-artifact-evidence",
  goal: "生成可审计的 HTML 分析看板",
  trial_task: "生成渠道异常看板",
  template_key: "dashboard",
  template_config: { mode: "artifact_evidence" },
  connection_ids: [connection.connection_id],
  resource_ids: [],
  lifecycle: "generated",
  current_revision_id: "revision-final",
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:04:00Z",
};
const revisions = [
  {
    revision_id: "revision-preview",
    draft_id: draft.draft_id,
    number: 1,
    skill_name: "preview-version",
    template_key: draft.template_key,
    template_config: draft.template_config,
    sha256: "a".repeat(64),
    manifest: { template_key: "dashboard", provenance: "preview" },
    created_at: "2026-08-30T00:01:00Z",
  },
  {
    revision_id: "revision-final",
    draft_id: draft.draft_id,
    number: 2,
    skill_name: "final-version",
    template_key: draft.template_key,
    template_config: draft.template_config,
    sha256: "b".repeat(64),
    manifest: {
      template_key: "dashboard",
      zip: { paths: ["skillhub/artifact-final/SKILL.md"] },
    },
    created_at: "2026-08-30T00:03:00Z",
  },
];
const finalArtifact = {
  artifact_id: "artifact-final",
  revision_id: "revision-final",
  invocation_id: "invocation-artifact",
  media_type: "text/html",
  uri: "/api/knowledge/v1/artifacts/artifact-final/content",
  sha256: "c".repeat(64),
  title: "最终 HTML Artifact",
  lineage: {
    template_key: "dashboard",
    revision_id: "revision-final",
    invocation_id: "invocation-artifact",
    source: "immutable-final-lineage",
  },
  csp: "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
  sandbox: "",
  created_at: "2026-08-30T00:04:00Z",
};
const invocation = {
  invocation_id: "invocation-artifact",
  kind: "generate",
  status: "succeeded",
  message: draft.trial_task,
  model: "doubao-seed",
  event_url: "/api/knowledge/v1/invocations/invocation-artifact/events",
  started_at: "2026-08-30T00:00:00Z",
  finished_at: "2026-08-30T00:00:06Z",
  created_at: "2026-08-30T00:00:00Z",
};

function envelope(data) {
  return JSON.stringify({ data, meta: { request_id: "artifact-evidence" } });
}

function event(id, cursor, type, data) {
  return {
    id,
    cursor: String(cursor),
    type,
    invocation_id: invocation.invocation_id,
    occurred_at: `2026-08-30T00:00:${String(cursor).padStart(2, "0")}Z`,
    data,
  };
}

const conversation = [{
  invocation,
  events: [
    event("preview", 1, "artifact.preview", {
      snapshot_id: "snapshot-preview",
      revision_id: "revision-preview",
      media_type: "text/html",
      sha256: "p".repeat(64),
      uri: "/api/knowledge/v1/artifact-snapshots/snapshot-preview/content",
      title: "临时预览",
      source: "<!doctype html><html><body>preview-source-must-not-win</body></html>",
      log: "validated preview snapshot",
    }),
    event("final", 2, "artifact.final", {
      artifact_id: finalArtifact.artifact_id,
      revision_id: finalArtifact.revision_id,
      media_type: finalArtifact.media_type,
      sha256: finalArtifact.sha256,
      uri: finalArtifact.uri,
      title: finalArtifact.title,
      log: "immutable final artifact recorded",
    }),
    event("late-preview", 3, "artifact.preview", {
      snapshot_id: "snapshot-late",
      revision_id: "revision-preview",
      media_type: "text/html",
      sha256: "l".repeat(64),
      uri: "/api/knowledge/v1/artifact-snapshots/snapshot-late/content",
      title: "迟到预览",
      status: "preview",
      source: "<!doctype html><html><body>late-preview-source-must-not-win</body></html>",
      log: "late preview replayed",
    }),
    event("created", 4, "artifact.created", {
      artifact_id: finalArtifact.artifact_id,
      revision_id: finalArtifact.revision_id,
      media_type: finalArtifact.media_type,
      sha256: finalArtifact.sha256,
      title: finalArtifact.title,
    }),
    event("done", 5, "done", {
      status: "succeeded",
      revision_id: finalArtifact.revision_id,
      artifact_ids: [finalArtifact.artifact_id],
      finished_at: invocation.finished_at,
    }),
  ],
}];

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const frameRequests = [];
  let publishModalOpened = false;
  let versionOpened = false;

  await page.addInitScript(() => {
    Element.prototype.requestFullscreen = function requestFullscreen() {
      window.__artifactFullscreenCalls = (window.__artifactFullscreenCalls || 0) + 1;
      return Promise.resolve();
    };
    HTMLAnchorElement.prototype.click = function click() {
      if (this.download) {
        window.__artifactDownloads = [
          ...(window.__artifactDownloads || []),
          { href: this.href, download: this.download, rel: this.rel },
        ];
      }
    };
  });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/oauth2/userinfo") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ sub: "artifact-user", email: "artifact@example.com" }),
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
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/connections") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([connection]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/resources") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([]) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/skills/drafts") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([draft]) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}`) {
      await route.fulfill({
        status: 200,
        headers: { ETag: "draft-artifact-v1" },
        contentType: "application/json",
        body: envelope(draft),
      });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/revisions`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope(revisions) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/conversation`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope(conversation) });
      return;
    }
    if (url.pathname === "/api/knowledge/v1/publications") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([]) });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/artifacts/${finalArtifact.artifact_id}`) {
      await route.fulfill({
        status: 200,
        headers: { ETag: "artifact-final-v1" },
        contentType: "application/json",
        body: envelope(finalArtifact),
      });
      return;
    }
    if (url.pathname === `/api/knowledge/v1/artifacts/${finalArtifact.artifact_id}/content`) {
      frameRequests.push(url.pathname + url.search);
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Security-Policy": finalArtifact.csp,
          "Cache-Control": "no-store",
          "Referrer-Policy": "no-referrer",
          "X-Content-Type-Options": "nosniff",
        },
        contentType: "text/html",
        body: "<!doctype html><html><body><h1>Final artifact rendered</h1></body></html>",
      });
      return;
    }
    if (url.pathname.startsWith("/api/knowledge/v1/artifact-snapshots/")) {
      frameRequests.push(url.pathname + url.search);
      await route.fulfill({
        status: 410,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "ARTIFACT_PREVIEW_EXPIRED" } }),
      });
      return;
    }
    if (url.pathname.endsWith("/publish")) {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: envelope({
          publication_id: "publication-artifact",
          revision_id: finalArtifact.revision_id,
          target_space: "personal",
          status: "published",
          created_at: "2026-08-30T00:05:00Z",
        }),
      });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "NOT_FOUND", message: `missing ${url.pathname}`, retryable: false },
        meta: { request_id: "artifact-evidence" },
      }),
    });
  });

  await page.goto(`${baseURL}/?view=knowledge-workspace&file=draft&draftId=${draft.draft_id}`);
  const workspace = page.locator(".kw-artifact-workspace");
  await workspace.waitFor({ state: "visible" });
  await workspace.locator("iframe").waitFor({ state: "attached" });
  await page.waitForFunction(() => {
    const frame = document.querySelector(".kw-artifact-workspace iframe");
    return frame?.classList.contains("is-loaded");
  });
  const iframe = workspace.locator("iframe").first();
  assert.match(await iframe.getAttribute("src"), /\/api\/knowledge\/v1\/artifacts\/artifact-final\/content/);
  assert.doesNotMatch(await iframe.getAttribute("src"), /artifact-snapshots/);
  assert.equal(await iframe.getAttribute("sandbox"), "");

  await workspace.getByRole("tab", { name: "Source" }).click();
  const source = workspace.locator(".kw-artifact-source");
  await source.waitFor({ state: "visible" });
  assert.equal(await source.getAttribute("readonly"), "");
  assert.match(await source.inputValue(), /immutable-final-lineage/);
  assert.doesNotMatch(await source.inputValue(), /preview-source-must-not-win|late-preview-source-must-not-win/);

  await workspace.getByRole("tab", { name: /Log/ }).click();
  await workspace.getByText("late preview replayed").waitFor();
  await workspace.getByText("final artifact artifact-final", { exact: true }).waitFor();
  await workspace.getByText("controlled same-origin artifact URL").waitFor();

  await workspace.getByLabel("选择版本").selectOption("revision-preview");
  assert.equal(await workspace.getByLabel("选择版本").inputValue(), "revision-preview");
  await workspace.getByLabel("选择版本").selectOption("revision-final");
  assert.equal(await workspace.getByLabel("选择版本").inputValue(), "revision-final");

  const finalFrameCount = frameRequests.filter((item) => item.includes("/artifacts/")).length;
  await workspace.getByRole("button", { name: "刷新预览" }).first().click();
  await page.waitForFunction(
    () => document.querySelector(".kw-artifact-workspace iframe")?.classList.contains("is-loaded"),
  );
  assert.ok(frameRequests.filter((item) => item.includes("/artifacts/")).length >= finalFrameCount);
  await workspace.getByRole("button", { name: "全屏预览" }).click();
  assert.equal(await page.evaluate(() => window.__artifactFullscreenCalls || 0), 1);
  await workspace.getByRole("button", { name: "下载 HTML" }).first().click();
  const exported = await page.evaluate(() => {
    return window.__artifactDownloads?.at(-1) || null;
  });
  assert.ok(exported);
  assert.match(exported.href, /\/api\/knowledge\/v1\/artifacts\/artifact-final\/content/);
  assert.equal(exported.rel, "noreferrer");

  await workspace.getByRole("button", { name: "版本" }).click();
  versionOpened = true;
  await page.getByRole("dialog").getByText("来源与版本历史").waitFor();
  await page.getByRole("dialog").getByRole("button", { name: "关闭" }).click();
  await workspace.getByRole("button", { name: "发布 Skill" }).click();
  await page.getByRole("dialog", { name: "发布 Skill" }).waitFor();
  await page.getByRole("button", { name: "发布到团队" }).waitFor();
  publishModalOpened = true;

  assert.equal(await workspace.getByRole("button", { name: "添加到 Agent" }).count(), 0);
  assert.equal(frameRequests.some((url) => url.includes("/artifact-snapshots/")), false);

  await page.screenshot({
    path: path.join(screenshotDir, "artifact-workspace-1440x900.png"),
  });
  console.log(JSON.stringify({
    status: "PASS",
    production_component_fixture: true,
    final_preferred_over_preview: true,
    panes: ["Preview", "Source", "Log"],
    controls: ["version", "refresh", "fullscreen", "download", "publish"],
    publishModalOpened,
    versionOpened,
    screenshot: path.join(screenshotDir, "artifact-workspace-1440x900.png"),
  }));
  await browser.close();
}

await main();
