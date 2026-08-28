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

const expectedModalState = {
  publish: { selector: '[data-state-modal="publish"]', text: "发布门禁检查" },
  advanced: { selector: '[data-state-modal="advanced"]', text: "高级设置 / 诊断" },
  test_records: { selector: '[data-state-modal="test_records"]', text: "测试记录" },
  tools: { selector: '[data-state-modal="tools"]', text: "数据与工具" },
  agent: { selector: '[data-state-modal="agent"]', text: "选择绑定目标 Agent" },
  share_run: { selector: '[data-state-modal="share_run"]', text: "分享本次结果" },
  instructions: { selector: '[data-state-modal="instructions"]', text: "调用说明" },
  versions: { selector: '[data-state-modal="versions"]', text: "版本记录" },
};

const expectedStateEvidence = {
  welcome: [".kw-welcome-dashboard-heading h1"],
  draft: [".kw-draft-section-heading h2", ".kw-chat-title"],
  success: [".kw-run-state-card.is-success", ".kw-success-revision"],
  publish: ['[data-state-modal="publish"]'],
  failed: [".kw-run-state-card.is-failed", "text=重试本次运行"],
  permission: [".kw-state-dialog.is-permission", "text=提交申请"],
  connection_error: [".kw-state-dialog.is-connection_error", "text=测试并重连"],
  upgrade: [".kw-upgrade-banner", "text=发现基础模型或版本更新"],
  advanced: ['[data-state-modal="advanced"] .kw-advanced', "text=连接诊断"],
  test_records: ['[data-state-modal="test_records"] .kw-records table'],
  tools: ['[data-state-modal="tools"] .kw-tools', "text=数据与工具"],
  published: [".kw-published-badge", ".kw-published h1"],
  agent: ['[data-state-modal="agent"] .kw-agent-layout', "text=选择绑定目标 Agent"],
  share_run: ['[data-state-modal="share_run"] .kw-share-warning', "text=暂无分享链接"],
  instructions: ['[data-state-modal="instructions"] .kw-instructions', "text=业务用途"],
  versions: ['[data-state-modal="versions"]', "text=数据来源"],
  sop_bluetooth: [".kw-draft-section-heading h2", "text=蓝牙"],
  sop_haidilao: [".kw-draft-section-heading h2", "text=巡检"],
  skill_new: [".kw-skill-new-heading h1", ".kw-upload-box"],
};

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
    connector_key: "oracle",
    display_name: "Oracle ERP 销售数据集",
    scope: "personal",
    status: "ready",
    definition_version: "1",
    profile: { account: "capture-fixture" },
    created_at: "2026-08-27T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
  };
  const draft = {
    draft_id: "draft-contract",
    goal: "区域经理使用，希望定位门店毛利异常与退货情况。",
    trial_task: "分析华东区本周退货率最高的 5 家门店，并列出其核心导致毛利下降的产品。",
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
    skill_name: "区域异常经营分析",
    sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    created_at: "2026-08-27T00:00:00Z",
  };
  const welcomeDrafts = [
    draft,
    {
      ...draft,
      draft_id: "draft-bluetooth",
      display_name: "蓝牙断连排查",
      goal: "售后专家诊断蓝牙故障，分析硬件衰减与固件问题。",
      trial_task: "排查 VIN LS68892019 的蓝牙反复断连问题，对比历史记录判断是否为天线硬件衰减。",
      current_revision_id: "revision-contract",
    },
    {
      ...draft,
      draft_id: "draft-haidilao",
      display_name: "门店卫生巡检",
      goal: "门店经理使用，希望查询卫生巡检得分并下发整改通报。",
      trial_task: "获取 SH-0021 门店今日巡检的扣分明细，并下发整改通知。",
      current_revision_id: "revision-contract",
    },
    {
      ...draft,
      draft_id: "draft-sales",
      display_name: "销售业务分析",
      goal: "分析师使用，希望对销售指标进行语义建模。",
      trial_task: "计算大区级别的销售额与净利润。",
      current_revision_id: "revision-contract",
    },
    {
      ...draft,
      draft_id: "draft-relationship",
      display_name: "销售关系分析",
      goal: "风控使用，希望挖掘经销商与客户的深层关系网络。",
      trial_task: "查询某客户名下的所有关联交易路径。",
      current_revision_id: "revision-contract",
    },
    {
      ...draft,
      draft_id: "draft-graph",
      display_name: "销售业务知识图谱",
      goal: "业务专家使用，希望定义销售领域的本体。",
      trial_task: "添加客户到订单的下单关系。",
      current_revision_id: "revision-contract",
    },
    {
      ...draft,
      draft_id: "draft-recruitment",
      display_name: "全球招聘供需",
      goal: "HRBP 使用，希望监控全球各站点的 HC 分布与供需状态。",
      trial_task: "查询越南区域的销售 HC 缺口，并给出填补建议。",
      current_revision_id: "revision-contract",
    },
    {
      ...draft,
      draft_id: "draft-finance",
      display_name: "金融行情监控",
      goal: "交易员使用，希望实时监控全球市场指数波动并触发风险告警。",
      trial_task: "监控 VIX 指数，若单日涨幅过高则触发警告。",
      current_revision_id: "revision-contract",
    },
    {
      ...draft,
      draft_id: "draft-conversion",
      display_name: "渠道转化趋势",
      goal: "营销人员使用，希望分析各渠道的转化漏斗。",
      trial_task: "查询微信与抖音渠道的获客成本与转化率差异。",
      current_revision_id: "revision-contract",
    },
  ];
  welcomeDrafts[0].display_name = "区域异常经营分析";
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
    const file = state.get("file") || "";
    const stateDraft = {
      ...draft,
      ...(file.includes("bluetooth") ? {
        goal: "售后专家诊断蓝牙故障，分析硬件衰减与固件问题。",
        trial_task: "排查 VIN LS68892019 的蓝牙反复断连问题，对比历史记录判断是否为天线硬件衰减。",
      } : file.includes("haidilao") ? {
        goal: "门店经理使用，希望查询卫生巡检得分并下发整改通报。",
        trial_task: "获取 SH-0021 门店今日巡检的扣分明细，并下发整改通知。",
      } : {}),
      lifecycle: runState === "failed"
        ? "failed"
        : runState === "success"
          ? "ready_to_publish"
          : "generated",
    };
    if (url.pathname === "/api/knowledge/v1/connector-definitions") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope([{
        connector_key: "oracle",
        version: "1",
        display_name: "Oracle Database",
        status: "verified",
        capabilities: ["validate", "discover", "http"],
        config_schema: { type: "object", properties: {} },
        auth_schema: { type: "object", properties: {} },
      }]) });
    } else if (url.pathname === "/api/knowledge/v1/connections") {
      await route.fulfill({ status: request.method() === "POST" ? 201 : 200, headers: { ETag: "capture-v1" }, contentType: "application/json", body: envelope(request.method() === "POST" ? connection : [connection]) });
    } else if (url.pathname === "/api/knowledge/v1/skills/drafts" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: envelope(welcomeDrafts) });
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

  const requestedIndices = process.env.KW_CAPTURE_INDICES
    ? new Set(process.env.KW_CAPTURE_INDICES.split(",").map((value) => Number(value.trim())).filter(Boolean))
    : null;
  const selectedStates = captureStates
    .map((capture, index) => ({ capture, index }))
    .filter(({ index }) => !requestedIndices || requestedIndices.has(index + 1));
  const results = [];
  for (const { capture, index } of selectedStates) {
    const query = new URLSearchParams(new URL(capture.stateUrl, "http://capture.local").search);
    query.set("view", "knowledge-workspace");
    if (capture.route === "draft" || capture.route === "published") {
      query.set("draftId", "draft-contract");
    } else {
      query.delete("draftId");
    }
    const url = `http://127.0.0.1:5174/?${query}`;
    await page.goto(url);
    await page.locator(".kw-shell").waitFor({ state: "visible" });
    if (capture.route === "welcome") {
      await page.locator(".kw-welcome-grid").waitFor({ state: "visible", timeout: 10_000 });
    } else if (capture.route === "skill_new") {
      await page.locator(".kw-create-form").waitFor({ state: "visible", timeout: 10_000 });
    } else {
      await page.locator(capture.route === "published" ? ".kw-published" : ".kw-draft-center")
        .waitFor({ state: "visible", timeout: 10_000 });
    }
    const renderCheck = await page.evaluate(({ route, stateUrl, expectedModalState, expectedStateEvidence }) => {
      const visible = (selector) => {
        const element = document.querySelector(selector);
        if (!element) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const dialogs = [...document.querySelectorAll('[role="dialog"]')].filter((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      });
      const dialogLabels = dialogs.map((element) => element.getAttribute("aria-label"));
      const center = document.querySelector(".kw-draft-center");
      const overlay = document.querySelector(".kw-state-overlay");
      const centerRect = center?.getBoundingClientRect();
      const overlayRect = overlay?.getBoundingClientRect();
      const overlayCoversCenter = Boolean(centerRect && overlayRect
        && Math.abs(overlayRect.left - centerRect.left) < 1
        && Math.abs(overlayRect.top - centerRect.top) < 1
        && Math.abs(overlayRect.right - centerRect.right) < 1
        && Math.abs(overlayRect.bottom - centerRect.bottom) < 1);
      const chat = document.querySelector(".kw-chat");
      const chatWidth = chat?.getBoundingClientRect().width || 0;
      const params = new URLSearchParams(stateUrl.split("?")[1] || "");
      const modal = params.get("modal");
      const modalElement = modal
        ? document.querySelector(expectedModalState[modal]?.selector || "")
        : null;
      const modalRect = modalElement?.getBoundingClientRect();
      const file = params.get("file") || "";
      const evidenceKey = modal
        || (file === "welcome" ? "welcome"
          : file === "skill_new" ? "skill_new"
            : file === "pub_dash_anta" ? "published"
              : file === "draft_sop_bluetooth" ? "sop_bluetooth"
                : file === "draft_sop_haidilao" ? "sop_haidilao"
                  : params.get("run_state") === "success" ? "success"
                    : params.get("run_state") === "failed" ? "failed"
                      : params.get("state") || "draft");
      return {
        shell: visible(".kw-shell"),
        route,
        state_url: stateUrl,
        welcome: route === "welcome"
          ? visible(".kw-welcome-grid")
            && document.querySelectorAll(".kw-welcome-card").length > 0
            && !document.querySelector(".kw-draft-center")
            && !document.querySelector(".kw-create-form")
          : false,
        draft: route === "draft"
          ? visible(".kw-draft-center")
            && visible(".kw-draft-artifact-card")
            && visible(".kw-chat")
            && !document.querySelector(".kw-welcome-grid")
            && !document.querySelector(".kw-create-form")
          : false,
        published: route === "published"
          ? visible(".kw-published")
            && Boolean(document.querySelector(".kw-published h1"))
            && !document.querySelector(".kw-draft-center")
            && !document.querySelector(".kw-create-form")
          : false,
        skill_new: route === "skill_new"
          ? visible(".kw-create-form")
            && visible(".kw-upload-box")
            && !document.querySelector(".kw-draft-center")
            && !document.querySelector(".kw-published")
          : false,
        dialog_count: dialogLabels.length,
        dialog_labels: dialogLabels,
        modal: route === "draft" || route === "published"
          ? new URLSearchParams(stateUrl.split("?")[1] || "").get("modal") || ""
          : "",
        modal_selector_visible: (() => {
          const modal = new URLSearchParams(stateUrl.split("?")[1] || "").get("modal");
          if (!modal || !expectedModalState[modal]) return true;
          const element = document.querySelector(expectedModalState[modal].selector);
          if (!element) return false;
          const style = window.getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
        })(),
        modal_text_present: (() => {
          const modal = new URLSearchParams(stateUrl.split("?")[1] || "").get("modal");
          if (!modal || !expectedModalState[modal]) return true;
          const element = document.querySelector(expectedModalState[modal].selector);
          return Boolean(element && element.textContent?.includes(expectedModalState[modal].text));
        })(),
        has_state_overlay: Boolean(overlay),
        overlay_covers_center: overlayCoversCenter,
        chat_width: Math.round(chatWidth),
        modal_geometry: modalRect
          ? {
            left: Math.round(modalRect.left),
            top: Math.round(modalRect.top),
            width: Math.round(modalRect.width),
            height: Math.round(modalRect.height),
          }
          : null,
        evidence_key: evidenceKey,
        evidence: (expectedStateEvidence[evidenceKey] || []).map((selector) => {
          if (selector.startsWith("text=")) {
            return [...document.querySelectorAll("body *")].some((element) => {
              const style = window.getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return element.textContent?.includes(selector.slice(5))
                && style.display !== "none"
                && style.visibility !== "hidden"
                && rect.width > 0
                && rect.height > 0;
            });
          }
          return visible(selector);
        }),
      };
    }, {
      route: capture.route,
      stateUrl: capture.stateUrl,
      expectedModalState,
      expectedStateEvidence,
    });
    assert.equal(renderCheck.shell, true, `${capture.stateUrl}: shell did not render`);
    if (capture.route === "welcome") assert.equal(renderCheck.welcome, true, `${capture.stateUrl}: welcome did not render`);
    if (capture.route === "draft") {
      assert.equal(renderCheck.draft, true, `${capture.stateUrl}: draft did not render`);
      assert.ok(renderCheck.chat_width >= 370, `${capture.stateUrl}: chat rail is not 380px: ${JSON.stringify(renderCheck)}`);
      if (capture.stateUrl.includes("state=permission") || capture.stateUrl.includes("state=connection_error")) {
        assert.equal(renderCheck.has_state_overlay, true, `${capture.stateUrl}: state overlay did not render`);
        assert.equal(renderCheck.overlay_covers_center, true, `${capture.stateUrl}: state overlay does not cover draft center`);
      }
    }
    if (capture.route === "published") assert.equal(renderCheck.published, true, `${capture.stateUrl}: published did not render`);
    if (new URL(capture.stateUrl, "http://capture.local").searchParams.has("modal")) {
      assert.equal(renderCheck.dialog_count, 1, `${capture.stateUrl}: modal did not render`);
      assert.equal(renderCheck.modal_selector_visible, true, `${capture.stateUrl}: expected modal surface did not render`);
      assert.equal(renderCheck.modal_text_present, true, `${capture.stateUrl}: expected modal content did not render`);
      if (capture.stateUrl.includes("modal=versions")) {
        assert.ok(renderCheck.modal_geometry, `${capture.stateUrl}: version modal geometry missing`);
        assert.ok(renderCheck.modal_geometry.width >= 400, `${capture.stateUrl}: version modal is not a centered modal`);
        assert.ok(renderCheck.modal_geometry.left > 400, `${capture.stateUrl}: version modal is incorrectly docked`);
      }
    }
    if (capture.route === "skill_new") assert.equal(renderCheck.skill_new, true, `${capture.stateUrl}: skill form did not render`);
    assert.ok(
      renderCheck.evidence.every(Boolean),
      `${capture.stateUrl}: state evidence did not render: ${JSON.stringify(renderCheck)}`,
    );
    const actualPath = path.join(outputDir, `${String(index + 1).padStart(2, "0")}.png`);
    await page.screenshot({ path: actualPath, fullPage: true });
    const actual = decodePng(await readFile(actualPath));
    const reference = decodePng(await readFile(path.join(references, `${String(index + 1).padStart(2, "0")}.png`)));
    results.push({
      index: index + 1,
      state_url: capture.stateUrl,
      route: capture.route,
      render_check: renderCheck,
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
