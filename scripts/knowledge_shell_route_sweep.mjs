#!/usr/bin/env node

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const origin = process.env.KNOWLEDGE_SHELL_SWEEP_ORIGIN ?? "http://127.0.0.1:18795";
const evidenceRoot = resolve(
  process.env.KNOWLEDGE_SHELL_SWEEP_EVIDENCE_DIR ??
    ".veadk/knowledge-assets/shell-route-sweep",
);
const matrixPath = resolve(
  process.env.KNOWLEDGE_SHELL_SWEEP_MATRIX ??
    "tests/fixtures/knowledge_step3_w4/capability-matrix.json",
);
const routes = JSON.parse(readFileSync(matrixPath, "utf8")).states;
const chrome =
  process.env.KNOWLEDGE_SHELL_SWEEP_CHROME ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

mkdirSync(evidenceRoot, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: chrome,
});
const results = [];

for (const [index, route] of routes.entries()) {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  const id = String(index + 1).padStart(2, "0");
  const safeName = route.stateUrl
    .replace(/^\//, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 100) || "home";
  let status = "pass";
  let error = null;
  try {
    const target = new URL(route.stateUrl, origin);
    target.searchParams.set("studio", "knowledge");
    await page.goto(target.toString(), {
      waitUntil: "networkidle",
      timeout: 30_000,
    });
    await page.locator("body").waitFor({ state: "visible" });
  } catch (caught) {
    status = "fail";
    error = String(caught);
  }
  const artifact = {
    index: index + 1,
    stateUrl: route.stateUrl,
    expectedStatus: route.status,
    status,
    error,
    finalUrl: page.url(),
    bodyText: (await page.locator("body").innerText()).replace(/\s+/g, " ").trim(),
    consoleErrors,
    pageErrors,
    horizontalOverflowPx: await page.evaluate(() =>
      Math.max(
        0,
        document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ),
  };
  const expectedFile = new URL(route.stateUrl, origin).searchParams.get("file");
  const finalFile = new URL(artifact.finalUrl).searchParams.get("file");
  artifact.expectedFile = expectedFile;
  artifact.finalFile = finalFile;
  artifact.routePreserved =
    expectedFile === null
      ? route.stateUrl.includes("modal=v212_entry")
        ? finalFile === "welcome"
        : true
      : finalFile === expectedFile;
  artifact.routeExpectation =
    route.stateUrl.includes("error_state=auth_failed")
      ? artifact.bodyText.includes("修复凭证")
      : route.stateUrl.includes("error_state=render_error")
        ? artifact.bodyText.includes("Artifact") &&
          artifact.bodyText.includes("暂时无法渲染")
        : true;
  await page.screenshot({
    path: resolve(evidenceRoot, `${id}-${safeName}.png`),
    fullPage: true,
  });
  writeFileSync(
    resolve(evidenceRoot, `${id}-${safeName}.json`),
    `${JSON.stringify(artifact, null, 2)}\n`,
  );
  results.push(artifact);
  await page.close();
}

const summary = {
  schema_version: "knowledge-shell.route-sweep.v1",
  origin,
  routeCount: routes.length,
  status:
    routes.length === 43 &&
    results.every(
      (result) =>
        result.status === "pass" &&
        result.bodyText.length > 0 &&
        result.bodyText.includes("Knowledge Asset") &&
        result.routePreserved &&
        result.routeExpectation &&
        result.consoleErrors.length === 0 &&
        result.pageErrors.length === 0 &&
        result.horizontalOverflowPx === 0 &&
        (!result.stateUrl.includes("modal=v212_entry") ||
          result.bodyText.includes("验收入口")),
    )
      ? "pass"
      : "fail",
  routes: results,
};
writeFileSync(
  resolve(evidenceRoot, "report.json"),
  `${JSON.stringify(summary, null, 2)}\n`,
);
console.log(JSON.stringify(summary, null, 2));
await browser.close();
if (summary.status !== "pass") process.exitCode = 1;
