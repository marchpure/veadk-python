import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { verifyBaselineIdentity } from "../../knowledgeWorkspaceV21141GlobalSetup.mjs";

test("Playwright setup verifies frozen identity and writes a runtime receipt", () => {
  const runtime = mkdtempSync(join(tmpdir(), "knowledge-v21141-identity-"));
  const calls = [];
  const report = verifyBaselineIdentity({
    env: {
      KNOWLEDGE_V21141_ARCHIVE: "/runtime/frozen.tar.gz",
      KNOWLEDGE_V21141_CAPTURE_DIR: "/runtime/captures",
      KNOWLEDGE_V21141_EVIDENCE_DIR: runtime,
      KNOWLEDGE_V21141_PYTHON: "/runtime/python-env/bin/python",
    },
    run(command, args) {
      calls.push({ command, args });
      if (args.includes("verify-captures")) {
        return {
          status: 0,
          stdout: JSON.stringify({
            status: "pass",
            capture_states: 13,
            unique_pngs: 12,
          }),
          stderr: "",
        };
      }
      return {
        status: 0,
        stdout: JSON.stringify({
          status: "pass",
          tar_sha256: "b5c172e6b1d79d5617ff49bfb11875507e25d33a5ee32af3ef90be4aa32ef773",
          source_tree_sha256: "57e97670c6091219dcf1ac35d76dd174a45c9fa69841ce5b7887caef39b27c83",
          source_file_count: 47,
          source_lines_posix: 9514,
          source_bytes: 607128,
          readme_sha256: "9c7570ba151c2f3c64a85276202450bebe217f5f1f886134b2258288bc7313d8",
          captures_sha256: "83f05bb57e7039bbe715078dd0e818074b30de3f45e2a85349c21af090fe5199",
          root_route_manifest_sha256: "339670643d53423e28850a0a6babff31a1042bdf6937897ac26ad35f8e4b5746",
          complete_route_manifest_sha256: "51a972c437e0580384249cc183cc7ec70d3292f416b5a4986e12bc32e5b8c92b",
          dependencies_sha256: "04a91782d6cd93dad26da3e529ac414ab29e6654063cf1655f5aebeae8e0c716",
        }),
        stderr: "",
      };
    },
  });
  assert.equal(report.status, "pass");
  assert.equal(report.captures.status, "pass");
  assert.equal(calls.length, 2);
  assert.equal(calls[0].command, "/runtime/python-env/bin/python");
  assert.equal(calls[1].command, "/runtime/python-env/bin/python");
  assert.match(calls[0].args.join(" "), /verify-archive/);
  assert.match(calls[1].args.join(" "), /verify-captures/);
  assert.equal(
    JSON.parse(readFileSync(join(runtime, "baseline-identity-receipt.json")))
      .status,
    "pass",
  );
});

test("Playwright setup fails before browser work when archive is absent", () => {
  assert.throws(
    () =>
      verifyBaselineIdentity({
        env: { KNOWLEDGE_V21141_EVIDENCE_DIR: tmpdir() },
        run() {
          throw new Error("must not run");
        },
      }),
    /KNOWLEDGE_V21141_ARCHIVE/,
  );
});

test("Playwright setup rejects a failed or malformed identity report", () => {
  assert.throws(
    () =>
      verifyBaselineIdentity({
        env: {
          KNOWLEDGE_V21141_ARCHIVE: "/runtime/tampered.tar.gz",
          KNOWLEDGE_V21141_CAPTURE_DIR: "/runtime/captures",
          KNOWLEDGE_V21141_EVIDENCE_DIR: tmpdir(),
        },
        run() {
          return { status: 1, stdout: "", stderr: "tar SHA-256 mismatch" };
        },
      }),
    /tar SHA-256 mismatch/,
  );
});

test("Playwright setup requires frozen PNGs before browser work", () => {
  assert.throws(
    () =>
      verifyBaselineIdentity({
        env: {
          KNOWLEDGE_V21141_ARCHIVE: "/runtime/frozen.tar.gz",
          KNOWLEDGE_V21141_EVIDENCE_DIR: tmpdir(),
        },
        run() {
          throw new Error("must not run");
        },
      }),
    /KNOWLEDGE_V21141_CAPTURE_DIR/,
  );
});
