"""Per-kind connector configuration contracts.

These models are deliberately separate from the runtime SPI payload.  They
make provider-specific configuration reviewable and prevent a database
connector from silently accepting file or web fields.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .contract_base import ContractModel, SecretRef


class FileConnectorConfig(ContractModel):
    kind: Literal["markdown", "csv", "pdf", "office", "excel"]
    source_ref: str = Field(min_length=1, max_length=2048)
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_files: int = Field(default=10_000, ge=1)
    follow_symlinks: Literal[False] = False
    sheet_allowlist: list[str] = Field(default_factory=list, max_length=100)


class ProviderDocumentConfig(ContractModel):
    kind: Literal["lark_doc", "lark_minutes", "lark_group_chat"]
    document_ref: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef
    scope_ref: str = Field(min_length=1, max_length=2048)
    page_size: int = Field(default=100, ge=1, le=1000)


class DatabaseConnectorConfig(ContractModel):
    kind: Literal["oracle", "postgresql", "mysql"]
    dsn_ref: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef
    schema_allowlist: list[str] = Field(default_factory=list, max_length=100)
    row_limit: int = Field(default=10_000, ge=1, le=1_000_000)
    byte_limit: int = Field(default=50 * 1024 * 1024, ge=1)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class WebConnectorConfig(ContractModel):
    kind: Literal["web_api", "web_url", "rest_api", "graphql", "openapi"]
    endpoint: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef | None = None
    terms_ref: str | None = Field(default=None, max_length=2048)
    operation_allowlist: list[str] = Field(default_factory=list, max_length=100)
    page_size: int = Field(default=100, ge=1, le=1000)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class McpConnectorConfig(ContractModel):
    kind: Literal["mcp"]
    server_url: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef
    oauth_scope_ref: str = Field(min_length=1, max_length=2048)
    tool_allowlist: list[str] = Field(min_length=1, max_length=100)
    output_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class PublishedSkillConnectorConfig(ContractModel):
    kind: Literal["published_skill"]
    skill_ref: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef
    scope_ref: str = Field(min_length=1, max_length=2048)
    dependency_allowlist: list[str] = Field(min_length=1, max_length=100)
    output_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


ConnectorKindConfig = Annotated[
    FileConnectorConfig
    | ProviderDocumentConfig
    | DatabaseConnectorConfig
    | WebConnectorConfig
    | McpConnectorConfig
    | PublishedSkillConnectorConfig,
    Field(discriminator="kind"),
]

_ADAPTER = TypeAdapter(ConnectorKindConfig)


def validate_kind_config(value: object) -> ConnectorKindConfig:
    """Validate one independent connector config without contacting a provider."""
    return _ADAPTER.validate_python(value)


def validate_runtime_connector_config(
    *,
    kind: str,
    endpoint: str,
    options: dict[str, object] | None,
) -> ConnectorKindConfig:
    """Build and validate a typed config from the runtime SPI envelope."""
    values = dict(options or {})
    values["kind"] = kind
    if kind in {"oracle", "postgresql", "mysql"}:
        values.setdefault("dsnRef", endpoint)
    elif kind in {"web_api", "web_url", "rest_api", "graphql", "openapi"}:
        values.setdefault("endpoint", endpoint)
    elif kind == "mcp":
        values.setdefault("serverUrl", endpoint)
    elif kind == "published_skill":
        values.setdefault("skillRef", endpoint)
    elif kind in {"markdown", "csv", "pdf", "office", "excel"}:
        values.setdefault("sourceRef", endpoint)
    elif kind in {"lark_doc", "lark_minutes", "lark_group_chat"}:
        values.setdefault("documentRef", endpoint)
    return validate_kind_config(values)


def connector_config_schema() -> dict[str, object]:
    """Return the generated JSON schema used by contract tooling."""
    return _ADAPTER.json_schema()
