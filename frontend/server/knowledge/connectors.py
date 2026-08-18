# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Knowledge source connectors that reuse Studio's Viking import path."""

from __future__ import annotations

import hashlib
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from frontend.server.knowledge_assets.contract import KnowledgeAssetRegistry

from .service import KnowledgeAccessError, KnowledgeIdentity, KnowledgeService
from .web_import import MAX_MARKDOWN_BYTES, _extract_visible_body_markdown

SourceType = Literal["feishu_doc", "local_web", "intranet_web"]
ContentFormat = Literal["markdown", "html"]

_REDACTED = "[REDACTED]"
_SECRET_TEXT = re.compile(
    r"(?i)\b(?:authorization\s*:\s*bearer|bearer|cookie\s*:|set-cookie\s*:|"
    r"access[_-]?token|refresh[_-]?token|session[_-]?token|api[_-]?key|"
    r"client[_-]?secret|password)\b"
)
_SENSITIVE_METADATA_KEYS = {
    "authorization",
    "cookie",
    "setcookie",
    "password",
    "token",
    "accesstoken",
    "refreshtoken",
    "sessiontoken",
    "apikey",
    "clientsecret",
    "secret",
}
_SUPPORTED_FEISHU_HOSTS = {
    "feishu.cn",
    "larksuite.com",
    "larkoffice.com",
}
FEISHU_MINIMAL_SCOPES = ("docs:doc:readonly", "wiki:wiki:readonly")


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ConnectorModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="ignore",
    )


class LocalWebImportBody(ConnectorModel):
    source_type: Literal["local_web", "intranet_web"]
    source_url: str = Field(min_length=1, max_length=4096)
    content_format: ContentFormat
    content: str = Field(min_length=1)
    access_mode: Literal["user_local"] = "user_local"
    name: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeishuAuthorizeResponse(ConnectorModel):
    status: Literal["configured", "not_configured"]
    authorization_url: str = ""
    scopes: list[str]
    message: str = ""


class FeishuOAuthCallbackBody(ConnectorModel):
    code: str = Field(min_length=1, max_length=4096)
    redirect_uri: str = Field(min_length=1, max_length=4096)


class FeishuOAuthCallbackResponse(ConnectorModel):
    status: Literal["connected"]
    credential_id: str = ""
    scopes: list[str]


class FeishuImportBody(ConnectorModel):
    doc_url: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("doc_url")
    @classmethod
    def validate_doc_url(cls, value: str) -> str:
        return _validate_feishu_url(value)


@dataclass(frozen=True, slots=True)
class FeishuDocumentExport:
    markdown: str
    title: str
    source_url: str
    space_id: str
    source_id: str
    external_doc_token: str
    revision: str
    permission_scope: str
    captured_at: str


class FeishuTokenExpiredError(RuntimeError):
    """Raised when a saved Feishu refresh token must be reconnected."""


class FeishuConnector(Protocol):
    def authorization_url(self, *, owner_id: str) -> str: ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Mapping[str, Any]:
        ...

    async def import_document(
        self,
        *,
        doc_url: str,
        owner_id: str,
        refresh_token: str,
    ) -> FeishuDocumentExport: ...


class CredentialRegistry(Protocol):
    async def save_credential(
        self,
        *,
        owner_id: str,
        provider: str,
        credential: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _safe_source_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_sensitive_key(key)
        ],
        doseq=True,
    )
    hostname = parsed.hostname or parsed.netloc
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{display_host}{port}", parsed.path, query, ""))


def _is_sensitive_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return normalized in _SENSITIVE_METADATA_KEYS or normalized.endswith(
        ("password", "secret", "token", "credential", "cookie", "apikey")
    )


def _public_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in metadata.items()
        if isinstance(key, str) and not _is_sensitive_key(key)
    }


def _assert_no_browser_secrets(text: str) -> None:
    if _SECRET_TEXT.search(text):
        raise KnowledgeAccessError(
            "提交内容包含浏览器凭据或登录态信息，请移除 cookie、Authorization header 或 token 后重试。",
            status_code=422,
            error_code="KNOWLEDGE_CONNECTOR_BROWSER_SECRET",
        )


def _content_hash(markdown: str) -> str:
    return "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _captured_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _markdown_from_local_content(body: LocalWebImportBody) -> tuple[str, str]:
    _assert_no_browser_secrets(body.content)
    if body.content_format == "markdown":
        markdown = body.content.strip()
        title = ""
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                break
        if not title:
            title = body.name or "本地网页"
    else:
        extracted, title = _extract_visible_body_markdown(body.content.encode("utf-8"))
        markdown = extracted.strip()
        title = title.strip() or body.name or "本地网页"
    if not markdown:
        raise KnowledgeAccessError(
            "提交内容没有可导入的正文，请粘贴已清洗的 HTML 或 Markdown。",
            status_code=422,
            error_code="KNOWLEDGE_CONNECTOR_CONTENT_EMPTY",
        )
    if len(markdown.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise KnowledgeAccessError(
            "提交内容超过 2 MB，请缩小内容范围后重试。",
            status_code=413,
            error_code="KNOWLEDGE_CONNECTOR_CONTENT_TOO_LARGE",
        )
    _assert_no_browser_secrets(markdown)
    return markdown, (body.name or title or "本地网页")[:256]


def _validate_feishu_url(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except (UnicodeError, ValueError) as error:
        raise ValueError("Feishu document URL is invalid.") from error
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or not host:
        raise ValueError("Feishu document URL must be HTTPS.")
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in _SUPPORTED_FEISHU_HOSTS):
        raise ValueError("Only Feishu/Lark document URLs are supported.")
    if not any(marker in parsed.path for marker in ("/doc", "/docx", "/wiki")):
        raise ValueError("Only Feishu doc/wiki resources are supported in this phase.")
    return _safe_source_url(candidate)


def _target_metadata(knowledge_id: str, region: str) -> dict[str, str]:
    return {"id": knowledge_id, "region": region}


def _duplicate_content_guard(
    service: KnowledgeService,
    *,
    knowledge_id: str,
    identity: KnowledgeIdentity,
    region: str,
    content_hash: str,
) -> None:
    offset = 0
    for _ in range(100):
        documents, has_more = service.list_documents(
            knowledge_id,
            identity=identity,
            region=region,
            offset=offset,
            limit=100,
            document_type=None,
        )
        for document in documents:
            metadata = document.get("metadata")
            if isinstance(metadata, Mapping) and metadata.get("content_hash") == content_hash:
                raise KnowledgeAccessError(
                    "相同内容已经导入到这个知识库。",
                    status_code=409,
                    error_code="KNOWLEDGE_CONNECTOR_DUPLICATE_CONTENT",
                )
        if not has_more:
            return
        offset += len(documents)
        if not documents:
            return


def _upload_markdown(
    service: KnowledgeService,
    *,
    knowledge_id: str,
    identity: KnowledgeIdentity,
    region: str,
    markdown: str,
    name: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            suffix=".md",
        ) as temp:
            temp_path = Path(temp.name)
            temp.write(markdown)
        return service.upload_document(
            knowledge_id,
            identity=identity,
            region=region,
            source=temp_path,
            file_name=f"connector-{hashlib.sha256(markdown.encode()).hexdigest()[:16]}.txt",
            mime_type="text/plain",
            name=name,
            document_type="txt",
            metadata=metadata,
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def import_local_web_document(
    service: KnowledgeService,
    *,
    knowledge_id: str,
    identity: KnowledgeIdentity,
    region: str,
    body: LocalWebImportBody,
) -> dict[str, Any]:
    markdown, title = _markdown_from_local_content(body)
    content_hash = _content_hash(markdown)
    _duplicate_content_guard(
        service,
        knowledge_id=knowledge_id,
        identity=identity,
        region=region,
        content_hash=content_hash,
    )
    safe_url = _safe_source_url(body.source_url)
    metadata = {
        **_public_metadata(body.metadata),
        "source_type": body.source_type,
        "source_url": safe_url,
        "captured_at": _captured_at(),
        "content_hash": content_hash,
        "access_mode": body.access_mode,
        "deployment_note": (
            "Authenticated local capture is disabled by default in hosted deployments."
        ),
        "_veadk_source_url": safe_url,
        "_veadk_source_title": title,
        "_veadk_content_format": "markdown",
        "_veadk_fetched_at": _captured_at(),
    }
    result = _upload_markdown(
        service,
        knowledge_id=knowledge_id,
        identity=identity,
        region=region,
        markdown=markdown,
        name=title,
        metadata=metadata,
    )
    return {
        **result,
        "sourceMarkdown": markdown,
        "metadata": {
            **result.get("metadata", {}),
            **metadata,
            "targetKnowledgeBase": _target_metadata(knowledge_id, region),
        },
    }


def feishu_authorization(
    *,
    connector: FeishuConnector | None,
    identity: KnowledgeIdentity,
) -> FeishuAuthorizeResponse:
    if connector is None:
        return FeishuAuthorizeResponse(
            status="not_configured",
            scopes=list(FEISHU_MINIMAL_SCOPES),
            message="Feishu connector is not configured.",
        )
    return FeishuAuthorizeResponse(
        status="configured",
        authorization_url=connector.authorization_url(owner_id=identity.owner_id),
        scopes=list(FEISHU_MINIMAL_SCOPES),
    )


async def save_feishu_oauth_callback(
    *,
    connector: FeishuConnector | None,
    registry: CredentialRegistry | KnowledgeAssetRegistry | None,
    identity: KnowledgeIdentity,
    body: FeishuOAuthCallbackBody,
) -> FeishuOAuthCallbackResponse:
    save_credential = getattr(registry, "save_credential", None)
    if connector is None or registry is None or not callable(save_credential):
        raise KnowledgeAccessError(
            "飞书连接器尚未配置，请联系管理员启用 OAuth 连接。",
            status_code=503,
            error_code="KNOWLEDGE_FEISHU_NOT_CONFIGURED",
        )
    token = await connector.exchange_code(
        code=body.code,
        redirect_uri=body.redirect_uri,
    )
    refresh_token = str(token.get("refresh_token") or "").strip()
    if not refresh_token:
        raise KnowledgeAccessError(
            "飞书 OAuth 未返回 refresh token，请重新授权。",
            status_code=502,
            error_code="KNOWLEDGE_FEISHU_REFRESH_TOKEN_MISSING",
        )
    scope = str(token.get("scope") or " ".join(FEISHU_MINIMAL_SCOPES)).strip()
    saved = await save_credential(
        owner_id=identity.owner_id,
        provider="feishu",
        credential={"refresh_token": refresh_token},
        metadata={
            "scope": scope,
            "permission_scope": scope,
            "connected_at": _captured_at(),
        },
    )
    credential_id = str(
        saved.get("credentialId")
        or saved.get("credential_id")
        or saved.get("id")
        or ""
    )
    return FeishuOAuthCallbackResponse(
        status="connected",
        credential_id=credential_id,
        scopes=scope.split(),
    )


def _saved_feishu_refresh_token(
    registry: CredentialRegistry | KnowledgeAssetRegistry | None,
    *,
    owner_id: str,
) -> str:
    saved = getattr(registry, "saved", None)
    if isinstance(saved, list):
        for item in reversed(saved):
            if not isinstance(item, Mapping):
                continue
            if item.get("owner_id") != owner_id or item.get("provider") != "feishu":
                continue
            credential = item.get("credential")
            if isinstance(credential, Mapping):
                token = str(credential.get("refresh_token") or "").strip()
                if token:
                    return token
    return ""


async def import_feishu_document(
    service: KnowledgeService,
    *,
    connector: FeishuConnector | None,
    registry: CredentialRegistry | KnowledgeAssetRegistry | None,
    knowledge_id: str,
    identity: KnowledgeIdentity,
    region: str,
    body: FeishuImportBody,
) -> dict[str, Any]:
    if connector is None:
        raise KnowledgeAccessError(
            "飞书连接器尚未配置，请联系管理员启用 OAuth 连接。",
            status_code=503,
            error_code="KNOWLEDGE_FEISHU_NOT_CONFIGURED",
        )
    refresh_token = _saved_feishu_refresh_token(registry, owner_id=identity.owner_id)
    if not refresh_token:
        raise KnowledgeAccessError(
            "飞书授权已过期或尚未连接，请重新授权。",
            status_code=401,
            error_code="KNOWLEDGE_FEISHU_AUTH_EXPIRED",
        )
    try:
        exported = await connector.import_document(
            doc_url=body.doc_url,
            owner_id=identity.owner_id,
            refresh_token=refresh_token,
        )
    except FeishuTokenExpiredError as error:
        raise KnowledgeAccessError(
            "飞书授权已过期，请重新授权后再导入。",
            status_code=401,
            error_code="KNOWLEDGE_FEISHU_AUTH_EXPIRED",
        ) from error
    markdown = exported.markdown.strip()
    _assert_no_browser_secrets(markdown)
    if not markdown:
        raise KnowledgeAccessError(
            "飞书文档没有可导入内容。",
            status_code=422,
            error_code="KNOWLEDGE_FEISHU_CONTENT_EMPTY",
        )
    if len(markdown.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise KnowledgeAccessError(
            "飞书文档超过 2 MB，请缩小文档范围后重试。",
            status_code=413,
            error_code="KNOWLEDGE_FEISHU_CONTENT_TOO_LARGE",
        )
    content_hash = _content_hash(markdown)
    _duplicate_content_guard(
        service,
        knowledge_id=knowledge_id,
        identity=identity,
        region=region,
        content_hash=content_hash,
    )
    safe_url = _safe_source_url(exported.source_url or body.doc_url)
    title = (body.name or exported.title or "飞书文档")[:256]
    metadata = {
        **_public_metadata(body.metadata),
        "space_id": exported.space_id,
        "source_id": exported.source_id,
        "source_type": "feishu_doc",
        "external_doc_token": exported.external_doc_token,
        "source_url": safe_url,
        "revision": exported.revision,
        "permission_scope": exported.permission_scope,
        "content_hash": content_hash,
        "captured_at": exported.captured_at or _captured_at(),
        "_veadk_source_url": safe_url,
        "_veadk_source_title": title,
        "_veadk_content_format": "markdown",
        "_veadk_fetched_at": exported.captured_at or _captured_at(),
    }
    result = _upload_markdown(
        service,
        knowledge_id=knowledge_id,
        identity=identity,
        region=region,
        markdown=markdown,
        name=title,
        metadata=metadata,
    )
    return {
        **result,
        "sourceMarkdown": markdown,
        "metadata": {
            **result.get("metadata", {}),
            **metadata,
            "targetKnowledgeBase": _target_metadata(knowledge_id, region),
        },
    }
