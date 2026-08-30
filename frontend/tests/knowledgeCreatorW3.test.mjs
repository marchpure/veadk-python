import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const featureRoot = path.join(root, "src/features/knowledge-workspace");
const page = await readFile(path.join(featureRoot, "pages/KnowledgeWorkspacePage.tsx"), "utf8");
const css = await readFile(path.join(featureRoot, "pages/knowledge-workspace.css"), "utf8");
const creator = await readFile(path.join(featureRoot, "creator/SkillCreateLanding.tsx"), "utf8");
const composer = await readFile(path.join(featureRoot, "creator/SkillComposer.tsx"), "utf8");
const timeline = await readFile(path.join(featureRoot, "assistant/ActivityTimeline.tsx"), "utf8");
const reducer = await readFile(path.join(featureRoot, "assistant/assistant-reducer.ts"), "utf8");

test("landing route uses the single SkillCreateLanding composer", () => {
  assert.match(page, /<SkillCreateLanding/);
  assert.match(page, /route\.file === "skill_new"/);
  assert.match(page, /requestedFile === "welcome"/);
  assert.match(page, /replaceState/);
  assert.match(creator, /创建一个新技能/);
  assert.match(page, /Dashboard/);
  assert.match(page, /SOP/);
  assert.match(page, /Semantic/);
  assert.match(composer, /Semantic/);
  assert.match(css, /kw-skill-create-landing/);
  assert.doesNotMatch(page, /WelcomeEntryView|kw-home-composer/);
  assert.doesNotMatch(css, /kw-home-composer|kw-output-types/);
});

test("workspace headers expose personal and team connection creation", () => {
  assert.match(page, /aria-label="添加个人连接"/);
  assert.match(page, /openConnectionSelector\("personal"\)/);
  assert.match(page, /aria-label="添加团队连接"/);
  assert.match(page, /openConnectionSelector\("team"\)/);
  assert.match(page, /initialScope=\{connectionFormScope\}/);
});

test("connection selector is catalog-driven with search category and schema summaries", () => {
  assert.match(page, /readableConnectorCategory/);
  assert.match(page, /connectorSearchText/);
  assert.match(page, /connectorSchemaSummary/);
  assert.match(page, /filteredConnectors/);
  assert.match(page, /role="list" aria-label="连接类型"/);
  assert.doesNotMatch(page, /oracle_database", "postgresql", "mysql", "sql_server"/);
});

test("generated skill package shows manifest, bindings, revision and run action", () => {
  assert.match(page, /function SkillPackagePanel/);
  assert.match(page, /data-testid="skill-package"/);
  assert.match(page, /SKILL\.md/);
  assert.match(page, /scripts \/ tests/);
  assert.match(page, /绑定 Connection/);
  assert.match(page, /Revision/);
  assert.match(page, /试跑/);
  assert.match(page, /manifestSkillMarkdown/);
  assert.match(page, /previewSkillFiles/);
  assert.match(page, /当前 Revision 尚未返回文件清单\/源文件内容/);
  assert.match(css, /kw-skill-empty/);
});

test("production skill package does not synthesize missing source files", () => {
  assert.doesNotMatch(page, /generated_skill/);
  assert.doesNotMatch(page, /scripts\/run\.py/);
  assert.doesNotMatch(page, /tests\/test_skill\.py/);
  assert.doesNotMatch(page, /业务目标：/);
  assert.doesNotMatch(page, /验收试跑：/);
  assert.doesNotMatch(page, /collectManifestFiles\(manifest\?\.scripts\)/);
  assert.doesNotMatch(page, /collectManifestFiles\(manifest\?\.tests\)/);
  assert.match(page, /collectBundlePaths\(manifest\)/);
  assert.match(page, /manifestBundleRoot/);
  assert.match(page, /<div className="kw-skill-empty">\{MISSING_SKILL_SOURCE\}<\/div>/);
});

test("run path uses real revision invocation when a revision exists", () => {
  assert.match(page, /const runSkill = useCallback/);
  assert.match(page, /knowledgeApi\.runRevision/);
  assert.match(page, /await sendMessage\(message, "run"\)/);
  assert.match(page, /onRun=\{runSkill\}/);
  assert.match(page, /handleAssistantSend/);
});

test("W3 source does not expose fake BuildPlan or multi-stage plan UI", () => {
  for (const source of [page, css, timeline, reducer]) {
    assert.doesNotMatch(source, /BuildPlan|多阶段产物生成计划|kw-plan-card|执行步骤|个步骤|排查步骤/);
  }
});
