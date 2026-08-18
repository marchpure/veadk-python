import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const defaultByaanRepo =
  process.env.BYAAN_REPO ||
  "/Users/bytedance/worktrees/session-f-byaan-knowledge-center-20260818";
const playwrightModule =
  process.env.PLAYWRIGHT_MODULE ||
  path.join(defaultByaanRepo, "client/node_modules/playwright/index.mjs");

const reportDir = process.env.REPORT_DIR
  ? path.resolve(process.env.REPORT_DIR)
  : path.join(repoRoot, "docs/knowledge-center/session-reports/live");
const screenshotDir = path.join(reportDir, "screenshots");
const resultPath = path.join(reportDir, "knowledge-center-live-result.json");
const seedResultPath = process.env.BYAAN_SEED_RESULT
  ? path.resolve(process.env.BYAAN_SEED_RESULT)
  : path.join(
      defaultByaanRepo,
      "artifacts/data-modeling/knowledge-center/session-reports/live/byaan-live-seed-result.json",
    );

const studioBaseUrl = requiredEnv("VEADK_STUDIO_URL").replace(/\/$/, "");
const byaanFrontendUrl = requiredEnv("DATASTUDIO_EMBED_URL").replace(/\/$/, "");
const byaanApiUrl = requiredEnv("DATASTUDIO_BASE_URL").replace(/\/$/, "");
const byaanApiKey = requiredEnv("BYAAN_MCP_API_KEY");
const dataStudioApiKey = requiredEnv("DATASTUDIO_API_KEY");
const byaanTeamEmail = process.env.MASTER_USER_EMAIL || "";
const byaanTeamPassword = process.env.MASTER_USER_PASSWORD || "";

const viewports = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "mobile-390", width: 390, height: 844 },
];

const sensitiveValues = [
  byaanApiKey,
  dataStudioApiKey,
  byaanTeamEmail,
  byaanTeamPassword,
  process.env.MODEL_AGENT_API_KEY || "",
  process.env.ARK_API_KEY || "",
  process.env.OPENAI_API_KEY || "",
].filter((value) => value && value.length >= 8);

function requiredEnv(name) {
  const value = (process.env[name] || "").trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function readJson(file) {
  return JSON.parse(await readFile(file, "utf8"));
}

async function writeJson(file, value) {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, JSON.stringify(value, null, 2) + "\n", "utf8");
}

function redact(value) {
  let text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  for (const secret of sensitiveValues) {
    text = text.split(secret).join("<redacted>");
  }
  return text;
}

async function api(base, route, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${base}${route}`, { ...options, headers });
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text };
  }
  if (!response.ok) {
    throw new Error(`${route} failed ${response.status}: ${redact(body)}`);
  }
  return body;
}

async function byaanApi(route, options = {}) {
  const body = await api(byaanApiUrl, route, options);
  return body?.data ?? body;
}

function normalizeExternalPayload(body) {
  return body?.data ?? body;
}

async function loginByaanTeam() {
  if (!byaanTeamEmail || !byaanTeamPassword) {
    throw new Error("MASTER_USER_EMAIL and MASTER_USER_PASSWORD are required for Team UI checks");
  }
  const form = new URLSearchParams();
  form.set("username", byaanTeamEmail);
  form.set("password", byaanTeamPassword);
  const tokenPair = await byaanApi("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  const accessToken = tokenPair.access_token;
  if (!accessToken) throw new Error("BYAAN Team login did not return access_token");
  const scopesPayload = await byaanApi("/api/scopes/all", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  const tenants = scopesPayload.tenants || [];
  const ownerTenant = tenants.find((tenant) => tenant.role === "owner") || tenants[0];
  if (!ownerTenant) throw new Error("BYAAN Team login did not return any tenant scope");
  const appConfig = await byaanApi("/api/app/config");
  const featureFlags = appConfig.features || {};
  if (featureFlags.enterprise_licensed !== true || featureFlags.team_sharing_enabled !== true) {
    throw new Error(`BYAAN Team feature flags are not enabled: ${redact(appConfig)}`);
  }
  if (appConfig.local_bootstrap || appConfig.community_bootstrap) {
    throw new Error(`BYAAN Team config exposed local/community bootstrap: ${redact(appConfig)}`);
  }
  const authHeaders = {
    Authorization: `Bearer ${accessToken}`,
    "X-Tenant-ID": ownerTenant.tenant_id,
  };
  const [me, feishuStatus, feishuAdminConfig, feishuInstallation] = await Promise.all([
    byaanApi("/api/users/me", { headers: authHeaders }),
    byaanApi("/api/source-connections/feishu/status", { headers: authHeaders }),
    byaanApi("/api/source-connections/feishu/admin-config", { headers: authHeaders }),
    byaanApi("/api/collaboration/installations/feishu", { headers: authHeaders }),
  ]);
  return {
    accessToken,
    tenantId: ownerTenant.tenant_id,
    tenantName: ownerTenant.tenant_name,
    role: ownerTenant.role,
    scopesCount: (ownerTenant.scopes || []).length,
    featureFlags,
    appConfig: {
      org_name: appConfig.org_name || "",
      hasLocalBootstrap: Boolean(appConfig.local_bootstrap),
      hasCommunityBootstrap: Boolean(appConfig.community_bootstrap),
      features: featureFlags,
    },
    user: { id: me.id, email: "<redacted>", is_superuser: Boolean(me.is_superuser) },
    feishu: {
      status: feishuStatus,
      adminConfig: feishuAdminConfig,
      installation: feishuInstallation || null,
    },
  };
}

function assertNoSecret(label, value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const leaked = sensitiveValues.find((secret) => text.includes(secret));
  if (leaked) throw new Error(`${label} leaked a secret value`);
}

function assertNoFailedResponses(responses) {
  const failures = responses.filter((item) => {
    if (item.status < 400) return false;
    if (item.status === 401 && item.url.endsWith("/oauth2/userinfo")) {
      return false;
    }
    return true;
  });
  if (failures.length) {
    throw new Error(`HTTP failures: ${redact(failures.slice(0, 10))}`);
  }
}

async function visualHealth(page, label) {
  const metrics = await page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const all = Array.from(document.querySelectorAll("*"));
    const visibleText = (body?.innerText || "").trim();
    const overflowing = all
      .map((node) => {
        const isHtmlElement = node instanceof HTMLElement;
        const inHorizontalScroller = (() => {
          let parent = node.parentElement;
          while (parent && parent !== document.body) {
            const parentStyle = window.getComputedStyle(parent);
            if (
              /(auto|scroll)/.test(parentStyle.overflowX) &&
              parent.scrollWidth > parent.clientWidth + 2
            ) {
              return true;
            }
            parent = parent.parentElement;
          }
          return false;
        })();
        const rect = node.getBoundingClientRect();
        const style = window.getComputedStyle(node);
        return {
          isHtmlElement,
          inHorizontalScroller,
          tag: node.tagName,
          className: String(node.getAttribute("class") || "").slice(0, 120),
          text: String(node.textContent || "").trim().slice(0, 120),
          left: rect.left,
          right: rect.right,
          top: rect.top,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
          overflowX: style.overflowX,
          position: style.position,
        };
      })
      .filter(
        (item) =>
          item.isHtmlElement &&
          !item.inHorizontalScroller &&
          item.width > 0 &&
          item.height > 0 &&
          (item.left < -2 || item.right > viewportWidth + 2),
      )
      .slice(0, 12);
    const scrollContainers = all.filter((node) => {
      const style = window.getComputedStyle(node);
      return (
        /(auto|scroll)/.test(`${style.overflowY} ${style.overflowX}`) &&
        (node.scrollHeight > node.clientHeight + 2 ||
          node.scrollWidth > node.clientWidth + 2)
      );
    }).length;
    return {
      title: document.title,
      visibleTextLength: visibleText.length,
      viewportWidth,
      viewportHeight,
      scrollWidth: Math.max(doc.scrollWidth, body?.scrollWidth || 0),
      scrollHeight: Math.max(doc.scrollHeight, body?.scrollHeight || 0),
      clientWidth: doc.clientWidth,
      clientHeight: doc.clientHeight,
      overflowing,
      scrollContainers,
      hasBlankBody: visibleText.length < 12,
    };
  });
  if (metrics.hasBlankBody) throw new Error(`${label} appears blank`);
  if (metrics.scrollWidth > metrics.clientWidth + 3) {
    throw new Error(`${label} has horizontal page overflow: ${JSON.stringify(metrics)}`);
  }
  if (metrics.overflowing.length) {
    throw new Error(`${label} has overflowing visible nodes: ${JSON.stringify(metrics.overflowing)}`);
  }
  return metrics;
}

async function waitForFrame(page) {
  await page.getByTitle("Byaan Data Studio Knowledge Center").waitFor({
    state: "attached",
    timeout: 30_000,
  });
  for (let i = 0; i < 80; i += 1) {
    const frame = page
      .frames()
      .find((item) => item.url().startsWith(byaanFrontendUrl));
    if (frame) return frame;
    await page.waitForTimeout(250);
  }
  throw new Error("Knowledge Center iframe did not navigate to the BYAAN frontend");
}

async function waitForEmbeddedFrameReady(frame, label) {
  await frame.waitForLoadState("domcontentloaded");
  await frame.waitForFunction(
    () => {
      const text = (document.body?.innerText || "").trim();
      return (
        Boolean(document.querySelector('[data-embedded-layout="knowledge-center"]')) &&
        Boolean(document.querySelector('[data-embedded-page="knowledge-center"]')) &&
        text.length > 20 &&
        text !== "Loading..."
      );
    },
    { timeout: 30_000 },
  ).catch(async (error) => {
    const state = await frame.evaluate(() => ({
      url: window.location.href,
      text: (document.body?.innerText || "").slice(0, 500),
      hasEmbeddedLayout: Boolean(document.querySelector('[data-embedded-layout="knowledge-center"]')),
      hasEmbeddedPage: Boolean(document.querySelector('[data-embedded-page="knowledge-center"]')),
    })).catch((stateError) => ({ error: String(stateError) }));
    throw new Error(`${label} did not finish embedded rendering: ${redact(state)}\n${String(error)}`);
  });
}

async function embeddedHealth(frame, label) {
  const health = await frame.evaluate(() => {
    const text = document.body?.innerText || "";
    const links = Array.from(document.querySelectorAll("a")).map((link) => ({
      text: (link.textContent || "").trim(),
      href: link.getAttribute("href") || "",
    }));
    const tabLabels = Array.from(
      document.querySelectorAll('nav[aria-label="Knowledge Center sections"] a'),
    ).map((node) => (node.textContent || "").trim());
    return {
      url: window.location.href,
      hasEmbeddedLayout: Boolean(document.querySelector('[data-embedded-layout="knowledge-center"]')),
      hasByaanGlobalSidebar: Boolean(
        document.querySelector('[data-testid="byaan-global-sidebar"], [aria-label="Close navigation"]'),
      ),
      hasContextSidebar: Boolean(document.querySelector('[data-testid="context-sidebar"]')),
      hasAccountMenu: Boolean(
        document.querySelector('[data-testid="profile-menu-trigger"], [data-testid^="profile-menu-"]'),
      ) || links.some((link) => /^(account|profile|team|协作集成|integrations|mcp keys?)$/i.test(link.text)),
      hasBrandHomeLink: links.some((link) => link.text === "Byaan" && link.href.endsWith("/")),
      forbiddenText: [
        "New Notebook",
        "My Notebooks",
        "MCP not configured",
        "Setup MCP",
      ].filter((snippet) => text.includes(snippet)),
      tabLabels,
    };
  });
  if (!health.url.includes("/embedded/knowledge-center")) {
    throw new Error(`${label} did not use the stable embedded route: ${health.url}`);
  }
  if (!health.hasEmbeddedLayout) {
    throw new Error(`${label} did not render the dedicated embedded layout`);
  }
  if (health.hasByaanGlobalSidebar || health.hasContextSidebar || health.hasAccountMenu || health.hasBrandHomeLink) {
    throw new Error(`${label} leaked the full BYAAN application shell: ${JSON.stringify(health)}`);
  }
  if (health.forbiddenText.length) {
    throw new Error(`${label} rendered non-Knowledge-Center content: ${health.forbiddenText.join(", ")}`);
  }
  for (const tab of ["Sources", "Data Models", "Dashboards", "Evaluation", "Folders"]) {
    if (!health.tabLabels.some((labelText) => labelText.includes(tab))) {
      throw new Error(`${label} missing embedded tab ${tab}: ${JSON.stringify(health.tabLabels)}`);
    }
  }
  return health;
}

async function loginByaanInBrowser(page, teamAuth, route = "/") {
  await page.goto(`${byaanFrontendUrl}/login`, { waitUntil: "domcontentloaded" });
  if (page.url().includes("/login")) {
    const emailInput = page.locator("#email");
    await emailInput.waitFor({ state: "visible", timeout: 20_000 });
    await emailInput.fill(byaanTeamEmail);
    await page.locator("#password").fill(byaanTeamPassword);
    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes("/api/auth/login") &&
          response.request().method() === "POST" &&
          response.status() >= 200 &&
          response.status() < 300,
        { timeout: 30_000 },
      ),
      page.locator('form button[type="submit"]').click(),
    ]);
  }
  await page.waitForFunction(() => {
    return (
      !window.location.pathname.startsWith("/login") ||
      Boolean(document.querySelector('[data-testid="profile-menu-trigger"], [data-testid="byaan-global-sidebar"], [data-embedded-layout="knowledge-center"]'))
    );
  }, { timeout: 30_000 });
  await page.evaluate(({ tenantId }) => {
    localStorage.setItem("byaan_active_tenant", tenantId);
    localStorage.removeItem("pendingInvitationToken");
    localStorage.removeItem("pendingInvitationTenantName");
  }, teamAuth);
  await page.goto(`${byaanFrontendUrl}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
}

async function fullDataStudioHealth(page, label) {
  const health = await page.evaluate(() => {
    const text = document.body?.innerText || "";
    const linksAndButtons = Array.from(document.querySelectorAll("a,button")).map((node) =>
      (node.textContent || "").trim(),
    );
    return {
      url: window.location.href,
      hasGlobalSidebar: Boolean(document.querySelector('[data-testid="byaan-global-sidebar"]')),
      hasEmbeddedLayout: Boolean(document.querySelector('[data-embedded-layout="knowledge-center"]')),
      hasContextSidebar: Boolean(document.querySelector('[data-testid="context-sidebar"]')),
      hasTeamEntry: linksAndButtons.some((textValue) => textValue === "Team" || textValue.includes("Team")),
      hasCollaborationEntry: text.includes("协作集成") || text.includes("Integrations"),
      hasFeishuSourceAuth: text.includes("飞书数据源授权"),
      hasFeishuBot: text.includes("飞书协作机器人"),
      hasFeishuAdminSettings: text.includes("飞书应用配置") || text.includes("FeishuAdminSettings"),
      safeUnconfiguredState:
        text.includes("Not configured") ||
        text.includes("未配置") ||
        text.includes("Not installed") ||
        text.includes("未连接") ||
        text.includes("Checking"),
    };
  });
  if (!health.hasGlobalSidebar) {
    throw new Error(`${label} did not render the full BYAAN global sidebar: ${JSON.stringify(health)}`);
  }
  if (health.hasEmbeddedLayout) {
    throw new Error(`${label} rendered the stripped embedded layout in the full Data Studio UI`);
  }
  return health;
}

async function verifyTeamDataStudio(browser, teamAuth, screenshots) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await loginByaanInBrowser(page, teamAuth, "/");

  await page.goto(`${byaanFrontendUrl}/`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("profile-menu-trigger").waitFor({ timeout: 20_000 });
  await page.getByTestId("profile-menu-trigger").click();
  await page.getByTestId("profile-menu-team").waitFor({ timeout: 20_000 });
  await page.getByTestId("profile-menu-integrations").waitFor({ timeout: 20_000 });
  const menuEvidence = await page.evaluate(() => ({
    hasTeam: Boolean(document.querySelector('[data-testid="profile-menu-team"]')),
    hasIntegrations: Boolean(document.querySelector('[data-testid="profile-menu-integrations"]')),
  }));
  await page.keyboard.press("Escape").catch(() => null);

  await page.goto(`${byaanFrontendUrl}/team`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  await page.getByRole("heading", { name: "Team" }).waitFor({ timeout: 20_000 });
  const teamShot = path.join(screenshotDir, "team-full-datastudio.png");
  await page.screenshot({ path: teamShot, fullPage: true });
  screenshots.push(teamShot);
  const teamHealth = await fullDataStudioHealth(page, "Team page");
  if (!/owner|admin/i.test(teamAuth.role)) {
    throw new Error(`Team auth role is not owner/admin: ${teamAuth.role}`);
  }
  if (!menuEvidence.hasTeam || !menuEvidence.hasIntegrations) {
    throw new Error(`Full Data Studio profile menu did not expose Team and 协作集成: ${JSON.stringify(menuEvidence)}`);
  }

  await page.goto(`${byaanFrontendUrl}/integrations`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  await page.getByRole("heading", { name: "Integrations" }).waitFor({ timeout: 20_000 });
  await page.getByText("飞书数据源授权").waitFor({ timeout: 20_000 });
  await page.getByText("飞书协作机器人").waitFor({ timeout: 20_000 });
  await page.getByText("飞书应用配置").waitFor({ timeout: 20_000 });
  const integrationsShot = path.join(screenshotDir, "integrations-full-datastudio.png");
  await page.screenshot({ path: integrationsShot, fullPage: true });
  screenshots.push(integrationsShot);
  const integrationsHealth = await fullDataStudioHealth(page, "Integrations page");
  for (const [field, present] of Object.entries({
    hasCollaborationEntry: integrationsHealth.hasCollaborationEntry,
    hasFeishuSourceAuth: integrationsHealth.hasFeishuSourceAuth,
    hasFeishuBot: integrationsHealth.hasFeishuBot,
    hasFeishuAdminSettings: integrationsHealth.hasFeishuAdminSettings,
    safeUnconfiguredState: integrationsHealth.safeUnconfiguredState,
  })) {
    if (!present) throw new Error(`Integrations page missing ${field}: ${JSON.stringify(integrationsHealth)}`);
  }

  await context.close();
  return {
    team: teamHealth,
    integrations: integrationsHealth,
    profileMenu: menuEvidence,
    boundary: {
      fullDataStudioUrl: byaanFrontendUrl,
      embeddedRoute: `${byaanFrontendUrl}/embedded/knowledge-center`,
      fullDataStudioHasGlobalSidebar: teamHealth.hasGlobalSidebar && integrationsHealth.hasGlobalSidebar,
      iframeMustNotExposeGlobalSidebar: true,
    },
  };
}

async function ensureLoggedIn(page) {
  await page.goto(`${studioBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    localStorage.setItem("veadk_local_user", "kcgate2026");
    sessionStorage.setItem("veadk_local_user_tab", "kcgate2026");
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);
  const loginInput = page.locator(".login-name-input");
  if ((await loginInput.count()) > 0) {
    await loginInput.first().fill("kcgate2026");
    await page.getByRole("button", { name: "进入" }).click();
    await page.waitForLoadState("domcontentloaded");
  }
  await page.waitForTimeout(1000);
}

async function verifyIframeRoutes(browser, responses, screenshots, teamAuth) {
  const checks = [];
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
    });
    const authPage = await context.newPage();
    await loginByaanInBrowser(authPage, teamAuth, "/embedded/knowledge-center");
    await authPage.close();
    const page = await context.newPage();
    page.on("response", (response) => {
      const url = response.url();
      if (
        url.startsWith(studioBaseUrl) ||
        url.startsWith(byaanFrontendUrl) ||
        url.startsWith(byaanApiUrl)
      ) {
        responses.push({ url, status: response.status() });
      }
    });
    await ensureLoggedIn(page);
    await page.getByRole("button", { name: "知识资产" }).click();
    const openDataStudioHref = await page.getByRole("link", { name: /打开 Data Studio/ }).getAttribute("href");
    if (!openDataStudioHref || openDataStudioHref.replace(/\/$/, "") !== byaanFrontendUrl) {
      throw new Error(`打开 Data Studio did not point to the full Team Data Studio URL: ${openDataStudioHref}`);
    }
    const frame = await waitForFrame(page);
    await waitForEmbeddedFrameReady(frame, `${viewport.name} iframe root`);
    const shellShot = path.join(screenshotDir, `${viewport.name}-studio-knowledge-center.png`);
    await page.screenshot({ path: shellShot, fullPage: true });
    screenshots.push(shellShot);
    const shellHealth = await visualHealth(page, `${viewport.name} Studio shell`);
    const iframeHealth = await visualHealth(frame, `${viewport.name} iframe root`);
    const iframeEmbeddedHealth = await embeddedHealth(frame, `${viewport.name} iframe root`);
    checks.push({
      viewport,
      route: "/",
      frameUrl: frame.url(),
      shellHealth,
      iframeHealth,
      iframeEmbeddedHealth,
    });

    const routes = [
      { route: "/sources", label: "Sources" },
      { route: "/data-models", label: "Data Models" },
      { route: "/dashboard-assets", label: "Dashboards" },
      { route: "/evaluation", label: "Evaluation" },
      { route: "/folders", label: "Folders" },
    ];
    for (const { route, label } of routes) {
      await frame.getByRole("link", { name: new RegExp(label) }).click();
      await frame.waitForURL(
        (url) => url.pathname === `/embedded/knowledge-center${route}`,
        { timeout: 20_000 },
      );
      await waitForEmbeddedFrameReady(frame, `${viewport.name} iframe ${route}`);
      const routeShot = path.join(
        screenshotDir,
        `${viewport.name}-iframe-${route.replace(/\W+/g, "-").replace(/^-|-$/g, "") || "root"}.png`,
      );
      await page.screenshot({ path: routeShot, fullPage: true });
      screenshots.push(routeShot);
      const text = await frame.locator("body").innerText({ timeout: 10_000 });
      if (/404|not found/i.test(text)) throw new Error(`${viewport.name} iframe ${route} rendered 404`);
      checks.push({
        viewport,
        route,
        frameUrl: frame.url(),
        iframeHealth: await visualHealth(frame, `${viewport.name} iframe ${route}`),
        iframeEmbeddedHealth: await embeddedHealth(frame, `${viewport.name} iframe ${route}`),
      });
    }
    await context.close();
  }
  return checks;
}

function selectedSkillFromAsset(asset) {
  const assetType = asset.asset_type;
  const assetId = asset.asset_id;
  const labelArray = (values) =>
    (Array.isArray(values) ? values : [])
      .map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return "";
        return item.id || item.name || item.businessName || item.field || JSON.stringify(item);
      })
      .filter(Boolean);
  return {
    source: "datastudio",
    folder: `datastudio-${assetType.replaceAll("_", "-")}-${assetId}`.slice(0, 64),
    name: asset.name || `Data Studio ${assetType} ${assetId}`,
    description: asset.description || "",
    dataStudioAssetType: assetType,
    dataStudioAssetId: assetId,
    dataStudioVersion: String(asset.version || ""),
    dataStudioGateScore: Number(asset.gate?.score || 0),
    dataStudioMetrics: labelArray(asset.capabilities?.metrics),
    dataStudioExampleQuestions: asset.capabilities?.example_questions || [],
    dataStudioPermissionHint:
      asset.usage_policy?.permission_hint ||
      asset.usage_policy?.policy ||
      "Use only governed aggregate data returned by Byaan.",
    dataStudioQueryUrl: asset.query_url,
    dataStudioTimeField: asset.capabilities?.time_field || "",
    dataStudioDimensions: labelArray(asset.capabilities?.dimensions),
    dataStudioEvidence: (asset.sample_evidence || []).map((item) =>
      typeof item === "string" ? item : JSON.stringify(item),
    ),
  };
}

function draftForAsset(asset, queryUrl, envValues) {
  const selectedSkill = selectedSkillFromAsset({ ...asset, query_url: queryUrl });
  return {
    name: "KC Live Revenue Agent",
    cloudProvider: "volcengine",
    description: "Answers governed revenue questions from Byaan Data Studio.",
    instruction:
      "You answer revenue questions using the selected Byaan Data Studio semantic model. " +
      "Always call the Data Studio REST tool before answering. Final answers must include " +
      "the real numeric values, compiled SQL, metric definition, and permission policy evidence.",
    agentType: "llm",
    modelSource: "ark",
    modelName: process.env.MODEL_AGENT_NAME || "doubao-seed-1-6-250615",
    tools: [],
    skills: [],
    memory: { shortTerm: false, longTerm: false },
    knowledgebase: false,
    tracing: false,
    subAgents: [],
    builtinTools: [],
    customTools: [],
    mcpTools: [],
    selectedSkills: [selectedSkill],
    deployment: {
      feishuEnabled: false,
      envValues,
    },
    cloudEnvironment: { cliTools: [] },
  };
}

function projectFile(project, suffix) {
  return project.files.find((file) => file.path.endsWith(suffix));
}

function assertGeneratedProject(project, assetId) {
  const skillFile = project.files.find(
    (file) =>
      file.path.startsWith("skills/datastudio-semantic-model-") &&
      file.path.endsWith("/SKILL.md"),
  );
  if (!skillFile) throw new Error("Generated project is missing Data Studio SKILL.md");
  const agentFile = projectFile(project, "/agent.py");
  if (!agentFile) throw new Error("Generated project is missing agents/<name>/agent.py");
  const skill = skillFile.content;
  const agent = agentFile.content;
  const requiredSkillSnippets = [
    "---",
    "asset_type: semantic_model",
    `asset_id: ${assetId}`,
    "## Metrics",
    "## Dimensions",
    "## Time Field",
    "## Permission Boundary",
    "## Evidence Rules",
    "## Seed Evidence",
  ];
  for (const snippet of requiredSkillSnippets) {
    if (!skill.includes(snippet)) throw new Error(`SKILL.md missing ${snippet}`);
  }
  const requiredAgentSnippets = [
    "load_skill_from_dir",
    "SkillToolset",
    "def query_datastudio",
    "metric: str",
    "dimension: str | None",
    "grain: str | None",
    "filters: dict | None",
    "time_range: dict | None",
    "limit: int = 100",
    "requests.post",
    "BYAAN_MCP_API_KEY",
    "_datastudio_query_url",
  ];
  for (const snippet of requiredAgentSnippets) {
    if (!agent.includes(snippet)) throw new Error(`agent.py missing ${snippet}`);
  }
  if (agent.includes("/api/mcp") || skill.includes("/api/mcp")) {
    throw new Error("Generated project contains a fake /api/mcp reference");
  }
  assertNoSecret("generated project", project);
  return {
    skillPath: skillFile.path,
    agentPath: agentFile.path,
    skillExcerpt: redact(skill.slice(0, 3000)),
    agentToolExcerpt: redact(agent.slice(agent.indexOf("def query_datastudio"), agent.indexOf("def query_datastudio") + 2500)),
  };
}

async function collectSseText(response) {
  const raw = await response.text();
  const events = [];
  let answer = "";
  for (const block of raw.split(/\n\n+/)) {
    const dataLine = block
      .split(/\n/)
      .find((line) => line.startsWith("data:"));
    if (!dataLine) continue;
    const payloadText = dataLine.replace(/^data:\s?/, "");
    try {
      const payload = JSON.parse(payloadText);
      events.push(payload);
      const parts = payload?.content?.parts || payload?.new_message?.parts || [];
      for (const part of parts) {
        if (typeof part?.text === "string") answer += part.text;
      }
    } catch {
      events.push({ raw: payloadText });
    }
  }
  assertNoSecret("SSE stream", raw);
  return { raw: redact(raw), events, answer };
}

function assertAgentAnswer(answer, events) {
  const joined = `${answer}\n${JSON.stringify(events)}`;
  const required = [/East/i, /\b150\b/, /West/i, /\b80\b/, /SQL|select/i, /metric/i, /definition|口径/i, /permission|policy|权限/i];
  const missing = required.filter((pattern) => !pattern.test(joined)).map(String);
  if (missing.length) throw new Error(`Agent answer missing evidence: ${missing.join(", ")}\n${redact(joined.slice(-4000))}`);
}

function collectFunctionEvidence(value, evidence = { functionCall: null, functionResponse: null }) {
  if (value === null || value === undefined) return evidence;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (
      (trimmed.startsWith("{") || trimmed.startsWith("[")) &&
      (trimmed.includes("function_call") || trimmed.includes("function_response"))
    ) {
      try {
        collectFunctionEvidence(JSON.parse(trimmed), evidence);
      } catch {
        return evidence;
      }
    }
    return evidence;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectFunctionEvidence(item, evidence);
    return evidence;
  }
  if (typeof value !== "object") return evidence;
  if (!evidence.functionCall && value.function_call) {
    evidence.functionCall = value.function_call;
  }
  if (!evidence.functionResponse && value.function_response) {
    evidence.functionResponse = value.function_response;
  }
  for (const item of Object.values(value)) {
    if (evidence.functionCall && evidence.functionResponse) break;
    collectFunctionEvidence(item, evidence);
  }
  return evidence;
}

function summarizeRuntimeEvidence(sse, trace) {
  let functionCall = null;
  let functionResponse = null;
  for (const source of [sse.events, trace]) {
    const evidence = collectFunctionEvidence(source);
    functionCall ||= evidence.functionCall;
    functionResponse ||= evidence.functionResponse;
  }
  if (!functionCall) {
    throw new Error("Agent runtime evidence did not contain a function_call");
  }
  if (!functionResponse) {
    throw new Error("Agent runtime evidence did not contain a function_response");
  }
  const response = functionResponse.response || {};
  return {
    eventCount: sse.events.length,
    functionCall: {
      name: functionCall.name,
      args: functionCall.args,
    },
    functionResponse: {
      name: functionResponse.name,
      status: response.status,
      result: response.result,
      sql: response.sql,
      metricDefinition: response.metricDefinition,
      policyDecision: response.policyDecision,
      evidenceKinds: (response.evidence || []).map((item) => item.kind),
    },
  };
}

function summarizeTrace(trace) {
  if (!Array.isArray(trace)) {
    return trace?.error ? { error: trace.error } : { available: false };
  }
  return {
    available: true,
    spanCount: trace.length,
    spanNames: trace
      .map((span) => span?.name)
      .filter(Boolean)
      .slice(0, 20),
  };
}

async function verifyStudioBackends(seed, responses) {
  const config = await api(studioBaseUrl, "/web/datastudio/config");
  if (config.mock) throw new Error("DATASTUDIO_MOCK is enabled");
  if (!config.configured) throw new Error("Data Studio gateway is not configured");
  if (config.embedUrl.replace(/\/$/, "") !== byaanFrontendUrl) {
    throw new Error(`embedUrl does not point to BYAAN frontend: ${config.embedUrl}`);
  }
  assertNoSecret("datastudio config", config);

  const listed = await api(studioBaseUrl, "/web/datastudio/assets?page_size=100");
  if (listed.mock) throw new Error("Data Studio asset list used mock mode");
  const assets = listed.assets || [];
  const asset = assets.find(
    (item) =>
      item.asset_type === "semantic_model" &&
      item.asset_id === seed.model.externalAssetId,
  );
  if (!asset) {
    throw new Error(`Seeded semantic model ${seed.model.externalAssetId} was not listed by Studio gateway`);
  }
  const detail = await api(
    studioBaseUrl,
    `/web/datastudio/assets/semantic_model/${encodeURIComponent(asset.asset_id)}`,
  );
  assertNoSecret("datastudio asset detail", detail);

  const directQuery = normalizeExternalPayload(
    await api(
      byaanApiUrl,
      `/api/external/assets/semantic_model/${encodeURIComponent(asset.asset_id)}/query`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${byaanApiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          metric: "revenue_revenue",
          dimension: "revenue_region",
          limit: 10,
        }),
      },
    ),
  );
  if (!["completed", "success"].includes(directQuery.status)) {
    throw new Error(`Live query did not complete: ${redact(directQuery)}`);
  }
  if (!Array.isArray(directQuery.result) || directQuery.result.length === 0) {
    throw new Error(`Live query returned empty result: ${redact(directQuery)}`);
  }
  if (!directQuery.evidence?.some((item) => item.kind === "sql")) {
    throw new Error("Live query response missing SQL evidence");
  }
  responses.push({ url: `${byaanApiUrl}/api/external/assets/.../query`, status: 200 });
  return { config, listedCount: assets.length, asset: detail, directQuery };
}

async function verifyGeneratedAgent(asset, queryUrl) {
  const envValues = {
    DATASTUDIO_BASE_URL: byaanApiUrl,
    BYAAN_MCP_API_KEY: byaanApiKey,
  };
  const draft = draftForAsset(asset, queryUrl, envValues);
  const project = await api(studioBaseUrl, "/web/generated-agent-projects", {
    method: "POST",
    body: JSON.stringify({ draft }),
  });
  const generatedProject = assertGeneratedProject(project, asset.asset_id);
  const run = await api(studioBaseUrl, "/web/generated-agent-test-runs", {
    method: "POST",
    body: JSON.stringify({ draft }),
  });
  const session = await api(
    studioBaseUrl,
    `/web/generated-agent-test-runs/${encodeURIComponent(run.runId)}/sessions`,
    {
      method: "POST",
      body: JSON.stringify({ userId: "knowledge-center-live-gate" }),
    },
  );
  const response = await fetch(
    `${studioBaseUrl}/web/generated-agent-test-runs/${encodeURIComponent(run.runId)}/run_sse`,
    {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: "knowledge-center-live-gate",
        session_id: session.id,
        new_message: {
          role: "user",
          parts: [
            {
              text:
                "Use the Data Studio semantic model to answer: revenue by region. " +
                "Return the real values, SQL, metric definition, and permission policy evidence.",
            },
          ],
        },
        streaming: true,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`Agent SSE failed ${response.status}: ${redact(await response.text())}`);
  }
  const sse = await collectSseText(response);
  assertAgentAnswer(sse.answer, sse.events);
  const trace = await api(
    studioBaseUrl,
    `/web/generated-agent-test-runs/${encodeURIComponent(run.runId)}/trace/session/${encodeURIComponent(session.id)}`,
  ).catch((error) => ({ error: redact(String(error)) }));
  const runtimeEvidence = summarizeRuntimeEvidence(sse, trace);
  await api(studioBaseUrl, `/web/generated-agent-test-runs/${encodeURIComponent(run.runId)}`, {
    method: "DELETE",
  }).catch(() => null);
  return {
    draft: redact(draft),
    project: generatedProject,
    run: { appName: run.appName, expiresAt: run.expiresAt },
    sessionId: session.id,
    answer: redact(sse.answer),
    runtimeEvidence: JSON.parse(redact(runtimeEvidence)),
    traceSummary: JSON.parse(redact(summarizeTrace(trace))),
  };
}

async function main() {
  const { chromium } = await import(playwrightModule);
  await mkdir(screenshotDir, { recursive: true });
  const seed = await readJson(seedResultPath);
  const responses = [];
  const screenshots = [];
  const result = {
    ok: false,
    startedAt: new Date().toISOString(),
    env: {
      VEADK_STUDIO_URL: studioBaseUrl,
      DATASTUDIO_EMBED_URL: byaanFrontendUrl,
      DATASTUDIO_BASE_URL: byaanApiUrl,
      DATASTUDIO_MOCK: process.env.DATASTUDIO_MOCK || "",
      VITE_KNOWLEDGE_CENTER_MOCK: process.env.VITE_KNOWLEDGE_CENTER_MOCK || "",
      BYAAN_MCP_API_KEY: "<redacted>",
      DATASTUDIO_API_KEY: "<redacted>",
      MASTER_USER_EMAIL: byaanTeamEmail ? "<redacted>" : "",
      MASTER_USER_PASSWORD: byaanTeamPassword ? "<redacted>" : "",
    },
    seed: JSON.parse(redact(seed)),
    screenshots,
  };
  try {
    if (/^(1|true|yes|on)$/i.test(process.env.DATASTUDIO_MOCK || "")) {
      throw new Error("DATASTUDIO_MOCK must be disabled");
    }
    if (/^(1|true|yes|on)$/i.test(process.env.VITE_KNOWLEDGE_CENTER_MOCK || "")) {
      throw new Error("VITE_KNOWLEDGE_CENTER_MOCK must be disabled");
    }
    const teamAuth = await loginByaanTeam();
    result.deployment = JSON.parse(redact({
      mode: "self-hosted",
      appConfig: teamAuth.appConfig,
      auth: {
        tenantId: teamAuth.tenantId,
        tenantName: teamAuth.tenantName,
        role: teamAuth.role,
        scopesCount: teamAuth.scopesCount,
        user: teamAuth.user,
      },
      feishu: teamAuth.feishu,
    }));
    const backend = await verifyStudioBackends(seed, responses);
    result.backend = JSON.parse(redact(backend));

    const browser = await chromium.launch();
    try {
      result.teamDataStudio = await verifyTeamDataStudio(browser, teamAuth, screenshots);
      result.iframe = await verifyIframeRoutes(browser, responses, screenshots, teamAuth);
    } finally {
      await browser.close();
    }
    assertNoFailedResponses(responses);
    result.responses = JSON.parse(redact(responses));
    result.generatedAgent = await verifyGeneratedAgent(
      backend.asset,
      backend.asset.query_url || seed.externalApi.asset.query_url,
    );
    result.ok = true;
    result.completedAt = new Date().toISOString();
  } catch (error) {
    result.ok = false;
    result.error = redact(error?.stack || String(error));
    result.completedAt = new Date().toISOString();
    await writeJson(resultPath, result);
    throw error;
  }
  assertNoSecret("result", result);
  await writeJson(resultPath, result);
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(redact(error?.stack || String(error)));
  process.exit(1);
});
