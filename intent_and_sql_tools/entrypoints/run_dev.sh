#!/bin/bash

set -e

export PYTHONPATH="$(pwd)"

if [ -z "${INTENT_SLOT_CATALOG_PATH:-}" ]; then
  export INTENT_SLOT_CATALOG_PATH="$(pwd)/intent_and_sql_tools/intent_tool/nl2json_pipeline/artifacts/slot_catalog.json"
fi

python3 -m uvicorn intent_and_sql_tools.entrypoints.intent_api:app --host 0.0.0.0 --port "${PORT:-8000}"
