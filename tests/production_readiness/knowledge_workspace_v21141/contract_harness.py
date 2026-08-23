#!/usr/bin/env python3
"""Fail-closed v2.11.4.1 frozen-export and evidence contract harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from contract_archive import (
    CONTRACT_ROOT,
    ContractError,
    assert_safe_tar,
    load_json,
    safe_extract,
    sha256_file,
    source_tree_fingerprint,
    validate_identity_contract,
    verify_archive,
    verify_capture_files,
    verify_contracts_against_export,
    verify_export_root,
)
from contract_inventory import (
    CONNECTOR_IDS,
    E2E_CASE_IDS,
    GA_GATE_IDS,
    REQUIRED_CERTIFICATION_SUBJECTS,
    STEP_1_PASS_GATES,
)

__all__ = [
    "CONTRACT_ROOT",
    "ContractError",
    "assert_safe_tar",
    "load_json",
    "safe_extract",
    "sha256_file",
    "source_tree_fingerprint",
    "validate_identity_contract",
    "validate_contracts",
    "verify_archive",
    "verify_capture_files",
    "verify_contracts_against_export",
    "verify_export_root",
]


def _require_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    missing = fields - value.keys()
    if missing:
        raise ContractError(f"{label} missing fields: {sorted(missing)}")
    empty = [field for field in fields if value[field] in (None, "", [], {})]
    if empty:
        raise ContractError(f"{label} has empty fields: {sorted(empty)}")


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in pointer.removeprefix("/").split("/"):
        if not token:
            continue
        key = token.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def validate_contracts(contract_root: Path = CONTRACT_ROOT) -> dict[str, Any]:
    identity = load_json(contract_root / "baseline-identity.json")
    sources = load_json(contract_root / "source-files.json")
    captures = load_json(contract_root / "captures.json")
    routes = load_json(contract_root / "route-manifests.json")
    golden = load_json(contract_root / "golden-master.json")
    visual = load_json(contract_root / "visual-contract.json")
    visual_evidence = load_json(contract_root / "visual-evidence.schema.json")
    trace_suite = load_json(contract_root / "trace-suite.json")
    connectors = load_json(contract_root / "connector-certification-matrix.json")
    readiness = load_json(contract_root / "commercial-readiness.json")
    journeys = load_json(contract_root / "e2e-skeleton.json")
    hotspots = load_json(contract_root / "hotspot-guard.json")
    production_config = load_json(contract_root / "production-config.schema.json")
    performance_evidence = load_json(contract_root / "performance-evidence.schema.json")
    topology = load_json(contract_root / "deployment-topology.json")
    transport = load_json(contract_root / "api-sse-contract.json")
    ga_gates = load_json(contract_root / "ga-gates.json")
    expected = identity["frozen_export"]
    validate_identity_contract(identity)

    if len(sources["files"]) != 47:
        raise ContractError("source manifest must freeze 47 files")
    source_fields = {
        "source_path",
        "target_path",
        "sha256",
        "lines_posix",
        "bytes",
        "routes",
        "status",
    }
    for source in sources["files"]:
        _require_fields(source, source_fields, source.get("source_path", "source row"))
        if (
            source["status"] != "frozen"
            or not source["target_path"].startswith(
                "frontend/src/knowledge-workspace/frozen-ui/"
            )
            or len(source["sha256"]) != 64
        ):
            raise ContractError(f"invalid source provenance: {source['source_path']}")
    if sources["tree_sha256"] != expected["source_tree_sha256"]:
        raise ContractError("source manifest tree hash differs from baseline identity")
    if sources["lines_posix"] != expected["source_lines_posix"]:
        raise ContractError("source manifest line count differs from baseline identity")
    if sources["bytes"] != expected["source_bytes"]:
        raise ContractError("source manifest byte count differs from baseline identity")
    if len(captures["captures"]) != 13:
        raise ContractError("capture manifest must freeze 13 states")
    if [item["id"] for item in captures["captures"]] != [
        f"CAP-{index:02d}" for index in range(1, 14)
    ]:
        raise ContractError("capture IDs must be CAP-01 through CAP-13")
    if any(
        item["status"] != "frozen"
        or item["viewport"] != [1920, 1080]
        or not item["state_url"]
        or not item["tos_url"]
        for item in captures["captures"]
    ):
        raise ContractError("capture rows must include frozen state, URL, and viewport")
    if captures["sha256"] != expected["captures_sha256"]:
        raise ContractError("capture manifest hash differs from baseline identity")
    if len({item["png_sha256"] for item in captures["captures"]}) != 12:
        raise ContractError("capture manifest must freeze 12 unique PNGs")
    if set(routes["manifests"]) != {"root", "complete"}:
        raise ContractError("both route manifests are required")
    if (
        len(routes["manifests"]["root"]["nodes"]) != 13
        or len(routes["manifests"]["complete"]["nodes"]) != 23
    ):
        raise ContractError("route manifests must freeze all 13 and 23 nodes")
    for name, manifest in routes["manifests"].items():
        state_urls = [node["state_url"] for node in manifest["nodes"]]
        if len(set(state_urls)) != len(state_urls):
            raise ContractError(f"{name} route manifest contains duplicate states")
        for node in manifest["nodes"]:
            _require_fields(
                node,
                {
                    "state_name",
                    "state_url",
                    "interaction",
                    "parent_state_url",
                    "status",
                }
                - ({"parent_state_url"} if node["parent_state_url"] is None else set()),
                f"{name} route node",
            )
            if node["status"] != "frozen":
                raise ContractError(f"{name} route node is not frozen")
    if (
        routes["manifests"]["root"]["sha256"] != expected["root_route_manifest_sha256"]
        or routes["manifests"]["complete"]["sha256"]
        != expected["complete_route_manifest_sha256"]
    ):
        raise ContractError("route manifest hash differs from baseline identity")
    if [item["id"] for item in golden["scenarios"]] != [
        f"GM-{index:02d}" for index in range(1, 21)
    ]:
        raise ContractError("GM-01 through GM-20 must be present in order")

    trace_fields = {
        "id",
        "route",
        "preconditions",
        "actions",
        "selectors",
        "assertions",
        "viewports",
        "evidence",
    }
    for scenario in golden["scenarios"]:
        _require_fields(scenario, trace_fields, scenario["id"])
        if scenario["drivers"] != ["reference", "candidate"]:
            raise ContractError(f"{scenario['id']} must share both drivers")

    if visual["thresholds"] != {
        "critical_anchor_px": 0,
        "other_boundary_px": 1,
        "pixel_mismatch_ratio": 0.001,
    }:
        raise ContractError("visual thresholds changed")
    required_gates = {
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
    }
    if set(visual["gates"]) != required_gates:
        raise ContractError("visual gate set is incomplete")
    if visual["mask_policy"]["business_component_masks_allowed"]:
        raise ContractError("business-component masks must be forbidden")
    if visual["mask_policy"]["allowed_reasons"] != ["font-antialiasing"]:
        raise ContractError("only font-antialiasing masks are permitted")
    if (
        not visual["evidence_output"]["identity_before_browser"]
        or len(visual["evidence_output"]["pair_artifacts"]) != 12
    ):
        raise ContractError("visual artifact comparator inputs are incomplete")
    if not visual_evidence["$id"].endswith("visual-evidence-v2.json"):
        raise ContractError("visual evidence schema must describe pair comparison")
    if set(visual_evidence["properties"]["snapshots"]["required"]) != {
        "dom",
        "class",
        "text",
        "event",
        "computedStyle",
    }:
        raise ContractError("visual evidence comparisons are incomplete")
    if visual_evidence["properties"]["evidence_hashes"].get("minItems") != 24:
        raise ContractError("visual evidence must hash all 24 pair artifacts")
    if trace_suite["drivers"] != ["reference", "candidate"]:
        raise ContractError("trace suite must drive reference and candidate equally")
    expected_trace_collections = {
        "frozen-source-files": ("source-files.json", 47),
        "frozen-captures": ("captures.json", 13),
        "root-route-nodes": ("route-manifests.json", 13),
        "complete-route-nodes": ("route-manifests.json", 23),
        "golden-masters": ("golden-master.json", 20),
    }
    trace_collections = {
        collection["id"]: collection for collection in trace_suite["collections"]
    }
    if set(trace_collections) != set(expected_trace_collections):
        raise ContractError("trace suite collections are incomplete")
    for collection_id, (manifest, count) in expected_trace_collections.items():
        collection = trace_collections[collection_id]
        if collection["manifest"] != manifest or collection["expected_count"] != count:
            raise ContractError(f"invalid trace collection: {collection_id}")
        rows = resolve_json_pointer(
            load_json(contract_root / manifest), collection["json_pointer"]
        )
        if len(rows) != count:
            raise ContractError(f"trace collection count mismatch: {collection_id}")
        keys = [row[collection["key"]] for row in rows]
        if len(keys) != len(set(keys)):
            raise ContractError(f"trace collection key is not unique: {collection_id}")
    if trace_suite["pair_artifacts"] != visual["evidence_output"]["pair_artifacts"]:
        raise ContractError("trace suite and visual artifact contract differ")

    connector_fields = {
        "id",
        "ui_name",
        "adapter",
        "auth",
        "discovery",
        "preview",
        "import",
        "incremental_sync",
        "limits",
        "tenant_isolation",
        "last_verified",
        "evidence",
        "owner",
        "support_tier",
        "certification_status",
        "ga_gate",
    }
    allowed_statuses = {
        "ga-certified",
        "available-unconfigured",
        "preview",
        "unsupported",
    }
    if set(connectors.get("allowed_statuses", [])) != allowed_statuses:
        raise ContractError("Connector Matrix status vocabulary changed")
    if len(connectors["connectors"]) != 37:
        raise ContractError("Connector Matrix must contain exactly 37 connectors")
    connector_ids = [connector["id"] for connector in connectors["connectors"]]
    if len(set(connector_ids)) != 37 or set(connector_ids) != CONNECTOR_IDS:
        raise ContractError("Connector Matrix differs from the frozen UI inventory")
    for connector in connectors["connectors"]:
        _require_fields(connector, connector_fields, connector["id"])
        if connector["certification_status"] not in allowed_statuses:
            raise ContractError(f"invalid connector status: {connector['id']}")
        if (
            connector["certification_status"] == "ga-certified"
            and connector["ga_gate"] != "pass"
        ):
            raise ContractError(f"invalid GA certification: {connector['id']}")
        if (
            connector["certification_status"] != "preview"
            or connector["ga_gate"] != "blocked"
            or connector["last_verified"] != "never"
            or any(
                not isinstance(item, str) or not item.startswith("BLOCKED:")
                for item in connector["evidence"]
            )
        ):
            raise ContractError(
                f"STEP 1 connector must remain preview and blocked: {connector['id']}"
            )
    present = {item["id"] for item in connectors["connectors"]}
    missing_required = set(connectors["required_ga_connector_ids"]) - present
    if missing_required:
        raise ContractError(f"missing required GA connectors: {missing_required}")
    certification_rows = connectors["required_ga_certifications"]
    required_subjects = {
        certification["subject"] for certification in certification_rows
    }
    if required_subjects != REQUIRED_CERTIFICATION_SUBJECTS:
        raise ContractError("required Connector certification subjects are incomplete")
    required_ids = set(connectors["required_ga_connector_ids"])
    if (
        len(certification_rows) != len(required_subjects)
        or len(required_ids) != len(connectors["required_ga_connector_ids"])
        or required_ids != {row["connector_id"] for row in certification_rows}
        or any(
            row["connector_id"] not in present
            or not row["profile"]
            or (
                row["subject"] != row["connector_id"]
                and row["subject"] != f"{row['connector_id']}:{row['profile']}"
            )
            for row in certification_rows
        )
    ):
        raise ContractError("required Connector certification rows are inconsistent")

    required_readiness = {
        "topology",
        "configuration",
        "migration",
        "health",
        "api_sse",
        "rbac_tenant",
        "secrets",
        "data_governance",
        "audit",
        "traffic_management",
        "sli_slo",
        "capacity",
        "disaster_recovery",
        "supply_chain",
        "release_rollback",
    }
    if set(readiness["contracts"]) != required_readiness:
        raise ContractError("commercial readiness contract set is incomplete")
    for contract_id, contract in readiness["contracts"].items():
        required = contract.get("required")
        gate = contract.get("gate")
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(item, str) or not item.strip() for item in required)
            or not isinstance(gate, str)
            or not gate.strip()
            or gate.strip().lower() in {"unknown", "todo", "tbd"}
        ):
            raise ContractError(
                f"commercial readiness contract is not actionable: {contract_id}"
            )
    metrics = readiness["minimum_ga_metrics"]
    expected_metrics = {
        "concurrent_interactive_users": 100,
        "concurrent_agent_turns": 20,
        "concurrent_import_jobs": 10,
        "read_api_p95_ms": 500,
        "mutation_accept_p95_ms": 1000,
        "sse_first_event_p95_ms": 2000,
        "monthly_availability": 0.999,
        "rpo_minutes": 15,
        "rto_minutes": 60,
    }
    if metrics != expected_metrics:
        raise ContractError("minimum GA metrics changed")
    for schema in (production_config, visual_evidence, performance_evidence):
        Draft202012Validator.check_schema(schema)
    performance_properties = performance_evidence["properties"]
    if (
        performance_properties["load"]["properties"]["concurrent_interactive_users"][
            "minimum"
        ]
        != metrics["concurrent_interactive_users"]
        or performance_properties["load"]["properties"]["concurrent_agent_turns"][
            "minimum"
        ]
        != metrics["concurrent_agent_turns"]
        or performance_properties["load"]["properties"]["concurrent_import_jobs"][
            "minimum"
        ]
        != metrics["concurrent_import_jobs"]
        or performance_properties["measurements"]["properties"]["read_api_p95_ms"][
            "maximum"
        ]
        != metrics["read_api_p95_ms"]
        or performance_properties["measurements"]["properties"][
            "mutation_accept_p95_ms"
        ]["maximum"]
        != metrics["mutation_accept_p95_ms"]
        or performance_properties["measurements"]["properties"][
            "sse_first_event_p95_ms"
        ]["maximum"]
        != metrics["sse_first_event_p95_ms"]
        or performance_properties["measurements"]["properties"]["monthly_availability"][
            "minimum"
        ]
        != metrics["monthly_availability"]
        or performance_properties["recovery"]["properties"]["rpo_minutes"]["maximum"]
        != metrics["rpo_minutes"]
        or performance_properties["recovery"]["properties"]["rto_minutes"]["maximum"]
        != metrics["rto_minutes"]
    ):
        raise ContractError("performance evidence schema differs from GA metrics")

    if any(case["status"] == "pass" for case in journeys["cases"]):
        raise ContractError("STEP 1 skeletons must not claim PASS")
    if journeys.get("policy", {}).get("allowed_statuses") != ["blocked"]:
        raise ContractError("STEP 1 E2E status policy must allow only blocked")
    if any(case.get("status") != "blocked" for case in journeys["cases"]):
        raise ContractError("STEP 1 E2E skeletons must remain blocked")
    for case in journeys["cases"]:
        evidence_prefix = f"{case.get('status', '').upper()}:"
        if (
            not case.get("requires")
            or not case.get("evidence")
            or any(
                not isinstance(item, str) or not item.startswith(evidence_prefix)
                for item in case["evidence"]
            )
        ):
            raise ContractError(
                "E2E skeleton status and evidence disagree or are incomplete: "
                f"{case.get('id', '<missing>')}"
            )
    expected_case_kinds = {
        "product-journey",
        "required-connector",
        "tenant-isolation",
        "restart-recovery",
        "worker-crash",
        "backup-restore",
        "secret-rotation",
        "upgrade-rollback",
        "fresh-install",
    }
    if {case["kind"] for case in journeys["cases"]} != expected_case_kinds:
        raise ContractError("E2E skeleton coverage is incomplete")
    case_ids = [case["id"] for case in journeys["cases"]]
    if len(case_ids) != len(E2E_CASE_IDS) or set(case_ids) != E2E_CASE_IDS:
        raise ContractError("E2E skeleton IDs are incomplete")
    connector_case = next(
        case for case in journeys["cases"] if case["kind"] == "required-connector"
    )
    if set(connector_case["connector_ids"]) != required_ids:
        raise ContractError("E2E skeleton omits required Connector IDs")
    required_certification_subjects = {
        certification["subject"]
        for certification in connectors["required_ga_certifications"]
    }
    if set(connector_case["certification_subjects"]) != required_certification_subjects:
        raise ContractError("E2E skeleton omits required Connector certification")
    if set(hotspots["shared_hotspots"]) != {
        "frontend/src/App.tsx",
        "frontend/server/knowledge_assets/service.py",
        "frontend/server/knowledge_assets/repository.py",
        "frontend/server/knowledge_assets/routes.py",
    }:
        raise ContractError("shared-hotspot guard is incomplete")
    if production_config.get("additionalProperties") is not False:
        raise ContractError("production config must reject unknown keys")
    required_config = {
        "profile",
        "version",
        "public_base_url",
        "database",
        "jobs",
        "object_storage",
        "secrets",
        "runner",
        "observability",
        "limits",
        "backup",
    }
    if set(production_config["required"]) != required_config:
        raise ContractError("production config schema is incomplete")
    expected_nodes = {
        "web-api",
        "worker",
        "scheduler",
        "database",
        "job-queue",
        "object-storage",
        "agentkit-runner",
        "provider",
        "secret-kms",
        "observability",
        "backup-restore",
    }
    if {node["id"] for node in topology["nodes"]} != expected_nodes:
        raise ContractError("deployment topology is incomplete")
    if topology["profile"] != "commercial":
        raise ContractError("deployment topology must use the commercial profile")
    required_edges = {tuple(edge) for edge in topology["required_edges"]}
    if len(required_edges) != 17 or any(
        source not in expected_nodes or target not in expected_nodes or source == target
        for source, target in required_edges
    ):
        raise ContractError("deployment topology edges are incomplete")
    if transport["sse"]["terminal_event_count"] != 1:
        raise ContractError("SSE must have exactly one terminal event")
    if transport["sse"]["browser_abort_changes_job_state"]:
        raise ContractError("browser abort must not mutate durable job state")
    if any(not gate["evidence"] for gate in ga_gates["gates"]):
        raise ContractError("GA gate evidence must never be empty")
    gate_ids = [gate["id"] for gate in ga_gates["gates"]]
    if len(gate_ids) != len(GA_GATE_IDS) or set(gate_ids) != GA_GATE_IDS:
        raise ContractError("Commercial contract must contain the exact GA gate set")
    if any(
        gate["status"] not in {"pass", "todo", "blocked"} for gate in ga_gates["gates"]
    ):
        raise ContractError("GA gate has invalid status")
    for gate in ga_gates["gates"]:
        if any(
            not isinstance(item, str) or not item.strip() for item in gate["evidence"]
        ):
            raise ContractError(f"GA gate evidence must never be empty: {gate['id']}")
        if gate["status"] != "pass" and (
            gate["status"] != "blocked"
            or not gate["evidence"][0].startswith("BLOCKED:")
        ):
            raise ContractError(f"GA gate status and evidence disagree: {gate['id']}")
    actual_pass_gates = {
        gate["id"] for gate in ga_gates["gates"] if gate["status"] == "pass"
    }
    if actual_pass_gates != STEP_1_PASS_GATES:
        raise ContractError("STEP 1 GA gate status set changed without evidence")
    if ga_gates["gates"][-1] != {
        "id": "commercial-ga",
        "status": "blocked",
        "evidence": [
            "BLOCKED:all non-pass gates above must pass in current "
            "production-equivalent environment"
        ],
    }:
        raise ContractError("Commercial GA must remain blocked in STEP 1")
    return {
        "sources": len(sources["files"]),
        "captures": len(captures["captures"]),
        "unique_pngs": len({item["png_sha256"] for item in captures["captures"]}),
        "route_nodes": sum(
            len(manifest["nodes"]) for manifest in routes["manifests"].values()
        ),
        "golden_masters": len(golden["scenarios"]),
        "connectors": len(connectors["connectors"]),
        "e2e_skeletons": len(journeys["cases"]),
        "ga_gates": len(ga_gates["gates"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-contracts")
    archive_parser = subparsers.add_parser("verify-archive")
    archive_parser.add_argument("--archive", type=Path, required=True)
    archive_parser.add_argument("--url", required=True)
    capture_parser = subparsers.add_parser("verify-captures")
    capture_parser.add_argument("--capture-dir", type=Path, required=True)
    args = parser.parse_args()
    identity = load_json(CONTRACT_ROOT / "baseline-identity.json")
    if args.command == "validate-contracts":
        result = validate_contracts()
    elif args.command == "verify-archive":
        result = verify_archive(args.archive, args.url, identity)
    else:
        result = verify_capture_files(args.capture_dir)
    print(json.dumps({"status": "pass", **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
