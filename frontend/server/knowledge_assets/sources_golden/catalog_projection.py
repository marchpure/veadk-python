"""Read-model projections for the immutable connector catalog."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from .models import (
    ConnectorCatalogView,
    ConnectorCategory,
    ConnectorDefinition,
    FormField,
    FormSchema,
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
    if definition.connector_key != "mcp_custom":
        return definition
    return definition.model_copy(
        update={
            "input_schema": _MCP_BROWSER_SCHEMA,
            "credential_schema": FormSchema(properties={}),
        }
    )


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
    field_types = {
        "integer": "number",
        "url": "string",
        "string_array": "string",
    }
    return [
        {
            "connectorKey": definition.connector_key,
            "category": definition.category,
            "name": definition.name,
            "desc": definition.description,
            "capabilities": definition.capabilities,
            "inputSchema": {
                key: field_types.get(field.type, field.type)
                for key, field in definition.input_schema.properties.items()
            },
            "credentialSchema": (
                {
                    key: ("secret_ref" if field.secret_reference else field.type)
                    for key, field in definition.credential_schema.properties.items()
                }
                or None
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
