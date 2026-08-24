"""Fail-closed validation shared by data_access connector adapters."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urlparse

from .ports import ConnectorConfig

_SECRET_KEY = re.compile(r"(secret|token|password|credential|private.?key|api.?key)", re.I)


def reject_inline_secrets(config: ConnectorConfig) -> None:
    for key, value in (config.options or {}).items():
        if _SECRET_KEY.search(key) or _SECRET_KEY.search(value):
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
