import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const fixtureRoot = join(
  here,
  "../../../tests/fixtures/knowledge_workspace_v21141",
);
const load = (name) =>
  JSON.parse(readFileSync(join(fixtureRoot, name), "utf8"));

test("frozen visual thresholds and comparison layers are fail-closed", () => {
  const contract = load("visual-contract.json");
  assert.deepEqual(contract.thresholds, {
    critical_anchor_px: 0,
    other_boundary_px: 1,
    pixel_mismatch_ratio: 0.001,
  });
  for (const gate of [
    "screenshot",
    "dom",
    "class",
    "text",
    "event",
    "bounding-box",
    "computed-style",
    "pixel-diff",
    "console-error",
    "page-error",
    "accessibility",
    "keyboard",
    "ime",
    "mobile",
    "no-iframe",
    "no-production-fixture",
  ]) {
    assert.ok(contract.gates.includes(gate), `missing ${gate}`);
  }
  assert.equal(contract.mask_policy.business_component_masks_allowed, false);
  assert.deepEqual(contract.mask_policy.allowed_reasons, ["font-antialiasing"]);
  assert.equal(contract.evidence_output.identity_before_browser, true);
  assert.equal(contract.evidence_output.pair_artifacts.length, 12);
  const schema = load("visual-evidence.schema.json");
  assert.match(schema.$id, /visual-evidence-v2/);
  assert.deepEqual(schema.properties.screenshotDimensionsEqual, { const: true });
  assert.equal(schema.properties.evidence_hashes.minItems, 24);
});

test("Playwright cannot create a browser before frozen identity verification", () => {
  const config = readFileSync(
    join(here, "../../playwright.knowledge-workspace-v21141.config.mjs"),
    "utf8",
  );
  assert.match(
    config,
    /globalSetup:\s*"\.\/knowledgeWorkspaceV21141GlobalSetup\.mjs"/,
  );
});

test("one declarative trace drives both reference and candidate", () => {
  const { scenarios } = load("golden-master.json");
  assert.equal(scenarios.length, 20);
  assert.deepEqual(
    scenarios.map(({ id }) => id),
    Array.from({ length: 20 }, (_, index) =>
      `GM-${String(index + 1).padStart(2, "0")}`,
    ),
  );
  for (const scenario of scenarios) {
    assert.deepEqual(scenario.drivers, ["reference", "candidate"]);
    assert.equal(scenario.viewports.length, 4);
    assert.ok(scenario.actions.length);
    assert.ok(scenario.assertions.length);
    assert.ok(scenario.evidence.length);
  }
});

test("connector UI inventory stays complete and uncertified entries block GA", () => {
  const matrix = load("connector-certification-matrix.json");
  assert.equal(matrix.connectors.length, 37);
  const byId = new Map(matrix.connectors.map((item) => [item.id, item]));
  assert.equal(matrix.required_ga_connector_ids.length, 19);
  assert.equal(matrix.required_ga_certifications.length, 22);
  assert.ok(matrix.required_ga_connector_ids.includes("openapi_spec"));
  assert.ok(
    matrix.required_ga_certifications.some(
      ({ subject }) => subject === "openapi_spec",
    ),
  );
  for (const id of matrix.required_ga_connector_ids) {
    assert.ok(byId.has(id), `required connector ${id} missing`);
    const connector = byId.get(id);
    assert.equal(connector.ga_gate, "blocked");
    assert.notEqual(connector.certification_status, "ga-certified");
    assert.ok(connector.evidence.every(Boolean));
  }
  assert.deepEqual(
    matrix.required_ga_certifications
      .filter(({ connector_id }) => connector_id === "doc_txt")
      .map(({ profile }) => profile)
      .sort(),
    ["html", "markdown", "pdf", "txt"],
  );
});

test("STEP 1 never turns an E2E skeleton into a fake PASS", () => {
  const { policy, cases } = load("e2e-skeleton.json");
  assert.deepEqual(policy.allowed_statuses, ["blocked"]);
  assert.equal(cases.length, 13);
  assert.equal(cases.filter(({ status }) => status === "pass").length, 0);
  assert.ok(cases.every(({ evidence }) => evidence.length > 0));
  const matrix = load("connector-certification-matrix.json");
  const connectorCase = cases.find(
    ({ kind }) => kind === "required-connector",
  );
  assert.deepEqual(
    [...connectorCase.certification_subjects].sort(),
    matrix.required_ga_certifications.map(({ subject }) => subject).sort(),
  );
});
