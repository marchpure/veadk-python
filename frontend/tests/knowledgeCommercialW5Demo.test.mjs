import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const demo = path.join(root, "src/features/knowledge-workspace/demo");
const bootstrap = await readFile(path.join(demo, "DemoBootstrap.tsx"), "utf8");
const card = await readFile(path.join(demo, "DemoScenarioCard.tsx"), "utf8");
const onboarding = await readFile(path.join(demo, "DemoOnboarding.tsx"), "utf8");
const types = await readFile(path.join(demo, "types.ts"), "utf8");
const seed = JSON.parse(await readFile(path.resolve(root, "../demo/seed-manifest.json"), "utf8"));
const wiring = JSON.parse(await readFile(path.resolve(root, "../demo/wiring-manifest.json"), "utf8"));

test("DemoBootstrap is explicit, tenant-safe, and does not modify the main entry", () => {
  assert.match(bootstrap, /\/api\/knowledge\/v1\/demo\/manifest/);
  assert.match(bootstrap, /示例数据/);
  assert.match(bootstrap, /未通过真实连接验证/);
  assert.match(bootstrap, /DemoOnboarding/);
  assert.match(bootstrap, /DemoScenarioCard/);
  assert.doesNotMatch(bootstrap, /localStorage|setTimeout|mock-success|fixture-success/i);
});

test("scenario cards expose all first-experience actions and explicit example status", () => {
  for (const label of ["示例", "打开 Skill", "查看连接", "重新验证", "用自己的数据复制"]) {
    assert.match(card, new RegExp(label));
  }
  assert.match(card, /disabled={!ready}/);
  assert.match(types, /"not_initialized"/);
  assert.match(card, /last_verified_at/);
});

test("empty-state onboarding contains the required three steps", () => {
  for (const label of ["添加数据或知识", "描述目标", "生成并发布 Skill"]) {
    assert.match(onboarding, new RegExp(label));
  }
  assert.match(onboarding, /role="status"/);
});

test("seed and wiring manifests describe three traceable scenarios and opt-in behavior", () => {
  assert.equal(seed.enabled_by_default, false);
  assert.deepEqual(seed.scenarios.map((item) => item.id), [
    "anta-sports-daily",
    "im-after-sales",
    "haidilao-inspection",
  ]);
  assert.equal(wiring.main_entry_modified, false);
  assert.equal(wiring.manifest_route, "/api/knowledge/v1/demo/manifest");
});
