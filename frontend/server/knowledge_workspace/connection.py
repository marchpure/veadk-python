"""Server-only Connection Service gateway owned by the BFF boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlencode, urlsplit

import httpx

from pydantic import BaseModel, ConfigDict, Field


class ConnectionServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class EphemeralConnectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: str = Field(min_length=1, max_length=4_096)
    connection_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    allowed_actions: tuple[str, ...] = Field(min_length=1, max_length=128)
    expires_at: datetime
    runtime_ref: str = Field(min_length=1, max_length=32_768)


class ConnectionInvocationContextPort(Protocol):
    async def issue(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        principal_id: str,
        invocation_id: str,
        connection_ids: Sequence[str],
        allowed_actions: Sequence[str],
        ttl_seconds: int,
    ) -> EphemeralConnectionContext:
        """Issue a short-lived, invocation-bound least-privilege context."""

    async def revoke(self, lease_id: str) -> None:
        """Revoke the context at invocation termination."""

    async def prepare_autoskill(
        self,
        *,
        context: EphemeralConnectionContext,
        autoskill: Any,
        agent_id: str,
        session_id: str,
        invocation_id: str,
    ) -> None:
        """Attach the lease-scoped runtime tools before invoking AutoSkill."""


@dataclass(frozen=True)
class ConnectionServiceConfig:
    base_url: str
    auth_secret: str
    audience: str = "knowledge-runtime"
    runtime_public_url: str | None = None
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "ConnectionServiceConfig":
        base_url = os.getenv("KNOWLEDGE_CONNECTION_SERVICE_BASE_URL", "").rstrip("/")
        auth_secret = os.getenv("KNOWLEDGE_CONNECTION_SERVICE_AUTH_SECRET", "")
        if not base_url or not auth_secret:
            raise ConnectionServiceError(
                "CONNECTION_SERVICE_UNAVAILABLE",
                "Connection Service is not configured",
                503,
            )
        return cls(
            base_url=base_url,
            auth_secret=auth_secret,
            audience=os.getenv(
                "KNOWLEDGE_CONNECTION_SERVICE_AUDIENCE",
                "knowledge-runtime",
            ),
            runtime_public_url=(
                os.getenv("KNOWLEDGE_CONNECTION_SERVICE_RUNTIME_PUBLIC_URL", "")
                .rstrip("/")
                or base_url
            ),
        )


class ConnectionServiceGateway:
    """Tenant-scoped HTTP gateway and invocation lease adapter.

    Principal tokens are generated from the already authenticated BFF actor.
    Browser identity headers and provider credentials never become authority.
    """

    def __init__(
        self,
        config: ConnectionServiceConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(config.base_url)
        hostname = (parsed.hostname or "").casefold()
        if (
            (
                parsed.scheme != "https"
                and not (
                    parsed.scheme == "http"
                    and hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
            or not hostname
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Connection Service base URL must be HTTPS or loopback HTTP"
            )
        self.config = config
        self._client = client

    @staticmethod
    def _b64url(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    def _token(self, tenant_id: str, workspace_id: str, principal_id: str) -> str:
        payload = self._b64url(
            json.dumps(
                {
                    "tenantId": tenant_id,
                    "workspaceId": workspace_id,
                    "subject": principal_id,
                    "audience": self.config.audience,
                    "ownerId": principal_id,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signature = self._b64url(
            hmac.new(
                self.config.auth_secret.encode("utf-8"),
                payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"cp1.{payload}.{signature}"

    def _lease_reference(
        self,
        tenant_id: str,
        workspace_id: str,
        principal_id: str,
        lease_ids: Sequence[str],
    ) -> str:
        payload = self._b64url(
            json.dumps(
                {
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "principal_id": principal_id,
                    "lease_ids": list(lease_ids),
                },
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signature = self._b64url(
            hmac.new(
                self.config.auth_secret.encode("utf-8"),
                f"knowledge-lease:{payload}".encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"kl1.{payload}.{signature}"

    def _read_lease_reference(
        self, value: str
    ) -> tuple[tuple[str, str, str], tuple[str, ...]]:
        try:
            prefix, payload, signature = value.split(".", 2)
            expected = self._b64url(
                hmac.new(
                    self.config.auth_secret.encode("utf-8"),
                    f"knowledge-lease:{payload}".encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if prefix != "kl1" or not hmac.compare_digest(signature, expected):
                raise ValueError
            decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            parsed = json.loads(decoded)
            actor = (
                str(parsed["tenant_id"]),
                str(parsed["workspace_id"]),
                str(parsed["principal_id"]),
            )
            lease_ids = tuple(str(item) for item in parsed["lease_ids"])
            if not all(actor) or not lease_ids or not all(lease_ids):
                raise ValueError
            return actor, lease_ids
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionServiceError(
                "INVALID_LEASE_REFERENCE",
                "Connection lease reference is invalid",
                400,
            ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        tenant_id: str,
        workspace_id: str,
        principal_id: str,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer " + self._token(
            tenant_id, workspace_id, principal_id
        )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.config.timeout_seconds)
        try:
            response = await client.request(
                method,
                f"{self.config.base_url}{path}",
                headers=headers,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise ConnectionServiceError(
                "CONNECTION_SERVICE_UNAVAILABLE",
                f"Connection Service request failed: {type(exc).__name__}",
                503,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code >= 400:
            code = "CONNECTION_SERVICE_ERROR"
            message = f"Connection Service returned HTTP {response.status_code}"
            try:
                error = response.json().get("error", {})
                if isinstance(error, Mapping):
                    code = str(error.get("code") or code).upper()
                    message = str(error.get("message") or message)
            except (ValueError, AttributeError):
                pass
            raise ConnectionServiceError(code, message, response.status_code)
        return response

    async def catalog(self, **actor: str) -> list[dict[str, Any]]:
        payload = (await self._request("GET", "/v1/catalog", **actor)).json()
        items = payload.get("items", [])
        return [self._catalog_item(item) for item in items if isinstance(item, Mapping)]

    async def adapter_capabilities(self, **actor: str) -> list[dict[str, Any]]:
        payload = (await self._request("GET", "/v1/adapters/capabilities", **actor)).json()
        items = payload.get("items", [])
        return [
            self._adapter_item(item)
            for item in items
            if isinstance(item, Mapping)
        ]

    async def validate_rest(
        self, body: Mapping[str, Any], **actor: str
    ) -> dict[str, Any]:
        response = await self._request(
            "POST", "/v1/adapters/rest/validate", json=dict(body), **actor
        )
        return dict(response.json().get("result", {}))

    async def validate_oracle(
        self, body: Mapping[str, Any], **actor: str
    ) -> dict[str, Any]:
        response = await self._request(
            "POST", "/v1/adapters/oracle/validate", json=dict(body), **actor
        )
        return dict(response.json().get("result", {}))

    async def discover_oracle(
        self, body: Mapping[str, Any], **actor: str
    ) -> dict[str, Any]:
        response = await self._request(
            "POST", "/v1/adapters/oracle/discover", json=dict(body), **actor
        )
        return dict(response.json().get("result", {}))

    async def discover_mcp(
        self, definition: Mapping[str, Any], **actor: str
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/v1/adapters/mcp/discover",
            json={"definition": dict(definition)},
            **actor,
        )
        return dict(response.json())

    async def register_mcp(
        self, definition: Mapping[str, Any], **actor: str
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/v1/adapters/mcp/definitions",
            json={"definition": dict(definition)},
            **actor,
        )
        return dict(response.json().get("definition", {}))

    async def list_files(self, **actor: str) -> list[dict[str, Any]]:
        payload = (await self._request("GET", "/v1/files", **actor)).json()
        items = payload.get("items", [])
        return [dict(item) for item in items if isinstance(item, Mapping)]

    async def preview_file(self, file_id: str, **actor: str) -> dict[str, Any]:
        response = await self._request(
            "GET", f"/v1/files/{file_id}/preview", **actor
        )
        return dict(response.json().get("preview", {}))

    async def _catalog_by_service(self, **actor: str) -> dict[str, Mapping[str, Any]]:
        payload = (await self._request("GET", "/v1/catalog", **actor)).json()
        items = payload.get("items", [])
        return {
            str(item["service"]): item
            for item in items
            if isinstance(item, Mapping) and item.get("service")
        }

    async def list_connections(self, **actor: str) -> list[dict[str, Any]]:
        payload = (await self._request("GET", "/v1/connections", **actor)).json()
        items = payload.get("items", [])
        return [self._connection(item) for item in items if isinstance(item, Mapping)]

    async def get_connection(self, connection_id: str, **actor: str) -> dict[str, Any]:
        items = await self.list_connections(**actor)
        for item in items:
            if item["connection_id"] == connection_id:
                return item
        raise ConnectionServiceError("NOT_FOUND", "connection not found", 404)

    async def create_connection(
        self,
        body: Mapping[str, Any],
        **actor: str,
    ) -> dict[str, Any]:
        credential = body.get("credential")
        values = {
            **(body.get("config") if isinstance(body.get("config"), Mapping) else {}),
            **(credential if isinstance(credential, Mapping) else {}),
        }
        requested_auth_type = values.pop("_auth_type", None)
        auth_type = (
            str(requested_auth_type)
            if requested_auth_type
            else ("custom_credential" if values else "no_auth")
        )
        catalog = await self._catalog_by_service(**actor)
        definition = catalog.get(str(body["connector_key"]))
        if definition is None:
            raise ConnectionServiceError(
                "CONNECTOR_NOT_ENABLED",
                "Connector is not enabled for this workspace",
                404,
            )
        response = await self._request(
            "POST",
            "/v1/connections",
            json={
                "service": body["connector_key"],
                "authType": auth_type,
                "connectionName": service_connection_name(
                    str(body["display_name"]),
                    str(body["connector_key"]),
                ),
                "visibility": body["scope"],
                "values": values,
            },
            **actor,
        )
        created = response.json()["connection"]
        if not isinstance(created, Mapping) or not created.get("id"):
            raise ConnectionServiceError(
                "CONNECTION_SERVICE_INVALID_RESPONSE",
                "Connection Service create response is missing connection.id",
                502,
            )
        # Some Connection Service versions return a complete record from
        # create; newer versions return only a redacted summary.  Preserve a
        # complete canonical response, and resolve summary-only responses
        # through the tenant list before exposing them to the workspace API.
        canonical_fields = {
            "visibility",
            "status",
            "connectorDefinitionVersion",
            "createdAt",
            "updatedAt",
            "revision",
        }
        if canonical_fields.issubset(created):
            connection = self._connection(created)
        else:
            connection = await self.get_connection(str(created["id"]), **actor)
        if body["scope"] != connection["scope"]:
            await self._request(
                "PATCH",
                f"/v1/connections/{connection['connection_id']}",
                json={"visibility": body["scope"]},
                **actor,
            )
            connection = await self.get_connection(connection["connection_id"], **actor)
        return connection

    async def update_connection(
        self,
        connection_id: str,
        body: Mapping[str, Any],
        **actor: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if body.get("display_name") is not None:
            payload["connectionName"] = body["display_name"]
        if body.get("scope") is not None:
            payload["visibility"] = body["scope"]
        if body.get("config") is not None or body.get("credential") is not None:
            raise ConnectionServiceError(
                "INVALID_ARGUMENT",
                "credential replacement is not supported by this Connection Service version",
                422,
            )
        response = await self._request(
            "PATCH",
            f"/v1/connections/{connection_id}",
            json=payload,
            **actor,
        )
        return self._connection(response.json()["connection"])

    async def delete_connection(self, connection_id: str, **actor: str) -> None:
        await self._request(
            "DELETE",
            f"/v1/connections/{connection_id}",
            **actor,
        )

    async def upload_file(
        self,
        *,
        filename: str,
        content: bytes,
        media_type: str,
        **actor: str,
    ) -> str:
        response = await self._request(
            "POST",
            "/v1/files",
            files={"file": (filename, content, media_type)},
            **actor,
        )
        payload = response.json().get("file", {})
        file_id = payload.get("fileId")
        if not isinstance(file_id, str) or not file_id:
            raise ConnectionServiceError(
                "CONNECTION_FILE_INVALID",
                "Connection Service returned an invalid file reference",
                502,
            )
        return file_id

    async def start_job(
        self,
        connection_id: str,
        kind: str,
        **actor: str,
    ) -> dict[str, Any]:
        if kind not in {"validate", "discover"}:
            raise ValueError("invalid connection job kind")
        response = await self._request(
            "POST",
            f"/v1/connections/{connection_id}/{kind}",
            json={},
            **actor,
        )
        job = response.json()["job"]
        return {
            "job_id": str(job["id"]),
            "status": str(job["status"]),
            "event_url": f"/api/knowledge/v1/connection-jobs/{job['id']}",
            **({"result": job["result"]} if "result" in job else {}),
            **({"error": job["error"]} if "error" in job else {}),
        }

    async def get_job(self, job_id: str, **actor: str) -> dict[str, Any]:
        job = (await self._request("GET", f"/v1/jobs/{job_id}", **actor)).json()["job"]
        return {
            "job_id": str(job["id"]),
            "status": str(job["status"]),
            **({"result": job["result"]} if "result" in job else {}),
            **({"error": job["error"]} if "error" in job else {}),
        }

    async def list_audit(self, **actor: str) -> list[dict[str, Any]]:
        payload = (await self._request("GET", "/v1/audit", **actor)).json()
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ConnectionServiceError(
                "CONNECTION_AUDIT_INVALID",
                "Connection Service returned an invalid audit response",
                502,
            )
        return [dict(item) for item in items if isinstance(item, Mapping)]

    async def issue(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        principal_id: str,
        invocation_id: str,
        connection_ids: Sequence[str],
        allowed_actions: Sequence[str],
        ttl_seconds: int,
    ) -> EphemeralConnectionContext:
        actor = {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "principal_id": principal_id,
        }
        catalog = await self._catalog_by_service(**actor)
        connections = {
            item["connection_id"]: item
            for item in await self.list_connections(**actor)
            if item["connection_id"] in connection_ids
        }
        if len(connections) != len(set(connection_ids)):
            raise ConnectionServiceError(
                "CONNECTION_NOT_FOUND",
                "One or more connections are not visible to this workspace",
                404,
            )
        action_ids_by_connection: dict[str, tuple[str, ...]] = {}
        all_actions: list[str] = []
        for connection_id in connection_ids:
            definition = catalog.get(str(connections[connection_id]["connector_key"]))
            action_ids = tuple(
                str(item)
                for item in (definition or {}).get("actionIds", [])
                if str(item)
            )
            if not action_ids:
                raise ConnectionServiceError(
                    "CONNECTION_NOT_READY",
                    "Selected connection has no enabled runtime actions",
                    409,
                )
            action_ids_by_connection[connection_id] = action_ids
            all_actions.extend(action_ids)

        issued: list[tuple[str, str, str]] = []
        expires_at: datetime | None = None
        try:
            for connection_id in connection_ids:
                response = await self._request(
                    "POST",
                    f"/v1/connections/{connection_id}/lease",
                    json={
                        "invocationId": invocation_id,
                        "audience": self.config.audience,
                        "allowedActions": list(action_ids_by_connection[connection_id]),
                        "ttlSeconds": min(ttl_seconds, 900),
                    },
                    **actor,
                )
                payload = response.json()
                claims = payload["claims"]
                issued.append(
                    (
                        connection_id,
                        str(claims["jti"]),
                        str(payload["token"]),
                    )
                )
                candidate = datetime.fromisoformat(
                    str(claims["expiresAt"]).replace("Z", "+00:00")
                )
                expires_at = (
                    candidate if expires_at is None else min(expires_at, candidate)
                )
        except Exception:
            for _, lease_jti, _ in issued:
                try:
                    await self._request(
                        "POST",
                        f"/v1/leases/{lease_jti}/revoke",
                        **actor,
                    )
                except ConnectionServiceError:
                    pass
            raise
        lease_id = self._lease_reference(
            tenant_id,
            workspace_id,
            principal_id,
            tuple(jti for _, jti, _ in issued),
        )
        return EphemeralConnectionContext(
            lease_id=lease_id,
            connection_ids=tuple(connection_ids),
            allowed_actions=tuple(dict.fromkeys(all_actions)),
            expires_at=expires_at or datetime.now(timezone.utc),
            runtime_ref=json.dumps(
                {
                    "audience": self.config.audience,
                    "leases": [
                        {
                            "connection_id": connection_id,
                            "token": token,
                            "allowed_actions": list(
                                action_ids_by_connection[connection_id]
                            ),
                        }
                        for connection_id, _, token in issued
                    ],
                },
                separators=(",", ":"),
            ),
        )

    async def revoke(self, lease_id: str) -> None:
        (tenant_id, workspace_id, principal_id), lease_ids = self._read_lease_reference(
            lease_id
        )
        for item in lease_ids:
            try:
                await self._request(
                    "POST",
                    f"/v1/leases/{item}/revoke",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    principal_id=principal_id,
                )
            except ConnectionServiceError as exc:
                if exc.status_code != 404:
                    raise

    async def prepare_autoskill(
        self,
        *,
        context: EphemeralConnectionContext,
        autoskill: Any,
        agent_id: str,
        session_id: str,
        invocation_id: str,
    ) -> None:
        parsed_runtime = (
            urlsplit(self.config.runtime_public_url)
            if self.config.runtime_public_url
            else None
        )
        if (
            parsed_runtime is None
            or parsed_runtime.scheme != "https"
            or not parsed_runtime.hostname
            or parsed_runtime.username
            or parsed_runtime.password
            or parsed_runtime.query
            or parsed_runtime.fragment
        ):
            raise ConnectionServiceError(
                "CONNECTION_RUNTIME_UNAVAILABLE",
                "The Connection Service MCP runtime requires a public HTTPS URL",
                503,
            )

        runtime = json.loads(context.runtime_ref)
        leases = runtime.get("leases")
        if not isinstance(leases, list) or not leases:
            raise ConnectionServiceError(
                "CONNECTION_NOT_READY",
                "Connection Service did not issue runtime leases",
                409,
            )
        servers: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(leases):
            if not isinstance(item, Mapping):
                raise ConnectionServiceError(
                    "CONNECTION_RUNTIME_INVALID",
                    "Connection Service returned an invalid runtime lease",
                    502,
                )
            connection_id = str(item.get("connection_id") or "")
            lease_token = str(item.get("token") or "")
            if not connection_id or not lease_token:
                raise ConnectionServiceError(
                    "CONNECTION_RUNTIME_INVALID",
                    "Connection Service returned an invalid runtime lease",
                    502,
                )
            query = urlencode(
                {
                    "connectionId": connection_id,
                    "invocationId": invocation_id,
                    "audience": self.config.audience,
                }
            )
            servers[f"knowledge-connection-{index + 1}"] = {
                "transport": "http",
                "url": (
                    f"{self.config.runtime_public_url}/v1/runtime/mcp/sse?{query}"
                ),
                "headers": {"X-Connection-Lease": lease_token},
            }
        state = await autoskill.download_optional_state(
            agent_id=agent_id, session_id=session_id
        )
        configured = self._state_with_mcp(state, servers)
        await autoskill.upload(
            agent_id=agent_id,
            session_id=session_id,
            file_type="state",
            file_name="state.zip",
            content=configured,
        )

    @staticmethod
    def _state_with_mcp(
        state: bytes | None, servers: Mapping[str, Mapping[str, Any]]
    ) -> bytes:
        import yaml

        entries: dict[str, bytes] = {}
        if state:
            with zipfile.ZipFile(io.BytesIO(state)) as archive:
                for info in archive.infolist():
                    if info.is_dir() or info.filename == "mcp_config.yaml":
                        continue
                    if (
                        info.filename.startswith("/")
                        or ".." in info.filename.split("/")
                        or "\\" in info.filename
                    ):
                        raise ConnectionServiceError(
                            "AUTOSKILL_STATE_INVALID",
                            "AutoSkill state archive contains an unsafe path",
                            502,
                        )
                    entries[info.filename] = archive.read(info)
        entries["mcp_config.yaml"] = yaml.safe_dump(
            {"servers": dict(servers)},
            sort_keys=True,
        ).encode("utf-8")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return output.getvalue()

    @classmethod
    def _catalog_item(cls, item: Mapping[str, Any]) -> dict[str, Any]:
        action_ids = [str(value) for value in item.get("actionIds", [])]
        capabilities = ["validate", "discover"]
        if action_ids:
            capabilities.append("action")
        return {
            "connector_key": str(item["service"]),
            "version": str(item["connectorDefinitionVersion"]),
            "display_name": str(item["displayName"]),
            "category": "connection",
            "status": str(item["tier"]),
            "capabilities": capabilities,
            "config_schema": cls._schema(item, "configSchema"),
            "auth_schema": cls._schema(item, "authSchema"),
        }

    @staticmethod
    def _adapter_item(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "connector_key": str(item["service"]),
            "version": str(item.get("connectorDefinitionVersion") or "1.0.0"),
            "display_name": str(item["displayName"]),
            "category": "adapter",
            "status": str(item["tier"]),
            "capabilities": [str(value) for value in item.get("capabilities", [])],
            "config_schema": dict(item.get("configSchema") or {}),
            "auth_schema": dict(item.get("authSchema") or {}),
            "endpoints": [str(value) for value in item.get("endpoints", [])],
        }

    @staticmethod
    def _schema(item: Mapping[str, Any], key: str) -> dict[str, Any]:
        schema = item.get(key)
        if not isinstance(schema, Mapping):
            raise ConnectionServiceError(
                "CONNECTION_CATALOG_INVALID",
                f"Connection Service catalog item is missing {key}",
                502,
            )
        return dict(schema)

    @staticmethod
    def _connection(
        item: Mapping[str, Any],
        *,
        default_scope: str = "personal",
        default_status: str = "error",
        default_definition_version: str = "1.0.0",
    ) -> dict[str, Any]:
        return {
            "connection_id": str(item["id"]),
            "connector_key": str(item["service"]),
            "display_name": str(item["connectionName"]),
            "scope": str(item.get("visibility") or default_scope),
            "status": str(item.get("status") or default_status),
            "definition_version": str(
                item.get("connectorDefinitionVersion")
                or default_definition_version
            ),
            "profile": item.get("profile", {}),
            "created_at": str(item["createdAt"]),
            "updated_at": str(item["updatedAt"]),
            "_revision": int(item["revision"]),
        }


def service_connection_name(display_name: str, connector_key: str) -> str:
    """Map the UI label to Connection Service's bounded identifier format."""

    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", display_name.strip()).strip("-_")
    normalized = normalized[:64].rstrip("-_")
    if normalized and normalized[0].isalnum():
        return normalized
    fallback = re.sub(r"[^A-Za-z0-9_-]+", "-", connector_key).strip("-_")
    return (fallback[:64].rstrip("-_") or "connection")
