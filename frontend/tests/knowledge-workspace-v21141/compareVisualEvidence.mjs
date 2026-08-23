#!/usr/bin/env node

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import {
  assertVisualEvidence,
  compareEvidenceBundle,
  loadVisualContract,
} from "./visualGate.mjs";

function parseArguments(args) {
  const result = {};
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index];
    const value = args[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(
        "usage: compareVisualEvidence.mjs --contract PATH --reference DIR " +
          "--candidate DIR --scenario GM-XX --viewport WIDTHxHEIGHT --output PATH",
      );
    }
    result[key.slice(2)] = value;
  }
  for (const key of [
    "contract",
    "reference",
    "candidate",
    "scenario",
    "viewport",
    "output",
  ]) {
    if (!result[key]) throw new Error(`missing --${key}`);
  }
  return result;
}

export function runVisualComparison(args) {
  const options = parseArguments(args);
  const contract = loadVisualContract(resolve(options.contract));
  const evidence = compareEvidenceBundle(contract, {
    reference: resolve(options.reference),
    candidate: resolve(options.candidate),
    scenarioId: options.scenario,
    viewport: options.viewport,
  });
  assertVisualEvidence(contract, evidence);
  const output = resolve(options.output);
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, `${JSON.stringify(evidence, null, 2)}\n`);
  return evidence;
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  try {
    const evidence = runVisualComparison(process.argv.slice(2));
    process.stdout.write(
      `${JSON.stringify({
        status: "pass",
        scenario_id: evidence.scenario_id,
        viewport: evidence.viewport,
        evidence_hashes: evidence.evidence_hashes,
      })}\n`,
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
    process.exitCode = 1;
  }
}
