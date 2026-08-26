#!/usr/bin/env node

/*
 * Production-real-bff visual gate.
 *
 * This runner deliberately has no Playwright routing hooks. Both the
 * prototype and Integration are visited over HTTP; all business responses
 * come from their servers. A missing dynamic state is a gate failure.
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { inflateSync } from "node:zlib";
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

function readPng(path) {
  const bytes = readFileSync(path);
  if (bytes.readUInt32BE(0) !== 0x89504e47) throw new Error("not a PNG");
  let offset = 8;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idat = [];
  while (offset < bytes.length) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.toString("ascii", offset + 4, offset + 8);
    const payload = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = payload.readUInt32BE(0);
      height = payload.readUInt32BE(4);
      const bitDepth = payload[8];
      colorType = payload[9];
      if (bitDepth !== 8 || ![2, 6].includes(colorType)) {
        throw new Error("visual gate requires 8-bit RGB/RGBA PNG");
      }
    } else if (type === "IDAT") {
      idat.push(payload);
    } else if (type === "IEND") {
      break;
    }
    offset += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const bytesPerPixel = colorType === 6 ? 4 : 3;
  const stride = width * bytesPerPixel;
  const decoded = Buffer.alloc(height * stride);
  const pixels = Buffer.alloc(height * width * 4);
  let source = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = raw[source++];
    const row = raw.subarray(source, source + stride);
    source += stride;
    const out = Buffer.alloc(stride);
    const prior = y === 0 ? null : decoded.subarray((y - 1) * stride, y * stride);
    for (let x = 0; x < stride; x += 1) {
      const left = x >= bytesPerPixel ? out[x - bytesPerPixel] : 0;
      const up = prior
        ? prior[Math.floor(x / bytesPerPixel) * bytesPerPixel + (x % bytesPerPixel)]
        : 0;
      const upperLeft = prior && x >= bytesPerPixel
        ? prior[
          Math.floor((x - bytesPerPixel) / bytesPerPixel) * bytesPerPixel +
          ((x - bytesPerPixel) % bytesPerPixel)
        ]
        : 0;
      const value = row[x];
      if (filter === 0) out[x] = value;
      else if (filter === 1) out[x] = (value + left) & 255;
      else if (filter === 2) out[x] = (value + up) & 255;
      else if (filter === 3) out[x] = (value + Math.floor((left + up) / 2)) & 255;
      else if (filter === 4) {
        const p = left + up - upperLeft;
        const pa = Math.abs(p - left);
        const pb = Math.abs(p - up);
        const pc = Math.abs(p - upperLeft);
        const predictor = pa <= pb && pa <= pc ? left : pb <= pc ? up : upperLeft;
        out[x] = (value + predictor) & 255;
      } else throw new Error(`unsupported PNG filter ${filter}`);
    }
    out.copy(decoded, y * stride);
    for (let x = 0; x < width; x += 1) {
      const sourceOffset = x * bytesPerPixel;
      const targetOffset = (y * width + x) * 4;
      pixels[targetOffset] = out[sourceOffset];
      pixels[targetOffset + 1] = out[sourceOffset + 1];
      pixels[targetOffset + 2] = out[sourceOffset + 2];
      pixels[targetOffset + 3] = colorType === 6 ? out[sourceOffset + 3] : 255;
    }
  }
  return { width, height, pixels };
}

function pixelDiff(actualPath, referencePath) {
  const actual = readPng(actualPath);
  const reference = readPng(referencePath);
  if (actual.width !== reference.width || actual.height !== reference.height) {
    return { ratio: 1, mean: 1, width: actual.width, height: actual.height };
  }
  let changed = 0;
  let total = 0;
  for (let index = 0; index < actual.pixels.length; index += 4) {
    const delta =
      Math.abs(actual.pixels[index] - reference.pixels[index]) +
      Math.abs(actual.pixels[index + 1] - reference.pixels[index + 1]) +
      Math.abs(actual.pixels[index + 2] - reference.pixels[index + 2]) +
      Math.abs(actual.pixels[index + 3] - reference.pixels[index + 3]);
    if (delta > 16) changed += 1;
    total += delta / 1020;
  }
  const pixelCount = actual.width * actual.height;
  return {
    ratio: changed / pixelCount,
    mean: total / pixelCount,
    width: actual.width,
    height: actual.height,
  };
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
    states: get("--states", ""),
    viewports: get("--viewports", ""),
    referenceDir: resolve(get("--reference-dir", ".veadk/knowledge-assets/prototype-reference-cache")),
    reuseReference: argv.includes("--reuse-reference"),
    actualOnly: argv.includes("--actual-only"),
  };
}

function selectedValues(value, allowed, flag) {
  if (!value) return allowed;
  const aliases = { welcome: "home" };
  const requested = value
    .split(",")
    .map((item) => aliases[item.trim()] ?? item.trim())
    .filter(Boolean);
  const invalid = requested.filter((item) => !allowed.includes(item));
  if (invalid.length) throw new Error(`${flag} contains unsupported values: ${invalid.join(",")}`);
  return requested;
}

function dynamicStateUrls(bootstrap) {
  const drafts = bootstrap.resources.filter((item) => item.resourceKind === "skill_draft");
  const published = bootstrap.resources.find((item) => item.resourceKind === "published_skill");
  // The seed's acceptance labels are server-projected display metadata. The
  // URL is still built only from the returned opaque resource id; production
  // routing never branches on these labels.
  const findDisplayName = (name) =>
    drafts.find((item) => item.displayName === name);
  const sop = findDisplayName("蓝牙断连排查 SOP");
  const dashboard = findDisplayName("安踏经营 Dashboard");
  const haidilaoSop = findDisplayName("海底捞卫生巡检 SOP");
  const optimization = findDisplayName("渠道转化趋势");
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
    url(haidilaoSop, "&pane=open"),
    url(haidilaoSop, "&run_state=input&pane=open"),
    url(haidilaoSop, "&run_state=result&pane=open"),
    url(published, ""),
    url(optimization, ""),
  ];
}

function atomicJson(path, value) {
  const temporary = `${path}.tmp-${process.pid}`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`);
  renameSync(temporary, path);
}

function cachePaths(referenceDir, state, viewportName) {
  const root = join(referenceDir, viewportName, state);
  return {
    root,
    screenshot: join(root, "prototype-reference.png"),
    metadata: join(root, "metadata.json"),
  };
}

function readReferenceCache(referenceDir, state, viewportName) {
  const paths = cachePaths(referenceDir, state, viewportName);
  if (!existsSync(paths.screenshot) || !existsSync(paths.metadata)) return null;
  try {
    const metadata = JSON.parse(readFileSync(paths.metadata, "utf8"));
    const screenshotSha = sha256(readFileSync(paths.screenshot));
    if (metadata.sha256 !== screenshotSha) return null;
    return {
      url: metadata.url,
      screenshot: paths.screenshot,
      sha256: screenshotSha,
      navigationError: "",
      screenshotError: "",
      consoleErrors: [],
      pageErrors: [],
      failedRequests: [],
      dom: metadata.dom ?? { scrollWidth: 0, innerWidth: 0, agentWidth: 0, bodyText: "" },
      cache: { reused: true, downloadedAt: metadata.downloadedAt, viewport: metadata.viewport },
    };
  } catch {
    return null;
  }
}

async function visit(browser, origin, stateUrl, viewport, output, label, options = {}) {
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
    // The prototype is a remote static app.  Its first document can exceed
    // ten seconds under normal CDN/TLS variance; allow the real navigation to
    // settle without treating a slow document as a missing reference.  A
    // missing screenshot, request error, or unusable DOM remains a gate
    // failure below.
    await page.goto(url.toString(), { waitUntil: "domcontentloaded", timeout: 30_000 });
    if (origin.includes("127.0.0.1") || origin.includes("localhost")) {
      await page
        .waitForResponse(
          (response) =>
            response.url().includes("/api/knowledge-assets/v1/bootstrap") &&
            response.ok(),
          { timeout: 8_000 },
        )
        .catch(() => undefined);
      // Bootstrap is only the first real request.  Let React commit the
      // server-projected revision and let the immutable artifact finish its
      // integrity-checked fetch before capturing or closing the page.
      await page.waitForTimeout(1200);
      await page
        .waitForFunction(() => {
          const host = document.querySelector(".trusted-artifact-host");
          if (!host) return true;
          const shell = host.closest("[aria-busy]");
          if (shell?.getAttribute("aria-busy") === "false") return true;
          return Boolean(host.shadowRoot?.textContent?.trim());
        }, { timeout: 8_000 })
        .catch(() => undefined);
      await page.waitForTimeout(250);
    } else {
      await page.waitForTimeout(800);
    }
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }
  const dom = await page.evaluate(() => ({
    readyState: document.readyState,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    agentWidth: document.querySelector('[aria-label="分析助手"]')?.getBoundingClientRect().width ?? 0,
    bodyText: document.body.innerText.slice(0, 5000),
  })).catch(() => ({ scrollWidth: 0, innerWidth: viewport.width, agentWidth: 0, bodyText: "" }));
  // The remote prototype can keep a stylesheet/font request open after the
  // application has rendered. A navigation timeout is therefore not by
  // itself a missing reference. Only a screenshot backed by a meaningful DOM
  // is eligible for comparison or cache reuse.
  const usableDom = dom.bodyText.trim().length >= 40 && dom.innerWidth === viewport.width;
  const navigationWarning = navigationError && usableDom ? navigationError : "";
  if (usableDom && navigationWarning) navigationError = "";
  const screenshot = join(output, `${label}.png`);
  let screenshotError = "";
  try {
    await page.screenshot({ path: screenshot, fullPage: false });
  } catch (error) {
    screenshotError = error instanceof Error ? error.message : String(error);
  }
  await page.close().catch(() => undefined);
  let screenshotSha = "";
  try {
    screenshotSha = sha256(readFileSync(screenshot));
  } catch {
    // Keep the failed capture visible in the report instead of throwing from
    // the evidence collector itself.
  }
  if (options.referenceCache && screenshotSha && !navigationError && !screenshotError) {
    mkdirSync(options.referenceCache.root, { recursive: true });
    writeFileSync(options.referenceCache.screenshot, readFileSync(screenshot));
    atomicJson(options.referenceCache.metadata, {
      url: url.toString(),
      viewport: viewport.name,
      downloadedAt: new Date().toISOString(),
      sha256: screenshotSha,
      dom,
      navigationWarning,
    });
  }
  return {
    url: url.toString(),
    screenshot,
    sha256: screenshotSha,
    navigationError,
    screenshotError,
    consoleErrors,
    pageErrors,
    failedRequests,
    dom,
    navigationWarning,
  };
}

async function main() {
  const options = args(process.argv.slice(2));
  mkdirSync(options.output, { recursive: true });
  const selectedStateNames = selectedValues(options.states, stateNames, "--states");
  const selectedViewports = selectedValues(
    options.viewports,
    VIEWPORTS.map((viewport) => viewport.name),
    "--viewports",
  ).map((name) => VIEWPORTS.find((viewport) => viewport.name === name));
  const response = await fetch(`${options.integration}/api/knowledge-assets/v1/bootstrap?workspace=${encodeURIComponent(options.workspace)}`);
  if (!response.ok) throw new Error(`integration bootstrap failed: ${response.status}`);
  const bootstrap = await response.json();
  const allUrls = dynamicStateUrls(bootstrap);
  const urls = selectedStateNames.map((state) => allUrls[stateNames.indexOf(state)]);
  const entries = [];
  const writeReport = () => {
    const failures = entries.flatMap((entry) => {
      const out = [];
      if (!entry.checks.dynamicUrl) out.push(`${entry.state}: no dynamic resource URL`);
      if (!entry.checks.horizontalOverflow) out.push(`${entry.state}/${entry.viewport}: horizontal overflow`);
      if (entry.actual.navigationError) out.push(`${entry.state}/${entry.viewport}: ${entry.actual.navigationError}`);
      if (entry.actual.screenshotError) out.push(`${entry.state}/${entry.viewport}: ${entry.actual.screenshotError}`);
      if (entry.actual.consoleErrors.length) out.push(`${entry.state}/${entry.viewport}: console errors`);
      if (entry.actual.pageErrors.length) out.push(`${entry.state}/${entry.viewport}: page errors`);
      if (entry.actual.failedRequests.length) out.push(`${entry.state}/${entry.viewport}: failed business/static requests`);
      if (entry.reference.navigationError) out.push(`${entry.state}/${entry.viewport}: prototype reference navigation failed`);
      if (entry.reference.screenshotError || !entry.reference.sha256) out.push(`${entry.state}/${entry.viewport}: prototype reference screenshot missing`);
      const threshold = entry.viewport === "mobile-390" ? 0.08 : 0.05;
      if (entry.pixelDiffRatio > 0.10) out.push(`${entry.state}/${entry.viewport}: pixel diff exceeds 10%`);
      if (entry.pixelDiffRatio > threshold) out.push(`${entry.state}/${entry.viewport}: pixel diff exceeds viewport threshold`);
      return out;
    });
    const expectedScreenshots = selectedStateNames.length * selectedViewports.length;
    const report = {
      generatedAt: new Date().toISOString(),
      validationScope: "production-real-bff",
      productionPass: failures.length === 0 && entries.length === expectedScreenshots,
      stateCount: selectedStateNames.length,
      viewportCount: selectedViewports.length,
      screenshots: entries.length,
      expectedScreenshots,
      states: selectedStateNames,
      viewports: selectedViewports.map((viewport) => viewport.name),
      workspace: bootstrap.access.spaceId,
      resourceIds: bootstrap.resources.map((item) => item.id),
      entries,
      failures,
      options: {
        reuseReference: options.reuseReference,
        actualOnly: options.actualOnly,
        referenceDir: options.referenceDir,
      },
      note: "Prototype reference is visited over HTTP or loaded from an explicit screenshot cache; this runner contains no page.route or route.fulfill.",
    };
    atomicJson(join(options.output, "report.json"), report);
    return report;
  };
  for (let index = 0; index < selectedStateNames.length; index += 1) {
    // The prototype is a remote static app. Reusing one Chromium process for
    // all 45 captures eventually exhausts its renderer; isolate each state so
    // a remote failure cannot invalidate already collected real captures.
    const browser = await chromium.launch({ headless: true });
    try {
      for (const viewport of selectedViewports) {
        const state = selectedStateNames[index];
        const root = join(options.output, viewport.name, state);
        mkdirSync(root, { recursive: true });
        let actual;
        let reference;
        try {
          actual = await visit(browser, options.integration, urls[index], viewport, root, "actual");
        } catch (error) {
          actual = {
            url: urls[index],
            screenshot: "",
            sha256: "",
            navigationError: error instanceof Error ? error.message : String(error),
            screenshotError: "",
            consoleErrors: [],
            pageErrors: [],
            failedRequests: [],
            dom: { scrollWidth: 0, innerWidth: viewport.width, agentWidth: 0, bodyText: "" },
            navigationWarning: "",
          };
        }
        try {
          const cached = options.reuseReference
            ? readReferenceCache(options.referenceDir, state, viewport.name)
            : null;
          if (cached) {
            reference = cached;
          } else if (options.actualOnly) {
            reference = {
              url: new URL(prototypeStateUrls[stateNames.indexOf(state)], options.prototype).toString(),
              screenshot: "",
              sha256: "",
              navigationError: "",
              screenshotError: "reference cache missing in --actual-only mode",
              consoleErrors: [],
              pageErrors: [],
              failedRequests: [],
              dom: { scrollWidth: 0, innerWidth: viewport.width, agentWidth: 0, bodyText: "" },
              navigationWarning: "",
            };
          } else {
            reference = await visit(
              browser,
              options.prototype,
              prototypeStateUrls[stateNames.indexOf(state)],
              viewport,
              root,
              "prototype-reference",
              { referenceCache: cachePaths(options.referenceDir, state, viewport.name) },
            );
          }
        } catch (error) {
          reference = {
            url: prototypeStateUrls[stateNames.indexOf(state)],
            screenshot: "",
            sha256: "",
            navigationError: error instanceof Error ? error.message : String(error),
            screenshotError: "",
            consoleErrors: [],
            pageErrors: [],
            failedRequests: [],
            dom: { scrollWidth: 0, innerWidth: viewport.width, agentWidth: 0, bodyText: "" },
          };
        }
        const ratio = actual.dom.scrollWidth > actual.dom.innerWidth ? 1 : 0;
        let diff = { ratio: 1, mean: 1, width: 0, height: 0 };
        if (
          actual.screenshot &&
          reference.screenshot &&
          actual.sha256 &&
          reference.sha256 &&
          !actual.navigationError &&
          !reference.navigationError &&
          !actual.screenshotError &&
          !reference.screenshotError
        ) {
          try {
            diff = pixelDiff(actual.screenshot, reference.screenshot);
          } catch {
            diff = { ratio: 1, mean: 1, width: 0, height: 0 };
          }
        }
        entries.push({
          state,
          viewport: viewport.name,
          stateUrl: urls[index],
          actual,
          reference,
          pixelDiffRatio: diff.ratio,
          pixelMeanDiff: diff.mean,
          screenshotSize: { width: diff.width, height: diff.height },
          checks: {
            dynamicUrl: Boolean(urls[index]),
            horizontalOverflow: ratio === 0,
            consoleErrors: actual.consoleErrors,
            pageErrors: actual.pageErrors,
            failedRequests: actual.failedRequests,
            navigationError: actual.navigationError,
          },
        });
        writeReport();
      }
    } finally {
      await browser.close().catch(() => undefined);
    }
  }
  const report = writeReport();
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
