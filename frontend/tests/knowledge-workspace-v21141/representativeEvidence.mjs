#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import { deflateSync } from "node:zlib";
import { decodePng } from "./visualPng.mjs";

const scenes = [
  {
    id: "GM-04",
    name: "Add Data",
    directory: "add-data",
    route: "/?file=add_data&step=1",
  },
  {
    id: "GM-10",
    name: "Dashboard",
    directory: "dashboard",
    route: "/?file=res_dash_east",
  },
  {
    id: "GM-13",
    name: "Knowledge Graph",
    directory: "knowledge-graph",
    route: "/?file=kg_sales",
  },
];

const root = resolve(
  process.env.KNOWLEDGE_REPRESENTATIVE_ROOT ??
    "/Users/bytedance/.codex/runtime/knowledge-v21141-commercial-step-2/representative",
);

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function crc32(content) {
  let crc = 0xffffffff;
  for (const byte of content) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, content) {
  const typeBytes = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(content.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBytes, content])));
  return Buffer.concat([length, typeBytes, content, checksum]);
}

function encodePng(width, height, rgba) {
  const rows = Buffer.alloc(height * (width * 4 + 1));
  for (let y = 0; y < height; y += 1) {
    const rowStart = y * (width * 4 + 1);
    rows[rowStart] = 0;
    rgba.copy(
      rows,
      rowStart + 1,
      y * width * 4,
      (y + 1) * width * 4,
    );
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  header[10] = 0;
  header[11] = 0;
  header[12] = 0;
  return Buffer.concat([
    Buffer.from("\x89PNG\r\n\x1a\n", "binary"),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function pixelDiff(referencePng, candidatePng) {
  const reference = decodePng(referencePng);
  const candidate = decodePng(candidatePng);
  if (
    reference.width !== candidate.width ||
    reference.height !== candidate.height
  ) {
    return {
      dimensionsEqual: false,
      mismatchRatio: 1,
      mismatchPixels: reference.width * reference.height,
      width: reference.width,
      height: reference.height,
      diff: Buffer.alloc(reference.width * reference.height * 4, 255),
    };
  }
  const diff = Buffer.alloc(reference.width * reference.height * 4);
  let mismatchPixels = 0;
  for (let index = 0; index < reference.width * reference.height; index += 1) {
    const offset = index * 4;
    const same =
      reference.rgba[offset] === candidate.rgba[offset] &&
      reference.rgba[offset + 1] === candidate.rgba[offset + 1] &&
      reference.rgba[offset + 2] === candidate.rgba[offset + 2] &&
      reference.rgba[offset + 3] === candidate.rgba[offset + 3];
    if (same) {
      diff[offset] = 0;
      diff[offset + 1] = 0;
      diff[offset + 2] = 0;
      diff[offset + 3] = 0;
    } else {
      mismatchPixels += 1;
      diff[offset] = 255;
      diff[offset + 1] = 0;
      diff[offset + 2] = 0;
      diff[offset + 3] = 255;
    }
  }
  return {
    dimensionsEqual: true,
    mismatchRatio: mismatchPixels / (reference.width * reference.height),
    mismatchPixels,
    width: reference.width,
    height: reference.height,
    diff,
  };
}

function arrayProjection(snapshot, keys) {
  return (snapshot.all ?? []).map((element) =>
    Object.fromEntries(keys.map((key) => [key, element[key]]))
  );
}

function maxGeometryDelta(reference, candidate) {
  const count = Math.min(reference.all?.length ?? 0, candidate.all?.length ?? 0);
  let max = 0;
  for (let index = 0; index < count; index += 1) {
    const left = reference.all[index].box;
    const right = candidate.all[index].box;
    for (const key of ["x", "y", "width", "height"]) {
      max = Math.max(max, Math.abs((left?.[key] ?? 0) - (right?.[key] ?? 0)));
    }
  }
  return max;
}

function compareScene(scene) {
  const sceneRoot = resolve(root, scene.directory);
  const referencePng = readFileSync(resolve(sceneRoot, "reference.png"));
  const candidatePng = readFileSync(resolve(sceneRoot, "candidate.png"));
  const reference = JSON.parse(readFileSync(resolve(sceneRoot, "reference.json")));
  const candidate = JSON.parse(readFileSync(resolve(sceneRoot, "candidate.json")));
  const pixels = pixelDiff(referencePng, candidatePng);
  writeFileSync(
    resolve(sceneRoot, "diff-online.png"),
    encodePng(pixels.width, pixels.height, pixels.diff),
  );
  const report = {
    scenario_id: scene.id,
    name: scene.name,
    route: scene.route,
    environment: {
      browser: "Google Chrome",
      viewport: "1440x900",
      deviceScaleFactor: 1,
      locale: "zh-CN",
      timezone: "Asia/Shanghai",
      colorScheme: "light",
      reducedMotion: "reduce",
    },
    evidence: {
      reference_png: resolve(sceneRoot, "reference.png"),
      candidate_png: resolve(sceneRoot, "candidate.png"),
      diff_png: resolve(sceneRoot, "diff-online.png"),
      reference_sha256: sha256(referencePng),
      candidate_sha256: sha256(candidatePng),
      diff_sha256: sha256(readFileSync(resolve(sceneRoot, "diff-online.png"))),
    },
    pixel: {
      dimensionsEqual: pixels.dimensionsEqual,
      width: pixels.width,
      height: pixels.height,
      mismatchPixels: pixels.mismatchPixels,
      mismatchRatio: pixels.mismatchRatio,
      mismatchPercent: pixels.mismatchRatio * 100,
    },
    structure: {
      referenceElementCount: reference.all?.length ?? 0,
      candidateElementCount: candidate.all?.length ?? 0,
      domEqual: JSON.stringify(arrayProjection(reference, ["tag", "id", "text"])) ===
        JSON.stringify(arrayProjection(candidate, ["tag", "id", "text"])),
      classEqual: JSON.stringify(arrayProjection(reference, ["cls"])) ===
        JSON.stringify(arrayProjection(candidate, ["cls"])),
      textEqual: reference.bodyText === candidate.bodyText,
      computedStyleEqual: JSON.stringify(arrayProjection(reference, [
        "fontFamily",
        "fontSize",
        "fontWeight",
        "lineHeight",
        "color",
        "backgroundColor",
        "border",
        "borderRadius",
        "boxShadow",
        "display",
        "position",
        "padding",
        "margin",
        "gap",
        "letterSpacing",
        "opacity",
        "overflow",
      ])) === JSON.stringify(arrayProjection(candidate, [
        "fontFamily",
        "fontSize",
        "fontWeight",
        "lineHeight",
        "color",
        "backgroundColor",
        "border",
        "borderRadius",
        "boxShadow",
        "display",
        "position",
        "padding",
        "margin",
        "gap",
        "letterSpacing",
        "opacity",
        "overflow",
      ])),
      maxIndexedGeometryDeltaPx: maxGeometryDelta(reference, candidate),
    },
    runtime: {
      referenceConsoleErrors: reference.consoleErrors ?? [],
      candidateConsoleErrors: candidate.consoleErrors ?? [],
      referencePageErrors: reference.pageErrors ?? [],
      candidatePageErrors: candidate.pageErrors ?? [],
      status: (reference.consoleErrors?.length ?? 0) === 0 &&
          (candidate.consoleErrors?.length ?? 0) === 0 &&
          (reference.pageErrors?.length ?? 0) === 0 &&
          (candidate.pageErrors?.length ?? 0) === 0
        ? "pass"
        : "fail",
    },
    verdict: "BLOCKED",
    blockedReasons: [],
  };
  if (scene.id === "GM-04" && report.structure.candidateElementCount <
      report.structure.referenceElementCount) {
    report.blockedReasons.push(
      "candidate production bootstrap did not provide the online 37-connector catalog; UI rendered 0 connector cards",
    );
  }
  if (!report.structure.domEqual) report.blockedReasons.push("DOM differs");
  if (!report.structure.classEqual) report.blockedReasons.push("class differs");
  if (!report.structure.textEqual) report.blockedReasons.push("text differs");
  if (!report.structure.computedStyleEqual) {
    report.blockedReasons.push("computed style differs");
  }
  if (report.pixel.mismatchRatio > 0.001) {
    report.blockedReasons.push("pixel mismatch exceeds 0.1%");
  }
  if (report.runtime.status !== "pass") report.blockedReasons.push("runtime errors");
  writeFileSync(
    resolve(sceneRoot, "scene-report.json"),
    `${JSON.stringify(report, null, 2)}\n`,
  );
  return report;
}

const reports = scenes.map(compareScene);
const total = {
  generated_at: new Date().toISOString(),
  environment: reports[0].environment,
  reference: "https://6a8afc013497970234090688-prototype.inspire.bytedance.net",
  candidate: "http://127.0.0.1:4173/?studio=knowledge",
  scenes: reports,
  status: "BLOCKED",
  blocked: [
    "GM-01 full document-level gate is not re-run in this representative-page batch; prior GM-01 capture/interactions remain PASS_FOR_GM01_CAPTURE_AND_REAL_INTERACTION_PROBES_BUT_NOT_FULL_DOCUMENT_1_TO_1_GATE",
    ...reports.flatMap((report) =>
      report.blockedReasons.map((reason) => `${report.scenario_id}: ${reason}`),
    ),
  ],
};
writeFileSync(
  resolve(root, "representative-report.json"),
  `${JSON.stringify(total, null, 2)}\n`,
);
process.stdout.write(`${JSON.stringify({
  status: total.status,
  scenes: reports.map(({ scenario_id, pixel, blockedReasons }) => ({
    scenario_id,
    mismatchPercent: pixel.mismatchPercent,
    blockedReasons,
  })),
})}\n`);
