from __future__ import annotations

import copy
import io
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from contract_harness import (
    CONTRACT_ROOT,
    ContractError,
    assert_safe_tar,
    load_json,
    source_tree_fingerprint,
    validate_contracts,
    validate_identity_contract,
    verify_archive,
    verify_capture_files,
    verify_contracts_against_export,
    verify_export_root,
)


FROZEN_URL = (
    "https://cdn-tos-cn.bytedance.net/obj/tiktok-web-ai-cn/"
    "b5c172e6b1d79d5617ff49bfb11875507e25d33a5ee32af3ef90be4aa32ef773.tar.gz"
)


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("url", "https://example.invalid/tampered.tar.gz"),
        ("tar_sha256", "0" * 64),
        ("source_tree_sha256", "0" * 64),
        ("captures_sha256", "0" * 64),
        ("root_route_manifest_sha256", "0" * 64),
        ("complete_route_manifest_sha256", "0" * 64),
        ("dependencies_sha256", "0" * 64),
    ],
)
def test_frozen_identity_fields_are_independently_pinned(
    field: str,
    tampered: str,
) -> None:
    identity = load_json(CONTRACT_ROOT / "baseline-identity.json")
    identity["frozen_export"][field] = tampered
    with pytest.raises(ContractError, match="frozen baseline identity changed"):
        validate_identity_contract(identity)


def test_all_machine_contracts_are_complete() -> None:
    result = validate_contracts()
    assert result["sources"] == 47
    assert result["captures"] == 13
    assert result["unique_pngs"] == 12
    assert result["golden_masters"] == 20
    assert result["connectors"] == 37


def test_step_1_connector_claims_and_ga_gate_ids_fail_closed(
    tmp_path: Path,
) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    connector_path = copied_contracts / "connector-certification-matrix.json"
    connector_matrix = load_json(connector_path)
    connector_matrix["connectors"][0]["certification_status"] = "ga-certified"
    connector_matrix["connectors"][0]["ga_gate"] = "pass"
    connector_path.write_text(json.dumps(connector_matrix), encoding="utf-8")
    with pytest.raises(ContractError, match="STEP 1 connector"):
        validate_contracts(copied_contracts)

    shutil.rmtree(copied_contracts)
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    gates_path = copied_contracts / "ga-gates.json"
    gates = load_json(gates_path)
    gates["gates"][1]["id"] = gates["gates"][0]["id"]
    gates_path.write_text(json.dumps(gates), encoding="utf-8")
    with pytest.raises(ContractError, match="exact GA gate set"):
        validate_contracts(copied_contracts)


def test_connector_inventory_cannot_duplicate_or_swap_ui_entries(
    tmp_path: Path,
) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    connector_path = copied_contracts / "connector-certification-matrix.json"
    connector_matrix = load_json(connector_path)
    connector_matrix["connectors"][-1]["id"] = connector_matrix["connectors"][0]["id"]
    connector_path.write_text(json.dumps(connector_matrix), encoding="utf-8")
    with pytest.raises(ContractError, match="frozen UI inventory"):
        validate_contracts(copied_contracts)


def test_required_connector_certifications_include_openapi_spec(
    tmp_path: Path,
) -> None:
    committed = load_json(CONTRACT_ROOT / "connector-certification-matrix.json")
    assert "openapi_spec" in committed["required_ga_connector_ids"]
    assert "openapi_spec" in {
        item["subject"] for item in committed["required_ga_certifications"]
    }

    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    connector_path = copied_contracts / "connector-certification-matrix.json"
    connector_matrix = load_json(connector_path)
    connector_matrix["required_ga_certifications"] = [
        certification
        for certification in connector_matrix["required_ga_certifications"]
        if certification["subject"] != "openapi_spec"
    ]
    connector_matrix["required_ga_connector_ids"].remove("openapi_spec")
    connector_path.write_text(json.dumps(connector_matrix), encoding="utf-8")
    with pytest.raises(ContractError, match="required Connector certification"):
        validate_contracts(copied_contracts)


def test_required_connector_certification_rows_are_unique_and_consistent(
    tmp_path: Path,
) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    connector_path = copied_contracts / "connector-certification-matrix.json"
    connector_matrix = load_json(connector_path)
    connector_matrix["required_ga_certifications"].append(
        copy.deepcopy(connector_matrix["required_ga_certifications"][0])
    )
    connector_path.write_text(json.dumps(connector_matrix), encoding="utf-8")
    with pytest.raises(ContractError, match="certification rows"):
        validate_contracts(copied_contracts)


def test_connector_blocked_evidence_cannot_be_empty_or_unmarked(
    tmp_path: Path,
) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    connector_path = copied_contracts / "connector-certification-matrix.json"
    connector_matrix = load_json(connector_path)
    connector_matrix["connectors"][0]["evidence"] = [""]
    connector_path.write_text(json.dumps(connector_matrix), encoding="utf-8")
    with pytest.raises(ContractError, match="preview and blocked"):
        validate_contracts(copied_contracts)


def test_visual_evidence_contract_cannot_drop_a_computed_layer() -> None:
    contract = load_json(CONTRACT_ROOT / "visual-contract.json")
    schema = load_json(CONTRACT_ROOT / "visual-evidence.schema.json")
    assert contract["evidence_output"]["identity_before_browser"] is True
    assert len(contract["evidence_output"]["pair_artifacts"]) == 12
    assert contract["mask_policy"]["allowed_reasons"] == ["font-antialiasing"]
    assert schema["properties"]["screenshotDimensionsEqual"] == {"const": True}
    assert schema["properties"]["masks"]["items"]["properties"]["reason"] == {
        "enum": ["font-antialiasing"]
    }
    assert schema["properties"]["evidence_hashes"] == {
        "type": "array",
        "minItems": 24,
        "maxItems": 24,
        "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }


def test_trace_suite_iterates_every_frozen_contract_with_both_drivers() -> None:
    trace_suite = load_json(CONTRACT_ROOT / "trace-suite.json")
    assert trace_suite["drivers"] == ["reference", "candidate"]
    collections = {
        item["id"]: item["expected_count"] for item in trace_suite["collections"]
    }
    assert collections == {
        "frozen-source-files": 47,
        "frozen-captures": 13,
        "root-route-nodes": 13,
        "complete-route-nodes": 23,
        "golden-masters": 20,
    }
    assert len(trace_suite["pair_artifacts"]) == 12
    assert trace_suite["output_location"] == "runtime-only"


def test_committed_manifests_exactly_match_frozen_export(tmp_path: Path) -> None:
    export_root = Path(
        os.environ.get(
            "KNOWLEDGE_V21141_EXPORT_ROOT",
            "/tmp/knowledge-v21141-step1.Ljw9m9/extracted",
        )
    )
    if not export_root.exists():
        pytest.skip("verified export root is supplied by the acceptance command")
    result = verify_contracts_against_export(export_root)
    assert result == {
        "source_manifest_rows": 47,
        "capture_manifest_rows": 13,
        "root_route_nodes": 13,
        "complete_route_nodes": 23,
    }

    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    source_manifest = load_json(copied_contracts / "source-files.json")
    source_manifest["files"][0]["sha256"] = "0" * 64
    (copied_contracts / "source-files.json").write_text(
        json.dumps(source_manifest), encoding="utf-8"
    )
    with pytest.raises(ContractError, match="source manifest differs"):
        verify_contracts_against_export(export_root, copied_contracts)

    shutil.rmtree(copied_contracts)
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    capture_manifest = load_json(copied_contracts / "captures.json")
    capture_manifest["captures"][0]["state_url"] += "&tampered=true"
    (copied_contracts / "captures.json").write_text(
        json.dumps(capture_manifest), encoding="utf-8"
    )
    with pytest.raises(ContractError, match="capture manifest differs"):
        verify_contracts_against_export(export_root, copied_contracts)

    shutil.rmtree(copied_contracts)
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    route_manifest = load_json(copied_contracts / "route-manifests.json")
    route_manifest["manifests"]["root"]["nodes"][0]["state_name"] = "tampered"
    (copied_contracts / "route-manifests.json").write_text(
        json.dumps(route_manifest), encoding="utf-8"
    )
    with pytest.raises(ContractError, match="root route manifest differs"):
        verify_contracts_against_export(export_root, copied_contracts)


def test_capture_png_tampering_fails_before_browser_work(tmp_path: Path) -> None:
    capture_dir = Path(
        os.environ.get(
            "KNOWLEDGE_V21141_CAPTURE_DIR",
            "/Users/bytedance/.codex/runtime/"
            "knowledge-v21141-commercial-step-1/captures",
        )
    )
    if not capture_dir.exists():
        pytest.skip("verified capture directory is supplied by the acceptance command")
    modified_captures = tmp_path / "captures"
    shutil.copytree(capture_dir, modified_captures)
    first_capture = next(modified_captures.glob("*.png"))
    content = bytearray(first_capture.read_bytes())
    content[-1] ^= 0x01
    first_capture.write_bytes(content)
    with pytest.raises(ContractError, match="capture PNG hash mismatch"):
        verify_capture_files(modified_captures)


def test_performance_evidence_schema_enforces_every_ga_threshold() -> None:
    schema = load_json(CONTRACT_ROOT / "performance-evidence.schema.json")
    Draft202012Validator.check_schema(schema)
    valid = {
        "schema_version": "knowledge-workspace.performance-evidence.v1",
        "status": "pass",
        "environment": {
            "profile": "production-equivalent",
            "topology_sha256": "a" * 64,
            "artifact_sha256": "b" * 64,
        },
        "load": {
            "concurrent_interactive_users": 100,
            "concurrent_agent_turns": 20,
            "concurrent_import_jobs": 10,
            "duration_seconds": 7200,
        },
        "measurements": {
            "read_api_p95_ms": 500,
            "mutation_accept_p95_ms": 1000,
            "sse_first_event_p95_ms": 2000,
            "monthly_availability": 0.999,
        },
        "recovery": {
            "rpo_minutes": 15,
            "rto_minutes": 60,
            "restore_reconciled": True,
        },
        "evidence_hashes": ["c" * 64],
    }
    Draft202012Validator(schema).validate(valid)
    for path, value in [
        (("load", "concurrent_interactive_users"), 99),
        (("load", "concurrent_agent_turns"), 19),
        (("load", "concurrent_import_jobs"), 9),
        (("measurements", "read_api_p95_ms"), 501),
        (("measurements", "mutation_accept_p95_ms"), 1001),
        (("measurements", "sse_first_event_p95_ms"), 2001),
        (("measurements", "monthly_availability"), 0.9989),
        (("recovery", "rpo_minutes"), 15.01),
        (("recovery", "rto_minutes"), 60.01),
    ]:
        candidate = copy.deepcopy(valid)
        candidate[path[0]][path[1]] = value
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(candidate)


def test_every_commercial_readiness_contract_is_actionable() -> None:
    readiness = load_json(CONTRACT_ROOT / "commercial-readiness.json")
    assert len(readiness["contracts"]) == 15
    for contract in readiness["contracts"].values():
        assert contract["required"]
        assert all(
            isinstance(requirement, str) and requirement.strip()
            for requirement in contract["required"]
        )
        assert isinstance(contract["gate"], str) and contract["gate"].strip()
        assert contract["gate"].strip().lower() not in {"unknown", "todo", "tbd"}


def test_contract_validator_rejects_empty_readiness_evidence(
    tmp_path: Path,
) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    readiness_path = copied_contracts / "commercial-readiness.json"
    readiness = load_json(readiness_path)
    readiness["contracts"]["audit"]["required"] = []
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    with pytest.raises(ContractError, match="commercial readiness"):
        validate_contracts(copied_contracts)


def test_contract_validator_rejects_empty_e2e_evidence(tmp_path: Path) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    skeleton_path = copied_contracts / "e2e-skeleton.json"
    skeleton = load_json(skeleton_path)
    skeleton["cases"][0]["evidence"] = []
    skeleton_path.write_text(json.dumps(skeleton), encoding="utf-8")
    with pytest.raises(ContractError, match="E2E skeleton status and evidence"):
        validate_contracts(copied_contracts)


def test_environment_dependent_e2e_cases_are_explicitly_blocked(
    tmp_path: Path,
) -> None:
    committed = load_json(CONTRACT_ROOT / "e2e-skeleton.json")
    assert {case["status"] for case in committed["cases"]} == {"blocked"}
    assert all(
        all(item.startswith("BLOCKED:") for item in case["evidence"])
        for case in committed["cases"]
    )

    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    skeleton_path = copied_contracts / "e2e-skeleton.json"
    skeleton = load_json(skeleton_path)
    skeleton["cases"][0]["status"] = "todo"
    skeleton["cases"][0]["evidence"] = ["TODO:implementation remains"]
    skeleton_path.write_text(json.dumps(skeleton), encoding="utf-8")
    with pytest.raises(ContractError, match="must remain blocked"):
        validate_contracts(copied_contracts)


def test_contract_validator_rejects_substituted_e2e_case(tmp_path: Path) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    skeleton_path = copied_contracts / "e2e-skeleton.json"
    skeleton = load_json(skeleton_path)
    skeleton["cases"][0]["id"] = "E2E-NOT-A-FROZEN-JOURNEY"
    skeleton_path.write_text(json.dumps(skeleton), encoding="utf-8")
    with pytest.raises(ContractError, match="E2E skeleton IDs"):
        validate_contracts(copied_contracts)


def test_e2e_connector_ids_match_the_required_matrix(tmp_path: Path) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    skeleton_path = copied_contracts / "e2e-skeleton.json"
    skeleton = load_json(skeleton_path)
    connector_case = next(
        case for case in skeleton["cases"] if case["kind"] == "required-connector"
    )
    connector_case["connector_ids"].remove("openapi_spec")
    skeleton_path.write_text(json.dumps(skeleton), encoding="utf-8")
    with pytest.raises(ContractError, match="required Connector IDs"):
        validate_contracts(copied_contracts)


def test_step_1_ga_gate_statuses_cannot_claim_unverified_pass(
    tmp_path: Path,
) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    gates_path = copied_contracts / "ga-gates.json"
    gates = load_json(gates_path)
    gate = next(item for item in gates["gates"] if item["id"] == "availability")
    gate["status"] = "pass"
    gate["evidence"] = ["forged-report.json"]
    gates_path.write_text(json.dumps(gates), encoding="utf-8")
    with pytest.raises(ContractError, match="STEP 1 GA gate status"):
        validate_contracts(copied_contracts)


def test_ga_gate_evidence_cannot_contain_empty_entries(tmp_path: Path) -> None:
    copied_contracts = tmp_path / "contracts"
    shutil.copytree(CONTRACT_ROOT, copied_contracts)
    gates_path = copied_contracts / "ga-gates.json"
    gates = load_json(gates_path)
    gates["gates"][0]["evidence"].append("")
    gates_path.write_text(json.dumps(gates), encoding="utf-8")
    with pytest.raises(ContractError, match="evidence must never be empty"):
        validate_contracts(copied_contracts)


def test_url_tampering_fails_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "placeholder.tar.gz"
    archive.write_bytes(b"not reached")
    identity = load_json(CONTRACT_ROOT / "baseline-identity.json")
    with pytest.raises(ContractError, match="URL mismatch"):
        verify_archive(archive, FROZEN_URL + "?changed=1", identity)


def test_tar_tampering_fails_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "tampered.tar.gz"
    archive.write_bytes(b"tampered")
    identity = load_json(CONTRACT_ROOT / "baseline-identity.json")
    with pytest.raises(ContractError, match="tar SHA-256 mismatch"):
        verify_archive(archive, FROZEN_URL, identity)


@pytest.mark.parametrize(
    ("relative_path", "expected_message"),
    [
        ("prototype/codebase/src/App.tsx", "source_tree_sha256"),
        (
            "prototype/codebase/prototype-route.json",
            "root_route_manifest_sha256",
        ),
        (
            "prototype/codebase/src/prototype-route.json",
            "source_tree_sha256",
        ),
        ("prototype/captures.json", "captures_sha256"),
        ("prototype/codebase/dependencies.json", "dependencies_sha256"),
    ],
)
def test_every_inner_artifact_tamper_fails(
    tmp_path: Path,
    relative_path: str,
    expected_message: str,
) -> None:
    identity = load_json(CONTRACT_ROOT / "baseline-identity.json")
    export_root = Path(
        os.environ.get(
            "KNOWLEDGE_V21141_EXPORT_ROOT",
            "/tmp/knowledge-v21141-step1.Ljw9m9/extracted",
        )
    )
    if not export_root.exists():
        pytest.skip("verified export root is supplied by the acceptance command")
    modified_root = tmp_path / "export"
    shutil.copytree(export_root, modified_root)
    tampered = modified_root / relative_path
    tampered.write_bytes(tampered.read_bytes() + b"\nTAMPERED")
    with pytest.raises(ContractError, match=expected_message):
        verify_export_root(modified_root, identity)


def test_complete_route_tamper_fails_its_own_gate(tmp_path: Path) -> None:
    identity = load_json(CONTRACT_ROOT / "baseline-identity.json")
    export_root = Path(
        os.environ.get(
            "KNOWLEDGE_V21141_EXPORT_ROOT",
            "/tmp/knowledge-v21141-step1.Ljw9m9/extracted",
        )
    )
    if not export_root.exists():
        pytest.skip("verified export root is supplied by the acceptance command")
    modified_root = tmp_path / "export"
    shutil.copytree(export_root, modified_root)
    route = modified_root / "prototype/codebase/src/prototype-route.json"
    content = route.read_bytes()
    assert b"Unified Workspace Home" in content
    route.write_bytes(
        content.replace(b"Unified Workspace Home", b"Xnified Workspace Home")
    )
    tree_hash, _ = source_tree_fingerprint(modified_root / "prototype/codebase/src")
    modified_identity = copy.deepcopy(identity)
    modified_identity["frozen_export"]["source_tree_sha256"] = tree_hash
    with pytest.raises(ContractError, match="complete_route_manifest_sha256"):
        verify_export_root(modified_root, modified_identity)


def test_readme_tampering_fails_identity_gate(tmp_path: Path) -> None:
    identity = load_json(CONTRACT_ROOT / "baseline-identity.json")
    export_root = Path(
        os.environ.get(
            "KNOWLEDGE_V21141_EXPORT_ROOT",
            "/tmp/knowledge-v21141-step1.Ljw9m9/extracted",
        )
    )
    if not export_root.exists():
        pytest.skip("verified export root is supplied by the acceptance command")
    modified_root = tmp_path / "export"
    shutil.copytree(export_root, modified_root)
    readme = modified_root / "prototype/readme.md"
    readme.write_bytes(readme.read_bytes() + b"\nTAMPERED")
    with pytest.raises(ContractError, match="readme_sha256"):
        verify_export_root(modified_root, identity)


def test_archive_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "traversal.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("../escape")
        payload = b"escape"
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    with pytest.raises(ContractError, match="unsafe archive path"):
        assert_safe_tar(archive)


def test_archive_rejects_absolute_path(tmp_path: Path) -> None:
    archive = tmp_path / "absolute.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("/absolute")
        payload = b"escape"
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    with pytest.raises(ContractError, match="unsafe archive path"):
        assert_safe_tar(archive)


def test_archive_rejects_escaping_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("prototype/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../escape"
        bundle.addfile(info)
    with pytest.raises(ContractError, match="escaping archive link"):
        assert_safe_tar(archive)


def test_archive_rejects_escaping_hardlink(tmp_path: Path) -> None:
    archive = tmp_path / "hardlink.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("prototype/link")
        info.type = tarfile.LNKTYPE
        info.linkname = "../escape"
        bundle.addfile(info)
    with pytest.raises(ContractError, match="escaping archive link"):
        assert_safe_tar(archive)


def test_archive_rejects_hardlink_to_missing_member(tmp_path: Path) -> None:
    archive = tmp_path / "missing-hardlink-target.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("prototype/link")
        info.type = tarfile.LNKTYPE
        info.linkname = "prototype/missing"
        bundle.addfile(info)
    with pytest.raises(ContractError, match="missing archive link target"):
        assert_safe_tar(archive)
