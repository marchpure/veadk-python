import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { JSDOM } from "jsdom";
import ts from "typescript";

const sourcePath = join(
  import.meta.dirname,
  "../../src/knowledge-workspace/frozen-ui/components/MainArea/TrustedHtmlArtifactPolicy.ts",
);
const source = readFileSync(sourcePath, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const policy = await import(`data:text/javascript,${encodeURIComponent(compiled)}`);

const dom = new JSDOM("<!doctype html>");
globalThis.DOMParser = dom.window.DOMParser;

test("trusted renderer policy accepts only same-origin HTTP artifact refs", () => {
  assert.equal(
    policy.isSameOriginHttpUrl("/api/knowledge-assets/v1/objects/abc", "https://studio.test"),
    true,
  );
  assert.equal(
    policy.isSameOriginHttpUrl("https://evil.test/object", "https://studio.test"),
    false,
  );
  assert.equal(
    policy.isSameOriginHttpUrl("file:///tmp/object.html", "https://studio.test"),
    false,
  );
  assert.equal(
    policy.isSameOriginHttpUrl("local://bundle/abc", "https://studio.test"),
    false,
  );
});

test("trusted renderer digest uses exact UTF-8 HTML bytes", async () => {
  assert.equal(
    await policy.sha256Text("<main>知识</main>"),
    "3e9ad9c71998944e9b2515aedac1134bff1ec5e1c1f5a7a43d1b5ae5f408fa71",
  );
  assert.equal(
    await policy.sha256Bytes(new TextEncoder().encode("<main>知识</main>")),
    "3e9ad9c71998944e9b2515aedac1134bff1ec5e1c1f5a7a43d1b5ae5f408fa71",
  );
});

test("trusted renderer requires exact HTML MIME and bounded content length", () => {
  assert.equal(policy.isHtmlMediaType("text/html; charset=utf-8"), true);
  assert.equal(policy.isHtmlMediaType("TEXT/HTML"), true);
  assert.equal(policy.isHtmlMediaType("text/html-malicious"), false);
  assert.equal(policy.isHtmlMediaType("application/xhtml+xml"), false);
  assert.equal(policy.parseTrustedContentLength("42"), 42);
  for (const value of [
    null,
    "",
    "-1",
    "1.5",
    "01",
    String(policy.MAX_TRUSTED_HTML_BYTES + 1),
  ]) {
    assert.throws(() => policy.parseTrustedContentLength(value));
  }
});

test("trusted renderer rejects script, iframe, event handlers, and network CSS", () => {
  for (const unsafe of [
    "<script>alert(1)</script>",
    "<iframe></iframe>",
    '<button onclick="alert(1)">x</button>',
    '<svg><use xlink:href="https://evil.test/x"></use></svg>',
    "<style>main{background:url(https://evil.test/x)}</style>",
    '<style>main{background:image-set("https://evil.test/x" 1x)}</style>',
    "<style>main{background:u\\72l(https://evil.test/x)}</style>",
    '<button data-artifact-event="arbitrary.execute">x</button>',
  ]) {
    assert.throws(() => policy.validateTrustedArtifactHtml(unsafe));
  }
});

test("trusted renderer emits only allowlisted typed bridge events", () => {
  const documentValue = policy.validateTrustedArtifactHtml(`
    <select data-artifact-event="filter.change" data-field="region">
      <option selected value="east">East</option>
    </select>
    <button data-artifact-event="export.request" data-format="csv">Export</button>
  `);
  assert.deepEqual(
    policy.eventFromElement(documentValue.querySelector("select"), "view-1"),
    {
      type: "filter.change",
      revisionId: "view-1",
      field: "region",
      value: "east",
    },
  );
  assert.deepEqual(
    policy.eventFromElement(documentValue.querySelector("button"), "view-1"),
    {
      type: "export.request",
      revisionId: "view-1",
      format: "csv",
    },
  );
});

test("trusted renderer exposes an honest no-ViewRevision state", () => {
  const rendererSource = readFileSync(
    join(
      import.meta.dirname,
      "../../src/knowledge-workspace/frozen-ui/components/MainArea/TrustedHtmlArtifactRenderer.tsx",
    ),
    "utf8",
  );
  assert.match(rendererSource, /if \(!revision\)/);
  assert.match(rendererSource, /暂无 HTML revision/);
  assert.match(rendererSource, /credentials: 'same-origin'/);
  assert.match(rendererSource, /responseLength !== resultRef\.bytes/);
  assert.match(rendererSource, /bytes\.byteLength !== responseLength/);
  assert.match(rendererSource, /response\.arrayBuffer\(\)/);
  assert.doesNotMatch(rendererSource, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(rendererSource, /<iframe/);
});
