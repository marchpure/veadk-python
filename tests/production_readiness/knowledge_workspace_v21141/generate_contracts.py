#!/usr/bin/env python3
"""Generate deterministic manifests from the verified frozen export."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from contract_harness import source_tree_fingerprint


TARGET = Path(__file__).resolve().parents[2] / "fixtures/knowledge_workspace_v21141"
EXPECTED = {
    "url": "https://cdn-tos-cn.bytedance.net/obj/tiktok-web-ai-cn/b5c172e6b1d79d5617ff49bfb11875507e25d33a5ee32af3ef90be4aa32ef773.tar.gz",
    "tar_sha256": "b5c172e6b1d79d5617ff49bfb11875507e25d33a5ee32af3ef90be4aa32ef773",
    "source_tree_sha256": "57e97670c6091219dcf1ac35d76dd174a45c9fa69841ce5b7887caef39b27c83",
    "captures_sha256": "83f05bb57e7039bbe715078dd0e818074b30de3f45e2a85349c21af090fe5199",
    "root_route_manifest_sha256": "339670643d53423e28850a0a6babff31a1042bdf6937897ac26ad35f8e4b5746",
    "complete_route_manifest_sha256": "51a972c437e0580384249cc183cc7ec70d3292f416b5a4986e12bc32e5b8c92b",
    "dependencies_sha256": "04a91782d6cd93dad26da3e529ac414ab29e6654063cf1655f5aebeae8e0c716",
}


def write(name: str, value: object) -> None:
    path = TARGET / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flatten_route(node: dict, parent: str | None = None) -> list[dict]:
    row = {
        "state_name": node["state_name"],
        "state_url": node["state_url"],
        "interaction": node.get("interaction", "root"),
        "parent_state_url": parent,
        "status": "frozen",
    }
    rows = [row]
    for child in node.get("children", []):
        rows.extend(flatten_route(child, node["state_url"]))
    return rows


def source_manifest(root: Path) -> None:
    tree_hash, files = source_tree_fingerprint(root / "prototype/codebase/src")
    assert tree_hash == EXPECTED["source_tree_sha256"]
    all_routes = ["root-manifest:*", "complete-manifest:*"]
    route_map = {
        "WelcomeView.tsx": ["/?file=welcome"],
        "AddDataView.tsx": ["/?file=add_data&step=*"],
        "UploadDocView.tsx": ["/?file=upload_doc"],
        "AddKnowledgeBaseView.tsx": ["/?file=add_kb"],
        "DashboardView.tsx": [
            "/?file=res_dash_east*",
            "/?file=res_dash_finance*",
            "/?file=res_dash_recruitment*",
        ],
        "EvaluationCenterView.tsx": ["/?file=evaluation_detail*"],
        "KnowledgeGraphView.tsx": ["/?file=kg_sales*"],
        "SemanticView.tsx": ["/?file=semantic_sales"],
        "KnowledgeBaseView.tsx": ["/?file=kb_sales*"],
        "ConnectionDetailView.tsx": ["/?file=res_sample_postgres"],
        "SkillArtifactView.tsx": ["/?file=res_api_1_1"],
        "ActionPolicyModal.tsx": ["*modal=action_policy*"],
        "AgentResourceSelectorModal.tsx": ["*modal=agent_selector*"],
        "AlertModal.tsx": ["*modal=alert*"],
        "CreateResourceModal.tsx": ["*modal=create_resource*"],
        "PublishAgentModal.tsx": ["*modal=publish_agent*"],
    }
    for row in files:
        row["status"] = "frozen"
        row["routes"] = route_map.get(
            Path(row["source_path"]).name,
            all_routes,
        )
    write(
        "source-files.json",
        {
            "schema_version": "knowledge-workspace.source-files.v1",
            "tree_hash_algorithm": (
                "sha256(sorted(relative_posix_path + NUL + raw_bytes + NUL))"
            ),
            "tree_sha256": tree_hash,
            "file_count": len(files),
            "lines_posix": sum(row["lines_posix"] for row in files),
            "bytes": sum(row["bytes"] for row in files),
            "files": files,
        },
    )


def route_manifest(root: Path) -> None:
    paths = {
        "root": root / "prototype/codebase/prototype-route.json",
        "complete": root / "prototype/codebase/src/prototype-route.json",
    }
    write(
        "route-manifests.json",
        {
            "schema_version": "knowledge-workspace.routes.v1",
            "manifests": {
                name: {
                    "source_path": path.relative_to(root).as_posix(),
                    "sha256": sha(path),
                    "nodes": flatten_route(json.loads(path.read_text())),
                }
                for name, path in paths.items()
            },
        },
    )


def capture_manifest(root: Path) -> None:
    path = root / "prototype/captures.json"
    captures = json.loads(path.read_text())["captures"]
    rows = []
    for index, capture in enumerate(captures, 1):
        png_hash = capture["tosUrl"].rsplit("/", 1)[-1].removesuffix(".png")
        rows.append(
            {
                "id": f"CAP-{index:02d}",
                "state_url": capture["stateUrl"],
                "tos_url": capture["tosUrl"],
                "png_sha256": png_hash,
                "viewport": [1920, 1080],
                "status": "frozen",
            }
        )
    write(
        "captures.json",
        {
            "schema_version": "knowledge-workspace.captures.v1",
            "source_path": "prototype/captures.json",
            "sha256": sha(path),
            "captures": rows,
        },
    )


def connector_manifest(root: Path) -> None:
    store = (root / "prototype/codebase/src/lib/store.ts").read_text()
    pattern = re.compile(
        r"\{ connectorKey: '([^']+)', category: '([^']+)', name: '([^']+)', "
        r"desc: '([^']+)', capabilities: \[.*?\], inputSchema: (.*?), "
        r"credentialSchema: (.*?), discoveryPipeline: \[(.*?)\], "
        r"syncModes: \[(.*?)\] \},"
    )
    required = {
        "postgresql",
        "mysql",
        "oracle",
        "csv",
        "excel",
        "json",
        "doc_txt",
        "web_discovery",
        "rest_api",
        "openapi_spec",
        "lark_doc",
        "lark_wiki",
        "lark_drive",
        "lark_sheet",
        "lark_base",
        "lark_minutes",
        "lark_meeting",
        "lark_group",
        "lark_chat",
    }
    required_certifications = [
        {"subject": connector_id, "connector_id": connector_id, "profile": "default"}
        for connector_id in sorted(required - {"doc_txt"})
    ] + [
        {"subject": f"doc_txt:{profile}", "connector_id": "doc_txt", "profile": profile}
        for profile in ["pdf", "markdown", "txt", "html"]
    ]
    connectors = []
    for match in pattern.finditer(store):
        connector_id, category, name, _, input_schema, credentials, pipeline, sync = (
            match.groups()
        )
        auth = (
            "none"
            if credentials == "null"
            else ("oauth" if "'oauth'" in credentials else "credential")
        )
        connectors.append(
            {
                "id": connector_id,
                "ui_name": name,
                "adapter": f"connector:{connector_id}",
                "auth": auth,
                "discovery": [item.strip(" '") for item in pipeline.split(",")],
                "preview": "required-safe-bounded-preview",
                "import": "required-durable-import-job",
                "incremental_sync": "incremental" in sync,
                "limits": {
                    "status": "contract-required",
                    "required_controls": ["payload", "rate", "pagination", "timeout"],
                },
                "tenant_isolation": "required-and-unverified",
                "last_verified": "never",
                "evidence": ["BLOCKED:no-real-system-auth-e2e-in-step-1"],
                "owner": "knowledge-workspace-connectors",
                "support_tier": "required-ga"
                if connector_id in required
                else "preview",
                "certification_status": "preview",
                "ga_gate": "blocked",
            }
        )
    assert len(connectors) == 37
    write(
        "connector-certification-matrix.json",
        {
            "schema_version": "knowledge-workspace.connector-certification.v1",
            "allowed_statuses": [
                "ga-certified",
                "available-unconfigured",
                "preview",
                "unsupported",
            ],
            "required_ga_connector_ids": sorted(required),
            "required_ga_certifications": required_certifications,
            "connectors": connectors,
            "ga_decision": {
                "status": "blocked",
                "reason": "No Connector has real-system Commercial GA E2E evidence in STEP 1.",
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.export_root.resolve()
    source_manifest(root)
    route_manifest(root)
    capture_manifest(root)
    connector_manifest(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
