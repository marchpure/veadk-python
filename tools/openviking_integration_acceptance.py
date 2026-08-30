#!/usr/bin/env python3
"""Credential-gated OpenViking integration acceptance runner.

This runner never substitutes a fake upstream. Without the four required
environment variables it writes a redacted BLOCKED_EXTERNAL report and exits
with code 2. With them, it drives the same-origin BFF and records only
redacted response metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/knowledge-workspace/evidence/openviking-integration-acceptance"
BFF = os.getenv("OPENVIKING_E2E_BFF_URL", "http://127.0.0.1:38111").rstrip("/")
REQUIRED = (
    "OPENVIKING_E2E_BASE_URL",
    "OPENVIKING_E2E_API_KEY",
    "OPENVIKING_PROFILE_ENCRYPTION_KEY",
    "OPENVIKING_REF_SIGNING_KEY",
)


def write(name: str, value: Any) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def redacted_endpoint(value: str) -> str:
    parsed = httpx.URL(value)
    return f"{parsed.scheme}://{parsed.host}{parsed.port and f':{parsed.port}' or ''}{parsed.path}".rstrip("/")


def main() -> int:
    missing = [name for name in REQUIRED if not os.getenv(name, "").strip()]
    if missing:
        write(
            "environment.json",
            {
                "status": "BLOCKED_EXTERNAL",
                "bff": BFF,
                "upstream": "UNSET",
                "missing": missing,
                "credentials": {name: "UNSET" for name in REQUIRED},
            },
        )
        write(
            "final-report.md",
            "# OpenViking integration acceptance\n\n"
            "Status: `OPENVIKING_INTEGRATION_ACCEPTANCE_BLOCKED`\n\n"
            f"Missing required external configuration: {', '.join(missing)}.\n"
            "No mock or fixture was used.\n",
        )
        return 2

    base_url = os.environ["OPENVIKING_E2E_BASE_URL"]
    tenant = f"ov-acceptance-{secrets.token_hex(6)}"
    workspace = f"workspace-{secrets.token_hex(6)}"
    headers = {
        "x-tenant-id": tenant,
        "x-workspace-id": workspace,
        "x-principal-id": "openviking-acceptance",
    }
    stamp = f"{int(time.time())}-{secrets.token_hex(4)}"
    events: list[dict[str, Any]] = []
    profile_id: str | None = None

    def record(event: str, status: str, **extra: Any) -> None:
        events.append({"event": event, "status": status, **extra})

    with httpx.Client(base_url=BFF, headers=headers, timeout=45, follow_redirects=False) as client:
        body = {
            "display_name": f"OpenViking acceptance {stamp}",
            "base_url": base_url,
            "api_key": os.environ["OPENVIKING_E2E_API_KEY"],
            "workspace_uri": "viking://resources/",
        }
        response = client.post("/api/knowledge/v1/openviking/profiles", json=body)
        response.raise_for_status()
        profile_id = response.json()["data"]["profile_id"]
        record("profile_created", "PASS", profile_id=profile_id)

        response = client.post(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}/validate"
        )
        if response.is_error:
            record("profile_validate", "FAIL", status_code=response.status_code)
            write("api-events.ndjson", "\n".join(json.dumps(item) for item in events) + "\n")
            return 1
        profile = response.json()["data"]
        parent_ref = profile["root_resource_ref"]
        record("profile_validate", "PASS", status=profile.get("status"))

        materials = {
            "TXT": (".txt", b""),
            "Markdown": (".md", b""),
            "PDF": (".pdf", b"%PDF-1.4\n"),
            "CSV": (".csv", b""),
            "JSON": (".json", b""),
            "XLSX": (".xlsx", b"PK\x03\x04"),
        }
        for kind, (suffix, prefix) in materials.items():
            canary = f"OV_ACCEPTANCE_{kind}_{stamp}_{secrets.token_hex(4)}"
            content = prefix + canary.encode()
            upload = client.post(
                f"/api/knowledge/v1/openviking/profiles/{profile_id}/upload",
                files={"file": (f"acceptance-{kind.lower()}{suffix}", content, "application/octet-stream")},
            )
            if upload.is_error:
                record("import", "FAIL", kind=kind, status_code=upload.status_code)
                continue
            task = client.post(
                f"/api/knowledge/v1/openviking/profiles/{profile_id}/operations/resource_import",
                json={"payload": {"temp_file_id": upload.json()["data"]["result"]["temp_file_id"], "parent_ref": parent_ref, "wait": True}},
            )
            record(
                "import",
                "PASS" if task.is_success else "FAIL",
                kind=kind,
                status_code=task.status_code,
                canary_sha256=hashlib.sha256(canary.encode()).hexdigest(),
            )

    write("api-events.ndjson", "\n".join(json.dumps(item, sort_keys=True) for item in events) + "\n")
    write("environment.json", {"status": "PASS", "bff": BFF, "upstream": redacted_endpoint(base_url)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
