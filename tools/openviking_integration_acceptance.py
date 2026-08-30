#!/usr/bin/env python3
"""Run credential-gated, real OpenViking acceptance through the same-origin BFF."""

from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from openpyxl import Workbook
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/knowledge-workspace/evidence/openviking-integration-acceptance"
BFF = os.getenv("OPENVIKING_E2E_BFF_URL", "http://127.0.0.1:38111").rstrip("/")
POLL_SECONDS = float(os.getenv("OPENVIKING_E2E_POLL_SECONDS", "3"))
TASK_TIMEOUT = float(os.getenv("OPENVIKING_E2E_TASK_TIMEOUT", "600"))
SEARCH_TIMEOUT = float(os.getenv("OPENVIKING_E2E_SEARCH_TIMEOUT", "300"))
REQUIRED = (
    "OPENVIKING_E2E_BASE_URL",
    "OPENVIKING_E2E_API_KEY",
    "OPENVIKING_PROFILE_ENCRYPTION_KEY",
    "OPENVIKING_REF_SIGNING_KEY",
)
ALLOWED_STATUSES = {"PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_SUPPORTED"}


def write(name: str, value: Any) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    if name.endswith(".md"):
        path.write_text(str(value), encoding="utf-8")
    else:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def write_ndjson(name: str, values: list[dict[str, Any]]) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
            for value in values
        ),
        encoding="utf-8",
    )


def redacted_endpoint(value: str) -> str:
    parsed = httpx.URL(value)
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.host}{port}{parsed.path}".rstrip("/")


def valid_pdf(text: str) -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 720, text)
    document.save()
    return output.getvalue()


def valid_xlsx(text: str) -> bytes:
    output = io.BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "canary"
    sheet["B1"] = text
    workbook.save(output)
    return output.getvalue()


def public_shape(value: Any) -> Any:
    """Remove credentials, internal URIs, and oversized model-generated text."""
    if isinstance(value, dict):
        hidden = {"api_key", "authorization", "token", "secret", "password"}
        return {
            key: public_shape(item)
            for key, item in value.items()
            if key.casefold() not in hidden
        }
    if isinstance(value, list):
        return [public_shape(item) for item in value[:20]]
    if isinstance(value, str):
        if value.startswith("viking://"):
            return "viking://<redacted>"
        return value if len(value) <= 500 else value[:500] + "…"
    return value


def nested_result(response: httpx.Response) -> Any:
    try:
        value = response.json()
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    data = value.get("data")
    if not isinstance(data, dict):
        return None
    return data.get("result")


def response_summary(response: httpx.Response) -> dict[str, Any]:
    try:
        body = public_shape(response.json())
    except ValueError:
        body = {"non_json": True}
    return {"status_code": response.status_code, "response": body}


def main() -> int:
    missing = [name for name in REQUIRED if not os.getenv(name, "").strip()]
    if missing:
        blocked = {
            "status": "BLOCKED_EXTERNAL",
            "bff": BFF,
            "upstream": "UNSET",
            "missing": missing,
            "credentials": {name: "UNSET" for name in REQUIRED},
        }
        write("environment.json", blocked)
        write(
            "final-report.md",
            "# OpenViking integration acceptance\n\n"
            "Status: `OPENVIKING_INTEGRATION_ACCEPTANCE_BLOCKED`\n\n"
            f"- Passed: credential-independent repository checks only\n"
            f"- Failed: real profile/import/browser/security acceptance\n"
            f"- Unique blocker: missing {', '.join(missing)}\n"
            "- Repository-fixable: no\n"
            "- Reproduce: `python tools/openviking_integration_acceptance.py`\n"
            "- Minimum next step: provide the required environment variables and rerun\n"
            f"- Evidence: `{EVIDENCE}`\n",
        )
        return 2

    base_url = os.environ["OPENVIKING_E2E_BASE_URL"]
    stamp = f"{int(time.time())}-{secrets.token_hex(4)}"
    # Production Studio resolves browser identity server-side; these headers are
    # ignored there. They remain useful when the runner targets a test server.
    tenant = os.getenv("OPENVIKING_E2E_TENANT", "local")
    workspace = os.getenv("OPENVIKING_E2E_WORKSPACE", "studio")
    headers = {
        "x-tenant-id": tenant,
        "x-workspace-id": workspace,
        "x-principal-id": "openviking-acceptance",
    }
    events: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    search_results: list[dict[str, Any]] = []
    security: list[dict[str, Any]] = []
    profile_id: str | None = None
    parent_ref: str | None = None

    def record(event: str, status: str, **extra: Any) -> None:
        assert status in ALLOWED_STATUSES
        events.append({"event": event, "status": status, **public_shape(extra)})

    def operation(
        client: httpx.Client,
        name: str,
        payload: dict[str, Any],
        item_id: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        assert profile_id
        suffix = f"/{item_id}" if item_id else ""
        request_headers = {"idempotency-key": idempotency_key} if idempotency_key else None
        return client.post(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}/operations/{name}{suffix}",
            json={"payload": payload},
            headers=request_headers,
        )

    def wait_task(client: httpx.Client, task_id: str) -> tuple[bool, dict[str, Any]]:
        deadline = time.monotonic() + TASK_TIMEOUT
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = operation(client, "task_get", {}, task_id)
            value = nested_result(response)
            last = value if isinstance(value, dict) else {}
            if response.is_success and last.get("status") == "completed":
                return True, last
            if response.is_error or last.get("status") == "failed":
                return False, last
            time.sleep(POLL_SECONDS)
        return False, {**last, "timeout_seconds": TASK_TIMEOUT}

    def wait_search(
        client: httpx.Client,
        canary: str,
        expected_ref: str | None = None,
        excluded_ref: str | None = None,
        target_ref: str | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        deadline = time.monotonic() + SEARCH_TIMEOUT
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = operation(
                client,
                "find",
                {
                    "query": canary,
                    "target_ref": target_ref or parent_ref,
                    "limit": 20,
                },
            )
            try:
                last = response.json()
            except ValueError:
                last = {}
            serialized = json.dumps(last, ensure_ascii=False)
            result = nested_result(response)
            scoped_resources = (
                result.get("resources")
                if isinstance(result, dict)
                and isinstance(result.get("resources"), list)
                else []
            )
            found = response.is_success and (
                canary in serialized
                or (expected_ref is not None and expected_ref in serialized)
                or (target_ref is not None and bool(scoped_resources))
            )
            if excluded_ref is None and found:
                return True, last
            if excluded_ref is not None and not found and excluded_ref not in serialized:
                return True, last
            time.sleep(POLL_SECONDS)
        return False, last

    materials: dict[str, tuple[str, str, Callable[[str], bytes]]] = {
        "TXT": (".txt", "text/plain", lambda value: value.encode()),
        "Markdown": (".md", "text/markdown", lambda value: f"# Acceptance\n\n{value}\n".encode()),
        "PDF": (".pdf", "application/pdf", valid_pdf),
        "CSV": (".csv", "text/csv", lambda value: f"name,value\ncanary,{value}\n".encode()),
        "JSON": (".json", "application/json", lambda value: json.dumps({"canary": value}).encode()),
        "XLSX": (
            ".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            valid_xlsx,
        ),
    }

    with httpx.Client(
        base_url=BFF, headers=headers, timeout=60, follow_redirects=False
    ) as client:
        profile_body = {
            "display_name": f"OpenViking acceptance {stamp}",
            "base_url": base_url,
            "api_key": os.environ["OPENVIKING_E2E_API_KEY"],
            "workspace_uri": "viking://resources/",
        }
        response = client.post("/api/knowledge/v1/openviking/profiles", json=profile_body)
        if response.is_error:
            record("profile_create", "FAIL", **response_summary(response))
        else:
            profile = response.json()["data"]
            profile_id = profile["profile_id"]
            key_redacted = os.environ["OPENVIKING_E2E_API_KEY"] not in json.dumps(profile)
            record("profile_create", "PASS" if key_redacted else "FAIL", profile_id=profile_id)

        if profile_id:
            response = client.post(
                f"/api/knowledge/v1/openviking/profiles/{profile_id}/validate"
            )
            profile = response.json().get("data", {}) if response.is_success else {}
            parent_ref = profile.get("root_resource_ref")
            ready = response.is_success and profile.get("status") == "ready"
            record("profile_validate", "PASS" if ready else "FAIL", **response_summary(response))

        if not profile_id or not parent_ref:
            write_ndjson("api-events.ndjson", events)
            return 1

        def import_task(
            kind: str,
            canary: str,
            submit: Callable[[], httpx.Response],
            *,
            idempotency_key: str | None = None,
        ) -> dict[str, Any] | None:
            response = submit()
            result = nested_result(response)
            task_id = result.get("task_id") if isinstance(result, dict) else None
            root_ref = result.get("root_ref") if isinstance(result, dict) else None
            accepted = response.is_success and isinstance(task_id, str) and isinstance(root_ref, str)
            record(
                "import_submitted",
                "PASS" if accepted else "FAIL",
                kind=kind,
                task_id=task_id,
                root_ref=root_ref,
                canary_sha256=hashlib.sha256(canary.encode()).hexdigest(),
                **response_summary(response),
            )
            if not accepted:
                matrix.append({"type": kind, "status": "FAIL", "reason": "No real task_id/root_ref"})
                return None
            completed, task = wait_task(client, task_id)
            record(
                "import_task_terminal",
                "PASS" if completed else "FAIL",
                kind=kind,
                task_id=task_id,
                terminal_status=task.get("status"),
                task=task,
            )
            if not completed:
                matrix.append({"type": kind, "status": "FAIL", "reason": "Task did not complete"})
                return None
            return {
                "kind": kind,
                "canary": canary,
                "task_id": task_id,
                "root_ref": root_ref,
                "idempotency_key": idempotency_key,
            }

        manual_canary = f"OV_ACCEPTANCE_MANUAL_{stamp}_{secrets.token_hex(4)}"
        manual = import_task(
            "manual_text",
            manual_canary,
            lambda: client.post(
                f"/api/knowledge/v1/openviking/profiles/{profile_id}/text",
                json={
                    "parent_ref": parent_ref,
                    "filename": f"acceptance-manual-{stamp}.md",
                    "content": f"# Acceptance\n\n{manual_canary}\n",
                },
            ),
        )
        if manual:
            resources.append(manual)

        for kind, (suffix, media_type, builder) in materials.items():
            canary = f"OV_ACCEPTANCE_{kind.upper()}_{stamp}_{secrets.token_hex(4)}"
            filename = f"acceptance-{kind.lower()}-{stamp}{suffix}"
            upload = client.post(
                f"/api/knowledge/v1/openviking/profiles/{profile_id}/upload",
                files={"file": (filename, builder(canary), media_type)},
            )
            temp = nested_result(upload)
            temp_file_id = temp.get("temp_file_id") if isinstance(temp, dict) else None
            record(
                "temp_upload",
                "PASS" if upload.is_success and temp_file_id else "FAIL",
                kind=kind,
                **response_summary(upload),
            )
            if not temp_file_id:
                matrix.append({"type": kind, "status": "FAIL", "reason": "Temporary upload failed"})
                continue
            key = f"acceptance-{kind.lower()}-{stamp}"
            item = import_task(
                kind,
                canary,
                lambda temp_file_id=temp_file_id, key=key: operation(
                    client,
                    "resource_import",
                    {"temp_file_id": temp_file_id, "parent_ref": parent_ref, "wait": False},
                    idempotency_key=key,
                ),
                idempotency_key=key,
            )
            if item:
                item["import_payload"] = {
                    "temp_file_id": temp_file_id,
                    "parent_ref": parent_ref,
                    "wait": False,
                }
                resources.append(item)

        # A public data URL gives the URL importer a unique real canary without fixtures.
        url_canary = f"OV_ACCEPTANCE_URL_{stamp}_{secrets.token_hex(4)}"
        url_item = import_task(
            "URL_web",
            url_canary,
            lambda: operation(
                client,
                "resource_import",
                {
                    "path": f"https://httpbin.org/anything?canary={url_canary}",
                    "parent_ref": parent_ref,
                    "wait": False,
                },
                idempotency_key=f"acceptance-url-{stamp}",
            ),
        )
        if url_item:
            resources.append(url_item)

        # The same idempotency key and body must replay the original response.
        file_item = next((item for item in resources if item.get("idempotency_key")), None)
        if file_item:
            exact = operation(
                client,
                "resource_import",
                file_item["import_payload"],
                idempotency_key=file_item["idempotency_key"],
            )
            exact_result = nested_result(exact)
            replay_ok = (
                exact.is_success
                and isinstance(exact_result, dict)
                and exact_result.get("task_id") == file_item["task_id"]
                and exact_result.get("root_ref") == file_item["root_ref"]
            )
            record(
                "idempotency_exact_replay",
                "PASS" if replay_ok else "FAIL",
                task_id=exact_result.get("task_id") if isinstance(exact_result, dict) else None,
            )
            replay = operation(
                client,
                "resource_import",
                {
                    "temp_file_id": "intentionally-not-reused",
                    "parent_ref": parent_ref,
                    "wait": False,
                },
                idempotency_key=file_item["idempotency_key"],
            )
            # A key is body-bound: changing the body must not replay another resource.
            record(
                "idempotency_body_binding",
                "PASS" if replay.is_error else "FAIL",
                **response_summary(replay),
            )

        for item in resources:
            kind, canary, root_ref = item["kind"], item["canary"], item["root_ref"]
            stat = operation(client, "fs_stat", {"resource_ref": root_ref})
            tree = operation(client, "fs_tree", {"resource_ref": root_ref, "level_limit": 3})
            children = nested_result(tree)
            content_ref = root_ref
            if isinstance(children, list):
                leaf = next(
                    (
                        child
                        for child in children
                        if isinstance(child, dict) and isinstance(child.get("resource_ref"), str)
                    ),
                    None,
                )
                if leaf:
                    content_ref = leaf["resource_ref"]
            read = operation(client, "content_read", {"resource_ref": content_ref, "limit": 10000})
            read_found = canary in json.dumps(read.json(), ensure_ascii=False) if read.is_success else False
            searched, search_body = wait_search(
                client, canary, expected_ref=root_ref, target_ref=root_ref
            )
            checks = {
                "task_id": bool(item.get("task_id")),
                "terminal_success": True,
                "tree_visible": stat.is_success and tree.is_success,
                "content_readable": read.is_success and read_found,
                "search_hit": searched,
            }
            passed = all(checks.values())
            matrix.append(
                {
                    "type": kind,
                    "status": "PASS" if passed else "FAIL",
                    "checks": checks,
                    "task_id": item["task_id"],
                    "root_ref": root_ref,
                }
            )
            resources_entry = {
                "type": kind,
                "root_ref": root_ref,
                "content_ref": content_ref,
                "stat": response_summary(stat),
                "tree": response_summary(tree),
                "read": response_summary(read),
            }
            search_results.append(
                {
                    "type": kind,
                    "status": "PASS" if searched else "FAIL",
                    "canary_sha256": hashlib.sha256(canary.encode()).hexdigest(),
                    "response": public_shape(search_body),
                }
            )
            item["evidence"] = resources_entry

        tasks = operation(client, "tasks", {"limit": 200})
        task_ids = {
            task.get("task_id")
            for task in (nested_result(tasks) or [])
            if isinstance(task, dict)
        }
        expected_ids = {item["task_id"] for item in resources}
        history_ok = tasks.is_success and expected_ids.issubset(task_ids)
        record("task_history", "PASS" if history_ok else "FAIL", expected=len(expected_ids))

        listed = client.get("/api/knowledge/v1/openviking/profiles")
        persisted = listed.is_success and profile_id in json.dumps(listed.json())
        record("profile_refresh_recovery", "PASS" if persisted else "FAIL")

        # Validation and edge failures must be explicit and understandable.
        edge_cases = [
            (
                "empty_text",
                lambda: client.post(
                    f"/api/knowledge/v1/openviking/profiles/{profile_id}/text",
                    json={"parent_ref": parent_ref, "filename": "empty.md", "content": " "},
                ),
            ),
            (
                "zero_byte_file",
                lambda: client.post(
                    f"/api/knowledge/v1/openviking/profiles/{profile_id}/upload",
                    files={"file": ("empty.txt", b"", "text/plain")},
                ),
            ),
            (
                "unsupported_extension",
                lambda: client.post(
                    f"/api/knowledge/v1/openviking/profiles/{profile_id}/upload",
                    files={"file": ("unsupported.docx", b"not-a-docx", "application/octet-stream")},
                ),
            ),
            (
                "localhost_import",
                lambda: operation(
                    client,
                    "resource_import",
                    {"path": "https://127.0.0.1/private", "parent_ref": parent_ref, "wait": False},
                ),
            ),
            (
                "private_ip_import",
                lambda: operation(
                    client,
                    "resource_import",
                    {"path": "https://10.0.0.1/private", "parent_ref": parent_ref, "wait": False},
                ),
            ),
            (
                "invalid_resource_ref",
                lambda: operation(client, "fs_stat", {"resource_ref": "ovr_invalid.signature"}),
            ),
        ]
        for check, invoke in edge_cases:
            response = invoke()
            status = "PASS" if response.status_code in {400, 403, 404, 413, 415, 422} else "FAIL"
            security.append({"check": check, "status": status, **response_summary(response)})

        for check, filename, content, media_type in (
            ("corrupt_pdf", "corrupt.pdf", b"not-a-pdf", "application/pdf"),
            (
                "corrupt_xlsx",
                "corrupt.xlsx",
                b"not-an-xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            ("invalid_json", "invalid.json", b"{", "application/json"),
        ):
            upload = client.post(
                f"/api/knowledge/v1/openviking/profiles/{profile_id}/upload",
                files={"file": (filename, content, media_type)},
            )
            uploaded = nested_result(upload)
            temp_file_id = (
                uploaded.get("temp_file_id") if isinstance(uploaded, dict) else None
            )
            submitted = (
                operation(
                    client,
                    "resource_import",
                    {
                        "temp_file_id": temp_file_id,
                        "parent_ref": parent_ref,
                        "wait": False,
                    },
                )
                if temp_file_id
                else upload
            )
            submitted_result = nested_result(submitted)
            task_id = (
                submitted_result.get("task_id")
                if isinstance(submitted_result, dict)
                else None
            )
            terminal_failed = False
            terminal: dict[str, Any] = {}
            if isinstance(task_id, str):
                completed, terminal = wait_task(client, task_id)
                terminal_failed = not completed and terminal.get("status") == "failed"
            rejected = submitted.is_error or terminal_failed
            security.append(
                {
                    "check": check,
                    "status": "PASS" if rejected else "FAIL",
                    "submit_status": submitted.status_code,
                    "task_status": terminal.get("status"),
                }
            )

        wrong = client.post(
            "/api/knowledge/v1/openviking/profiles",
            json={**profile_body, "display_name": "wrong-key", "api_key": "definitely-wrong"},
        )
        wrong_id = wrong.json().get("data", {}).get("profile_id") if wrong.is_success else None
        wrong_validate = (
            client.post(f"/api/knowledge/v1/openviking/profiles/{wrong_id}/validate")
            if wrong_id
            else wrong
        )
        security.append(
            {
                "check": "wrong_api_key",
                "status": "PASS" if 400 <= wrong_validate.status_code < 500 else "FAIL",
                **response_summary(wrong_validate),
            }
        )
        if wrong_id:
            client.delete(f"/api/knowledge/v1/openviking/profiles/{wrong_id}")

        # Deletion is last so tree/read/search evidence exists before cleanup.
        for item in resources:
            deleted = operation(
                client,
                "fs_delete",
                {"resource_ref": item["root_ref"], "recursive": True, "wait": True, "timeout": 180},
            )
            stat = operation(client, "fs_stat", {"resource_ref": item["root_ref"]})
            absent, _ = wait_search(
                client, item["canary"], excluded_ref=item["root_ref"]
            )
            delete_ok = deleted.is_success and stat.status_code == 404 and absent
            item["deleted"] = delete_ok
            record(
                "resource_delete",
                "PASS" if delete_ok else "FAIL",
                kind=item["kind"],
                delete_status=deleted.status_code,
                read_after_delete_status=stat.status_code,
                search_absent=absent,
            )
            for row in matrix:
                if row["type"] == item["kind"]:
                    row.setdefault("checks", {})["delete_effect"] = delete_ok
                    if not delete_ok:
                        row["status"] = "FAIL"

    unsupported = [
        ("DOC/DOCX", "当前适配层未实现"),
        ("PPT/PPTX", "当前适配层未实现"),
        ("HTML local upload", "当前适配层未实现"),
        ("images/audio/video local upload", "当前适配层未实现"),
        ("archives/directories/batch upload", "当前适配层未实现"),
        ("Git remote import", "需要外部转换器"),
        ("Feishu/Lark remote import", "需要外部转换器"),
        ("TOS remote import", "UI 未暴露可独立验收的外部凭据"),
    ]
    matrix.extend(
        {"type": kind, "status": "NOT_SUPPORTED", "reason": reason}
        for kind, reason in unsupported
    )
    mandatory_failures = [
        event for event in events if event["status"] == "FAIL"
    ] + [row for row in matrix if row["status"] == "FAIL"] + [
        row for row in security if row["status"] == "FAIL"
    ]
    overall = "FAIL" if mandatory_failures else "PASS"
    write_ndjson("api-events.ndjson", events)
    write(
        "environment.json",
        {
            "status": overall,
            "bff": BFF,
            "upstream": redacted_endpoint(base_url),
            "tenant": tenant,
            "workspace": workspace,
            "profile_id": profile_id,
            "credentials": "configured and redacted",
        },
    )
    write("import-matrix.json", {"status": overall, "imports": matrix})
    write(
        "resource-tree.json",
        {
            "status": "PASS" if resources and all("evidence" in item for item in resources) else "FAIL",
            "profile_id": profile_id,
            "resources": [public_shape(item.get("evidence", {})) for item in resources],
        },
    )
    write(
        "search-results.json",
        {
            "status": "PASS" if search_results and all(row["status"] == "PASS" for row in search_results) else "FAIL",
            "queries": search_results,
        },
    )
    write(
        "security-matrix.json",
        {
            "status": "PASS" if security and all(row["status"] == "PASS" for row in security) else "FAIL",
            "checks": security,
        },
    )
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
