import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const viewer = await readFile(
  path.join(root, "src/features/knowledge-workspace/artifact/ArtifactViewer.tsx"),
  "utf8",
);
const workspace = await readFile(
  path.join(root, "src/features/knowledge-workspace/workspace/ArtifactWorkspace.tsx"),
  "utf8",
);
const toolbar = await readFile(
  path.join(root, "src/features/knowledge-workspace/workspace/ArtifactToolbar.tsx"),
  "utf8",
);
const conversation = await readFile(
  path.join(root, "src/features/knowledge-workspace/workspace/SkillConversation.tsx"),
  "utf8",
);
const turn = await readFile(
  path.join(root, "src/features/knowledge-workspace/assistant/ConversationTurn.tsx"),
  "utf8",
);
const styles = await readFile(
  path.join(root, "src/features/knowledge-workspace/pages/knowledge-workspace.css"),
  "utf8",
);

test("artifact viewer is fail-closed and only renders controlled same-origin urls", () => {
  assert.match(viewer, /export function hasRenderableArtifact/);
  assert.match(viewer, /url\.origin !== window\.location\.origin/);
  assert.match(viewer, /url\.pathname\.startsWith\("\/api\/knowledge\/v1\/artifacts\/"\)/);
  assert.match(viewer, /url\.pathname\.startsWith\("\/api\/knowledge\/v1\/artifact-snapshots\/"\)/);
  assert.match(viewer, /previewState\?\.status === "preview" && previewState\.mediaType === "text\/html"/);
  assert.doesNotMatch(viewer.toLowerCase(), /mock/);
  assert.doesNotMatch(viewer, /allow-same-origin/);
});

test("artifact viewer exposes preview source log with debounced snapshot updates", () => {
  assert.match(viewer, /type ArtifactPane = "preview" \| "source" \| "log"/);
  assert.match(viewer, /const PREVIEW_DEBOUNCE_MS = 320/);
  assert.match(viewer, /role="tablist"/);
  assert.match(viewer, /Preview/);
  assert.match(viewer, /Source/);
  assert.match(viewer, /Log/);
  assert.match(viewer, /readOnly/);
  assert.match(viewer, /kw-artifact-skeleton/);
});

test("artifact viewer source respects final artifact priority over preview source", () => {
  assert.match(
    viewer,
    /function sourceText\(artifact: Artifact \| null, previewState\?: AssistantArtifactPreview\): string \{\s+if \(artifact\?\.lineage\) return JSON\.stringify\(artifact\.lineage, null, 2\);/s,
  );
});

test("artifact workspace uses reducer preview state without widening renderability", () => {
  assert.match(workspace, /turns,/);
  assert.match(workspace, /turn\.artifactPreview/);
  assert.match(workspace, /hasRenderableArtifact\(activeArtifact\)/);
  assert.match(workspace, /\/api\/knowledge\/v1\/artifact-snapshots\//);
  assert.doesNotMatch(workspace, /onRefresh=.*onRun|onRun=.*onRefresh/);
});

test("artifact toolbar keeps refresh local and publish as the only primary action", () => {
  assert.match(toolbar, /kw-artifact-toolbar-group/);
  assert.match(toolbar, /kw-artifact-icon-button/);
  assert.match(toolbar, /发布 Skill/);
  assert.doesNotMatch(toolbar, /onRun/);
  assert.doesNotMatch(toolbar, /重新运行|运行/);
});

test("assistant workspace exposes stop reconnect retry and manual scroll recovery", () => {
  assert.match(conversation, /onCancel/);
  assert.match(conversation, /停止/);
  assert.match(conversation, /following/);
  assert.match(conversation, /回到最新消息/);
  assert.match(turn, /connectionState === "disconnected"/);
  assert.match(turn, /继续接收/);
  assert.match(turn, /重试本次运行/);
});

test("artifact styles cover preview tabs source log skeleton and compact toolbar", () => {
  for (const selector of [
    ".kw-artifact-controls",
    ".kw-artifact-identity",
    ".kw-artifact-pane-tabs",
    ".kw-artifact-pane-body",
    ".kw-artifact-source",
    ".kw-artifact-log",
    ".kw-artifact-skeleton",
    ".kw-artifact-toolbar-group",
    ".kw-artifact-icon-button",
    ".kw-artifact-secondary-action",
    ".kw-artifact-publish-action",
  ]) {
    assert.match(styles, new RegExp(selector.replace(".", "\\.")));
  }
});
