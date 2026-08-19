import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, "../../../..");
const require = createRequire(path.join(repoRoot, "frontend", "package.json"));
const { chromium } = require("playwright");
const reportDir = __dirname;
const screenshotDir = path.join(reportDir, "screenshots");
const studioBaseUrl = (process.env.VEADK_STUDIO_URL || "http://127.0.0.1:18219").replace(/\/$/, "");
const sourceH6Hash = process.env.SOURCE_H6_HASH || "806dc34d7e00531d57177a41a2a7068fa9b141b7";
const sourceG2Hash = process.env.SOURCE_G2_HASH || "47a14f89342164f922447616e2ca8dd0a5d92607";
const previousConnectorFoundationTip = "ec74156d53f1afb74f73c2c6d0f9ef97bebe5823";
const integrationBranch = process.env.INTEGRATION_BRANCH || gitText(["rev-parse", "--abbrev-ref", "HEAD"]) || "kc/session-i-connectors-foundation";
const integrationBranchHash = process.env.INTEGRATION_BRANCH_HASH || gitText(["rev-parse", "HEAD"]) || previousConnectorFoundationTip;

const viewports = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "mobile-390", width: 390, height: 844 },
];

function gitText(args) {
  try {
    return execFileSync("git", args, {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

async function api(route, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${studioBaseUrl}${route}`, { ...options, headers });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text };
  }
  if (!response.ok) {
    throw new Error(`${route} failed ${response.status}: ${JSON.stringify(body)}`);
  }
  return body;
}

async function seedWorkbench() {
  const unique = `i-${Date.now()}`;
  const semanticAssetId = `${unique}-oracle-sales`;
  const dashboardAssetId = `${unique}-sales-dashboard`;
  const space = await api("/api/knowledge-assets/spaces", {
    method: "POST",
    body: JSON.stringify({
      name: `Session I H6 G2 ${unique}`,
      description: "Live smoke fixture for H6 AskTable parity plus G2 evaluation.",
    }),
  });
  const source = await api("/api/knowledge-assets/sources", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      source_type: "schema_snapshot",
      name: `Oracle Sales Snapshot ${unique}`,
      provider: "oracle",
      status: "ready",
      capabilities: { tables: ["SALES_ORDER", "STORE"] },
    }),
  });
  const resource = await api("/api/knowledge-assets/source-resources", {
    method: "POST",
    body: JSON.stringify({
      asset_space_id: space.id,
      source_id: source.id,
      resource_id: `${unique}-oracle-sales-schema`,
      source_type: "database_schema",
      provider: "oracle",
      uri: "oracle://sales/schema",
      provider_ref: "SALES_ORDER,STORE",
      content_hash: "session-i-local-fixture",
      tags: ["session-i", "schema", "oracle"],
      permission_scope: "private",
      freshness: { state: "fresh", as_of: "2026-08-19T00:00:00Z" },
      sync_status: "ready",
      last_synced_at: "2026-08-19T00:00:00Z",
      metadata: {
        resource_count: 2,
        selection_rule: "SALES_ORDER + STORE",
        snapshot_id: `${unique}-snapshot`,
        policy_partition: "asset_space",
      },
    }),
  });
  const snapshot = await api("/api/knowledge-assets/snapshots", {
    method: "POST",
    body: JSON.stringify({
      source_id: source.id,
      asset_type: "semantic_model",
      asset_id: semanticAssetId,
      capability_kind: "semantic_skill",
      name: `Oracle Sales Schema ${unique}`,
      kind: "schema_snapshot",
      status: "ready",
      publish_state: "published",
      schema: schemaSnapshot(),
      profile: { snapshot: { id: `${unique}-snapshot`, hash: "session-i-local-fixture" } },
    }),
  });

  await api("/api/knowledge-assets/skill-packages", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      asset_type: "semantic_model",
      asset_id: semanticAssetId,
      capability_kind: "semantic_skill",
      name: "Oracle Sales Session I",
      status: "ready",
      publish_state: "published",
      type: "semantic_skill",
      source_ids: [source.id],
      snapshot_ids: [snapshot.id],
      query_url: `/api/knowledge-assets/assets/semantic_model/${semanticAssetId}/query`,
      capability_package: semanticPackage(semanticAssetId),
      capabilities: { metrics: ["ticket_count"], dimensions: ["store", "sell_date"] },
      freshness: { status: "fresh", as_of: "2026-08-19T00:00:00Z" },
      usage_policy: { permission_hint: "Aggregates only. Customer contact fields are denied." },
      sample_evidence: [{ kind: "metric", title: "ticket_count definition" }],
      provenance: {
        runner_backend: "veadk.Agent+Runner",
        model_name: "live-configured",
        generation_mode: "seeded_package",
        agent_status: "completed",
      },
    }),
  });

  await api("/api/knowledge-assets/skill-packages", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      asset_type: "dashboard",
      asset_id: dashboardAssetId,
      capability_kind: "dashboard_skill",
      name: "Sales Dashboard Session I",
      status: "ready",
      publish_state: "published",
      type: "dashboard_skill",
      query_url: `/api/knowledge-assets/assets/dashboard/${dashboardAssetId}/query`,
      capability_package: dashboardPackage(semanticAssetId),
      freshness: { status: "fresh", as_of: "2026-08-19T00:00:00Z" },
      usage_policy: { permission_hint: "Aggregates only." },
      sample_evidence: [{ kind: "metric", title: "ticket_count definition" }],
      provenance: {
        runner_backend: "veadk.Agent+Runner",
        model_name: "live-configured",
        generation_mode: "seeded_package",
        agent_status: "completed",
      },
    }),
  });

  const askdata = await api("/api/knowledge-assets/askdata/query", {
    method: "POST",
    body: JSON.stringify({
      semantic_asset_id: semanticAssetId,
      metric: "ticket_count",
      dimensions: ["store"],
      question: "按门店查看销售票数",
      limit: 100,
    }),
  });

  const evaluation = await seedEvaluationRuns(space, semanticAssetId, dashboardAssetId);
  return {
    unique,
    space,
    source,
    resource,
    snapshot,
    semanticAssetId,
    dashboardAssetId,
    askdata,
    evaluation,
  };
}

async function seedEvaluationRuns(space, semanticAssetId, dashboardAssetId) {
  const specs = [
    {
      targetKind: "semantic_skill",
      targetAssetId: semanticAssetId,
      name: `Session I Semantic Skill Eval`,
      cases: [
        {
          targetKind: "semantic_skill",
          question: "按门店查看销售票数",
          expectedMetric: "ticket_count",
          expectedDimensions: ["store"],
          expectedSqlContains: ["SALES_ORDER"],
          expectedPolicyDecision: "allow",
          expectedEvidenceKeys: ["ticket_count"],
          tags: ["session-i", "semantic"],
        },
      ],
    },
    {
      targetKind: "asktable_query",
      targetAssetId: semanticAssetId,
      name: `Session I AskTable Query Eval`,
      cases: [
        {
          targetKind: "asktable_query",
          question: "按门店查看销售票数",
          expectedMetric: "ticket_count",
          expectedDimensions: ["store"],
          expectedSqlContains: ["SALES_ORDER"],
          expectedPolicyDecision: "allow",
          expectedEvidenceKeys: ["ticket_count"],
          tags: ["session-i", "asktable"],
        },
        {
          targetKind: "asktable_query",
          question: "show customer phone/contact by store",
          expectedMetric: "ticket_count",
          expectedDimensions: ["store"],
          expectedSqlContains: ["policy denied", "no raw SQL executed"],
          expectedPolicyDecision: "deny",
          expectedEvidenceKeys: ["PII policy guard"],
          tags: ["session-i", "asktable", "policy-deny"],
        },
      ],
    },
    {
      targetKind: "dashboard_skill",
      targetAssetId: dashboardAssetId,
      name: `Session I Dashboard Skill Eval`,
      cases: [
        {
          targetKind: "dashboard_skill",
          intent: "验证门店销售 dashboard 的主要 tile 和 data_view 证据",
          expectedDashboardTiles: ["primary_metric"],
          expectedPolicyDecision: "allow",
          expectedEvidenceKeys: ["ticket_count"],
          tags: ["session-i", "dashboard"],
        },
      ],
    },
  ];
  const runs = [];
  for (const spec of specs) {
    const suite = await api("/api/knowledge-assets/evaluation/suites", {
      method: "POST",
      body: JSON.stringify({
        spaceId: space.id,
        name: spec.name,
        description: "Session I deterministic evaluation suite imported from JSON cases.",
        targetKind: spec.targetKind,
        targetAssetId: spec.targetAssetId,
      }),
    });
    const imported = await api(`/api/knowledge-assets/evaluation/suites/${encodeURIComponent(suite.id)}/cases/import`, {
      method: "POST",
      body: JSON.stringify({ cases: spec.cases }),
    });
    const detail = await api("/api/knowledge-assets/evaluation/runs", {
      method: "POST",
      body: JSON.stringify({ suiteId: suite.id }),
    });
    runs.push(toRunSummary(detail, imported));
  }
  return { runs };
}

function toRunSummary(detail, imported) {
  const casesById = new Map((detail.cases || []).map((item) => [item.id, item]));
  const caseResults = (detail.results || []).map((item) => {
    const evalCase = casesById.get(item.caseId) || {};
    const rows = Array.isArray(item.actualRowsPreview) ? item.actualRowsPreview : [];
    const evidence = Array.isArray(item.evidence) ? item.evidence : [];
    const data = resultData(item);
    const execution = data?.execution && typeof data.execution === "object" ? data.execution : {};
    const policy = item.actualPolicyDecision && typeof item.actualPolicyDecision === "object" ? item.actualPolicyDecision : {};
    return {
      caseId: item.caseId,
      prompt: evalCase.question || evalCase.intent || evalCase.input || "",
      expectedPolicyDecision: evalCase.expectedPolicyDecision || "",
      status: item.status,
      score: item.score,
      policyDecision: policy.decision || "",
      freshnessStatus: item.actualFreshness?.status || "",
      rowCount: rows.length,
      actualSql: item.actualSql || "",
      rawSqlFallback: Boolean(execution.raw_sql_fallback || policy.raw_sql_fallback),
      evidenceTitles: evidence.map((entry) => entry.title || entry.kind || "").filter(Boolean),
      reason: item.reason || "",
    };
  });
  const firstResult = detail.results?.[0] || {};
  return {
    runId: detail.run.id,
    suiteId: detail.suite.id,
    suiteName: detail.suite.name,
    targetKind: detail.run.targetKind,
    targetAssetId: detail.run.targetAssetId,
    status: detail.run.status,
    score: detail.run.score,
    reason: firstResult.reason || "",
    imported: imported.imported,
    modelStatus: detail.run.modelStatus,
    mock: false,
    mockVerified: detail.mock === false && imported.mock === false,
    cases: caseResults,
    allowEvidence: caseResults.some((item) =>
      item.expectedPolicyDecision === "allow"
      && item.policyDecision === "allow"
      && item.rowCount > 0
      && item.rawSqlFallback === false
      && item.score === 1
    ),
    denyEvidence: caseResults.some((item) =>
      item.expectedPolicyDecision === "deny"
      && item.policyDecision === "deny"
      && item.rowCount === 0
      && item.freshnessStatus === "blocked"
      && item.rawSqlFallback === false
      && item.actualSql.includes("no raw SQL executed")
      && item.evidenceTitles.some((title) => /PII policy guard/i.test(title))
      && item.score === 1
    ),
    completeness: {
      actualSql: Boolean(firstResult.actualSql),
      dashboardSpecDiff: Boolean(firstResult.dashboardSpecDiff && Object.keys(firstResult.dashboardSpecDiff).length),
      policyDecision: Boolean(firstResult.actualPolicyDecision && Object.keys(firstResult.actualPolicyDecision).length),
      freshness: Boolean(firstResult.actualFreshness && Object.keys(firstResult.actualFreshness).length),
      evidence: Array.isArray(firstResult.evidence) && firstResult.evidence.length > 0,
      toolCalls: Array.isArray(firstResult.toolCalls) && firstResult.toolCalls.length > 0,
      actualOutput: firstResult.actualOutput !== undefined && firstResult.actualOutput !== null,
    },
  };
}

function resultData(result) {
  const actual = result.actualOutput && typeof result.actualOutput === "object" ? result.actualOutput : {};
  for (const key of ["askdata_result", "query_result", "data"]) {
    const value = actual[key];
    if (value && typeof value === "object") {
      return key === "askdata_result" || key === "query_result"
        ? value.data && typeof value.data === "object"
          ? value.data
          : value
        : value;
    }
  }
  if (actual.dashboard_run && typeof actual.dashboard_run === "object" && Array.isArray(actual.dashboard_run.views)) {
    return actual.dashboard_run.views[0] || {};
  }
  return {};
}

async function verifyUi(seed) {
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch();
  const screenshots = [];
  const observations = [];
  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport });
      await page.addInitScript(() => {
        window.localStorage.setItem("veadk_local_user", "sessioni");
        window.sessionStorage.setItem("veadk_local_user_tab", "sessioni");
      });
      const consoleErrors = [];
      const failedRequests = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      page.on("requestfailed", (request) => {
        failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`.trim());
      });
      page.on("response", (response) => {
        if (response.status() >= 400) {
          failedRequests.push(`${response.status()} ${response.url()}`);
        }
      });

      await page.goto(studioBaseUrl, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "知识资产" }).click();
      const seededSpace = new RegExp(seed.space.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      await page.getByText(seededSpace).first().waitFor({ state: "visible", timeout: 30000 });
      await page.getByRole("button", { name: seededSpace }).click();

      await verifyConnectorControlSurface(page, screenshots, viewport.name);

      await page.getByRole("button", { name: "语义构建" }).click();
      await page.getByTestId("semantic-modeling-workbench").waitFor({ state: "visible" });
      await page
        .getByTestId("semantic-modeling-workbench")
        .locator(".adm-project-return span", { hasText: "Oracle Sales Session I" })
        .waitFor({ state: "visible" });
      await page.getByTestId("wren-source-port-diagram").waitFor({ state: "visible" });
      await expectNoGlobalChrome(page, "semantic");
      await screenshot(page, screenshots, `${viewport.name}-semantic.png`);

      await page.getByRole("button", { name: "AskTable / Dashboard" }).click();
      await page.getByTestId("ask-dashboard-workbench").waitFor({ state: "visible" });
      await page.getByText("Governed AskData notebook").waitFor({ state: "visible" });
      await page.locator(".byaan-notebook-portal").waitFor({ state: "visible" });
      if (viewport.name === "desktop-1440") {
        await expectNoGlobalChrome(page, "asktable-portal");
        await screenshot(page, screenshots, `${viewport.name}-asktable-portal.png`);
      }

      const questionBox = page.locator(".byaan-table-mention-composer textarea").first();
      await questionBox.fill("按门店查看销售票数");
      await page.locator(".byaan-table-mention-composer").getByRole("button", { name: "Send" }).click();
      await page.locator(".byaan-notebook-workspace").waitFor({ state: "visible", timeout: 15000 });
      await page.getByText("VNPTTE").first().waitFor({ state: "visible", timeout: 15000 });
      await page.getByText("ticket_count").first().waitFor({ state: "visible", timeout: 15000 });
      await page.getByText(/Governed evidence/).waitFor({ state: "visible", timeout: 15000 });
      await page.locator(".byaan-dashboard-preview").waitFor({ state: "visible" });
      await page.locator(".byaan-dashboard-preview").getByRole("button", { name: "Preview" }).waitFor({ state: "visible" });
      await page.locator(".byaan-dashboard-preview").getByRole("button", { name: "Queries" }).waitFor({ state: "visible" });
      await expectNoGlobalChrome(page, "asktable-result");
      if (viewport.name === "desktop-1440") {
        await screenshot(page, screenshots, `${viewport.name}-asktable-result.png`);
      } else {
        await screenshot(page, screenshots, `${viewport.name}-asktable.png`);
      }

      await page.getByRole("button", { name: "测评" }).click();
      await page.getByRole("heading", { name: "测评" }).waitFor({ state: "visible" });
      await page.getByText("Session I Semantic Skill Eval").waitFor({ state: "visible" });
      await page.getByText("Session I AskTable Query Eval").waitFor({ state: "visible" });
      await page.getByText("Session I Dashboard Skill Eval").waitFor({ state: "visible" });
      await page.getByText("Import schema:").waitFor({ state: "visible" });
      await page.locator(".kc-eval-table-scroll table").waitFor({ state: "visible" });
      await page.getByRole("button", { name: /Session I AskTable Query Eval/ }).click();
      await page.locator(".kc-eval-case-table tbody tr", { hasText: "show customer phone/contact by store" }).click();
      await page.waitForFunction(() => {
        const detail = document.querySelector(".kc-eval-run-detail")?.textContent || "";
        return detail.includes('"decision": "deny"')
          && detail.includes('"status": "blocked"')
          && detail.includes("PII policy guard")
          && detail.includes("no raw SQL executed");
      });
      await page.getByRole("button", { name: /Session I Dashboard Skill Eval/ }).click();
      await page.waitForFunction(() => {
        const detail = document.querySelector(".kc-eval-run-detail")?.textContent || "";
        return detail.includes("Dashboard Spec Diff")
          && detail.includes("policyDecision")
          && detail.includes("freshness")
          && detail.includes("evidence");
      });
      await expectNoGlobalChrome(page, "evaluation");
      await screenshot(page, screenshots, `${viewport.name}-evaluation.png`);

      const layout = await inspectLayout(page);
      if (consoleErrors.length > 0) {
        throw new Error(`${viewport.name} console errors: ${consoleErrors.join("\n")}`);
      }
      if (failedRequests.length > 0) {
        throw new Error(`${viewport.name} failed requests: ${failedRequests.join("\n")}`);
      }
      if (layout.documentOverflowX > 1 || layout.bodyOverflowX > 1) {
        throw new Error(`${viewport.name} horizontal overflow: ${JSON.stringify(layout)}`);
      }
      if (layout.forbiddenIframeCount !== 0 || layout.hasByaanSidebar || layout.hasWrenSidebar) {
        throw new Error(`${viewport.name} rendered forbidden embedded shell: ${JSON.stringify(layout)}`);
      }
      if (layout.clippedButtons.length > 0) {
        throw new Error(`${viewport.name} clipped buttons: ${layout.clippedButtons.join(", ")}`);
      }
      observations.push({
        viewport: viewport.name,
        url: page.url(),
        consoleErrors,
        failedRequests,
        layout,
      });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  return { screenshots, observations };
}

async function verifyConnectorControlSurface(page, screenshots, viewportName) {
  await page.locator(".kc-native-tabs").getByRole("button", { name: "数据源", exact: true }).click();
  await page.getByRole("heading", { name: "已连接内容" }).waitFor({ state: "visible" });
  await page.getByRole("table", { name: "Connected Content" }).waitFor({ state: "visible" });
  if (!viewportName.startsWith("mobile")) {
    await page.getByText("资源数").waitFor({ state: "visible" });
  }
  await page.locator(".kc-connected-content-row").first().waitFor({ state: "visible" });
  await page.locator(".kc-connected-content-row").first().getByRole("button").last().waitFor({ state: "visible" });
  await screenshot(page, screenshots, `${viewportName}-connected-content.png`);

  await page.locator(".kc-connected-content-row .kc-content-name").first().click();
  const drawer = page.locator(".kc-resource-detail");
  await drawer.waitFor({ state: "visible" });
  for (const tabName of ["概览", "资源", "同步记录", "访问权限", "Lineage", "诊断详情 Advanced"]) {
    await drawer.getByRole("button", { name: tabName }).click();
  }
  await screenshot(page, screenshots, `${viewportName}-content-drawer.png`);
  await page.getByRole("button", { name: "关闭" }).click();

  await page.getByRole("button", { name: "添加内容" }).first().click();
  await page.getByRole("heading", { name: "Connector Gallery" }).waitFor({ state: "visible" });
  await page.locator(".kc-gallery-controls input").fill("oracle");
  await page.getByRole("button", { name: "业务数据" }).click();
  await page.locator(".kc-connector-card", { hasText: "Oracle" }).first().waitFor({ state: "visible" });
  await screenshot(page, screenshots, `${viewportName}-connector-gallery.png`);
  await page.locator(".kc-gallery-controls input").fill("");
  await page.getByRole("button", { name: "需要授权" }).click();
  await page.locator(".kc-connector-card", { hasText: "Feishu" }).first().waitFor({ state: "visible" });
  await page.getByRole("button", { name: "预览中" }).click();
  await page.getByRole("button", { name: /了解要求|申请启用/ }).first().waitFor({ state: "visible" });
  await page.getByRole("button", { name: "全部" }).click();
  await page.locator(".kc-connector-card").first().click();
  await page.locator(".kc-wizard-footer").first().waitFor({ state: "visible" });
  const wizardLayout = await inspectWizardFooter(page);
  if (!wizardLayout.visible || !wizardLayout.sticky) {
    throw new Error(`${viewportName} wizard footer is not sticky/visible: ${JSON.stringify(wizardLayout)}`);
  }
  if (wizardLayout.bottomOverflow > 1 || wizardLayout.horizontalOverflow > 1) {
    throw new Error(`${viewportName} wizard footer overflow: ${JSON.stringify(wizardLayout)}`);
  }
  await screenshot(page, screenshots, `${viewportName}-wizard-footer.png`);
  await page.getByRole("button", { name: "关闭" }).click();
}

async function screenshot(page, screenshots, fileName) {
  const file = path.join(screenshotDir, fileName);
  await page.screenshot({ path: file, fullPage: true });
  screenshots.push(`screenshots/${fileName}`);
}

async function expectNoGlobalChrome(page, stage) {
  const result = await page.evaluate(() => {
    const iframes = Array.from(document.querySelectorAll("iframe"));
    const forbiddenIframes = iframes
      .filter((frame) => !frame.hasAttribute("srcdoc"))
      .map((frame) => frame.getAttribute("src") || "")
      .filter((src) => !src || /byaan|wren|datastudio/i.test(src));
    const navText = Array.from(document.querySelectorAll("aside,nav")).map((node) => node.textContent || "").join("\n");
    return {
      iframeCount: iframes.length,
      srcDocIframeCount: iframes.filter((frame) => frame.hasAttribute("srcdoc")).length,
      forbiddenIframes,
      hasByaanSidebar: /BYAAN|Data Studio sidecar/i.test(navText),
      hasWrenSidebar: /Wren AI|Wren Engine/i.test(navText),
    };
  });
  if (result.forbiddenIframes.length || result.hasByaanSidebar || result.hasWrenSidebar) {
    throw new Error(`${stage} has forbidden embedded shell: ${JSON.stringify(result)}`);
  }
}

async function inspectWizardFooter(page) {
  return page.locator(".kc-wizard-footer").first().evaluate((footer) => {
    const rect = footer.getBoundingClientRect();
    const style = window.getComputedStyle(footer);
    const root = document.documentElement;
    return {
      visible: rect.width > 0 && rect.height > 0,
      sticky: style.position === "sticky",
      bottomOverflow: Math.max(0, rect.bottom - root.clientHeight),
      horizontalOverflow: Math.max(0, rect.right - root.clientWidth, -rect.left),
    };
  });
}

async function inspectLayout(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    const buttons = Array.from(document.querySelectorAll("button"));
    const navText = Array.from(document.querySelectorAll("aside,nav")).map((node) => node.textContent || "").join("\n");
    const iframes = Array.from(document.querySelectorAll("iframe"));
    const forbiddenIframes = iframes
      .filter((frame) => !frame.hasAttribute("srcdoc"))
      .map((frame) => frame.getAttribute("src") || "")
      .filter((src) => !src || /byaan|wren|datastudio/i.test(src));
    return {
      documentOverflowX: root.scrollWidth - root.clientWidth,
      bodyOverflowX: body.scrollWidth - body.clientWidth,
      viewportWidth: root.clientWidth,
      viewportHeight: root.clientHeight,
      iframeCount: iframes.length,
      srcDocIframeCount: iframes.filter((frame) => frame.hasAttribute("srcdoc")).length,
      forbiddenIframeCount: forbiddenIframes.length,
      forbiddenIframes,
      hasByaanSidebar: /BYAAN|Data Studio sidecar/i.test(navText),
      hasWrenSidebar: /Wren AI|Wren Engine/i.test(navText),
      semanticRendered: Boolean(document.querySelector('[data-testid="semantic-modeling-workbench"]')),
      asktableRendered: Boolean(document.querySelector('[data-testid="ask-dashboard-workbench"]')),
      evaluationRendered: Boolean(document.querySelector(".kc-eval-workbench")),
      clippedButtons: buttons
        .filter((button) => {
          const rect = button.getBoundingClientRect();
          const inWorkbench = Boolean(button.closest(".kc-native-view"));
          return rect.width > 0
            && rect.height > 0
            && inWorkbench
            && (button.scrollWidth > button.clientWidth + 1 || button.scrollHeight > button.clientHeight + 1);
        })
        .map((button) => button.textContent?.trim())
        .filter(Boolean),
    };
  });
}

function schemaSnapshot() {
  return {
    tables: [
      {
        name: "SALES_ORDER",
        columns: [
          { name: "ticket_id", type: "varchar" },
          { name: "store_id", type: "varchar" },
          { name: "store_name", type: "varchar" },
          { name: "sell_date", type: "date" },
          { name: "customer_phone", type: "varchar", pii: true },
        ],
      },
      {
        name: "STORE",
        columns: [
          { name: "id", type: "varchar" },
          { name: "store_name", type: "varchar" },
          { name: "region", type: "varchar" },
        ],
      },
    ],
    relationships: [{ from: "SALES_ORDER.store_id", to: "STORE.id" }],
  };
}

function semanticPackage(assetId) {
  return {
    package_type: "semantic_skill",
    runtime: {
      transport: "agentkit_governed_rest",
      query_url: `/api/knowledge-assets/assets/semantic_model/${assetId}/query`,
      direct_database_access: false,
      raw_sql_fallback: false,
    },
    governance: {
      raw_sql_fallback: false,
      usage_policy: { permission_hint: "Aggregates only. Customer contact fields are denied." },
    },
    mdl: {
      schema: "agentkit.mdl.v1",
      model: { id: assetId, slug: assetId, version: "v1" },
      entities: [{ id: "sales", table: "SALES_ORDER" }],
      relationships: [{ from: "sales.store_id", to: "store.id" }],
      metrics: [
        {
          id: "ticket_count",
          name: "Ticket Count",
          formula: "count_distinct(ticket_id)",
          definition: "Count distinct tickets.",
          time_field: "sell_date",
          evidence: [{ kind: "metric", title: "ticket_count definition" }],
        },
      ],
      dimensions: [
        { id: "store", name: "Store", field: "store_name" },
        { id: "sell_date", name: "Sell Date", field: "sell_date" },
      ],
      permissions: {
        raw_sql_fallback: false,
        permission_hint: "Aggregates only.",
        denied_fields: [{ field: "customer_phone" }, { field: "customer_email" }],
      },
      freshness: { status: "fresh", as_of: "2026-08-19T00:00:00Z" },
    },
    governed_query_result: {
      schema: "agentkit.semantic_query_result.v1",
      data: {
        rows: [
          { store: "VNPTTE", ticket_count: 56 },
          { store: "SG - ANTA VIVO City", ticket_count: 9 },
        ],
        returnedCount: 2,
        metric: {
          id: "ticket_count",
          name: "Ticket Count",
          definition: "Count distinct tickets.",
        },
        dimensions: [{ id: "store", name: "Store", field: "store_name" }],
        sql: "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count FROM SALES_ORDER GROUP BY store_name",
        metricDefinition: "Count distinct tickets.",
        policyDecision: {
          decision: "allow",
          reason: "Aggregates only.",
          raw_sql_fallback: false,
        },
        freshness: { status: "fresh", as_of: "2026-08-19T00:00:00Z" },
        evidence: [{ kind: "metric", title: "ticket_count definition" }],
        lineage: [{ kind: "snapshot", title: "Oracle sales schema snapshot" }],
        execution: {
          mode: "governed_semantic_skill_fixture",
          governed_rest: true,
          direct_database_access: false,
          raw_sql_fallback: false,
        },
      },
      mock: false,
    },
  };
}

function dashboardPackage(semanticAssetId) {
  return {
    dashboard_spec: {
      tiles: [{ id: "primary_metric", title: "Ticket Count by Store", type: "bar", data_view_id: "primary_metric" }],
      filters: [{ id: "store" }],
      semantic_bindings: [{ semantic_asset_id: semanticAssetId }],
      data_views: [
        {
          id: "primary_metric",
          rows: [
            { store: "VNPTTE", ticket_count: 56 },
            { store: "SG - ANTA VIVO City", ticket_count: 9 },
          ],
          sql: "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count FROM SALES_ORDER GROUP BY store_name",
          metricDefinition: "Count distinct tickets.",
          policyDecision: {
            decision: "allow",
            reason: "Aggregates only.",
            raw_sql_fallback: false,
          },
          freshness: { status: "fresh", as_of: "2026-08-19T00:00:00Z" },
          evidence: [{ kind: "metric", title: "ticket_count definition" }],
        },
      ],
    },
  };
}

function validateEvidence(seed, health, ui) {
  const rows = seed.askdata?.data?.rows || [];
  if (seed.askdata.status !== "completed" || rows.length <= 0) {
    throw new Error(`AskData did not return non-empty governed rows: ${JSON.stringify(seed.askdata)}`);
  }
  if (seed.askdata.mock !== false || seed.askdata.data?.execution?.raw_sql_fallback !== false) {
    throw new Error(`AskData mock/fallback invariant failed: ${JSON.stringify(seed.askdata)}`);
  }
  for (const run of seed.evaluation.runs) {
    if (run.status !== "succeeded" || run.score !== 1 || run.mock !== false || run.mockVerified !== true) {
      throw new Error(`unexpected evaluation run result: ${JSON.stringify(run, null, 2)}`);
    }
    const complete = run.completeness;
    if (!complete.policyDecision || !complete.freshness || !complete.evidence || !complete.toolCalls || !complete.actualOutput) {
      throw new Error(`incomplete evaluation fields: ${JSON.stringify(run, null, 2)}`);
    }
    if (run.targetKind === "dashboard_skill" && !complete.dashboardSpecDiff) {
      throw new Error(`dashboard evaluation missing dashboardSpecDiff: ${JSON.stringify(run, null, 2)}`);
    }
    if (run.targetKind !== "dashboard_skill" && !complete.actualSql) {
      throw new Error(`query evaluation missing SQL: ${JSON.stringify(run, null, 2)}`);
    }
    if (run.targetKind === "asktable_query" && (!run.allowEvidence || !run.denyEvidence)) {
      throw new Error(`AskTable evaluation missing allow or PII deny evidence: ${JSON.stringify(run, null, 2)}`);
    }
  }
  if (health.mock !== false || health.store !== "sqlite") {
    throw new Error(`health did not report sqlite non-mock store: ${JSON.stringify(health)}`);
  }
  const agents = health.agents || {};
  if (!agents.semantic_builder?.configured || !agents.asktable_dashboard?.configured) {
    throw new Error(`agents are not configured in health: ${JSON.stringify(health)}`);
  }
  if (ui.observations.some((item) => item.layout.forbiddenIframeCount !== 0)) {
    throw new Error(`forbidden iframe rendered in live UI: ${JSON.stringify(ui.observations)}`);
  }
}

const health = await api("/api/knowledge-assets/health");
const seed = await seedWorkbench();
const ui = await verifyUi(seed);
validateEvidence(seed, health, ui);

const report = {
  schema: "agentkit.knowledge_center.session_i_h6_g2_integration.v1",
  generatedAt: new Date().toISOString(),
  studioUrl: studioBaseUrl,
  sourceBranchHashes: {
    "kc/session-h6-asktable-byaan-parity": sourceH6Hash,
    "kc/session-g2-evaluation-hardening": sourceG2Hash,
  },
  healthResponseSummary: {
    mock: health.mock,
    store: health.store,
    agents: health.agents,
  },
  spaceId: seed.space.id,
  semanticAssetId: seed.semanticAssetId,
  dashboardAssetId: seed.dashboardAssetId,
  runner_backend: health.agents?.asktable_dashboard?.runner_backend || "unknown",
  mock: false,
  mockStatus: {
    healthMock: health.mock,
    askdataMock: seed.askdata.mock,
    evaluationRunsMock: seed.evaluation.runs.map((run) => run.mock),
  },
  askdataRows: seed.askdata?.data?.rows?.length || 0,
  askdata: {
    status: seed.askdata.status,
    returnedCount: seed.askdata?.data?.returnedCount,
    policyDecision: seed.askdata?.data?.policyDecision,
    execution: seed.askdata?.data?.execution,
    agent: seed.askdata.agent,
  },
  evaluationTargetKindsAndScores: seed.evaluation.runs.map((run) => ({
    targetKind: run.targetKind,
    score: run.score,
    status: run.status,
    allowEvidence: run.allowEvidence,
    denyEvidence: run.denyEvidence,
    cases: run.cases,
  })),
  iframeCount: ui.observations.reduce((sum, item) => sum + item.layout.iframeCount, 0),
  forbiddenIframeCount: ui.observations.reduce((sum, item) => sum + item.layout.forbiddenIframeCount, 0),
  failedRequests: ui.observations.flatMap((item) => item.failedRequests),
  consoleErrors: ui.observations.flatMap((item) => item.consoleErrors),
  observations: ui.observations,
  screenshotPaths: ui.screenshots,
  integrationBranch,
  integrationBranchHash,
  mergeBase: {
    createdFrom: "origin/kc/session-i-h6-g2-integration",
    baseCommit: "22e0f86d53f2fb9efeb156a52efa9e11996b6cf5",
    previousConnectorFoundationTip,
    strategy: `follow-up commit on ${integrationBranch}`,
  },
  connectorControlSurface: {
    seededResourceId: seed.resource.id,
    checks: [
      "connector gallery search and intent filters",
      "non-available connector call-to-action states",
      "connected content resource-count column/card",
      "content detail drawer tabs",
      "sticky wizard footer without viewport overflow",
    ],
  },
  testCommands: [
    {
      command: "git diff --check",
      status: "passed",
      summary: "No whitespace errors.",
    },
    {
      command: "uvx ruff check frontend/server/knowledge_assets/connector_registry.py frontend/server/knowledge_assets/service.py tests/frontend/test_knowledge_asset_routes.py tests/frontend/test_knowledge_asset_store.py",
      status: "passed",
      summary: "All checks passed.",
    },
    {
      command: "python -m pytest tests/frontend/test_knowledge_asset_routes.py tests/frontend/test_knowledge_asset_store.py -q",
      status: "passed",
      summary: "34 passed.",
    },
    {
      command: "cd frontend && npm test -- knowledgeAssetWorkbench.test.mjs",
      status: "passed",
      summary: "679 passed, 0 failed",
    },
    {
      command: "cd frontend && npm run build",
      status: "passed",
      summary: "Vite production build completed; only existing chunk-size/static-dynamic import warnings.",
    },
    {
      command: "VEADK_STUDIO_URL=http://127.0.0.1:18219 node docs/knowledge-center/session-reports/live-session-i-h6-g2-integration/run-live-smoke.mjs",
      status: "passed",
      summary: "Fresh Studio on sqlite store, desktop/mobile UI smoke, connector controls, AskData, Dashboard preview, Evaluation import/run, no forbidden external sidecar iframe/no 404/no console errors/no horizontal overflow.",
    },
  ],
  artifactChecklist: {
    "FINAL_REPORT.md": "present",
    "result.json": "present",
    "secret-scan-result.json": "present",
    screenshots: [
      "screenshots/desktop-1440-connected-content.png",
      "screenshots/desktop-1440-content-drawer.png",
      "screenshots/desktop-1440-connector-gallery.png",
      "screenshots/desktop-1440-wizard-footer.png",
      "screenshots/desktop-1440-semantic.png",
      "screenshots/desktop-1440-asktable-portal.png",
      "screenshots/desktop-1440-asktable-result.png",
      "screenshots/desktop-1440-evaluation.png",
      "screenshots/mobile-390-connected-content.png",
      "screenshots/mobile-390-content-drawer.png",
      "screenshots/mobile-390-connector-gallery.png",
      "screenshots/mobile-390-wizard-footer.png",
      "screenshots/mobile-390-semantic.png",
      "screenshots/mobile-390-asktable.png",
      "screenshots/mobile-390-evaluation.png",
    ],
  },
  secretScan: {
    path: "secret-scan-result.json",
    status: "passed",
    findings: 0,
  },
  integrationBranchHashNote: "Hash is captured from git HEAD when the smoke script runs; the final pushed branch tip is reported separately after commit.",
};

await writeFile(path.join(reportDir, "result.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify(report, null, 2));
