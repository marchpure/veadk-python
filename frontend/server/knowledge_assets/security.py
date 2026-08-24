"""Fail-closed validation shared by data_access connector adapters."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urlparse

from .ports import ConnectorConfig

_SECRET_KEY = re.compile(r"(secret|token|password|credential|private.?key|api.?key)", re.I)
_PROMPT_INJECTION = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions|reveal\s+the\s+system\s+prompt|"
    r"bypass\s+(the\s+)?safety|you\s+are\s+now\s+the)",
    re.I,
)


def reject_inline_secrets(config: ConnectorConfig) -> None:
    for key, value in (config.options or {}).items():
        rendered = value if isinstance(value, str) else repr(value)
        if _SECRET_KEY.search(key) or _SECRET_KEY.search(rendered):
            raise ValueError("credentials must be referenced by secretRef, never supplied inline")


def validate_web_endpoint(
    endpoint: str,
    *,
    resolver: Callable[[str], list[str]] | None = None,
) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Web/API endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("Web/API endpoint must not contain inline credentials")
    addresses = resolver(parsed.hostname) if resolver else _resolve(parsed.hostname)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise ValueError("Web/API endpoint resolves to a non-public address")


def _resolve(hostname: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(hostname, None)})


def validate_read_only_sql(query: str, *, parameters: dict[str, object]) -> None:
    statement = query.strip()
    if not re.match(r"^(SELECT|WITH)\b", statement, re.I):
        raise ValueError("database connector accepts read-only SELECT/WITH statements")
    if ";" in statement.rstrip(";"):
        raise ValueError("database query must contain one statement")
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|EXEC|CALL)\b", statement, re.I):
        raise ValueError("database query contains a write or procedure operation")
    if re.search(r"(?<!:):[A-Za-z_][A-Za-z0-9_]*", statement):
        names = set(re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", statement))
        if names - set(parameters):
            raise ValueError("all SQL parameters must be supplied separately")


def validate_database_limits(
    *,
    row_limit: int,
    byte_limit: int,
    timeout_seconds: int,
) -> None:
    if row_limit < 1:
        raise ValueError("database row limit must be positive")
    if byte_limit < 1:
        raise ValueError("database byte limit must be positive")
    if timeout_seconds < 1:
        raise ValueError("database timeout must be positive")


def sanitize_mcp_output(output: str) -> str:
    """Keep provider output untrusted and quarantine instruction-like content."""
    if _PROMPT_INJECTION.search(output):
        return "[QUARANTINED_UNTRUSTED_MCP_OUTPUT]"
    return output


def validate_archive_limits(
    *,
    compressed_bytes: int,
    expanded_bytes: int,
    file_count: int,
    member_names: list[str],
    max_expansion_ratio: int = 100,
    max_expanded_bytes: int = 100 * 1024 * 1024,
    max_files: int = 10_000,
) -> None:
    if compressed_bytes < 1 or expanded_bytes < 0:
        raise ValueError("archive byte counts must be valid")
    if expanded_bytes > max_expanded_bytes:
        raise ValueError("archive expanded-byte limit exceeded")
    if expanded_bytes / compressed_bytes > max_expansion_ratio:
        raise ValueError("archive compression expansion ratio exceeded")
    if file_count < 0 or file_count > max_files:
        raise ValueError("archive file-count limit exceeded")
    if any(
        name.startswith("/") or ".." in name.split("/")
        for name in member_names
    ):
        raise ValueError("archive member path escapes the destination")


def validate_mcp_tool(
    tool_name: str,
    *,
    allowlist: set[str],
    output_bytes: int,
    max_output_bytes: int = 1_000_000,
) -> None:
    if tool_name not in allowlist:
        raise ValueError("MCP tool is not on the configured allowlist")
    if output_bytes < 0 or output_bytes > max_output_bytes:
        raise ValueError("MCP output exceeds the configured budget")
