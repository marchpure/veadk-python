import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const feature = path.join(root, "src/features/knowledge-workspace");
const page = await readFile(path.join(feature, "pages/KnowledgeWorkspacePage.tsx"), "utf8");
const publication = await readFile(path.join(feature, "pages/McpPublications.tsx"), "utf8");
const api = await readFile(path.join(feature, "api/mcpPublications.ts"), "utf8");
const css = await readFile(path.join(feature, "pages/knowledge-workspace.css"), "utf8");

test("connection detail opens the four-step MCP publication wizard", () => {
  assert.match(page, /ConnectionPublications/);
  assert.match(publication, /发布为 MCP/);
  for (const label of ["选择数据", "设置权限", "选择使用者", "确认发布"]) {
    assert.match(publication, new RegExp(label));
  }
  assert.match(publication, /添加更多连接（高级）/);
  assert.match(publication, /默认不授权/);
  assert.match(publication, /我确认此发布包含写入能力/);
});

test("connection selection is limited to ready connections sharing the registered MCP endpoint", () => {
  assert.match(publication, /normalizedEndpoint/);
  assert.match(publication, /item\.mcp_endpoint/);
  assert.match(publication, /Endpoint 与当前连接一致/);
  assert.match(publication, /Boolean\(initialEndpoint\)/);
});

test("application audience is enabled while user-group mode fails closed", () => {
  assert.match(publication, /应用客户端授权/);
  assert.match(publication, /当前环境未配置可执行的 Publication Access Broker/);
  assert.doesNotMatch(publication, /userIds:\s*\[/);
  assert.match(api, /audienceTypes/);
});

test("browser API submits only business fields and supports lifecycle actions", () => {
  assert.match(api, /name:\s*string/);
  assert.match(api, /connectionIds:\s*string\[\]/);
  assert.match(api, /actionPolicy:\s*McpActionPolicy/);
  assert.match(api, /audience:\s*McpAudience/);
  assert.doesNotMatch(api, /runtimeTokenId|accessPackageId|customJwtDiscoveryUrl|backendEndpointRef/);
  for (const action of ["verify", "retry", "rotate-credential", "disable"]) {
    assert.match(api, new RegExp(action));
  }
});

test("progress, detail, history and audit are server-backed and responsive", () => {
  for (const stage of ["准备权限", "托管凭据", "创建 Gateway", "验证访问", "发布完成"]) {
    assert.match(publication, new RegExp(stage));
  }
  assert.match(publication, /Revision 历史/);
  assert.match(publication, /审计事件/);
  assert.match(publication, /管理员诊断信息/);
  assert.match(publication, /setInterval\(\(\) => void load\(\), 1500\)/);
  assert.match(css, /\.kw-mcp-policy-grid/);
  assert.match(css, /@media \(max-width: 720px\)/);
});
