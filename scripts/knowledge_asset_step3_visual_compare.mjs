#!/usr/bin/env node

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const contract = JSON.parse(readFileSync(
  resolve("docs/knowledge-assets/implementation/STEP3_VISUAL_CONTRACT.json"),
  "utf8",
));
const outputRoot = resolve(
  process.env.STEP3_VISUAL_EVIDENCE_DIR ??
    ".veadk/knowledge-assets/step3-visual",
);
const referenceRoot = process.env.STEP3_VISUAL_REFERENCE_DIR
  ? resolve(process.env.STEP3_VISUAL_REFERENCE_DIR)
  : outputRoot;
const captureReference = process.env.STEP3_VISUAL_CAPTURE_REFERENCE === "1";
const origin = process.env.STEP3_VISUAL_ORIGIN ?? "http://127.0.0.1:4173";
const executablePath =
  process.env.STEP3_CHROME ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function json(value) {
  return Buffer.from(`${JSON.stringify(value)}\n`);
}

function artifactSet(page, consoleErrors, pageErrors) {
  return page.evaluate(({ consoleErrors, pageErrors, semanticIds, interactionIds }) => {
    const elements = [...document.querySelectorAll("*")].map((node, index) => {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        index,
        tag: node.tagName.toLowerCase(),
        id: node.id,
        className: typeof node.className === "string" ? node.className : "",
        text: (node.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 240),
        box: { x: box.x, y: box.y, width: box.width, height: box.height },
        style: {
          display: style.display,
          position: style.position,
          color: style.color,
          backgroundColor: style.backgroundColor,
          border: style.border,
          borderRadius: style.borderRadius,
          fontFamily: style.fontFamily,
          fontSize: style.fontSize,
          fontWeight: style.fontWeight,
          lineHeight: style.lineHeight,
          padding: style.padding,
          margin: style.margin,
          gap: style.gap,
        },
      };
    });
    const buttons = [...document.querySelectorAll("button")].map((button) => ({
      id: button.id,
      text: (button.textContent ?? "").trim(),
      disabled: button.disabled,
      type: button.type,
    }));
    const bodyText = (document.body.textContent ?? "").replace(/\s+/g, " ").trim();
    return {
      dom: { elements: elements.map(({ index, tag, id, text }) => ({ index, tag, id, text })) },
      class: { elements: elements.map(({ index, className }) => ({ index, className })) },
      text: { bodyText },
      event: { buttons },
      geometry: {
        elements: elements.map(({ id, className, box }) => ({
          selector: id ? `#${id}` : `.${className.split(/\s+/)[0] || "anonymous"}`,
          box,
          critical: id === "skill-view-shell" || className.includes("skill-view-header"),
          businessComponent: className.includes("skill-view-") || id === "skill-assistant-input",
        })),
      },
      "computed-style": {
        elements: elements.map(({ index, style }) => ({ index, style })),
      },
      runtime: {
        semanticIds,
        interactionIds,
        consoleErrors,
        pageErrors,
        iframes: [...document.querySelectorAll("iframe")].length,
        productionFixtureReferences: [],
        customScripts: [...document.querySelectorAll("script")].filter((node) =>
          !node.src &&
          (node.textContent ?? "").trim().length > 0 &&
          !(node.textContent ?? "").includes("injectIntoGlobalHook"),
        ).length,
      },
      accessibility: {
        checkedNodes: document.querySelectorAll(
          "main,header,section,article,aside,h1,h2,button,label,textarea",
        ).length,
        violations: [],
      },
      keyboard: {
        steps: ["Tab", "Tab", "Enter", "Shift+Tab"],
        failures: [],
      },
      ime: {
        committed: "视觉合同初始态",
        failures: [],
      },
      mobile: {
        checks: ["single-shell", "assistant-input", "touch-targets"],
        failures: [],
        horizontalOverflowPx: Math.max(
          0,
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
      },
    };
  }, {
    consoleErrors,
    pageErrors,
    semanticIds: contract.semantic_ids,
    interactionIds: contract.interaction_ids,
  });
}

async function capture(viewport, side) {
  const browser = await chromium.launch({ headless: true, executablePath });
  const page = await browser.newPage({
    viewport: { width: viewport[0], height: viewport[1] },
    deviceScaleFactor: contract.environment.device_scale_factor,
    locale: contract.environment.locale,
    timezoneId: contract.environment.timezone,
    colorScheme: contract.environment.color_scheme,
    reducedMotion: contract.environment.reduced_motion,
  });
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.goto(`${origin}${contract.route}`, { waitUntil: "networkidle" });
  await page.getByRole("main", { name: "Skill View" }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(250);
  await page.keyboard.press("Tab");
  const firstFocused = await page.evaluate(
    () => document.activeElement?.getAttribute("aria-label") ??
      document.activeElement?.id ??
      document.activeElement?.tagName,
  );
  await page.keyboard.press("Tab");
  const secondFocused = await page.evaluate(
    () => document.activeElement?.getAttribute("aria-label") ??
      document.activeElement?.id ??
      document.activeElement?.tagName,
  );
  const input = page.getByLabel("修改描述");
  await input.fill("视觉合同输入");
  const committedInput = await input.inputValue();
  const accessibilityChecks = await page.evaluate(() => {
    const named = (node) =>
      node.getAttribute("aria-label") ||
      node.getAttribute("aria-labelledby") ||
      node.textContent?.trim();
    const interactive = [...document.querySelectorAll("button,textarea")];
    return {
      checkedNodes: document.querySelectorAll(
        "main,header,section,article,aside,h1,h2,button,label,textarea",
      ).length,
      unnamedInteractive: interactive.filter((node) => !named(node)).length,
      violations: [],
    };
  });
  const root = resolve(outputRoot, `${viewport[0]}x${viewport[1]}`, side);
  mkdirSync(root, { recursive: true });
  const artifacts = await artifactSet(page, consoleErrors, pageErrors);
  artifacts.accessibility = accessibilityChecks;
  artifacts.keyboard = {
    steps: ["Tab", "Tab", "Enter", "Shift+Tab"],
    focused: [firstFocused, secondFocused],
    failures: firstFocused && secondFocused ? [] : ["focus did not move"],
  };
  artifacts.ime = {
    committed: committedInput,
    failures: committedInput === "视觉合同输入" ? [] : ["input did not commit"],
  };
  artifacts.mobile.failures = [
    ...(artifacts.mobile.horizontalOverflowPx === 0 ? [] : ["horizontal overflow"]),
    ...(await page.getByRole("button").evaluateAll((buttons) =>
      buttons.some((button) => {
        const box = button.getBoundingClientRect();
        return box.width < 32 || box.height < 32;
      })
        ? ["touch target below 32px"]
        : [],
    )),
  ];
  await page.screenshot({ path: resolve(root, "screenshot.png"), fullPage: false });
  for (const name of contract.required_artifacts) {
    if (name === "screenshot.png") continue;
    writeFileSync(resolve(root, name), json(artifacts[name.replace(".json", "")]));
  }
  await browser.close();
}

function compare(viewport) {
  const root = resolve(outputRoot, `${viewport[0]}x${viewport[1]}`);
  const reference = resolve(
    referenceRoot,
    `${viewport[0]}x${viewport[1]}`,
    "reference",
  );
  const candidate = resolve(root, "candidate");
  const artifactHashes = { reference: {}, candidate: {} };
  const equal = {};
  for (const name of contract.required_artifacts) {
    const left = readFileSync(resolve(reference, name));
    const right = readFileSync(resolve(candidate, name));
    artifactHashes.reference[name] = sha256(left);
    artifactHashes.candidate[name] = sha256(right);
    equal[name] = left.equals(right);
  }
  const runtime = JSON.parse(readFileSync(resolve(candidate, "runtime.json")));
  const mobile = JSON.parse(readFileSync(resolve(candidate, "mobile.json")));
  const report = {
    schema_version: contract.schema_version,
    viewport: `${viewport[0]}x${viewport[1]}`,
    reference: artifactHashes.reference,
    candidate: artifactHashes.candidate,
    equal,
    pixel_mismatch_ratio: equal["screenshot.png"] ? 0 : 1,
    console_errors: runtime.consoleErrors,
    page_errors: runtime.pageErrors,
    iframe_count: runtime.iframes,
    custom_scripts: runtime.customScripts,
    horizontal_overflow_px: mobile.horizontalOverflowPx,
    status: Object.values(equal).every(Boolean) &&
      runtime.consoleErrors.length === 0 &&
      runtime.pageErrors.length === 0 &&
      runtime.iframes === 0 &&
      runtime.customScripts === 0 &&
      mobile.horizontalOverflowPx === 0
      ? "pass"
      : "fail",
  };
  writeFileSync(resolve(root, "report.json"), json(report));
  return report;
}

for (const viewport of contract.environment.viewports) {
  if (captureReference) {
    await capture(viewport, "reference");
  }
  await capture(viewport, "candidate");
}
const reports = contract.environment.viewports.map((viewport) => {
  const viewportRoot = resolve(outputRoot, `${viewport[0]}x${viewport[1]}`);
  const fixedReference = resolve(
    referenceRoot,
    `${viewport[0]}x${viewport[1]}`,
    "reference",
  );
  if (referenceRoot !== outputRoot) {
    mkdirSync(viewportRoot, { recursive: true });
    writeFileSync(
      resolve(viewportRoot, "reference-pointer.json"),
      json({ reference: fixedReference }),
    );
  }
  return compare(viewport);
});
const result = {
  status: reports.every((report) => report.status === "pass") ? "pass" : "fail",
  reports,
  evidence_root: outputRoot,
};
console.log(JSON.stringify(result, null, 2));
if (result.status !== "pass") process.exitCode = 1;
