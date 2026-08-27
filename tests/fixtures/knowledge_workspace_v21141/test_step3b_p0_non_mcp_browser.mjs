#!/usr/bin/env node

import { mkdirSync, writeFileSync, renameSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const webOrigin = process.env.STEP3B_P0_WEB_ORIGIN ?? "http://127.0.0.1:18401";
const workspace = process.env.STEP3B_P0_WORKSPACE ?? `p0-browser-${Date.now()}`;
const evidenceDirectory =
  process.env.STEP3B_P0_EVIDENCE_DIR ??
  "/tmp/step3b-p0-non-mcp-browser";
const reportPath = `${evidenceDirectory}/report.json`;

mkdirSync(evidenceDirectory, { recursive: true });

const report = {
  validationScope: "production-real-bff",
  productionPass: false,
  workspace,
  webOrigin,
  requests: [],
  errors: [],
};

function writeReport() {
  const temporaryPath = `${reportPath}.tmp-${process.pid}`;
  writeFileSync(temporaryPath, `${JSON.stringify(report, null, 2)}\n`);
  renameSync(temporaryPath, reportPath);
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath:
      process.env.STEP3B_P0_CHROME ??
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  const page = await browser.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") report.errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => report.errors.push(`page: ${error.message}`));
  page.on("requestfailed", (request) => {
    report.errors.push(
      `request: ${request.url()} ${request.failure()?.errorText ?? "failed"}`,
    );
  });
  page.on("request", (request) => {
    if (
      request.url().includes("/api/source-golden/") ||
      request.url().includes("/api/knowledge-assets/")
    ) {
      report.requests.push({
        method: request.method(),
        url: request.url(),
        postData: request.postData() ?? null,
      });
    }
  });

  try {
    const query = `studio=knowledge&workspace=${encodeURIComponent(workspace)}`;
    await page.goto(`${webOrigin}/?${query}&file=data_overview`, {
      waitUntil: "networkidle",
    });
    await page.getByRole("button", { name: "添加数据连接" }).click();
    await page.getByRole("button", { name: /CSV/ }).first().click();
    await page.locator('input[type="file"]').first().setInputFiles({
      name: "browser-orders.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("service,cpu\nsearch,37.4\nindexer,61.8\n"),
    });
    await page.getByRole("button", { name: "下一步" }).click();
    await page.getByRole("button", { name: "完成配置并命名" }).waitFor({
      state: "visible",
      timeout: 15_000,
    });
    await page.getByRole("button", { name: "完成配置并命名" }).click();
    await page.goto(`${webOrigin}/?${query}&file=data_overview`, {
      waitUntil: "networkidle",
    });

    const row = page.locator("tr:visible", { hasText: "CSV 连接" }).first();
    await row.waitFor({ state: "visible", timeout: 15_000 });
    await row.getByRole("button", { name: "作为上下文加入" }).click();
    const agentInput = page.getByLabel("分析助手输入框");
    await agentInput.waitFor({ state: "visible", timeout: 15_000 });
    const startRequest = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().includes("/api/knowledge-assets/") &&
        request.postData()?.includes('"command":"skill-authoring.start"'),
    );
    await agentInput.fill("基于 CSV 生成分析 Skill");
    await agentInput.press("Enter");
    const request = await startRequest;
    const payload = JSON.parse(request.postData());
    const references = payload.payload?.resourceRefs ?? [];
    if (
      !references.some(
        (reference) =>
          reference.kind === "golden_asset" &&
          typeof reference.object_id === "string" &&
          typeof reference.revision === "string",
      )
    ) {
      throw new Error("Agent request did not contain a server-owned Golden context reference.");
    }

    const postData = report.requests.filter((item) => item.method === "POST");
    const commands = postData
      .map((item) => (item.postData ? JSON.parse(item.postData).command : null))
      .filter(Boolean);
    for (const command of [
      "source-golden.connection.create",
      "source-golden.ingest",
      "skill-authoring.start",
    ]) {
      if (!commands.includes(command)) {
        throw new Error(`Missing real command in browser trace: ${command}`);
      }
    }
    if (!report.requests.some((item) => item.url.includes("/api/source-golden/v1/uploads"))) {
      throw new Error("Missing real source-golden upload request.");
    }
    report.productionPass = report.errors.length === 0;
    if (!report.productionPass) throw new Error("Browser regression captured runtime errors.");
  } finally {
    await browser.close();
    writeReport();
  }
}

main().catch((error) => {
  report.errors.push(error instanceof Error ? error.message : String(error));
  writeReport();
  process.exitCode = 1;
});
