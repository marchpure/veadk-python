import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const baseURL = process.env.OPENVIKING_BROWSER_URL || "http://127.0.0.1:38113";
const upstream = process.env.OPENVIKING_E2E_BASE_URL;
const apiKey = process.env.OPENVIKING_E2E_API_KEY;
const evidenceDir = new URL(
  "../../docs/knowledge-workspace/evidence/openviking-integration-acceptance/",
  import.meta.url,
);
const screenshotDir = new URL("screenshots/", evidenceDir);

if (!upstream || !apiKey) {
  throw new Error("OPENVIKING_E2E_BASE_URL and OPENVIKING_E2E_API_KEY are required");
}

await mkdir(screenshotDir, { recursive: true });
const stamp = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
const results = [];

async function run(viewport, label, mutate) {
  const runStamp = `${stamp}-${label}`;
  const profileName = `Browser acceptance ${runStamp}`;
  const filename = `browser-${runStamp}.md`;
  const resourceName = filename.replace(/\.md$/, "");
  const canary = `OV_BROWSER_${runStamp.replaceAll("-", "_")}`;
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const apiBodies = [];
  const openVikingErrors = [];
  page.on("response", async (response) => {
    if (!response.url().includes("/api/knowledge/v1/openviking/")) return;
    try {
      const body = await response.text();
      apiBodies.push(body);
      if (
        [404, 409].includes(response.status()) &&
        /profile not found|PROFILE_NOT_READY/i.test(body)
      ) {
        openVikingErrors.push({
          status: response.status(),
          path: new URL(response.url()).pathname,
        });
      }
    } catch {
      // Navigation can dispose response bodies; the visible UI remains asserted below.
    }
  });
  page.on("dialog", (dialog) => dialog.accept());
  const check = {
    viewport: label,
    status: "FAIL",
    no_openviking_request_interception: true,
  };
  try {
    await page.goto(`${baseURL}/?view=knowledge-workspace`, {
      waitUntil: "networkidle",
    });
    await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
    check.knowledge_workspace_direct_url = true;

    await page.evaluate(() => {
      localStorage.setItem("openviking.activeProfileId", "revoked-or-missing-profile");
    });
    await page.goto(`${baseURL}/?view=openviking`, { waitUntil: "networkidle" });
    await page.locator(".openviking-studio").waitFor();
    check.stale_profile_recovered = true;
    await page.getByRole("button", { name: "Connection", exact: true }).click();

    if (mutate) {
      await page.getByLabel("Name").fill(profileName);
      await page.getByLabel("Base URL").fill(upstream);
      const apiKeyInput = page.getByLabel("API key");
      assert.equal(await apiKeyInput.getAttribute("type"), "password");
      await apiKeyInput.fill(apiKey);
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      await page.waitForFunction(
        (name) =>
          [...document.querySelectorAll('select[aria-label="OpenViking profile"] option')]
            .some((option) => option.selected && option.textContent === name),
        profileName,
        { timeout: 60_000 },
      );
      check.profile_created_ready = true;
      check.api_key_masked = apiBodies.every((body) => !body.includes(apiKey));

      await page.getByRole("button", { name: "Resources", exact: true }).click();
      await page.getByRole("button", { name: "Import resource", exact: true }).click();
      await page.getByRole("button", { name: "Manual Text", exact: true }).click();
      await page.getByLabel("File name").fill(filename);
      await page.getByLabel("Text content").fill(`# Browser acceptance\n\n${canary}\n`);
      await page.getByRole("button", { name: "Start Processing" }).click();
      await page.getByRole("button", { name: "Tasks", exact: true }).click();
      await page.getByText("Resource processing").first().waitFor({ timeout: 60_000 });
      check.real_task_history = true;

      await page.goto(`${baseURL}/?view=openviking`, { waitUntil: "networkidle" });
      assert.ok(apiBodies.some((body) => body.includes(profileName)));
      check.refresh_recovery = true;
      if (label === "desktop-1440x900") {
        await page.getByRole("button", { name: "Resources", exact: true }).click();
      }
      const folder = page.getByRole("treeitem", { name: new RegExp(resourceName) }).first();
      await folder.waitFor({ timeout: 120_000 });
      await folder.click();
      const leaf = page.getByRole("treeitem", { name: new RegExp(filename) }).first();
      await leaf.waitFor({ timeout: 30_000 });
      await leaf.click();
      await page.getByText(canary, { exact: false }).waitFor({ timeout: 30_000 });
      check.tree_and_preview = true;

      await page.getByRole("button", { name: "Retrieval", exact: true }).click();
      await page.getByRole("textbox").fill(canary);
      await page.keyboard.press("Enter");
      await page.getByRole("heading", { name: /Search Results/ }).waitFor({
        timeout: 120_000,
      });
      check.search = true;

      await page.getByRole("button", { name: "Resources", exact: true }).click();
      await folder.waitFor();
      await folder.click();
      await leaf.waitFor();
      await leaf.click();
      let deleted = false;
      for (let attempt = 0; attempt < 12 && !deleted; attempt += 1) {
        const responsePromise = page.waitForResponse((response) =>
          response.url().includes("/operations/fs_delete"),
        );
        await page.getByRole("button", { name: "Delete resource" }).click();
        const response = await responsePromise;
        deleted = response.status() === 200;
        if (!deleted) await page.waitForTimeout(5_000);
      }
      assert.equal(deleted, true);
      check.delete = true;

      await page.getByRole("button", { name: "加入 Skill 上下文" }).click();
      await page.getByRole("heading", { name: "创建一个新技能" }).waitFor();
      await page.getByRole("button", { name: `移除 ${profileName}` }).waitFor();
      check.skill_creator_selection = true;

      await page.goto(`${baseURL}/?view=openviking`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Connection", exact: true }).click();
      await page.getByRole("button", { name: "Revoke" }).click();
      await page.getByRole("heading", { name: profileName, exact: true }).waitFor({
        state: "detached",
      });
      check.revoke_ui = true;
    } else {
      assert.equal(await page.locator(".openviking-studio").count(), 1);
      assert.ok(await page.getByRole("button", { name: "Resources" }).count());
      assert.ok(await page.getByRole("button", { name: "Retrieval" }).count());
      check.workspace_controls = true;
    }

    assert.equal(apiBodies.some((body) => body.includes(apiKey)), false);
    assert.deepEqual(openVikingErrors, []);
    check.no_profile_404_or_409 = true;
    check.api_responses_secret_free = true;
    check.status = "PASS";
    await page.screenshot({
      path: new URL(`${label}.png`, screenshotDir).pathname,
      fullPage: true,
    });
  } catch (error) {
    check.error = error instanceof Error ? error.message : String(error);
    await page.screenshot({
      path: new URL(`${label}-failure.png`, screenshotDir).pathname,
      fullPage: true,
    });
  } finally {
    results.push(check);
    await browser.close();
  }
}

await run({ width: 1440, height: 900 }, "desktop-1440x900", true);
await run({ width: 390, height: 844 }, "narrow-390x844", true);

const output = {
  status: results.every((item) => item.status === "PASS") ? "PASS" : "FAIL",
  real_services: true,
  request_interception: false,
  results,
};
await writeFile(
  new URL("browser-results.json", evidenceDir),
  `${JSON.stringify(output, null, 2)}\n`,
);
console.log(JSON.stringify(output));
process.exitCode = output.status === "PASS" ? 0 : 1;
