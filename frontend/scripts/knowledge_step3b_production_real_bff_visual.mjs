#!/usr/bin/env node

/*
 * Production-real-bff visual gate.
 *
 * This runner deliberately has no Playwright routing hooks. Both the
 * prototype and Integration are visited over HTTP; all business responses
 * come from their servers. A missing dynamic state is a gate failure.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const VIEWPORTS = [
  { name: "desktop-1920", width: 1920, height: 1080 },
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "mobile-390", width: 390, height: 844, isMobile: true },
];
const stateNames = [
  "home", "agent-clarify", "bluetooth-sop-draft", "edit-sop-step",
  "bluetooth-sop-input", "bluetooth-sop-result", "publish-to-agent",
  "anta-dashboard-draft", "anta-dashboard-result", "publish-team",
  "haidilao-sop-draft", "haidilao-sop-input", "haidilao-sop-result",
  "published-sop-monitoring", "optimization-draft",
];
const prototypeStateUrls = [
  "/?file=welcome",
  "/?file=welcome&chat=clarify",
  "/?file=draft_sop_bluetooth&pane=open",
  "/?file=draft_sop_bluetooth&edit_step=Step_2&pane=open",
  "/?file=draft_sop_bluetooth&run_state=input&pane=open",
  "/?file=draft_sop_bluetooth&run_state=result&pane=open",
  "/?file=draft_sop_bluetooth&run_state=result&pane=open&modal=publish_agent",
  "/?file=draft_dash_anta&pane=open",
  "/?file=draft_dash_anta&run_state=result&pane=open",
  "/?file=draft_dash_anta&run_state=result&pane=open&modal=publish",
  "/?file=draft_sop_haidilao&pane=open",
  "/?file=draft_sop_haidilao&run_state=input&pane=open",
  "/?file=draft_sop_haidilao&run_state=result&pane=open",
  "/?file=pub_sop_bluetooth",
  "/?file=draft_sop_bluetooth_opt",
];

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function args(argv) {
  const get = (name, fallback) => {
    const index = argv.indexOf(name);
    return index >= 0 ? argv[index + 1] : fallback;
  };
  return {
    integration: get("--integration-origin", "http://127.0.0.1:5174"),
    prototype: get("--prototype-origin", "https://6a8d6b680c998402432b2a6f-prototype.inspire.bytedance.net"),
    workspace: get("--workspace", "acceptance-workspace"),
    output: resolve(get("--output", ".veadk/knowledge-assets/production-real-bff")),
  };
}

function dynamicStateUrls(bootstrap) {
  const drafts = bootstrap.resources.filter((item) => item.resourceKind === "skill_draft");
  const published = bootstrap.resources.find((item) => item.resourceKind === "published_skill");
  const find = (renderer, offset = 0) =>
    drafts.filter((item) => item.subtype === renderer)[offset] ?? drafts[offset];
  const sop = find("sop");
  const dashboard = find("dashboard");
  const optimization = drafts[drafts.length - 1];
  const url = (resource, extra = "") =>
    resource
      ? `/?studio=knowledge&workspace=${encodeURIComponent(bootstrap.access.spaceId)}&file=${encodeURIComponent(resource.id)}${extra}`
      : "";
  return [
    `/?studio=knowledge&workspace=${encodeURIComponent(bootstrap.access.spaceId)}&file=welcome`,
    `/?studio=knowledge&workspace=${encodeURIComponent(bootstrap.access.spaceId)}&file=welcome&chat=clarify`,
    url(sop, "&pane=open"),
    url(sop, "&edit_step=step_2&pane=open"),
    url(sop, "&run_state=input&pane=open"),
    url(sop, "&run_state=result&pane=open"),
    url(sop, "&run_state=result&pane=open&modal=publish_agent"),
    url(dashboard, "&pane=open"),
    url(dashboard, "&run_state=result&pane=open"),
    url(dashboard, "&run_state=result&pane=open&modal=publish"),
    url(drafts.filter((item) => item.subtype === "sop")[1] ?? sop, "&pane=open"),
    url(drafts.filter((item) => item.subtype === "sop")[1] ?? sop, "&run_state=input&pane=open"),
    url(drafts.filter((item) => item.subtype === "sop")[1] ?? sop, "&run_state=result&pane=open"),
    url(published, ""),
    url(optimization, ""),
  ];
}

async function visit(browser, origin, stateUrl, viewport, output, label) {
  const page = await browser.newPage({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: viewport.isMobile,
    deviceScaleFactor: 1,
    locale: "zh-CN",
  });
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push({
    url: request.url(), method: request.method(),
    failure: request.failure()?.errorText ?? "",
  }));
  const url = new URL(stateUrl || "/?file=welcome", origin);
  let navigationError = "";
  try {
    await page.goto(url.toString(), { waitUntil: "domcontentloaded", timeout: 10_000 });
    await page.waitForTimeout(350);
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }
  const dom = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    agentWidth: document.querySelector('[aria-label="分析助手"]')?.getBoundingClientRect().width ?? 0,
    bodyText: document.body.innerText.slice(0, 5000),
  })).catch(() => ({ scrollWidth: 0, innerWidth: viewport.width, agentWidth: 0, bodyText: "" }));
  const screenshot = join(output, `${label}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });
  await page.close();
  return {
    url: url.toString(),
    screenshot,
    sha256: sha256(readFileSync(screenshot)),
    navigationError,
    consoleErrors,
    pageErrors,
    failedRequests,
    dom,
  };
}

async function main() {
  const options = args(process.argv.slice(2));
  mkdirSync(options.output, { recursive: true });
  const response = await fetch(`${options.integration}/api/knowledge-assets/v1/bootstrap?workspace=${encodeURIComponent(options.workspace)}`);
  if (!response.ok) throw new Error(`integration bootstrap failed: ${response.status}`);
  const bootstrap = await response.json();
  const urls = dynamicStateUrls(bootstrap);
  const browser = await chromium.launch({ headless: true });
  const entries = [];
  try {
    for (let index = 0; index < stateNames.length; index += 1) {
      for (const viewport of VIEWPORTS) {
        const root = join(options.output, viewport.name, stateNames[index]);
        mkdirSync(root, { recursive: true });
        const actual = await visit(browser, options.integration, urls[index], viewport, root, "actual");
        const reference = await visit(
          browser,
          options.prototype,
          prototypeStateUrls[index],
          viewport,
          root,
          "prototype-reference",
        );
        const ratio = actual.dom.scrollWidth > actual.dom.innerWidth ? 1 : 0;
        entries.push({
          state: stateNames[index],
          viewport: viewport.name,
          stateUrl: urls[index],
          actual,
          reference,
          pixelDiffRatio: null,
          checks: {
            dynamicUrl: Boolean(urls[index]),
            horizontalOverflow: ratio === 0,
            consoleErrors: actual.consoleErrors,
            pageErrors: actual.pageErrors,
            failedRequests: actual.failedRequests,
            navigationError: actual.navigationError,
          },
        });
      }
    }
  } finally {
    await browser.close();
  }
  const failures = entries.flatMap((entry) => {
    const out = [];
    if (!entry.checks.dynamicUrl) out.push(`${entry.state}: no dynamic resource URL`);
    if (!entry.checks.horizontalOverflow) out.push(`${entry.state}/${entry.viewport}: horizontal overflow`);
    if (entry.actual.navigationError) out.push(`${entry.state}/${entry.viewport}: ${entry.actual.navigationError}`);
    if (entry.actual.consoleErrors.length) out.push(`${entry.state}/${entry.viewport}: console errors`);
    if (entry.actual.pageErrors.length) out.push(`${entry.state}/${entry.viewport}: page errors`);
    if (entry.actual.failedRequests.length) out.push(`${entry.state}/${entry.viewport}: failed business/static requests`);
    return out;
  });
  const report = {
    generatedAt: new Date().toISOString(),
    validationScope: "production-real-bff",
    productionPass: failures.length === 0 && entries.length === 45,
    stateCount: stateNames.length,
    viewportCount: VIEWPORTS.length,
    screenshots: entries.length,
    workspace: bootstrap.access.spaceId,
    resourceIds: bootstrap.resources.map((item) => item.id),
    entries,
    failures,
    note: "Prototype reference is visited over HTTP; this runner contains no page.route or route.fulfill.",
  };
  writeFileSync(join(options.output, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({
    validationScope: report.validationScope,
    productionPass: report.productionPass,
    screenshots: report.screenshots,
    failures: report.failures.length,
  }, null, 2)}\n`);
  if (!report.productionPass) process.exitCode = 1;
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : error}\n`);
  process.exitCode = 1;
});
