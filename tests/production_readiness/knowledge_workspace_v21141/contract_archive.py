"""Frozen-export identity, extraction, and capture verification."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPO_ROOT / "tests/fixtures/knowledge_workspace_v21141"
FROZEN_EXPORT_IDENTITY = {
    "url": (
        "https://cdn-tos-cn.bytedance.net/obj/tiktok-web-ai-cn/"
        "b5c172e6b1d79d5617ff49bfb11875507e25d33a5ee32af3ef90be4aa32ef773.tar.gz"
    ),
    "tar_sha256": "b5c172e6b1d79d5617ff49bfb11875507e25d33a5ee32af3ef90be4aa32ef773",
    "source_tree_sha256": (
        "57e97670c6091219dcf1ac35d76dd174a45c9fa69841ce5b7887caef39b27c83"
    ),
    "source_file_count": 47,
    "source_lines_posix": 9514,
    "source_bytes": 607128,
    "readme_sha256": "9c7570ba151c2f3c64a85276202450bebe217f5f1f886134b2258288bc7313d8",
    "captures_sha256": "83f05bb57e7039bbe715078dd0e818074b30de3f45e2a85349c21af090fe5199",
    "capture_state_count": 13,
    "unique_png_count": 12,
    "root_route_manifest_sha256": (
        "339670643d53423e28850a0a6babff31a1042bdf6937897ac26ad35f8e4b5746"
    ),
    "complete_route_manifest_sha256": (
        "51a972c437e0580384249cc183cc7ec70d3292f416b5a4986e12bc32e5b8c92b"
    ),
    "dependencies_sha256": (
        "04a91782d6cd93dad26da3e529ac414ab29e6654063cf1655f5aebeae8e0c716"
    ),
}
FROZEN_VERIFICATION_ORDER = [
    "url",
    "tar_sha256",
    "archive_path_safety",
    "read_prototype_readme",
    "source_tree_sha256",
    "captures_sha256",
    "root_route_manifest_sha256",
    "complete_route_manifest_sha256",
    "dependencies_sha256",
    "screenshots_or_candidate_implementation",
]


class ContractError(RuntimeError):
    """A Commercial GA contract failed closed."""


def validate_identity_contract(identity: dict[str, Any]) -> None:
    expected_top_level = {
        "schema_version": "knowledge-workspace.baseline-identity.v1",
        "repository": "https://github.com/volcengine/veadk-python",
        "baseline_commit": "3dbee406d2be8eea5efe1b7fe18199a193f8f25e",
        "oracle_commit": "7595864d723cbf510ecaf16e3f22626085c0f2d6",
        "prototype": "知识资产工作区 v2.11.4.1 Final",
        "line_count_definition": (
            "Count LF bytes in each frozen source file; sum in relative POSIX "
            "path order."
        ),
    }
    for field, expected in expected_top_level.items():
        if identity.get(field) != expected:
            raise ContractError(f"frozen baseline identity changed: {field}")
    if identity.get("frozen_export") != FROZEN_EXPORT_IDENTITY:
        raise ContractError("frozen baseline identity changed: frozen_export")
    if identity.get("verification_order") != FROZEN_VERIFICATION_ORDER:
        raise ContractError("frozen baseline identity changed: verification_order")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def source_tree_fingerprint(source_root: Path) -> tuple[str, list[dict[str, Any]]]:
    digest = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    files = sorted(
        (path for path in source_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source_root).as_posix(),
    )
    for path in files:
        relative_path = path.relative_to(source_root).as_posix()
        content = path.read_bytes()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        rows.append(
            {
                "source_path": f"prototype/codebase/src/{relative_path}",
                "target_path": (
                    f"frontend/src/knowledge-workspace/frozen-ui/{relative_path}"
                ),
                "sha256": hashlib.sha256(content).hexdigest(),
                "lines_posix": content.count(b"\n"),
                "bytes": len(content),
            }
        )
    return digest.hexdigest(), rows


def flatten_route_manifest(
    node: dict[str, Any], parent: str | None = None
) -> list[dict[str, Any]]:
    row = {
        "state_name": node["state_name"],
        "state_url": node["state_url"],
        "interaction": node.get("interaction", "root"),
        "parent_state_url": parent,
        "status": "frozen",
    }
    rows = [row]
    for child in node.get("children", []):
        rows.extend(flatten_route_manifest(child, node["state_url"]))
    return rows


def assert_safe_tar(archive: Path) -> int:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        member_names = {PurePosixPath(member.name) for member in members}
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ContractError(f"unsafe archive path: {member.name}")
            if not (
                member.isfile() or member.isdir() or member.issym() or member.islnk()
            ):
                raise ContractError(f"unsupported archive entry: {member.name}")
            if member.issym() or member.islnk():
                target = PurePosixPath(member.linkname)
                if target.is_absolute():
                    raise ContractError(
                        f"absolute archive link: {member.name} -> {member.linkname}"
                    )
                resolved = (
                    PurePosixPath(*path.parts[:-1], *target.parts)
                    if member.issym()
                    else target
                )
                depth = 0
                for part in resolved.parts:
                    depth += -1 if part == ".." else 1
                    if depth < 0:
                        raise ContractError(
                            f"escaping archive link: {member.name} -> {member.linkname}"
                        )
                if member.islnk() and resolved not in member_names:
                    raise ContractError(
                        f"missing archive link target: "
                        f"{member.name} -> {member.linkname}"
                    )
        return len(members)


def safe_extract(archive: Path, destination: Path) -> None:
    assert_safe_tar(archive)
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(destination, filter="data")


def verify_export_root(
    export_root: Path,
    identity: dict[str, Any],
) -> dict[str, Any]:
    prototype = export_root / "prototype"
    readme = prototype / "readme.md"
    if not readme.is_file():
        raise ContractError("missing frozen-export entry: readme")
    readme_content = readme.read_bytes()
    if not readme_content:
        raise ContractError("empty frozen-export readme")
    paths = {
        "source_tree": prototype / "codebase/src",
        "captures": prototype / "captures.json",
        "root_route_manifest": prototype / "codebase/prototype-route.json",
        "complete_route_manifest": prototype / "codebase/src/prototype-route.json",
        "dependencies": prototype / "codebase/dependencies.json",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise ContractError(f"missing frozen-export entries: {', '.join(missing)}")

    tree_hash, source_files = source_tree_fingerprint(paths["source_tree"])
    actual = {
        "source_tree_sha256": tree_hash,
        "source_file_count": len(source_files),
        "source_lines_posix": sum(row["lines_posix"] for row in source_files),
        "source_bytes": sum(row["bytes"] for row in source_files),
        "captures_sha256": sha256_file(paths["captures"]),
        "root_route_manifest_sha256": sha256_file(paths["root_route_manifest"]),
        "complete_route_manifest_sha256": sha256_file(paths["complete_route_manifest"]),
        "dependencies_sha256": sha256_file(paths["dependencies"]),
        "readme_sha256": hashlib.sha256(readme_content).hexdigest(),
    }
    expected = identity["frozen_export"]
    for field, value in actual.items():
        if value != expected[field]:
            raise ContractError(
                f"identity mismatch for {field}: expected {expected[field]!r}, "
                f"got {value!r}"
            )

    captures = load_json(paths["captures"])["captures"]
    if len(captures) != expected["capture_state_count"]:
        raise ContractError("capture state count mismatch")
    unique_pngs = {item["tosUrl"].rsplit("/", 1)[-1] for item in captures}
    if len(unique_pngs) != expected["unique_png_count"]:
        raise ContractError("unique PNG count mismatch")
    return actual


def verify_contracts_against_export(
    export_root: Path,
    contract_root: Path = CONTRACT_ROOT,
) -> dict[str, int]:
    """Reconcile every frozen manifest row with the authenticated export."""
    prototype = export_root / "prototype"
    _, actual_sources = source_tree_fingerprint(prototype / "codebase/src")
    source_manifest = load_json(contract_root / "source-files.json")
    if len(source_manifest["files"]) != len(actual_sources):
        raise ContractError("source manifest row count differs from frozen export")
    for committed, actual in zip(source_manifest["files"], actual_sources, strict=True):
        expected = {
            **actual,
            "routes": committed.get("routes"),
            "status": "frozen",
        }
        if committed != expected or not committed["routes"]:
            raise ContractError(
                f"source manifest differs from frozen export: "
                f"{committed.get('source_path', '<missing>')}"
            )

    raw_captures = load_json(prototype / "captures.json")["captures"]
    capture_manifest = load_json(contract_root / "captures.json")
    actual_captures = []
    for index, capture in enumerate(raw_captures, 1):
        png_hash = capture["tosUrl"].rsplit("/", 1)[-1].removesuffix(".png")
        actual_captures.append(
            {
                "id": f"CAP-{index:02d}",
                "state_url": capture["stateUrl"],
                "tos_url": capture["tosUrl"],
                "png_sha256": png_hash,
                "viewport": [1920, 1080],
                "status": "frozen",
            }
        )
    if capture_manifest["captures"] != actual_captures:
        raise ContractError("capture manifest differs from frozen export")

    route_contract = load_json(contract_root / "route-manifests.json")["manifests"]
    route_paths = {
        "root": prototype / "codebase/prototype-route.json",
        "complete": prototype / "codebase/src/prototype-route.json",
    }
    for name, path in route_paths.items():
        expected = {
            "source_path": path.relative_to(export_root).as_posix(),
            "sha256": sha256_file(path),
            "nodes": flatten_route_manifest(load_json(path)),
        }
        if route_contract.get(name) != expected:
            raise ContractError(f"{name} route manifest differs from frozen export")

    return {
        "source_manifest_rows": len(actual_sources),
        "capture_manifest_rows": len(actual_captures),
        "root_route_nodes": len(route_contract["root"]["nodes"]),
        "complete_route_nodes": len(route_contract["complete"]["nodes"]),
    }


def verify_archive(
    archive: Path,
    source_url: str,
    identity: dict[str, Any],
    extract_to: Path | None = None,
) -> dict[str, Any]:
    validate_identity_contract(identity)
    expected = identity["frozen_export"]
    if source_url != expected["url"]:
        raise ContractError("frozen-export URL mismatch")
    actual_tar_hash = sha256_file(archive)
    if actual_tar_hash != expected["tar_sha256"]:
        raise ContractError(
            f"tar SHA-256 mismatch: expected {expected['tar_sha256']}, "
            f"got {actual_tar_hash}"
        )
    temporary_parent = (
        Path(tempfile.mkdtemp(prefix="knowledge-v21141-"))
        if extract_to is None
        else None
    )
    if extract_to is None:
        if temporary_parent is None:
            raise AssertionError("temporary extraction parent was not created")
        destination = temporary_parent / "export"
    else:
        destination = extract_to
    owns_destination = extract_to is None
    try:
        safe_extract(archive, destination)
        result = verify_export_root(destination, identity)
        result.update(verify_contracts_against_export(destination))
        result["tar_sha256"] = actual_tar_hash
        result["safe_archive_members"] = assert_safe_tar(archive)
        return result
    finally:
        if owns_destination and temporary_parent is not None:
            shutil.rmtree(temporary_parent)


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ContractError(f"not a PNG: {path}")
    return struct.unpack(">II", header[16:24])


def verify_capture_files(
    capture_dir: Path, contract_root: Path = CONTRACT_ROOT
) -> dict[str, Any]:
    contract = load_json(contract_root / "captures.json")
    checked: set[str] = set()
    for capture in contract["captures"]:
        png_hash = capture["png_sha256"]
        if png_hash in checked:
            continue
        checked.add(png_hash)
        path = capture_dir / f"{png_hash}.png"
        if not path.is_file():
            raise ContractError(f"missing capture PNG: {path}")
        if sha256_file(path) != png_hash:
            raise ContractError(f"capture PNG hash mismatch: {path}")
        if list(png_dimensions(path)) != capture["viewport"]:
            raise ContractError(f"capture PNG dimensions mismatch: {path}")
    return {"capture_states": len(contract["captures"]), "unique_pngs": len(checked)}
