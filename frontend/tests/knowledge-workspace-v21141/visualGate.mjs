import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { comparePng } from "./visualPng.mjs";

const JSON_ARTIFACTS = [
  ["dom", "dom.json"],
  ["class", "class.json"],
  ["text", "text.json"],
  ["event", "event.json"],
  ["geometry", "geometry.json"],
  ["computedStyle", "computed-style.json"],
  ["runtime", "runtime.json"],
  ["accessibility", "accessibility.json"],
  ["keyboard", "keyboard.json"],
  ["ime", "ime.json"],
  ["mobile", "mobile.json"],
];
export function loadVisualContract(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function readArtifact(root, name) {
  const path = join(root, name);
  if (!existsSync(path)) {
    throw new Error(`missing evidence artifact: ${path}`);
  }
  return readFileSync(path);
}

function readJsonArtifact(root, name) {
  const content = readArtifact(root, name);
  let value;
  try {
    value = JSON.parse(content.toString("utf8"));
  } catch (error) {
    throw new Error(`invalid JSON evidence artifact ${join(root, name)}: ${error}`);
  }
  return { content, value, sha256: sha256(content) };
}

function snapshotComparison(reference, candidate) {
  return {
    equal: isDeepStrictEqual(reference.value, candidate.value),
    reference_sha256: reference.sha256,
    candidate_sha256: candidate.sha256,
  };
}

function finiteBox(box, selector) {
  const coordinates = ["x", "y", "width", "height"];
  if (
    typeof box !== "object" ||
    coordinates.some((key) => !Number.isFinite(box?.[key]))
  ) {
    throw new Error(`invalid geometry evidence for ${selector}`);
  }
  return coordinates.map((key) => box[key]);
}

function geometryDeltas(reference, candidate) {
  const toMap = (artifact) => {
    if (!Array.isArray(artifact.value?.elements)) {
      throw new Error("geometry evidence must contain elements");
    }
    const entries = artifact.value.elements.map((element) => {
      if (
        !element.selector ||
        typeof element.critical !== "boolean" ||
        typeof element.businessComponent !== "boolean"
      ) {
        throw new Error(
          "geometry element requires selector, critical, and businessComponent",
        );
      }
      return [element.selector, element];
    });
    if (new Set(entries.map(([selector]) => selector)).size !== entries.length) {
      throw new Error("geometry evidence contains duplicate selectors");
    }
    return new Map(entries);
  };
  const left = toMap(reference);
  const right = toMap(candidate);
  const selectors = new Set([...left.keys(), ...right.keys()]);
  for (const selector of selectors) {
    const referenceElement = left.get(selector);
    const candidateElement = right.get(selector);
    if (
      !referenceElement ||
      !candidateElement ||
      referenceElement.critical !== candidateElement.critical ||
      referenceElement.businessComponent !== candidateElement.businessComponent
    ) {
      throw new Error(`geometry classification differs for ${selector}`);
    }
  }
  if (
    ![...left.values()].some((element) => element.critical) ||
    ![...left.values()].some((element) => element.businessComponent) ||
    ![...right.values()].some((element) => element.critical) ||
    ![...right.values()].some((element) => element.businessComponent)
  ) {
    throw new Error(
      "geometry evidence must classify critical anchors and business components",
    );
  }
  let maxCritical = 0;
  let maxOther = 0;
  for (const selector of selectors) {
    const referenceElement = left.get(selector);
    const candidateElement = right.get(selector);
    if (!referenceElement || !candidateElement) continue;
    const referenceBox = finiteBox(referenceElement.box, selector);
    const candidateBox = finiteBox(candidateElement.box, selector);
    const delta = Math.max(
      ...referenceBox.map((value, index) =>
        Math.abs(value - candidateBox[index]),
      ),
    );
    if (referenceElement.critical) maxCritical = Math.max(maxCritical, delta);
    else maxOther = Math.max(maxOther, delta);
  }
  return {
    maxCriticalAnchorDeltaPx: maxCritical,
    maxOtherBoundaryDeltaPx: maxOther,
  };
}

function symmetricDifferenceCount(reference = [], candidate = []) {
  const left = new Set(reference);
  const right = new Set(candidate);
  return [...left].filter((value) => !right.has(value)).length +
    [...right].filter((value) => !left.has(value)).length;
}

function requireArray(value, label) {
  if (!Array.isArray(value)) {
    throw new Error(`${label} evidence must be an array`);
  }
  return value;
}

function requireNonEmptyArray(value, label) {
  const result = requireArray(value, label);
  if (result.length === 0) {
    throw new Error(`${label} evidence must not be empty`);
  }
  return result;
}

function requireNonEmptyObservation(value, label) {
  const hasContent = (item) => {
    if (typeof item === "string") return item.length > 0;
    if (Array.isArray(item)) return item.length > 0 && item.some(hasContent);
    if (item && typeof item === "object") {
      return Object.values(item).some(hasContent);
    }
    return typeof item === "number" || typeof item === "boolean";
  };
  if (!hasContent(value)) {
    throw new Error(`${label} evidence must not be empty`);
  }
  if (typeof value !== "object" && typeof value !== "string") {
    throw new Error(`${label} evidence has an invalid shape`);
  }
  return value;
}

function statusEvidence(reference, candidate, kind) {
  const equal = isDeepStrictEqual(reference.value, candidate.value);
  const value = candidate.value;
  let hasFailure = !equal;
  if (kind === "accessibility") {
    for (const [side, artifact] of [
      ["reference", reference],
      ["candidate", candidate],
    ]) {
      if (
        !Number.isInteger(artifact.value?.checkedNodes) ||
        artifact.value.checkedNodes <= 0
      ) {
        throw new Error(
          `${side} accessibility checks evidence must not be empty`,
        );
      }
    }
    hasFailure ||=
      requireArray(reference.value?.violations, "reference accessibility")
        .length > 0 ||
      requireArray(value?.violations, "candidate accessibility").length > 0;
  } else if (kind === "mobile") {
    requireNonEmptyArray(reference.value?.checks, "reference mobile checks");
    requireNonEmptyArray(value?.checks, "candidate mobile checks");
    hasFailure ||=
      !Number.isFinite(value?.horizontalOverflowPx) ||
      value.horizontalOverflowPx > 0 ||
      requireArray(reference.value?.failures, "reference mobile").length > 0 ||
      requireArray(value?.failures, "candidate mobile").length > 0;
  } else if (kind === "keyboard") {
    requireNonEmptyArray(reference.value?.steps, "reference keyboard steps");
    requireNonEmptyArray(value?.steps, "candidate keyboard steps");
    hasFailure ||=
      requireArray(reference.value?.failures, "reference keyboard").length > 0 ||
      requireArray(value?.failures, "candidate keyboard").length > 0;
  } else if (kind === "ime") {
    if (
      typeof reference.value?.committed !== "string" ||
      !reference.value.committed ||
      typeof value?.committed !== "string" ||
      !value.committed
    ) {
      throw new Error("IME committed evidence must not be empty");
    }
    hasFailure ||=
      requireArray(reference.value?.failures, "reference ime").length > 0 ||
      requireArray(value?.failures, "candidate ime").length > 0;
  } else {
    hasFailure ||=
      requireArray(reference.value?.failures, `reference ${kind}`).length > 0 ||
      requireArray(value?.failures, `candidate ${kind}`).length > 0;
  }
  return {
    status: hasFailure ? "fail" : "pass",
    reference_sha256: reference.sha256,
    candidate_sha256: candidate.sha256,
  };
}

function maskCoversBusinessComponent(mask, geometry) {
  const [left, top, width, height] = mask.rectangle ?? [];
  if (
    ![left, top, width, height].every(Number.isFinite) ||
    width <= 0 ||
    height <= 0
  ) {
    throw new Error("mask rectangle must have positive dimensions");
  }
  return (geometry.value?.elements ?? [])
    .filter((element) => element.businessComponent === true)
    .some((element) => {
      const [x, y, elementWidth, elementHeight] = finiteBox(
        element.box,
        element.selector,
      );
      return (
        left < x + elementWidth &&
        left + width > x &&
        top < y + elementHeight &&
        top + height > y
      );
    });
}

export function compareEvidenceBundle(contract, roots) {
  if (!roots?.reference || !roots?.candidate) {
    throw new Error("reference and candidate evidence roots are required");
  }
  if (!/^GM-(0[1-9]|1[0-9]|20)$/.test(roots.scenarioId ?? "")) {
    throw new Error("a valid GM-01 through GM-20 scenarioId is required");
  }
  const viewport = roots.viewport ?? "";
  if (!contract.environment.viewports.some((value) => value.join("x") === viewport)) {
    throw new Error("a frozen viewport is required");
  }
  const artifacts = { reference: {}, candidate: {} };
  const artifactHashes = { reference: {}, candidate: {} };
  for (const side of ["reference", "candidate"]) {
    for (const [key, file] of JSON_ARTIFACTS) {
      artifacts[side][key] = readJsonArtifact(roots[side], file);
      artifactHashes[side][file] = artifacts[side][key].sha256;
    }
  }
  for (const [key, label] of [
    ["dom", "DOM"],
    ["class", "class"],
    ["text", "text"],
    ["event", "event"],
    ["computedStyle", "computed-style"],
  ]) {
    requireNonEmptyObservation(artifacts.reference[key].value, `reference ${label}`);
    requireNonEmptyObservation(artifacts.candidate[key].value, `candidate ${label}`);
  }
  const referencePng = readArtifact(roots.reference, "screenshot.png");
  const candidatePng = readArtifact(roots.candidate, "screenshot.png");
  artifactHashes.reference["screenshot.png"] = sha256(referencePng);
  artifactHashes.candidate["screenshot.png"] = sha256(candidatePng);
  const evidenceHashes = ["reference", "candidate"].flatMap((side) =>
    contract.evidence_output.pair_artifacts.map(
      (file) => artifactHashes[side][file],
    ),
  );

  const referenceMasks = artifacts.reference.runtime.value?.masks ?? [];
  const candidateMasks = artifacts.candidate.runtime.value?.masks ?? [];
  if (!isDeepStrictEqual(referenceMasks, candidateMasks)) {
    throw new Error("reference and candidate mask definitions differ");
  }
  const masks = candidateMasks.map((mask) => ({
    ...mask,
    coversBusinessComponent:
      maskCoversBusinessComponent(mask, artifacts.reference.geometry) ||
      maskCoversBusinessComponent(mask, artifacts.candidate.geometry),
  }));
  const [expectedWidth, expectedHeight] = viewport.split("x").map(Number);
  const pixels = comparePng(referencePng, candidatePng, masks, {
    width: expectedWidth,
    height: expectedHeight,
  });
  const geometry = geometryDeltas(
    artifacts.reference.geometry,
    artifacts.candidate.geometry,
  );
  const runtime = artifacts.candidate.runtime.value;
  const referenceRuntime = artifacts.reference.runtime.value;
  const referenceSemanticIds = requireNonEmptyArray(
    referenceRuntime.semanticIds,
    "reference semantic IDs",
  );
  const candidateSemanticIds = requireNonEmptyArray(
    runtime.semanticIds,
    "candidate semantic IDs",
  );
  const referenceInteractionIds = requireNonEmptyArray(
    referenceRuntime.interactionIds,
    "reference interaction IDs",
  );
  const candidateInteractionIds = requireNonEmptyArray(
    runtime.interactionIds,
    "candidate interaction IDs",
  );
  const consoleErrors = [
    ...requireArray(referenceRuntime.consoleErrors, "reference console errors"),
    ...requireArray(runtime.consoleErrors, "candidate console errors"),
  ];
  const pageErrors = [
    ...requireArray(referenceRuntime.pageErrors, "reference page errors"),
    ...requireArray(runtime.pageErrors, "candidate page errors"),
  ];
  const iframes = [
    ...requireArray(referenceRuntime.iframes, "reference iframes"),
    ...requireArray(runtime.iframes, "candidate iframes"),
  ];
  const fixtureReferences = [
    ...requireArray(
      referenceRuntime.productionFixtureReferences,
      "reference production fixture references",
    ),
    ...requireArray(
      runtime.productionFixtureReferences,
      "candidate production fixture references",
    ),
  ];
  return {
    scenario_id: roots.scenarioId,
    viewport,
    snapshots: {
      dom: snapshotComparison(artifacts.reference.dom, artifacts.candidate.dom),
      class: snapshotComparison(
        artifacts.reference.class,
        artifacts.candidate.class,
      ),
      text: snapshotComparison(
        artifacts.reference.text,
        artifacts.candidate.text,
      ),
      event: snapshotComparison(
        artifacts.reference.event,
        artifacts.candidate.event,
      ),
      computedStyle: snapshotComparison(
        artifacts.reference.computedStyle,
        artifacts.candidate.computedStyle,
      ),
    },
    screenshotDimensionsEqual: pixels.dimensionsEqual,
    semanticMissing: symmetricDifferenceCount(
      referenceSemanticIds,
      candidateSemanticIds,
    ),
    interactionMissing: symmetricDifferenceCount(
      referenceInteractionIds,
      candidateInteractionIds,
    ),
    ...geometry,
    pixelMismatchRatio: pixels.mismatchRatio,
    consoleErrors,
    pageErrors,
    accessibility: statusEvidence(
      artifacts.reference.accessibility,
      artifacts.candidate.accessibility,
      "accessibility",
    ),
    keyboard: statusEvidence(
      artifacts.reference.keyboard,
      artifacts.candidate.keyboard,
      "keyboard",
    ),
    ime: statusEvidence(
      artifacts.reference.ime,
      artifacts.candidate.ime,
      "ime",
    ),
    mobile: statusEvidence(
      artifacts.reference.mobile,
      artifacts.candidate.mobile,
      "mobile",
    ),
    iframeCount: iframes.length,
    productionFixtureReferences: fixtureReferences.length,
    masks,
    artifactHashes,
    evidence_hashes: evidenceHashes,
  };
}

export function assertVisualEvidence(contract, evidence) {
  const failures = [];
  const snapshotArtifacts = {
    dom: "dom.json",
    class: "class.json",
    text: "text.json",
    event: "event.json",
    computedStyle: "computed-style.json",
  };
  if (!/^GM-(0[1-9]|1[0-9]|20)$/.test(evidence.scenario_id ?? "")) {
    failures.push("invalid scenario ID");
  }
  if (
    !contract.environment.viewports.some(
      (viewport) => viewport.join("x") === evidence.viewport,
    )
  ) {
    failures.push("invalid viewport");
  }
  for (const snapshot of ["dom", "class", "text", "event", "computedStyle"]) {
    if (evidence.snapshots?.[snapshot]?.equal !== true) {
      failures.push(
        `${snapshot === "computedStyle" ? "computed-style" : snapshot} snapshot mismatch or missing`,
      );
    }
    for (const field of ["reference_sha256", "candidate_sha256"]) {
      if (!/^[0-9a-f]{64}$/.test(evidence.snapshots?.[snapshot]?.[field] ?? "")) {
        failures.push(`${snapshot} ${field} missing`);
      }
    }
    if (
      evidence.snapshots?.[snapshot]?.reference_sha256 !==
        evidence.artifactHashes?.reference?.[snapshotArtifacts[snapshot]] ||
      evidence.snapshots?.[snapshot]?.candidate_sha256 !==
        evidence.artifactHashes?.candidate?.[snapshotArtifacts[snapshot]]
    ) {
      failures.push(`${snapshot} comparison hash differs from artifact`);
    }
  }
  if (evidence.screenshotDimensionsEqual !== true) {
    failures.push("screenshot dimensions mismatch");
  }
  if (evidence.semanticMissing !== 0) failures.push("semantic content missing");
  if (evidence.interactionMissing !== 0) {
    failures.push("interaction coverage missing");
  }
  if (evidence.maxCriticalAnchorDeltaPx !== 0) {
    failures.push("critical anchor moved");
  }
  if (
    !Number.isFinite(evidence.maxOtherBoundaryDeltaPx) ||
    evidence.maxOtherBoundaryDeltaPx < 0 ||
    evidence.maxOtherBoundaryDeltaPx > contract.thresholds.other_boundary_px
  ) {
    failures.push("boundary delta exceeds 1px");
  }
  if (
    !Number.isFinite(evidence.pixelMismatchRatio) ||
    evidence.pixelMismatchRatio < 0 ||
    evidence.pixelMismatchRatio > contract.thresholds.pixel_mismatch_ratio
  ) {
    failures.push("pixel mismatch exceeds 0.1%");
  }
  if (!Array.isArray(evidence.consoleErrors) || evidence.consoleErrors.length) {
    failures.push("console error");
  }
  if (!Array.isArray(evidence.pageErrors) || evidence.pageErrors.length) {
    failures.push("page error");
  }
  for (const gate of ["accessibility", "keyboard", "ime", "mobile"]) {
    if (evidence[gate]?.status !== "pass") failures.push(`${gate} failed`);
    for (const field of ["reference_sha256", "candidate_sha256"]) {
      if (!/^[0-9a-f]{64}$/.test(evidence[gate]?.[field] ?? "")) {
        failures.push(`${gate} ${field} missing`);
      }
    }
    if (
      evidence[gate]?.reference_sha256 !==
        evidence.artifactHashes?.reference?.[`${gate}.json`] ||
      evidence[gate]?.candidate_sha256 !==
        evidence.artifactHashes?.candidate?.[`${gate}.json`]
    ) {
      failures.push(`${gate} comparison hash differs from artifact`);
    }
  }
  if (evidence.iframeCount !== 0) failures.push("iframe present");
  if (evidence.productionFixtureReferences !== 0) {
    failures.push("production fixture reachable");
  }
  const expectedEvidenceHashes = [];
  for (const side of ["reference", "candidate"]) {
    const hashes = evidence.artifactHashes?.[side];
    for (const file of contract.evidence_output.pair_artifacts) {
      const hash = hashes?.[file];
      if (!/^[0-9a-f]{64}$/.test(hash ?? "")) {
        failures.push(`${side} artifact hash missing: ${file}`);
      } else {
        expectedEvidenceHashes.push(hash);
      }
    }
  }
  if (
    !Array.isArray(evidence.evidence_hashes) ||
    !isDeepStrictEqual(evidence.evidence_hashes, expectedEvidenceHashes)
  ) {
    failures.push("evidence hashes missing or inconsistent");
  }

  if (!Array.isArray(evidence.masks)) failures.push("masks missing");
  for (const mask of evidence.masks ?? []) {
    if (!contract.mask_policy.allowed_reasons.includes(mask.reason)) {
      failures.push(`mask reason forbidden: ${mask.reason}`);
    }
    for (const field of contract.mask_policy.required_fields) {
      if (mask[field] === undefined || mask[field] === "") {
        failures.push(`mask field missing: ${field}`);
      }
    }
    if (mask.coversBusinessComponent === true) {
      failures.push("mask covers business component");
    }
    if (
      !Array.isArray(mask.rectangle) ||
      mask.rectangle.length !== 4 ||
      !mask.rectangle.every(Number.isFinite)
    ) {
      failures.push("mask rectangle invalid");
    }
  }
  if (failures.length) throw new Error(failures.join("; "));
  return { status: "pass" };
}
