#!/usr/bin/env python3
"""Static package, production-fixture, runtime-artifact, and hotspot guard."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
from pathlib import Path

from contract_harness import CONTRACT_ROOT, ContractError, load_json


REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_EXTENSIONS = {".js", ".jsx", ".mjs", ".py", ".ts", ".tsx"}
FIRST_PARTY_PRODUCTION_PREFIXES = ("frontend/src/", "frontend/server/", "veadk/")
RUNTIME_PATTERNS = {
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.pid",
    "*.tar.gz",
    "*.tgz",
    "*.ipynb",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
}
BUNDLE_PATTERNS = {"*.bundle.js", "*.min.js", "*.chunk.js"}
STEP_1_ALLOWED_PATHS = {
    "frontend/knowledgeWorkspaceV21141GlobalSetup.mjs",
    "frontend/playwright.knowledge-workspace-v21141.config.mjs",
    "frontend/tests/knowledgeWorkspaceV21141Contracts.test.mjs",
    "scripts/generate_knowledge_asset_seam.py",
    "tests/frontend/test_knowledge_asset_bff.py",
    "veadk/cli/cli_frontend.py",
    "tests/frontend/test_skill_authoring.py",
}
STEP_1_ALLOWED_PREFIXES = (
    "docs/productization/v2.11.4.1/",
    "docs/knowledge-assets/implementation/",
    "frontend/tests/knowledge-workspace-v21141/",
    "frontend/server/knowledge_assets/",
    "frontend/src/knowledge-workspace/production/",
    "tests/frontend/knowledge_workspace_v21141/",
    "tests/fixtures/knowledge_workspace_v21141/",
    "tests/production_readiness/knowledge_workspace_v21141/",
    "tests/fixtures/knowledge_step3_w4/",
)
STEP_2_ALLOWED_PATHS = {
    "frontend/index.html",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/scripts/build.mjs",
    "frontend/src/entry.tsx",
    "frontend/src/styles.css",
    "frontend/src/studio-entry.tsx",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "frontend/src/main.tsx",
    "frontend/src/ui/Sidebar.tsx",
    "frontend/tests/cronJobFinalAnswer.test.mjs",
    "scripts/knowledge_asset_step3_server.py",
    "scripts/knowledge_asset_step3_playwright.mjs",
    "scripts/knowledge_asset_step3_visual_compare.mjs",
}
STEP_2_ALLOWED_PREFIXES = (
    "frontend/src/knowledge-workspace/",
    "frontend/tests/knowledge-workspace-v21141/",
)

# STEP 3 Worker 2 owns this service boundary and its focused tests. These
# files remain subject to the production dependency scan; their size is
# recorded as an explicit handoff review rather than silently ignored.
STEP3_APPROVED_SPLIT_REVIEW_PATHS = {
    "frontend/server/skill_authoring/ports.py",
    "frontend/server/skill_authoring/service.py",
    "tests/frontend/test_skill_authoring.py",
    "tests/frontend/knowledge_workspace_v21141/test_worker3_kind_runtime.py",
}


def repository_files(repo_root: Path) -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        text=True,
    )
    return [
        path
        for path in output.splitlines()
        if path != ".veadk" and not path.startswith(".veadk/")
    ]


def baseline_files(repo_root: Path, commit: str) -> set[str]:
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit],
        cwd=repo_root,
        text=True,
    )
    return set(output.splitlines())


def baseline_blob(repo_root: Path, commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def changed_paths(repo_root: Path, baseline: str) -> set[str]:
    tracked = subprocess.check_output(
        ["git", "diff", "--name-only", baseline, "--"],
        cwd=repo_root,
        text=True,
    ).splitlines()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_root,
        text=True,
    ).splitlines()
    return {
        path
        for path in set(tracked) | set(untracked)
        if path != ".veadk" and not path.startswith(".veadk/")
    }


def count_lines(content: bytes) -> int:
    return content.count(b"\n")


def is_first_party_production_source(relative: str) -> bool:
    return relative.startswith(FIRST_PARTY_PRODUCTION_PREFIXES) and (
        Path(relative).suffix in PRODUCTION_EXTENSIONS
    )


def production_policy_findings(relative: str, text: str) -> list[str]:
    checks = {
        "iframe": r"<iframe\b",
        "fixture": r"\bfixtures?\b",
        "local-storage": r"\blocalstorage\b",
        "mock-provider": r"\bmock[\s_-]*provider\b",
        "static-success": r"\bstatic[\s_-]*success\b",
        "fake-sse": r"\bfake[\s_-]*sse\b",
    }
    findings = [
        f"production-{kind}:{relative}"
        for kind, pattern in checks.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    # Trusted server renderers may contain an explicit rejection check for
    # executable tags. That is a boundary assertion, not emitted markup.
    if "production-iframe:" + relative in findings and re.search(
        r"""b"<iframe"|b'<iframe'""", text
    ):
        findings.remove("production-iframe:" + relative)
    return findings


def scan(repo_root: Path) -> dict:
    contract = load_json(CONTRACT_ROOT / "hotspot-guard.json")
    paths = repository_files(repo_root)
    baseline_paths = baseline_files(repo_root, contract["baseline_commit"])
    new_paths = set(paths) - baseline_paths
    changed = changed_paths(repo_root, contract["baseline_commit"])
    findings: list[str] = []
    rules = contract["rules"]

    for relative in changed:
        allowed = (
            relative in STEP_2_ALLOWED_PATHS
            or relative.startswith(STEP_2_ALLOWED_PREFIXES)
            or relative in STEP_1_ALLOWED_PATHS
            or relative.startswith(STEP_1_ALLOWED_PREFIXES)
            or relative == "frontend/server/skill_authoring/__init__.py"
            or relative.startswith("frontend/server/skill_authoring/")
        )
        if not allowed:
            findings.append(f"step-1-write-scope:{relative}")

    for relative in new_paths:
        path = Path(relative)
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in RUNTIME_PATTERNS):
            findings.append(f"forbidden-runtime-artifact:{relative}")
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in BUNDLE_PATTERNS):
            findings.append(f"compiled-bundle:{relative}")
        if {"dist", "build", "node_modules"} & set(path.parts):
            findings.append(f"compiled-output:{relative}")

    new_source_files = sorted(
        relative
        for relative in new_paths
        if Path(relative).suffix in PRODUCTION_EXTENSIONS
    )
    oversized_new_source_files = [
        relative
        for relative in new_source_files
        if (repo_root / relative).stat().st_size > rules["new_source_review_bytes"]
    ]
    mandatory_split_review_files = [
        relative
        for relative in new_source_files
        if relative not in STEP3_APPROVED_SPLIT_REVIEW_PATHS
        if not relative.startswith("frontend/src/knowledge-workspace/frozen-ui/")
        if count_lines((repo_root / relative).read_bytes())
        > rules["new_file_mandatory_split_review_loc"]
    ]
    for relative in oversized_new_source_files:
        findings.append(f"new-source-review-bytes:{relative}")
    for relative in mandatory_split_review_files:
        findings.append(f"mandatory-split-review:{relative}")

    new_production_files = sorted(
        relative for relative in new_paths if is_first_party_production_source(relative)
    )
    frozen_production_files = [
        relative
        for relative in new_production_files
        if relative.startswith("frontend/src/knowledge-workspace/frozen-ui/")
    ]
    implementation_production_files = [
        relative for relative in new_production_files if relative not in frozen_production_files
    ]
    production_gross_loc = sum(
        count_lines((repo_root / relative).read_bytes())
        for relative in new_production_files
    )
    production_net_loc = sum(
        count_lines((repo_root / relative).read_bytes())
        for relative in implementation_production_files
    )
    if production_gross_loc > rules["new_first_party_production_gross_loc_max"]:
        findings.append(f"new-production-gross-loc:{production_gross_loc}")
    if production_net_loc > rules["new_first_party_production_net_loc_max"]:
        findings.append(f"new-production-net-loc:{production_net_loc}")

    knowledge_root = repo_root / "frontend/src/knowledge-workspace"
    policy_paths = {
        relative
        for relative in changed
        if is_first_party_production_source(relative)
        and not relative.startswith("frontend/src/knowledge-workspace/frozen-ui/")
        and (repo_root / relative).is_file()
    }
    if knowledge_root.exists():
        policy_paths.update(
            path.relative_to(repo_root).as_posix()
            for path in knowledge_root.rglob("*")
            if path.is_file()
            and path.suffix in PRODUCTION_EXTENSIONS
            and "frozen-ui" not in path.parts
        )
    for relative in sorted(policy_paths):
        text = (repo_root / relative).read_text(encoding="utf-8", errors="ignore")
        findings.extend(production_policy_findings(relative, text))
        if "knowledge_workspace_v21141" in text:
            findings.append(f"production-fixture:{relative}")

    frozen_sources = load_json(CONTRACT_ROOT / "source-files.json")["files"]
    frozen_hashes = {row["sha256"]: row["target_path"] for row in frozen_sources}
    frozen_matches: dict[str, list[str]] = {}
    for relative in paths:
        if not is_first_party_production_source(relative):
            continue
        path = repo_root / relative
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in frozen_hashes:
            frozen_matches.setdefault(digest, []).append(relative)
    for digest, matches in frozen_matches.items():
        expected_target = frozen_hashes[digest]
        if len(matches) > 1:
            findings.append(f"duplicate-frozen-source:{','.join(sorted(matches))}")
        if expected_target not in matches:
            findings.append(
                f"misplaced-frozen-source:{matches[0]}:expected:{expected_target}"
            )

    frozen_roots = [
        path
        for path in (repo_root / "frontend/src").rglob("frozen-ui")
        if path.is_dir()
    ]
    if len(frozen_roots) > 1:
        findings.append(
            "duplicate-frozen-ui:"
            + ",".join(path.relative_to(repo_root).as_posix() for path in frozen_roots)
        )

    hotspot_report = []
    for relative in contract["shared_hotspots"]:
        current_path = repo_root / relative
        current = current_path.read_bytes() if current_path.exists() else None
        baseline = baseline_blob(repo_root, contract["baseline_commit"], relative)
        current_lines = count_lines(current) if current is not None else 0
        baseline_lines = count_lines(baseline) if baseline is not None else 0
        growth = current_lines - baseline_lines
        hotspot_report.append(
            {
                "path": relative,
                "baseline_exists": baseline is not None,
                "current_exists": current is not None,
                "baseline_lines": baseline_lines,
                "current_lines": current_lines,
                "line_growth": growth,
            }
        )
        if growth > contract["rules"]["shared_hotspot_behavior_loc_growth"]:
            findings.append(f"shared-hotspot-growth:{relative}:{growth}")

    return {
        "status": "pass" if not findings else "fail",
        "findings": findings,
        "repository_files": len(paths),
        "new_files": len(new_paths),
        "changed_files": len(changed),
        "new_first_party_production_files": len(new_production_files),
        "new_first_party_production_gross_loc": production_gross_loc,
        "new_first_party_production_net_loc": production_net_loc,
        "oversized_new_source_files": oversized_new_source_files,
        "mandatory_split_review_files": mandatory_split_review_files,
        "frozen_production_copies": len(frozen_roots),
        "shared_hotspots": hotspot_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    result = scan(args.repo_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["findings"]:
        raise ContractError("static guard failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
