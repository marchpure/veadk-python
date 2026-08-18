import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const reportDir = __dirname;
const screenshotDir = path.join(reportDir, "screenshots");
const studioBaseUrl = (process.env.VEADK_STUDIO_URL || "http://127.0.0.1:18330").replace(/\/$/, "");

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

async function seedEvaluationRun() {
  const space = await api("/api/knowledge-assets/spaces", {
    method: "POST",
    body: JSON.stringify({
      name: "Session G Evaluation",
      description: "Live E2E fixture for Knowledge Asset evaluation.",
    }),
  });

  await api("/api/knowledge-assets/skill-packages", {
    method: "POST",
    body: JSON.stringify({
      space_id: space.id,
      asset_type: "semantic_model",
      asset_id: "oracle-sales",
      capability_kind: "semantic_skill",
      name: "Oracle Sales",
      status: "ready",
      publish_state: "published",
      type: "semantic_skill",
      query_url: "/api/knowledge-assets/assets/semantic_model/oracle-sales/query",
      capability_package: semanticPackage(),
      capabilities: { metrics: ["ticket_count"], dimensions: ["store"] },
      freshness: { status: "fresh", as_of: "2026-08-18T00:00:00Z" },
      usage_policy: { permission_hint: "Aggregates only." },
      sample_evidence: [{ kind: "metric", title: "ticket" }],
    }),
  });

  const suite = await api("/api/knowledge-assets/evaluation/suites", {
    method: "POST",
    body: JSON.stringify({
      spaceId: space.id,
      name: "Oracle Sales Semantic Eval",
      description: "Live deterministic Semantic Skill evaluation.",
      targetKind: "semantic_skill",
      targetAssetId: "oracle-sales",
    }),
  });

  await api(`/api/knowledge-assets/evaluation/suites/${encodeURIComponent(suite.id)}/cases`, {
    method: "POST",
    body: JSON.stringify({
      question: "按门店查看销售票数",
      expectedMetric: "ticket_count",
      expectedDimensions: ["store"],
      expectedSqlContains: ["SALES_ORDER"],
      expectedPolicyDecision: "allow",
      expectedEvidenceKeys: ["ticket"],
      tags: ["smoke", "semantic"],
    }),
  });

  const detail = await api("/api/knowledge-assets/evaluation/runs", {
    method: "POST",
    body: JSON.stringify({ suiteId: suite.id }),
  });

  return {
    space,
    suite: detail.suite,
    caseCount: detail.cases.length,
    runId: detail.run.id,
    score: detail.run.score,
    failedCases: detail.results
      .filter((result) => result.status === "failed")
      .map((result) => result.caseId),
    judgeModelStatus: detail.run.modelStatus,
    runStatus: detail.run.status,
    targetKind: detail.run.targetKind,
    targetAssetId: detail.run.targetAssetId,
    results: detail.results,
    mock: detail.mock,
  };
}

async function verifyUi(result) {
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch();
  const screenshots = [];
  const observations = [];
  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport });
      await page.addInitScript(() => {
        window.localStorage.setItem("veadk_local_user", "sessiong");
        window.sessionStorage.setItem("veadk_local_user_tab", "sessiong");
      });
      const consoleErrors = [];
      const failedRequests = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      page.on("requestfailed", (request) => {
        const url = request.url();
        const reason = request.failure()?.errorText || "";
        if (
          (url.endsWith("/oauth2/userinfo") && reason.includes("ERR_ABORTED"))
          || (url.includes("lf-static.applogcdn.com") && reason.includes("ERR_ABORTED"))
        ) {
          return;
        }
        failedRequests.push(`${request.method()} ${url} ${reason}`);
      });
      page.on("response", (response) => {
        if (response.status() === 404) {
          const url = response.url();
          if (!url.endsWith("/oauth2/userinfo")) {
            failedRequests.push(`404 ${url}`);
          }
        }
      });

      await page.goto(studioBaseUrl, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "知识资产" }).click();
      await page.getByRole("button", { name: /测评/ }).click();
      await page.getByRole("heading", { name: "测评" }).waitFor({ state: "visible" });
      await page.getByText("Oracle Sales Semantic Eval").waitFor({ state: "visible" });
      await page.locator("em.kc-eval-status", { hasText: "judge not_configured" }).waitFor({ state: "visible" });
      await page.locator(".kc-eval-table-scroll table").waitFor({ state: "visible" });
      await page.getByText("succeeded · 1.00").waitFor({ state: "visible" });
      await page.waitForFunction(() => {
        const detail = document.querySelector(".kc-eval-run-detail")?.textContent || "";
        return detail.includes("SELECT store_name AS store")
          && detail.includes("All deterministic checks passed.");
      });

      const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const body = document.body;
        const main = document.querySelector(".kc-eval-workbench");
        const grid = document.querySelector(".kc-eval-grid");
        const rect = main?.getBoundingClientRect();
        return {
          documentOverflowX: root.scrollWidth - root.clientWidth,
          bodyOverflowX: body.scrollWidth - body.clientWidth,
          viewportWidth: root.clientWidth,
          viewportHeight: root.clientHeight,
          hasMain: Boolean(main),
          hasGrid: Boolean(grid),
          mainRect: rect
            ? {
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                left: Math.round(rect.left),
                right: Math.round(rect.right),
              }
            : null,
          visibleButtons: Array.from(document.querySelectorAll(".kc-eval-toolbar button"))
            .map((button) => button.textContent?.trim())
            .filter(Boolean),
        };
      });
      if (!layout.hasMain || !layout.hasGrid) {
        throw new Error(`${viewport.name} did not render evaluation layout`);
      }
      if (layout.documentOverflowX > 1 || layout.bodyOverflowX > 1) {
        throw new Error(`${viewport.name} horizontal overflow: ${JSON.stringify(layout)}`);
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

function semanticPackage() {
  return {
    package_type: "semantic_skill",
    runtime: {
      transport: "agentkit_governed_rest",
      query_url: "/api/knowledge-assets/assets/semantic_model/oracle-sales/query",
      direct_database_access: false,
      raw_sql_fallback: false,
    },
    governance: {
      raw_sql_fallback: false,
      usage_policy: { permission_hint: "Aggregates only." },
    },
    mdl: {
      schema: "agentkit.mdl.v1",
      model: { id: "oracle-sales", slug: "oracle-sales", version: "v1" },
      entities: [{ id: "sales", table: "SALES_ORDER" }],
      relationships: [{ from: "sales.store_id", to: "store.id" }],
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
        { id: "sell_date", name: "Sell Date", field: "sell_date" },
      ],
      permissions: {
        raw_sql_fallback: false,
        permission_hint: "Aggregates only.",
        denied_fields: [{ field: "customer_phone" }],
      },
      freshness: { status: "fresh", as_of: "2026-08-18T00:00:00Z" },
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
        freshness: { status: "fresh", as_of: "2026-08-18T00:00:00Z" },
        evidence: [{ kind: "metric", title: "ticket" }],
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

const result = await seedEvaluationRun();
if (result.runStatus !== "succeeded" || result.score !== 1 || result.judgeModelStatus !== "not_configured") {
  throw new Error(`unexpected run result: ${JSON.stringify(result, null, 2)}`);
}
const ui = await verifyUi(result);
const report = {
  generatedAt: new Date().toISOString(),
  studioUrl: studioBaseUrl,
  ...result,
  screenshots: ui.screenshots,
  observations: ui.observations,
};
await writeFile(path.join(reportDir, "result.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify(report, null, 2));
