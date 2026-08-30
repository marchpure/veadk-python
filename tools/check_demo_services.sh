#!/usr/bin/env bash
set -euo pipefail

readonly compose_file="${1:-demo-services/docker-compose.yml}"
export KNOWLEDGE_DEMO_POSTGRES_PORT="${KNOWLEDGE_DEMO_POSTGRES_PORT:-15432}"
export KNOWLEDGE_DEMO_WEB_PORT="${KNOWLEDGE_DEMO_WEB_PORT:-18081}"
export KNOWLEDGE_DEMO_FORM_PORT="${KNOWLEDGE_DEMO_FORM_PORT:-18082}"
export KNOWLEDGE_DEMO_MCP_PORT="${KNOWLEDGE_DEMO_MCP_PORT:-18083}"
docker compose -f "${compose_file}" up -d
docker compose -f "${compose_file}" ps
for url in \
  "http://127.0.0.1:${KNOWLEDGE_DEMO_WEB_PORT}/healthz" \
  "http://127.0.0.1:${KNOWLEDGE_DEMO_FORM_PORT}/healthz" \
  "http://127.0.0.1:${KNOWLEDGE_DEMO_MCP_PORT}/healthz"; do
  curl --fail --silent --show-error "${url}" >/dev/null
done
echo "DEMO_LOCAL_SERVICES_HEALTHY"
