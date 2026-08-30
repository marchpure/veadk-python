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
import unicodedata
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
PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
SAFE_BASE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")
URL_UNRESERVED_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
)


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
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS openviking_task_history (
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              profile_id TEXT NOT NULL,
              task_id TEXT NOT NULL,
              task_json TEXT NOT NULL,
              observed_at TEXT NOT NULL,
              PRIMARY KEY (tenant_id, workspace_id, profile_id, task_id)
            )
            """)
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS openviking_task_history_scope "
            "ON openviking_task_history(tenant_id, workspace_id, profile_id, observed_at)"
        )
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
            self._db.execute(
                "DELETE FROM openviking_task_history "
                "WHERE profile_id=? AND tenant_id=? AND workspace_id=?",
                (profile_id, tenant_id, workspace_id),
            )
            self._db.commit()
        return cursor.rowcount > 0

    def save_task_history(
        self, profile: OpenVikingProfile, tasks: list[Mapping[str, Any]]
    ) -> None:
        observed_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for task in tasks:
            task_id = task.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            rows.append(
                (
                    profile.tenant_id,
                    profile.workspace_id,
                    profile.profile_id,
                    task_id,
                    json.dumps(task, ensure_ascii=False, separators=(",", ":")),
                    observed_at,
                )
            )
        if not rows:
            return
        with self._lock:
            self._db.executemany(
                """
                INSERT INTO openviking_task_history VALUES(?,?,?,?,?,?)
                ON CONFLICT(tenant_id, workspace_id, profile_id, task_id)
                DO UPDATE SET
                  task_json=excluded.task_json,
                  observed_at=excluded.observed_at
                """,
                rows,
            )
            self._db.commit()

    def list_task_history(self, profile: OpenVikingProfile) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT task_json FROM openviking_task_history "
                "WHERE tenant_id=? AND workspace_id=? AND profile_id=? "
                "ORDER BY observed_at DESC",
                (profile.tenant_id, profile.workspace_id, profile.profile_id),
            ).fetchall()
        return [json.loads(row["task_json"]) for row in rows]

    def get_idempotent_response(self, scope_key: str) -> Any | None:
        with self._lock:
            row = self._db.execute(
                "SELECT response_json, created_at FROM openviking_idempotency "
                "WHERE scope_key=?",
                (scope_key,),
            ).fetchone()
            if (
                row
                and (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(row["created_at"])
                ).total_seconds()
                > IDEMPOTENCY_TTL_SECONDS
            ):
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
    "session_commit": Operation("POST", "/api/v1/sessions", body_limit=1024),
    "task_get": Operation("GET", "/api/v1/tasks"),
    "watch_get": Operation("GET", "/api/v1/watches"),
    "watch_update": Operation("PATCH", "/api/v1/watches"),
    "watch_delete": Operation("DELETE", "/api/v1/watches"),
    "watch_trigger": Operation("POST", "/api/v1/watches", body_limit=1024),
}

OPERATION_FIELDS: Mapping[str, frozenset[str]] = {
    "fs_list": frozenset(
        {
            "resource_ref",
            "simple",
            "recursive",
            "output",
            "abs_limit",
            "show_all_hidden",
            "node_limit",
            "limit",
            "sort_by",
            "sort_order",
        }
    ),
    "fs_tree": frozenset(
        {
            "resource_ref",
            "output",
            "abs_limit",
            "show_all_hidden",
            "node_limit",
            "limit",
            "level_limit",
        }
    ),
    "fs_stat": frozenset({"resource_ref"}),
    "content_read": frozenset({"resource_ref", "offset", "limit", "raw"}),
    "content_abstract": frozenset({"resource_ref"}),
    "content_overview": frozenset({"resource_ref"}),
    "content_write": frozenset(
        {
            "resource_ref",
            "content",
            "mode",
            "wait",
            "timeout",
            "telemetry",
            "processing_mode",
        }
    ),
    "content_reindex": frozenset(
        {
            "resource_ref",
            "mode",
            "wait",
            "dry_run",
            "recursive",
            "tags",
            "tag_mode",
        }
    ),
    "resource_import": frozenset(
        {
            "path",
            "temp_file_id",
            "add_type",
            "destination_ref",
            "parent_ref",
            "create_parent",
            "reason",
            "instruction",
            "wait",
            "timeout",
            "strict",
            "source_name",
            "ignore_dirs",
            "include",
            "exclude",
            "directly_upload_media",
            "preserve_structure",
            "args",
            "telemetry",
            "watch_interval",
            "processing_mode",
            "tags",
            "tag_mode",
        }
    ),
    "find": frozenset(
        {
            "query",
            "image_url",
            "target_ref",
            "context_type",
            "limit",
            "node_limit",
            "score_threshold",
            "filter",
            "include_provenance",
            "tags",
            "since",
            "until",
            "time_field",
            "level",
            "read_content",
            "telemetry",
        }
    ),
    "search": frozenset(
        {
            "query",
            "image_url",
            "target_ref",
            "context_type",
            "session_id",
            "limit",
            "node_limit",
            "score_threshold",
            "filter",
            "include_provenance",
            "tags",
            "since",
            "until",
            "time_field",
            "level",
            "read_content",
            "telemetry",
            "mode",
            "query_expansion",
            "max_tokens",
            "quotas",
            "purpose",
            "detail",
            "dedup_turns",
            "exclude_uris",
            "peer_scope",
            "other_peer_penalty",
            "rewrite",
            "rewrite_max_bullets",
        }
    ),
    "grep": frozenset(
        {
            "resource_ref",
            "exclude_uri",
            "pattern",
            "case_insensitive",
            "node_limit",
            "level_limit",
        }
    ),
    "glob": frozenset({"pattern", "resource_ref", "node_limit"}),
    "tasks": frozenset(
        {"task_type", "status", "resource_id_ref", "include_internal", "limit"}
    ),
    "watches": frozenset({"active_only", "to_ref"}),
    "task_get": frozenset(),
    "session_commit": frozenset({"keep_recent_count"}),
    "watch_get": frozenset({"to_ref"}),
    "watch_update": frozenset(
        {"watch_interval", "is_active", "reason", "instruction", "to_ref"}
    ),
    "watch_delete": frozenset({"to_ref"}),
    "watch_trigger": frozenset({"to_ref"}),
}

BOOLEAN_FIELDS = frozenset(
    {
        "active_only",
        "case_insensitive",
        "create_parent",
        "directly_upload_media",
        "dry_run",
        "include_internal",
        "include_provenance",
        "is_active",
        "preserve_structure",
        "raw",
        "read_content",
        "recursive",
        "show_all_hidden",
        "simple",
        "strict",
        "wait",
    }
)
INTEGER_FIELDS = frozenset(
    {
        "abs_limit",
        "dedup_turns",
        "level_limit",
        "limit",
        "max_tokens",
        "node_limit",
        "offset",
        "keep_recent_count",
        "rewrite_max_bullets",
    }
)
NUMBER_FIELDS = frozenset({"score_threshold", "timeout", "watch_interval"})
STRING_FIELDS = frozenset(
    {
        "add_type",
        "destination_ref",
        "exclude",
        "exclude_uri",
        "image_url",
        "include",
        "instruction",
        "mode",
        "output",
        "parent_ref",
        "path",
        "pattern",
        "peer_scope",
        "processing_mode",
        "purpose",
        "query",
        "query_expansion",
        "reason",
        "resource_id_ref",
        "resource_ref",
        "session_id",
        "sort_by",
        "sort_order",
        "source_name",
        "status",
        "tag_mode",
        "task_type",
        "temp_file_id",
        "time_field",
        "to_ref",
        "until",
        "since",
    }
)
LIST_FIELDS = frozenset({"exclude_uris", "tags"})
OBJECT_FIELDS = frozenset({"args", "detail", "filter", "quotas"})
SAFE_IMPORT_ARG_FIELDS = frozenset(
    {
        "allow_external_links",
        "branch",
        "commit",
        "depth",
        "exclude_paths",
        "include_paths",
        "max_pages",
        "parse_mode",
        "site",
        "skip_download_links",
    }
)
FORBIDDEN_BROWSER_FIELDS = frozenset(
    {
        "account",
        "account_id",
        "api_key",
        "auth_config",
        "authorization",
        "credential",
        "credentials",
        "feishu_access_token",
        "feishu_app_secret",
        "feishu_refresh_token",
        "owner",
        "owner_id",
        "password",
        "principal_id",
        "secret",
        "token",
        "user",
        "user_id",
    }
)


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

    @staticmethod
    def _normalize_base_path(path: str) -> str:
        if path in {"", "/"}:
            return ""
        if not path.startswith("/") or re.search(r"%(?![0-9A-Fa-f]{2})", path):
            raise OpenVikingError(
                "INVALID_BASE_URL", "Base URL must have a safe path", 422
            )

        def decode_unreserved(match: re.Match[str]) -> str:
            character = chr(int(match.group(1), 16))
            if character not in URL_UNRESERVED_CHARACTERS:
                raise OpenVikingError(
                    "INVALID_BASE_URL", "Base URL must have a safe path", 422
                )
            return character

        normalized = PERCENT_ESCAPE.sub(decode_unreserved, path).rstrip("/")
        segments = normalized[1:].split("/")
        if any(
            not segment
            or segment in {".", ".."}
            or SAFE_BASE_PATH_SEGMENT.fullmatch(segment) is None
            for segment in segments
        ):
            raise OpenVikingError(
                "INVALID_BASE_URL", "Base URL must have a safe path", 422
            )
        return normalized

    @staticmethod
    def _normalize_workspace_uri(value: str) -> str:
        if (
            "\\" in value
            or "?" in value
            or "#" in value
            or any(unicodedata.category(character) == "Cc" for character in value)
        ):
            raise OpenVikingError(
                "INVALID_ARGUMENT", "Workspace URI must be a safe viking:// URI"
            )
        try:
            parsed = urlsplit(value.strip())
        except ValueError as exc:
            raise OpenVikingError(
                "INVALID_ARGUMENT", "Workspace URI is malformed"
            ) from exc
        if (
            parsed.scheme != "viking"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise OpenVikingError(
                "INVALID_ARGUMENT", "Workspace URI must be a safe viking:// URI"
            )
        if SAFE_BASE_PATH_SEGMENT.fullmatch(parsed.netloc) is None:
            raise OpenVikingError(
                "INVALID_ARGUMENT", "Workspace URI must be a safe viking:// URI"
            )
        path = OpenVikingService._normalize_base_path(parsed.path)
        return f"viking://{parsed.netloc}{path}/"

    def _allows_dev_loopback(self, hostname: str, addresses: set[str]) -> bool:
        if not self.config.allow_loopback:
            return False
        host = hostname.casefold()
        if host == "localhost":
            return all(ipaddress.ip_address(address).is_loopback for address in addresses)
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return str(ip) in {"127.0.0.1", "::1"} and all(
            ipaddress.ip_address(address).is_loopback for address in addresses
        )

    @staticmethod
    def _join_upstream_url(base_url: str, api_path: str) -> str:
        return f"{base_url.rstrip('/')}/{api_path.lstrip('/')}"

    def _validate_base_url(self, value: str) -> str:
        if (
            "\\" in value
            or "?" in value
            or "#" in value
            or any(unicodedata.category(character) == "Cc" for character in value)
        ):
            raise OpenVikingError(
                "INVALID_BASE_URL", "Base URL must be a safe HTTPS URL", 422
            )
        try:
            parsed = urlsplit(value.strip())
            hostname = parsed.hostname
            port_number = parsed.port
            username = parsed.username
            password = parsed.password
        except ValueError as exc:
            raise OpenVikingError(
                "INVALID_BASE_URL", "Base URL is malformed", 422
            ) from exc
        if (
            parsed.scheme not in {"https", "http"}
            or not hostname
            or port_number == 0
            or username is not None
            or password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise OpenVikingError(
                "INVALID_BASE_URL",
                "Base URL must be a valid origin with an optional safe path",
                422,
            )
        path = self._normalize_base_path(parsed.path)
        host = hostname.casefold()
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    host, port_number or 443, type=socket.SOCK_STREAM
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
        dev_loopback = parsed.scheme == "http" and self._allows_dev_loopback(
            host, addresses
        )
        if parsed.scheme != "https" and not dev_loopback:
            raise OpenVikingError("INVALID_BASE_URL", "Base URL must use HTTPS", 422)
        if blocked and not dev_loopback:
            raise OpenVikingError(
                "SSRF_BLOCKED", "Base URL resolves to a restricted network", 422
            )
        serialized_host = f"[{hostname}]" if ":" in hostname else hostname
        port = f":{port_number}" if port_number is not None else ""
        return f"{parsed.scheme}://{serialized_host}{port}{path}"

    def public_profile(self, profile: OpenVikingProfile) -> dict[str, Any]:
        return {
            "profile_id": profile.profile_id,
            "display_name": profile.display_name,
            "workspace_uri": "viking://workspace/",
            "root_resource_ref": self.resource_ref(profile, profile.workspace_uri),
            "status": profile.status,
            "base_url_configured": True,
            "api_key_configured": True,
            "last_validated_at": profile.updated_at if profile.status == "ready" else None,
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
                workspace_uri=self._normalize_workspace_uri(workspace_uri),
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
                    self._normalize_workspace_uri(workspace_uri)
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
            self._validate_base_url(self._decrypt(profile.encrypted_base_url, scope)),
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

    @staticmethod
    def _reject_private_payload_fields(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if (
                    normalized in FORBIDDEN_BROWSER_FIELDS
                    or any(
                        marker in normalized
                        for marker in ("password", "secret", "credential")
                    )
                    or (
                        normalized != "max_tokens"
                        and normalized.endswith(("_token", "_tokens"))
                    )
                ):
                    raise OpenVikingError(
                        "INVALID_ARGUMENT",
                        f"Browser payload field '{key}' is not allowed",
                        422,
                    )
                if (
                    isinstance(item, str)
                    and item.startswith("viking://")
                    and normalized
                    in {
                        "parent",
                        "resource_id",
                        "root_uri",
                        "target_uri",
                        "to",
                        "to_uri",
                        "uri",
                    }
                ):
                    raise OpenVikingError(
                        "OPAQUE_RESOURCE_REF_REQUIRED",
                        "OpenViking resources must use an opaque resource reference",
                        422,
                    )
                OpenVikingService._reject_private_payload_fields(item)
        elif isinstance(value, list):
            for item in value:
                OpenVikingService._reject_private_payload_fields(item)
        elif isinstance(value, str) and value.startswith("viking://"):
            raise OpenVikingError(
                "OPAQUE_RESOURCE_REF_REQUIRED",
                "OpenViking resources must use an opaque resource reference",
                422,
            )

    @staticmethod
    def _contains_internal_uri(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(
                OpenVikingService._contains_internal_uri(item)
                for item in value.values()
            )
        if isinstance(value, list):
            return any(OpenVikingService._contains_internal_uri(item) for item in value)
        return isinstance(value, str) and value.startswith("viking://")

    @staticmethod
    def _validate_operation_payload(
        operation_name: str, payload: Mapping[str, Any]
    ) -> None:
        allowed = OPERATION_FIELDS[operation_name]
        unknown = sorted(set(payload) - allowed)
        if unknown:
            if set(unknown) & {
                "parent",
                "resource_id",
                "root_uri",
                "target_uri",
                "to",
                "to_uri",
                "uri",
            }:
                raise OpenVikingError(
                    "OPAQUE_RESOURCE_REF_REQUIRED",
                    "OpenViking resources must use an opaque resource reference",
                    422,
                )
            raise OpenVikingError(
                "INVALID_ARGUMENT",
                f"Unsupported fields for {operation_name}: {', '.join(unknown)}",
                422,
            )
        OpenVikingService._reject_private_payload_fields(payload)

        for key, value in payload.items():
            if value is None:
                continue
            if key in BOOLEAN_FIELDS and type(value) is not bool:
                raise OpenVikingError(
                    "INVALID_ARGUMENT", f"Field '{key}' must be a boolean", 422
                )
            if key in INTEGER_FIELDS and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise OpenVikingError(
                    "INVALID_ARGUMENT", f"Field '{key}' must be an integer", 422
                )
            if key in NUMBER_FIELDS and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise OpenVikingError(
                    "INVALID_ARGUMENT", f"Field '{key}' must be a number", 422
                )
            if key in STRING_FIELDS and not isinstance(value, str):
                raise OpenVikingError(
                    "INVALID_ARGUMENT", f"Field '{key}' must be a string", 422
                )
            if key in LIST_FIELDS and not isinstance(value, list):
                raise OpenVikingError(
                    "INVALID_ARGUMENT", f"Field '{key}' must be a list", 422
                )
            if key in OBJECT_FIELDS and not isinstance(value, Mapping):
                raise OpenVikingError(
                    "INVALID_ARGUMENT", f"Field '{key}' must be an object", 422
                )
        context_type = payload.get("context_type")
        if context_type is not None and not (
            isinstance(context_type, str)
            or (
                isinstance(context_type, list)
                and all(isinstance(item, str) for item in context_type)
            )
        ):
            raise OpenVikingError(
                "INVALID_ARGUMENT",
                "Field 'context_type' must be a string or string list",
                422,
            )
        rewrite = payload.get("rewrite")
        if rewrite is not None and not (type(rewrite) is bool or rewrite == "auto"):
            raise OpenVikingError(
                "INVALID_ARGUMENT",
                "Field 'rewrite' must be a boolean or 'auto'",
                422,
            )
        other_peer_penalty = payload.get("other_peer_penalty")
        if isinstance(other_peer_penalty, Mapping):
            if not all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in other_peer_penalty.values()
            ):
                raise OpenVikingError(
                    "INVALID_ARGUMENT",
                    "Field 'other_peer_penalty' values must be numbers",
                    422,
                )
        elif other_peer_penalty is not None and (
            not isinstance(other_peer_penalty, (int, float))
            or isinstance(other_peer_penalty, bool)
        ):
            raise OpenVikingError(
                "INVALID_ARGUMENT",
                "Field 'other_peer_penalty' must be a number or number map",
                422,
            )
        exclude_uris = payload.get("exclude_uris")
        if isinstance(exclude_uris, list) and exclude_uris:
            raise OpenVikingError(
                "INVALID_ARGUMENT",
                "Field 'exclude_uris' is unavailable through the browser adapter",
                422,
            )

        for key in INTEGER_FIELDS:
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                minimum = -1 if key == "limit" else 0
                maximum = (
                    1_000_000
                    if key == "offset"
                    or (key == "limit" and operation_name == "content_read")
                    else 32_000
                )
                if value < minimum or value > maximum:
                    raise OpenVikingError(
                        "INVALID_ARGUMENT", f"Field '{key}' is out of range", 422
                    )
        for key in ("timeout", "watch_interval"):
            value = payload.get(key)
            if isinstance(value, (int, float)) and (
                isinstance(value, bool) or value < 0 or value > 604_800
            ):
                raise OpenVikingError(
                    "INVALID_ARGUMENT", f"Field '{key}' is out of range", 422
                )
        args = payload.get("args")
        if isinstance(args, Mapping):
            unknown_args = sorted(set(args) - SAFE_IMPORT_ARG_FIELDS)
            if unknown_args:
                raise OpenVikingError(
                    "INVALID_ARGUMENT",
                    f"Unsupported resource import args: {', '.join(unknown_args)}",
                    422,
                )
            if OpenVikingService._contains_internal_uri(args):
                raise OpenVikingError(
                    "OPAQUE_RESOURCE_REF_REQUIRED",
                    "OpenViking resources must use an opaque resource reference",
                    422,
                )
        telemetry = payload.get("telemetry")
        if telemetry is not None and not (
            type(telemetry) is bool
            or (
                isinstance(telemetry, Mapping)
                and all(type(item) is bool for item in telemetry.values())
            )
        ):
            raise OpenVikingError(
                "INVALID_ARGUMENT",
                "Field 'telemetry' must be a boolean or boolean map",
                422,
            )

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
                    result[ref_fields[key]] = self.resource_ref(profile, normalized_uri)
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

    def _persist_and_merge_task_history(
        self,
        profile: OpenVikingProfile,
        operation_name: str,
        result: Any,
        payload: Mapping[str, Any],
    ) -> Any:
        if not isinstance(result, dict) or not isinstance(
            result.get("result"), (dict, list)
        ):
            return result
        if operation_name == "task_get":
            task = result["result"]
            if isinstance(task, dict):
                self.repository.save_task_history(profile, [task])
            return result
        if operation_name != "tasks":
            return result

        current = [item for item in result["result"] if isinstance(item, dict)]
        self.repository.save_task_history(profile, current)
        by_id = {
            item["task_id"]: item
            for item in self.repository.list_task_history(profile)
            if isinstance(item.get("task_id"), str)
        }
        by_id.update(
            {
                item["task_id"]: item
                for item in current
                if isinstance(item.get("task_id"), str)
            }
        )
        tasks = list(by_id.values())
        task_type = payload.get("task_type")
        status = payload.get("status")
        resource_id = payload.get("resource_id")
        if isinstance(task_type, str):
            tasks = [item for item in tasks if item.get("task_type") == task_type]
        if isinstance(status, str):
            tasks = [item for item in tasks if item.get("status") == status]
        if isinstance(resource_id, str):
            public_resource = self._sanitize(profile, {"resource_id": resource_id})
            tasks = [
                item
                for item in tasks
                if item.get("resource_id") == public_resource.get("resource_id")
            ]
        tasks.sort(
            key=lambda item: float(item.get("created_at") or 0),
            reverse=True,
        )
        limit = payload.get("limit", 50)
        if not isinstance(limit, int) or isinstance(limit, bool):
            limit = 50
        result["result"] = tasks[: max(0, min(limit, 200))]
        return result

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
        browser_payload = dict(payload or {})
        self._validate_operation_payload(operation_name, browser_payload)
        body = self._replace_refs(profile, browser_payload)
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
        if operation_name in {"find", "search"}:
            image_url = body.get("image_url")
            if isinstance(image_url, str) and (
                image_url.startswith("http://") or image_url.startswith("https://")
            ):
                self._validate_import_url(image_url)
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
            if operation_name == "session_commit":
                path += "/commit"
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
            response = await client.request(
                operation.method, self._join_upstream_url(base_url, path), **kwargs
            )
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
            sanitized = self._sanitize(profile, result)
            return self._persist_and_merge_task_history(
                profile, operation_name, sanitized, body
            )
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
        return await self._import_text_file(
            profile,
            parent_ref=parent_ref,
            filename=name,
            content=content,
            content_type="text/markdown"
            if name.casefold().endswith(".md")
            else "text/plain",
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
        name = filename.strip()
        if (
            not SAFE_RESOURCE_NAME.fullmatch(name)
            or name in {".", ".."}
            or not name.casefold().endswith(".json")
        ):
            raise OpenVikingError(
                "INVALID_ARGUMENT",
                "Connection resource filename must use .json",
                422,
            )
        return await self._import_text_file(
            profile,
            parent_ref=parent_ref,
            filename=name,
            content=content,
            content_type="application/json",
        )

    async def _import_text_file(
        self,
        profile: OpenVikingProfile,
        *,
        parent_ref: str,
        filename: str,
        content: str,
        content_type: str,
    ) -> Any:
        if parent_ref.startswith("viking://"):
            raise OpenVikingError(
                "OPAQUE_RESOURCE_REF_REQUIRED",
                "OpenViking resources must use an opaque resource reference",
                422,
            )
        self.resolve_ref(profile, parent_ref)
        uploaded = await self.upload(
            profile,
            filename=filename,
            content_type=content_type,
            content=content.encode("utf-8"),
        )
        result = uploaded.get("result") if isinstance(uploaded, Mapping) else None
        temp_file_id = (
            result.get("temp_file_id") if isinstance(result, Mapping) else None
        )
        if not isinstance(temp_file_id, str) or not temp_file_id:
            raise OpenVikingError(
                "OPENVIKING_INVALID_RESPONSE",
                "OpenViking upload did not return a temporary file id",
                502,
            )
        return await self.request(
            profile,
            "resource_import",
            payload={
                "temp_file_id": temp_file_id,
                "parent_ref": parent_ref,
                "wait": True,
                "timeout": self.config.timeout_seconds,
            },
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
                self._join_upstream_url(base_url, "/api/v1/resources/temp_upload"),
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
