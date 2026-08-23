import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  assertVisualEvidence,
  compareEvidenceBundle,
  loadVisualContract,
} from "./visualGate.mjs";
import { makePng } from "./visualTestFixtures.mjs";
import { runVisualComparison } from "./compareVisualEvidence.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const contract = loadVisualContract(
  join(
    here,
    "../../../tests/fixtures/knowledge_workspace_v21141/visual-contract.json",
  ),
);

function writeJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value)}\n`);
}

function makeBundle() {
  const root = mkdtempSync(join(tmpdir(), "knowledge-v21141-evidence-"));
  const reference = join(root, "reference");
  const candidate = join(root, "candidate");
  mkdirSync(reference);
  mkdirSync(candidate);
  const width = 1920;
  const height = 1080;
  const pixels = Buffer.alloc(width * height * 4, 255);
  const observations = {
    "dom.json": { nodes: [{ id: "workspace", role: "main" }] },
    "class.json": { workspace: ["flex", "min-w-0"] },
    "text.json": { workspace: "知识资产" },
    "event.json": [{ type: "click", target: "create" }],
    "geometry.json": {
      elements: [
        {
          selector: "#critical",
          critical: true,
          businessComponent: true,
          box: { x: 0, y: 0, width: 100, height: 20 },
        },
        {
          selector: "#ordinary",
          critical: false,
          businessComponent: true,
          box: { x: 10, y: 20, width: 50, height: 30 },
        },
      ],
    },
    "computed-style.json": {
      "#critical": { color: "rgb(0, 0, 0)", display: "flex" },
    },
    "runtime.json": {
      semanticIds: ["workspace", "resource-tree"],
      interactionIds: ["create", "select-resource"],
      consoleErrors: [],
      pageErrors: [],
      iframes: [],
      productionFixtureReferences: [],
    },
    "accessibility.json": { violations: [], checkedNodes: 2 },
    "keyboard.json": {
      failures: [],
      steps: ["Tab", "Enter"],
    },
    "ime.json": { failures: [], committed: "知识" },
    "mobile.json": {
      failures: [],
      checks: ["single-composer", "touch-targets"],
      horizontalOverflowPx: 0,
    },
  };
  for (const side of [reference, candidate]) {
    writeFileSync(join(side, "screenshot.png"), makePng(width, height, pixels));
    for (const [name, value] of Object.entries(observations)) {
      writeJson(join(side, name), value);
    }
  }
  return {
    root,
    reference,
    candidate,
    scenarioId: "GM-01",
    viewport: "1920x1080",
  };
}

function mutateJson(path, mutate) {
  const value = JSON.parse(readFileSync(path, "utf8"));
  mutate(value);
  writeJson(path, value);
}

function compare(reference, candidate) {
  return compareEvidenceBundle(contract, {
    reference,
    candidate,
    scenarioId: "GM-01",
    viewport: "1920x1080",
  });
}

test("computes passing evidence from identical runtime artifacts", () => {
  const { reference, candidate } = makeBundle();
  const evidence = compare(reference, candidate);
  assert.deepEqual(assertVisualEvidence(contract, evidence), { status: "pass" });
  assert.equal(evidence.pixelMismatchRatio, 0);
  assert.equal(evidence.snapshots.computedStyle.equal, true);
  assert.equal(evidence.maxCriticalAnchorDeltaPx, 0);
  assert.equal(evidence.maxOtherBoundaryDeltaPx, 0);
  assert.equal(evidence.semanticMissing, 0);
  assert.equal(evidence.interactionMissing, 0);
  assert.equal(evidence.evidence_hashes.length, 24);
  assert.deepEqual(Object.keys(evidence.artifactHashes.reference).sort(), [
    "accessibility.json",
    "class.json",
    "computed-style.json",
    "dom.json",
    "event.json",
    "geometry.json",
    "ime.json",
    "keyboard.json",
    "mobile.json",
    "runtime.json",
    "screenshot.png",
    "text.json",
  ]);
  assert.ok(
    evidence.evidence_hashes.every((hash) => /^[0-9a-f]{64}$/.test(hash)),
  );
});

test("computes a real PNG pixel mismatch", () => {
  const { reference, candidate } = makeBundle();
  const width = 1920;
  const height = 1080;
  const changedPixels = 2074;
  const changed = Buffer.alloc(width * height * 4, 255);
  for (let pixel = 0; pixel < changedPixels; pixel += 1) {
    changed[pixel * 4] = 254;
  }
  writeFileSync(
    join(candidate, "screenshot.png"),
    makePng(width, height, changed),
  );
  const evidence = compare(reference, candidate);
  assert.equal(evidence.pixelMismatchRatio, changedPixels / (width * height));
  assert.throws(
    () => assertVisualEvidence(contract, evidence),
    /pixel mismatch/,
  );
});

test("rejects screenshots whose dimensions do not match the frozen viewport", () => {
  const { reference, candidate } = makeBundle();
  const pixels = Buffer.alloc(2 * 2 * 4, 255);
  writeFileSync(join(candidate, "screenshot.png"), makePng(2, 2, pixels));
  assert.throws(
    () => compare(reference, candidate),
    /screenshot dimensions do not match viewport/,
  );
});

for (const [name, file, mutate, message] of [
  [
    "DOM drift",
    "dom.json",
    (value) => value.nodes.push({ id: "extra" }),
    /dom snapshot/,
  ],
  [
    "class drift",
    "class.json",
    (value) => value.workspace.push("hidden"),
    /class snapshot/,
  ],
  [
    "text drift",
    "text.json",
    (value) => {
      value.workspace = "changed";
    },
    /text snapshot/,
  ],
  [
    "event drift",
    "event.json",
    (value) => value.push({ type: "submit" }),
    /event snapshot/,
  ],
  [
    "computed-style drift",
    "computed-style.json",
    (value) => {
      value["#critical"].display = "none";
    },
    /computed-style snapshot/,
  ],
  [
    "critical geometry drift",
    "geometry.json",
    (value) => {
      value.elements[0].box.x = 0.01;
    },
    /critical anchor/,
  ],
  [
    "ordinary geometry over 1px",
    "geometry.json",
    (value) => {
      value.elements[1].box.width = 51.01;
    },
    /boundary delta/,
  ],
  [
    "missing semantic content",
    "runtime.json",
    (value) => value.semanticIds.pop(),
    /semantic content/,
  ],
  [
    "missing interaction",
    "runtime.json",
    (value) => value.interactionIds.pop(),
    /interaction coverage/,
  ],
  [
    "console error",
    "runtime.json",
    (value) => value.consoleErrors.push("boom"),
    /console error/,
  ],
  [
    "page error",
    "runtime.json",
    (value) => value.pageErrors.push("boom"),
    /page error/,
  ],
  [
    "iframe",
    "runtime.json",
    (value) => value.iframes.push({ selector: "iframe", src: "/embedded" }),
    /iframe/,
  ],
  [
    "production fixture",
    "runtime.json",
    (value) => value.productionFixtureReferences.push("tests/fixtures/data.json"),
    /production fixture/,
  ],
  [
    "accessibility failure",
    "accessibility.json",
    (value) => value.violations.push({ id: "button-name" }),
    /accessibility failed/,
  ],
  [
    "keyboard failure",
    "keyboard.json",
    (value) => value.failures.push("focus trap"),
    /keyboard failed/,
  ],
  [
    "IME failure",
    "ime.json",
    (value) => value.failures.push("composition committed early"),
    /ime failed/,
  ],
  [
    "mobile failure",
    "mobile.json",
    (value) => value.failures.push("control clipped"),
    /mobile failed/,
  ],
]) {
  test(`fails closed on computed ${name}`, () => {
    const { reference, candidate } = makeBundle();
    mutateJson(join(candidate, file), mutate);
    const evidence = compare(reference, candidate);
    assert.throws(() => assertVisualEvidence(contract, evidence), message);
  });
}

test("evidence hashes change when an artifact is tampered", () => {
  const { reference, candidate } = makeBundle();
  const before = compare(reference, candidate).evidence_hashes;
  mutateJson(join(candidate, "dom.json"), (value) => {
    value.nodes[0].role = "dialog";
  });
  const after = compare(reference, candidate).evidence_hashes;
  assert.notDeepEqual(after, before);
  assert.ok(
    after.includes(
    createHash("sha256")
      .update(readFileSync(join(candidate, "text.json")))
        .digest("hex"),
    ),
  );
});

test("rejects a report with forged or incomplete evidence hashes", () => {
  const { reference, candidate } = makeBundle();
  const evidence = compare(reference, candidate);
  evidence.artifactHashes.candidate["dom.json"] = "0".repeat(64);
  assert.throws(
    () => assertVisualEvidence(contract, evidence),
    /evidence hashes missing or inconsistent/,
  );
});

test("rejects comparison hashes not bound to their named artifacts", () => {
  const { reference, candidate } = makeBundle();
  const evidence = compare(reference, candidate);
  evidence.snapshots.dom.reference_sha256 = "0".repeat(64);
  evidence.accessibility.candidate_sha256 = "1".repeat(64);
  assert.throws(
    () => assertVisualEvidence(contract, evidence),
    /comparison hash differs from artifact/,
  );
});

for (const [field, message] of [
  ["maxOtherBoundaryDeltaPx", /boundary delta/],
  ["pixelMismatchRatio", /pixel mismatch/],
  ["consoleErrors", /console error/],
  ["pageErrors", /page error/],
  ["masks", /masks missing/],
]) {
  test(`rejects a report missing ${field}`, () => {
    const { reference, candidate } = makeBundle();
    const evidence = compare(reference, candidate);
    delete evidence[field];
    assert.throws(() => assertVisualEvidence(contract, evidence), message);
  });
}

test("rejects a PNG with an invalid chunk checksum", () => {
  const { reference, candidate } = makeBundle();
  const screenshot = join(candidate, "screenshot.png");
  const content = Buffer.from(readFileSync(screenshot));
  content[29] ^= 0x01;
  writeFileSync(screenshot, content);
  assert.throws(
    () => compare(reference, candidate),
    /PNG evidence has an invalid/,
  );
});

test("rejects a PNG with trailing data after IEND", () => {
  const { reference, candidate } = makeBundle();
  const screenshot = join(candidate, "screenshot.png");
  writeFileSync(
    screenshot,
    Buffer.concat([readFileSync(screenshot), Buffer.from("trailing")]),
  );
  assert.throws(
    () => compare(reference, candidate),
    /trailing data/,
  );
});

test("rejects a visual mask that intersects a business component", () => {
  const { reference, candidate } = makeBundle();
  for (const root of [reference, candidate]) {
    mutateJson(join(root, "runtime.json"), (value) => {
      value.masks = [
        {
          selector: "#critical",
          rectangle: [0, 0, 1, 1],
          reason: "font-antialiasing",
          owner: "visual-platform",
        },
      ];
    });
  }
  const evidence = compare(reference, candidate);
  assert.equal(evidence.masks[0].coversBusinessComponent, true);
  assert.throws(
    () => assertVisualEvidence(contract, evidence),
    /business component/,
  );
});

test("rejects a visual mask with non-positive dimensions", () => {
  const { reference, candidate } = makeBundle();
  for (const root of [reference, candidate]) {
    mutateJson(join(root, "runtime.json"), (value) => {
      value.masks = [
        {
          selector: "html",
          rectangle: [500, 500, 0, -1],
          reason: "font-antialiasing",
          owner: "visual-platform",
        },
      ];
    });
  }
  assert.throws(
    () => compare(reference, candidate),
    /mask rectangle/,
  );
});

test("rejects a mask reason other than font antialiasing", () => {
  const { reference, candidate } = makeBundle();
  for (const root of [reference, candidate]) {
    mutateJson(join(root, "runtime.json"), (value) => {
      value.masks = [{
        selector: "html",
        rectangle: [500, 500, 1, 1],
        reason: "cursor",
        owner: "visual-platform",
      }];
    });
  }
  const evidence = compare(reference, candidate);
  assert.throws(() => assertVisualEvidence(contract, evidence), /mask reason forbidden/);
});

test("rejects candidate-only mask definitions", () => {
  const { reference, candidate } = makeBundle();
  mutateJson(join(candidate, "runtime.json"), (value) => {
    value.masks = [
      {
        selector: "html",
        rectangle: [500, 500, 1, 1],
        reason: "font-antialiasing",
        owner: "visual-platform",
      },
    ];
  });
  assert.throws(
    () => compare(reference, candidate),
    /mask definitions differ/,
  );
});

test("rejects missing artifact files rather than inventing evidence", () => {
  const { reference, candidate } = makeBundle();
  assert.throws(
    () =>
      compare(reference, join(candidate, "missing")),
    /evidence artifact/,
  );
});

test("rejects incomplete observations rather than treating them as empty", () => {
  const { reference, candidate } = makeBundle();
  mutateJson(join(candidate, "runtime.json"), (value) => {
    delete value.consoleErrors;
  });
  assert.throws(
    () => compare(reference, candidate),
    /candidate console errors evidence must be an array/,
  );
});

test("rejects identically empty semantic and interaction observations", () => {
  const { reference, candidate } = makeBundle();
  for (const root of [reference, candidate]) {
    mutateJson(join(root, "runtime.json"), (value) => {
      value.semanticIds = [];
      value.interactionIds = [];
    });
  }
  assert.throws(
    () => compare(reference, candidate),
    /semantic IDs evidence must not be empty/,
  );
});

for (const [name, file, value, message] of [
  ["DOM", "dom.json", { nodes: [] }, /DOM evidence must not be empty/],
  ["class", "class.json", {}, /class evidence must not be empty/],
  ["text", "text.json", {}, /text evidence must not be empty/],
  ["event", "event.json", [], /event evidence must not be empty/],
  [
    "computed-style",
    "computed-style.json",
    {},
    /computed-style evidence must not be empty/,
  ],
]) {
  test(`rejects identically empty ${name} observations`, () => {
    const { reference, candidate } = makeBundle();
    for (const root of [reference, candidate]) {
      writeJson(join(root, file), value);
    }
    assert.throws(() => compare(reference, candidate), message);
  });
}

test("rejects geometry without an explicit business-component classification", () => {
  const { reference, candidate } = makeBundle();
  for (const root of [reference, candidate]) {
    mutateJson(join(root, "geometry.json"), (value) => {
      delete value.elements[0].businessComponent;
    });
  }
  assert.throws(
    () => compare(reference, candidate),
    /businessComponent/,
  );
});

test("rejects geometry that silently downgrades a critical anchor", () => {
  const { reference, candidate } = makeBundle();
  mutateJson(join(candidate, "geometry.json"), (value) => {
    value.elements[0].critical = false;
  });
  assert.throws(
    () => compare(reference, candidate),
    /geometry classification differs/,
  );
});

test("rejects geometry that silently downgrades a business component", () => {
  const { reference, candidate } = makeBundle();
  mutateJson(join(candidate, "geometry.json"), (value) => {
    value.elements[0].businessComponent = false;
  });
  assert.throws(
    () => compare(reference, candidate),
    /geometry classification differs/,
  );
});

test("rejects geometry evidence with no critical or business components", () => {
  const { reference, candidate } = makeBundle();
  for (const root of [reference, candidate]) {
    mutateJson(join(root, "geometry.json"), (value) => {
      for (const element of value.elements) {
        element.critical = false;
        element.businessComponent = false;
      }
    });
  }
  assert.throws(
    () => compare(reference, candidate),
    /geometry evidence must classify/,
  );
});

test("rejects empty successful accessibility and input evidence", () => {
  const { reference, candidate } = makeBundle();
  for (const root of [reference, candidate]) {
    writeJson(join(root, "accessibility.json"), { violations: [] });
    writeJson(join(root, "keyboard.json"), { failures: [], steps: [] });
    writeJson(join(root, "ime.json"), { failures: [], committed: "" });
    writeJson(join(root, "mobile.json"), {
      failures: [],
      checks: [],
      horizontalOverflowPx: 0,
    });
  }
  assert.throws(
    () => compare(reference, candidate),
    /accessibility checks evidence must not be empty/,
  );
});

test("CLI writes a computed report only after every gate passes", () => {
  const bundle = makeBundle();
  const output = join(bundle.root, "report.json");
  const result = runVisualComparison([
    "--contract",
    join(
      here,
      "../../../tests/fixtures/knowledge_workspace_v21141/visual-contract.json",
    ),
    "--reference",
    bundle.reference,
    "--candidate",
    bundle.candidate,
    "--scenario",
    bundle.scenarioId,
    "--viewport",
    bundle.viewport,
    "--output",
    output,
  ]);
  assert.equal(result.pixelMismatchRatio, 0);
  assert.deepEqual(JSON.parse(readFileSync(output, "utf8")), result);
});
