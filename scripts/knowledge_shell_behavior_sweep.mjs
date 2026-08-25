#!/usr/bin/env node

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const origin = process.env.KNOWLEDGE_SHELL_BEHAVIOR_ORIGIN ?? "http://127.0.0.1:18795";
const evidenceRoot = resolve(
  process.env.KNOWLEDGE_SHELL_BEHAVIOR_EVIDENCE_DIR ??
    ".veadk/knowledge-assets/shell-behavior-sweep",
);
const chrome =
  process.env.KNOWLEDGE_SHELL_BEHAVIOR_CHROME ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

mkdirSync(evidenceRoot, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: chrome });
const results = [];

async function scenario(id, name, stateUrl, viewport, verify, readModelMode = null) {
  const page = await browser.newPage({
    viewport,
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const consoleErrors = [];
  const pageErrors = [];
  const events = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.exposeFunction("__captureKnowledgeTelemetry", (event) => {
    events.push(event);
  });
  await page.addInitScript(() => {
    window.addEventListener("knowledge_workspace_telemetry", (event) => {
      window.__captureKnowledgeTelemetry(event.detail);
    });
  });
  if (readModelMode) {
    await page.addInitScript((mode) => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const response = await originalFetch(input, init);
        const requestUrl = typeof input === "string" ? input : input?.url;
        if (!requestUrl?.includes("/api/knowledge-assets/v1/bootstrap")) {
          return response;
        }
        const body = await response.clone().json();
        const baseResource = {
          id: "shell-telemetry-draft",
          displayName: "Shell telemetry draft",
          resourceKind: "skill_draft",
          subtype: "skill",
          space: "personal",
          lifecycle: "draft",
          version: "0.1.0",
          revision: 1,
          permission: true,
        };
        const readModels = {
          prepare: {
            stage: "prepare",
            status: "awaiting_input",
          },
          debug: {
            stage: "debug",
            status: "ready_for_evaluation",
            executionState: "schema_drift",
            missingField: "region",
            skillViewRevision: {
              id: "shell-view-revision",
              template: "knowledge",
              answer: "server-derived artifact",
            },
          },
          publish: {
            stage: "publish",
            status: "ready_for_publish",
            evaluationRun: { status: "succeeded", score: 0.98 },
            policyGateResult: { decision: "publishable" },
          },
          published: {
            stage: "publish",
            status: "published",
            published: true,
            publishedVersion: {
              id: "shell-published-version",
              status: "published",
              semver: "0.1.0",
            },
            evaluationRun: { status: "succeeded", score: 0.98 },
            policyGateResult: { decision: "publishable" },
          },
        };
        const readModel = readModels[mode];
        if (!readModel) return response;
        body.resources = [
          { ...baseResource, readModel },
          ...(Array.isArray(body.resources) ? body.resources : []),
        ];
        return new Response(JSON.stringify(body), {
          status: response.status,
          statusText: response.statusText,
          headers: { "content-type": "application/json" },
        });
      };
    }, readModelMode);
  }

  let status = "pass";
  let error = null;
  try {
    const target = new URL(stateUrl, origin);
    target.searchParams.set("studio", "knowledge");
    await page.goto(target.toString(), {
      waitUntil: "networkidle",
      timeout: 30_000,
    });
    await verify(page);
  } catch (caught) {
    status = "fail";
    error = String(caught);
  }
  const artifact = {
    id,
    name,
    stateUrl,
    status,
    error,
    finalUrl: page.url(),
    events,
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
  await page.screenshot({
    path: resolve(evidenceRoot, `${id}.png`),
    fullPage: true,
  });
  writeFileSync(
    resolve(evidenceRoot, `${id}.json`),
    `${JSON.stringify(artifact, null, 2)}\n`,
  );
  results.push(artifact);
  await page.close();
}

await scenario(
  "01-home-more",
  "Home Composer and More acceptance entry",
  "/?file=welcome",
  { width: 1440, height: 900 },
  async (page) => {
    await page.getByPlaceholder("你想把哪些数据或知识加工成什么能力？").waitFor();
    await page.locator('summary[aria-label="更多"]:visible').click();
    await page.getByRole("button", { name: "验收与评测" }).first().waitFor();
  },
);

await scenario(
  "02-prepare-primary",
  "Journey prepare state and primary CTA",
  "/?file=journey_knowledge&step=1&pane=open",
  { width: 1440, height: 900 },
  async (page) => {
    await page.getByRole("button", { name: "准备素材" }).click();
    if (!new URL(page.url()).searchParams.has("file")) {
      throw new Error("prepare CTA did not preserve a file route");
    }
  },
  "prepare",
);

await scenario(
  "03-debug-details",
  "Journey and eight-step Build Details drawer",
  "/?file=journey_knowledge&step=1&pane=open",
  { width: 1440, height: 900 },
  async (page) => {
    await page.getByRole("button", { name: "打开构建详情" }).click();
    const drawer = page.locator('[aria-label="构建详情"]');
    await drawer.waitFor();
    for (const label of [
      "添加数据或知识",
      "自动检查与清洗",
      "可信数据版本",
      "定义 Agent 能力",
      "预览与调试",
      "质量检查",
      "发布门禁",
      "发布给 Agent",
    ]) {
      await drawer.getByText(label).waitFor();
    }
    await drawer.getByRole("button", { name: "关闭构建详情" }).click();
    await page.getByRole("button", { name: "模拟调用" }).click();
  },
  "debug",
);

await scenario(
  "04-publish-stage",
  "Publish-stage CTA and evaluation gate",
  "/?file=journey_knowledge&step=7&pane=open",
  { width: 1440, height: 900 },
  async (page) => {
    await page.getByRole("button", { name: "提交发布" }).click();
  },
  "publish",
);

await scenario(
  "05-published-view",
  "Published Skill read model",
  "/?file=journey_knowledge&step=8&pane=open",
  { width: 1440, height: 900 },
  async (page) => {
    await page.getByText("发布版本：0.1.0", { exact: true }).first().waitFor();
    await page.getByRole("button", { name: "执行调用" }).first().click();
  },
  "published",
);

await scenario(
  "06-auth-error",
  "Credential error blocks the Journey CTA",
  "/?file=journey_knowledge&step=1&error_state=auth_failed&pane=open",
  { width: 1440, height: 900 },
  async (page) => {
    await page.getByRole("button", { name: "修复凭证" }).waitFor();
    const primary = page.getByRole("button", { name: "等待服务端确认" });
    if (!(await primary.isDisabled())) {
      throw new Error("credential error did not block the primary CTA");
    }
  },
);

await scenario(
  "07-render-error",
  "Artifact render error remains inside the Artifact boundary",
  "/?file=journey_workday_mcp&step=5&error_state=render_error&pane=open",
  { width: 1440, height: 900 },
  async (page) => {
    await page.getByRole("status", { name: "Artifact 渲染错误" }).waitFor();
    await page
      .getByRole("status", { name: "Artifact 渲染错误" })
      .getByText("Artifact 暂时无法渲染")
      .first()
      .waitFor();
  },
);

await scenario(
  "08-mobile-shell",
  "Mobile Journey and directory",
  "/?file=journey_knowledge&step=1&pane=open",
  { width: 390, height: 844 },
  async (page) => {
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      )
    ) {
      throw new Error("mobile horizontal overflow");
    }
    await page.getByLabel("打开目录").click();
    const menu = page.getByRole("dialog", { name: "目录" });
    await menu.waitFor();
    for (const label of ["数据与知识", "Skill 草稿", "已发布 Skill"]) {
      if ((await menu.getByText(new RegExp(label)).count()) < 2) {
        throw new Error(`directory is missing personal/team ${label} roots`);
      }
    }
  },
);

const requiredEventNames = [
  "workspace_home_view",
  "workspace_menu_more_click",
  "skill_draft_view",
  "skill_primary_cta_click",
  "skill_build_detail_drawer_open",
  "skill_auth_error_shown",
  "skill_debug_view",
  "skill_debug_render_error_shown",
  "skill_eval_view",
  "skill_publish_submit",
  "skill_published_view",
  "skill_simulate_call_click",
  "skill_schema_drift_warning_shown",
];
const summary = {
  schema_version: "knowledge-shell.behavior-sweep.v1",
  origin,
  scenarioCount: results.length,
  requiredObservedEvents: requiredEventNames.filter((name) =>
    results.some((result) => result.events.some((event) => event.name === name)),
  ),
  status:
    results.length === 8 &&
    results.every(
      (result) =>
        result.status === "pass" &&
        result.consoleErrors.length === 0 &&
        result.pageErrors.length === 0 &&
        result.horizontalOverflowPx === 0,
    ) &&
    requiredEventNames.every((name) =>
      results.some((result) => result.events.some((event) => event.name === name)),
    )
      ? "pass"
      : "fail",
  scenarios: results,
};
writeFileSync(
  resolve(evidenceRoot, "report.json"),
  `${JSON.stringify(summary, null, 2)}\n`,
);
console.log(JSON.stringify(summary, null, 2));
await browser.close();
if (summary.status !== "pass") process.exitCode = 1;
