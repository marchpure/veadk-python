#!/usr/bin/env python3
"""Small dependency-free STEP 1 contract/document validator.

It checks JSON syntax, required OpenAPI surface/headers, event coverage, and
the checkpoint's required fields. It deliberately does not pretend to be a
full OpenAPI or JSON Schema implementation; CI can add a standards validator
later without changing the frozen documents.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "knowledge-workspace"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AssertionError(f"{path}: root must be object")
    return value


def main() -> int:
    openapi = (DOCS / "api-contracts" / "openapi.yaml").read_text(encoding="utf-8")
    events = load_json(DOCS / "events.schema.json")
    bootstrap = load_json(DOCS / "checkpoints" / "bootstrap.json")
    required_paths = [
        "/connector-definitions",
        "/connections",
        "/connections/{connection_id}/validate",
        "/connections/{connection_id}/discover",
        "/uploads",
        "/skills/drafts",
        "/skills/drafts/{draft_id}/generate",
        "/skills/drafts/{draft_id}/messages",
        "/skills/drafts/{draft_id}/conversation",
        "/invocations/{invocation_id}/events",
        "/invocations/{invocation_id}/cancel",
        "/skills/drafts/{draft_id}/revisions",
        "/skill-revisions/{revision_id}/run",
        "/artifacts/{artifact_id}",
        "/skill-revisions/{revision_id}/publish",
        "/publications/{publication_id}/invoke",
    ]
    for path in required_paths:
        assert f"  {path}:" in openapi, f"OpenAPI path missing: {path}"
    for header in ["Idempotency-Key", "If-Match", "ETag", "Last-Event-ID"]:
        assert header in openapi, (
            f"OpenAPI concurrency/reconnect contract missing: {header}"
        )

    event_types = [
        "run.started",
        "assistant.delta",
        "assistant.progress",
        "assistant.final",
        "turn.started",
        "activity.started",
        "activity.completed",
        "request.summary",
        "state.updated",
        "plan.updated",
        "tool.started",
        "tool.completed",
        "artifact.created",
        "revision.created",
        "run.completed",
        "run.failed",
        "run.cancelled",
    ]
    event_text = json.dumps(events)
    for event_type in event_types:
        assert event_type in event_text, f"event schema missing: {event_type}"

    for key in [
        "base_sha",
        "branch",
        "worktree",
        "prototype_sha256",
        "autoskill_ref",
        "openconnector_ref",
        "contract_files",
        "forbidden_paths",
        "worker_worktrees",
    ]:
        assert key in bootstrap, f"checkpoint field missing: {key}"
    assert re.fullmatch(r"[0-9a-f]{40}", bootstrap["base_sha"])
    assert re.fullmatch(r"[0-9a-f]{64}", bootstrap["prototype_sha256"])

    for filename in [
        "architecture.md",
        "migration-ledger.md",
        "acceptance-matrix.md",
        "api-contracts/openapi.yaml",
        "events.schema.json",
        "checkpoints/bootstrap.json",
    ]:
        assert (DOCS / filename).is_file(), f"contract file missing: {filename}"
    print("knowledge workspace contract validation: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, json.JSONDecodeError) as exc:
        print(f"knowledge workspace contract validation: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
