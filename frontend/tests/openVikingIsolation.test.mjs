import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const knowledgePage = readFileSync(
  new URL("../src/features/knowledge-workspace/pages/KnowledgeWorkspacePage.tsx", import.meta.url),
  "utf8",
);

test("OpenViking implementation is not statically imported by App", () => {
  assert.match(appSource, /lazy\(loadOpenVikingWorkspace\)/);
  assert.doesNotMatch(appSource, /from\s*["']\.\/extensions\/openviking\//);
});

test("legacy OpenViking source roots are removed", () => {
  assert.equal(existsSync(new URL("../src/features/openviking", import.meta.url)), false);
  assert.equal(existsSync(new URL("../../server/openviking", import.meta.url)), false);
});

test("extension publishes opaque source contracts", () => {
  const publicSource = readFileSync(new URL("../src/extensions/openviking/public.ts", import.meta.url), "utf8");
  assert.match(publicSource, /KnowledgeSourceRef/);
  assert.match(publicSource, /loadOpenVikingWorkspace/);
});

test("legacy payload conversion is isolated in the extension", () => {
  const registrySource = readFileSync(new URL("../src/extensions/knowledgeSources.ts", import.meta.url), "utf8");
  const manifestSource = readFileSync(new URL("../src/extensions/openviking/manifest.ts", import.meta.url), "utf8");
  assert.match(knowledgePage, /extensions\/knowledgeSources/);
  assert.doesNotMatch(knowledgePage, /OpenViking|openViking|root_resource_ref|profile_id/);
  assert.match(registrySource, /loadKnowledgeSourceOptions/);
  assert.doesNotMatch(registrySource, /OpenVikingWorkspace\.tsx/);
  assert.match(registrySource, /loadOpenVikingWorkspace\?\.\(\)/);
  assert.match(manifestSource, /slots:[\s\S]*dataTools/);
  assert.match(manifestSource, /createKnowledgeBase/);
});
