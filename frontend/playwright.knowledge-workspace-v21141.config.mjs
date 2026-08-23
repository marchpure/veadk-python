import { defineConfig } from "@playwright/test";

// Contract runtime: @playwright/test 1.55.0, Chromium revision 1187
// (browser 140.0.7339.16). Install only in the external test runtime.
const shared = {
  colorScheme: "light",
  deviceScaleFactor: 1,
  locale: "zh-CN",
  timezoneId: "Asia/Shanghai",
  reducedMotion: "reduce",
  screenshot: "only-on-failure",
  trace: "retain-on-failure",
};

export default defineConfig({
  globalSetup: "./knowledgeWorkspaceV21141GlobalSetup.mjs",
  testDir: "./tests/knowledge-workspace-v21141",
  testMatch: "**/*.spec.mjs",
  outputDir:
    process.env.KNOWLEDGE_V21141_EVIDENCE_DIR ??
    "/Users/bytedance/.codex/runtime/knowledge-v21141-commercial-step-1/playwright",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["json", { outputFile: "/Users/bytedance/.codex/runtime/knowledge-v21141-commercial-step-1/playwright-report.json" }]],
  projects: [
    { name: "desktop-1920", use: { ...shared, viewport: { width: 1920, height: 1080 } } },
    { name: "desktop-1440", use: { ...shared, viewport: { width: 1440, height: 900 } } },
    { name: "tablet-1024", use: { ...shared, viewport: { width: 1024, height: 768 } } },
    { name: "mobile-390", use: { ...shared, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } }
  ]
});
