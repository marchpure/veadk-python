"""Encrypted OpenViking profiles and a strict, tenant-scoped upstream adapter."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_JSON_BYTES = 1_048_576
MAX_UPLOAD_BYTES = 50 * 1_048_576
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
ALLOWED_UPLOAD_EXTENSIONS = {
    ".csv",
    ".json",
    ".md",
    ".pdf",
    ".txt",
    ".xlsx",
}
SAFE_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")


class OpenVikingError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class OpenVikingConfig:
    encryption_key: bytes
    ref_signing_key: bytes
    timeout_seconds: float = 30.0
    allow_loopback: bool = False

    @classmethod
    def from_env(cls) -> "OpenVikingConfig":
        raw = os.getenv("OPENVIKING_PROFILE_ENCRYPTION_KEY", "")
        signing = os.getenv("OPENVIKING_REF_SIGNING_KEY", "")
        if not raw or not signing:
            raise OpenVikingError(
                "OPENVIKING_UNAVAILABLE",
                "OpenViking profile encryption is not configured",
                503,
            )
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except ValueError as exc:
            raise OpenVikingError(
                "OPENVIKING_UNAVAILABLE", "OpenViking encryption key is invalid", 503
            ) from exc
        if len(key) != 32 or len(signing.encode()) < 32:
            raise OpenVikingError(
                "OPENVIKING_UNAVAILABLE",
                "OpenViking profile keys do not meet minimum strength",
                503,
            )
        return cls(
            encryption_key=key,
            ref_signing_key=signing.encode(),
            allow_loopback=os.getenv("OPENVIKING_ALLOW_LOOPBACK", "") == "1",
        )


@dataclass(frozen=True)
class OpenVikingProfile:
    profile_id: str
    tenant_id: str
    workspace_id: str
    principal_id: str
    display_name: str
    encrypted_base_url: bytes
    encrypted_api_key: bytes
    workspace_uri: str
    status: str
    created_at: str
    updated_at: str


class OpenVikingProfileRepository:
    def __init__(self, database: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(database), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS openviking_profiles (
              profile_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              principal_id TEXT NOT NULL,
              display_name TEXT NOT NULL,
              encrypted_base_url BLOB NOT NULL,
              encrypted_api_key BLOB NOT NULL,
              workspace_uri TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """)
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS openviking_profile_scope "
            "ON openviking_profiles(tenant_id, workspace_id)"
        )
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS openviking_idempotency (
              scope_key TEXT PRIMARY KEY,
              response_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """)
        self._db.commit()

    @staticmethod
    def _profile(row: sqlite3.Row | None) -> OpenVikingProfile | None:
        return OpenVikingProfile(**dict(row)) if row else None

    def save(self, profile: OpenVikingProfile) -> OpenVikingProfile:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO openviking_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET
                  display_name=excluded.display_name,
                  encrypted_base_url=excluded.encrypted_base_url,
                  encrypted_api_key=excluded.encrypted_api_key,
                  workspace_uri=excluded.workspace_uri,
                  status=excluded.status,
                  updated_at=excluded.updated_at
                """,
                tuple(profile.__dict__.values()),
            )
            self._db.commit()
        return profile

    def get(
        self, profile_id: str, *, tenant_id: str, workspace_id: str
    ) -> OpenVikingProfile | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM openviking_profiles "
                "WHERE profile_id=? AND tenant_id=? AND workspace_id=?",
                (profile_id, tenant_id, workspace_id),
            ).fetchone()
        return self._profile(row)

    def list(
        self, *, tenant_id: str, workspace_id: str
    ) -> tuple[OpenVikingProfile, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM openviking_profiles "
                "WHERE tenant_id=? AND workspace_id=? ORDER BY created_at",
                (tenant_id, workspace_id),
            ).fetchall()
        return tuple(self._profile(row) for row in rows if row is not None)

    def delete(self, profile_id: str, *, tenant_id: str, workspace_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "DELETE FROM openviking_profiles "
                "WHERE profile_id=? AND tenant_id=? AND workspace_id=?",
                (profile_id, tenant_id, workspace_id),
            )
            self._db.commit()
        return cursor.rowcount > 0

    def get_idempotent_response(self, scope_key: str) -> Any | None:
        with self._lock:
            row = self._db.execute(
                "SELECT response_json, created_at FROM openviking_idempotency "
                "WHERE scope_key=?",
                (scope_key,),
            ).fetchone()
            if row and (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(row["created_at"])
            ).total_seconds() > IDEMPOTENCY_TTL_SECONDS:
                self._db.execute(
                    "DELETE FROM openviking_idempotency WHERE scope_key=?",
                    (scope_key,),
                )
                self._db.commit()
                row = None
        return json.loads(row["response_json"]) if row else None

    def save_idempotent_response(self, scope_key: str, response: Any) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO openviking_idempotency VALUES(?,?,?) "
                "ON CONFLICT(scope_key) DO UPDATE SET "
                "response_json=excluded.response_json, created_at=excluded.created_at",
                (
                    scope_key,
                    json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._db.commit()


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    body_limit: int = MAX_JSON_BYTES


OPERATIONS: Mapping[str, Operation] = {
    "fs_list": Operation("GET", "/api/v1/fs/ls"),
    "fs_tree": Operation("GET", "/api/v1/fs/tree"),
    "fs_stat": Operation("GET", "/api/v1/fs/stat"),
    "content_read": Operation("GET", "/api/v1/content/read"),
    "content_abstract": Operation("GET", "/api/v1/content/abstract"),
    "content_overview": Operation("GET", "/api/v1/content/overview"),
    "content_reindex": Operation("POST", "/api/v1/content/reindex"),
    "content_write": Operation("POST", "/api/v1/content/write"),
    "resource_import": Operation("POST", "/api/v1/resources"),
    "find": Operation("POST", "/api/v1/search/find"),
    "search": Operation("POST", "/api/v1/search/search"),
    "grep": Operation("POST", "/api/v1/search/grep"),
    "glob": Operation("POST", "/api/v1/search/glob"),
    "tasks": Operation("GET", "/api/v1/tasks"),
    "watches": Operation("GET", "/api/v1/watches"),
}

ITEM_OPERATIONS: Mapping[str, Operation] = {
    "task_get": Operation("GET", "/api/v1/tasks"),
    "watch_get": Operation("GET", "/api/v1/watches"),
    "watch_update": Operation("PATCH", "/api/v1/watches"),
    "watch_delete": Operation("DELETE", "/api/v1/watches"),
    "watch_trigger": Operation("POST", "/api/v1/watches", body_limit=1024),
}


class OpenVikingService:
    def __init__(
        self,
        repository: OpenVikingProfileRepository,
        config: OpenVikingConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.repository = repository
        self.config = config
        self._client = client
        self._cipher = AESGCM(config.encryption_key)
        self._idempotency_lock = asyncio.Lock()

    def _encrypt(self, value: str, scope: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, value.encode(), scope.encode())

    def _decrypt(self, value: bytes, scope: str) -> str:
        try:
            return self._cipher.decrypt(value[:12], value[12:], scope.encode()).decode()
        except Exception as exc:
            raise OpenVikingError(
                "OPENVIKING_PROFILE_CORRUPT",
                "OpenViking profile cannot be decrypted",
                500,
            ) from exc

    @staticmethod
    def _scope(tenant_id: str, workspace_id: str, profile_id: str) -> str:
        return f"{tenant_id}:{workspace_id}:{profile_id}"

    def _validate_base_url(self, value: str) -> str:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.path not in {"", "/"})
        ):
            raise OpenVikingError(
                "INVALID_BASE_URL", "Base URL must be an HTTPS origin", 422
            )
        host = parsed.hostname.casefold()
        loopback_name = host == "localhost"
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    host, parsed.port or 443, type=socket.SOCK_STREAM
                )
            }
        except socket.gaierror as exc:
            raise OpenVikingError(
                "INVALID_BASE_URL", "Base URL host cannot be resolved", 422
            ) from exc
        blocked = any(
            (ip := ipaddress.ip_address(address)).is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            for address in addresses
        )
        if parsed.scheme != "https" and not (
            self.config.allow_loopback and loopback_name
        ):
            raise OpenVikingError("INVALID_BASE_URL", "Base URL must use HTTPS", 422)
        if blocked and not (self.config.allow_loopback and loopback_name):
            raise OpenVikingError(
                "SSRF_BLOCKED", "Base URL resolves to a restricted network", 422
            )
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"

    def public_profile(self, profile: OpenVikingProfile) -> dict[str, Any]:
        return {
            "profile_id": profile.profile_id,
            "display_name": profile.display_name,
            "workspace_uri": "viking://workspace/",
            "root_resource_ref": self.resource_ref(profile, profile.workspace_uri),
            "status": profile.status,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    def create_profile(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        principal_id: str,
        display_name: str,
        base_url: str,
        api_key: str,
        workspace_uri: str,
    ) -> OpenVikingProfile:
        if not api_key or len(api_key) > 4096:
            raise OpenVikingError("INVALID_ARGUMENT", "API key is required")
        if not workspace_uri.startswith("viking://"):
            raise OpenVikingError(
                "INVALID_ARGUMENT", "Workspace URI must use viking://"
            )
        profile_id = f"ovp_{secrets.token_urlsafe(18)}"
        scope = self._scope(tenant_id, workspace_id, profile_id)
        now = datetime.now(timezone.utc).isoformat()
        return self.repository.save(
            OpenVikingProfile(
                profile_id=profile_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                principal_id=principal_id,
                display_name=display_name.strip(),
                encrypted_base_url=self._encrypt(
                    self._validate_base_url(base_url), scope
                ),
                encrypted_api_key=self._encrypt(api_key, scope),
                workspace_uri=workspace_uri.rstrip("/") + "/",
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )

    def update_profile(
        self,
        profile: OpenVikingProfile,
        *,
        display_name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        workspace_uri: str | None = None,
    ) -> OpenVikingProfile:
        scope = self._scope(profile.tenant_id, profile.workspace_id, profile.profile_id)
        if api_key is not None and (not api_key or len(api_key) > 4096):
            raise OpenVikingError("INVALID_ARGUMENT", "API key is invalid")
        if workspace_uri is not None and not workspace_uri.startswith("viking://"):
            raise OpenVikingError(
                "INVALID_ARGUMENT", "Workspace URI must use viking://"
            )
        value = OpenVikingProfile(
            **{
                **profile.__dict__,
                "display_name": (
                    display_name.strip()
                    if display_name is not None
                    else profile.display_name
                ),
                "encrypted_base_url": (
                    self._encrypt(self._validate_base_url(base_url), scope)
                    if base_url is not None
                    else profile.encrypted_base_url
                ),
                "encrypted_api_key": (
                    self._encrypt(api_key, scope)
                    if api_key is not None
                    else profile.encrypted_api_key
                ),
                "workspace_uri": (
                    workspace_uri.rstrip("/") + "/"
                    if workspace_uri is not None
                    else profile.workspace_uri
                ),
                "status": "pending",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return self.repository.save(value)

    def _credentials(self, profile: OpenVikingProfile) -> tuple[str, str]:
        scope = self._scope(profile.tenant_id, profile.workspace_id, profile.profile_id)
        return (
            self._decrypt(profile.encrypted_base_url, scope),
            self._decrypt(profile.encrypted_api_key, scope),
        )

    def resource_ref(self, profile: OpenVikingProfile, uri: str) -> str:
        if uri.rstrip("/") == profile.workspace_uri.rstrip("/"):
            uri = profile.workspace_uri
        if not uri.startswith(profile.workspace_uri):
            raise OpenVikingError(
                "RESOURCE_OUT_OF_SCOPE", "Resource is outside workspace", 403
            )
        payload = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {"p": profile.profile_id, "u": uri},
                    separators=(",", ":"),
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        signature = hmac.new(
            self.config.ref_signing_key, payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"ovr_{payload}.{signature}"

    def resolve_ref(self, profile: OpenVikingProfile, value: str) -> str:
        try:
            prefix_payload, signature = value.rsplit(".", 1)
            if not prefix_payload.startswith("ovr_"):
                raise ValueError
            payload = prefix_payload[4:]
            expected = hmac.new(
                self.config.ref_signing_key, payload.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            data = json.loads(
                base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            )
            if data["p"] != profile.profile_id:
                raise ValueError
            uri = str(data["u"])
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise OpenVikingError(
                "INVALID_RESOURCE_REF", "Resource reference is invalid", 422
            ) from exc
        if not uri.startswith(profile.workspace_uri):
            raise OpenVikingError(
                "RESOURCE_OUT_OF_SCOPE", "Resource is outside workspace", 403
            )
        return uri

    def creator_context(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        profile_ids: list[str] | tuple[str, ...],
        resource_refs: list[str] | tuple[str, ...],
    ) -> dict[str, object]:
        profiles: list[OpenVikingProfile] = []
        for profile_id in dict.fromkeys(profile_ids):
            profile = self.repository.get(
                profile_id, tenant_id=tenant_id, workspace_id=workspace_id
            )
            if profile is None:
                raise OpenVikingError(
                    "OPENVIKING_CONTEXT_FORBIDDEN",
                    "OpenViking profile is not available in this workspace",
                    403,
                )
            if profile.status != "ready":
                raise OpenVikingError(
                    "OPENVIKING_PROFILE_NOT_READY",
                    "OpenViking profile must be validated before use",
                    409,
                )
            profiles.append(profile)
        if resource_refs and not profiles:
            raise OpenVikingError(
                "OPENVIKING_PROFILE_REQUIRED",
                "An OpenViking profile is required for resource references",
                422,
            )
        for resource_ref in dict.fromkeys(resource_refs):
            if not any(
                self._ref_matches_profile(profile, resource_ref) for profile in profiles
            ):
                raise OpenVikingError(
                    "OPENVIKING_CONTEXT_FORBIDDEN",
                    "OpenViking resource is not available through the selected profiles",
                    403,
                )
        return {
            "profile_ids": list(dict.fromkeys(profile_ids)),
            "resource_refs": list(dict.fromkeys(resource_refs)),
        }

    async def resolved_creator_context(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        profile_ids: list[str] | tuple[str, ...],
        resource_refs: list[str] | tuple[str, ...],
    ) -> dict[str, object]:
        context = self.creator_context(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            profile_ids=profile_ids,
            resource_refs=resource_refs,
        )
        resources: list[dict[str, object]] = []
        remaining = 128 * 1024
        profiles = {
            item.profile_id: item
            for item in self.repository.list(
                tenant_id=tenant_id, workspace_id=workspace_id
            )
            if item.profile_id in profile_ids
        }
        for resource_ref in dict.fromkeys(resource_refs):
            selected = next(
                (
                    item
                    for item in profiles.values()
                    if self._ref_matches_profile(item, resource_ref)
                ),
                None,
            )
            if selected is None:
                raise OpenVikingError(
                    "OPENVIKING_CONTEXT_FORBIDDEN",
                    "OpenViking resource is not available through the selected profiles",
                    403,
                )
            result = await self.request(
                selected,
                "content_read",
                payload={"resource_ref": resource_ref, "offset": 0, "limit": remaining},
            )
            encoded = json.dumps(result, ensure_ascii=False)
            bounded = encoded.encode("utf-8")[:remaining].decode(
                "utf-8", errors="ignore"
            )
            resources.append(
                {
                    "resource_ref": resource_ref,
                    "content": bounded,
                }
            )
            remaining -= len(bounded.encode("utf-8"))
            if remaining <= 0:
                break
        return {**context, "resolved_resources": resources}

    def _ref_matches_profile(
        self, profile: OpenVikingProfile, resource_ref: str
    ) -> bool:
        try:
            self.resolve_ref(profile, resource_ref)
            return True
        except OpenVikingError:
            return False

    def _replace_refs(self, profile: OpenVikingProfile, value: Any) -> Any:
        ref_fields = {
            "resource_ref": "uri",
            "target_ref": "target_uri",
            "resource_id_ref": "resource_id",
            "root_ref": "root_uri",
            "to_ref": "to_uri",
            "parent_ref": "parent",
            "destination_ref": "to",
        }
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key in ref_fields and isinstance(item, str):
                    result[ref_fields[key]] = self.resolve_ref(profile, item)
                elif (
                    key
                    in {
                        "uri",
                        "target_uri",
                        "resource_id",
                        "root_uri",
                        "to_uri",
                        "parent",
                        "to",
                    }
                    and isinstance(item, str)
                    and item.startswith("viking://")
                ):
                    raise OpenVikingError(
                        "OPAQUE_RESOURCE_REF_REQUIRED",
                        "OpenViking resources must use an opaque resource reference",
                        422,
                    )
                else:
                    result[key] = self._replace_refs(profile, item)
            return result
        if isinstance(value, list):
            return [self._replace_refs(profile, item) for item in value]
        return value

    def _sanitize(self, profile: OpenVikingProfile, value: Any) -> Any:
        ref_fields = {
            "uri": "resource_ref",
            "target_uri": "target_ref",
            "resource_id": "resource_id_ref",
            "root_uri": "root_ref",
            "to_uri": "to_ref",
            "parent": "parent_ref",
            "to": "destination_ref",
        }
        private_fields = {
            "account_id",
            "api_key",
            "archive_uri",
            "authorization",
            "base_url",
            "internal_url",
            "lease_ref",
            "lock_paths",
            "memory_diff_uri",
            "original_role",
            "owner_id",
            "ownership_ref",
            "resource_lock",
            "temp_uri",
            "token",
            "user_id",
        }
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key.casefold() in private_fields:
                    continue
                if (
                    key in ref_fields
                    and isinstance(item, str)
                    and item.startswith("viking://")
                ):
                    normalized_uri = (
                        profile.workspace_uri
                        if item.rstrip("/") == profile.workspace_uri.rstrip("/")
                        else item
                    )
                    relative = normalized_uri.removeprefix(profile.workspace_uri)
                    result[ref_fields[key]] = self.resource_ref(
                        profile, normalized_uri
                    )
                    result[key] = f"viking://workspace/{relative}"
                    result["display_path"] = relative
                elif isinstance(item, str) and item.startswith("viking://"):
                    # Non-workspace URIs expose upstream account/session layout and
                    # cannot be represented by this profile's scoped resource refs.
                    continue
                elif (
                    key in {"path", "source_path"}
                    and isinstance(item, str)
                    and Path(item).is_absolute()
                ):
                    # Parser results may contain upstream temporary filesystem paths.
                    result[key] = Path(item).name
                else:
                    result[key] = self._sanitize(profile, item)
            return result
        if isinstance(value, list):
            return [self._sanitize(profile, item) for item in value]
        if isinstance(value, str):
            return value.replace(profile.workspace_uri, "viking://workspace/")
        return value

    async def request(
        self,
        profile: OpenVikingProfile,
        operation_name: str,
        *,
        payload: Mapping[str, Any] | None = None,
        item_id: str | None = None,
    ) -> Any:
        operation = (
            ITEM_OPERATIONS.get(operation_name)
            if item_id is not None
            else OPERATIONS.get(operation_name)
        )
        if operation is None:
            raise OpenVikingError(
                "OPERATION_NOT_ALLOWED", "Operation is not allowed", 404
            )
        body = self._replace_refs(profile, dict(payload or {}))
        if operation_name in {"fs_list", "fs_tree"} and not any(
            key in body for key in {"uri", "resource_ref"}
        ):
            body["uri"] = profile.workspace_uri
        if operation_name == "resource_import":
            remote_url = body.get("path")
            if isinstance(remote_url, str) and (
                remote_url.startswith("http://") or remote_url.startswith("https://")
            ):
                self._validate_import_url(remote_url)
        encoded = json.dumps(body, separators=(",", ":")).encode()
        if len(encoded) > operation.body_limit:
            raise OpenVikingError("PAYLOAD_TOO_LARGE", "Request body is too large", 413)
        path = operation.path
        if item_id:
            if (
                not item_id
                or len(item_id) > 256
                or any(
                    character
                    not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
                    for character in item_id
                )
            ):
                raise OpenVikingError("INVALID_ARGUMENT", "Item id is invalid", 422)
            path += f"/{item_id}"
            if operation_name == "watch_trigger":
                path += "/trigger"
        base_url, api_key = self._credentials(profile)
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=5),
            follow_redirects=False,
        )
        owns_client = self._client is None
        try:
            kwargs: dict[str, Any] = {
                "headers": {"X-API-Key": api_key, "Accept": "application/json"}
            }
            if operation.method == "GET":
                kwargs["params"] = body
            elif operation.method != "DELETE":
                kwargs["json"] = body
            response = await client.request(operation.method, base_url + path, **kwargs)
            if response.status_code >= 400:
                code = (
                    "OPENVIKING_AUTH_FAILED"
                    if response.status_code in {401, 403}
                    else "OPENVIKING_UPSTREAM_ERROR"
                )
                raise OpenVikingError(
                    code, "OpenViking request failed", response.status_code
                )
            try:
                result = response.json()
            except ValueError as exc:
                raise OpenVikingError(
                    "OPENVIKING_INVALID_RESPONSE",
                    "OpenViking returned invalid JSON",
                    502,
                ) from exc
            return self._sanitize(profile, result)
        except httpx.TimeoutException as exc:
            raise OpenVikingError(
                "OPENVIKING_TIMEOUT", "OpenViking request timed out", 504
            ) from exc
        except httpx.TransportError as exc:
            raise OpenVikingError(
                "OPENVIKING_UNAVAILABLE", "OpenViking is unavailable", 502
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    async def request_idempotent(
        self,
        profile: OpenVikingProfile,
        operation_name: str,
        *,
        payload: Mapping[str, Any] | None = None,
        item_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        body = dict(payload or {})
        if not idempotency_key and operation_name not in {
            "content_write",
            "resource_import",
        }:
            return await self.request(
                profile, operation_name, payload=body, item_id=item_id
            )
        body_hash = hashlib.sha256(
            json.dumps(body, separators=(",", ":")).encode()
        ).hexdigest()
        request_key = idempotency_key or body_hash
        if len(request_key) > 256:
            raise OpenVikingError(
                "INVALID_IDEMPOTENCY_KEY", "Idempotency key is too long", 422
            )
        scope_key = hashlib.sha256(
            (
                f"{profile.tenant_id}\0{profile.workspace_id}\0"
                f"{profile.profile_id}\0{operation_name}\0{item_id or ''}\0"
                f"{request_key}\0{body_hash}"
            ).encode()
        ).hexdigest()
        async with self._idempotency_lock:
            cached = self.repository.get_idempotent_response(scope_key)
            if cached is not None:
                return cached
            result = await self.request(
                profile, operation_name, payload=body, item_id=item_id
            )
            self.repository.save_idempotent_response(scope_key, result)
            return result

    async def write_text(
        self,
        profile: OpenVikingProfile,
        *,
        parent_ref: str,
        filename: str,
        content: str,
    ) -> Any:
        name = filename.strip()
        if not SAFE_RESOURCE_NAME.fullmatch(name) or name in {".", ".."}:
            raise OpenVikingError(
                "INVALID_ARGUMENT", "Resource filename is invalid", 422
            )
        if not name.casefold().endswith((".md", ".txt")):
            raise OpenVikingError(
                "UNSUPPORTED_FILE_TYPE", "Manual text must use .md or .txt", 415
            )
        if not content.strip():
            raise OpenVikingError("INVALID_ARGUMENT", "Text content is required", 422)
        if len(content.encode("utf-8")) > MAX_JSON_BYTES:
            raise OpenVikingError("PAYLOAD_TOO_LARGE", "Text content is too large", 413)
        parent = self.resolve_ref(profile, parent_ref).rstrip("/") + "/"
        return await self.request(
            profile,
            "content_write",
            payload={
                "resource_ref": self.resource_ref(profile, parent + name),
                "content": content,
                "mode": "replace",
                "wait": False,
            },
        )

    async def import_connection_resource(
        self,
        profile: OpenVikingProfile,
        *,
        parent_ref: str,
        filename: str,
        document: Mapping[str, Any],
    ) -> Any:
        content = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
        return await self.write_text(
            profile,
            parent_ref=parent_ref,
            filename=filename,
            content=content,
        )

    def _validate_import_url(self, value: str) -> None:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise OpenVikingError(
                "INVALID_IMPORT_URL", "Imported URLs must use HTTPS", 422
            )
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
                )
            }
        except socket.gaierror as exc:
            raise OpenVikingError(
                "INVALID_IMPORT_URL", "Import URL host cannot be resolved", 422
            ) from exc
        if any(
            (ip := ipaddress.ip_address(address)).is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            for address in addresses
        ):
            raise OpenVikingError(
                "SSRF_BLOCKED", "Import URL resolves to a restricted network", 422
            )

    async def upload(
        self,
        profile: OpenVikingProfile,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> Any:
        suffix = Path(filename).suffix.casefold()
        if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
            raise OpenVikingError(
                "UNSUPPORTED_FILE_TYPE", "File type is not supported", 415
            )
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise OpenVikingError("PAYLOAD_TOO_LARGE", "Upload is too large", 413)
        base_url, api_key = self._credentials(profile)
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=5),
            follow_redirects=False,
        )
        owns_client = self._client is None
        try:
            response = await client.post(
                base_url + "/api/v1/resources/temp_upload",
                headers={"X-API-Key": api_key, "Accept": "application/json"},
                files={"file": (Path(filename).name, content, content_type)},
                data={"telemetry": "true"},
            )
            if response.status_code >= 400:
                raise OpenVikingError(
                    "OPENVIKING_UPLOAD_FAILED",
                    "OpenViking upload failed",
                    response.status_code,
                )
            return self._sanitize(profile, response.json())
        except httpx.TimeoutException as exc:
            raise OpenVikingError(
                "OPENVIKING_TIMEOUT", "OpenViking upload timed out", 504
            ) from exc
        except httpx.TransportError as exc:
            raise OpenVikingError(
                "OPENVIKING_UNAVAILABLE", "OpenViking is unavailable", 502
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    async def validate(self, profile: OpenVikingProfile) -> Any:
        result = await self.request(
            profile,
            "fs_list",
            payload={"resource_ref": self.resource_ref(profile, profile.workspace_uri)},
        )
        updated = OpenVikingProfile(
            **{
                **profile.__dict__,
                "status": "ready",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.repository.save(updated)
        return result
