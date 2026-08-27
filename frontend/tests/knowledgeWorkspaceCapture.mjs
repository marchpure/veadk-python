/**
 * Test-only 22-state capture and comparison harness.
 *
 * The BFF is intercepted with the same contract fixture as the journey test.
 * This deliberately reports pixel deltas; it does not turn prototype data into
 * a production fallback or claim real-service completion.
 */
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";
import playwright from "/Users/bytedance/node_modules/playwright/index.js";

const { chromium } = playwright;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const prototypeDir = process.env.KW_PROTOTYPE_CAPTURE_DIR;
const outputDir = process.env.KW_CAPTURE_OUTPUT_DIR || path.join(root, "docs/knowledge-workspace/evidence/captures");
const captureStates = [
  ["/?file=welcome", "welcome"],
  ["/?file=draft_dash_anta", "draft"],
  ["/?file=draft_dash_anta&run_state=success", "draft"],
  ["/?file=draft_dash_anta&run_state=success&modal=publish", "draft"],
  ["/?file=draft_dash_anta&run_state=failed", "draft"],
  ["/?file=draft_dash_anta&state=permission", "draft"],
  ["/?file=draft_dash_anta&state=connection_error", "draft"],
  ["/?file=draft_dash_anta&state=upgrade", "draft"],
  ["/?file=draft_dash_anta&modal=advanced", "draft"],
  ["/?file=draft_dash_anta&modal=test_records", "draft"],
  ["/?file=draft_dash_anta&modal=tools", "draft"],
  ["/?file=pub_dash_anta", "published"],
  ["/?file=pub_dash_anta&modal=agent", "published"],
  ["/?file=pub_dash_anta&modal=share_run", "published"],
  ["/?file=pub_dash_anta&modal=instructions", "published"],
  ["/?file=pub_dash_anta&modal=versions", "published"],
  ["/?file=draft_sop_bluetooth", "draft"],
  ["/?file=draft_sop_haidilao", "draft"],
  ["/?file=skill_new", "skill_new"],
  ["/?file=skill_new&scenario=anta", "skill_new"],
  ["/?file=skill_new&scenario=zhiji", "skill_new"],
  ["/?file=skill_new&scenario=haidilao", "skill_new"],
].map(([stateUrl, route]) => ({ stateUrl, route }));

function requiredDir() {
  assert.ok(prototypeDir, "KW_PROTOTYPE_CAPTURE_DIR must point at downloaded prototype PNGs");
  return path.resolve(prototypeDir);
}

function decodePng(buffer) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  assert.deepEqual(buffer.subarray(0, 8), signature);
  let offset = 8;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idat = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    offset += length + 12;
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      assert.equal(data[8], 8, "only 8-bit PNG captures are supported");
      colorType = data[9];
      assert.ok(colorType === 2 || colorType === 6, "only RGB/RGBA PNG captures are supported");
    } else if (type === "IDAT") {
      idat.push(data);
    } else if (type === "IEND") break;
  }
  assert.ok(colorType === 2 || colorType === 6);
  const compressed = Buffer.concat(idat);
  const scanlines = inflateSync(compressed);
  const sourceChannels = colorType === 6 ? 4 : 3;
  const sourceStride = width * sourceChannels;
  const pixels = Buffer.alloc(height * width * 4);
  let source = 0;
  let previous = Buffer.alloc(sourceStride);
  for (let row = 0; row < height; row++) {
    const filter = scanlines[source++];
    const current = Buffer.alloc(sourceStride);
    for (let x = 0; x < sourceStride; x++) {
      const raw = scanlines[source++];
      const left = x >= sourceChannels ? current[x - sourceChannels] : 0;
      const up = previous[x] || 0;
      const upperLeft = x >= sourceChannels ? previous[x - sourceChannels] : 0;
      if (filter === 0) current[x] = raw;
      else if (filter === 1) current[x] = (raw + left) & 255;
      else if (filter === 2) current[x] = (raw + up) & 255;
      else if (filter === 3) current[x] = (raw + Math.floor((left + up) / 2)) & 255;
      else if (filter === 4) {
        const estimate = left + up - upperLeft;
        const distanceLeft = Math.abs(estimate - left);
        const distanceUp = Math.abs(estimate - up);
        const distanceUpperLeft = Math.abs(estimate - upperLeft);
        const predictor = distanceLeft <= distanceUp && distanceLeft <= distanceUpperLeft
          ? left
          : distanceUp <= distanceUpperLeft ? up : upperLeft;
        current[x] = (raw + predictor) & 255;
      } else throw new Error(`Unsupported PNG filter ${filter}`);
    }
    for (let x = 0; x < width; x++) {
      const sourceOffset = x * sourceChannels;
      const targetOffset = (row * width + x) * 4;
      pixels[targetOffset] = current[sourceOffset];
      pixels[targetOffset + 1] = current[sourceOffset + 1];
      pixels[targetOffset + 2] = current[sourceOffset + 2];
      pixels[targetOffset + 3] = sourceChannels === 4 ? current[sourceOffset + 3] : 255;
    }
    previous = current;
  }
  return { width, height, data: pixels };
}

function digestPixels(left, right) {
  if (left.width !== right.width || left.height !== right.height) {
    return {
      pixels: left.width * left.height,
      reference_pixels: right.width * right.height,
      differing_pixels: null,
      differing_ratio: null,
      mean_absolute_rgb_delta: null,
      dimension_mismatch: true,
    };
  }
  let differing = 0;
  let absolute = 0;
  for (let index = 0; index < left.data.length; index += 4) {
    const delta = Math.abs(left.data[index] - right.data[index])
      + Math.abs(left.data[index + 1] - right.data[index + 1])
      + Math.abs(left.data[index + 2] - right.data[index + 2]);
    if (delta) differing += 1;
    absolute += delta;
  }
  return {
    pixels: left.width * left.height,
    differing_pixels: differing,
    differing_ratio: differing / (left.width * left.height),
    mean_absolute_rgb_delta: absolute / (left.width * left.height * 3),
  };
}

async function main() {
  const references = requiredDir();
  await mkdir(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.route("**/oauth2/userinfo", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ sub: "capture-user", email: "capture@example.com" }),
  }));
  await page.route("**/web/auth-config", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ providers: [] }),
  }));
  const connection = {
    connection_id: "conn-contract",
    connector_key: "contract-http",
    display_name: "Contract API",
    scope: "personal",
    status: "ready",
    definition_version: "1",
    profile: { account: "capture-fixture" },
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
  };
  const draft = {
    draft_id: "draft-contract",
    goal: "让支持工程师排查线上告警并给出处理建议",
    trial_task: "查询最近一条告警",
    connection_ids: [connection.connection_id],
    lifecycle: "generated",
    current_revision_id: "revision-contract",
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
  };
  const revision = {
    revision_id: "revision-contract",
    draft_id: draft.draft_id,
    number: 1,
    skill_name: "support-skill",
    sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    created_at: "2026-08-27T00:00:00Z",
  };
  const envelope = (data) => JSON.stringify({ data, meta: { request_id: "capture" } });
  const errorEnvelope = (code, message, retryable = false) => JSON.stringify({
    error: { code, message, retryable },
    meta: { request_id: "capture" },
  });
  await page.route("**/api/knowledge/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const state = new URL(page.url()).searchParams;
    const runState = state.get("run_state") || "";
    const resourceState = state.get("state") || "";
    const stateDraft = {
      ...draft,
      lifecycle: runState === "failed" ? "failed" : "generated",
    };
    if (url.pathname === "/api/knowledge/v1/connector-definitions") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([{
        connector_key: "contract-http",
        version: "1",
        display_name: "Contract API",
        status: "verified",
        capabilities: ["validate", "discover", "http"],
        config_schema: { type: "object", properties: {} },
        auth_schema: { type: "object", properties: {} },
      }]) });
    } else if (url.pathname === "/api/knowledge/v1/connections") {
      await route.fulfill({ status: request.method() === "POST" ? 201 : 200, headers: { ETag: "capture-v1" }, contentType: "application/json", body: envelope(request.method() === "POST" ? connection : [connection]) });
    } else if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([stateDraft]) });
    } else if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}`) {
      if (resourceState === "permission") {
        await route.fulfill({
          status: 403,
          contentType: "application/json",
          body: errorEnvelope("FORBIDDEN", "当前账号没有访问该资源的权限。"),
        });
      } else if (resourceState === "connection_error") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: errorEnvelope("CONNECTION_NOT_READY", "连接尚未可用，请先完成验证。", true),
        });
      } else if (resourceState === "upgrade") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: errorEnvelope("PUBLISH_GATE_FAILED", "当前能力需要升级服务配置。"),
        });
      } else {
        await route.fulfill({ status: 200, headers: { ETag: "capture-v1" }, contentType: "application/json", body: envelope(stateDraft) });
      }
    } else if (url.pathname === `/api/knowledge/v1/skills/drafts/${draft.draft_id}/revisions`) {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([revision]) });
    } else {
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "NOT_FOUND", message: "capture route missing", retryable: false }, meta: { request_id: "capture" } }) });
    }
  });

  const results = [];
  for (const [index, capture] of captureStates.entries()) {
    const query = new URLSearchParams(new URL(capture.stateUrl, "http://capture.local").search);
    query.set("view", "knowledge-workspace");
    if (capture.route === "draft" || capture.route === "published") {
      query.set("draftId", "draft-contract");
    } else {
      query.delete("draftId");
    }
    const url = `http://127.0.0.1:5174/?${query}`;
    await page.goto(url);
    const actualPath = path.join(outputDir, `${String(index + 1).padStart(2, "0")}.png`);
    await page.screenshot({ path: actualPath, fullPage: true });
    const actual = decodePng(await readFile(actualPath));
    const reference = decodePng(await readFile(path.join(references, `${String(index + 1).padStart(2, "0")}.png`)));
    results.push({
      index: index + 1,
      state_url: capture.stateUrl,
      route: capture.route,
      ...digestPixels(actual, reference),
    });
  }
  await writeFile(path.join(outputDir, "report.json"), JSON.stringify({
    contract_fixture: true,
    visual_diff_mode: "RGBA per-pixel absolute delta",
    states: results,
  }, null, 2));
  await browser.close();
  console.log(JSON.stringify({ contract_fixture: true, states: results.length, output_dir: outputDir }));
}

await main();
