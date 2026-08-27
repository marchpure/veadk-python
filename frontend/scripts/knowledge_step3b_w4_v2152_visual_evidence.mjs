#!/usr/bin/env node

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { copyFile, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { inflateSync, deflateSync } from "node:zlib";
import { createServer } from "node:http";

import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = resolve(SCRIPT_DIR, "..");
const REPO_ROOT = resolve(FRONTEND_DIR, "..");
const FIXTURE_PATH = resolve(
  REPO_ROOT,
  "tests/fixtures/knowledge_step3b_w4_v2152/captures.json",
);
const PROTOTYPE_POINTER = "/tmp/knowledge-v2152-latest-dir.txt";
const DEFAULT_OUTPUT_ROOT =
  "/Users/bytedance/.codex/runtime/knowledge-step3b-w4-v2152/visual-evidence";
const TRANSPORT_SCHEMA_VERSION = "knowledge-workspace.transport.v1";
const TRUSTED_HTML_ARTIFACT_NOTE = "Trusted HTML artifact evidence harness";

const VIEWPORTS = [
  { name: "desktop-1920", width: 1920, height: 1080, isMobile: false },
  { name: "studio-1440", width: 1440, height: 900, isMobile: false },
  { name: "mobile-390", width: 390, height: 844, isMobile: true },
];

const TEMPLATE_BY_ROUTE = new Map([
  ["draft_dash_anta", "dashboard"],
  ["pub_sop_bluetooth", "monitoring"],
  ["draft_sop_bluetooth_opt", "sop"],
]);

function parseArgs(argv) {
  const result = {
    outputRoot: process.env.KNOWLEDGE_V2152_EVIDENCE_DIR || DEFAULT_OUTPUT_ROOT,
    prototypeDir: process.env.KNOWLEDGE_V2152_PROTOTYPE_DIR || "",
    referenceDir: process.env.KNOWLEDGE_V2152_REFERENCE_DIR || "",
    reuseReference: process.env.KNOWLEDGE_V2152_REUSE_REFERENCE === "1",
    actualOnly: process.env.KNOWLEDGE_V2152_ACTUAL_ONLY === "1",
    states: null,
    viewports: null,
    keepServer: false,
    prototypeSourceServer: false,
    realBff: process.env.STEP3B_REAL_BFF === "1",
    bffOrigin: process.env.STEP3B_BFF_ORIGIN || "",
    workspace: process.env.STEP3B_WORKSPACE_ID || "workspace-step3",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--keep-server") {
      result.keepServer = true;
      continue;
    }
    if (key === "--prototype-source-server") {
      result.prototypeSourceServer = true;
      continue;
    }
    if (key === "--reuse-reference") {
      result.reuseReference = true;
      continue;
    }
    if (key === "--actual-only") {
      result.actualOnly = true;
      continue;
    }
    if (key === "--states" && value) {
      result.states = value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
        .map((item) => item === "welcome" ? "home" : item);
      index += 1;
      continue;
    }
    if (key === "--viewports" && value) {
      result.viewports = value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
        .map((item) => item === "desktop-1440" ? "studio-1440" : item);
      index += 1;
      continue;
    }
    if (key === "--reference-dir" && value) {
      result.referenceDir = value;
      index += 1;
      continue;
    }
    if (key === "--real-bff") {
      result.realBff = true;
      continue;
    }
    if (key === "--bff-origin" && value) {
      result.bffOrigin = value;
      index += 1;
      continue;
    }
    if (key === "--workspace" && value) {
      result.workspace = value;
      index += 1;
      continue;
    }
    if (key === "--output-root" && value) {
      result.outputRoot = value;
      index += 1;
      continue;
    }
    if (key === "--prototype-dir" && value) {
      result.prototypeDir = value;
      index += 1;
      continue;
    }
    throw new Error(
      "usage: knowledge_step3b_w4_v2152_visual_evidence.mjs " +
        "[--output-root DIR] [--prototype-dir DIR] [--keep-server] " +
        "[--prototype-source-server] [--real-bff --bff-origin URL --workspace ID] " +
        "[--states state-a,state-b] [--viewports desktop-1440,mobile-390] " +
        "[--reference-dir DIR] [--reuse-reference] [--actual-only]",
    );
  }
  if (!result.prototypeDir && existsSync(PROTOTYPE_POINTER)) {
    result.prototypeDir = readFileSync(PROTOTYPE_POINTER, "utf8").trim();
  }
  if (!result.prototypeDir && !result.actualOnly && !result.reuseReference) {
    throw new Error(
      "missing prototype dir; set KNOWLEDGE_V2152_PROTOTYPE_DIR or /tmp/knowledge-v2152-latest-dir.txt",
    );
  }
  if (result.reuseReference && !result.actualOnly && !result.referenceDir) {
    throw new Error(
      "--reuse-reference/--actual-only requires --reference-dir DIR",
    );
  }
  return result;
}

export { VIEWPORTS };

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function mkdirp(path) {
  mkdirSync(path, { recursive: true });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pathnameFor(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return "";
  }
}

function isKnowledgeAssetsApi(url) {
  return pathnameFor(url).startsWith("/api/knowledge-assets/v1/");
}

function isDevServerAuxiliary(url) {
  const pathname = pathnameFor(url);
  return pathname === "/__vite_ping" || pathname === "/@vite/client";
}

function isStaticResourceType(resourceType) {
  return ["document", "script", "stylesheet", "image", "font", "media"].includes(resourceType);
}

function hasProvenNavigationAction(action) {
  return [
    "playwright-navigation:agent-pane-width",
    "page-close-after-capture",
    "prototype-page-close-after-capture",
  ].includes(action);
}

export function classifyFailedRequest(request) {
  const failure = request.failure ?? "";
  const resourceType = request.resourceType ?? "unknown";
  const action = request.action ?? "unknown";
  if (isKnowledgeAssetsApi(request.url)) {
    return {
      ignored: false,
      reason: failure === "net::ERR_ABORTED"
        ? "critical business API aborted"
        : "critical business API request failed",
      request,
    };
  }
  if (failure === "net::ERR_ABORTED" && isDevServerAuxiliary(request.url) && hasProvenNavigationAction(action)) {
    return {
      ignored: true,
      reason: "dev-server navigation abort; non-business auxiliary request; scenario already captured",
      request,
    };
  }
  if (isStaticResourceType(resourceType)) {
    return { ignored: false, reason: "static resource request failed", request };
  }
  return { ignored: false, reason: "request failed", request };
}

function shouldRecordResponseError(response) {
  const status = response.status;
  if (isKnowledgeAssetsApi(response.url)) return status < 200 || status >= 300;
  if (isStaticResourceType(response.resourceType)) return status >= 400;
  return status >= 400;
}

function installPageEvidenceObservers(page, initialAction) {
  let action = initialAction;
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const responseErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    failedRequests.push({
      url: request.url(),
      failure: request.failure()?.errorText ?? "",
      method: request.method(),
      resourceType: request.resourceType(),
      action,
    });
  });
  page.on("response", (response) => {
    const request = response.request();
    const record = {
      url: response.url(),
      status: response.status(),
      statusText: response.statusText(),
      method: request.method(),
      resourceType: request.resourceType(),
      action,
    };
    if (shouldRecordResponseError(record)) responseErrors.push(record);
  });
  return {
    consoleErrors,
    pageErrors,
    failedRequests,
    responseErrors,
    setAction(nextAction) {
      action = nextAction;
    },
  };
}

function createRequiredResponseWaiters(page, state) {
  const waiters = [
    page
      .waitForResponse((response) => response.url().includes("/api/knowledge-assets/v1/bootstrap"), { timeout: 15_000 })
      .then((response) => ({
        name: "bootstrap",
        url: response.url(),
        status: response.status(),
        ok: response.status() >= 200 && response.status() < 300,
      }))
      .catch((error) => ({
        name: "bootstrap",
        url: "/api/knowledge-assets/v1/bootstrap",
        status: 0,
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      })),
  ];
  if (stateNameToRoute(state) !== "welcome") {
    waiters.push(
      page
        .waitForResponse((response) =>
          (response.url().includes("/__w4_v2152_artifacts/") ||
            response.url().includes("/api/knowledge-assets/v1/workspaces/")) &&
          response.url().includes("/artifacts/"),
        { timeout: 15_000 })
        .then((response) => ({
          name: "trusted-html-artifact",
          url: response.url(),
          status: response.status(),
          ok: response.status() >= 200 && response.status() < 300,
        }))
        .catch((error) => ({
          name: "trusted-html-artifact",
          url: "/api/knowledge-assets/v1/workspaces/*/skill-view-revisions/*/artifacts/*",
          status: 0,
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        })),
    );
  }
  return waiters;
}

async function settleRequiredResponses(waiters, responseErrors, action) {
  const results = await Promise.all(waiters);
  for (const result of results) {
    if (!result.ok) {
      responseErrors.push({
        url: result.url,
        status: result.status,
        statusText: result.error ?? "required response was not successful",
        method: "GET",
        resourceType: result.name === "bootstrap" ? "fetch" : "document",
        action,
        required: result.name,
      });
    }
  }
  return results;
}

export function evaluateEvidenceGate(entries, promptHandoff) {
  const failures = [];
  const ignoredRequests = [];
  const unhandledFailedRequests = [];
  let failedRequestsTotal = 0;
  let responseErrorsTotal = 0;
  let consoleErrorsTotal = 0;
  let pageErrorsTotal = 0;
  for (const entry of entries) {
    const label = `${entry.viewport}/${entry.state}`;
    const checks = entry.checks ?? {};
    for (const message of checks.layoutFailures ?? []) failures.push(`${label}: ${message}`);
    for (const message of checks.consoleErrors ?? []) {
      consoleErrorsTotal += 1;
      failures.push(`${label}: console ${message}`);
    }
    for (const message of checks.pageErrors ?? []) {
      pageErrorsTotal += 1;
      failures.push(`${label}: page ${message}`);
    }
    for (const response of checks.responseErrors ?? []) {
      responseErrorsTotal += 1;
      failures.push(`${label}: response ${response.url} HTTP ${response.status} ${response.statusText ?? ""}`.trim());
    }
    for (const request of checks.failedRequests ?? []) {
      failedRequestsTotal += 1;
      const classified = classifyFailedRequest(request);
      if (classified.ignored) {
        ignoredRequests.push({
          ...request,
          reason: classified.reason,
          state: entry.state,
          viewport: entry.viewport,
        });
      } else {
        unhandledFailedRequests.push({
          ...request,
          reason: classified.reason,
          state: entry.state,
          viewport: entry.viewport,
        });
        failures.push(`${label}: ${classified.reason}: ${request.url} ${request.failure}`);
      }
    }
    for (const message of checks.keyboardFailures ?? []) failures.push(`${label}: keyboard ${message}`);
    for (const message of checks.agentPaneFailures ?? []) failures.push(`${label}: agent pane ${message}`);
  }
  if (promptHandoff?.status && promptHandoff.status !== "pass") {
    failures.push(`prompt handoff: ${promptHandoff.status}`);
  }
  return {
    status: failures.length === 0 ? "pass" : "fail",
    failures,
    failedRequestsTotal,
    ignoredRequestsTotal: ignoredRequests.length,
    unhandledFailedRequests,
    ignoredRequests,
    responseErrorsTotal,
    consoleErrorsTotal,
    pageErrorsTotal,
  };
}

async function waitForHttp(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { method: "GET" });
      if (response.ok) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  throw new Error(`server did not become ready at ${url}: ${lastError}`);
}

async function startVite(root, port, apiTarget) {
  const child = spawn(
    process.execPath,
    [resolve(root, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    {
      cwd: root,
      env: {
        ...process.env,
        FORCE_COLOR: "0",
        ...(apiTarget ? { VEADK_API_TARGET: apiTarget } : {}),
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const logs = [];
  child.stdout.on("data", (chunk) => logs.push(chunk.toString()));
  child.stderr.on("data", (chunk) => logs.push(chunk.toString()));
  child.on("exit", (code) => {
    if (code !== null && code !== 0) {
      logs.push(`vite exited with ${code}`);
    }
  });
  await waitForHttp(`http://127.0.0.1:${port}/`, 45_000).catch((error) => {
    child.kill("SIGTERM");
    throw new Error(`${error.message}\n${logs.join("")}`);
  });
  return {
    origin: `http://127.0.0.1:${port}`,
    async close() {
      if (child.exitCode !== null) return;
      child.kill("SIGTERM");
      await Promise.race([once(child, "exit"), sleep(5_000)]);
      if (child.exitCode === null) child.kill("SIGKILL");
    },
  };
}

async function runChild(command, args, options) {
  const child = spawn(command, args, options);
  const logs = [];
  child.stdout?.on("data", (chunk) => logs.push(chunk.toString()));
  child.stderr?.on("data", (chunk) => logs.push(chunk.toString()));
  const [code] = await once(child, "exit");
  if (code !== 0) {
    throw new Error(`${command} ${args.join(" ")} exited ${code}\n${logs.join("")}`);
  }
  return logs.join("");
}

function contentTypeFor(pathname) {
  if (pathname.endsWith(".html")) return "text/html; charset=utf-8";
  if (pathname.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (pathname.endsWith(".css")) return "text/css; charset=utf-8";
  if (pathname.endsWith(".svg")) return "image/svg+xml";
  if (pathname.endsWith(".json")) return "application/json; charset=utf-8";
  if (pathname.endsWith(".ttf")) return "font/ttf";
  if (pathname.endsWith(".woff2")) return "font/woff2";
  if (pathname.endsWith(".png")) return "image/png";
  return "application/octet-stream";
}

async function startStaticServer(root, port) {
  const server = createServer((request, response) => {
    try {
      const parsed = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
      let pathname = decodeURIComponent(parsed.pathname);
      if (pathname === "/") pathname = "/index.html";
      const candidate = resolve(root, `.${pathname}`);
      const normalizedRoot = resolve(root);
      const filePath = candidate.startsWith(normalizedRoot) && existsSync(candidate)
        ? candidate
        : resolve(root, "index.html");
      response.writeHead(200, {
        "content-type": contentTypeFor(filePath),
        "cache-control": "no-store",
      });
      response.end(readFileSync(filePath));
    } catch (error) {
      response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      response.end(error instanceof Error ? error.message : String(error));
    }
  });
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(port, "127.0.0.1", () => {
      server.off("error", rejectListen);
      resolveListen();
    });
  });
  return {
    origin: `http://127.0.0.1:${port}`,
    async close() {
      await new Promise((resolveClose) => server.close(resolveClose));
    },
  };
}

async function startProductionWorkspaceServer(frontendDir, port) {
  const outputDir = resolve(
    "/tmp",
    `knowledge-v2152-w4-production-${process.pid}-${Date.now()}`,
  );
  mkdirp(outputDir);
  await runChild(
    process.execPath,
    [
      resolve(frontendDir, "node_modules/vite/bin/vite.js"),
      "build",
      "--outDir",
      outputDir,
      "--emptyOutDir",
    ],
    {
      cwd: frontendDir,
      env: { ...process.env, FORCE_COLOR: "0" },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const server = await startStaticServer(outputDir, port);
  return {
    origin: server.origin,
    async close() {
      await server.close();
      await rm(outputDir, { recursive: true, force: true });
    },
  };
}

async function startPrototypeServer(prototypeDir, port) {
  const codebase = resolve(prototypeDir, "prototype/codebase");
  if (!existsSync(resolve(codebase, "src/App.tsx"))) {
    return { origin: null, close: async () => {}, skippedReason: "prototype source missing" };
  }
  const tempRoot = resolve(
    "/tmp",
    `knowledge-v2152-prototype-run-${process.pid}-${Date.now()}`,
  );
  mkdirp(tempRoot);
  await copyFile(resolve(codebase, "src/App.tsx"), resolve(tempRoot, "App.tsx"));
  await copyFile(resolve(codebase, "prototype-route.json"), resolve(tempRoot, "prototype-route.json")).catch(() => {});
  await copyRecursive(resolve(codebase, "src"), resolve(tempRoot, "src"));
  writeFileSync(
    resolve(tempRoot, "index.html"),
    [
      "<!doctype html>",
      '<html lang="zh-CN">',
      "<head>",
      '<meta charset="UTF-8" />',
      '<meta name="viewport" content="width=device-width, initial-scale=1.0" />',
      "<title>Prototype v2.15.2</title>",
      "</head>",
      "<body>",
      '<div id="root"></div>',
      '<script type="module" src="/src/main.tsx"></script>',
      "</body>",
      "</html>",
    ].join("\n"),
  );
  writeFileSync(
    resolve(tempRoot, "src/main.tsx"),
    [
      "import React from 'react';",
      "import ReactDOM from 'react-dom/client';",
      "import App from '../App';",
      "import './styles.css';",
      "ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);",
    ].join("\n"),
  );
  writeFileSync(
    resolve(tempRoot, "src/styles.css"),
    [
      '@import "tailwindcss";',
      "html, body, #root { height: 100%; margin: 0; overflow: hidden; }",
      "body { font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; background: #f8fafc; }",
      "* { box-sizing: border-box; }",
      ".custom-scrollbar::-webkit-scrollbar { width: 8px; height: 8px; }",
      ".custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(100,116,139,.3); border-radius: 999px; }",
    ].join("\n"),
  );
  writeFileSync(
    resolve(tempRoot, "package.json"),
    JSON.stringify({ type: "module", dependencies: {} }, null, 2),
  );
  const child = spawn(
    process.execPath,
    [resolve(FRONTEND_DIR, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    {
      cwd: tempRoot,
      env: { ...process.env, NODE_PATH: resolve(FRONTEND_DIR, "node_modules"), FORCE_COLOR: "0" },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const logs = [];
  child.stdout.on("data", (chunk) => logs.push(chunk.toString()));
  child.stderr.on("data", (chunk) => logs.push(chunk.toString()));
  try {
    await waitForHttp(`http://127.0.0.1:${port}/`, 45_000);
    return {
      origin: `http://127.0.0.1:${port}`,
      skippedReason: "",
      async close() {
        if (child.exitCode === null) {
          child.kill("SIGTERM");
          await Promise.race([once(child, "exit"), sleep(5_000)]);
          if (child.exitCode === null) child.kill("SIGKILL");
        }
        await rm(tempRoot, { recursive: true, force: true });
      },
    };
  } catch (error) {
    if (child.exitCode === null) child.kill("SIGTERM");
    await rm(tempRoot, { recursive: true, force: true });
    return {
      origin: null,
      skippedReason: `prototype source server unavailable: ${error.message}\n${logs.join("")}`,
      close: async () => {},
    };
  }
}

async function copyRecursive(source, target) {
  const { cp } = await import("node:fs/promises");
  await cp(source, target, { recursive: true, force: true });
}

function makePng(width, height, rgba) {
  const signature = Buffer.from("\x89PNG\r\n\x1a\n", "binary");
  const chunk = (type, data) => {
    const typeBytes = Buffer.from(type);
    const body = Buffer.concat([typeBytes, data]);
    const header = Buffer.alloc(4);
    header.writeUInt32BE(data.length);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body));
    return Buffer.concat([header, body, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  const rows = [];
  for (let y = 0; y < height; y += 1) {
    rows.push(Buffer.from([0]), rgba.subarray(y * width * 4, (y + 1) * width * 4));
  }
  return Buffer.concat([
    signature,
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function crc32(content) {
  let crc = 0xffffffff;
  for (const byte of content) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function decodePng(content) {
  const signature = Buffer.from("\x89PNG\r\n\x1a\n", "binary");
  if (!content.subarray(0, 8).equals(signature)) throw new Error("not a png");
  let offset = 8;
  let width = 0;
  let height = 0;
  let colorType = 0;
  let bitDepth = 0;
  const compressed = [];
  while (offset < content.length) {
    const length = content.readUInt32BE(offset);
    const type = content.toString("ascii", offset + 4, offset + 8);
    const data = content.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
    }
    if (type === "IDAT") compressed.push(data);
    if (type === "IEND") break;
    offset += 12 + length;
  }
  if (!width || !height || bitDepth !== 8 || ![2, 6].includes(colorType)) {
    throw new Error("unsupported png");
  }
  const channels = colorType === 2 ? 3 : 4;
  const rowBytes = width * channels;
  const inflated = inflateSync(Buffer.concat(compressed));
  const decoded = Buffer.alloc(width * height * channels);
  let sourceOffset = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[sourceOffset];
    sourceOffset += 1;
    for (let x = 0; x < rowBytes; x += 1) {
      const raw = inflated[sourceOffset + x];
      const left = x >= channels ? decoded[y * rowBytes + x - channels] : 0;
      const above = y > 0 ? decoded[(y - 1) * rowBytes + x] : 0;
      const upperLeft = y > 0 && x >= channels ? decoded[(y - 1) * rowBytes + x - channels] : 0;
      let reconstructed = raw;
      if (filter === 1) reconstructed += left;
      if (filter === 2) reconstructed += above;
      if (filter === 3) reconstructed += Math.floor((left + above) / 2);
      if (filter === 4) {
        const prediction = left + above - upperLeft;
        const pa = Math.abs(prediction - left);
        const pb = Math.abs(prediction - above);
        const pc = Math.abs(prediction - upperLeft);
        reconstructed += pa <= pb && pa <= pc ? left : pb <= pc ? above : upperLeft;
      }
      decoded[y * rowBytes + x] = reconstructed & 0xff;
    }
    sourceOffset += rowBytes;
  }
  const rgba = Buffer.alloc(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    rgba[pixel * 4] = decoded[pixel * channels];
    rgba[pixel * 4 + 1] = decoded[pixel * channels + 1];
    rgba[pixel * 4 + 2] = decoded[pixel * channels + 2];
    rgba[pixel * 4 + 3] = channels === 4 ? decoded[pixel * channels + 3] : 255;
  }
  return { width, height, rgba };
}

function nearestResizePng(source, targetWidth, targetHeight) {
  const decoded = decodePng(source);
  if (decoded.width === targetWidth && decoded.height === targetHeight) return source;
  const out = Buffer.alloc(targetWidth * targetHeight * 4);
  for (let y = 0; y < targetHeight; y += 1) {
    const sourceY = Math.min(decoded.height - 1, Math.floor((y / targetHeight) * decoded.height));
    for (let x = 0; x < targetWidth; x += 1) {
      const sourceX = Math.min(decoded.width - 1, Math.floor((x / targetWidth) * decoded.width));
      const sourceOffset = (sourceY * decoded.width + sourceX) * 4;
      const targetOffset = (y * targetWidth + x) * 4;
      decoded.rgba.copy(out, targetOffset, sourceOffset, sourceOffset + 4);
    }
  }
  return makePng(targetWidth, targetHeight, out);
}

function createDiffArtifacts(reference, actual) {
  const left = decodePng(reference);
  const right = decodePng(actual);
  const width = Math.min(left.width, right.width);
  const height = Math.min(left.height, right.height);
  const overlay = Buffer.alloc(width * height * 4);
  let mismatched = 0;
  let compared = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const leftOffset = (y * left.width + x) * 4;
      const rightOffset = (y * right.width + x) * 4;
      const outOffset = (y * width + x) * 4;
      const delta =
        Math.abs(left.rgba[leftOffset] - right.rgba[rightOffset]) +
        Math.abs(left.rgba[leftOffset + 1] - right.rgba[rightOffset + 1]) +
        Math.abs(left.rgba[leftOffset + 2] - right.rgba[rightOffset + 2]);
      compared += 1;
      if (delta > 24) mismatched += 1;
      overlay[outOffset] = delta > 24 ? 255 : Math.floor((left.rgba[leftOffset] + right.rgba[rightOffset]) / 2);
      overlay[outOffset + 1] = delta > 24 ? 48 : Math.floor((left.rgba[leftOffset + 1] + right.rgba[rightOffset + 1]) / 2);
      overlay[outOffset + 2] = delta > 24 ? 48 : Math.floor((left.rgba[leftOffset + 2] + right.rgba[rightOffset + 2]) / 2);
      overlay[outOffset + 3] = 255;
    }
  }
  return {
    mismatchRatio: compared ? mismatched / compared : 1,
    overlayPng: makePng(width, height, overlay),
    dimensionsEqual: left.width === right.width && left.height === right.height,
  };
}

function stateNameToRoute(state) {
  return new URL(`http://local${state.stateUrl}`).searchParams.get("file") || "welcome";
}

function resourceKindForRoute(routeId) {
  if (routeId === "welcome") return "golden_asset";
  if (routeId === "pub_sop_bluetooth") return "skill";
  if (routeId.startsWith("draft_")) return "skill_draft";
  return "golden_asset";
}

function subtypeForRoute(routeId) {
  if (routeId.includes("dash")) return "dashboard";
  if (routeId.includes("opt")) return "sop";
  if (routeId.includes("pub")) return "monitoring";
  if (routeId.includes("sop")) return "sop";
  return "knowledge";
}

function displayNameForRoute(routeId) {
  const names = {
    welcome: "Workspace home",
    draft_sop_bluetooth: "SOP Skill draft",
    draft_dash_anta: "Dashboard Skill draft",
    draft_sop_haidilao: "Service SOP Skill draft",
    pub_sop_bluetooth: "Published Skill monitoring",
    draft_sop_bluetooth_opt: "Optimized SOP Skill revision",
  };
  return names[routeId] || routeId.replaceAll("_", " ");
}

function sourceRef(id, kind = "golden_asset") {
  return {
    kind,
    object_id: id,
    revision: `${id}:rev-1`,
    scope: id.startsWith("team") ? "team" : "personal",
  };
}

function templateForState(state) {
  const routeId = stateNameToRoute(state);
  return TEMPLATE_BY_ROUTE.get(routeId) || subtypeForRoute(routeId);
}

function safeHtmlForState(state) {
  const routeId = stateNameToRoute(state);
  const template = templateForState(state);
  const runState = new URL(`http://local${state.stateUrl}`).searchParams.get("run_state");
  const title = displayNameForRoute(routeId);
  const statusText = runState === "input"
    ? "等待真实试运行输入"
    : runState === "result"
    ? "服务端 Runner 返回 immutable ViewRevision"
    : "正在编辑可信 HTML Skill";
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  :host, body { margin: 0; font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #0f172a; background: #fff; }
  .kw-artifact { min-height: 620px; padding: 24px; background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); }
  .kw-hero { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; padding:18px; border:1px solid #e2e8f0; border-radius:20px; background:#fff; box-shadow:0 14px 38px rgba(15,23,42,.08); }
  .kw-title { margin:0; font-size:24px; line-height:1.2; font-weight:700; letter-spacing:-.02em; }
  .kw-meta { margin-top:8px; color:#64748b; font-size:13px; line-height:1.6; }
  .kw-toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
  .kw-btn, select.kw-btn { border:1px solid #cbd5e1; border-radius:10px; background:#fff; color:#334155; padding:8px 10px; font-size:12px; font-weight:650; }
  .kw-grid { margin-top:18px; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
  .kw-card { min-height:132px; border:1px solid #e2e8f0; border-radius:18px; background:#fff; padding:16px; box-shadow:0 8px 24px rgba(15,23,42,.06); }
  .kw-card h3 { margin:0 0 10px; font-size:14px; color:#0f172a; }
  .kw-card p, .kw-card li { color:#64748b; font-size:12px; line-height:1.7; }
  .kw-stage { margin-top:18px; display:grid; grid-template-columns:1.1fr .9fr; gap:14px; }
  .kw-list { margin:0; padding-left:18px; }
  .kw-pill { display:inline-flex; align-items:center; border-radius:999px; padding:4px 8px; background:#eff6ff; color:#1d4ed8; font-size:11px; font-weight:700; }
  @media (max-width: 720px) {
    .kw-artifact { padding: 14px; }
    .kw-hero, .kw-stage { display:block; }
    .kw-toolbar { margin-top:12px; }
    .kw-grid { grid-template-columns:1fr; }
  }
</style>
</head>
<body>
  <main class="kw-artifact" data-template="${template}" data-route="${routeId}">
    <section class="kw-hero">
      <div>
        <span class="kw-pill">${template} · Skill visualization</span>
        <h1 class="kw-title">${title}</h1>
        <p class="kw-meta">${statusText}。本证据 HTML 来自测试专用 typed ViewRevision；生产组件不会根据 routeId 生成业务事实。</p>
      </div>
      <div class="kw-toolbar" aria-label="artifact actions">
        <select class="kw-btn" data-artifact-event="filter.change" data-element-id="scope-filter" data-field="scope">
          <option value="current">当前范围</option>
          <option value="team">团队范围</option>
        </select>
        <button class="kw-btn" data-artifact-event="drill.request" data-element-id="primary-card" data-value="details">钻取</button>
        <button class="kw-btn" data-artifact-event="refresh.request" data-element-id="revision" data-value="manual">刷新</button>
        <button class="kw-btn" data-artifact-event="export.request" data-element-id="artifact" data-format="html">导出</button>
        <button class="kw-btn" data-artifact-event="context.reference" data-element-id="artifact-root" data-value="${routeId}">加入上下文</button>
      </div>
    </section>
    <section class="kw-grid">
      <article class="kw-card"><h3>输入材料</h3><p>来自 bootstrap 的 typed resource refs；固定 revision 后交给 Agent。</p></article>
      <article class="kw-card"><h3>执行状态</h3><p>${statusText}</p></article>
      <article class="kw-card"><h3>视图类型</h3><p>Dashboard、Semantic、SOP、Knowledge、Graph、Monitoring 都作为 Skill HTML revision 呈现。</p></article>
    </section>
    <section class="kw-stage">
      <article class="kw-card">
        <h3>主视图</h3>
        <ul class="kw-list">
          <li>可信 HTML artifact 通过 digest 校验后渲染。</li>
          <li>筛选、钻取、刷新、导出只发 typed command 或 gated event。</li>
          <li>无服务端数据时显示 empty / loading / gated / error。</li>
        </ul>
      </article>
      <article class="kw-card">
        <h3>审计</h3>
        <p>Manifest、BuildPlan、traceId、revisionId 进入高级详情，不作为普通用户编辑流水线。</p>
      </article>
    </section>
  </main>
</body>
</html>`;
}

function revisionForState(state, origin) {
  const routeId = stateNameToRoute(state);
  if (routeId === "welcome") return null;
  const html = safeHtmlForState(state);
  const bytes = Buffer.byteLength(html, "utf8");
  const template = templateForState(state);
  return {
    id: `vr-${routeId}`,
    skillRevisionId: `${routeId}:1`,
    skill_revision_id: `${routeId}:1`,
    revision: 1,
    manifest: {
      id: `manifest-${routeId}`,
      skillRevisionId: `${routeId}:1`,
      rendererRef: "trusted-html-renderer",
      viewModelSchemaRef: {
        uri: `schema://w4/${template}`,
        version: "v2.15.2",
        sha256: "0".repeat(64),
      },
      cspProfile: "trusted-renderer-v1",
    },
    intent: {
      id: `intent-${routeId}`,
      skillId: routeId,
      skillRevision: 1,
      template,
      purpose: template === "monitoring" ? "monitor" : template === "graph_ontology" ? "explore" : "overview",
      resultRef: `artifact-${routeId}`,
    },
    viewModel: {
      template,
      title: displayNameForRoute(routeId),
      dataRef: {
        uri: `${origin}/__w4_v2152_artifacts/${routeId}.json`,
        kind: "object",
        sha256: "1".repeat(64),
        mediaType: "application/json",
        bytes: 2,
      },
      kpis: [
        { key: "read_model", label: "Read model", value: "typed", trend: "unknown" },
      ],
      fields: [{ name: "scope", label: "Scope" }],
      values: [["accepted", 1]],
    },
    resultRef: {
      uri: `${origin}/__w4_v2152_artifacts/${routeId}.html`,
      kind: "object",
      sha256: sha256(Buffer.from(html, "utf8")),
      mediaType: "text/html",
      bytes,
    },
    createdAt: "2026-08-25T00:00:00.000Z",
  };
}

function createResource(routeId, overrides = {}) {
  const kind = resourceKindForRoute(routeId);
  const subtype = subtypeForRoute(routeId);
  return {
    id: routeId,
    resourceId: routeId,
    displayName: displayNameForRoute(routeId),
    name: displayNameForRoute(routeId),
    resourceKind: kind,
    subtype,
    space: routeId === "pub_sop_bluetooth" ? "team" : "personal",
    lifecycle: kind === "skill_draft" ? "draft" : "ready",
    version: "v2.15.2",
    revision: 1,
    permission: true,
    draftId: kind === "skill_draft" ? routeId : null,
    viewRevisionId: `vr-${routeId}`,
    traceId: `op-${routeId}`,
    contextRef: sourceRef(routeId, kind === "skill" ? "skill" : "artifact"),
    authoringSession: {
      prompt: `Build ${displayNameForRoute(routeId)} from selected workspace resources`,
      template: subtype,
      scope: routeId === "pub_sop_bluetooth" ? "team" : "personal",
      resourceRefs: [sourceRef("ga-orders")],
    },
    ...overrides,
  };
}

function bootstrapForState(state, origin) {
  const routeId = stateNameToRoute(state);
  const skillRoutes = [
    "draft_sop_bluetooth",
    "draft_dash_anta",
    "draft_sop_haidilao",
    "pub_sop_bluetooth",
    "draft_sop_bluetooth_opt",
  ];
  const resources = [
    {
      id: "ga-orders",
      resourceId: "ga-orders",
      displayName: "Workspace dataset revision",
      name: "Workspace dataset revision",
      resourceKind: "golden_asset",
      subtype: "dataset",
      space: "personal",
      lifecycle: "ready",
      version: "rev-1",
      revision: 1,
      assetId: "asset-orders",
      goldenRevisionId: "ga-orders:rev-1",
      permission: true,
      contextRef: sourceRef("ga-orders"),
    },
    {
      id: "doc-playbook",
      resourceId: "doc-playbook",
      displayName: "Workspace document revision",
      name: "Workspace document revision",
      resourceKind: "golden_asset",
      subtype: "knowledge",
      space: "team",
      lifecycle: "ready",
      version: "rev-2",
      revision: 2,
      assetId: "asset-doc",
      goldenRevisionId: "doc-playbook:rev-2",
      permission: true,
      contextRef: sourceRef("doc-playbook", "knowledge"),
    },
    ...skillRoutes.map((id) => createResource(id)),
  ];
  const revision = revisionForState(state, origin);
  return {
    resources,
    connections: [
      {
        id: "conn-mcp",
        workspaceId: "w4-v2152",
        connectorKey: "mcp",
        displayName: "MCP workspace connector",
        scope: "personal",
        ownerId: "user",
        status: "ready",
        syncMode: "realtime",
        createdAt: "2026-08-25T00:00:00.000Z",
        updatedAt: "2026-08-25T00:00:00.000Z",
        lastSuccessAt: "2026-08-25T00:00:00.000Z",
        discoveredResources: [],
        discoveredTools: [],
        goldenRevisionIds: ["ga-orders:rev-1"],
        isTeam: false,
      },
    ],
    publications: [
      {
        skillId: "pub_sop_bluetooth",
        resourceId: "pub_sop_bluetooth",
        version: "v2.15.2",
        qualityScore: "server-read-model",
        invocationCount: "server-read-model",
        freshness: "server-read-model",
      },
    ],
    routes: ["welcome", "skill_builder", "add_data", "upload_doc", "add_kb", "data_overview", "evaluation_detail", ...skillRoutes],
    workspaceData: {
      connectorCatalog: [
        {
          connectorKey: "mcp",
          category: "runtime",
          name: "MCP",
          desc: "Server provided MCP connector",
          capabilities: ["discover", "invoke"],
          inputSchema: { endpoint: "string" },
          credentialSchema: null,
          discoveryPipeline: ["validate", "discover"],
          syncModes: ["realtime"],
        },
      ],
      mcpProfileCatalog: [
        {
          profileId: "mcp-default",
          label: "Default MCP profile",
          transport: "stdio",
          toolAllowlist: ["query", "invoke"],
        },
      ],
      datasetFields: [
        { name: "dimension", type: "string", desc: "typed field from read model" },
        { name: "value", type: "number", desc: "typed field from read model" },
      ],
      dashboard: {
        kpis: [],
        trendData: [],
      },
      knowledgeGraph: {
        entities: [],
        mappings: [],
      },
      skillViewRevision: revision,
    },
    actionLoop: {
      signals: [],
      policies: [],
      todos: [],
      reviews: [],
      briefs: [],
    },
    access: {
      spaceId: "w4-v2152",
      role: "owner",
      capabilities: ["read", "command", "stream"],
    },
    serverTime: "2026-08-25T00:00:00.000Z",
  };
}

function commandResponse(commandName, requestId) {
  const operationId = `op-${commandName.replaceAll(".", "-")}`;
  if (commandName === "skill-authoring.start") {
    return {
      accepted: true,
      requestId,
      operationId,
      result: {
        resultType: "skill-authoring.start",
        status: "ready_for_execution",
        operation: {
          operation_id: operationId,
          status: "ready_for_execution",
          trace_id: `trace-${operationId}`,
          plan: { plan_id: "plan-w4", intent: "analysis", purpose: "generate skill", nodes: [], outputs: [], kind_spec: { kind: "analysis", question: "from typed command", queryPlanRef: "qp" }, plan_digest: "digest" },
          summary: "Typed Agent command accepted.",
        },
        draft: {
          draft_id: "draft-from-command",
          revision: 1,
          scope: "personal",
          prompt: "from typed command",
        },
      },
    };
  }
  if (commandName === "skill-authoring.execute") {
    return {
      accepted: true,
      requestId,
      operationId,
      result: {
        resultType: "skill-authoring.execute",
        status: "succeeded",
        operation: {
          operation_id: operationId,
          status: "succeeded",
          trace_id: `trace-${operationId}`,
          summary: "Execution produced immutable ViewRevision.",
          artifact_result: { revision_id: "vr-draft-from-command" },
        },
        draft: {
          draft_id: "draft-from-command",
          revision: 2,
          scope: "personal",
        },
      },
    };
  }
  return {
    accepted: true,
    requestId,
    operationId,
    result: {
      resultType: commandName,
      status: "succeeded",
      operation: {
        operation_id: operationId,
        status: "succeeded",
        trace_id: `trace-${operationId}`,
      },
    },
  };
}

function sseForCommand(commandName) {
  const now = "2026-08-25T00:00:00.000Z";
  const streamId = `stream-${commandName.replaceAll(".", "-")}`;
  const events = [
    {
      schema_version: TRANSPORT_SCHEMA_VERSION,
      stream_id: streamId,
      event_id: `${streamId}-1`,
      sequence: 1,
      occurred_at: now,
      type: "assistant.delta",
      payload: { delta: "收到真实 command，正在读取上下文。", status: "streaming" },
      terminal: false,
    },
    {
      schema_version: TRANSPORT_SCHEMA_VERSION,
      stream_id: streamId,
      event_id: `${streamId}-2`,
      sequence: 2,
      occurred_at: now,
      type: "tool_call",
      payload: { name: "workspace.read_model", status: "succeeded", elapsed_ms: 31, summary: "Loaded typed bootstrap resources." },
      terminal: false,
    },
    {
      schema_version: TRANSPORT_SCHEMA_VERSION,
      stream_id: streamId,
      event_id: `${streamId}-3`,
      sequence: 3,
      occurred_at: now,
      type: "context.revision",
      payload: { revision_id: "vr-streamed", status: "ready", summary: "ViewRevision available from server event." },
      terminal: false,
    },
    {
      schema_version: TRANSPORT_SCHEMA_VERSION,
      stream_id: streamId,
      event_id: `${streamId}-4`,
      sequence: 4,
      occurred_at: now,
      type: "warning",
      payload: { code: "redacted", message: "Sensitive tool output is redacted." },
      terminal: false,
    },
    {
      schema_version: TRANSPORT_SCHEMA_VERSION,
      stream_id: streamId,
      event_id: `${streamId}-5`,
      sequence: 5,
      occurred_at: now,
      type: "terminal",
      payload: { status: "succeeded" },
      terminal: true,
    },
  ];
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

async function routeW4Api(page, state, origin) {
  await page.route("**/api/knowledge-assets/v1/bootstrap", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(bootstrapForState(state, origin)),
    });
  });
  await page.route("**/api/knowledge-assets/v1/commands", async (route) => {
    const request = route.request();
    let commandName = "unknown";
    try {
      commandName = JSON.parse(request.postData() || "{}").command || "unknown";
    } catch {
      commandName = "unknown";
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(commandResponse(commandName, request.headers()["x-request-id"] || `req-${Date.now()}`)),
    });
  });
  await page.route("**/api/knowledge-assets/v1/streams", async (route) => {
    let commandName = "assistant.turn";
    try {
      commandName = JSON.parse(route.request().postData() || "{}").command || commandName;
    } catch {
      commandName = "assistant.turn";
    }
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        "x-stream-id": `stream-${commandName.replaceAll(".", "-")}`,
      },
      body: sseForCommand(commandName),
    });
  });
  await page.route("**/__w4_v2152_artifacts/*.html", async (route) => {
    const routeId = route.request().url().split("/").pop().replace(/\.html$/, "");
    const html = safeHtmlForState({ stateUrl: `/?file=${routeId}` });
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "content-length": String(Buffer.byteLength(html, "utf8")),
      },
      body: html,
    });
  });
  await page.route("**/__w4_v2152_artifacts/*.json", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{}",
    });
  });
  await page.route("**/api/knowledge-domains/v1/**", async (route) => {
    await route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({
        code: "UNAVAILABLE",
        message: "test harness: domain command seam not implemented",
        retryable: true,
        requestId: "w4-visual-domain",
      }),
    });
  });
}

async function capturePrototypeReference(browser, state, viewport, prototypeCapture, outputDir, prototypeOrigin) {
  mkdirp(outputDir);
  const referencePath = join(outputDir, "reference.png");
  const consoleErrors = [];
  const failedRequests = [];
  if (prototypeOrigin) {
    const page = await browser.newPage({
      viewport: { width: viewport.width, height: viewport.height },
      isMobile: viewport.isMobile,
      deviceScaleFactor: 1,
      locale: "zh-CN",
      colorScheme: "light",
    });
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      failedRequests.push({ url: request.url(), failure: request.failure()?.errorText ?? "" });
    });
    try {
      await page.goto(`${prototypeOrigin}${state.stateUrl}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.waitForSelector("body", { timeout: 15_000 });
      await sleep(300);
      await page.screenshot({ path: referencePath, fullPage: false });
      const summary = await collectDomAndLayoutSummary(page);
      await page.close();
      return {
        source: "prototype-source",
        path: referencePath,
        sha256: sha256(readFileSync(referencePath)),
        consoleErrors,
        failedRequests,
        dom: summary,
        metadata: { sourceUrl: `${prototypeOrigin}${state.stateUrl}` },
      };
    } catch (error) {
      consoleErrors.push(`prototype-source fallback: ${error.message}`);
      await page.close();
    }
  }
  const imageResponse = await fetch(prototypeCapture.tosUrl);
  if (!imageResponse.ok) {
    throw new Error(`failed to fetch prototype capture ${prototypeCapture.tosUrl}: HTTP ${imageResponse.status}`);
  }
  const sourceBuffer = Buffer.from(await imageResponse.arrayBuffer());
  const reference = nearestResizePng(sourceBuffer, viewport.width, viewport.height);
  writeFileSync(referencePath, reference);
  return {
    source: "captures-json-tos-png",
    path: referencePath,
    sha256: sha256(reference),
    consoleErrors,
    failedRequests,
    dom: { fallback: "reference derived from captures.json TOS PNG", stateUrl: state.stateUrl },
    metadata: { sourceUrl: prototypeCapture.tosUrl },
  };
}

function referenceCachePaths(referenceDir, state, viewport) {
  const root = join(resolve(referenceDir), viewport.name, state.name);
  return {
    root,
    image: join(root, "reference.png"),
    metadata: join(root, "reference.json"),
  };
}

function readCachedReference(referenceDir, state, viewport) {
  const paths = referenceCachePaths(referenceDir, state, viewport);
  if (!existsSync(paths.image) || !existsSync(paths.metadata)) {
    throw new Error(
      `reference cache missing for ${state.name}/${viewport.name}: ${paths.root}`,
    );
  }
  const metadata = JSON.parse(readFileSync(paths.metadata, "utf8"));
  const image = readFileSync(paths.image);
  const digest = sha256(image);
  if (metadata.state !== state.name ||
      metadata.viewport !== viewport.name ||
      metadata.stateUrl !== state.stateUrl ||
      metadata.sha256 !== digest) {
    throw new Error(
      `reference cache metadata/SHA mismatch for ${state.name}/${viewport.name}`,
    );
  }
  const dimensions = decodePng(image);
  if (dimensions.width !== viewport.width || dimensions.height !== viewport.height) {
    throw new Error(
      `reference cache dimensions mismatch for ${state.name}/${viewport.name}`,
    );
  }
  return {
    source: "reference-cache",
    path: paths.image,
    sha256: digest,
    consoleErrors: [],
    failedRequests: [],
    dom: { cached: true, stateUrl: state.stateUrl },
    metadata,
  };
}

function persistReferenceCache(referenceDir, state, viewport, reference) {
  if (!referenceDir) return;
  const paths = referenceCachePaths(referenceDir, state, viewport);
  mkdirp(paths.root);
  const image = readFileSync(reference.path);
  const digest = sha256(image);
  const metadata = {
    schemaVersion: "step3b.prototype-reference-cache.v1",
    state: state.name,
    stateUrl: state.stateUrl,
    viewport: viewport.name,
    dimensions: { width: viewport.width, height: viewport.height },
    source: reference.source,
    sourceUrl: reference.metadata?.sourceUrl ?? null,
    capturedAt: new Date().toISOString(),
    sha256: digest,
  };
  writeFileSync(paths.image, image);
  writeFileSync(paths.metadata, `${JSON.stringify(metadata, null, 2)}\n`);
  return { ...reference, sha256: digest, metadata };
}

async function waitForRendered(page, state) {
  await page.waitForSelector(".knowledge-workspace-host", { timeout: 15_000 });
  const routeId = stateNameToRoute(state);
  if (routeId === "welcome") {
    await page.waitForFunction(() => document.body.innerText.includes("今天想解决什么业务问题"), null, { timeout: 15_000 }).catch(() => undefined);
    return;
  }
  await page.waitForFunction(() => {
    const host = document.querySelector(".trusted-artifact-host");
    const shadowText = host?.shadowRoot?.textContent ?? "";
    return shadowText.length > 40 || document.body.innerText.includes("等待服务端返回") || document.body.innerText.includes("无法展示");
  }, null, { timeout: 15_000 }).catch(() => undefined);
}

async function resolveRealStateUrl(page, state, origin) {
  const url = new URL(state.stateUrl, origin);
  if (state.routeId === "welcome") return url;
  const response = await page.request.get(
    `${origin}/api/knowledge-assets/v1/bootstrap`,
  );
  if (!response.ok()) {
    throw new Error(`real bootstrap failed while resolving ${state.name}: HTTP ${response.status()}`);
  }
  const body = await response.json();
  const resources = Array.isArray(body.resources) ? body.resources : [];
  const drafts = resources.filter((item) => item.resourceKind === "skill_draft");
  const published = resources.filter((item) => item.resourceKind === "published_skill");
  let resource;
  if (state.name.startsWith("bluetooth-sop") || state.name === "edit-sop-step" || state.name === "publish-to-agent") {
    resource = drafts.find((item) => /蓝牙断连排查/.test(String(item.displayName ?? item.name ?? "")));
  } else if (state.name.startsWith("anta-dashboard") || state.name === "publish-team") {
    resource = drafts.find((item) => item.subtype === "dashboard");
  } else if (state.name.startsWith("haidilao-sop")) {
    resource = drafts.find((item) => /门店卫生巡检/.test(String(item.displayName ?? item.name ?? "")));
  } else if (state.name === "published-sop-monitoring") {
    resource = published[0];
  } else if (state.name === "optimization-draft") {
    resource = drafts.find((item) => /优化草稿/.test(String(item.displayName ?? item.name ?? "")));
  }
  if (!resource?.id) {
    throw new Error(`real bootstrap has no dynamic resource for ${state.name}`);
  }
  url.searchParams.set("file", String(resource.id));
  const viewRevisionId = resource.viewRevisionId ?? resource.skillViewRevision?.id;
  if (viewRevisionId) url.searchParams.set("view_revision_id", String(viewRevisionId));
  return url;
}

async function collectDomAndLayoutSummary(page) {
  return await page.evaluate(() => {
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const boxFor = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };
    };
    const text = document.body.innerText.replace(/\s+/g, " ").slice(0, 1600);
    const interactive = Array.from(document.querySelectorAll("button, input, textarea, select, [role='button'], [tabindex]"))
      .slice(0, 80)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: element.textContent?.replace(/\s+/g, " ").trim().slice(0, 80) ?? "",
        ariaLabel: element.getAttribute("aria-label"),
        disabled: element.hasAttribute("disabled") || element.getAttribute("aria-disabled") === "true",
      }));
    const dialogs = Array.from(document.querySelectorAll("[role='dialog'], [aria-modal='true']"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          label: element.getAttribute("aria-label") || element.getAttribute("aria-labelledby") || "",
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      });
    return {
      title: document.title,
      viewport,
      text,
      nodeCount: document.querySelectorAll("*").length,
      shell: boxFor("[data-kw-shell='desktop']") || boxFor("[data-kw-shell='mobile']") || boxFor("#root"),
      leftNav: boxFor("[data-kw-region='left-nav']"),
      main: boxFor("[data-kw-region='main']"),
      agent: boxFor("[data-kw-region='agent']"),
      header: boxFor("header"),
      dialogs,
      interactive,
      horizontalOverflowPx: Math.max(0, document.documentElement.scrollWidth - window.innerWidth, document.body.scrollWidth - window.innerWidth),
      verticalOverflowPx: Math.max(0, document.documentElement.scrollHeight - window.innerHeight, document.body.scrollHeight - window.innerHeight),
    };
  });
}

async function collectKeyboardEvidence(page) {
  const steps = [];
  const failures = [];
  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press("Tab");
    steps.push(await page.evaluate(() => {
      const active = document.activeElement;
      return {
        tag: active?.tagName?.toLowerCase() ?? "",
        text: active?.textContent?.replace(/\s+/g, " ").trim().slice(0, 80) ?? "",
        ariaLabel: active?.getAttribute("aria-label") ?? "",
        id: active?.id ?? "",
      };
    }));
  }
  if (!steps.some((step) => step.tag === "button" || step.tag === "textarea" || step.tag === "input" || step.tag === "select")) {
    failures.push("no keyboard-focusable controls reached");
  }
  return { steps, failures };
}

async function collectAgentPaneWidthEvidence(browser, localOrigin, state, viewport) {
  if (viewport.isMobile) {
    return {
      skipped: "mobile uses overlay assistant drawer",
      collapsed: null,
      expanded: null,
      failures: [],
      consoleErrors: [],
      pageErrors: [],
      failedRequests: [],
      responseErrors: [],
    };
  }
  const url = new URL(state.stateUrl, localOrigin);
  url.searchParams.set("studio", "knowledge");
  url.searchParams.set("pane", "closed");
  const openPanePage = async (paneState) => {
    const page = await browser.newPage({
      viewport: { width: viewport.width, height: viewport.height },
      isMobile: viewport.isMobile,
      deviceScaleFactor: 1,
      locale: "zh-CN",
      colorScheme: "light",
    });
    const observed = installPageEvidenceObservers(page, "playwright-navigation:agent-pane-width");
    const paneUrl = new URL(state.stateUrl, localOrigin);
    paneUrl.searchParams.set("studio", "knowledge");
    paneUrl.searchParams.set("pane", paneState);
    // Width probing isolates the shell toggle. A clarification state carries
    // chat=clarify, which intentionally forces the assistant open in the
    // product journey; leaving it here would make the "closed" sample open.
    paneUrl.searchParams.delete("chat");
    const waiters = createRequiredResponseWaiters(page, state);
    await page.goto(paneUrl.toString(), { waitUntil: "networkidle", timeout: 30_000 });
    await settleRequiredResponses(waiters, observed.responseErrors, "playwright-navigation:agent-pane-width");
    await waitForRendered(page, state);
    const summary = await collectDomAndLayoutSummary(page);
    observed.setAction("page-close-after-capture");
    await page.close();
    return { summary, observed };
  };
  const closedCapture = await openPanePage("closed");
  const collapsed = closedCapture.summary;
  url.searchParams.set("pane", "open");
  const openCapture = await openPanePage("open");
  const expanded = openCapture.summary;
  const failures = [];
  if (collapsed.horizontalOverflowPx > 0 || expanded.horizontalOverflowPx > 0) {
    failures.push("horizontal overflow when toggling agent pane");
  }
  const collapsedWidth = collapsed.main?.width ?? 0;
  const expandedWidth = expanded.main?.width ?? 0;
  if (expandedWidth > 0 && collapsedWidth > 0 && expandedWidth >= collapsedWidth) {
    failures.push("main area did not shrink when agent pane opened");
  }
  return {
    collapsed: collapsed.main,
    expanded: expanded.main,
    failures,
    consoleErrors: [
      ...closedCapture.observed.consoleErrors,
      ...openCapture.observed.consoleErrors,
    ],
    pageErrors: [
      ...closedCapture.observed.pageErrors,
      ...openCapture.observed.pageErrors,
    ],
    failedRequests: [
      ...closedCapture.observed.failedRequests,
      ...openCapture.observed.failedRequests,
    ],
    responseErrors: [
      ...closedCapture.observed.responseErrors,
      ...openCapture.observed.responseErrors,
    ],
  };
}

function analyzeLayout(summary, state, viewport) {
  const failures = [];
  if (summary.horizontalOverflowPx > 0) {
    failures.push(`horizontal overflow ${summary.horizontalOverflowPx}px`);
  }
  if (!summary.text || summary.text.length < 40) {
    failures.push("page text too small");
  }
  if (!summary.interactive.length) {
    failures.push("no interactive controls");
  }
  if (!viewport.isMobile) {
    if (!summary.leftNav || summary.leftNav.width < 180) failures.push("left directory missing or too narrow");
    if (!summary.main || summary.main.width < 320) failures.push("main region missing or too narrow");
    if ((new URL(`http://local${state.stateUrl}`).searchParams.get("pane") === "open") && (!summary.agent || summary.agent.width < 320)) {
      failures.push("right Agent pane missing while pane=open");
    }
  }
  for (const dialog of summary.dialogs) {
    if (
      dialog.x < -1 ||
      dialog.y < -1 ||
      dialog.x + dialog.width > viewport.width + 1 ||
      dialog.y + dialog.height > viewport.height + 1
    ) {
      failures.push(`dialog obstructed/out of viewport: ${dialog.label}`);
    }
  }
  return failures;
}

async function captureW4Actual(browser, state, viewport, outputDir, localOrigin) {
  mkdirp(outputDir);
  const page = await browser.newPage({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: viewport.isMobile,
    deviceScaleFactor: 1,
    locale: "zh-CN",
    colorScheme: "light",
  });
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const responseErrors = [];
  if (!localOrigin) {
    throw new Error("real BFF origin is required for production-real-bff capture");
  }
  const observed = installPageEvidenceObservers(page, "initial-capture");
  const url = await resolveRealStateUrl(page, state, localOrigin);
  url.searchParams.set("studio", "knowledge");
  const waiters = createRequiredResponseWaiters(page, state);
  await page.goto(url.toString(), { waitUntil: "networkidle", timeout: 30_000 });
  await settleRequiredResponses(waiters, observed.responseErrors, "initial-capture");
  await waitForRendered(page, state);
  await sleep(300);
  const screenshotPath = join(outputDir, "actual.png");
  await page.screenshot({ path: screenshotPath, fullPage: false });
  const dom = await collectDomAndLayoutSummary(page);
  const keyboard = await collectKeyboardEvidence(page);
  observed.setAction("page-close-after-capture");
  await page.close();
  const agentPane = await collectAgentPaneWidthEvidence(browser, localOrigin, state, viewport);
  const layoutFailures = analyzeLayout(dom, state, viewport);
  consoleErrors.push(...observed.consoleErrors, ...(agentPane.consoleErrors ?? []));
  pageErrors.push(...observed.pageErrors, ...(agentPane.pageErrors ?? []));
  failedRequests.push(...observed.failedRequests, ...(agentPane.failedRequests ?? []));
  responseErrors.push(...observed.responseErrors, ...(agentPane.responseErrors ?? []));
  return {
    source: "w4-current-worktree",
    path: screenshotPath,
    sha256: sha256(readFileSync(screenshotPath)),
    consoleErrors,
    pageErrors,
    failedRequests,
    responseErrors,
    dom,
    keyboard,
    agentPane,
    layoutFailures,
  };
}

async function runPromptHandoffRegression(browser, localOrigin, outputRoot, realBff = false) {
  const outputDir = join(outputRoot, "regressions", "home-to-builder-prompt");
  mkdirp(outputDir);
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    colorScheme: "light",
  });
  const state = { name: "home", stateUrl: "/?file=welcome", routeId: "welcome" };
  if (!realBff) await routeW4Api(page, state, localOrigin);
  const observed = installPageEvidenceObservers(page, "home-to-builder-prompt");
  const prompt = "请基于真实工作区资源生成一个 Dashboard Skill，并保留上下文。";
  const readPromptValues = async () => {
    const fields = page.getByTestId("skill-builder-prompt");
    await fields.first().waitFor({ state: "attached", timeout: 15_000 });
    const count = await fields.count();
    const values = [];
    for (let index = 0; index < count; index += 1) {
      values.push(await fields.nth(index).inputValue());
    }
    return values;
  };
  let waiters = createRequiredResponseWaiters(page, state);
  await page.goto(`${localOrigin}/?studio=knowledge&file=welcome`, { waitUntil: "networkidle", timeout: 30_000 });
  await settleRequiredResponses(waiters, observed.responseErrors, "home-to-builder-prompt:initial");
  if (realBff) {
    await page.getByLabel("描述要构建的 Skill").fill(`${prompt} @库存`);
    await page
      .locator("button")
      .filter({ hasText: "库存明细.csv" })
      .last()
      .click();
  } else {
    await page.getByLabel("描述要构建的 Skill").fill(`${prompt} @Workspace`);
    await page
      .locator("button")
      .filter({ hasText: "Workspace dataset revision" })
      .last()
      .click();
  }
  await page.getByLabel("描述要构建的 Skill").fill(prompt);
  if (realBff) {
    await page.getByRole("button", { name: "模板库", exact: true }).click();
    const templateDialog = page.getByRole("dialog", { name: "模板库" });
    await templateDialog.getByRole("button", { name: /^Dashboard/ }).click();
  } else {
    await page.getByRole("button", { name: /Semantic/ }).click();
  }
  await page.getByRole("button", { name: /生成 Skill/ }).click();
  // Real BFF authoring may spend several seconds running the durable Agent
  // operation before it commits the builder route. Keep this a real user-flow
  // wait, but allow the server-backed operation enough time to complete.
  await page.waitForURL(/file=skill_builder/, { timeout: 45_000 });
  const builderValues = await readPromptValues();
  const url = new URL(page.url());
  observed.setAction("home-to-builder-prompt:reload");
  waiters = createRequiredResponseWaiters(page, state);
  await page.reload({ waitUntil: "networkidle", timeout: 30_000 });
  await settleRequiredResponses(waiters, observed.responseErrors, "home-to-builder-prompt:reload");
  const reloadedValues = await readPromptValues();
  const result = {
    status: "fail",
    prompt,
    builderValue: builderValues.find((value) => value === prompt) ?? builderValues[0] ?? "",
    reloadedValue: reloadedValues.find((value) => value === prompt) ?? reloadedValues[0] ?? "",
    builderValues,
    reloadedValues,
    url: url.pathname + url.search,
    hasContextRefs: url.searchParams.has("context_refs"),
    template: url.searchParams.get("template"),
    workspaceScope: url.searchParams.get("workspace_scope"),
    draftId: url.searchParams.get("draft_id"),
    operationId: url.searchParams.get("operation_id"),
    serverOperation: null,
    failedRequests: observed.failedRequests,
    responseErrors: observed.responseErrors,
    consoleErrors: observed.consoleErrors,
    pageErrors: observed.pageErrors,
  };
  if (result.operationId) {
    const operationResponse = await page.request.get(
      `${localOrigin}/api/knowledge-assets/v1/authoring/operations/${encodeURIComponent(result.operationId)}`,
    );
    if (operationResponse.ok()) {
      result.serverOperation = await operationResponse.json();
    } else {
      observed.responseErrors.push({
        url: operationResponse.url(),
        status: operationResponse.status(),
        statusText: "authoring operation read failed",
        method: "GET",
        resourceType: "fetch",
        action: "home-to-builder-prompt:operation-read",
        required: "authoring-operation",
      });
    }
  }
  result.status = builderValues.includes(prompt)
    && reloadedValues.includes(prompt)
    && Boolean(result.operationId)
    && Boolean(result.serverOperation)
    ? "pass"
    : "fail";
  await page.screenshot({ path: join(outputDir, "after-reload.png"), fullPage: false });
  writeFileSync(join(outputDir, "result.json"), `${JSON.stringify(result, null, 2)}\n`);
  await page.close();
  const gate = evaluateEvidenceGate([
    {
      viewport: "studio-1440",
      state: "home-to-builder-prompt",
      checks: {
        layoutFailures: [],
        consoleErrors: observed.consoleErrors,
        pageErrors: observed.pageErrors,
        responseErrors: observed.responseErrors,
        failedRequests: observed.failedRequests,
        keyboardFailures: [],
        agentPaneFailures: [],
      },
    },
  ], result);
  if (result.status !== "pass" || gate.status !== "pass") {
    throw new Error(`home-to-builder prompt handoff failed: ${JSON.stringify(result)}`);
  }
  return result;
}

function stateCaptureMap(prototypeCaptures) {
  return new Map(prototypeCaptures.captures.map((capture) => [capture.stateUrl, capture]));
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const outputRoot = resolve(options.outputRoot);
  mkdirp(outputRoot);
  const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf8"));
  const prototypeCaptures = options.actualOnly || options.reuseReference
    ? { captures: [] }
    : JSON.parse(
        readFileSync(resolve(options.prototypeDir, "prototype/captures.json"), "utf8"),
      );
  const capturesByUrl = stateCaptureMap(prototypeCaptures);
  const selectedStates = options.states
    ? fixture.states.filter((state) => options.states.includes(state.name))
    : fixture.states;
  const selectedViewports = options.viewports
    ? VIEWPORTS.filter((viewport) => options.viewports.includes(viewport.name))
    : VIEWPORTS;
  const missingStates = (options.states ?? []).filter(
    (name) => !fixture.states.some((state) => state.name === name),
  );
  const missingViewports = (options.viewports ?? []).filter(
    (name) => !VIEWPORTS.some((viewport) => viewport.name === name),
  );
  if (missingStates.length || missingViewports.length ||
      !selectedStates.length || !selectedViewports.length) {
    throw new Error(
      `invalid visual selection: states=${missingStates.join(",") || "ok"} ` +
      `viewports=${missingViewports.join(",") || "ok"}`,
    );
  }
      const localServer = options.realBff
        ? await startVite(
            FRONTEND_DIR,
            Number(process.env.STEP3B_WEB_PORT || 18401),
            options.bffOrigin,
          )
        : await startProductionWorkspaceServer(FRONTEND_DIR, 5179);
      const prototypeServer = !options.actualOnly && !options.reuseReference && options.prototypeSourceServer
        ? await startPrototypeServer(options.prototypeDir, 5180)
        : {
            origin: null,
            skippedReason: options.actualOnly
              ? "actual-only"
              : options.reuseReference
                ? "reusing reference cache"
                : "using captures.json TOS PNG reference",
            close: async () => {},
          };
  const browser = await chromium.launch({ headless: true });
  const entries = [];
  try {
    for (const state of selectedStates) {
      const prototypeCapture = capturesByUrl.get(state.stateUrl);
      if (!options.actualOnly && !options.reuseReference && !prototypeCapture) {
        throw new Error(`missing prototype capture for ${state.stateUrl}`);
      }
      for (const viewport of selectedViewports) {
        const root = join(outputRoot, viewport.name, state.name);
        mkdirp(root);
        let reference = null;
        if (!options.actualOnly) {
          reference = options.reuseReference
            ? readCachedReference(options.referenceDir, state, viewport)
            : await capturePrototypeReference(
                browser,
                state,
                viewport,
                prototypeCapture,
                join(root, "reference"),
                prototypeServer.origin,
              );
          if (!options.reuseReference) {
            reference = persistReferenceCache(options.referenceDir, state, viewport, reference);
          }
        }
        const actual = await captureW4Actual(
          browser,
          state,
          viewport,
          join(root, "actual"),
          localServer.origin,
        );
        const actualPng = readFileSync(actual.path);
        const diffDir = join(root, "diff");
        mkdirp(diffDir);
        const diff = reference
          ? createDiffArtifacts(readFileSync(reference.path), actualPng)
          : null;
        const overlayPath = diff ? join(diffDir, "overlay.png") : null;
        if (diff) writeFileSync(overlayPath, diff.overlayPng);
        const entry = {
          state: state.name,
          routeId: state.routeId,
          stateUrl: state.stateUrl,
          viewport: viewport.name,
          dimensions: { width: viewport.width, height: viewport.height },
          reference: reference ? {
              source: reference.source,
              path: reference.path,
              sha256: reference.sha256,
              consoleErrors: reference.consoleErrors,
              failedRequests: reference.failedRequests,
              metadata: reference.metadata,
            } : null,
          actual: {
            path: actual.path,
            sha256: actual.sha256,
            consoleErrors: actual.consoleErrors,
            pageErrors: actual.pageErrors,
            failedRequests: actual.failedRequests,
            responseErrors: actual.responseErrors,
          },
          diff: diff ? {
              overlayPath,
              sha256: sha256(diff.overlayPng),
              dimensionsEqual: diff.dimensionsEqual,
              mismatchRatio: diff.mismatchRatio,
            } : null,
          dom: actual.dom,
          keyboard: actual.keyboard,
          agentPane: actual.agentPane,
          checks: {
            horizontalOverflowPx: actual.dom.horizontalOverflowPx,
            layoutFailures: actual.layoutFailures,
            consoleErrors: actual.consoleErrors,
            pageErrors: actual.pageErrors,
            responseErrors: actual.responseErrors,
            failedRequests: actual.failedRequests,
            keyboardFailures: actual.keyboard.failures,
            agentPaneFailures: actual.agentPane.failures,
          },
        };
        writeFileSync(join(root, "summary.json"), `${JSON.stringify(entry, null, 2)}\n`);
        entries.push(entry);
      }
    }
    const promptHandoff = await runPromptHandoffRegression(
      browser,
      localServer.origin,
      outputRoot,
      options.realBff,
    );
    const networkGate = evaluateEvidenceGate(entries, promptHandoff);
    const failures = networkGate.failures;
    const report = {
      status: networkGate.status,
      generatedAt: new Date().toISOString(),
      prototypeDir: options.prototypeDir,
      prototypeReference: prototypeServer.origin ? "prototype source server" : "captures.json TOS PNG fallback",
      validationScope: options.realBff
        ? "production-real-bff"
        : "w4-ui-typed-seam",
      productionPass: options.realBff && networkGate.status === "pass",
      integrationPending: options.realBff ? [] : [
        "W1 connector/backend services",
        "W2 authoring/runtime streaming backend",
        "W3 trusted renderer/template registry/runtime",
        "Integration MAIN vertical production wiring",
      ],
      localOrigin: localServer.origin,
      states: selectedStates.length,
      stateNames: selectedStates.map((state) => state.name),
      viewports: selectedViewports.map((viewport) => viewport.name),
      screenshots: entries.length,
      referenceMode: options.actualOnly
        ? "actual-only"
        : options.reuseReference
          ? "reuse-reference-cache"
          : "capture-and-cache-reference",
      promptHandoff,
      networkGate: {
        failedRequestsTotal: networkGate.failedRequestsTotal,
        ignoredRequestsTotal: networkGate.ignoredRequestsTotal,
        responseErrorsTotal: networkGate.responseErrorsTotal,
        consoleErrorsTotal: networkGate.consoleErrorsTotal,
        pageErrorsTotal: networkGate.pageErrorsTotal,
        ignoredRequests: networkGate.ignoredRequests,
        unhandledFailedRequests: networkGate.unhandledFailedRequests,
      },
      failures,
      entries,
    };
    writeFileSync(join(outputRoot, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
    writeFileSync(
      join(outputRoot, "README.md"),
      [
        "# STEP3B production-real-bff v2.15.2 browser evidence",
        "",
        `Generated at: ${report.generatedAt}`,
        `Prototype dir: ${options.prototypeDir}`,
        `Reference source: ${report.prototypeReference}`,
        `Validation scope: ${report.validationScope}`,
        `Production pass: ${report.productionPass}`,
        `Status: ${report.status}`,
        "",
        "Artifacts are grouped as `<viewport>/<state>/{reference,actual,diff}`.",
        "Each state has `summary.json` with DOM, layout, console, failed request, overflow, keyboard, modal, and Agent pane width checks.",
        "",
        `Prompt handoff regression: ${promptHandoff.status}`,
        `Failed requests: ${networkGate.failedRequestsTotal}`,
        `Ignored requests: ${networkGate.ignoredRequestsTotal}`,
        `Response errors: ${networkGate.responseErrorsTotal}`,
        `Console errors: ${networkGate.consoleErrorsTotal}`,
        `Page errors: ${networkGate.pageErrorsTotal}`,
      ].join("\n"),
    );
    process.stdout.write(`${JSON.stringify({
      status: report.status,
      outputRoot,
      screenshots: report.screenshots,
      failures,
      promptHandoff: promptHandoff.status,
    }, null, 2)}\n`);
    if (failures.length) process.exitCode = 1;
  } finally {
    await browser.close();
    await localServer.close();
    if (!options.keepServer) await prototypeServer.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack || error.message : error}\n`);
    process.exitCode = 1;
  });
}
