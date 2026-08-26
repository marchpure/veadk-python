from __future__ import annotations

import pytest

from frontend.server.knowledge_assets.connector_contracts import (
    connector_config_schema,
    validate_kind_config,
)
from frontend.server.knowledge_assets.sources_golden.catalog import BUILTIN_CONNECTORS


def test_available_catalog_reason_describes_formal_adapter_lifecycle() -> None:
    available = [
        definition
        for definition in BUILTIN_CONNECTORS
        if definition.capability_state == "available"
    ]

    assert len(available) == 37
    for definition in available:
        assert (
            definition.reason.message
            == "This connector has a formal adapter and durable lifecycle."
        )


def test_each_catalog_connector_has_an_independent_discriminated_config_contract() -> (
    None
):
    schema = connector_config_schema()
    discriminator = schema["discriminator"]
    assert isinstance(discriminator, dict)
    mapping = discriminator["mapping"]
    assert isinstance(mapping, dict)
    catalog = {
        definition.connector_key: definition for definition in BUILTIN_CONNECTORS
    }

    assert set(mapping) == set(catalog)
    assert len(set(mapping.values())) == 37
    for connector_key, definition in catalog.items():
        values: dict[str, object] = {"kind": connector_key}
        for name, field in definition.input_schema.properties.items():
            if not field.required:
                continue
            samples: dict[str, object] = {
                "string": "value",
                "file": "source.dat",
                "url": "https://example.com/data",
                "integer": 1,
                "number": 1.0,
                "boolean": True,
                "string_array": ["value"],
                "object": {},
            }
            values[name] = (
                field.options[0] if field.type == "select" else samples[field.type]
            )
        if definition.credential_schema.required:
            values["secretRef"] = {
                "uri": f"secret://workspace/{connector_key}",
                "version": "v1",
            }

        parsed = validate_kind_config(values)

        assert parsed.kind == connector_key
        with pytest.raises(ValueError):
            validate_kind_config({**values, "foreignConnectorField": "forbidden"})
