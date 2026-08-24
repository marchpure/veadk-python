"""Export the canonical Pydantic contracts for review and code generation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from .contracts import (
    BootstrapResponse,
    CommandRequest,
    CommandResponse,
    ErrorEnvelope,
    OperationEvent,
    OperationAuditResponse,
    OperationResponse,
)


def export_schemas(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    schemas = {
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


if __name__ == "__main__":
    export_schemas(Path(__file__).with_name("contracts"))
