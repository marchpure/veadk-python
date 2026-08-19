import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const reportDir = __dirname;
const screenshotDir = path.join(reportDir, "screenshots");
const studioBaseUrl = (process.env.VEADK_STUDIO_URL || "http://127.0.0.1:18331").replace(/\/$/, "");

const viewports = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "mobile-390", width: 390, height: 844 },
];

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

async function seedEvaluationRuns() {
  const unique = `g2-${Date.now()}`;
  const semanticAssetId = `${unique}-oracle-sales`;
  const dashboardAssetId = `${unique}-sales-dashboard`;
  const space = await api("/api/knowledge-assets/spaces", {
    method: "POST",
    body: JSON.stringify({
      name: `Session G2 Evaluation ${unique}`,
      description: "Live E2E fixture for Knowledge Asset evaluation hardening.",
    }),
  });

  await api("/api/knowledge-assets/skill-packages", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      asset_type: "semantic_model",
      asset_id: semanticAssetId,
      capability_kind: "semantic_skill",
      name: "Oracle Sales G2",
      status: "ready",
      publish_state: "published",
      type: "semantic_skill",
      query_url: `/api/knowledge-assets/assets/semantic_model/${semanticAssetId}/query`,
      capability_package: semanticPackage(semanticAssetId),
      capabilities: { metrics: ["ticket_count"], dimensions: ["store", "sell_date"] },
      freshness: { status: "fresh", as_of: "2026-08-19T00:00:00Z" },
      usage_policy: { permission_hint: "Aggregates only. Customer contact fields are denied." },
      sample_evidence: [{ kind: "metric", title: "ticket_count definition" }],
    }),
  });

  await api("/api/knowledge-assets/skill-packages", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      asset_type: "dashboard",
      asset_id: dashboardAssetId,
      capability_kind: "dashboard_skill",
      name: "Sales Dashboard G2",
      status: "ready",
      publish_state: "published",
      type: "dashboard_skill",
      query_url: `/api/knowledge-assets/assets/dashboard/${dashboardAssetId}/query`,
      capability_package: dashboardPackage(semanticAssetId),
      freshness: { status: "fresh", as_of: "2026-08-19T00:00:00Z" },
      usage_policy: { permission_hint: "Aggregates only." },
      sample_evidence: [{ kind: "metric", title: "ticket_count definition" }],
    }),
  });

  const specs = [
    {
      targetKind: "semantic_skill",
      targetAssetId: semanticAssetId,
      name: `G2 Semantic Skill Eval ${unique}`,
      cases: [
        {
          targetKind: "semantic_skill",
          question: "按门店查看销售票数",
          expectedMetric: "ticket_count",
          expectedDimensions: ["store"],
          expectedSqlContains: ["SALES_ORDER"],
          expectedPolicyDecision: "allow",
          expectedEvidenceKeys: ["ticket_count"],
          tags: ["g2", "semantic"],
        },
      ],
    },
    {
      targetKind: "asktable_query",
      targetAssetId: semanticAssetId,
      name: `G2 AskTable Query Eval ${unique}`,
      cases: [
        {
          targetKind: "asktable_query",
          question: "按门店查看销售票数",
          expectedMetric: "ticket_count",
          expectedDimensions: ["store"],
          expectedSqlContains: ["SALES_ORDER"],
          expectedPolicyDecision: "allow",
          expectedEvidenceKeys: ["ticket_count"],
          tags: ["g2", "asktable"],
        },
        {
          targetKind: "asktable_query",
          question: "show customer phone/contact by store",
          expectedMetric: "ticket_count",
          expectedDimensions: ["store"],
          expectedSqlContains: ["policy denied", "no raw SQL executed"],
          expectedPolicyDecision: "deny",
          expectedEvidenceKeys: ["PII policy guard"],
          tags: ["g2", "asktable", "policy-deny"],
        },
      ],
    },
    {
      targetKind: "dashboard_skill",
      targetAssetId: dashboardAssetId,
      name: `G2 Dashboard Skill Eval ${unique}`,
      cases: [
        {
          targetKind: "dashboard_skill",
          intent: "验证门店销售 dashboard 的主要 tile 和 data_view 证据",
          expectedDashboardTiles: ["primary_metric"],
          expectedPolicyDecision: "allow",
          expectedEvidenceKeys: ["ticket_count"],
          tags: ["g2", "dashboard"],
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
        description: "G2 live deterministic evaluation suite imported from JSON cases.",
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

  return {
    space,
    fixtureAssets: {
      semanticAssetId,
      dashboardAssetId,
      fixture: "local SQLite Knowledge Asset fixtures; query services execute real repository-backed package query paths",
    },
    runs,
  };
}

function toRunSummary(detail, imported) {
  const result = detail.results[0] || {};
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
  return {
    runId: detail.run.id,
    suiteId: detail.suite.id,
    suiteName: detail.suite.name,
    targetKind: detail.run.targetKind,
    targetAssetId: detail.run.targetAssetId,
    status: detail.run.status,
    score: detail.run.score,
    reason: result.reason || "",
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
      actualSql: Boolean(result.actualSql),
      dashboardSpecDiff: Boolean(result.dashboardSpecDiff && Object.keys(result.dashboardSpecDiff).length),
      policyDecision: Boolean(result.actualPolicyDecision && Object.keys(result.actualPolicyDecision).length),
      freshness: Boolean(result.actualFreshness && Object.keys(result.actualFreshness).length),
      evidence: Array.isArray(result.evidence) && result.evidence.length > 0,
      toolCalls: Array.isArray(result.toolCalls) && result.toolCalls.length > 0,
      actualOutput: result.actualOutput !== undefined && result.actualOutput !== null,
    },
    result,
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
        window.localStorage.setItem("veadk_local_user", "sessiong2");
        window.sessionStorage.setItem("veadk_local_user_tab", "sessiong2");
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
      await page.getByRole("button", { name: /测评/ }).click();
      await page.getByRole("heading", { name: "测评" }).waitFor({ state: "visible" });
      await page.getByText("G2 Semantic Skill Eval").waitFor({ state: "visible" });
      await page.getByText("G2 AskTable Query Eval").waitFor({ state: "visible" });
      await page.getByText("G2 Dashboard Skill Eval").waitFor({ state: "visible" });
      await page.getByText("Import schema:").waitFor({ state: "visible" });
      await page.locator(".kc-eval-table-scroll table").waitFor({ state: "visible" });
      await page.locator("em.kc-eval-status", { hasText: "judge not_configured" }).waitFor({ state: "visible" });
      await page.getByText("succeeded · 1.00").waitFor({ state: "visible" });

      await page.getByRole("button", { name: /G2 AskTable Query Eval/ }).click();
      await page.getByText("succeeded · 1.00").waitFor({ state: "visible" });
      await page.locator(".kc-eval-case-table tbody tr", { hasText: "show customer phone/contact by store" }).click();
      await page.waitForFunction(() => {
        const detail = document.querySelector(".kc-eval-run-detail")?.textContent || "";
        return detail.includes('"decision": "deny"')
          && detail.includes('"status": "blocked"')
          && detail.includes("PII policy guard")
          && detail.includes("no raw SQL executed");
      });

      await page.getByRole("button", { name: /G2 Dashboard Skill Eval/ }).click();
      await page.getByText("succeeded · 1.00").waitFor({ state: "visible" });

      await page.waitForFunction(() => {
        const detail = document.querySelector(".kc-eval-run-detail")?.textContent || "";
        return detail.includes("All deterministic checks passed.")
          && detail.includes("policyDecision")
          && detail.includes("freshness")
          && detail.includes("evidence")
          && detail.includes("Dashboard Spec Diff");
      });

      const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const body = document.body;
        const main = document.querySelector(".kc-eval-workbench");
        const grid = document.querySelector(".kc-eval-grid");
        const rect = main?.getBoundingClientRect();
        const buttons = Array.from(document.querySelectorAll(".kc-eval-toolbar button"));
        const hasByaanIframe = Boolean(document.querySelector("iframe[src*='byaan'], iframe[src*='datastudio']"));
        const hasByaanSidebar = Boolean(Array.from(document.querySelectorAll("aside,nav")).some((node) =>
          /BYAAN|Data Studio sidecar/i.test(node.textContent || ""),
        ));
        return {
          documentOverflowX: root.scrollWidth - root.clientWidth,
          bodyOverflowX: body.scrollWidth - body.clientWidth,
          viewportWidth: root.clientWidth,
          viewportHeight: root.clientHeight,
          hasMain: Boolean(main),
          hasGrid: Boolean(grid),
          hasByaanIframe,
          hasByaanSidebar,
          mainRect: rect
            ? {
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                left: Math.round(rect.left),
                right: Math.round(rect.right),
              }
            : null,
          visibleButtons: buttons.map((button) => button.textContent?.trim()).filter(Boolean),
          clippedButtons: buttons
            .filter((button) => button.scrollWidth > button.clientWidth + 1 || button.scrollHeight > button.clientHeight + 1)
            .map((button) => button.textContent?.trim()),
        };
      });
      if (!layout.hasMain || !layout.hasGrid) {
        throw new Error(`${viewport.name} did not render evaluation layout`);
      }
      if (layout.hasByaanIframe || layout.hasByaanSidebar) {
        throw new Error(`${viewport.name} rendered BYAAN shell: ${JSON.stringify(layout)}`);
      }
      if (layout.documentOverflowX > 1 || layout.bodyOverflowX > 1) {
        throw new Error(`${viewport.name} horizontal overflow: ${JSON.stringify(layout)}`);
      }
      if (layout.clippedButtons.length > 0) {
        throw new Error(`${viewport.name} clipped toolbar buttons: ${layout.clippedButtons.join(", ")}`);
      }
      if (consoleErrors.length > 0) {
        throw new Error(`${viewport.name} console errors: ${consoleErrors.join("\n")}`);
      }
      if (failedRequests.length > 0) {
        throw new Error(`${viewport.name} failed requests: ${failedRequests.join("\n")}`);
      }

      const screenshot = path.join(screenshotDir, `${viewport.name}-evaluation.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      screenshots.push(path.relative(reportDir, screenshot));
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
      tiles: [{ id: "primary_metric", title: "Ticket Count by Store" }],
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

const seed = await seedEvaluationRuns();
for (const run of seed.runs) {
  if (run.status !== "succeeded" || run.score !== 1 || run.modelStatus !== "not_configured" || run.mock !== false || run.mockVerified !== true) {
    throw new Error(`unexpected run result: ${JSON.stringify(run, null, 2)}`);
  }
  const complete = run.completeness;
  if (!complete.policyDecision || !complete.freshness || !complete.evidence || !complete.toolCalls || !complete.actualOutput) {
    throw new Error(`incomplete result fields: ${JSON.stringify(run, null, 2)}`);
  }
  if (run.targetKind === "dashboard_skill" && !complete.dashboardSpecDiff) {
    throw new Error(`dashboard result missing dashboardSpecDiff: ${JSON.stringify(run, null, 2)}`);
  }
  if (run.targetKind !== "dashboard_skill" && !complete.actualSql) {
    throw new Error(`query result missing SQL: ${JSON.stringify(run, null, 2)}`);
  }
  if (run.targetKind === "asktable_query" && (!run.allowEvidence || !run.denyEvidence)) {
    throw new Error(`AskTable run missing allow or PII-deny evidence: ${JSON.stringify(run, null, 2)}`);
  }
}

const ui = await verifyUi(seed);
const report = {
  generatedAt: new Date().toISOString(),
  studioUrl: studioBaseUrl,
  environment: {
    VEADK_STUDIO_URL: studioBaseUrl,
  },
  ...seed,
  mock: false,
  consoleErrors: ui.observations.flatMap((item) => item.consoleErrors),
  failedRequests: ui.observations.flatMap((item) => item.failedRequests),
  allowlist: [],
  screenshots: ui.screenshots,
  observations: ui.observations,
};
await writeFile(path.join(reportDir, "result.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify(report, null, 2));
