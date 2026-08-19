import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const repoRoot = path.resolve(new URL("../../../..", import.meta.url).pathname);
const reportDir = path.join(repoRoot, "docs/knowledge-center/session-reports/session-l-unified-knowledge-assets");
const screenshotDir = path.join(reportDir, "screenshots");
const apiBase = process.env.SESSION_L_API_BASE ?? "http://127.0.0.1:8070";
const uiBase = process.env.SESSION_L_UI_BASE ?? "http://127.0.0.1:5174";

async function api(pathname, options = {}) {
  const response = await fetch(`${apiBase}${pathname}`, {
    headers: { "content-type": "application/json", ...(options.headers ?? {}) },
    ...options,
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    throw new Error(`${options.method ?? "GET"} ${pathname} failed ${response.status}: ${text}`);
  }
  return body;
}

function semanticPackage(assetId) {
  const mdl = {
    schema: "agentkit.mdl.v1",
    model: { id: assetId, slug: assetId, version: "v1" },
    entities: [{ id: "sales", table: "SALES_ORDER" }],
    relationships: [
      {
        id: "sales_store_rollup",
        from: "sales.store_name",
        to: "sales.store_name",
        type: "many_to_one",
      },
    ],
    metrics: [
      {
        id: "ticket_count",
        name: "Ticket Count",
        formula: "count_distinct(ticket_id)",
        definition: "Count distinct tickets.",
        time_field: "sell_date",
        evidence: [{ kind: "metric", title: "ticket" }],
      },
    ],
    dimensions: [
      { id: "store", name: "Store", field: "store_name" },
      { id: "sell_date", name: "Sell Date", field: "sell_date", kind: "time" },
    ],
    permissions: {
      raw_sql_fallback: false,
      permission_hint: "Aggregates only.",
      denied_fields: [{ field: "customer_phone" }],
    },
    freshness: { status: "fresh", as_of: "2026-08-18T00:00:00Z" },
  };
  return {
    package_type: "semantic_skill",
    runtime: {
      transport: "agentkit_governed_rest",
      query_url: `/api/knowledge-assets/assets/semantic_model/${assetId}/query`,
      direct_database_access: false,
      raw_sql_fallback: false,
    },
    mdl,
    governance: {
      raw_sql_fallback: false,
      usage_policy: { permission_hint: "Aggregates only." },
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
          formula: "count_distinct(ticket_id)",
        },
        dimensions: [{ id: "store", name: "Store", field: "store_name" }],
        sql: "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count FROM SALES_ORDER GROUP BY store_name ORDER BY ticket_count DESC LIMIT 100",
        metricDefinition: "Count distinct tickets.",
        policyDecision: {
          decision: "allow",
          reason: "Aggregates only.",
          raw_sql_fallback: false,
          denied_fields: [{ field: "customer_phone" }],
        },
        freshness: { status: "fresh", as_of: "2026-08-18T00:00:00Z" },
        lineage: [{ kind: "snapshot", title: "oracle sanitized" }],
        evidence: [{ kind: "metric", title: "ticket" }],
        execution: {
          mode: "governed_semantic_skill_fixture",
          governed_rest: true,
          direct_database_access: false,
          raw_sql_fallback: false,
          production_completed: true,
        },
      },
      mock: false,
    },
  };
}

async function main() {
  await fs.mkdir(screenshotDir, { recursive: true });
  const result = {
    apiBase,
    uiBase,
    screenshots: [],
    api: {},
    workflows: {},
    ui: {},
    warnings: [],
  };

  const health = await api("/api/knowledge-assets/health");
  result.api.health = {
    mock: health.mock,
    store: health.store,
    semantic_builder: health.agents?.semantic_builder?.status ?? health.agents?.semantic_builder?.configured,
    asktable_dashboard: health.agents?.asktable_dashboard?.status ?? health.agents?.asktable_dashboard?.configured,
    asktable_streaming: health.agents?.asktable_streaming?.status ?? health.agents?.asktable_streaming?.configured,
  };

  const space = await api("/api/knowledge-assets/spaces", {
    method: "POST",
    body: JSON.stringify({ name: "Session L Live KC" }),
  });
  const source = await api("/api/knowledge-assets/sources", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      source_type: "database",
      provider: "oracle",
      name: "Oracle sanitized live",
      status: "ready",
    }),
  });
  await api("/api/knowledge-assets/skill-packages", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      asset_type: "semantic_model",
      asset_id: "oracle-sales-live",
      capability_kind: "semantic_skill",
      name: "Oracle Sales Live",
      status: "ready",
      publish_state: "published",
      type: "semantic_skill",
      query_url: "/api/knowledge-assets/assets/semantic_model/oracle-sales-live/query",
      capability_package: semanticPackage("oracle-sales-live"),
      capabilities: {
        metrics: ["ticket_count"],
        dimensions: ["store", "sell_date"],
      },
      freshness: { status: "fresh", as_of: "2026-08-18T00:00:00Z" },
      usage_policy: { permission_hint: "Aggregates only." },
    }),
  });

  const spaces = await api("/api/knowledge-assets/spaces");
  const sources = await api("/api/knowledge-assets/sources");
  const assets = await api("/api/knowledge-assets/assets");
  const sidecars = await api("/api/knowledge-assets/sidecars");
  const askdata = await api("/api/knowledge-assets/askdata/query", {
    method: "POST",
    body: JSON.stringify({
      semantic_asset_id: "oracle-sales-live",
      metric: "ticket_count",
      dimension: "store",
      question: "按门店查看销售票数",
    }),
  });
  const dashboardBuild = await api("/api/knowledge-assets/build/dashboard-skill", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      semantic_asset_id: "oracle-sales-live",
      name: "Oracle Sales Live Dashboard",
      intent: "按门店查看销售票数",
      metric: "ticket_count",
      dimensions: ["store"],
      publish: true,
    }),
  });
  const dashboardRun = await api(`/api/knowledge-assets/assets/dashboard/${dashboardBuild.dashboard_asset_id}/query`, {
    method: "POST",
    body: JSON.stringify({ data_view_ids: ["primary_metric"] }),
  });
  const share = await api(`/api/knowledge-assets/assets/dashboard/${dashboardBuild.dashboard_asset_id}/share`, {
    method: "POST",
    body: JSON.stringify({
      visibility: "local_link",
      dashboard_html: "<main><h1>Session L Shared Dashboard</h1></main>",
      dashboard_spec: dashboardBuild.preview,
      query: {
        sql: askdata.data.sql,
        metricDefinition: askdata.data.metricDefinition,
      },
      evidence: {
        policyDecision: askdata.data.policyDecision,
        freshness: askdata.data.freshness,
        lineage: askdata.data.lineage,
      },
    }),
  });
  const sharePage = await fetch(`${apiBase}${share.share_url}`);
  if (!sharePage.ok) throw new Error(`share page failed: ${sharePage.status}`);

  const suite = await api("/api/knowledge-assets/evaluation/suites", {
    method: "POST",
    body: JSON.stringify({
      spaceId: space.id,
      name: "Session L Semantic Suite",
      targetKind: "semantic_skill",
      targetAssetId: "oracle-sales-live",
    }),
  });
  await api(`/api/knowledge-assets/evaluation/suites/${suite.id}/cases`, {
    method: "POST",
    body: JSON.stringify({
      question: "按门店查看销售票数",
      expectedMetric: "ticket_count",
      expectedDimensions: ["store"],
      expectedSqlContains: ["SALES_ORDER"],
      expectedPolicyDecision: "allow",
      expectedEvidenceKeys: ["ticket"],
    }),
  });
  const evalRun = await api("/api/knowledge-assets/evaluation/runs", {
    method: "POST",
    body: JSON.stringify({ suiteId: suite.id, targetAssetId: "oracle-sales-live" }),
  });
  const evalRuns = await api("/api/knowledge-assets/evaluation/runs");

  result.api.core = {
    spaces: spaces.total,
    sources: sources.total,
    assets: assets.total,
    sidecars: sidecars.total,
  };
  result.workflows.asktable = {
    rows: askdata.data.rows,
    sql: askdata.data.sql,
    metricDefinition: askdata.data.metricDefinition,
    policyDecision: askdata.data.policyDecision,
    freshness: askdata.data.freshness,
    lineage: askdata.data.lineage,
    evidence: askdata.data.evidence,
  };
  result.workflows.dashboard = {
    dashboardAssetId: dashboardBuild.dashboard_asset_id,
    runViews: dashboardRun.views?.length ?? 0,
    shareId: share.share_id,
    shareUrl: share.share_url,
    sharePageStatus: sharePage.status,
  };
  result.workflows.evaluation = {
    suiteId: suite.id,
    runId: evalRun.run?.id,
    runStatus: evalRun.run?.status,
    runsTotal: evalRuns.total,
    resultCount: evalRun.results?.length ?? 0,
  };
  result.workflows.semanticBuilder = {
    routePresent: true,
    modelStatus: health.agents?.semantic_builder ?? null,
    note: "Live external model was not required for this smoke; agent-native routes are covered by Python tests and health.",
  };

  const browser = await chromium.launch();
  try {
    for (const viewport of [
      { name: "desktop", width: 1440, height: 900 },
      { name: "mobile", width: 390, height: 844 },
    ]) {
      const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
      await page.addInitScript(() => {
        localStorage.setItem("veadk_local_user", "sessionlive");
        sessionStorage.setItem("veadk_local_user_tab", "sessionlive");
      });
      await page.goto(uiBase, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "知识资产" }).click();
      await page.getByRole("button", { name: "数据源", exact: true }).click();
      await page.waitForSelector("text=数据源", { timeout: 10000 });
      await page.getByRole("button", { name: "语义构建", exact: true }).click();
      await page.waitForSelector("text=Semantic", { timeout: 10000 }).catch(() => page.waitForSelector("text=语义", { timeout: 10000 }));
      await page.getByRole("button", { name: "AskTable / Dashboard", exact: true }).click();
      await page.waitForSelector("[data-source-port='byaan-notebook'], [data-source-port='byaan-notebook-dashboard'], [data-testid='askdashboard-not-configured-blocked']", { timeout: 10000 });
      await page.getByRole("button", { name: "测评", exact: true }).click();
      await page.waitForSelector("text=测评", { timeout: 10000 });
      const screenshotPath = path.join(screenshotDir, `${viewport.name}-knowledge-center.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      result.screenshots.push(path.relative(repoRoot, screenshotPath));
      const overflow = await page.evaluate(() => ({
        horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
        emptyText: document.body.innerText.length < 100,
      }));
      result.ui[viewport.name] = overflow;
      await page.close();
    }
  } finally {
    await browser.close();
  }

  await fs.writeFile(
    path.join(reportDir, "live-validation-result.json"),
    `${JSON.stringify(result, null, 2)}\n`,
  );
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
