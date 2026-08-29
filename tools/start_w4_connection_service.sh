#!/usr/bin/env bash
set -euo pipefail

# Start an isolated W4 Connection Service from the frozen W0 data snapshot.
# Secrets are read into the child process environment and never written here.
readonly repo="/Users/bytedance/agentkit-connectors-poc/open-connector"
readonly evidence_root="/tmp/kp-rerun-20260829/w4-live-corrective"
readonly runtime_dir="${evidence_root}/connection-service-runtime"
readonly frozen_dir="/tmp/kp-rerun-20260829/w0-corrective-runtime/connection-service"
readonly frozen_env="/tmp/kp-rerun-20260829/w0-corrective-runtime/connection.env"
readonly port="${W4_CONNECTION_SERVICE_PORT:-38142}"

cd "${repo}"
mkdir -p "${runtime_dir}"
if [[ ! -f "${runtime_dir}/control.sqlite" ]]; then
  cp "${frozen_dir}/control.sqlite" "${runtime_dir}/control.sqlite"
fi

readonly egress_allowlist="${CONNECTION_DATABASE_EGRESS_ALLOWLIST:-$(python - <<'PY'
import json
import sqlite3

database = "/tmp/kp-rerun-20260829/w4-live-corrective/connection-service-runtime/control.sqlite"
with sqlite3.connect(database) as connection:
    row = connection.execute(
        "select profile_json from tenant_connections where service = 'postgresql' limit 1"
    ).fetchone()
profile = json.loads(row[0]) if row else {}
account_id = str(profile.get("accountId") or "")
parts = account_id.split(":")
print(parts[1] if len(parts) > 1 and parts[1] else "")
PY
)}"

set -a
source "${frozen_env}"
set +a
export CONNECTION_SERVICE_PORT="${port}"
export CONNECTION_SERVICE_HOST="${CONNECTION_SERVICE_HOST:-127.0.0.1}"
export CONNECTION_SERVICE_DATA_DIR="${runtime_dir}"
export CONNECTION_SERVICE_PUBLIC_ORIGIN="${CONNECTION_SERVICE_PUBLIC_ORIGIN:-https://independent-runtime.invalid}"
export OOMOL_CONNECT_ALLOW_PRIVATE_NETWORK="${OOMOL_CONNECT_ALLOW_PRIVATE_NETWORK:-true}"
export CONNECTION_DATABASE_EGRESS_ALLOWLIST="${egress_allowlist}"
exec npm run start:connection-service
