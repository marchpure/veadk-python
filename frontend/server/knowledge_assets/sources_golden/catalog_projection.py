"""Read-model projections for the immutable connector catalog."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from .models import (
    CapabilityReason,
    ConnectorCatalogView,
    ConnectorCategory,
    ConnectorDefinition,
    FormField,
    FormSchema,
)

# These adapters are implemented and exercised against deterministic local
# protocol fixtures.  Provider-backed adapters remain visible in the catalog,
# but must not be advertised as ready until a server-side credential/provider
# is available for the current workspace.
_LOCAL_PROTOCOL_CONNECTORS = frozenset(
    {
        "csv",
        "excel",
        "json",
        "parquet",
        "doc_txt",
        "local_file",
        "sqlite",
        "postgresql",
        "mysql",
        "rest_api",
        "graphql",
        "web_discovery",
        "webhook",
        "mcp_custom",
        "custom_http",
        "openapi_spec",
    }
)

_MCP_BROWSER_SCHEMA = FormSchema(
    properties={
        "profileId": FormField(
            type="string",
            title="Server MCP profile",
            required=True,
            description=(
                "Identifier of an MCP profile registered and resolved by the server."
            ),
        )
    },
    required=["profileId"],
)


def _public_definition(definition: ConnectorDefinition) -> ConnectorDefinition:
    """Remove server-only MCP execution settings from browser-facing catalogs."""
    updates: dict[str, object] = {}
    if definition.connector_key == "mcp_custom":
        updates.update(
            {
                "input_schema": _MCP_BROWSER_SCHEMA,
                "credential_schema": FormSchema(properties={}),
            }
        )
    if definition.connector_key not in _LOCAL_PROTOCOL_CONNECTORS:
        updates.update(
            {
                "capability_state": "credential_blocked",
                "reason": CapabilityReason(
                    code="CREDENTIAL_REQUIRED",
                    message=(
                        "需要服务端 secretRef 和可访问的 provider/sandbox；"
                        "当前工作区尚未提供外部凭据。"
                    ),
                ),
            }
        )
    return definition.model_copy(update=updates) if updates else definition


def connector_catalog_view(
    connectors: Sequence[ConnectorDefinition],
    *,
    category: ConnectorCategory | None = None,
    query: str | None = None,
) -> ConnectorCatalogView:
    normalized = (query or "").strip().casefold()
    rows = [
        _public_definition(item)
        for item in connectors
        if (category is None or item.category == category)
        and (
            not normalized
            or normalized in item.connector_key.casefold()
            or normalized in item.name.casefold()
            or normalized in item.description.casefold()
        )
    ]
    counts = Counter(item.category for item in connectors)
    category_names: tuple[ConnectorCategory, ...] = (
        "office",
        "file",
        "db",
        "api",
        "custom",
    )
    return ConnectorCatalogView(
        connectors=rows,
        categories={
            category_name: counts[category_name] for category_name in category_names
        },
        total=len(rows),
    )


def bootstrap_catalog(
    connectors: Sequence[ConnectorDefinition],
) -> list[dict[str, object]]:
    return [
        {
            "connectorKey": definition.connector_key,
            "category": definition.category,
            "name": definition.name,
            "desc": definition.description,
            "capabilities": definition.capabilities,
            # Keep the complete server-owned form contract.  The browser needs
            # required/default/options/description and secret-reference
            # metadata to render a truthful configuration flow.
            "inputSchema": definition.input_schema.model_dump(
                mode="json", by_alias=True
            ),
            "credentialSchema": definition.credential_schema.model_dump(
                mode="json", by_alias=True
            ),
            "discoveryPipeline": definition.discovery_modes,
            "syncModes": definition.sync_modes,
            "capabilityState": definition.capability_state,
            "reason": definition.reason.model_dump(mode="json", by_alias=True),
            "permissions": definition.permissions.model_dump(
                mode="json", by_alias=True
            ),
        }
        for raw_definition in connectors
        for definition in [_public_definition(raw_definition)]
    ]
