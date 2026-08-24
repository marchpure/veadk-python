"""Export the canonical Pydantic contracts for review and code generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .contracts import (
    BootstrapResponse,
    CoreContractBundle,
    CommandRequest,
    CommandResponse,
    ErrorEnvelope,
    OperationEvent,
    OperationAuditResponse,
    OperationResponse,
)


def _ts_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(item) for item in schema["enum"])
    if "anyOf" in schema or "oneOf" in schema:
        key = "anyOf" if "anyOf" in schema else "oneOf"
        parts = [_ts_type(item) for item in schema[key]]
        return " | ".join(dict.fromkeys(parts))
    schema_type = schema.get("type")
    if schema_type == "array":
        prefix_items = schema.get("prefixItems")
        if prefix_items:
            return "[" + ", ".join(_ts_type(item) for item in prefix_items) + "]"
        return f"Array<{_ts_type(schema.get('items', {}))}>"
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        rows = []
        for name, value in properties.items():
            optional = "" if name in required else "?"
            rows.append(f"  {name}{optional}: {_ts_type(value)};")
        if rows:
            return "{\n" + "\n".join(rows) + "\n}"
        if "additionalProperties" in schema:
            additional = schema["additionalProperties"]
            if isinstance(additional, dict):
                return f"Record<string, {_ts_type(additional)}>"
            return "Record<string, unknown>"
        return "Record<string, never>"
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(schema_type, "unknown")


def _render_typescript(schema: dict[str, Any]) -> str:
    lines = [
        "/* Generated from contracts.py; do not edit manually. */",
        "",
    ]
    for name, definition in schema.get("$defs", {}).items():
        if "enum" in definition or "oneOf" in definition or "anyOf" in definition:
            lines.append(f"export type {name} = {_ts_type(definition)};")
        else:
            lines.append(f"export interface {name} {_ts_type(definition)}")
        lines.append("")
    if schema.get("title") == "CoreContractBundle":
        lines.append("export interface CoreContractBundle {")
        for name, value in schema.get("properties", {}).items():
            optional = "" if name in schema.get("required", []) else "?"
            lines.append(f"  {name}{optional}: {_ts_type(value)};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def export_schemas(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    schemas = {
        "core-contracts.schema.json": CoreContractBundle.model_json_schema(
            by_alias=True, ref_template="#/$defs/{model}"
        ),
        "bootstrap.schema.json": BootstrapResponse.model_json_schema(
            by_alias=True, ref_template="#/$defs/{model}"
        ),
        "command-registry.schema.json": {
            "commandRequest": TypeAdapter(CommandRequest).json_schema(),
            "commandResponse": CommandResponse.model_json_schema(
                by_alias=True, ref_template="#/$defs/{model}"
            ),
        },
        "operation.schema.json": OperationResponse.model_json_schema(
            by_alias=True, ref_template="#/$defs/{model}"
        ),
        "audit.schema.json": OperationAuditResponse.model_json_schema(
            by_alias=True, ref_template="#/$defs/{model}"
        ),
        "event.schema.json": OperationEvent.model_json_schema(
            by_alias=True, ref_template="#/$defs/{model}"
        ),
        "error.schema.json": ErrorEnvelope.model_json_schema(
            by_alias=True, ref_template="#/$defs/{model}"
        ),
    }
    for filename, schema in schemas.items():
        (output / filename).write_text(
            json.dumps(schema, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    core_schema = schemas["core-contracts.schema.json"]
    (output.parent.parent.parent / "src/knowledge-workspace/production/generatedContracts.ts").write_text(
        _render_typescript(core_schema),
        encoding="utf-8",
    )


if __name__ == "__main__":
    export_schemas(Path(__file__).with_name("contracts"))
