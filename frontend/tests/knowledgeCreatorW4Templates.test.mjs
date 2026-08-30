import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const featureRoot = path.join(root, "src/features/knowledge-workspace");
const page = await readFile(path.join(featureRoot, "pages/KnowledgeWorkspacePage.tsx"), "utf8");
const css = await readFile(path.join(featureRoot, "pages/knowledge-workspace.css"), "utf8");
const composer = await readFile(path.join(featureRoot, "creator/SkillComposer.tsx"), "utf8");
const artifact = await readFile(path.join(featureRoot, "artifact/ArtifactViewer.tsx"), "utf8");
const toolActivity = await readFile(path.join(featureRoot, "assistant/ToolActivity.tsx"), "utf8");

test("W4 template options are selectable Creator entry points", () => {
  assert.match(page, /TEMPLATE_DEFINITIONS/);
  assert.match(page, /key: "semantic"/);
  assert.match(page, /key: "dashboard"/);
  assert.match(page, /key: "sop"/);
  assert.match(composer, /role="listbox" aria-label="产物类型"/);
  assert.match(composer, /aria-selected=\{templateKey === option.key\}/);
  assert.match(composer, /onTemplateKeyChange\(option.key\)/);
  assert.doesNotMatch(page, /即将开放/);
});

test("W4 create flow submits template metadata through the existing draft API", () => {
  assert.match(page, /template_key: templateKey/);
  assert.match(page, /template_config: templateConfig/);
  assert.match(composer, /templateKey === option\.key/);
  assert.match(page, /const createAndGenerate = useCallback\(async \(\s*goal: string,\s*templateKey: TemplateKey,\s*templateConfig: JsonObject/s);
  assert.match(page, /TEMPLATE_DEFINITIONS[\s\S]*config: \{ mode: "auto" \}/);
});

test("W4 generated package keeps HTML as presentation artifact with lineage", () => {
  assert.match(page, /templateLabel\(revision\?\.template_key \|\| draft.template_key\)/);
  assert.match(page, /HTML Artifact/);
  assert.match(page, /Lineage/);
  assert.match(page, /source_refs/);
  assert.match(artifact, /sandbox=\{artifact\.sandbox \|\| ""\}/);
});

test("W4 styles expose selected template and compact lineage metadata", () => {
  assert.match(css, /kw-template-selector/);
  assert.match(css, /kw-template-choice/);
  assert.match(css, /kw-template-popover button\[aria-selected="true"\]/);
  assert.match(css, /kw-template-badge/);
});

test("assistant tool rows expose sanitized input and output details", () => {
  assert.match(toolActivity, /查看输入/);
  assert.match(toolActivity, /查看结果/);
  assert.match(toolActivity, /查看错误/);
});
