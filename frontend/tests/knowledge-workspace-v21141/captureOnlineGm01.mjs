#!/usr/bin/env node

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright";

const referenceUrl =
  "https://6a8afc013497970234090688-prototype.inspire.bytedance.net/?file=welcome";
const candidateUrl = process.env.KNOWLEDGE_CANDIDATE_URL ??
  "http://127.0.0.1:4173/?studio=knowledge&file=welcome";
const outputRoot = resolve(
  process.env.KNOWLEDGE_GM01_OUTPUT ??
    "/Users/bytedance/.codex/runtime/knowledge-v21141-commercial-step-2/gm01-online/round15",
);

const capture = async (page, side, url, root) => {
  const consoleErrors = [];
  const pageErrors = [];
  console.log(`[capture] ${side} ${url}`);
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
  try {
    await page.waitForFunction(
      () =>
        document.querySelector("#root") &&
        (location.hostname.includes("inspire") ||
          document.querySelector("#root")?.textContent?.includes("Knowledge") ||
          document.querySelector("#root textarea")),
      undefined,
      { timeout: 20_000 },
    );
  } catch (error) {
    console.error(
      `[capture] ${side} wait failed: ${error}; console=${
        JSON.stringify(consoleErrors)
      } page=${JSON.stringify(pageErrors)} root=${
        (
          await page
            .locator("#root")
            .innerText()
            .catch(() => "")
        ).slice(0, 500)
      }`,
    );
    throw error;
  }
  await page.waitForFunction(
    () => document.fonts.status === "loaded",
    undefined,
    { timeout: 60_000 },
  );
  await page.waitForTimeout(1200);
  const snapshot = await page.evaluate(() => {
    const properties = [
      "fontFamily",
      "fontSize",
      "fontWeight",
      "lineHeight",
      "color",
      "backgroundColor",
      "border",
      "borderRadius",
      "boxShadow",
      "display",
      "position",
      "padding",
      "margin",
      "gap",
      "letterSpacing",
      "opacity",
      "overflow",
    ];
    const all = [...document.querySelectorAll("*")].map((element, index) => {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return {
        i: index,
        tag: element.tagName.toLowerCase(),
        id: element.id,
        cls: typeof element.className === "string" ? element.className : "",
        text: (element.textContent ?? "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 240),
        box: {
          x: box.x,
          y: box.y,
          width: box.width,
          height: box.height,
        },
        ...Object.fromEntries(
          properties.map((property) => [
            property,
            style[
              property.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`)
            ],
          ]),
        ),
      };
    });
    const cssRules = [];
    for (const sheet of [...document.styleSheets]) {
      try {
        cssRules.push(...[...sheet.cssRules].map((rule) => rule.cssText));
      } catch {
        cssRules.push(
          `/* inaccessible stylesheet: ${sheet.href ?? "inline"} */`,
        );
      }
    }
    const fonts = [...document.fonts].map((font) => ({
      family: font.family,
      weight: font.weight,
      style: font.style,
      status: font.status,
    }));
    return {
      url: location.href,
      title: document.title,
      bodyText: document.body.innerText,
      htmlClass: document.documentElement.className,
      bodyClass: document.body.className,
      scroll: {
        innerWidth,
        innerHeight,
        scrollWidth: document.documentElement.scrollWidth,
        scrollHeight: document.documentElement.scrollHeight,
      },
      all,
      css: cssRules.join("\n"),
      fonts,
      active: document.body.innerHTML,
    };
  });
  snapshot.consoleErrors = consoleErrors;
  snapshot.pageErrors = pageErrors;
  mkdirSync(root, { recursive: true });
  writeFileSync(
    resolve(root, `${side}.json`),
    `${JSON.stringify(snapshot, null, 2)}\n`,
  );
  await page.screenshot({
    path: resolve(root, `${side}.png`),
    fullPage: false,
  });
  return snapshot;
};

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const reference = await capture(
    await context.newPage(),
    "reference",
    referenceUrl,
    outputRoot,
  );
  const candidate = await capture(
    await context.newPage(),
    "candidate",
    candidateUrl,
    outputRoot,
  );
  writeFileSync(
    resolve(outputRoot, "capture-summary.json"),
    `${
      JSON.stringify(
        {
          reference: {
            url: reference.url,
            elements: reference.all.length,
            consoleErrors: reference.consoleErrors,
            pageErrors: reference.pageErrors,
          },
          candidate: {
            url: candidate.url,
            elements: candidate.all.length,
            consoleErrors: candidate.consoleErrors,
            pageErrors: candidate.pageErrors,
          },
        },
        null,
        2,
      )
    }\n`,
  );
} finally {
  await browser.close();
}
