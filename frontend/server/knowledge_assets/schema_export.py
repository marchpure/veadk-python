"""Export the canonical Pydantic contracts for review and code generation."""

from __future__ import annotations

import json
import re
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


def _render_typescript(schema: dict[str, Any], names: list[str] | None = None) -> str:
    lines = [
        "/* Generated from contracts.py; do not edit manually. */",
        "",
    ]
    definitions = schema.get("$defs", {})
    selected = names or list(definitions)
    for name in selected:
        definition = definitions[name]
        rendered_type = _ts_type(definition)
        if (
            "enum" in definition
            or "oneOf" in definition
            or "anyOf" in definition
            or rendered_type == "unknown"
        ):
            lines.append(f"export type {name} = {rendered_type};")
        else:
            lines.append(f"export interface {name} {rendered_type}")
        # Keep the generated contract facade reviewable as one module while
        # avoiding artificial blank-line growth as the canonical model grows.
        if name != selected[-1]:
            lines.append("")
    if schema.get("title") == "CoreContractBundle" and (
        names is None or "CoreContractBundle" in selected
    ):
        lines.append("export interface CoreContractBundle {")
        for name, value in schema.get("properties", {}).items():
            optional = "" if name in schema.get("required", []) else "?"
            lines.append(f"  {name}{optional}: {_ts_type(value)};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def _render_part(
    schema: dict[str, Any],
    names: list[str],
    module_name: str,
    module_names: list[str],
    chunks: list[list[str]],
) -> str:
    all_names = list(schema.get("$defs", {}))
    rendered = _render_typescript(schema, names)
    referenced = {
        name
        for name in all_names
        if name not in names and re.search(rf"\b{name}\b", rendered)
    }
    imports = []
    for other_module_name, chunk in zip(module_names, chunks, strict=True):
        if other_module_name == module_name:
            continue
        module_references = sorted(referenced.intersection(chunk))
        if module_references:
            imports.append(
                f"import type {{ {', '.join(module_references)} }} "
                f'from "./{other_module_name}";'
            )
    return (
        "/* Generated from contracts.py; do not edit manually. */\n\n"
        + "\n".join(imports)
        + ("\n\n" if imports else "")
        + rendered.split("\n\n", 1)[-1]
    )


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
    generated_root = output.parent.parent.parent / "src/knowledge-workspace/production"
    generated_dir = generated_root / "generatedContracts"
    generated_dir.mkdir(parents=True, exist_ok=True)
    names = list(core_schema.get("$defs", {}))
    chunk_size = max(1, (len(names) + 3) // 4)
    chunks = [
        names[index : index + chunk_size] for index in range(0, len(names), chunk_size)
    ]
    module_names = [f"part{index}" for index in range(1, len(chunks) + 1)]
    for module_name, chunk in zip(module_names, chunks, strict=True):
        (generated_dir / f"{module_name}.ts").write_text(
            _render_part(core_schema, chunk, module_name, module_names, chunks),
            encoding="utf-8",
        )
    bundle_lines = [
        "/* Generated from contracts.py; do not edit manually. */",
        "",
    ]
    for module_name, chunk in zip(module_names, chunks, strict=True):
        bundle_lines.append(
            f'import type {{ {", ".join(chunk)} }} from "./{module_name}";'
        )
    bundle_lines.extend(["", "export interface CoreContractBundle {"])
    for name, value in core_schema.get("properties", {}).items():
        optional = "" if name in core_schema.get("required", []) else "?"
        bundle_lines.append(f"  {name}{optional}: {_ts_type(value)};")
    bundle_lines.extend(["}", ""])
    (generated_dir / "bundle.ts").write_text("\n".join(bundle_lines), encoding="utf-8")
    (generated_root / "generatedContracts.ts").write_text(
        "/* Generated from contracts.py; do not edit manually. */\n\n"
        + "\n".join(
            f'export * from "./generatedContracts/{module_name}";'
            for module_name in [*module_names, "bundle"]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    export_schemas(Path(__file__).with_name("contracts"))
