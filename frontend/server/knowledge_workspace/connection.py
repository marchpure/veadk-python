"""Server-only Connection Service gateway owned by the BFF boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

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
    bridge_base_url: str | None = None
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
            bridge_base_url=(
                os.getenv("KNOWLEDGE_CONNECTION_BRIDGE_BASE_URL", "").rstrip("/")
                or None
            ),
        )


@dataclass
class _McpBridgeSession:
    server: Any
    invocation_id: str
    expires_at: datetime


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
        self._mcp_transport: Any = None
        self._mcp_sessions: dict[str, _McpBridgeSession] = {}

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
                "connectionName": body["display_name"],
                "visibility": body["scope"],
                "values": values,
            },
            **actor,
        )
        connection = self._connection(response.json()["connection"])
        if body["scope"] != connection["scope"]:
            response = await self._request(
                "PATCH",
                f"/v1/connections/{connection['connection_id']}",
                json={"visibility": body["scope"]},
                **actor,
            )
            connection = self._connection(response.json()["connection"])
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
        parsed_bridge = (
            urlsplit(self.config.bridge_base_url)
            if self.config.bridge_base_url
            else None
        )
        if (
            parsed_bridge is None
            or parsed_bridge.scheme != "https"
            or not parsed_bridge.hostname
            or parsed_bridge.username
            or parsed_bridge.password
            or parsed_bridge.query
            or parsed_bridge.fragment
        ):
            raise ConnectionServiceError(
                "CONNECTION_RUNTIME_UNAVAILABLE",
                "The lease-scoped AutoSkill tool bridge requires a public HTTPS URL",
                503,
            )
        from mcp import types
        from mcp.server import Server

        runtime = json.loads(context.runtime_ref)
        lease_by_connection = {
            str(item["connection_id"]): {
                "token": str(item["token"]),
                "allowed_actions": frozenset(
                    str(action) for action in item.get("allowed_actions", [])
                ),
            }
            for item in runtime["leases"]
        }
        actor, _ = self._read_lease_reference(context.lease_id)
        actor_value = {
            "tenant_id": actor[0],
            "workspace_id": actor[1],
            "principal_id": actor[2],
        }
        tool_records: dict[str, dict[str, Any]] = {}
        for connection_id in context.connection_ids:
            job = await self.start_job(connection_id, "discover", **actor_value)
            if job["status"] != "succeeded":
                raise ConnectionServiceError(
                    "CONNECTION_DISCOVERY_FAILED",
                    "Connection action discovery did not succeed",
                    502,
                )
            for action in job.get("result", {}).get("actions", []):
                if not isinstance(action, Mapping) or not action.get("executable"):
                    continue
                action_id = str(action["id"])
                lease = lease_by_connection[connection_id]
                if action_id not in lease["allowed_actions"]:
                    continue
                tool_name = self._tool_name(connection_id, action_id)
                tool_records[tool_name] = {
                    "connection_id": connection_id,
                    "action_id": action_id,
                    "description": str(action.get("description") or action_id),
                    "input_schema": action.get("inputSchema")
                    if isinstance(action.get("inputSchema"), Mapping)
                    else {"type": "object", "properties": {}},
                    "lease_token": lease["token"],
                }
        if not tool_records:
            raise ConnectionServiceError(
                "CONNECTION_NOT_READY",
                "Selected connections have no executable runtime actions",
                409,
            )

        bridge_token = secrets.token_urlsafe(32)
        server = Server("knowledge-connections")

        @server.list_tools()
        async def list_tools() -> list[Any]:
            return [
                types.Tool(
                    name=name,
                    description=record["description"],
                    inputSchema=record["input_schema"],
                )
                for name, record in tool_records.items()
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            active = self._mcp_sessions.get(bridge_token)
            if active is None or active.expires_at <= datetime.now(timezone.utc):
                self._mcp_sessions.pop(bridge_token, None)
                raise ConnectionServiceError(
                    "LEASE_EXPIRED", "Connection runtime session expired", 401
                )
            record = tool_records.get(name)
            if record is None:
                raise ValueError("Unknown connection action")
            response = await self._request(
                "POST",
                f"/v1/runtime/actions/{record['action_id']}",
                headers={"X-Connection-Lease": record["lease_token"]},
                json={
                    "invocationId": invocation_id,
                    "audience": self.config.audience,
                    "connectionId": record["connection_id"],
                    "input": arguments,
                },
                **actor_value,
            )
            payload = response.json()
            if payload.get("auditPersisted") is not True:
                raise ConnectionServiceError(
                    "CONNECTION_AUDIT_UNAVAILABLE",
                    "Connection action audit was not persisted",
                    502,
                )
            return payload

        self._mcp_sessions[bridge_token] = _McpBridgeSession(
            server=server,
            invocation_id=invocation_id,
            expires_at=context.expires_at,
        )
        try:
            state = await autoskill.download_optional_state(
                agent_id=agent_id, session_id=session_id
            )
            configured = self._state_with_mcp(
                state,
                (
                    f"{self.config.bridge_base_url}/api/knowledge/v1/"
                    f"connection-runtime/{bridge_token}/sse"
                ),
            )
            await autoskill.upload(
                agent_id=agent_id,
                session_id=session_id,
                file_type="state",
                file_name="state.zip",
                content=configured,
            )
        except Exception:
            self._mcp_sessions.pop(bridge_token, None)
            raise

    def _transport(self) -> Any:
        if self._mcp_transport is None:
            from mcp.server.sse import SseServerTransport

            self._mcp_transport = SseServerTransport(
                "/api/knowledge/v1/connection-runtime/messages/"
            )
        return self._mcp_transport

    async def mcp_sse(self, request: Any, bridge_token: str) -> Any:
        from starlette.responses import Response

        session = self._mcp_sessions.get(bridge_token)
        if session is None or session.expires_at <= datetime.now(timezone.utc):
            self._mcp_sessions.pop(bridge_token, None)
            raise ConnectionServiceError(
                "LEASE_EXPIRED", "Connection runtime session expired", 401
            )
        transport = self._transport()
        async with transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await session.server.run(
                streams[0],
                streams[1],
                session.server.create_initialization_options(),
            )
        return Response()

    @property
    def mcp_message_app(self) -> Any:
        return self._transport().handle_post_message

    def forget_invocation(self, invocation_id: str) -> None:
        stale = [
            token
            for token, session in self._mcp_sessions.items()
            if session.invocation_id == invocation_id
        ]
        for token in stale:
            self._mcp_sessions.pop(token, None)

    @staticmethod
    def _tool_name(connection_id: str, action_id: str) -> str:
        raw = f"{connection_id[:12]}__{action_id}"
        return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)[:120]

    @staticmethod
    def _state_with_mcp(state: bytes | None, url: str) -> bytes:
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
            {
                "servers": {
                    "knowledge-connections": {
                        "transport": "http",
                        "url": url,
                    }
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return output.getvalue()

    @staticmethod
    def _catalog_item(item: Mapping[str, Any]) -> dict[str, Any]:
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
            "config_schema": {"type": "object", "properties": {}},
            "auth_schema": {"type": "object", "properties": {}},
        }

    @staticmethod
    def _connection(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "connection_id": str(item["id"]),
            "connector_key": str(item["service"]),
            "display_name": str(item["connectionName"]),
            "scope": str(item["visibility"]),
            "status": str(item["status"]),
            "definition_version": str(item["connectorDefinitionVersion"]),
            "profile": item.get("profile", {}),
            "created_at": str(item["createdAt"]),
            "updated_at": str(item["updatedAt"]),
            "_revision": int(item["revision"]),
        }
