"""Security validation for AutoSkill Skill ZIP downloads."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from pathlib import PurePosixPath
from typing import Any


class SkillZipError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _safe_entry_path(value: str) -> str:
    """Keep provider-controlled paths useful in errors without log injection."""

    sanitized = "".join(
        char if char.isprintable() and char not in "\r\n\t" else "?"
        for char in value
    )
    return sanitized[:240] or "[empty]"


def _runtime_residue(relative: PurePosixPath, root: tuple[str, ...]) -> bool:
    """Identify only the producer's observed test/runtime residue.

    These names are never accepted as Skill content. They are removed by the
    consumer normalization boundary after the archive has passed all generic
    ZIP safety checks. Other unsupported paths remain hard failures.
    """

    parts = relative.parts
    if parts == ("pytest.ini",):
        return True
    if parts and parts[0] in {".pytest_cache", "__pycache__"}:
        return True
    return len(parts) > 1 and parts[-1].endswith(".pyc") and "__pycache__" in parts


def _inspect_skill_zip(
    content: bytes,
    *,
    max_archive_bytes: int,
    max_expanded_bytes: int,
    max_files: int,
    max_depth: int,
    max_compression_ratio: int,
) -> tuple[zipfile.ZipFile, list[zipfile.ZipInfo], list[str], tuple[str, ...], int]:
    if not content:
        raise SkillZipError("SKILL_ZIP_EMPTY", "Skill ZIP is empty")
    if len(content) > max_archive_bytes:
        raise SkillZipError(
            "SKILL_ZIP_TOO_LARGE", "Skill ZIP exceeds compressed size limit"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise SkillZipError(
            "SKILL_ZIP_INVALID", "Skill ZIP is not a valid ZIP archive"
        ) from exc

    infos = archive.infolist()
    paths: list[str] = []
    folded: set[str] = set()
    expanded = 0
    files = 0
    for info in infos:
        raw = info.filename
        path = PurePosixPath(raw)
        normalized = path.as_posix()
        if raw.endswith("/"):
            normalized += "/"
        if (
            not raw
            or "\x00" in raw
            or path.is_absolute()
            or "\\" in raw
            or ".." in path.parts
            or normalized != raw
            or len(path.parts) > max_depth
        ):
            raise SkillZipError(
                "SKILL_ZIP_UNSAFE_PATH",
                f"unsafe ZIP path: {_safe_entry_path(raw)}",
            )
        if normalized.casefold() in folded:
            raise SkillZipError(
                "SKILL_ZIP_DUPLICATE_PATH",
                f"duplicate ZIP path: {_safe_entry_path(raw)}",
            )
        folded.add(normalized.casefold())
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type in {
            stat.S_IFLNK,
            stat.S_IFCHR,
            stat.S_IFBLK,
            stat.S_IFIFO,
            stat.S_IFSOCK,
        }:
            raise SkillZipError(
                "SKILL_ZIP_SPECIAL_FILE",
                f"special ZIP entry: {_safe_entry_path(raw)}",
            )
        if info.is_dir() or raw.endswith("/"):
            continue
        files += 1
        if files > max_files:
            raise SkillZipError(
                "SKILL_ZIP_FILE_COUNT", "Skill ZIP contains too many files"
            )
        expanded += info.file_size
        if expanded > max_expanded_bytes:
            raise SkillZipError(
                "SKILL_ZIP_EXPANDED_TOO_LARGE", "expanded Skill ZIP is too large"
            )
        if (info.compress_size == 0 and info.file_size > 0) or (
            info.compress_size
            and info.file_size > info.compress_size * max_compression_ratio
        ):
            raise SkillZipError(
                "SKILL_ZIP_COMPRESSION_BOMB",
                f"suspicious compression ratio: {_safe_entry_path(raw)}",
            )
        paths.append(normalized)

    if not paths:
        archive.close()
        raise SkillZipError("SKILL_ZIP_EMPTY", "Skill ZIP contains no files")
    entries_for_root = [
        PurePosixPath(path.rstrip("/")).parts
        for path in paths
    ]
    roots = {parts[:2] for parts in entries_for_root}
    if len(roots) != 1:
        archive.close()
        raise SkillZipError(
            "SKILL_ZIP_ROOT", "Skill ZIP must have one skillhub/<name>/ root"
        )
    root = next(iter(roots))
    if root[0] != "skillhub" or len(root) != 2 or not root[1]:
        archive.close()
        raise SkillZipError(
            "SKILL_ZIP_ROOT", "Skill ZIP root must be skillhub/<name>/"
        )
    return archive, infos, paths, root, expanded


def normalize_skill_zip(
    content: bytes,
    *,
    max_archive_bytes: int = 20 * 1024 * 1024,
    max_expanded_bytes: int = 100 * 1024 * 1024,
    max_files: int = 256,
    max_depth: int = 16,
    max_compression_ratio: int = 200,
) -> bytes:
    """Remove only the observed AutoSkill test/runtime residue.

    The source archive is fully inspected first, including traversal,
    duplicate, special-file, compression, size, and single-root checks.
    """

    archive, infos, paths, root, _ = _inspect_skill_zip(
        content,
        max_archive_bytes=max_archive_bytes,
        max_expanded_bytes=max_expanded_bytes,
        max_files=max_files,
        max_depth=max_depth,
        max_compression_ratio=max_compression_ratio,
    )
    root_prefix = "/".join(root)
    retained: list[str] = []
    removed: list[str] = []
    try:
        for path in paths:
            relative = PurePosixPath(path.removeprefix(root_prefix + "/"))
            if _runtime_residue(relative, root):
                removed.append(path)
            else:
                retained.append(path)
        for path in retained:
            relative = PurePosixPath(path.removeprefix(root_prefix + "/"))
            first = relative.parts[0] if relative.parts else ""
            root_level_html = len(relative.parts) == 1 and relative.suffix.casefold() in {
                ".html",
                ".htm",
            }
            if "BuildPlan" in relative.name:
                raise SkillZipError(
                    "SKILL_ZIP_UNSUPPORTED_ENTRY",
                    f"Skill ZIP must not contain BuildPlan artifact: "
                    f"{_safe_entry_path(path)}",
                )
            if not root_level_html and first not in {
                "SKILL.md",
                "assets",
                "data",
                "docs",
                "glossary.json",
                "manifest.json",
                "output",
                "package-lock.json",
                "package.json",
                "presentation",
                "presentation.html",
                "pyproject.toml",
                "README.md",
                "requirements.txt",
                "resources",
                "schema_glossary.json",
                "scripts",
                "tests",
                "query_results.csv",
            }:
                raise SkillZipError(
                    "SKILL_ZIP_UNSUPPORTED_ENTRY",
                    f"Skill ZIP contains unsupported entry: {_safe_entry_path(path)}",
                )
        if not removed:
            return content
        output = io.BytesIO()
        retained_set = set(retained)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as normalized:
            for info in infos:
                if info.filename in retained_set:
                    normalized.writestr(info, archive.read(info.filename))
        return output.getvalue()
    finally:
        archive.close()


def validate_skill_zip(
    content: bytes,
    *,
    max_archive_bytes: int = 20 * 1024 * 1024,
    max_expanded_bytes: int = 100 * 1024 * 1024,
    max_files: int = 256,
    max_depth: int = 16,
    max_compression_ratio: int = 200,
) -> dict[str, Any]:
    """Validate and describe one immutable SkillHub archive.

    The accepted archive has exactly one non-metadata root:
    ``skillhub/<name>/SKILL.md``.  The returned digest is over the original
    downloaded bytes and must be used as the immutable object key.
    """

    archive, _, paths, root, expanded = _inspect_skill_zip(
        content,
        max_archive_bytes=max_archive_bytes,
        max_expanded_bytes=max_expanded_bytes,
        max_files=max_files,
        max_depth=max_depth,
        max_compression_ratio=max_compression_ratio,
    )
    with archive:
        root_prefix = "/".join(root)
        allowed_top_level = {
            "SKILL.md",
            "assets",
            "data",
            "docs",
            "glossary.json",
            "manifest.json",
            "output",
            "package-lock.json",
            "package.json",
            "presentation",
            "presentation.html",
            "pyproject.toml",
            "README.md",
            "requirements.txt",
            "resources",
            "schema_glossary.json",
            "scripts",
            "tests",
            "query_results.csv",
        }
        for path in paths:
            relative = path.removeprefix(root_prefix + "/")
            first = PurePosixPath(relative).parts[0] if relative else ""
            root_level_html = (
                len(PurePosixPath(relative).parts) == 1
                and PurePosixPath(relative).suffix.casefold() in {".html", ".htm"}
            )
            if "BuildPlan" in PurePosixPath(relative).name:
                raise SkillZipError(
                    "SKILL_ZIP_UNSUPPORTED_ENTRY",
                    f"Skill ZIP must not contain BuildPlan artifact: "
                    f"{_safe_entry_path(path)}",
                )
            if not root_level_html and first not in allowed_top_level:
                raise SkillZipError(
                    "SKILL_ZIP_UNSUPPORTED_ENTRY",
                    f"Skill ZIP contains unsupported entry: {_safe_entry_path(path)}",
                )
        skill_path = f"{root[0]}/{root[1]}/SKILL.md"
        if skill_path not in paths:
            raise SkillZipError(
                "SKILL_MD_MISSING", "Skill ZIP must contain a non-empty SKILL.md"
            )
        skill_md = archive.read(skill_path)
        if not skill_md.strip():
            raise SkillZipError("SKILL_MD_EMPTY", "SKILL.md must be non-empty")
        try:
            text = skill_md.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillZipError("SKILL_MD_ENCODING", "SKILL.md must be UTF-8") from exc
        return {
            "sha256": hashlib.sha256(content).hexdigest(),
            "compressed_bytes": len(content),
            "expanded_bytes": expanded,
            "file_count": len(paths),
            "root": "/".join(root) + "/",
            "skill_name": root[1],
            "skill_md_bytes": len(skill_md),
            "skill_md": text,
            "paths": tuple(paths),
        }


def extract_skill_from_state_zip(
    content: bytes,
    skill_name: str,
    *,
    max_archive_bytes: int = 20 * 1024 * 1024,
    max_expanded_bytes: int = 100 * 1024 * 1024,
    max_files: int = 4_096,
    max_depth: int = 32,
    max_compression_ratio: int = 200,
) -> bytes:
    """Safely reduce an AutoSkill state archive to one Skill workspace.

    ``state.zip`` also contains provider/runtime state and built-in Skills, so
    it is intentionally not accepted by ``validate_skill_zip`` as a Skill
    archive.  Scan the complete state archive with separate limits first,
    then extract only the requested ``skillhub/<name>/`` subtree for the
    strict Skill ZIP contract.
    """

    if not skill_name or "/" in skill_name or "\\" in skill_name:
        raise SkillZipError(
            "SKILL_STATE_TARGET_INVALID",
            f"invalid state Skill target: {_safe_entry_path(skill_name)}",
        )
    if not content:
        raise SkillZipError("SKILL_STATE_EMPTY", "state.zip is empty")
    if len(content) > max_archive_bytes:
        raise SkillZipError(
            "SKILL_STATE_TOO_LARGE", "state.zip exceeds compressed size limit"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise SkillZipError(
            "SKILL_STATE_INVALID", "state.zip is not a valid ZIP archive"
        ) from exc

    paths: list[str] = []
    folded: set[str] = set()
    expanded = 0
    files = 0
    target_prefix = f"skillhub/{skill_name}/"
    try:
        for info in archive.infolist():
            raw = info.filename
            path = PurePosixPath(raw)
            normalized = path.as_posix()
            if raw.endswith("/"):
                normalized += "/"
            if (
                not raw
                or "\x00" in raw
                or path.is_absolute()
                or "\\" in raw
                or ".." in path.parts
                or normalized != raw
                or len(path.parts) > max_depth
            ):
                raise SkillZipError(
                    "SKILL_STATE_UNSAFE_PATH",
                    f"unsafe state ZIP path: {_safe_entry_path(raw)}",
                )
            if normalized.casefold() in folded:
                raise SkillZipError(
                    "SKILL_STATE_DUPLICATE_PATH",
                    f"duplicate state ZIP path: {_safe_entry_path(raw)}",
                )
            folded.add(normalized.casefold())
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if file_type in {
                stat.S_IFLNK,
                stat.S_IFCHR,
                stat.S_IFBLK,
                stat.S_IFIFO,
                stat.S_IFSOCK,
            }:
                raise SkillZipError(
                    "SKILL_STATE_SPECIAL_FILE",
                    f"special state ZIP entry: {_safe_entry_path(raw)}",
                )
            if info.is_dir() or raw.endswith("/"):
                continue
            files += 1
            if files > max_files:
                raise SkillZipError(
                    "SKILL_STATE_FILE_COUNT",
                    "state.zip contains too many files",
                )
            expanded += info.file_size
            if expanded > max_expanded_bytes:
                raise SkillZipError(
                    "SKILL_STATE_EXPANDED_TOO_LARGE",
                    "expanded state.zip is too large",
                )
            if (info.compress_size == 0 and info.file_size > 0) or (
                info.compress_size
                and info.file_size > info.compress_size * max_compression_ratio
            ):
                raise SkillZipError(
                    "SKILL_STATE_COMPRESSION_BOMB",
                    f"suspicious state ZIP compression ratio: "
                    f"{_safe_entry_path(raw)}",
                )
            paths.append(normalized)

        selected = [path for path in paths if path.startswith(target_prefix)]
        if not selected:
            raise SkillZipError(
                "SKILL_STATE_TARGET_MISSING",
                f"state.zip has no target Skill subtree: "
                f"{_safe_entry_path(target_prefix)}",
            )
        selected_set = set(selected)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as reduced:
            for info in archive.infolist():
                if info.filename in selected_set:
                    reduced.writestr(info, archive.read(info.filename))
        return output.getvalue()
    finally:
        archive.close()
