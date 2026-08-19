import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const defaultByaanRepo =
  process.env.BYAAN_REPO ||
  "/Users/bytedance/worktrees/session-f-byaan-knowledge-center-20260818";
const playwrightModule =
  process.env.PLAYWRIGHT_MODULE ||
  path.join(defaultByaanRepo, "client/node_modules/playwright/index.mjs");
const { chromium } = await import(playwrightModule);

const reportDir = process.env.REPORT_DIR
  ? path.resolve(process.env.REPORT_DIR)
  : path.join(repoRoot, "docs/knowledge-center/session-reports/live-session-h4-source-port");
const screenshotDir = path.join(reportDir, "screenshots");
const studioBaseUrl = (process.env.VEADK_STUDIO_URL || "http://127.0.0.1:57596").replace(/\/$/, "");
const studioLocalUser = process.env.VEADK_STUDIO_LOCAL_USER || "h4smoke";
const wrenBaseUrl = (process.env.WREN_MODELING_URL || "http://127.0.0.1:3011/modeling").replace(/\/$/, "");
const byaanBaseUrl = (
  process.env.BYAAN_NOTEBOOK_URL ||
  "http://127.0.0.1:15183/notebook/36c04b0d-d412-4b89-aad8-4bd36004fbcb"
).replace(/\/$/, "");
const byaanFallbackUrl = (
  process.env.BYAAN_NOTEBOOK_FALLBACK_URL || "http://127.0.0.1:15183/notebook/new"
).replace(/\/$/, "");
const byaanAuthEnvFile = process.env.BYAAN_AUTH_ENV_FILE || "/tmp/session-f-preview-current.team.env";

const viewports = [
  { key: "desktop", width: 1440, height: 900 },
  { key: "mobile", width: 390, height: 844 },
];

const result = {
  schema: "agentkit.knowledge_center.h4_source_port_smoke.v1",
  generatedAt: new Date().toISOString(),
  studioBaseUrl,
  wrenBaseUrl,
  byaanBaseUrl,
  byaanFallbackUrl,
  api: {},
  screenshots: {},
  visual: {},
  checks: [],
  limitations: [],
};

function recordCheck(name, ok, details = {}) {
  result.checks.push({ name, ok: Boolean(ok), ...details });
  if (!ok) throw new Error(`${name} failed: ${JSON.stringify(details)}`);
}

async function api(route, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(`${studioBaseUrl}${route}`, { ...options, headers });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text };
  }
  if (!response.ok) {
    throw new Error(`${route} failed ${response.status}: ${text.slice(0, 500)}`);
  }
  return body;
}

async function pollJob(jobId, label) {
  let latest = await api(`/api/knowledge-assets/build-jobs/${encodeURIComponent(jobId)}`);
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (!["queued", "running", "pending", "building"].includes(String(latest.status))) {
      return latest;
    }
    await new Promise((resolve) => setTimeout(resolve, attempt < 3 ? 300 : 1000));
    latest = await api(`/api/knowledge-assets/build-jobs/${encodeURIComponent(jobId)}`);
  }
  throw new Error(`${label} did not finish: ${JSON.stringify(latest)}`);
}

async function writeJson(file, value) {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function readByaanAuth() {
  if (process.env.BYAAN_AUTH_EMAIL && process.env.BYAAN_AUTH_PASSWORD) {
    return {
      email: process.env.BYAAN_AUTH_EMAIL,
      password: process.env.BYAAN_AUTH_PASSWORD,
      source: "env",
    };
  }
  try {
    const envText = await readFile(byaanAuthEnvFile, "utf8");
    const values = {};
    for (const line of envText.split(/\r?\n/)) {
      const match = line.match(/^\s*(?:export\s+)?([A-Z0-9_]+)=['"]?([^'"]*)['"]?\s*$/);
      if (match) values[match[1]] = match[2];
    }
    if (values.MASTER_USER_EMAIL && values.MASTER_USER_PASSWORD) {
      return {
        email: values.MASTER_USER_EMAIL,
        password: values.MASTER_USER_PASSWORD,
        source: byaanAuthEnvFile,
      };
    }
  } catch {
    // Fall through to explicit failure below.
  }
  return null;
}

async function seedAndExerciseApi() {
  const health = await api("/api/knowledge-assets/health");
  result.api.health = health;
  recordCheck("health route returns sqlite store", String(health.store || "").includes("sqlite"), {
    store: health.store,
  });
  recordCheck("semantic builder health is non-mock", health.agents?.semantic_builder?.mock !== true, {
    semantic_builder: health.agents?.semantic_builder,
  });
  recordCheck("asktable dashboard health is non-mock", health.agents?.asktable_dashboard?.mock !== true, {
    asktable_dashboard: health.agents?.asktable_dashboard,
  });

  const space = await api("/api/knowledge-assets/spaces", {
    method: "POST",
    body: JSON.stringify({ name: "H4 Source Port Smoke" }),
  });
  const source = await api("/api/knowledge-assets/sources", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      source_type: "database",
      provider: "oracle",
      name: "H4 Oracle Sales",
      description: "Local H4 source-port live smoke database source",
    }),
  });
  const snapshot = await api("/api/knowledge-assets/snapshots", {
    method: "POST",
    body: JSON.stringify({
      source_id: source.id,
      asset_type: "knowledge_resource",
      asset_id: "h4-oracle-schema",
      capability_kind: "retrieval_binding",
      name: "H4 Oracle schema snapshot",
      kind: "schema_snapshot",
      schema: {
        tables: [
          {
            name: "sales_order",
            columns: [
              { name: "ticket_id", type: "number", primary_key: true },
              { name: "store_id", type: "number" },
              { name: "ticket_amount", type: "number" },
              { name: "order_date", type: "date" },
            ],
          },
          {
            name: "store",
            columns: [
              { name: "store_id", type: "number", primary_key: true },
              { name: "store_name", type: "string" },
              { name: "region", type: "string" },
            ],
          },
        ],
        relationships: [
          {
            id: "sales_store",
            from_table: "sales_order",
            to_table: "store",
            join_fields: [{ from: "store_id", to: "store_id" }],
          },
        ],
      },
      profile: {
        snapshot: {
          status: "fresh",
          id: "h4-oracle-sales-snapshot",
          hash: "h4-source-port-golden-results",
          data_through: "2026-08-18T00:00:00Z",
        },
        golden_results: {
          top_3_stores_by_sales_order_count: [
            { store_store_name: "VNPTTE", sales_order_count: 56 },
            { store_store_name: "SG - ANTA VIVO City", sales_order_count: 9 },
            { store_store_name: "Hanoi Flagship", sales_order_count: 7 },
          ],
          sales_order_count_last_30_snapshot_days: 72,
        },
      },
    }),
  });
  const semanticJob = await api("/api/knowledge-assets/build/semantic-skill", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      source_ids: [source.id],
      snapshot_ids: [snapshot.id],
      name: "H4 Sales Semantic Skill",
      intent: "Model sales tickets by store and region",
      target_domain: "sales",
      publish: true,
    }),
  });
  const semanticJobLoaded = await pollJob(semanticJob.id, "semantic builder job");
  recordCheck("semantic builder agent produced persisted job", semanticJobLoaded.status === "succeeded", {
    jobStatus: semanticJobLoaded.status,
    agentStatus: semanticJobLoaded.output?.agent_status,
    runnerBackend: semanticJobLoaded.output?.runner_backend,
  });
  const semanticList = await api(
    "/api/knowledge-assets/assets?asset_type=semantic_model&capability_kind=semantic_skill",
  );
  const semanticAsset = semanticList.items.find((item) => item.name === "H4 Sales Semantic Skill") || semanticList.items[0];
  recordCheck("semantic skill persisted in KnowledgeAssetStore", Boolean(semanticAsset?.asset_id), {
    semanticAssetId: semanticAsset?.asset_id,
  });
  const askdata = await api("/api/knowledge-assets/askdata/query", {
    method: "POST",
    body: JSON.stringify({
      semantic_asset_id: semanticAsset.asset_id,
      metric: "sales_order_count",
      dimensions: ["store_store_name"],
      question: "按门店查看销售票数",
      limit: 100,
    }),
  });
  recordCheck("askdata agent returns governed non-empty evidence", askdata.status === "completed" && (askdata.data?.rows?.length || 0) > 0, {
    status: askdata.status,
    agent: askdata.agent,
    rows: askdata.data?.rows?.length,
  });
  const dashboard = await api("/api/knowledge-assets/build/dashboard-skill", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      semantic_asset_id: semanticAsset.asset_id,
      name: "H4 Sales Dashboard Skill",
      intent: "Create a governed dashboard draft from store sales evidence",
      metric: "sales_order_count",
      dimensions: ["store_store_name"],
      publish: true,
    }),
  });
  recordCheck("dashboard agent persisted dashboard skill", dashboard.status === "succeeded", {
    dashboardAssetId: dashboard.dashboard_asset_id,
    agent: dashboard.agent,
  });
  const overview = await api(`/api/knowledge-assets/workbench/overview?space_id=${encodeURIComponent(space.id)}`);
  const semanticCapabilityCount = Number(overview.capability_counts?.semantic_skill || 0);
  const dashboardCapabilityCount = Number(overview.capability_counts?.dashboard_skill || 0);
  const recentJobIds = Array.isArray(overview.recent_jobs)
    ? overview.recent_jobs.map((job) => job.id)
    : [];
  recordCheck(
    "refresh overview reads persisted semantic and dashboard results",
    semanticCapabilityCount >= 1 &&
      dashboardCapabilityCount >= 1 &&
      recentJobIds.includes(semanticJob.id) &&
      recentJobIds.includes(dashboard.job_id),
    {
      capabilityCounts: overview.capability_counts,
      recentJobIds,
    },
  );
  result.api.seed = {
    spaceId: space.id,
    sourceId: source.id,
    snapshotId: snapshot.id,
    semanticJobId: semanticJob.id,
    semanticAssetId: semanticAsset.asset_id,
    dashboardAssetId: dashboard.dashboard_asset_id,
    askdataRows: askdata.data?.rows?.length || 0,
  };
}

async function visualHealth(page, label) {
  const metrics = await page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const visibleText = (body.innerText || "").trim();
    const viewportWidth = window.innerWidth;
    const all = Array.from(document.querySelectorAll("*"));
    const overflowing = all
      .map((node) => {
        if (!(node instanceof HTMLElement)) return null;
        let parent = node.parentElement;
        while (parent && parent !== document.body) {
          const parentStyle = window.getComputedStyle(parent);
          if (/(auto|scroll)/.test(parentStyle.overflowX) && parent.scrollWidth > parent.clientWidth + 2) {
            return null;
          }
          parent = parent.parentElement;
        }
        const rect = node.getBoundingClientRect();
        return {
          tag: node.tagName,
          className: String(node.getAttribute("class") || "").slice(0, 100),
          text: String(node.textContent || "").trim().slice(0, 100),
          left: rect.left,
          right: rect.right,
          width: rect.width,
          height: rect.height,
        };
      })
      .filter(
        (item) =>
          item &&
          item.width > 0 &&
          item.height > 0 &&
          (item.left < -2 || item.right > viewportWidth + 2),
      )
      .slice(0, 10);
    return {
      title: document.title,
      visibleTextLength: visibleText.length,
      scrollWidth: Math.max(doc.scrollWidth, body.scrollWidth),
      clientWidth: doc.clientWidth,
      overflowing,
      iframeCount: document.querySelectorAll("iframe").length,
      sourcePorts: Array.from(document.querySelectorAll("[data-source-port]")).map((node) =>
        node.getAttribute("data-source-port"),
      ),
    };
  });
  recordCheck(`${label} is not blank`, metrics.visibleTextLength > 20, metrics);
  recordCheck(`${label} has no iframe`, metrics.iframeCount === 0, metrics);
  recordCheck(`${label} has no horizontal page overflow`, metrics.scrollWidth <= metrics.clientWidth + 3, metrics);
  recordCheck(`${label} has no visible offscreen elements`, metrics.overflowing.length === 0, metrics);
  return metrics;
}

async function gotoKnowledgeTab(page, tabName) {
  await page.addInitScript((name) => {
    window.localStorage.setItem("veadk_local_user", name);
    window.sessionStorage.setItem("veadk_local_user_tab", name);
  }, studioLocalUser);
  await page.goto(studioBaseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("body", { timeout: 15000 });

  const usernameInput = page.getByPlaceholder(/用户名|username/i).first();
  if (await usernameInput.count()) {
    await usernameInput.fill(studioLocalUser);
    await page.getByRole("button", { name: /进入|continue|start/i }).click();
    await page.waitForTimeout(800);
  }

  const knowledgeNav = page.getByRole("button", { name: /知识资产|Knowledge Assets|Knowledge Center/ }).first();
  if (await knowledgeNav.count()) {
    await knowledgeNav.click();
  }
  try {
    await page.waitForSelector(".kc-native-tabs", { timeout: 20000 });
    await page.getByRole("button", { name: tabName }).first().click({ timeout: 20000 });
  } catch (error) {
    const text = await page.locator("body").innerText({ timeout: 3000 }).catch(() => "");
    throw new Error(`failed to open Knowledge Center tab ${String(tabName)}: ${error.message}; body=${text.slice(0, 1000)}`);
  }
  await page.waitForTimeout(1200);
}

async function captureTarget(page, viewport, kind, fileName, tabName, sourceSelector) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await gotoKnowledgeTab(page, tabName);
  await page.waitForSelector(sourceSelector, { timeout: 15000 });
  const metrics = await visualHealth(page, `target ${kind} ${viewport.key}`);
  const file = path.join(screenshotDir, fileName);
  await page.screenshot({ path: file, fullPage: true });
  result.screenshots[fileName] = { path: file, metrics };
}

async function authenticateByaan(page) {
  const auth = await readByaanAuth();
  if (!auth) {
    throw new Error(`BYAAN auth unavailable; provide BYAAN_AUTH_EMAIL/BYAAN_AUTH_PASSWORD or ${byaanAuthEnvFile}`);
  }
  const base = new URL(byaanBaseUrl).origin;
  await page.goto(`${base}/login`, { waitUntil: "domcontentloaded", timeout: 20000 });
  await page.getByLabel(/email/i).fill(auth.email);
  await page.getByLabel(/password/i).fill(auth.password);
  await page.getByRole("button", { name: /sign in|login/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20000 });
  await page.waitForTimeout(1200);
  return auth.source;
}

async function captureExternalBaseline(browser, viewport, url, fileName, label, requiredPattern, options = {}) {
  const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
  try {
    let authSource = null;
    if (options.authenticate === "byaan") authSource = await authenticateByaan(page);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.waitForTimeout(1800);
    let text = await page.locator("body").innerText({ timeout: 4000 }).catch(() => "");
    if (options.fallbackUrl && (requiredPattern && !requiredPattern.test(text))) {
      await page.goto(options.fallbackUrl, { waitUntil: "domcontentloaded", timeout: 20000 });
      await page.waitForTimeout(1800);
      text = await page.locator("body").innerText({ timeout: 4000 }).catch(() => "");
      url = options.fallbackUrl;
    }
    if (requiredPattern && !requiredPattern.test(text)) {
      throw new Error(`baseline did not show expected notebook content; url=${url}; text=${text.slice(0, 240)}`);
    }
    if (/Invitation Only|Sign in to your account|Welcome back|Forgot password/i.test(text)) {
      throw new Error(`baseline resolved to BYAAN login screen; url=${url}; text=${text.slice(0, 240)}`);
    }
    const file = path.join(screenshotDir, fileName);
    await page.screenshot({ path: file, fullPage: true });
    result.screenshots[fileName] = {
      path: file,
      baselineAvailable: true,
      auth: authSource ? { type: "byaan-local-login", source: authSource } : undefined,
      url,
      textSample: text.slice(0, 180),
    };
  } catch (error) {
    const file = path.join(screenshotDir, fileName);
    await page.setContent(
      `<main style="font:14px system-ui;padding:24px;max-width:760px"><h1>${label} unavailable</h1><p>${String(
        error.message || error,
      )}</p><p>URL: ${url}</p></main>`,
    );
    await page.screenshot({ path: file, fullPage: true });
    result.screenshots[fileName] = {
      path: file,
      baselineAvailable: false,
      error: String(error.message || error),
    };
    result.limitations.push({ label, url, reason: String(error.message || error) });
    if (options.required !== false) throw error;
  } finally {
    await page.close();
  }
}

async function makeSideBySide(browser, viewport, leftFile, rightFile, outFile, label) {
  const leftUri = `file://${path.resolve(screenshotDir, leftFile)}`;
  const rightUri = `file://${path.resolve(screenshotDir, rightFile)}`;
  const page = await browser.newPage({ viewport: { width: Math.max(900, viewport.width * 2), height: viewport.height } });
  const html = `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;font:13px system-ui;background:#111;color:#f8fafc}
    header{height:34px;display:grid;grid-template-columns:1fr 1fr;align-items:center}
    header span{padding:8px 12px;border-right:1px solid #333}
    main{display:grid;grid-template-columns:1fr 1fr;gap:0}
    img{width:100%;display:block;background:white;border-top:1px solid #333}
  </style><header><span>${label} baseline</span><span>${label} AgentKit target</span></header>
  <main><img src="${leftUri}"><img src="${rightUri}"></main>`;
  await page.setContent(html, { waitUntil: "load" });
  const file = path.join(screenshotDir, outFile);
  await page.screenshot({ path: file, fullPage: true });
  result.visual[outFile] = { path: file, left: leftFile, right: rightFile };
  await page.close();
}

async function captureScreenshots() {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of viewports) {
      await captureExternalBaseline(
        browser,
        viewport,
        wrenBaseUrl,
        `baseline-wren-modeling-${viewport.key}.png`,
        `Wren modeling ${viewport.key}`,
        /Modeling|model/i,
      );
      await captureExternalBaseline(
        browser,
        viewport,
        byaanBaseUrl,
        `baseline-byaan-notebook-${viewport.key}.png`,
        `BYAAN notebook ${viewport.key}`,
        /Notebook|Query|Dashboard|Byaan the data|Analyzing/i,
        { authenticate: "byaan", fallbackUrl: byaanFallbackUrl },
      );
      const target = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
      await captureTarget(
        target,
        viewport,
        "semantic",
        `target-agentkit-semantic-${viewport.key}.png`,
        /语义构建|Semantic/,
        "[data-source-port='wren-modeling']",
      );
      await captureTarget(
        target,
        viewport,
        "askdashboard",
        `target-agentkit-askdashboard-${viewport.key}.png`,
        /AskTable|Dashboard/,
        "[data-source-port='byaan-notebook-dashboard']",
      );
      await target.close();
      await makeSideBySide(
        browser,
        viewport,
        `baseline-wren-modeling-${viewport.key}.png`,
        `target-agentkit-semantic-${viewport.key}.png`,
        `side-by-side-wren-semantic-${viewport.key}.png`,
        `Wren semantic ${viewport.key}`,
      );
      await makeSideBySide(
        browser,
        viewport,
        `baseline-byaan-notebook-${viewport.key}.png`,
        `target-agentkit-askdashboard-${viewport.key}.png`,
        `side-by-side-byaan-askdashboard-${viewport.key}.png`,
        `BYAAN askdashboard ${viewport.key}`,
      );
    }
  } finally {
    await browser.close();
  }
}

async function writeSourceLocationNotes() {
  const notes = {
    wren: [
      "/Users/bytedance/wrenai-legacy-v1-style-a/wren-ui/src/pages/modeling.tsx",
      "/Users/bytedance/wrenai-legacy-v1-style-a/wren-ui/src/components/diagram/index.tsx",
      "/Users/bytedance/wrenai-legacy-v1-style-a/wren-ui/src/components/diagram/customNode/ModelNode.tsx",
      "/Users/bytedance/wrenai-legacy-v1-style-a/wren-ui/src/components/sidebar/Modeling.tsx",
      "/Users/bytedance/wrenai-legacy-v1-style-a/wren-ui/src/components/sidebar/modeling/*",
    ],
    byaan: [
      "/Users/bytedance/worktrees/session-f-byaan-knowledge-center-20260818/client/src/components/NotebookQueryPanel.tsx",
      "/Users/bytedance/worktrees/session-f-byaan-knowledge-center-20260818/client/src/components/QueryEditor.tsx",
      "/Users/bytedance/worktrees/session-f-byaan-knowledge-center-20260818/client/src/components/QueryResults.tsx",
      "/Users/bytedance/worktrees/session-f-byaan-knowledge-center-20260818/client/src/components/QueryRunnerDocked.tsx",
      "/Users/bytedance/worktrees/session-f-byaan-knowledge-center-20260818/client/src/features/dashboard/pages/DashboardWorkspacePage.tsx",
    ],
    target: [
      "frontend/src/features/knowledge-assets/source-ports/wren/WrenModelingSourcePort.tsx",
      "frontend/src/features/knowledge-assets/adapters/wrenSemanticAdapter.ts",
      "frontend/src/features/knowledge-assets/source-ports/byaan/ByaanNotebookDashboardSourcePort.tsx",
      "frontend/src/features/knowledge-assets/adapters/byaanAskTableAdapter.ts",
      "frontend/src/knowledge-center/SemanticModelingWorkbench.tsx",
      "frontend/src/knowledge-center/AskDashboardWorkbench.tsx",
    ],
  };
  await writeJson(path.join(reportDir, "source-locations.json"), notes);
}

await mkdir(screenshotDir, { recursive: true });
await seedAndExerciseApi();
await captureScreenshots();
await writeSourceLocationNotes();
result.visual.summary = {
  method: "Side-by-side screenshots generated. Pixelmatch was not used because source/target data and authentication state differ; structural checks validate no blank pages, no iframe, no page overflow, and source-port markers.",
  limitations: result.limitations,
};
await writeJson(path.join(reportDir, "result.json"), result);
console.log(JSON.stringify(result, null, 2));
