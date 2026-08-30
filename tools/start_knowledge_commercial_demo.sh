#!/usr/bin/env bash
set -euo pipefail

readonly repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly runtime_dir="${KNOWLEDGE_DEMO_RUNTIME_DIR:-/tmp/veadk-knowledge-commercial-demo}"
readonly connection_repo="${KNOWLEDGE_DEMO_CONNECTION_REPO:-/Users/bytedance/.codex/worktrees/knowledge-final-connection-service}"
readonly autoskill_repo="${KNOWLEDGE_DEMO_AUTOSKILL_REPO:-/Users/bytedance/.codex/worktrees/kp-current-preview-autoskill/backend}"
readonly studio_port="${KNOWLEDGE_DEMO_STUDIO_PORT:-8000}"
readonly frontend_port="${KNOWLEDGE_DEMO_FRONTEND_PORT:-5173}"
readonly connection_port="${KNOWLEDGE_DEMO_CONNECTION_PORT:-38200}"
readonly autoskill_port="${KNOWLEDGE_DEMO_AUTOSKILL_PORT:-38202}"
readonly postgres_port="${KNOWLEDGE_DEMO_POSTGRES_PORT:-25432}"
readonly web_port="${KNOWLEDGE_DEMO_WEB_PORT:-18081}"
readonly form_port="${KNOWLEDGE_DEMO_FORM_PORT:-18082}"
readonly mcp_port="${KNOWLEDGE_DEMO_MCP_PORT:-18083}"
readonly ngrok_inspection_port="${KNOWLEDGE_DEMO_NGROK_INSPECTION_PORT:-4041}"
readonly runtime_public_url="${KNOWLEDGE_DEMO_RUNTIME_PUBLIC_URL:-https://annelle-figured-intimately.ngrok-free.dev}"
readonly connection_secret="${KNOWLEDGE_DEMO_CONNECTION_SECRET:-knowledge-commercial-demo-local}"
readonly connection_encryption_key="${KNOWLEDGE_DEMO_CONNECTION_ENCRYPTION_KEY:-$(openssl rand -hex 32)}"
readonly python_bin="${KNOWLEDGE_DEMO_PYTHON:-python}"
readonly postgres_host="${KNOWLEDGE_DEMO_POSTGRES_HOST:-$(
  route -n get default | awk '/interface:/{print $2; exit}' | xargs ipconfig getifaddr
)}"

mkdir -p "${runtime_dir}/logs" "${runtime_dir}/connection-data" \
  "${runtime_dir}/workspace-objects"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  }
}

check_port() {
  local port="$1"
  local label="$2"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'Port %s is already in use (%s); refusing to stop another session.\n' \
      "${port}" "${label}" >&2
    exit 2
  fi
}

wait_url() {
  local url="$1"
  local label="$2"
  for _ in $(seq 1 90); do
    if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  printf '%s did not become ready: %s\n' "${label}" "${url}" >&2
  exit 3
}

for command in curl docker lsof ngrok npm openssl "${python_bin}"; do
  require_command "${command}"
done
for entry in \
  "${studio_port}:Studio BFF" \
  "${frontend_port}:Vite frontend" \
  "${connection_port}:Connection Service" \
  "${autoskill_port}:AutoSkill" \
  "${postgres_port}:demo PostgreSQL" \
  "${web_port}:demo Web Action" \
  "${form_port}:demo Form API" \
  "${mcp_port}:demo MCP" \
  "${ngrok_inspection_port}:ngrok inspection"; do
  check_port "${entry%%:*}" "${entry#*:}"
done

children=()
cleanup() {
  for pid in "${children[@]:-}"; do
    kill "${pid}" >/dev/null 2>&1 || true
  done
  wait "${children[@]:-}" >/dev/null 2>&1 || true
  (
    cd "${repo_root}"
    KNOWLEDGE_DEMO_POSTGRES_PORT="${postgres_port}" \
    KNOWLEDGE_DEMO_WEB_PORT="${web_port}" \
    KNOWLEDGE_DEMO_FORM_PORT="${form_port}" \
    KNOWLEDGE_DEMO_MCP_PORT="${mcp_port}" \
      docker compose -f demo-services/docker-compose.yml down
  ) >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

(
  cd "${repo_root}"
  KNOWLEDGE_DEMO_POSTGRES_PORT="${postgres_port}" \
  KNOWLEDGE_DEMO_WEB_PORT="${web_port}" \
  KNOWLEDGE_DEMO_FORM_PORT="${form_port}" \
  KNOWLEDGE_DEMO_MCP_PORT="${mcp_port}" \
    docker compose -f demo-services/docker-compose.yml up -d
)

ngrok http "${connection_port}" \
  --url "${runtime_public_url}" \
  --web-addr "127.0.0.1:${ngrok_inspection_port}" \
  --log "${runtime_dir}/logs/ngrok.log" &
children+=("$!")

(
  cd "${connection_repo}"
  CONNECTION_SERVICE_HOST=127.0.0.1 \
  CONNECTION_SERVICE_PORT="${connection_port}" \
  CONNECTION_SERVICE_PUBLIC_ORIGIN="${runtime_public_url}" \
  CONNECTION_SERVICE_DATA_DIR="${runtime_dir}/connection-data" \
  CONNECTION_SERVICE_AUTH_SECRET="${connection_secret}" \
  CONNECTION_SERVICE_ENCRYPTION_KEY="${connection_encryption_key}" \
  CONNECTION_DATABASE_EGRESS_ALLOWLIST="${postgres_host}" \
  OOMOL_CONNECT_ALLOW_PRIVATE_NETWORK=true \
    npm run start:connection-service
) >"${runtime_dir}/logs/connection-service.log" 2>&1 &
children+=("$!")

(
  cd "${autoskill_repo}"
  PORT="${autoskill_port}" \
  AUTOSKILL_STATE_MODE=stateless \
  AGENT_CONFIG="${KNOWLEDGE_DEMO_AUTOSKILL_CONFIG:-${autoskill_repo}/config.yaml}" \
    ./start_backend.sh
) >"${runtime_dir}/logs/autoskill.log" 2>&1 &
children+=("$!")

if [[ -n "${KNOWLEDGE_DEMO_OPENVIKING_COMMAND:-}" ]]; then
  (
    cd "${repo_root}"
    bash -lc "${KNOWLEDGE_DEMO_OPENVIKING_COMMAND}"
  ) >"${runtime_dir}/logs/openviking.log" 2>&1 &
  children+=("$!")
fi

(
  cd "${repo_root}"
  KNOWLEDGE_DEMO_ENABLED=true \
  KNOWLEDGE_DEMO_SEED_VERSION="${KNOWLEDGE_DEMO_SEED_VERSION:-w5-v1}" \
  KNOWLEDGE_DEMO_STATE_DB="${runtime_dir}/demo.sqlite3" \
  KNOWLEDGE_DEMO_POSTGRES_HOST="${postgres_host}" \
  KNOWLEDGE_DEMO_POSTGRES_PORT="${postgres_port}" \
  KNOWLEDGE_DEMO_POSTGRES_DATABASE=demo \
  KNOWLEDGE_DEMO_POSTGRES_USER=demo \
  KNOWLEDGE_DEMO_POSTGRES_PASSWORD=demo-local-only \
  KNOWLEDGE_CONNECTION_SERVICE_BASE_URL="http://127.0.0.1:${connection_port}" \
  KNOWLEDGE_CONNECTION_SERVICE_RUNTIME_PUBLIC_URL="${runtime_public_url}" \
  KNOWLEDGE_CONNECTION_SERVICE_AUTH_SECRET="${connection_secret}" \
  KNOWLEDGE_AUTOSKILL_BASE_URL="http://[::1]:${autoskill_port}" \
  KNOWLEDGE_AUTOSKILL_STATE_MODE=stateless \
  KNOWLEDGE_WORKSPACE_DATABASE="${runtime_dir}/workspace.sqlite3" \
  KNOWLEDGE_WORKSPACE_OBJECT_ROOT="${runtime_dir}/workspace-objects" \
    "${python_bin}" -m veadk.cli.cli studio \
      --agents-dir examples/basic-app/agents \
      --frontend-dir veadk/webui \
      --host 127.0.0.1 \
      --port "${studio_port}" \
      --dev --vite --no-open
) >"${runtime_dir}/logs/studio.log" 2>&1 &
children+=("$!")

(
  cd "${repo_root}/frontend"
  VEADK_API_TARGET="http://127.0.0.1:${studio_port}" \
    npm run dev -- --host 127.0.0.1 --port "${frontend_port}"
) >"${runtime_dir}/logs/frontend.log" 2>&1 &
children+=("$!")

wait_url "http://127.0.0.1:${connection_port}/health" "Connection Service"
wait_url "http://[::1]:${autoskill_port}/openapi/autoskill/v1/health" "AutoSkill"
wait_url "http://127.0.0.1:${web_port}/healthz" "demo Web Action"
wait_url "http://127.0.0.1:${form_port}/healthz" "demo Form API"
wait_url "http://127.0.0.1:${mcp_port}/healthz" "demo MCP"
wait_url "http://127.0.0.1:${studio_port}/web/auth-config" "Studio BFF"
wait_url "http://127.0.0.1:${frontend_port}" "Vite frontend"

printf 'Knowledge Commercial Demo is ready.\n'
printf 'Studio UI: http://127.0.0.1:%s/?view=knowledge-workspace\n' "${frontend_port}"
printf 'Studio BFF: http://127.0.0.1:%s\n' "${studio_port}"
printf 'Connection runtime: %s\n' "${runtime_public_url}"
printf 'Logs: %s/logs\n' "${runtime_dir}"
printf 'Seed: curl -X POST -H "X-VeADK-Local-User: tester" http://127.0.0.1:%s/api/knowledge/v1/demo/seed\n' "${studio_port}"
wait
