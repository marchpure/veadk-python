import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { once } from "node:events";
import { tmpdir } from "node:os";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PAGE_URL = process.env.KC_SMOKE_URL || "http://127.0.0.1:4173";
const OUT = new URL("./", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

function base64Url(value) {
  return Buffer.from(JSON.stringify(value))
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

const TEST_JWT = [
  base64Url({ alg: "none", typ: "JWT" }),
  base64Url({
    sub: "kc-smoke-user",
    email: "kc-smoke@example.com",
    name: "KC Smoke",
    preferred_username: "kc-smoke",
  }),
  "signature",
].join(".");

function freePort() {
  return new Promise((resolve, reject) => {
    import("node:net").then(({ createServer }) => {
      const server = createServer();
      server.listen(0, "127.0.0.1", () => {
        const address = server.address();
        const port = typeof address === "object" && address ? address.port : 0;
        server.close(() => resolve(port));
      });
      server.on("error", reject);
    }, reject);
  });
}

async function waitJson(url, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError}`);
}

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result || {});
        return;
      }
      if (message.method) this.events.push(message);
    });
  }

  async send(method, params = {}) {
    const id = this.nextId++;
    const promise = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.socket.send(JSON.stringify({ id, method, params }));
    return promise;
  }

  takeEvents(method) {
    const matches = this.events.filter((event) => event.method === method);
    this.events = this.events.filter((event) => event.method !== method);
    return matches;
  }
}

async function runViewport(viewport) {
  const debugPort = await freePort();
  const profileDir = mkdtempSync(`${tmpdir()}/kc-smoke-${viewport.name}-`);
  const chrome = spawn(CHROME, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${profileDir}`,
    "about:blank",
  ], { stdio: "ignore" });

  try {
    const targets = await waitJson(`http://127.0.0.1:${debugPort}/json/list`);
    const pageTarget = targets.find((target) => target.type === "page") || targets[0];
    const socket = new WebSocket(pageTarget.webSocketDebuggerUrl);
    await once(socket, "open");
    const cdp = new Cdp(socket);
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Log.enable");
    await cdp.send("Network.enable");
    await cdp.send("Network.setExtraHTTPHeaders", {
      headers: { Authorization: `Bearer ${TEST_JWT}` },
    });
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: viewport.name === "mobile",
    });
    await cdp.send("Page.navigate", { url: PAGE_URL });
    await new Promise((resolve) => setTimeout(resolve, 3_000));
    await cdp.send("Runtime.evaluate", {
      expression: `(() => {
        const button = [...document.querySelectorAll("button")]
          .find((item) => item.getAttribute("aria-label") === "知识中心" || item.textContent.includes("知识中心"));
        if (button) button.click();
      })()`,
    });
    await new Promise((resolve) => setTimeout(resolve, 1_000));

    const metrics = await cdp.send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const doc = document.documentElement;
        const text = document.body ? document.body.innerText : "";
        return {
          title: document.title,
          scrollWidth: doc.scrollWidth,
          innerWidth: window.innerWidth,
          hasRoot: !!document.querySelector("#root"),
          hasSidebar: !!document.querySelector(".sidebar"),
          hasKnowledgeNavText: text.includes("知识中心"),
          hasKnowledgeFrame: !!document.querySelector(".kc-frame"),
          hasKnowledgeShell: !!document.querySelector(".kc-root"),
          hasKnowledgeSteps: text.includes("连接器") && text.includes("建模") && text.includes("看板") && text.includes("评测分享"),
          bodyTextLength: text.length
        };
      })()`,
    });
    const screenshot = await cdp.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    const screenshotName = `kc-smoke-${viewport.name}.png`;
    writeFileSync(`${OUT}${screenshotName}`, Buffer.from(screenshot.data, "base64"));

    const consoleErrors = cdp
      .takeEvents("Runtime.consoleAPICalled")
      .filter((event) => event.params.type === "error")
      .map((event) => JSON.stringify(event.params.args || []));
    const pageErrors = cdp
      .takeEvents("Runtime.exceptionThrown")
      .map((event) => event.params.exceptionDetails?.text || "exception");
    const requestFailures = cdp
      .takeEvents("Network.loadingFailed")
      .filter((event) => event.params.type !== "Document" || event.params.errorText !== "net::ERR_ABORTED")
      .filter((event) => event.params.errorText !== "net::ERR_BLOCKED_BY_RESPONSE")
      .map((event) => `${event.params.requestId}: ${event.params.errorText}`);
    socket.close();

    const value = metrics.result?.value || {};
    return {
      viewport: viewport.name,
      size: `${viewport.width}x${viewport.height}`,
      screenshot: screenshotName,
      consoleErrors,
      pageErrors,
      requestFailures,
      overflow: value.scrollWidth > value.innerWidth + 1
        ? [{ scrollWidth: value.scrollWidth, innerWidth: value.innerWidth }]
        : [],
      assertions: [
        { name: "root mounted", ok: value.hasRoot === true },
        { name: "sidebar visible", ok: value.hasSidebar === true },
        { name: "knowledge center nav visible", ok: value.hasKnowledgeNavText === true },
        { name: "knowledge center shell visible", ok: value.hasKnowledgeShell === true },
        { name: "knowledge center four steps visible", ok: value.hasKnowledgeSteps === true },
        { name: "knowledge center iframe visible", ok: value.hasKnowledgeFrame === true },
        { name: "body has rendered text", ok: value.bodyTextLength > 0 },
      ],
    };
  } finally {
    chrome.kill("SIGTERM");
    await Promise.race([
      once(chrome, "exit").catch(() => undefined),
      new Promise((resolve) => setTimeout(resolve, 2_000)),
    ]);
    rmSync(profileDir, { recursive: true, force: true });
  }
}

const report = {
  url: PAGE_URL,
  startedAt: new Date().toISOString(),
  runs: [],
};

for (const viewport of VIEWPORTS) {
  const run = await runViewport(viewport);
  run.passed = run.assertions.every((item) => item.ok) &&
    run.consoleErrors.length === 0 &&
    run.pageErrors.length === 0 &&
    run.requestFailures.length === 0 &&
    run.overflow.length === 0;
  report.runs.push(run);
  console.log(`${viewport.name}: ${run.passed ? "PASS" : "FAIL"}`);
}

report.finishedAt = new Date().toISOString();
report.passed = report.runs.every((run) => run.passed);
writeFileSync(`${OUT}kc-smoke-result.json`, JSON.stringify(report, null, 2));
process.exit(report.passed ? 0 : 1);
