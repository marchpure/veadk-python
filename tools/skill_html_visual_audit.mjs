import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

const site = path.resolve(process.argv[2] ?? "/tmp/veadk-w3-html-acceptance");
const output = path.resolve(process.argv[3] ?? "/tmp/veadk-w3-html-evidence");
fs.mkdirSync(output, { recursive: true });
const visualEvaluation = JSON.parse(
  fs.readFileSync(path.join(site, "visual-evaluation.json"), "utf8"),
);
const templates = ["dashboard", "semantic", "sop", "knowledge", "graph-ontology", "monitoring"];
const scenarios = ["primary", "alternate"];
const viewports = [
  ["desktop", { width: 1440, height: 900 }],
  ["studio", { width: 1024, height: 768 }],
  ["mobile", { width: 390, height: 844 }],
];

const browser = await chromium.launch({ headless: true });
const report = [];
for (const scenario of scenarios) for (const template of templates) {
  const page = await browser.newPage();
  const consoleErrors = [];
  const externalRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("request", (request) => {
    if (request.url().startsWith("http://") || request.url().startsWith("https://")) {
      externalRequests.push(request.url());
    }
  });
  for (const [viewportName, viewport] of viewports) {
    await page.setViewportSize(viewport);
    const fileTemplate = template.replaceAll("-", "_");
    await page.goto(`file://${site}/${fileTemplate}-${scenario}.html`, { waitUntil: "load" });
    const facts = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      scrollHeight: document.documentElement.scrollHeight,
      bodyText: document.body.innerText,
      scripts: document.scripts.length,
      iframes: document.querySelectorAll("iframe").length,
      artifact: Boolean(document.querySelector("[data-template][data-view-model-digest]")),
      events: document.querySelectorAll("[data-artifact-event]").length,
      eventTypes: [...new Set([...document.querySelectorAll("[data-artifact-event]")].map((node) => node.getAttribute("data-artifact-event")))].sort(),
      direction: document.querySelector("[data-direction]")?.getAttribute("data-direction") ?? null,
      visualProfile: document.querySelector("[data-visual-profile]")?.getAttribute("data-visual-profile") ?? null,
      stateCoverage: Boolean(document.querySelector(".state-coverage")),
    }));
    const filename = `${template}-${scenario}-${viewportName}.png`;
    await page.screenshot({ path: path.join(output, filename), fullPage: true });
    report.push({
      template,
      scenario,
      viewport: viewportName,
      screenshot: filename,
      horizontalOverflow: facts.scrollWidth > facts.clientWidth + 1,
      scripts: facts.scripts,
      iframes: facts.iframes,
      artifact: facts.artifact,
      declarativeEvents: facts.events,
      eventTypes: facts.eventTypes,
      direction: facts.direction,
      visualProfile: facts.visualProfile,
      stateCoverage: facts.stateCoverage,
      visualScore: visualEvaluation.find(
        (item) => item.template === template && item.scenario === scenario,
      )?.attempts.at(-1)?.score ?? null,
      visualAttempts: visualEvaluation.find(
        (item) => item.template === template && item.scenario === scenario,
      )?.attempts ?? [],
      textLength: facts.bodyText.length,
      consoleErrors: [...consoleErrors],
      externalRequests: [...externalRequests],
    });
  }
  await page.close();
}
await browser.close();
fs.writeFileSync(path.join(output, "visual-audit.json"), JSON.stringify(report, null, 2));
const failures = report.filter((item) =>
  item.horizontalOverflow ||
  item.scripts !== 0 ||
  item.iframes !== 0 ||
  !item.artifact ||
  item.declarativeEvents === 0 ||
  !item.stateCoverage ||
  !item.direction ||
  item.consoleErrors.length ||
  item.externalRequests.length
);
console.log(JSON.stringify({ output, screenshots: report.length, failures }, null, 2));
if (failures.length) process.exit(1);
