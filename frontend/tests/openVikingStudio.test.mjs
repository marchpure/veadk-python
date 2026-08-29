import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(
  new URL("../src/App.tsx", import.meta.url),
  "utf8",
);
const workspaceSource = readFileSync(
  new URL(
    "../src/features/openviking/OpenVikingWorkspace.tsx",
    import.meta.url,
  ),
  "utf8",
);
const sidebarSource = readFileSync(
  new URL("../src/ui/Sidebar.tsx", import.meta.url),
  "utf8",
);

test("OpenViking is selected through StudioApp instead of bypassing the shell", () => {
  assert.match(appSource, /return <StudioApp initialWorkspace=\{initialWorkspace\} \/>/);
  assert.doesNotMatch(
    appSource,
    /query\.get\("view"\) === "openviking"\) \{\s*return <OpenVikingWorkspace \/>/,
  );
});

test("OpenViking reuses the Studio shell and contextual sidebar navigation", () => {
  assert.match(workspaceSource, /className="layout openviking-studio"/);
  assert.match(workspaceSource, /<Sidebar[\s\S]*?contextNavigation=/);
  assert.match(workspaceSource, /<Navbar[\s\S]*?crumbs=/);
  assert.match(workspaceSource, /<main className="main openviking-main">/);
  assert.match(sidebarSource, /contextNavigation\?: SidebarContextNavigation/);

  for (const label of [
    "Resources",
    "Retrieval",
    "Tasks",
    "Watches",
    "Connection",
  ]) {
    assert.match(workspaceSource, new RegExp(`label: '${label}'`));
  }
});

test("Resources uses a persistent context tree and connection uses the canonical URL", () => {
  assert.match(workspaceSource, /aria-label="OpenViking context tree"/);
  assert.match(workspaceSource, /<LazyFilePreview/);
  assert.match(
    workspaceSource,
    /https:\/\/api\.vikingdb\.cn-beijing\.volces\.com\/openviking/,
  );
  assert.doesNotMatch(workspaceSource, /setPaletteOpen\(true\)/);
  assert.doesNotMatch(workspaceSource, /className="ov-tabs"/);
  assert.doesNotMatch(workspaceSource, /className="ov-header"/);
});
