"""Safe ingestion policy for real AutoSkill output files."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import PurePosixPath
from typing import Any


class HtmlArtifactError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_BLOCKED = re.compile(
    r"<\s*(script|iframe|object|embed|form|link)\b|"
    r"\b(on[a-z]+\s*=|javascript\s*:|data\s*:\s*text/html)",
    re.IGNORECASE,
)
_EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']https?://""", re.IGNORECASE)
_EXTERNAL_CSS = re.compile(r"""url\s*\(\s*["']?https?://""", re.IGNORECASE)


def validate_html_artifact(
    content: bytes,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    allow_external: bool = False,
) -> dict[str, Any]:
    if not content:
        raise HtmlArtifactError("ARTIFACT_EMPTY", "HTML artifact is empty")
    if len(content) > max_bytes:
        raise HtmlArtifactError("ARTIFACT_TOO_LARGE", "HTML artifact exceeds size limit")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HtmlArtifactError("ARTIFACT_ENCODING", "HTML artifact must be UTF-8") from exc
    if _BLOCKED.search(text):
        raise HtmlArtifactError("ARTIFACT_UNSAFE", "HTML artifact contains executable or active content")
    if not allow_external and (_EXTERNAL.search(text) or _EXTERNAL_CSS.search(text)):
        raise HtmlArtifactError("ARTIFACT_EXTERNAL_LINK", "external HTML resources are not allowed")
    if "<html" not in text.lower() and "<!doctype" not in text.lower():
        raise HtmlArtifactError("ARTIFACT_NOT_HTML", "output is not an HTML document")
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "media_type": "text/html",
        "encoding": "utf-8",
        "size_bytes": len(content),
        "csp": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'",
        "sandbox": "allow-same-origin",
    }


def validate_output_archive(
    content: bytes,
    *,
    max_file_bytes: int = 10 * 1024 * 1024,
) -> tuple[str, bytes, dict[str, Any]]:
    """Find a real HTML file in AutoSkill's output ZIP without inventing one."""

    if len(content) > max_file_bytes * 4:
        raise HtmlArtifactError("ARTIFACT_OUTPUT_TOO_LARGE", "output ZIP is too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise HtmlArtifactError("ARTIFACT_OUTPUT_INVALID", "output is not a valid ZIP") from exc
    with archive:
        infos = archive.infolist()
        seen: set[str] = set()
        expanded = 0
        for info in infos:
            path = PurePosixPath(info.filename)
            normalized = path.as_posix()
            if (
                not info.filename
                or path.is_absolute()
                or "\\" in info.filename
                or ".." in path.parts
                or normalized != info.filename
            ):
                raise HtmlArtifactError("ARTIFACT_OUTPUT_INVALID", "output ZIP contains an unsafe path")
            if normalized.casefold() in seen:
                raise HtmlArtifactError("ARTIFACT_OUTPUT_INVALID", "output ZIP contains duplicate paths")
            seen.add(normalized.casefold())
            expanded += info.file_size
            if expanded > max_file_bytes * 10:
                raise HtmlArtifactError("ARTIFACT_OUTPUT_TOO_LARGE", "output ZIP expands beyond the size limit")
        candidates = [
            i for i in infos
            if not i.is_dir() and i.filename.lower().endswith((".html", ".htm"))
        ]
        if not candidates:
            raise HtmlArtifactError("ARTIFACT_HTML_MISSING", "AutoSkill output contains no HTML file")
        if len(candidates) > 1:
            # Deterministic selection is safe only when the service names one
            # index explicitly; ambiguous output is retained as a file result.
            raise HtmlArtifactError("ARTIFACT_HTML_AMBIGUOUS", "AutoSkill output contains multiple HTML files")
        info = candidates[0]
        data = archive.read(info)
        return info.filename, data, validate_html_artifact(data)
