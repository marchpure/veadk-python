"""Fail-closed orchestration for business-facing MCP publications."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from frontend.server.knowledge_workspace.connection import ConnectionServiceGateway
from frontend.server.knowledge_workspace.service import Actor

from .credential import CredentialProviderPort
from .domain import (
    ActionPolicy,
    ManagedPublication,
    ManagedPublicationCreateRequest,
    ManagedPublicationStatus,
    ManagedPublicationView,
    ManagedRevision,
    ManagedRevisionRequest,
    OperationStage,
    PublicationAuditEvent,
    PublicationOperation,
    PublicationSubject,
    RevisionState,
)
from .domain_repository import ManagedPublicationRepository
from .models import PublicationCreateRequest, PublicationStatus
from .service import AgentKitMcpPublisher, publication_key

_READ_ACTION = re.compile(
    r"(?:^|[._:/-])(get|list|read|search|query|describe|show|fetch|inspect|preview)(?:$|[._:/-])",
    re.IGNORECASE,
)
_SECRET = re.compile(
    r"(?i)(bearer\s+\S+|(?:api[_ -]?key|token|secret|password|cookie|authorization)\s*[:=]\s*\S+)"
)


class ManagedPublicationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class ManagedPublicationService:
    def __init__(
        self,
        repository: ManagedPublicationRepository,
        connection_gateway: ConnectionServiceGateway,
        credential_provider: CredentialProviderPort,
        gateway_publisher: AgentKitMcpPublisher,
        *,
        jwt_discovery_url: str,
    ) -> None:
        self.repository = repository
        self.connection_gateway = connection_gateway
        self.credential_provider = credential_provider
        self.gateway_publisher = gateway_publisher
        self.jwt_discovery_url = jwt_discovery_url.strip()

    @property
    def capabilities(self) -> dict[str, object]:
        return {
            "audienceTypes": ["applications"],
            "usersAndGroups": {
                "enabled": False,
                "reason": "当前环境未配置可执行的 Publication Access Broker。",
            },
        }

    async def create(
        self, request: ManagedPublicationCreateRequest, actor: Actor, request_id: str
    ) -> ManagedPublicationView:
        digest = _digest(request.model_dump(mode="json", by_alias=True))
        existing = self.repository.find_operation(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            idempotency_key=request.idempotency_key,
        )
        if existing:
            if existing.request_digest != digest:
                raise ManagedPublicationError(
                    "IDEMPOTENCY_CONFLICT",
                    "idempotencyKey was reused with different input",
                    status_code=409,
                )
            return self.get(existing.publication_id, actor)
        publication = ManagedPublication(
            id=f"mpub_{uuid4().hex}",
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            name=request.name,
            status=ManagedPublicationStatus.DRAFT,
            created_by=actor.principal_id,
        )
        revision = ManagedRevision(
            id=f"mrev_{uuid4().hex}",
            publication_id=publication.id,
            version=1,
            connection_scope=request.connection_ids,
            action_policy_source=request.action_policy,
            audience_type=request.audience.type,
        )
        operation = PublicationOperation(
            operation_id=f"op_{uuid4().hex}",
            publication_id=publication.id,
            revision_id=revision.id,
            idempotency_key=request.idempotency_key,
            request_digest=digest,
            stage=OperationStage.DRAFT_SAVED,
        )
        self.repository.save_publication(publication)
        self.repository.save_revision(revision)
        self.repository.reserve_operation(operation)
        self.repository.replace_subjects(
            revision.id, _subjects(publication.id, revision.id, request.audience)
        )
        self._audit(publication, revision, actor, "publication.created", request_id)
        return await self._provision(
            publication, revision, operation, actor, request_id
        )

    async def create_revision(
        self,
        publication: ManagedPublication,
        request: ManagedRevisionRequest,
        actor: Actor,
        request_id: str,
    ) -> ManagedPublicationView:
        self._ensure_mutable(publication)
        if publication.status == ManagedPublicationStatus.DISABLED:
            raise ManagedPublicationError(
                "PUBLICATION_DISABLED",
                "Disabled publications cannot be modified",
                status_code=409,
            )
        digest = _digest(request.model_dump(mode="json", by_alias=True))
        existing = next(
            (
                item
                for item in self.repository.list_operations(publication.id)
                if item.idempotency_key == request.idempotency_key
            ),
            None,
        )
        if existing:
            if existing.request_digest != digest:
                raise ManagedPublicationError(
                    "IDEMPOTENCY_CONFLICT",
                    "idempotencyKey was reused with different input",
                    status_code=409,
                )
            return self.view(publication)
        revision = ManagedRevision(
            id=f"mrev_{uuid4().hex}",
            publication_id=publication.id,
            version=max(
                (
                    item.version
                    for item in self.repository.list_revisions(publication.id)
                ),
                default=0,
            )
            + 1,
            connection_scope=request.connection_ids,
            action_policy_source=request.action_policy,
            audience_type=request.audience.type,
        )
        operation = PublicationOperation(
            operation_id=f"op_{uuid4().hex}",
            publication_id=publication.id,
            revision_id=revision.id,
            idempotency_key=request.idempotency_key,
            request_digest=digest,
            stage=OperationStage.DRAFT_SAVED,
        )
        publication.status = ManagedPublicationStatus.UPDATING
        self.repository.save_publication(publication)
        self.repository.save_revision(revision)
        self.repository.reserve_operation(operation)
        self.repository.replace_subjects(
            revision.id, _subjects(publication.id, revision.id, request.audience)
        )
        self._audit(publication, revision, actor, "revision.created", request_id)
        return await self._provision(
            publication, revision, operation, actor, request_id
        )

    async def retry(
        self, publication: ManagedPublication, actor: Actor, request_id: str
    ) -> ManagedPublicationView:
        self._ensure_mutable(publication)
        operation = next(
            (
                item
                for item in self.repository.list_operations(publication.id)
                if item.stage == OperationStage.FAILED
            ),
            None,
        )
        if not operation:
            raise ManagedPublicationError(
                "PUBLICATION_NOT_FAILED",
                "No failed publication operation can be retried",
                status_code=409,
            )
        revision = self.repository.get_revision(operation.revision_id)
        assert revision is not None
        operation.attempt += 1
        operation.last_error = None
        publication.status = ManagedPublicationStatus.RETRYING
        revision.state = RevisionState.PROVISIONING
        self._save(publication, revision, operation)
        return await self._provision(
            publication, revision, operation, actor, request_id
        )

    async def verify(
        self, publication: ManagedPublication, actor: Actor, request_id: str
    ) -> ManagedPublicationView:
        self._ensure_mutable(publication)
        revision = self._active_or_latest(publication)
        result = await self.gateway_publisher.verify(
            self._low_level(revision, publication)
        )
        revision.verification_summary = result.model_dump(mode="json")
        if not result.live:
            raise ManagedPublicationError(
                "VERIFICATION_FAILED",
                "Gateway positive and negative verification did not both pass",
                status_code=502,
                retryable=True,
            )
        revision.state = RevisionState.ACTIVE
        publication.status = ManagedPublicationStatus.ACTIVE
        publication.active_revision_id = revision.id
        self.repository.save_revision(revision)
        self.repository.save_publication(publication)
        self._audit(publication, revision, actor, "publication.verified", request_id)
        return self.view(publication)

    async def rotate(
        self, publication: ManagedPublication, actor: Actor, request_id: str
    ) -> ManagedPublicationView:
        self._ensure_mutable(publication)
        active = self._active_or_latest(publication)
        revision_request = ManagedRevisionRequest.model_validate(
            {
                "connectionIds": active.connection_scope,
                "actionPolicy": active.action_policy_source,
                "audience": _audience_from_subjects(
                    active.id, self.repository.list_subjects(publication.id)
                ),
                "idempotencyKey": f"rotate-{publication.id}-{uuid4()}",
            }
        )
        return await self.create_revision(
            publication,
            revision_request,
            actor,
            request_id,
        )

    async def disable(
        self, publication: ManagedPublication, actor: Actor, request_id: str
    ) -> ManagedPublicationView:
        self._ensure_mutable(publication)
        if publication.status == ManagedPublicationStatus.DISABLED:
            return self.view(publication)
        revision = self._active_or_latest(publication)
        publication.status = ManagedPublicationStatus.DISABLING
        self.repository.save_publication(publication)
        await self.gateway_publisher.disable(self._low_level(revision, publication))
        if revision.runtime_token_record_id:
            await self.connection_gateway.revoke_runtime_token(
                revision.runtime_token_record_id, **_actor_kwargs(actor)
            )
        if revision.credential_provider_ref:
            await self.credential_provider.delete(revision.credential_provider_ref)
        revision.state = RevisionState.DISABLED
        publication.status = ManagedPublicationStatus.DISABLED
        self.repository.save_revision(revision)
        self.repository.save_publication(publication)
        self._audit(publication, revision, actor, "publication.disabled", request_id)
        return self.view(publication)

    def list(self, actor: Actor) -> tuple[ManagedPublicationView, ...]:
        return tuple(
            self.view(item)
            for item in self.repository.list_publications(
                tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
            )
        )

    def get(self, publication_id: str, actor: Actor) -> ManagedPublicationView:
        return self.view(self.require(publication_id, actor))

    def require(self, publication_id: str, actor: Actor) -> ManagedPublication:
        value = self.repository.get_publication(
            publication_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if value is None:
            raise ManagedPublicationError(
                "NOT_FOUND", "Publication not found", status_code=404
            )
        return value

    def _ensure_mutable(self, publication: ManagedPublication) -> None:
        if publication.status == ManagedPublicationStatus.EXTERNAL_MANAGED:
            raise ManagedPublicationError(
                "EXTERNAL_MANAGED_READ_ONLY",
                "Imported AgentKit publications are read-only and must be managed externally",
                status_code=409,
            )

    def view(self, publication: ManagedPublication) -> ManagedPublicationView:
        revisions = self.repository.list_revisions(publication.id)
        active = next(
            (item for item in revisions if item.id == publication.active_revision_id),
            None,
        )
        return ManagedPublicationView(
            publication=publication,
            activeRevision=active,
            revisions=revisions,
            subjects=self.repository.list_subjects(publication.id),
            operations=self.repository.list_operations(publication.id),
            auditEvents=self.repository.list_audit(publication.id),
            capabilities=self.capabilities,
        )

    async def _provision(
        self,
        publication: ManagedPublication,
        revision: ManagedRevision,
        operation: PublicationOperation,
        actor: Actor,
        request_id: str,
    ) -> ManagedPublicationView:
        publication.status = (
            ManagedPublicationStatus.UPDATING
            if publication.active_revision_id
            else ManagedPublicationStatus.PROVISIONING
        )
        revision.state = RevisionState.PROVISIONING
        self._save(publication, revision, operation)
        try:
            if revision.audience_type != "applications":
                raise ManagedPublicationError(
                    "AUDIENCE_NOT_ENFORCEABLE",
                    "User and group authorization is unavailable in this environment",
                )
            if not self.jwt_discovery_url:
                raise ManagedPublicationError(
                    "IDENTITY_NOT_CONFIGURED",
                    "Application identity discovery is not configured",
                    status_code=503,
                )
            endpoint, actions = await self._resolve_scope(
                revision.connection_scope, revision.action_policy_source, actor
            )
            revision.endpoint_ref = endpoint
            revision.resolved_action_scope = actions
            operation.stage = OperationStage.VALIDATED
            self._save(publication, revision, operation)
            if (
                revision.runtime_token_record_id
                and not revision.credential_provider_ref
            ):
                # The one-time secret cannot be recovered after a process crash.
                # Revoke that orphan and create a fresh idempotency generation.
                await self.connection_gateway.revoke_runtime_token(
                    revision.runtime_token_record_id, **_actor_kwargs(actor)
                )
                revision.runtime_token_record_id = None
                self._save(publication, revision, operation)
            if not revision.runtime_token_record_id:
                (
                    record_id,
                    plaintext,
                ) = await self.connection_gateway.create_runtime_token(
                    name=f"{publication.name}-v{revision.version}",
                    allowed_connections=revision.connection_scope,
                    allowed_actions=revision.resolved_action_scope,
                    idempotency_key=(
                        f"{publication.id}:{revision.id}:runtime-token:{operation.attempt}"
                    ),
                    **_actor_kwargs(actor),
                )
                revision.runtime_token_record_id = record_id
                operation.stage = OperationStage.RUNTIME_TOKEN_CREATED
                self._save(publication, revision, operation)
                revision.credential_provider_ref = (
                    await self.credential_provider.create(
                        name=f"dw-{publication.id}-{revision.version}",
                        plaintext=plaintext,
                    )
                )
                plaintext = ""
                operation.stage = OperationStage.CREDENTIAL_MANAGED
                self._save(publication, revision, operation)
            if not revision.credential_provider_ref:
                raise ManagedPublicationError(
                    "UPSTREAM_CREDENTIAL_FAILED",
                    "Publication credential was not managed",
                    status_code=502,
                    retryable=True,
                )
            clients = [
                item.subject_ref
                for item in self.repository.list_subjects(publication.id)
                if item.revision_id == revision.id
                and item.subject_type == "application"
            ]
            low = await self.gateway_publisher.create_or_reuse(
                tenant_id=publication.tenant_id,
                workspace_id=publication.workspace_id,
                request=PublicationCreateRequest(
                    accessPackageId=revision.id,
                    runtimeTokenId=revision.credential_provider_ref,
                    backendEndpointRef=revision.endpoint_ref,
                    desiredVersion=f"v{revision.version}",
                    allowedClientRef=clients[0],
                    allowedClientRefs=tuple(clients),
                    customJwtDiscoveryUrl=self.jwt_discovery_url,
                ),
            )
            revision.mcp_service_id = low.mcp_service_id
            revision.toolset_id = low.toolset_id
            revision.gateway_endpoint = low.gateway_endpoint
            revision.identity_binding_ref = (
                f"toolset://{low.toolset_id}/custom-jwt" if low.toolset_id else None
            )
            if low.request_id:
                operation.external_request_ids = tuple(
                    dict.fromkeys((*operation.external_request_ids, low.request_id))
                )
            if low.status == PublicationStatus.FAILED:
                raise ManagedPublicationError(
                    "GATEWAY_PROVISION_FAILED",
                    "AgentKit Gateway provisioning failed",
                    status_code=502,
                    retryable=True,
                )
            operation.stage = OperationStage.VERIFYING
            publication.status = ManagedPublicationStatus.VERIFYING
            revision.state = RevisionState.VERIFYING
            self._save(publication, revision, operation)
            result = await self.gateway_publisher.verify(low)
            revision.verification_summary = result.model_dump(mode="json")
            if not result.live:
                raise ManagedPublicationError(
                    "VERIFICATION_FAILED",
                    "Gateway positive and negative verification did not both pass",
                    status_code=502,
                    retryable=True,
                )
            previous = (
                self.repository.get_revision(publication.active_revision_id)
                if publication.active_revision_id
                else None
            )
            revision.state = RevisionState.ACTIVE
            publication.active_revision_id = revision.id
            publication.status = ManagedPublicationStatus.ACTIVE
            operation.stage = OperationStage.COMPLETE
            operation.last_error = None
            self._save(publication, revision, operation)
            if previous and previous.id != revision.id:
                await self._retire(previous, publication, actor)
            self._audit(publication, revision, actor, "revision.activated", request_id)
        except Exception as error:
            publication.status = ManagedPublicationStatus.FAILED
            revision.state = RevisionState.FAILED
            operation.stage = OperationStage.FAILED
            operation.last_error = _safe_error(error)
            self._save(publication, revision, operation)
            self._audit(publication, revision, actor, "provisioning.failed", request_id)
        return self.view(publication)

    async def _resolve_scope(
        self, connection_ids: tuple[str, ...], policy: ActionPolicy, actor: Actor
    ) -> tuple[str, tuple[str, ...]]:
        if not connection_ids:
            raise ManagedPublicationError(
                "EMPTY_CONNECTION_SCOPE", "At least one connection is required"
            )
        actor_kwargs = _actor_kwargs(actor)
        visible = {
            item["connection_id"]: item
            for item in await self.connection_gateway.list_connections(**actor_kwargs)
            if item["connection_id"] in connection_ids
        }
        if len(visible) != len(set(connection_ids)):
            raise ManagedPublicationError(
                "CONNECTION_SCOPE_FORBIDDEN",
                "One or more connections are not visible in this tenant and workspace",
                status_code=403,
            )
        if any(str(item.get("status")) != "ready" for item in visible.values()):
            raise ManagedPublicationError(
                "CONNECTION_NOT_READY",
                "Every selected connection must be ready",
                status_code=409,
            )
        catalog = {
            item["connector_key"]: item
            for item in await self.connection_gateway.catalog(**actor_kwargs)
        }
        actions: list[str] = []
        for connection in visible.values():
            definition = catalog.get(connection["connector_key"]) or {}
            available = tuple(
                str(item)
                for item in (
                    definition.get("action_ids") or definition.get("actionIds", [])
                )
                if str(item)
            )
            actions.extend(resolve_actions(available, policy))
        resolved = tuple(dict.fromkeys(actions))
        if not resolved:
            raise ManagedPublicationError(
                "EMPTY_ACTION_SCOPE", "Action policy resolved to an empty allowlist"
            )
        selected_endpoints = tuple(
            _normalize_mcp_endpoint(str(item.get("mcp_endpoint") or ""))
            for item in visible.values()
        )
        if any(not endpoint for endpoint in selected_endpoints):
            raise ManagedPublicationError(
                "CONNECTION_NOT_READY",
                "Every selected connection must have a registered OpenConnector MCP endpoint",
                status_code=409,
            )
        endpoints = tuple(dict.fromkeys(selected_endpoints))
        if len(endpoints) > 1:
            raise ManagedPublicationError(
                "MIXED_MCP_ENDPOINTS",
                "Selected connections must share one OpenConnector MCP endpoint",
            )
        return endpoints[0], resolved

    async def _retire(
        self, revision: ManagedRevision, publication: ManagedPublication, actor: Actor
    ) -> None:
        await self.gateway_publisher.disable(self._low_level(revision, publication))
        if revision.runtime_token_record_id:
            await self.connection_gateway.revoke_runtime_token(
                revision.runtime_token_record_id, **_actor_kwargs(actor)
            )
        if revision.credential_provider_ref:
            await self.credential_provider.delete(revision.credential_provider_ref)
        revision.state = RevisionState.RETIRED
        self.repository.save_revision(revision)

    def _low_level(self, revision: ManagedRevision, publication: ManagedPublication):
        value = self.gateway_publisher.repository.get_by_key(
            publication_key(
                publication.workspace_id, revision.id, f"v{revision.version}"
            ),
            tenant_id=publication.tenant_id,
            workspace_id=publication.workspace_id,
        )
        if value is None:
            raise ManagedPublicationError(
                "GATEWAY_PROVISION_FAILED",
                "Gateway resource record is unavailable",
                status_code=409,
                retryable=True,
            )
        return value

    def _active_or_latest(self, publication: ManagedPublication) -> ManagedRevision:
        revisions = self.repository.list_revisions(publication.id)
        value = next(
            (item for item in revisions if item.id == publication.active_revision_id),
            revisions[0] if revisions else None,
        )
        if value is None:
            raise ManagedPublicationError(
                "NOT_FOUND", "Publication revision not found", status_code=404
            )
        return value

    def _save(
        self,
        publication: ManagedPublication,
        revision: ManagedRevision,
        operation: PublicationOperation,
    ) -> None:
        timestamp = datetime.now(timezone.utc)
        publication.updated_at = timestamp
        operation.updated_at = timestamp
        self.repository.save_publication(publication)
        self.repository.save_revision(revision)
        self.repository.save_operation(operation)

    def _audit(
        self,
        publication: ManagedPublication,
        revision: ManagedRevision,
        actor: Actor,
        event_type: str,
        request_id: str,
    ) -> None:
        self.repository.save_audit(
            PublicationAuditEvent(
                id=f"audit_{uuid4().hex}",
                publication_id=publication.id,
                revision_id=revision.id,
                actor=actor.principal_id,
                event_type=event_type,
                after_digest=_digest(
                    {
                        "status": publication.status,
                        "revision": revision.id,
                        "state": revision.state,
                    }
                ),
                request_id=request_id,
            )
        )


def resolve_actions(
    available: tuple[str, ...], policy: ActionPolicy
) -> tuple[str, ...]:
    known = tuple(dict.fromkeys(item.strip() for item in available if item.strip()))
    if policy.preset == "read_write":
        return known
    if policy.preset == "custom":
        requested = tuple(item for item in policy.action_ids if item in set(known))
        if len(requested) != len(policy.action_ids):
            raise ManagedPublicationError(
                "UNKNOWN_ACTION", "Custom policy contains unavailable Action IDs"
            )
        return requested
    return tuple(item for item in known if _READ_ACTION.search(item))


def _subjects(
    publication_id: str, revision_id: str, audience: Any
) -> tuple[PublicationSubject, ...]:
    pairs: tuple[tuple[str, str], ...] = (
        tuple(("application", value) for value in audience.client_ids)
        if audience.type == "applications"
        else tuple(
            (
                *((("user", value) for value in audience.user_ids)),
                *((("group", value) for value in audience.group_ids)),
            )
        )
    )
    return tuple(
        PublicationSubject(
            publication_id=publication_id,
            revision_id=revision_id,
            subject_type=kind,  # type: ignore[arg-type]
            subject_ref=value,
        )
        for kind, value in pairs
    )


def _audience_from_subjects(
    revision_id: str, subjects: tuple[PublicationSubject, ...]
) -> dict[str, object]:
    current = tuple(item for item in subjects if item.revision_id == revision_id)
    applications = [
        item.subject_ref for item in current if item.subject_type == "application"
    ]
    if applications:
        return {"type": "applications", "clientIds": applications}
    return {
        "type": "users_and_groups",
        "userIds": [
            item.subject_ref for item in current if item.subject_type == "user"
        ],
        "groupIds": [
            item.subject_ref for item in current if item.subject_type == "group"
        ],
    }


def _actor_kwargs(actor: Actor) -> dict[str, str]:
    return {
        "tenant_id": actor.tenant_id,
        "workspace_id": actor.workspace_id,
        "principal_id": actor.principal_id,
    }


def _normalize_mcp_endpoint(value: str) -> str:
    endpoint = value.strip().rstrip("/")
    return endpoint if not endpoint or endpoint.endswith("/mcp") else f"{endpoint}/mcp"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _safe_error(error: Exception) -> dict[str, object]:
    return {
        "code": str(getattr(error, "code", "") or "GATEWAY_PROVISION_FAILED"),
        "message": _SECRET.sub("[REDACTED]", str(error))[:500],
        "retryable": bool(getattr(error, "retryable", False)),
    }
