# STEP 2B Connection Service Contract

The Knowledge BFF calls the independent Connection Service over an
authenticated server-to-server URL. Studio browser code never calls this
service or OpenConnector's `/api` management routes.

## Identity

The BFF obtains a signed `TenantPrincipal` from the platform identity layer
and sends it as an opaque bearer token. The service derives
`tenant_id`, `workspace_id`, `subject`, `owner_id`, and `audience` from that
token; request JSON is not authoritative for those fields.

## Control API

Base URL: `CONNECTION_SERVICE_BASE_URL`

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v1/catalog` | enabled catalog/beta/verified definitions only |
| GET | `/v1/connections` | tenant/workspace-scoped safe profiles |
| POST | `/v1/connections` | create and validate an encrypted connection |
| POST | `/v1/connections/{id}/lease` | issue explicit short-lived lease |
| POST | `/v1/leases/{jti}/revoke` | revoke a lease |
| POST | `/v1/runtime/actions/{action_id}` | execute through a lease |

Connection profiles never contain passwords, API keys, cookies, OAuth access or
refresh tokens, MCP headers, or credential values. Execution audit is
redacted before persistence and returned only to the owning tenant/workspace.

## Lease invariant

Every lease must contain non-empty `connection_ids` and `allowed_actions` and
bind:

`subject + invocation_id + tenant_id + workspace_id + audience + expiry + jti`

The token is presented in `X-Connection-Lease`; only its SHA-256 hash is
stored. An empty allowed-connection list never means unrestricted access.

## Deployment

```text
CONNECTION_SERVICE_BASE_URL=https://connection-service.internal
CONNECTION_SERVICE_AUTH_SECRET=<platform-issued signing secret>
CONNECTION_SERVICE_ENCRYPTION_KEY=<secret-store key>
```

Customer private-network connections must run in a tenant/security-domain
runner pool with an explicit egress allowlist. Shared public runtime remains
SSRF fail-closed. Connection pools and long-lived MCP/VPC workers are
residents; veFaaS is limited to stateless control/execution functions.

This contract records the service boundary only. It does not claim that the
catalog provider directory is verified or that a connector is end-to-end
ready.
