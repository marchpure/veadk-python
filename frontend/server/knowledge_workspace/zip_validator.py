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

    with archive:
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
                raise SkillZipError("SKILL_ZIP_UNSAFE_PATH", f"unsafe ZIP path: {raw}")
            if normalized.casefold() in folded:
                raise SkillZipError(
                    "SKILL_ZIP_DUPLICATE_PATH", f"duplicate ZIP path: {raw}"
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
                    "SKILL_ZIP_SPECIAL_FILE", f"special ZIP entry: {raw}"
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
                    "SKILL_ZIP_COMPRESSION_BOMB", f"suspicious compression ratio: {raw}"
                )
            paths.append(normalized)

        if not paths:
            raise SkillZipError("SKILL_ZIP_EMPTY", "Skill ZIP contains no files")
        entries_for_root = [
            PurePosixPath(path.rstrip("/")).parts
            for path in (
                item.filename
                for item in infos
                if item.filename and not item.filename.endswith("/")
            )
        ]
        roots = {parts[:2] for parts in entries_for_root}
        if len(roots) != 1:
            raise SkillZipError(
                "SKILL_ZIP_ROOT", "Skill ZIP must have one skillhub/<name>/ root"
            )
        root = next(iter(roots))
        if root[0] != "skillhub" or len(root) != 2 or not root[1]:
            raise SkillZipError(
                "SKILL_ZIP_ROOT", "Skill ZIP root must be skillhub/<name>/"
            )
        root_prefix = "/".join(root)
        allowed_top_level = {"SKILL.md", "manifest.json", "scripts", "tests"}
        for path in paths:
            relative = path.removeprefix(root_prefix + "/")
            first = PurePosixPath(relative).parts[0] if relative else ""
            if first not in allowed_top_level:
                raise SkillZipError(
                    "SKILL_ZIP_UNSUPPORTED_ENTRY",
                    "Skill ZIP must contain only SKILL.md, scripts, tests, and optional manifest.json",
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
            "file_count": files,
            "root": "/".join(root) + "/",
            "skill_name": root[1],
            "skill_md_bytes": len(skill_md),
            "skill_md": text,
            "paths": tuple(paths),
        }
