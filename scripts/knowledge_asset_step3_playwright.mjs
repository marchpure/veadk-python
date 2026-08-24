#!/usr/bin/env node

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const origin = process.env.STEP3_PLAYWRIGHT_ORIGIN ?? "http://127.0.0.1:4174";
const apiOrigin = process.env.STEP3_PLAYWRIGHT_API ?? "http://127.0.0.1:8794";
const evidenceRoot = resolve(
  process.env.STEP3_PLAYWRIGHT_EVIDENCE_DIR ??
    ".veadk/knowledge-assets/step3-playwright",
);
const configuredSkillId = process.env.STEP3_PLAYWRIGHT_SKILL_ID;
const chrome =
  process.env.STEP3_CHROME ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

mkdirSync(evidenceRoot, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: chrome });
const results = [];

async function journey(id, name, fn) {
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
  const requests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("request", (request) => {
    if (request.url().includes("/api/knowledge-assets/")) {
      requests.push({ method: request.method(), url: request.url() });
    }
  });
  const bootstrap = await page.request.get(
    `${apiOrigin}/api/knowledge-assets/v1/bootstrap`,
  );
  const resources = await bootstrap.json();
  const selected = resources.resources.find((item) =>
    configuredSkillId ? item.id === configuredSkillId : true,
  );
  if (!selected) throw new Error("no configured Skill draft in bootstrap");
  const entry = `${origin}/?studio=knowledge&view=skill&skillId=${encodeURIComponent(selected.id)}&revision=${selected.revision}`;
  let status = "pass";
  let error = null;
  try {
    await page.goto(entry, { waitUntil: "networkidle" });
    await page.getByRole("main", { name: "Skill View" }).waitFor();
    await fn(page);
  } catch (caught) {
    status = "fail";
    error = String(caught);
  }
  const artifact = {
    id,
    name,
    status,
    error,
    consoleErrors,
    pageErrors,
    requests,
    bodyText: (await page.locator("body").innerText()).replace(/\s+/g, " ").trim(),
    horizontalOverflowPx: await page.evaluate(() =>
      Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
    ),
  };
  writeFileSync(resolve(evidenceRoot, `${id}.json`), `${JSON.stringify(artifact, null, 2)}\n`);
  results.push(artifact);
  await page.close();
}

await journey("01-execute", "Execute real Skill Builder", async (page) => {
  await page.getByRole("button", { name: "执行 Skill" }).click();
  await page.getByText("操作已完成。", { exact: true }).waitFor();
  await page.getByText("Data version:").waitFor();
  if (!(await page.getByText("Answer & citations").count())) {
    throw new Error("typed knowledge view did not render");
  }
});

await journey("02-evaluate", "Evaluate and machine Policy Gate", async (page) => {
  await page.getByRole("button", { name: "执行 Skill" }).click();
  await page.getByText("操作已完成。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Evaluate", exact: true }).click();
  await page.getByText("操作已完成。", { exact: true }).waitFor();
});

await journey("03-patch-undo", "Typed assistant patch and durable Undo", async (page) => {
  await page.getByLabel("修改描述").fill("Playwright typed patch");
  await page.getByRole("button", { name: "提议修改并重跑" }).click();
  await page.getByText("修改已应用并重新执行。").waitFor();
  await page.getByRole("button", { name: "Undo" }).click();
  await page.getByText("修改已撤销并重新执行。").waitFor();
});

await journey("04-export-share", "Server-side Export and Share", async (page) => {
  await page.getByRole("button", { name: "执行 Skill" }).click();
  await page.getByText("操作已完成。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Export" }).click();
  await page.getByText("导出已由服务端创建。").waitFor();
  await page.getByRole("button", { name: "Share to human" }).click();
  await page.getByText("分享已由服务端创建。").waitFor();
});

await journey("05-retry", "Failed Builder Retry", async (page) => {
  await page.goto(
    `${origin}/?studio=knowledge&view=skill&skillId=missing-step3-skill&revision=1`,
    { waitUntil: "networkidle" },
  );
  await page.getByRole("main", { name: "Skill View" }).waitFor();
  await page.getByRole("button", { name: "执行 Skill" }).click();
  await page.getByText("操作未通过服务端确认。").waitFor();
  await page.getByRole("button", { name: "Retry Builder" }).click();
  await page.getByText("Builder 重试未通过服务端确认。").waitFor();
});

const summary = {
  schema_version: "knowledge-assets.step3-playwright.v1",
  origin,
  apiOrigin,
  status:
    results.length === 5 &&
    results.every(
      (result) =>
        result.status === "pass" &&
        result.consoleErrors.length === 0 &&
        result.pageErrors.length === 0 &&
        result.horizontalOverflowPx === 0,
    )
      ? "pass"
      : "fail",
  journeys: results,
};
writeFileSync(resolve(evidenceRoot, "report.json"), `${JSON.stringify(summary, null, 2)}\n`);
console.log(JSON.stringify(summary, null, 2));
await browser.close();
if (summary.status !== "pass") process.exitCode = 1;
