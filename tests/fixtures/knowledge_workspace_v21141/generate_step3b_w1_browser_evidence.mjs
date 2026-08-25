#!/usr/bin/env node

import { spawn } from "node:child_process";
import { createHmac, randomBytes } from "node:crypto";
import { createServer } from "node:http";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import net from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repository = resolve(scriptDirectory, "../../..");
const frontend = resolve(repository, "frontend");
const runtimeDirectory = resolve(
  process.env.STEP3B_W1_BROWSER_EVIDENCE_DIR ??
    "/Users/bytedance/.codex/runtime/knowledge-step3b-w1-browser",
);
const python =
  process.env.STEP3B_W1_PYTHON ?? resolve(repository, ".venv/bin/python");
const chrome =
  process.env.STEP3B_W1_CHROME ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const mcpServer = resolve(
  repository,
  "tests/fixtures/knowledge_workspace_v21141/mcp_sdk_infrastructure_server.py",
);
const mcpData = resolve(runtimeDirectory, "infrastructure-metrics.json");
const harPath = resolve(runtimeDirectory, "browser.har");
const videoDirectory = resolve(runtimeDirectory, "video");
const browserLogPath = resolve(runtimeDirectory, "browser-console.json");
const serverLogPath = resolve(runtimeDirectory, "server.log");
const mcpTranscriptPath = resolve(runtimeDirectory, "mcp-transcript.json");
const reportPath = resolve(runtimeDirectory, "browser-evidence.json");
const sourceFixtureDirectory = resolve(runtimeDirectory, "source-fixtures");

mkdirSync(runtimeDirectory, { recursive: true });
mkdirSync(videoDirectory, { recursive: true });
writeFileSync(
  mcpData,
  `${JSON.stringify(
    [
      {
        service: "search",
        cpuPercent: 37.4,
        dataAsOf: "2026-08-25T20:00:00Z",
      },
      {
        service: "indexer",
        cpuPercent: 61.8,
        dataAsOf: "2026-08-25T20:00:00Z",
      },
    ],
    null,
    2,
  )}\n`,
);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function unusedPort() {
  return await new Promise((resolvePort, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => {
        if (error) reject(error);
        else resolvePort(port);
      });
    });
  });
}

function sanitized(value) {
  return String(value)
    .replace(/(authorization["']?\s*[:=]\s*["']?bearer\s+)[^\s"',}]+/gi, "$1[REDACTED]")
    .replace(/(token|password|secret)(["']?\s*[:=]\s*["']?)[^\s"',}]+/gi, "$1$2[REDACTED]");
}

function redactAndVerifyHar() {
  assert(existsSync(harPath), "browser HAR was not created");
  const har = JSON.parse(readFileSync(harPath, "utf8"));
  const entries = har.log?.entries ?? [];
  const requestIds = new Set();
  let webhookTraceFound = false;
  for (const entry of entries) {
    for (const header of entry.request?.headers ?? []) {
      const name = String(header.name).toLowerCase();
      if (name === "x-request-id") requestIds.add(header.value);
      if (
        name === "x-trace-id" &&
        header.value === report.operationTraceConsistency.webhook?.traceId
      ) {
        webhookTraceFound = true;
      }
      if (
        ["authorization", "cookie", "x-webhook-signature"].includes(name)
      ) {
        header.value = "[REDACTED]";
      }
    }
  }
  const traced = Object.values(report.operationTraceConsistency).filter(
    (item) => item && typeof item === "object" && item.traceId,
  );
  for (const item of traced) {
    if (item === report.operationTraceConsistency.webhook) continue;
    assert(
      requestIds.has(item.traceId),
      `HAR is missing request correlation ${item.traceId}`,
    );
  }
  assert(webhookTraceFound, "HAR is missing the webhook trace correlation");
  writeFileSync(harPath, `${JSON.stringify(har)}\n`);
  return {
    status: "PASS",
    requestCount: entries.length,
    correlatedTraceCount: traced.length,
    sensitiveHeadersRedacted: true,
  };
}

function startLoggedProcess(name, command, args, options, logs) {
  const child = spawn(command, args, {
    ...options,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const append = (stream, chunk) => {
    logs.push({
      process: name,
      stream,
      text: sanitized(chunk.toString()),
      at: new Date().toISOString(),
    });
  };
  child.stdout.on("data", (chunk) => append("stdout", chunk));
  child.stderr.on("data", (chunk) => append("stderr", chunk));
  return child;
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

async function stopProcess(child) {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  const exited = await Promise.race([
    new Promise((resolveExit) => child.once("exit", () => resolveExit(true))),
    new Promise((resolveTimeout) =>
      setTimeout(() => resolveTimeout(false), 5_000),
    ),
  ]);
  if (!exited && child.exitCode === null) {
    child.kill("SIGKILL");
    await new Promise((resolveExit) => child.once("exit", resolveExit));
  }
}

async function waitForUrl(url, label, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = `${response.status} ${response.statusText}`;
    } catch (error) {
      lastError = String(error);
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`${label} did not become ready: ${lastError}`);
}

async function runFixtureCommand(name, args) {
  const child = startLoggedProcess(
    name,
    python,
    args,
    { cwd: repository, env: backendEnvironment },
    processLogs,
  );
  const exitCode = await new Promise((resolveExit) =>
    child.once("exit", resolveExit),
  );
  assert(exitCode === 0, `${name} failed with exit code ${exitCode}`);
}

async function runFixtureJsonCommand(name, args) {
  let stdout = "";
  const child = spawn(python, args, {
    cwd: repository,
    env: backendEnvironment,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => {
    stdout += chunk.toString();
    processLogs.push({
      process: name,
      stream: "stdout",
      text: sanitized(chunk.toString()),
      at: new Date().toISOString(),
    });
  });
  child.stderr.on("data", (chunk) => {
    processLogs.push({
      process: name,
      stream: "stderr",
      text: sanitized(chunk.toString()),
      at: new Date().toISOString(),
    });
  });
  const exitCode = await new Promise((resolveExit) =>
    child.once("exit", resolveExit),
  );
  assert(exitCode === 0, `${name} failed with exit code ${exitCode}`);
  return JSON.parse(stdout);
}

async function startHttpFixture() {
  const port = await unusedPort();
  const state = {
    rows: [
      { id: 1, name: "alpha" },
      { id: 2, name: "beta" },
    ],
  };
  const server = createServer((request, response) => {
    if (request.url?.startsWith("/oversized")) {
      const body = JSON.stringify([{ value: "x".repeat(2_000) }]);
      response.writeHead(200, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(body),
      });
      response.end(body);
      return;
    }
    if (request.url?.startsWith("/slow")) {
      setTimeout(() => {
        const body = '{"status":"late"}';
        response.writeHead(200, {
          "content-type": "application/json",
          "content-length": Buffer.byteLength(body),
        });
        response.end(body);
      }, 2_000);
      return;
    }
    if (request.url?.startsWith("/items")) {
      const body = JSON.stringify(state.rows);
      response.writeHead(200, {
        "content-type": "application/json",
        etag: `"items-${state.rows.length}"`,
        "content-length": Buffer.byteLength(body),
      });
      response.end(body);
      return;
    }
    response.writeHead(404, { "content-type": "application/json" });
    response.end('{"error":"not found"}');
  });
  await new Promise((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolveListen);
  });
  return {
    origin: `http://127.0.0.1:${port}`,
    state,
    close: () =>
      new Promise((resolveClose, reject) =>
        server.close((error) => (error ? reject(error) : resolveClose())),
      ),
  };
}

function categoryCounts(connectors) {
  return connectors.reduce((counts, connector) => {
    counts[connector.category] = (counts[connector.category] ?? 0) + 1;
    return counts;
  }, {});
}

function normalizeLabel(value) {
  return value.replace(/\s+/g, " ").trim().replace(/ 文件$/, "");
}

async function jsonResponse(response) {
  const body = await response.json();
  assert(response.ok(), `${response.url()} returned ${response.status()}`);
  return body;
}

async function command(commandName, payload, suffix) {
  return jsonResponse(
    await page.request.post(
      `${frontendOrigin}/api/knowledge-assets/v1/commands`,
      {
        data: { command: commandName, payload },
        headers: {
          "X-Request-ID": `browser-${suffix}`,
          "Idempotency-Key": `browser-${suffix}`,
        },
      },
    ),
  );
}

async function uploadSource(filename, mimeType) {
  return jsonResponse(
    await page.request.post(`${backendOrigin}/api/source-golden/v1/uploads`, {
      multipart: {
        upload: {
          name: filename,
          mimeType,
          buffer: readFileSync(resolve(sourceFixtureDirectory, filename)),
        },
      },
    }),
  );
}

async function createAndIngest({
  connectorKey,
  displayName,
  configuration,
  suffix,
  resourceId,
  secretRef,
}) {
  const created = await command(
    "source-golden.connection.create",
    {
      connectorKey,
      displayName,
      scope: "team",
      configuration,
      ...(secretRef ? { secretRef } : {}),
    },
    `${suffix}-create`,
  );
  assert(created.accepted === true, `${connectorKey} create was not accepted`);
  const connection = created.result.connection;
  const discovered =
    resourceId ?? created.result.discovery.resources[0]?.id;
  assert(discovered, `${connectorKey} did not discover a resource`);
  const ingested = await command(
    "source-golden.ingest",
    {
      connectionId: connection.id,
      resourceId: discovered,
      recipeOperations: ["trim"],
      toolArguments: {},
    },
    `${suffix}-ingest`,
  );
  assert(ingested.accepted === true, `${connectorKey} ingest was not accepted`);
  const source = ingested.result.sourceRevision;
  const golden = ingested.result.goldenAssetRevision;
  const contextReference = {
    kind: "golden_asset",
    objectId: golden.assetId,
    revision: golden.id,
    providerRevision: source.id,
  };
  const resolved = await jsonResponse(
    await page.request.post(
      `${backendOrigin}/api/source-golden/v1/context/resolve`,
      { data: { reference: contextReference } },
    ),
  );
  assert(resolved.objectId === golden.assetId, `${connectorKey} context mismatch`);
  const content = await page.request.get(
    `${backendOrigin}/api/source-golden/v1/golden-revisions/${encodeURIComponent(
      golden.id,
    )}/content`,
  );
  assert(content.ok(), `${connectorKey} Golden content was not readable`);
  assert(
    (await content.body()).length > 0,
    `${connectorKey} Golden content was empty`,
  );
  return { connectorKey, connection, source, golden, contextReference };
}

async function operationTraceEvidence(result, expectedOperations) {
  const operations = await jsonResponse(
    await page.request.get(
      `${backendOrigin}/api/source-golden/v1/connections/${encodeURIComponent(
        result.connection.id,
      )}/operations`,
    ),
  );
  const operationNames = new Set(operations.map((item) => item.operation));
  for (const expected of expectedOperations) {
    assert(
      operationNames.has(expected),
      `${result.connectorKey} operation log is missing ${expected}`,
    );
  }
  const tracedOperation = operations.find(
    (item) => item.operation === "read" && item.status === "succeeded",
  );
  assert(tracedOperation, `${result.connectorKey} has no successful read trace`);
  const trace = await jsonResponse(
    await page.request.get(
      `${backendOrigin}/api/source-golden/v1/connections/${encodeURIComponent(
        result.connection.id,
      )}/traces/${encodeURIComponent(tracedOperation.traceId)}`,
    ),
  );
  assert(
    trace.connectionId === result.connection.id &&
      trace.traceId === tracedOperation.traceId,
    `${result.connectorKey} trace identity is inconsistent`,
  );
  assert(
    trace.operations.every(
      (item) =>
        item.connectionId === result.connection.id &&
        item.traceId === tracedOperation.traceId,
    ),
    `${result.connectorKey} trace contains inconsistent operations`,
  );
  assert(
    trace.events.every(
      (item) =>
        item.connectionId === result.connection.id &&
        item.traceId === tracedOperation.traceId,
    ),
    `${result.connectorKey} trace contains inconsistent events`,
  );
  return {
    connectionId: result.connection.id,
    traceId: tracedOperation.traceId,
    operationCount: trace.operations.length,
    eventCount: trace.events.length,
    operations: [...new Set(trace.operations.map((item) => item.operation))],
  };
}

const backendPort = await unusedPort();
const frontendPort = await unusedPort();
const backendOrigin = `http://127.0.0.1:${backendPort}`;
const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
const processLogs = [];
const browserLogs = [];
let backend;
let vite;
let browser;
let context;
let page;
let video;
let httpFixture;

const backendEnvironment = {
  ...process.env,
  PYTHONPATH: [repository, process.env.PYTHONPATH].filter(Boolean).join(":"),
  STEP3B_BROWSER_RUNTIME_ROOT: runtimeDirectory,
  STEP3_MCP_PROFILE_ID: "browser-official-sdk",
  STEP3_MCP_SERVER_PATH: mcpServer,
  STEP3_MCP_DATA_PATH: mcpData,
  STEP3B_WEBHOOK_SECRET: randomBytes(32).toString("hex"),
};
const databaseFixture = resolve(
  repository,
  "tests/fixtures/knowledge_workspace_v21141/prepare_step3b_browser_databases.py",
);

function startBackend() {
  return startLoggedProcess(
    "bff",
    python,
    [
      "-m",
      "uvicorn",
      "tests.fixtures.knowledge_workspace_v21141.step3b_w1_browser_server:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(backendPort),
      "--no-server-header",
    ],
    { cwd: runtimeDirectory, env: backendEnvironment },
    processLogs,
  );
}

const report = {
  schemaVersion: "knowledge-assets.step3b.w1-browser-evidence.v1",
  generatedAt: new Date().toISOString(),
  repository,
  runtimeDirectory,
  ports: { bff: backendPort, vite: frontendPort },
  status: "FAIL",
  catalog: {},
  connectorUiAudit: [],
  mcp: {},
  localSources: {},
  httpSources: {},
  httpFixture: {},
  context: {},
  databases: { status: "SKIPPED", reason: "STEP3B_DB_PASSWORD not set" },
  operationTraceConsistency: {},
  harConsistency: {},
  negativeCases: {},
  restartRecovery: {},
  sharedUiSeam: {},
  artifacts: {
    har: harPath,
    video: resolve(runtimeDirectory, "browser.webm"),
    browserLog: browserLogPath,
    serverLog: serverLogPath,
    mcpTranscript: mcpTranscriptPath,
    screenshots: [],
  },
};

try {
  const fixtureBuilder = startLoggedProcess(
    "source-fixture-builder",
    python,
    [
      resolve(
        repository,
        "tests/fixtures/knowledge_workspace_v21141/prepare_step3b_browser_sources.py",
      ),
      sourceFixtureDirectory,
    ],
    { cwd: repository, env: backendEnvironment },
    processLogs,
  );
  const fixtureExit = await new Promise((resolveExit) =>
    fixtureBuilder.once("exit", resolveExit),
  );
  assert(fixtureExit === 0, "source fixture generation failed");
  httpFixture = await startHttpFixture();
  report.httpFixture = {
    implementation: "node:http",
    runtimeVersion: process.version,
    origin: httpFixture.origin,
  };
  backend = startBackend();
  await waitForUrl(
    `${backendOrigin}/api/knowledge-assets/v1/bootstrap`,
    "Knowledge Asset BFF",
  );
  vite = startLoggedProcess(
    "vite",
    resolve(frontend, "node_modules/.bin/vite"),
    [
      "--host",
      "127.0.0.1",
      "--port",
      String(frontendPort),
      "--strictPort",
    ],
    {
      cwd: frontend,
      env: { ...process.env, VEADK_API_TARGET: backendOrigin },
    },
    processLogs,
  );
  await waitForUrl(frontendOrigin, "Vite");

  browser = await chromium.launch({ headless: true, executablePath: chrome });
  context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "light",
    reducedMotion: "reduce",
    recordHar: { path: harPath, mode: "full", content: "embed" },
    recordVideo: { dir: videoDirectory, size: { width: 1440, height: 900 } },
  });
  page = await context.newPage();
  video = page.video();
  page.on("console", (message) => {
    browserLogs.push({
      type: message.type(),
      text: sanitized(message.text()),
      at: new Date().toISOString(),
    });
  });
  page.on("pageerror", (error) => {
    browserLogs.push({
      type: "pageerror",
      text: sanitized(error),
      at: new Date().toISOString(),
    });
  });

  await page.goto(`${frontendOrigin}/?studio=knowledge`, {
    waitUntil: "networkidle",
  });
  const homeScreenshot = resolve(runtimeDirectory, "01-home.png");
  await page.screenshot({ path: homeScreenshot, fullPage: true });
  report.artifacts.screenshots.push(homeScreenshot);

  await page.getByRole("button", { name: "新建资源" }).first().click();
  await page.getByRole("dialog").waitFor();
  const modalScreenshot = resolve(runtimeDirectory, "02-new-resource.png");
  await page.screenshot({ path: modalScreenshot, fullPage: true });
  report.artifacts.screenshots.push(modalScreenshot);
  await page.getByRole("button", { name: /连接或同步来源/ }).click();
  await page
    .getByRole("heading", { name: "添加连接或上下文", exact: true })
    .first()
    .waitFor();

  const bootstrap = await jsonResponse(
    await page.request.get(
      `${frontendOrigin}/api/knowledge-assets/v1/bootstrap`,
    ),
  );
  const connectors = bootstrap.workspaceData.connectorCatalog;
  assert(Array.isArray(connectors), "bootstrap connectorCatalog is not an array");
  assert(connectors.length === 37, `expected 37 connectors, got ${connectors.length}`);
  assert(
    new Set(connectors.map((connector) => connector.connectorKey)).size === 37,
    "connector keys are not unique",
  );
  const counts = categoryCounts(connectors);
  assert(
    JSON.stringify(counts) ===
      JSON.stringify({ office: 10, file: 8, db: 11, api: 5, custom: 3 }),
    `unexpected category counts: ${JSON.stringify(counts)}`,
  );
  assert(
    connectors.every((connector) => connector.capabilityState === "available"),
    "browser bootstrap contains a non-available formal adapter",
  );
  const browserMcp = connectors.find(
    (connector) => connector.connectorKey === "mcp_custom",
  );
  assert(browserMcp, "browser bootstrap is missing MCP");
  assert(
    JSON.stringify(browserMcp.inputSchema) ===
      JSON.stringify({ profileId: "string" }),
    "browser bootstrap exposes MCP fields other than profileId",
  );
  for (const forbidden of ["command", "args", "cwd", "env", "secretRef"]) {
    assert(
      !JSON.stringify(browserMcp).includes(`\"${forbidden}\"`),
      `browser bootstrap exposes forbidden MCP field ${forbidden}`,
    );
  }
  report.catalog = {
    total: connectors.length,
    categoryCounts: counts,
    capabilityStates: { available: 37 },
    source: "GET /api/knowledge-assets/v1/bootstrap",
    enteredFromSidebarPlus: true,
  };
  const catalogScreenshot = resolve(runtimeDirectory, "03-catalog-all.png");
  await page.screenshot({ path: catalogScreenshot, fullPage: true });
  report.artifacts.screenshots.push(catalogScreenshot);

  const categoryLabels = {
    office: "办公上下文",
    file: "文件与对象存储",
    db: "数据库与数仓",
    api: "API 与流",
    custom: "自定义与扩展",
  };
  for (const [category, label] of Object.entries(categoryLabels)) {
    await page.getByRole("button", { name: new RegExp(label) }).click();
    await page
      .getByText(`共找到 ${counts[category]} 个符合条件的连接器`, {
        exact: true,
      })
      .waitFor();
    const screenshot = resolve(runtimeDirectory, `category-${category}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    report.artifacts.screenshots.push(screenshot);
  }
  await page.goto(
    `${frontendOrigin}/?studio=knowledge&file=add_data&step=1`,
    { waitUntil: "networkidle" },
  );
  const searchInputs = await page
    .locator('input[placeholder="搜索连接器..."]')
    .all();
  for (const searchInput of searchInputs) {
    await searchInput.evaluate((element) => {
      const input = element;
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(input, "OpenAPI");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  await page
    .getByText("共找到 2 个符合条件的连接器", { exact: true })
    .first()
    .waitFor();
  assert(
    (await page.locator("h4:visible", { hasText: "OpenAPI Spec" }).count()) > 0,
    "OpenAPI search result is not visible",
  );
  const searchScreenshot = resolve(runtimeDirectory, "04-search-openapi.png");
  await page.screenshot({ path: searchScreenshot, fullPage: true });
  report.artifacts.screenshots.push(searchScreenshot);

  for (const [index, connector] of connectors.entries()) {
    await page.goto(
      `${frontendOrigin}/?studio=knowledge&file=add_data&step=2&source=${encodeURIComponent(
        connector.connectorKey,
      )}`,
      { waitUntil: "networkidle" },
    );
    await page
      .getByRole("heading", { name: `配置 ${connector.name}` })
      .first()
      .waitFor();
    const labels = (await page.locator("label").allTextContents()).map(
      normalizeLabel,
    );
    const inputFields = Object.keys(connector.inputSchema);
    const credentialFields = Object.keys(connector.credentialSchema ?? {});
    if (connector.connectorKey === "mcp_custom") {
      assert(
        labels.includes("服务端 MCP Profile"),
        "MCP browser form does not expose the server profile selector",
      );
      for (const forbidden of ["command", "args", "cwd", "env", "secretRef"]) {
        assert(
          !labels.includes(forbidden),
          `MCP browser form exposes forbidden execution field ${forbidden}`,
        );
      }
    } else {
      for (const expected of inputFields) {
        assert(
          labels.includes(expected),
          `${connector.connectorKey} is missing input field ${expected}`,
        );
      }
    }
    let credentialLabels = [];
    if (connector.connectorKey !== "mcp_custom" && credentialFields.length > 0) {
      await page
        .locator("button:visible", { hasText: "下一步" })
        .first()
        .click();
      await page
        .getByRole("heading", { name: /步骤 2: 授权与鉴权测试/ })
        .waitFor();
      credentialLabels = (await page.locator("label").allTextContents()).map(
        normalizeLabel,
      );
      for (const expected of credentialFields) {
        assert(
          credentialLabels.includes(expected),
          `${connector.connectorKey} is missing credential field ${expected}`,
        );
      }
    }
    const screenshot = resolve(
      runtimeDirectory,
      `connector-${String(index + 1).padStart(2, "0")}-${connector.connectorKey}.png`,
    );
    await page.screenshot({ path: screenshot, fullPage: true });
    report.artifacts.screenshots.push(screenshot);
    report.connectorUiAudit.push({
      connectorKey: connector.connectorKey,
      category: connector.category,
      name: connector.name,
      descriptionPresent: Boolean(connector.desc),
      capabilityState: connector.capabilityState,
      capabilityStateSource: "browser-received server bootstrap",
      inputFields,
      renderedInputLabels: labels,
      credentialFields,
      renderedCredentialLabels: credentialLabels,
      screenshot,
      status: "PASS",
    });
  }

  await page.goto(
    `${frontendOrigin}/?studio=knowledge&file=add_data&step=2&source=csv`,
    { waitUntil: "networkidle" },
  );
  await page
    .locator("button:visible", { hasText: "下一步" })
    .first()
    .click();
  await page
    .getByRole("alert")
    .filter({ hasText: "尚未接入真实服务端执行" })
    .waitFor();
  const seamScreenshot = resolve(
    runtimeDirectory,
    "05-non-mcp-shared-command-seam.png",
  );
  await page.screenshot({ path: seamScreenshot, fullPage: true });
  report.artifacts.screenshots.push(seamScreenshot);
  report.sharedUiSeam = {
    status: "MAIN_WIRING_REQUIRED",
    owner: "shared frozen UI and command composition",
    observed:
      "The non-MCP save path fails explicitly and does not create a local fake connection.",
    existingCommands: [
      "source-golden.connection.create",
      "source-golden.ingest",
    ],
    screenshot: seamScreenshot,
  };

  const localCases = [
    ["csv", "orders.csv", "text/csv", {}],
    [
      "excel",
      "orders.xlsx",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      { sheetAllowlist: ["Orders"] },
    ],
    ["json", "orders.json", "application/json", { maxDepth: 8, maxRows: 100 }],
    [
      "parquet",
      "orders.parquet",
      "application/vnd.apache.parquet",
      {
        maxRows: 100,
        maxColumns: 20,
        maxUncompressedBytes: 100000,
        maxNestingDepth: 8,
      },
    ],
    ["doc_txt", "notes.pdf", "application/pdf", { maxTextChars: 10000 }],
    ["local_file", "notes.md", "text/markdown", {}],
    ["doc_txt", "notes.txt", "text/plain", { maxTextChars: 10000 }],
    ["doc_txt", "notes.html", "text/html", { maxTextChars: 10000 }],
    [
      "sqlite",
      "orders.sqlite",
      "application/vnd.sqlite3",
      { tableAllowlist: ["orders"], rowLimit: 100 },
    ],
  ];
  const localResults = [];
  for (const [connectorKey, filename, mimeType, extraConfiguration] of localCases) {
    const upload = await uploadSource(filename, mimeType);
    localResults.push(
      await createAndIngest({
        connectorKey,
        displayName: `Browser ${connectorKey} ${filename}`,
        configuration: {
          sourceRef: upload.sourceRef,
          ...extraConfiguration,
        },
        suffix: `${connectorKey}-${filename.replaceAll(".", "-")}`,
      }),
    );
  }

  const restResult = await createAndIngest({
    connectorKey: "rest_api",
    displayName: "Browser REST",
    configuration: {
      endpoint: `${httpFixture.origin}/items`,
      operationAllowlist: ["read"],
      paginationMode: "none",
      pageSize: 10,
      maxPages: 2,
      maxRows: 100,
      maxResponseBytes: 100000,
      rateLimitPerMinute: 60,
      timeoutSeconds: 5,
    },
    suffix: "rest",
  });
  const openApiDocument = {
    openapi: "3.1.0",
    info: { title: "Browser inventory", version: "1" },
    servers: [{ url: httpFixture.origin }],
    paths: {
      "/items": {
        get: {
          operationId: "listItems",
          responses: {
            200: {
              description: "ok",
              content: {
                "application/json": {
                  schema: {
                    type: "array",
                    items: {
                      type: "object",
                      properties: {
                        id: { type: "integer" },
                        name: { type: "string" },
                      },
                    },
                  },
                },
              },
            },
          },
        },
      },
    },
  };
  writeFileSync(
    resolve(sourceFixtureDirectory, "inventory.openapi.json"),
    `${JSON.stringify(openApiDocument, null, 2)}\n`,
  );
  const openApiUpload = await uploadSource(
    "inventory.openapi.json",
    "application/json",
  );
  const openApiResult = await createAndIngest({
    connectorKey: "openapi_spec",
    displayName: "Browser OpenAPI",
    configuration: {
      specRef: openApiUpload.sourceRef,
      operationAllowlist: ["listItems"],
      maxRows: 100,
      maxResponseBytes: 100000,
      rateLimitPerMinute: 60,
      timeoutSeconds: 5,
    },
    suffix: "openapi",
  });
  httpFixture.state.rows = [{ id: 1, name: "alpha", stock: 8 }];
  const refresh = await jsonResponse(
    await page.request.post(
      `${backendOrigin}/api/source-golden/v1/golden-assets/${encodeURIComponent(
        openApiResult.golden.assetId,
      )}/refresh`,
      {
        data: {},
        headers: {
          "X-Request-ID": "browser-openapi-refresh",
          "Idempotency-Key": "browser-openapi-refresh",
        },
      },
    ),
  );
  assert(refresh.run.status === "schema_drift", "OpenAPI schema drift was missed");

  const databaseResults = [];
  if (
    process.env.STEP3B_DB_PASSWORD &&
    process.env.STEP3B_POSTGRES_PORT &&
    process.env.STEP3B_MYSQL_PORT
  ) {
    await runFixtureCommand("database-fixture-initialize", [
      databaseFixture,
      "initialize",
    ]);
    const databaseVersions = await runFixtureJsonCommand(
      "database-fixture-versions",
      [databaseFixture, "versions"],
    );
    for (const connectorKey of ["postgresql", "mysql"]) {
      const schema = connectorKey === "postgresql" ? "public" : "knowledge";
      const port =
        connectorKey === "postgresql"
          ? Number(process.env.STEP3B_POSTGRES_PORT)
          : Number(process.env.STEP3B_MYSQL_PORT);
      const configuration = {
        host: "127.0.0.1",
        port,
        database: "knowledge",
        schemaAllowlist: [schema],
        tableAllowlist: ["step3b_browser_orders"],
        query:
          `SELECT * FROM ${schema}.step3b_browser_orders ` +
          "WHERE amount >= :minimum ORDER BY order_id",
        queryParameters: { minimum: 10 },
        pageSize: 1,
        rowLimit: 10,
        byteLimit: 10000,
        timeoutSeconds: 5,
      };
      const result = await createAndIngest({
        connectorKey,
        displayName: `Browser ${connectorKey}`,
        configuration,
        suffix: `database-${connectorKey}`,
        secretRef: `secret://workspace-step3/${connectorKey}`,
      });
      databaseResults.push(result);
      const wrongPasswordResponse = await page.request.post(
        `${frontendOrigin}/api/knowledge-assets/v1/commands`,
        {
          data: {
            command: "source-golden.connection.create",
            payload: {
              connectorKey,
              displayName: `Wrong password ${connectorKey}`,
              scope: "personal",
              configuration,
              secretRef: `secret://workspace-step3/${connectorKey}-wrong`,
            },
          },
          headers: {
            "X-Request-ID": `browser-database-${connectorKey}-wrong-password`,
            "Idempotency-Key": `browser-database-${connectorKey}-wrong-password`,
          },
        },
      );
      const wrongPassword = await wrongPasswordResponse.json();
      assert(
        wrongPasswordResponse.status() === 422 &&
          wrongPassword.code === "DATABASE_AUTHENTICATION_FAILED",
        `${connectorKey} wrong password was not typed and fail-closed`,
      );
      const writeResponse = await page.request.post(
        `${frontendOrigin}/api/knowledge-assets/v1/commands`,
        {
          data: {
            command: "source-golden.connection.create",
            payload: {
              connectorKey,
              displayName: `Write query ${connectorKey}`,
              scope: "personal",
              configuration: {
                ...configuration,
                query:
                  `UPDATE ${schema}.step3b_browser_orders ` +
                  "SET amount = :minimum",
              },
              secretRef: `secret://workspace-step3/${connectorKey}`,
            },
          },
          headers: {
            "X-Request-ID": `browser-database-${connectorKey}-write`,
            "Idempotency-Key": `browser-database-${connectorKey}-write`,
          },
        },
      );
      assert(writeResponse.status() === 422, `${connectorKey} write SQL was accepted`);
      const writeBody = await writeResponse.json();
      assert(
        writeBody.code === "DATABASE_CONFIGURATION_INVALID",
        `${connectorKey} write SQL rejection was not typed`,
      );
      const bounded = await command(
        "source-golden.connection.create",
        {
          connectorKey,
          displayName: `Bounded ${connectorKey}`,
          scope: "personal",
          configuration: {
            ...configuration,
            queryParameters: { minimum: 0 },
            rowLimit: 1,
          },
          secretRef: `secret://workspace-step3/${connectorKey}`,
        },
        `database-${connectorKey}-bounded-create`,
      );
      const oversized = await page.request.post(
        `${frontendOrigin}/api/knowledge-assets/v1/commands`,
        {
          data: {
            command: "source-golden.ingest",
            payload: {
              connectionId: bounded.result.connection.id,
              resourceId: bounded.result.discovery.resources[0].id,
              recipeOperations: [],
              toolArguments: {},
            },
          },
          headers: {
            "X-Request-ID": `browser-database-${connectorKey}-oversized`,
            "Idempotency-Key": `browser-database-${connectorKey}-oversized`,
          },
        },
      );
      assert(oversized.status() === 422, `${connectorKey} row budget did not fail`);
      const oversizedBody = await oversized.json();
      assert(
        oversizedBody.code === "DATABASE_ROW_LIMIT",
        `${connectorKey} row budget rejection was not typed`,
      );
      report.negativeCases[`${connectorKey}WrongPassword`] =
        {
          status: wrongPasswordResponse.status(),
          code: wrongPassword.code,
        };
      report.negativeCases[`${connectorKey}WriteSql`] = {
        status: writeResponse.status(),
        code: writeBody.code,
      };
      report.negativeCases[`${connectorKey}Oversized`] = {
        status: oversized.status(),
        code: oversizedBody.code,
      };
    }
    await runFixtureCommand("database-fixture-update", [databaseFixture, "update"]);
    const refreshResults = [];
    for (const result of databaseResults) {
      const refreshed = await jsonResponse(
        await page.request.post(
          `${backendOrigin}/api/source-golden/v1/golden-assets/${encodeURIComponent(
            result.golden.assetId,
          )}/refresh`,
          {
            data: {},
            headers: {
              "X-Request-ID": `browser-${result.connectorKey}-refresh`,
              "Idempotency-Key": `browser-${result.connectorKey}-refresh`,
            },
          },
        ),
      );
      assert(refreshed.run.status === "succeeded", "database refresh failed");
      refreshResults.push(refreshed);
    }
    await runFixtureCommand("database-fixture-schema", [databaseFixture, "schema"]);
    const driftResults = [];
    for (const [index, result] of databaseResults.entries()) {
      const drifted = await jsonResponse(
        await page.request.post(
          `${backendOrigin}/api/source-golden/v1/golden-assets/${encodeURIComponent(
            result.golden.assetId,
          )}/refresh`,
          {
            data: {},
            headers: {
              "X-Request-ID": `browser-${result.connectorKey}-schema-drift`,
              "Idempotency-Key": `browser-${result.connectorKey}-schema-drift`,
            },
          },
        ),
      );
      assert(
        drifted.run.status === "schema_drift" &&
          drifted.lastGoodRevision?.id ===
            refreshResults[index].goldenAssetRevision?.id,
        `${result.connectorKey} schema drift did not preserve last good`,
      );
      driftResults.push(drifted);
    }
    report.databases = {
      status: "PASS",
      images: {
        postgresql: process.env.STEP3B_POSTGRES_IMAGE ?? "postgres:16-alpine",
        mysql: process.env.STEP3B_MYSQL_IMAGE ?? "mysql:8.4",
      },
      versions: databaseVersions,
      cases: databaseResults.map((result, index) => ({
        connectorKey: result.connectorKey,
        port:
          result.connectorKey === "postgresql"
            ? Number(process.env.STEP3B_POSTGRES_PORT)
            : Number(process.env.STEP3B_MYSQL_PORT),
        connectionId: result.connection.id,
        sourceRevisionId: result.source.id,
        initialGoldenRevisionId: result.golden.id,
        refreshedGoldenRevisionId: refreshResults[index].goldenAssetRevision.id,
        schemaDriftStatus: driftResults[index].run.status,
      })),
    };
  }

  const privateEndpoint = await page.request.post(
    `${frontendOrigin}/api/knowledge-assets/v1/commands`,
    {
      data: {
        command: "source-golden.connection.create",
        payload: {
          connectorKey: "rest_api",
          displayName: "Forbidden metadata endpoint",
          scope: "personal",
          configuration: {
            endpoint: "http://169.254.169.254/latest/meta-data",
            operationAllowlist: ["read"],
          },
        },
      },
      headers: {
        "X-Request-ID": "browser-ssrf",
        "Idempotency-Key": "browser-ssrf",
      },
    },
  );
  assert(privateEndpoint.status() === 422, "SSRF endpoint was not rejected");
  const privateEndpointBody = await privateEndpoint.json();
  assert(
    [
      "HTTP_CONFIGURATION_INVALID",
      "HTTP_ENDPOINT_FORBIDDEN",
      "HTTP_DISCOVERY_FAILED",
    ].includes(
      String(privateEndpointBody.code),
    ),
    "SSRF rejection was not typed",
  );
  const oversizedHttpResponse = await page.request.post(
    `${frontendOrigin}/api/knowledge-assets/v1/commands`,
    {
      data: {
        command: "source-golden.connection.create",
        payload: {
          connectorKey: "rest_api",
          displayName: "Oversized HTTP fixture",
          scope: "personal",
          configuration: {
            endpoint: `${httpFixture.origin}/oversized`,
            operationAllowlist: ["read"],
            timeoutSeconds: 5,
            maxResponseBytes: 128,
            maxRows: 10,
          },
        },
      },
      headers: {
        "X-Request-ID": "browser-http-oversized",
        "Idempotency-Key": "browser-http-oversized",
      },
    },
  );
  assert(
    oversizedHttpResponse.status() === 422,
    "oversized HTTP response did not fail closed",
  );
  const oversizedHttpBody = await oversizedHttpResponse.json();
  assert(
    typeof oversizedHttpBody.code === "string",
    "oversized HTTP response was not typed",
  );
  report.negativeCases.httpOversized = {
    status: oversizedHttpResponse.status(),
    code: oversizedHttpBody.code,
  };

  const webhookSchemaUpload = await uploadSource(
    "event.schema.json",
    "application/json",
  );
  const webhookCreated = await command(
    "source-golden.connection.create",
    {
      connectorKey: "webhook",
      displayName: "Browser Webhook",
      scope: "team",
      configuration: {
        listenPath: "/inventory/events",
        schemaRef: webhookSchemaUpload.sourceRef,
        maxEventBytes: 1000,
        maxEvents: 10,
        rateLimitPerMinute: 60,
      },
      secretRef: "secret://workspace-step3/browser-webhook",
    },
    "webhook-create",
  );
  assert(webhookCreated.accepted === true, "webhook create was not accepted");
  const webhookConnection = webhookCreated.result.connection;
  const webhookBody = JSON.stringify({ sku: "A-1", stock: 8 });
  const webhookTraceId = "browser-webhook-delivery";
  const webhookSignature = createHmac(
    "sha256",
    backendEnvironment.STEP3B_WEBHOOK_SECRET,
  )
    .update(webhookBody)
    .digest("hex");
  const webhookDelivery = await page.request.post(
    `${backendOrigin}/api/source-golden/v1/webhooks/workspaces/workspace-step3/connections/${encodeURIComponent(
      webhookConnection.id,
    )}/inventory/events`,
    {
      data: webhookBody,
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Id": "browser-delivery-1",
        "X-Webhook-Signature": `sha256=${webhookSignature}`,
        "X-Trace-Id": webhookTraceId,
      },
    },
  );
  assert(webhookDelivery.status() === 202, "signed webhook was not accepted");
  const webhookTrace = await jsonResponse(
    await page.request.get(
      `${backendOrigin}/api/source-golden/v1/connections/${encodeURIComponent(
        webhookConnection.id,
      )}/traces/${webhookTraceId}`,
    ),
  );
  assert(
    webhookTrace.events.length === 1 &&
      webhookTrace.events[0].eventType === "webhook.delivery.accepted" &&
      webhookTrace.operations.some(
        (operation) => operation.operation === "authorize",
      ),
    "webhook operation/event trace is inconsistent",
  );
  const webhookTraceEvidence = {
    connectionId: webhookConnection.id,
    traceId: webhookTraceId,
    operationCount: webhookTrace.operations.length,
    eventCount: webhookTrace.events.length,
  };

  const crossWorkspace = await page.request.post(
    `${backendOrigin}/api/source-golden/v1/context/resolve`,
    {
      data: { reference: localResults[0].contextReference },
      headers: { "X-Step3B-Test-Workspace": "workspace-attacker" },
    },
  );
  assert(crossWorkspace.status() === 404, "cross-workspace context did not fail closed");
  const mismatchedReference = {
    ...localResults[0].contextReference,
    objectId: "golden-forged",
  };
  const forged = await page.request.post(
    `${backendOrigin}/api/source-golden/v1/context/resolve`,
    { data: { reference: mismatchedReference } },
  );
  assert(forged.status() === 422, "forged context did not fail closed");
  const revoked = await page.request.delete(
    `${backendOrigin}/api/source-golden/v1/connections/${encodeURIComponent(
      localResults[8].connection.id,
    )}`,
    {
      data: { reason: "browser revocation certification" },
      headers: { "X-Request-ID": "browser-revoke-sqlite" },
    },
  );
  assert(revoked.status() === 204, "connection revocation failed");
  const revokedContext = await page.request.post(
    `${backendOrigin}/api/source-golden/v1/context/resolve`,
    { data: { reference: localResults[8].contextReference } },
  );
  assert(
    [403, 404].includes(revokedContext.status()),
    "revoked source context did not fail closed",
  );
  const revokedContextBody = await revokedContext.json();
  assert(
    ["PERMISSION_REVOKED", "GOLDEN_REVISION_NOT_FOUND"].includes(
      revokedContextBody.code,
    ),
    "revoked source context rejection was not typed",
  );
  report.negativeCases.revokedContext = {
    status: revokedContext.status(),
    code: revokedContextBody.code,
  };

  await page.reload({ waitUntil: "networkidle" });
  const sourceBootstrap = await jsonResponse(
    await page.request.get(`${frontendOrigin}/api/knowledge-assets/v1/bootstrap`),
  );
  const expectedGoldenIds = [
    ...localResults.slice(0, 8).map((item) => item.golden.id),
    restResult.golden.id,
    openApiResult.golden.id,
    ...(report.databases.cases ?? []).map(
      (item) => item.refreshedGoldenRevisionId,
    ),
  ];
  assert(
    expectedGoldenIds.every((id) =>
      sourceBootstrap.resources.some(
        (resource) => resource.goldenRevisionId === id,
      ),
    ),
    "non-MCP Golden revisions are missing from the browser bootstrap",
  );
  await page.goto(
    `${frontendOrigin}/?studio=knowledge&file=data_overview&chat=ready`,
    { waitUntil: "networkidle" },
  );
  const contextLabel = "Browser csv orders.csv";
  const connectionRow = page.locator("tr:visible", { hasText: contextLabel }).first();
  await connectionRow.waitFor();
  await connectionRow
    .getByRole("button", { name: "作为上下文加入" })
    .click();
  assert(
    (await page.getByText(contextLabel, { exact: true }).count()) > 1,
    "visible UI did not add a context chip",
  );
  const contextScreenshot = resolve(
    runtimeDirectory,
    "06-non-mcp-context-added.png",
  );
  await page.screenshot({ path: contextScreenshot, fullPage: true });
  report.artifacts.screenshots.push(contextScreenshot);
  const assistantInput = page.getByLabel("分析助手输入框");
  await assistantInput.fill("生成基于固定 CSV revision 的分析 Skill");
  const contextRequestPromise = page.waitForRequest((request) =>
    request.postData()?.includes('"command":"skill-authoring.start"'),
  );
  await assistantInput.press("Enter");
  const contextRequest = await contextRequestPromise;
  const contextPayload = contextRequest.postDataJSON();
  const submittedReferences = contextPayload.payload.resourceRefs;
  assert(
    submittedReferences.some(
      (reference) =>
        reference.kind === "golden_asset" &&
        reference.object_id === localResults[0].golden.assetId &&
        reference.revision === localResults[0].golden.id,
    ),
    "Agent request did not contain the immutable Golden context reference",
  );
  assert(
    contextPayload.payload.fixedRevisions.includes(localResults[0].golden.id),
    "Agent request did not pin the Golden revision",
  );
  report.localSources = {
    status: "PASS",
    cases: localResults.map((item) => ({
      connectorKey: item.connectorKey,
      connectionId: item.connection.id,
      sourceRevisionId: item.source.id,
      goldenRevisionId: item.golden.id,
    })),
  };
  report.httpSources = {
    status: "PASS",
    rest: {
      connectionId: restResult.connection.id,
      goldenRevisionId: restResult.golden.id,
    },
    openapi: {
      connectionId: openApiResult.connection.id,
      goldenRevisionId: openApiResult.golden.id,
      refreshStatus: refresh.run.status,
    },
    ssrf: {
      status: privateEndpoint.status(),
      code: privateEndpointBody.code,
    },
  };
  const traceResults = {
    webhook: webhookTraceEvidence,
    csv: await operationTraceEvidence(localResults[0], [
      "validate",
      "discover",
      "read",
      "checkpoint",
      "close",
    ]),
    rest: await operationTraceEvidence(restResult, [
      "validate",
      "discover",
      "read",
      "checkpoint",
      "close",
    ]),
    openapi: await operationTraceEvidence(openApiResult, [
      "validate",
      "discover",
      "read",
      "checkpoint",
      "close",
    ]),
  };
  for (const result of databaseResults) {
    traceResults[result.connectorKey] = await operationTraceEvidence(result, [
      "validate",
      "discover",
      "read",
      "checkpoint",
      "close",
    ]);
  }
  const slowResponse = await page.request.post(
    `${frontendOrigin}/api/knowledge-assets/v1/commands`,
    {
      data: {
        command: "source-golden.connection.create",
        payload: {
          connectorKey: "rest_api",
          displayName: "Timeout fixture",
          scope: "personal",
          configuration: {
            endpoint: `${httpFixture.origin}/slow`,
            operationAllowlist: ["read"],
            timeoutSeconds: 1,
            maxResponseBytes: 1000,
            maxRows: 10,
          },
        },
      },
      headers: {
        "X-Request-ID": "browser-http-timeout",
        "Idempotency-Key": "browser-http-timeout",
      },
    },
  );
  const slowBody = await slowResponse.json();
  const slowCode =
    slowBody.code ?? slowBody.result?.connection?.lastError?.code;
  assert(
    (slowResponse.status() === 422 || slowBody.accepted === false) &&
      typeof slowCode === "string" &&
      slowCode.length > 0,
    "HTTP timeout was not typed",
  );
  report.negativeCases.httpTimeout = {
    status: slowResponse.status(),
    code: slowCode,
  };
  report.context = {
    status: "PASS",
    contextReference: localResults[0].contextReference,
    submittedReference: submittedReferences.find(
      (reference) => reference.revision === localResults[0].golden.id,
    ),
    crossWorkspaceStatus: crossWorkspace.status(),
    forgedReferenceStatus: forged.status(),
    addedThroughVisibleUi: true,
    screenshot: contextScreenshot,
  };

  await page.goto(
    `${frontendOrigin}/?studio=knowledge&file=add_data&step=2&source=mcp_custom`,
    { waitUntil: "networkidle" },
  );
  const profileSelect = page.locator("select:visible").filter({
    has: page.locator('option[value="browser-official-sdk"]'),
  }).first();
  await profileSelect.selectOption("browser-official-sdk");
  await page
    .locator("button:visible", { hasText: "下一步" })
    .first()
    .click();
  await page
    .getByRole("heading", { name: "步骤 4: 命名与保存" })
    .waitFor();
  await page
    .getByText("连接命名", { exact: true })
    .locator("..")
    .locator("input")
    .fill("Browser Official MCP");
  await page.getByText("团队共享库", { exact: true }).click();
  const createResponsePromise = page.waitForResponse((response) =>
    response.request().postData()?.includes("source-golden.connection.create"),
  );
  const ingestResponsePromise = page.waitForResponse((response) =>
    response.request().postData()?.includes("source-golden.ingest"),
  );
  await page
    .locator("button:visible", { hasText: "保存连接" })
    .first()
    .click();
  const [createResponse, ingestResponse] = await Promise.all([
    createResponsePromise,
    ingestResponsePromise,
  ]);
  const createBody = await jsonResponse(createResponse);
  const ingestBody = await jsonResponse(ingestResponse);
  assert(createBody.accepted === true, "MCP create was not accepted");
  assert(ingestBody.accepted === true, "MCP ingest was not accepted");
  await page
    .getByText("真实 MCP 已完成连接、工具发现与 Source/Golden ingest。", {
      exact: true,
    })
    .waitFor();
  const mcpConnection = createBody.result.connection;
  const goldenRevision = ingestBody.result.goldenAssetRevision;
  const mcpTraceEvidence = await operationTraceEvidence(
    {
      connectorKey: "mcp_custom",
      connection: mcpConnection,
    },
    ["validate", "discover", "read", "checkpoint", "close"],
  );
  const mcpProcessTraces = await jsonResponse(
    await page.request.get(
      `${backendOrigin}/__step3b/mcp-process-status/${encodeURIComponent(
        mcpConnection.id,
      )}`,
    ),
  );
  assert(mcpProcessTraces.length >= 2, "MCP process traces were not persisted");
  assert(
    mcpProcessTraces.every(
      (trace) =>
        trace.processReaped === true &&
        trace.status === "succeeded" &&
        !processExists(trace.pid),
    ),
    "an MCP child process was not reaped",
  );
  assert(
    mcpProcessTraces.some(
      (trace) =>
        trace.exchangeMethods.includes("tools/list") &&
        trace.exchangeMethods.includes("initialize"),
    ) &&
      mcpProcessTraces.some((trace) =>
        trace.exchangeMethods.includes("tools/call"),
      ),
    "MCP initialize/tools/list/tools/call transcript is incomplete",
  );
  const mcpScreenshot = resolve(runtimeDirectory, "06-mcp-ingested.png");
  await page.screenshot({ path: mcpScreenshot, fullPage: true });
  report.artifacts.screenshots.push(mcpScreenshot);

  await page.reload({ waitUntil: "networkidle" });
  const refreshedBootstrap = await jsonResponse(
    await page.request.get(
      `${frontendOrigin}/api/knowledge-assets/v1/bootstrap`,
    ),
  );
  assert(
    refreshedBootstrap.connections.some(
      (connection) => connection.id === mcpConnection.id,
    ),
    "connection did not survive browser refresh",
  );
  assert(
    refreshedBootstrap.resources.some(
      (resource) => resource.id === goldenRevision.id,
    ),
    "Golden revision did not survive browser refresh",
  );

  await stopProcess(backend);
  backend = startBackend();
  await waitForUrl(
    `${backendOrigin}/api/knowledge-assets/v1/bootstrap`,
    "restarted Knowledge Asset BFF",
  );
  await page.reload({ waitUntil: "networkidle" });
  const restartedBootstrap = await jsonResponse(
    await page.request.get(
      `${frontendOrigin}/api/knowledge-assets/v1/bootstrap`,
    ),
  );
  const restoredConnection = restartedBootstrap.connections.find(
    (connection) => connection.id === mcpConnection.id,
  );
  const restoredGolden = restartedBootstrap.resources.find(
    (resource) => resource.id === goldenRevision.id,
  );
  assert(restoredConnection, "connection did not survive BFF restart");
  assert(restoredGolden, "Golden revision did not survive BFF restart");
  const allExpectedGoldenIds = [...expectedGoldenIds, goldenRevision.id];
  assert(
    allExpectedGoldenIds.every((id) =>
      restartedBootstrap.resources.some(
        (resource) =>
          resource.id === id || resource.goldenRevisionId === id,
      ),
    ),
    "one or more local/HTTP/MCP Golden revisions did not survive BFF restart",
  );
  const browserConnectionPayload = JSON.stringify(
    restartedBootstrap.connections,
  );
  const browserProfilePayload = JSON.stringify(
    restartedBootstrap.workspaceData.mcpProfileCatalog,
  );
  assert(
    !browserConnectionPayload.includes('"configuration"') &&
      !browserConnectionPayload.includes('"secretRef"') &&
      !browserConnectionPayload.includes('"command"') &&
      !browserConnectionPayload.includes('"cwd"') &&
      !browserConnectionPayload.includes('"env"') &&
      !browserProfilePayload.includes('"command"') &&
      !browserProfilePayload.includes('"cwd"') &&
      !browserProfilePayload.includes('"env"') &&
      !browserProfilePayload.includes('"secretRef"'),
    "browser connection/profile payload leaked an MCP execution or secret field",
  );
  const restartScreenshot = resolve(
    runtimeDirectory,
    "07-after-bff-restart.png",
  );
  await page.screenshot({ path: restartScreenshot, fullPage: true });
  report.artifacts.screenshots.push(restartScreenshot);
  report.mcp = {
    profileId: "browser-official-sdk",
    createAccepted: true,
    ingestAccepted: true,
    connectionId: mcpConnection.id,
    discoveredResources: mcpConnection.discoveredResources,
    sourceRevisionId: ingestBody.result.sourceRevision.id,
    sourceDigest: ingestBody.result.sourceRevision.sourceDigest,
    goldenRevisionId: goldenRevision.id,
    goldenOutputDigest: goldenRevision.storageRef.sha256,
    browserSubmittedExecutionFields: false,
    processTraces: mcpProcessTraces,
    screenshot: mcpScreenshot,
  };
  writeFileSync(
    mcpTranscriptPath,
    `${JSON.stringify(
      {
        schemaVersion: "knowledge-assets.step3b.w1-mcp-transcript.v1",
        connectionId: mcpConnection.id,
        processTraces: mcpProcessTraces,
      },
      null,
      2,
    )}\n`,
  );
  report.operationTraceConsistency = {
    status: "PASS",
    ...traceResults,
    mcp: mcpTraceEvidence,
  };
  report.restartRecovery = {
    browserRefresh: "PASS",
    bffRestart: "PASS",
    connectionId: restoredConnection.id,
    goldenRevisionId: restoredGolden.id,
    restoredGoldenRevisionIds: allExpectedGoldenIds,
    durableDatabase: resolve(
      runtimeDirectory,
      ".veadk/knowledge-assets-step3.sqlite3",
    ),
    durableSourceGoldenDatabase: resolve(
      runtimeDirectory,
      ".veadk/sources-golden/sources-golden.sqlite3",
    ),
    screenshot: restartScreenshot,
  };
  report.status = "PASS";
} catch (error) {
  report.error = sanitized(error?.stack ?? error);
  process.exitCode = 1;
} finally {
  if (page && !page.isClosed()) await page.close();
  if (context) await context.close();
  try {
    if (existsSync(harPath)) {
      report.harConsistency = redactAndVerifyHar();
    }
  } catch (error) {
    report.status = "FAIL";
    report.error = sanitized(error?.stack ?? error);
    process.exitCode = 1;
  }
  if (video) {
    try {
      const generatedVideo = await video.path();
      renameSync(generatedVideo, report.artifacts.video);
    } catch (error) {
      report.videoError = sanitized(error);
    }
  }
  if (browser) await browser.close();
  await stopProcess(vite);
  await stopProcess(backend);
  if (httpFixture) await httpFixture.close();
  writeFileSync(browserLogPath, `${JSON.stringify(browserLogs, null, 2)}\n`);
  writeFileSync(
    serverLogPath,
    processLogs
      .map(
        (entry) =>
          `${entry.at} ${entry.process} ${entry.stream}: ${entry.text.trimEnd()}`,
      )
      .join("\n"),
  );
  report.generatedAt = new Date().toISOString();
  report.browser = browser
    ? { name: "chromium", version: browser.version() }
    : null;
  report.consoleErrors = browserLogs.filter(
    (entry) => entry.type === "error" || entry.type === "pageerror",
  );
  if (report.consoleErrors.length > 0) report.status = "FAIL";
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(
    `${JSON.stringify(
      {
        status: report.status,
        report: reportPath,
        runtimeDirectory,
        connectorCount: report.connectorUiAudit.length,
        mcp: report.mcp,
        restartRecovery: report.restartRecovery,
        error: report.error ?? null,
      },
      null,
      2,
    )}\n`,
  );
}
