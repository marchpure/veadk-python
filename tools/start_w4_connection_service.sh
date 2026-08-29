#!/usr/bin/env bash
set -euo pipefail

# Start an isolated W4 Connection Service from the frozen W0 implementation.
# Secrets are read into the child process environment and never written here.
readonly repo="${W4_CONNECTION_SERVICE_REPO:-/Users/bytedance/.codex/worktrees/kp-rerun-20260829-w0-connection}"
readonly expected_sha="b51379c0e1c515fb6811a3be7b0a79d0cc506a80"
readonly evidence_root="${W4_EVIDENCE_ROOT:-/tmp/kp-rerun-20260829/w4-live-final}"
readonly runtime_dir="${W4_CONNECTION_SERVICE_RUNTIME_DIR:-${evidence_root}/connection-service-runtime}"
readonly frozen_dir="${W4_FROZEN_CONNECTION_DIR:-/tmp/kp-rerun-20260829/w0-corrective-runtime/connection-service}"
readonly frozen_env="${W4_FROZEN_CONNECTION_ENV:-/tmp/kp-rerun-20260829/w0-corrective-runtime/connection.env}"
readonly port="${W4_CONNECTION_SERVICE_PORT:-38142}"
readonly egress_allowlist="${CONNECTION_DATABASE_EGRESS_ALLOWLIST:-${W4_POSTGRES_HOST:?W4_POSTGRES_HOST is required}}"

cd "${repo}"
actual_sha="$(git rev-parse HEAD)"
if [[ "${actual_sha}" != "${expected_sha}" ]]; then
  printf 'W4_CONNECTION_SERVICE_SHA_MISMATCH expected=%s actual=%s\n' \
    "${expected_sha}" "${actual_sha}" >&2
  exit 1
fi
mkdir -p "${runtime_dir}"
if [[ ! -f "${runtime_dir}/control.sqlite" ]]; then
  cp "${frozen_dir}/control.sqlite" "${runtime_dir}/control.sqlite"
fi

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
