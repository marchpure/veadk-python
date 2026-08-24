"""Real local-file connectors and fail-closed external connector registry."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from .ports import (
    ConnectorAdapter,
    ConnectorConfig,
    ConnectorContext,
    ConnectorEvent,
    CredentialBlockedConnector,
)


class LocalFileConnector:
    """Read-only Markdown/CSV connector with bounded, deterministic reads."""

    def __init__(self, *, root: str | Path, max_bytes: int = 10 * 1024 * 1024) -> None:
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes

    def _path(self, config: ConnectorConfig) -> Path:
        candidate = (self.root / config.endpoint).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("local source escapes the configured workspace root")
        if candidate.suffix.lower() not in {".md", ".markdown", ".csv"}:
            raise ValueError("only Markdown and CSV sources are supported")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if candidate.stat().st_size > self.max_bytes:
            raise ValueError("local source exceeds the configured size limit")
        return candidate

    def _event(self, context: ConnectorContext, operation: str, path: Path) -> ConnectorEvent:
        return ConnectorEvent(
            operation=operation,
            status="succeeded",
            trace_id=context.trace_id,
            details={"path": str(path.relative_to(self.root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        )

    def validate_config(self, context, config):
        return self._event(context, "validateConfig", self._path(config))

    def test_connection(self, context, config):
        return self._event(context, "testConnection", self._path(config))

    def discover(self, context, config):
        return self._event(context, "discover", self._path(config))

    def introspect(self, context, config):
        path = self._path(config)
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8") as handle:
                columns = next(csv.reader(handle), [])
            return ConnectorEvent("introspect", "succeeded", context.trace_id, {"columns": ",".join(columns)})
        return ConnectorEvent("introspect", "succeeded", context.trace_id, {"format": "markdown"})

    def sample(self, context, config):
        path = self._path(config)
        return self._event(context, "sample", path)

    def read(self, context, config):
        return self._event(context, "read", self._path(config))

    def subscribe(self, context, config):
        return ConnectorEvent("subscribe", "failed", context.trace_id, {"reason": "local files are not subscribable"})

    def checkpoint(self, context, config):
        return self._event(context, "checkpoint", self._path(config))

    def close(self, context, config):
        return ConnectorEvent("close", "succeeded", context.trace_id, {})


def connector_for(kind: str, *, root: str | Path = ".") -> ConnectorAdapter:
    if kind in {"markdown", "csv"}:
        return LocalFileConnector(root=root)
    if kind in {"oracle", "web_api", "mcp", "published_skill"}:
        return CredentialBlockedConnector(kind)
    raise ValueError(f"unsupported data_access connector kind: {kind}")
