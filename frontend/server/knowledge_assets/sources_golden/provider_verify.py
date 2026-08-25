"""Run a credential-backed connector verification through the formal adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from .application import SourceGoldenApplication
from .connector_adapter import ConnectorAdapterError, ConnectorRequest
from .connector_registry import EXTERNAL_PROVIDER_KEYS

_CONFIGURATION_ENV = "STEP3B_CONNECTOR_CONFIGURATION_JSON"
_SECRET_ENV = "STEP3B_CONNECTOR_SECRET_JSON"


_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def _json_object(name: str) -> dict[str, JsonValue]:
    raw = os.environ.get(name)
    if not raw:
        raise ValueError(f"{name} is required")
    value: JsonValue = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return _JSON_OBJECT.validate_python(value)


def verify(connector_key: str) -> dict[str, object]:
    """Validate credentials and perform real provider discovery."""
    if connector_key not in EXTERNAL_PROVIDER_KEYS:
        raise ValueError(f"{connector_key} is not an external provider connector")
    configuration = _json_object(_CONFIGURATION_ENV)
    secret = json.dumps(_json_object(_SECRET_ENV))
    with tempfile.TemporaryDirectory(prefix="step3b-provider-verify-") as directory:
        root = Path(directory)
        application = SourceGoldenApplication(
            database_path=root / "sources-golden.sqlite3",
            artifact_root=root / "artifacts",
            source_root=root / "uploads",
            secret_resolver=lambda _reference: secret,
        )
        adapter = application.connector_adapters()[connector_key]
        request = ConnectorRequest(
            connector_key=connector_key,
            workspace_id="provider-verification",
            principal_id="provider-verification",
            configuration=configuration,
            secret_ref="secret://provider-verification/credential",
            trace_id=f"provider-verification-{uuid.uuid4()}",
        )
        validation = adapter.validate(request)
        authentication = adapter.authenticate(request)
        authorization = adapter.authorize(request)
        discovery = adapter.discover(request)
        return {
            "connectorKey": connector_key,
            "status": "passed",
            "stages": {
                "validate": validation.status,
                "authenticate": authentication.status,
                "authorize": authorization.status,
                "discover": discovery.status,
            },
            "resourceCount": len(discovery.resources),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one external connector with its formal adapter. Set "
            f"{_CONFIGURATION_ENV} and {_SECRET_ENV} to JSON objects."
        )
    )
    parser.add_argument("connector_key", choices=sorted(EXTERNAL_PROVIDER_KEYS))
    arguments = parser.parse_args()
    try:
        result = verify(arguments.connector_key)
    except ConnectorAdapterError as error:
        print(
            json.dumps(
                {
                    "connectorKey": arguments.connector_key,
                    "status": "failed",
                    "code": error.code,
                    "stage": error.stage,
                    "message": error.message,
                    "retryable": error.retryable,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "connectorKey": arguments.connector_key,
                    "status": "failed",
                    "code": "VERIFICATION_CONFIGURATION_INVALID",
                    "stage": "validate",
                    "message": str(error),
                    "retryable": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
