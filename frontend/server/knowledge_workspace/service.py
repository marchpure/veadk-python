"""Knowledge Workspace orchestration and completion gates."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass

from .autoskill import AutoSkillClient, AutoSkillProtocolError
from .connection import ConnectionInvocationContextPort, ConnectionServiceError
from .html_artifact import (
    HtmlArtifactError,
    validate_html_artifact,
    validate_output_archive,
)
from .models import (
    Artifact,
    AuthoringSession,
    DraftStatus,
    Invocation,
    InvocationKind,
    InvocationStatus,
    Publication,
    SkillDraft,
    SkillRevision,
    WorkspaceUpload,
    new_id,
    utc_now,
)
from .registry import PublicationRegistryPort
from .repository import KnowledgeWorkspaceRepository
from .sse import ParsedUpstreamEvent, normalize_upstream_event, sanitize_event_payload
from .zip_validator import SkillZipError, validate_skill_zip


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    workspace_id: str
    principal_id: str


class KnowledgeWorkspaceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class KnowledgeWorkspaceService:
    def __init__(
        self,
        repository: KnowledgeWorkspaceRepository,
        autoskill: AutoSkillClient,
        connection_context: ConnectionInvocationContextPort | None = None,
        publication_registry: PublicationRegistryPort | None = None,
    ) -> None:
        self.repository = repository
        self.autoskill = autoskill
        self.connection_context = connection_context
        self.publication_registry = publication_registry
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancelled: set[str] = set()

    @staticmethod
    def _public_value(value: object) -> object:
        if isinstance(value, Mapping):
            hidden = {
                "agent_id",
                "session_id",
                "request_id",
                "autoskill_agent_id",
                "autoskill_session_id",
                "autoskill_request_id",
                "tenant_id",
                "workspace_id",
                "token",
                "access_token",
                "refresh_token",
                "authorization",
                "upstream_url",
                "provider_url",
            }
            return {
                str(key): KnowledgeWorkspaceService._public_value(item)
                for key, item in value.items()
                if str(key).casefold() not in hidden
            }
        if isinstance(value, (list, tuple)):
            return [KnowledgeWorkspaceService._public_value(item) for item in value]
        return value

    @staticmethod
    def public_invocation(invocation: Invocation) -> dict[str, object]:
        """Return the browser contract without provider IDs or credentials."""

        return {
            "invocation_id": invocation.invocation_id,
            "kind": invocation.kind,
            "status": invocation.status,
            "message": invocation.message,
            "model": invocation.model,
            "started_at": invocation.started_at,
            "finished_at": invocation.finished_at,
            "created_at": invocation.created_at,
        }

    def conversation(self, actor: Actor, draft_id: str) -> list[dict[str, object]]:
        self.get_draft(actor, draft_id)
        return [
            {
                "invocation": self.public_invocation(invocation),
                "events": [
                    item["event"]
                    for item in self.repository.events_after(invocation.invocation_id)
                ],
            }
            for invocation in self.repository.invocations_for_draft(
                draft_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
        ]

    @staticmethod
    def public_draft(draft: SkillDraft) -> dict[str, object]:
        return {
            "draft_id": draft.draft_id,
            "goal": draft.goal,
            "trial_task": draft.trial_task,
            "connection_ids": draft.connection_ids,
            "upload_ids": draft.upload_ids,
            "lifecycle": draft.status,
            "current_revision_id": draft.current_revision_id,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
        }

    @staticmethod
    def public_revision(revision: SkillRevision) -> dict[str, object]:
        return {
            "revision_id": revision.revision_id,
            "draft_id": revision.draft_id,
            "number": revision.number,
            "skill_name": revision.skill_name,
            "sha256": revision.sha256,
            "manifest": KnowledgeWorkspaceService._public_value(revision.manifest),
            "created_from_invocation": revision.created_from_invocation,
            "created_at": revision.created_at,
        }

    @staticmethod
    def public_artifact(artifact: Artifact) -> dict[str, object]:
        lineage = KnowledgeWorkspaceService._public_value(artifact.lineage)
        return {
            "artifact_id": artifact.artifact_id,
            "revision_id": artifact.revision_id,
            "invocation_id": artifact.invocation_id,
            "sha256": artifact.sha256,
            "media_type": artifact.media_type,
            "encoding": artifact.encoding,
            "size_bytes": artifact.size_bytes,
            "lineage": lineage,
            "csp": artifact.csp,
            "sandbox": artifact.sandbox,
            "created_at": artifact.created_at,
        }

    @staticmethod
    def public_upload(upload: WorkspaceUpload) -> dict[str, object]:
        return {
            "upload_id": upload.upload_id,
            "filename": upload.filename,
            "sha256": upload.sha256,
            "size_bytes": upload.size_bytes,
            "media_type": upload.media_type,
        }

    @staticmethod
    def public_publication(publication: Publication) -> dict[str, object]:
        return {
            "publication_id": publication.publication_id,
            "revision_id": publication.revision_id,
            "target_space": publication.target_space,
            "status": publication.status,
            "created_at": publication.created_at,
        }

    def create_draft(
        self,
        actor: Actor,
        goal: str,
        connection_ids: Sequence[str],
        *,
        trial_task: str | None = None,
        upload_ids: Sequence[str] = (),
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> SkillDraft:
        if not goal.strip():
            raise KnowledgeWorkspaceError("INVALID_REQUEST", "goal is required", 400)
        unique = tuple(dict.fromkeys(str(item) for item in connection_ids))
        if not unique:
            raise KnowledgeWorkspaceError(
                "CONNECTION_NOT_READY", "at least one connection is required", 409
            )
        uploads = tuple(dict.fromkeys(str(item) for item in upload_ids))
        for upload_id in uploads:
            if (
                self.repository.get_upload(
                    upload_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
                is None
            ):
                raise KnowledgeWorkspaceError("NOT_FOUND", "upload not found", 404)
        draft_id = new_id("draft")
        if idempotency_key:
            try:
                draft_id = self.repository.idempotent(
                    f"{actor.tenant_id}:{actor.workspace_id}:{actor.principal_id}:draft",
                    idempotency_key,
                    request_digest,
                    draft_id,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
            existing = self.repository.get_draft(
                draft_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if existing is not None:
                return existing
        draft = SkillDraft(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            draft_id=draft_id,
            created_by=actor.principal_id,
            goal=goal.strip(),
            trial_task=trial_task.strip()
            if trial_task and trial_task.strip()
            else None,
            connection_ids=unique,
            upload_ids=uploads,
            etag=new_id("etag"),
        )
        session = AuthoringSession(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            draft_id=draft.draft_id,
            authoring_session_id=new_id("authoring"),
            autoskill_agent_id=new_id("agent"),
            autoskill_session_id=new_id("session"),
        )
        self.repository.save_draft(draft)
        self.repository.save_session(session)
        return draft

    def update_draft(
        self,
        actor: Actor,
        draft_id: str,
        *,
        goal: str | None,
        connection_ids: Sequence[str] | None,
        if_match: str | None,
        trial_task: str | None = None,
        upload_ids: Sequence[str] | None = None,
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> SkillDraft:
        draft = self.get_draft(actor, draft_id)
        idempotency_scope = f"{actor.tenant_id}:{actor.workspace_id}:{actor.principal_id}:draft-update:{draft_id}"
        if idempotency_key:
            try:
                replay_etag = self.repository.idempotency_value(
                    idempotency_scope,
                    idempotency_key,
                    request_digest,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
            if replay_etag:
                replay = self.repository.get_draft(
                    draft_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
                if replay is not None:
                    return replay
        if if_match and if_match.strip('"') != draft.etag:
            raise KnowledgeWorkspaceError(
                "ETAG_MISMATCH", "draft was modified by another request", 412
            )
        if draft.status == DraftStatus.GENERATING:
            raise KnowledgeWorkspaceError(
                "INVOCATION_ACTIVE", "draft has an active invocation", 409
            )
        updates: dict[str, object] = {
            "etag": new_id("etag"),
            "status": DraftStatus.EDITING,
            "updated_at": utc_now(),
        }
        if goal is not None:
            if not goal.strip():
                raise KnowledgeWorkspaceError(
                    "INVALID_REQUEST", "goal is required", 400
                )
            updates["goal"] = goal.strip()
        if connection_ids is not None:
            unique = tuple(dict.fromkeys(str(item) for item in connection_ids))
            if not unique:
                raise KnowledgeWorkspaceError(
                    "CONNECTION_NOT_READY", "at least one connection is required", 409
                )
            updates["connection_ids"] = unique
        if trial_task is not None:
            updates["trial_task"] = trial_task.strip() or None
        if upload_ids is not None:
            uploads = tuple(dict.fromkeys(str(item) for item in upload_ids))
            for upload_id in uploads:
                if (
                    self.repository.get_upload(
                        upload_id,
                        tenant_id=actor.tenant_id,
                        workspace_id=actor.workspace_id,
                    )
                    is None
                ):
                    raise KnowledgeWorkspaceError("NOT_FOUND", "upload not found", 404)
            updates["upload_ids"] = uploads
        updated = draft.model_copy(update=updates)
        self.repository.save_draft(updated)
        if idempotency_key:
            try:
                self.repository.idempotent(
                    idempotency_scope,
                    idempotency_key,
                    request_digest,
                    updated.etag,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
        return updated

    def list_drafts(self, actor: Actor) -> tuple[SkillDraft, ...]:
        return self.repository.list_drafts(
            tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )

    def get_draft(self, actor: Actor, draft_id: str) -> SkillDraft:
        draft = self.repository.get_draft(
            draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if draft is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "draft not found", 404)
        return draft

    def _session(self, actor: Actor, draft_id: str) -> AuthoringSession:
        session = self.repository.get_session(
            draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if session is None:
            raise KnowledgeWorkspaceError(
                "NOT_FOUND", "authoring session not found", 404
            )
        return session

    def _session_state(self, session: AuthoringSession) -> bytes | None:
        return (
            self.repository.read_object(session.state_uri)
            if session.state_uri
            else None
        )

    def start(
        self,
        actor: Actor,
        draft_id: str,
        kind: InvocationKind,
        *,
        message: str = "",
        model: str | None = None,
        revision_id: str | None = None,
        connection_ids: Sequence[str] = (),
        upload_ids: Sequence[str] = (),
        lease_id: str | None = None,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        request_digest: str = "",
        autoskill_agent_id: str | None = None,
        autoskill_session_id: str | None = None,
    ) -> Invocation:
        draft = self.get_draft(actor, draft_id)
        session = self._session(actor, draft_id)
        if if_match and if_match.strip('"') != draft.etag:
            raise KnowledgeWorkspaceError(
                "ETAG_MISMATCH", "draft was modified by another request", 412
            )
        effective_connection_ids = tuple(connection_ids) or draft.connection_ids
        effective_upload_ids = tuple(upload_ids) or draft.upload_ids
        for upload_id in effective_upload_ids:
            if (
                self.repository.get_upload(
                    upload_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
                is None
            ):
                raise KnowledgeWorkspaceError("NOT_FOUND", "upload not found", 404)
        invocation_id = new_id("inv")
        if idempotency_key:
            try:
                invocation_id = self.repository.idempotent(
                    f"{actor.tenant_id}:{actor.workspace_id}:{actor.principal_id}:{draft_id}:{kind.value}",
                    idempotency_key,
                    request_digest,
                    invocation_id,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
            existing = self.repository.get_invocation(
                invocation_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if existing is not None:
                return existing
        if draft.status == DraftStatus.GENERATING:
            raise KnowledgeWorkspaceError(
                "INVOCATION_ACTIVE", "draft already has an active invocation", 409
            )
        invocation = Invocation(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            invocation_id=invocation_id,
            draft_id=draft_id,
            revision_id=revision_id,
            connection_ids=effective_connection_ids,
            upload_ids=effective_upload_ids,
            lease_id=lease_id,
            authoring_session_id=session.authoring_session_id,
            principal_id=actor.principal_id,
            kind=kind,
            message=message or draft.goal,
            model=model,
            autoskill_agent_id=autoskill_agent_id or session.autoskill_agent_id,
            autoskill_session_id=autoskill_session_id or session.autoskill_session_id,
            autoskill_request_id=new_id("request"),
            autoskill_request_ids=(),
        )
        invocation = invocation.model_copy(
            update={"autoskill_request_ids": (invocation.autoskill_request_id,)}
        )
        self.repository.save_invocation(invocation)
        self.repository.save_draft(
            draft.model_copy(
                update={"status": DraftStatus.GENERATING, "updated_at": utc_now()}
            )
        )
        task = asyncio.create_task(
            self._execute(
                actor, invocation, draft, session, message or draft.goal, model
            )
        )
        self._tasks[invocation.invocation_id] = task
        return invocation

    async def _append(
        self,
        invocation: Invocation,
        event: ParsedUpstreamEvent,
        normalized: dict | None,
    ) -> int:
        return self.repository.append_event(
            invocation.invocation_id,
            sanitize_event_payload(event.payload),
            normalized,
            event.event_id,
        )

    async def _execute(
        self,
        actor: Actor,
        invocation: Invocation,
        draft: SkillDraft,
        session: AuthoringSession,
        message: str,
        model: str | None,
        *,
        resume: bool = False,
    ) -> None:
        current = invocation.model_copy(
            update={"status": InvocationStatus.RUNNING, "started_at": utc_now()}
        )
        self.repository.save_invocation(current)
        if not resume:
            self.repository.append_event(
                invocation.invocation_id,
                {"type": "run.started"},
                {
                    "id": f"{invocation.invocation_id}:0",
                    "type": "run.started",
                    "invocation_id": invocation.invocation_id,
                    "occurred_at": utc_now().isoformat(),
                    "data": {
                        "kind": invocation.kind.value,
                        "status": "running",
                        "draft_id": draft.draft_id,
                    },
                },
                None,
            )
        had_error = False
        summary: Mapping | None = None
        last_event_id: str | None = None
        lease_id = invocation.lease_id
        terminal_event: ParsedUpstreamEvent | None = None
        malformed_event: ParsedUpstreamEvent | None = None
        try:
            prior_events = self.repository.raw_events(invocation.invocation_id)
            prior_raw = [item["raw"] for item in prior_events]
            had_error = any(
                str(item.get("type", "")).casefold() == "error" for item in prior_raw
            )
            current = current.model_copy(
                update={
                    "error_observed": current.error_observed or had_error,
                    "final_answer_observed": current.final_answer_observed
                    or any(
                        str(item.get("type", "")).casefold() == "final_answer"
                        for item in prior_raw
                    ),
                    "request_summary_observed": current.request_summary_observed
                    or any(
                        str(item.get("type", "")).casefold() == "request_summary"
                        for item in prior_raw
                    ),
                    "done_observed": current.done_observed
                    or any(
                        str(item.get("type", "")).casefold() == "done"
                        for item in prior_raw
                    ),
                    "state_update_observed": current.state_update_observed
                    or any(
                        str(item.get("type", "")).casefold() == "state_update"
                        for item in prior_raw
                    ),
                }
            )
            for item in prior_raw:
                if str(item.get("type", "")).casefold() == "request_summary":
                    value = item.get("data")
                    if isinstance(value, Mapping):
                        summary = value
            if invocation.invocation_id in self._cancelled:
                cancelled = current.model_copy(
                    update={
                        "status": InvocationStatus.CANCELLED,
                        "error_code": "CANCELLED",
                        "finished_at": utc_now(),
                    }
                )
                self.repository.save_invocation(cancelled)
                return
            if invocation.connection_ids and self.connection_context is None:
                raise KnowledgeWorkspaceError(
                    "CONNECTION_CONTEXT_UNAVAILABLE",
                    "a server-side connection invocation context is required",
                    503,
                )
            if resume and lease_id and self.connection_context is not None:
                await self.connection_context.revoke(lease_id)
                lease_id = None
            if (
                lease_id is None
                and self.connection_context is not None
                and invocation.connection_ids
            ):
                allowed_actions = (
                    ("connection.execute",)
                    if invocation.kind is InvocationKind.RUN
                    else ("connection.execute", "connection.read")
                )
                lease = await self.connection_context.issue(
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                    principal_id=actor.principal_id,
                    invocation_id=invocation.autoskill_request_id,
                    connection_ids=invocation.connection_ids,
                    allowed_actions=allowed_actions,
                    ttl_seconds=1800,
                )
                lease_id = lease.lease_id
                current = current.model_copy(update={"lease_id": lease_id})
                self.repository.save_invocation(current)
                prepare_autoskill = getattr(
                    self.connection_context, "prepare_autoskill", None
                )
                if prepare_autoskill is not None:
                    await prepare_autoskill(
                        context=lease,
                        autoskill=self.autoskill,
                        agent_id=invocation.autoskill_agent_id,
                        session_id=invocation.autoskill_session_id,
                        invocation_id=invocation.autoskill_request_id,
                    )
            if invocation.invocation_id in self._cancelled:
                cancelled = current.model_copy(
                    update={
                        "status": InvocationStatus.CANCELLED,
                        "error_code": "CANCELLED",
                        "finished_at": utc_now(),
                    }
                )
                self.repository.save_invocation(cancelled)
                return
            if (
                invocation.kind is InvocationKind.RUN
                and invocation.revision_id
                and (
                    invocation.autoskill_agent_id != session.autoskill_agent_id
                    or invocation.autoskill_session_id != session.autoskill_session_id
                )
            ):
                revision = self.repository.get_revision(
                    invocation.revision_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
                if revision is None:
                    raise KnowledgeWorkspaceError(
                        "NOT_FOUND", "revision not found", 404
                    )
                await self.autoskill.upload(
                    agent_id=invocation.autoskill_agent_id,
                    session_id=invocation.autoskill_session_id,
                    file_type="skill",
                    file_name=revision.skill_name,
                    content=self.repository.read_object(revision.zip_uri),
                )
            for upload_id in invocation.upload_ids:
                upload = self.repository.get_upload(
                    upload_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
                if upload is None:
                    raise KnowledgeWorkspaceError("NOT_FOUND", "upload not found", 404)
                await self.autoskill.upload(
                    agent_id=invocation.autoskill_agent_id,
                    session_id=invocation.autoskill_session_id,
                    file_type="file",
                    file_name=upload.filename,
                    content=self.repository.read_object(upload.uri),
                )
            if resume:
                last = self.repository.raw_events(invocation.invocation_id)
                cursor = (
                    str(last[-1]["upstream_id"])
                    if last and last[-1]["upstream_id"]
                    else None
                )
                stream = self.autoskill.reconnect(
                    agent_id=invocation.autoskill_agent_id,
                    session_id=invocation.autoskill_session_id,
                    request_id=invocation.autoskill_request_id,
                    last_event_id=cursor,
                )
            elif invocation.kind is InvocationKind.GENERATE:
                stream = self.autoskill.command(
                    "create_skill",
                    agent_id=invocation.autoskill_agent_id,
                    session_id=invocation.autoskill_session_id,
                    request_id=invocation.autoskill_request_id,
                    prompt=message,
                    model=model,
                    state=self._session_state(session),
                )
            elif invocation.kind is InvocationKind.UPDATE:
                stream = self.autoskill.command(
                    "update_skill",
                    agent_id=invocation.autoskill_agent_id,
                    session_id=invocation.autoskill_session_id,
                    request_id=invocation.autoskill_request_id,
                    prompt=message,
                    model=model,
                    state=self._session_state(session),
                )
            else:
                state = (
                    self._session_state(session)
                    if getattr(self.autoskill, "config", None) is not None
                    and self.autoskill.config.state_mode.casefold() == "stateless"
                    else None
                )
                stream = self.autoskill.invoke(
                    agent_id=invocation.autoskill_agent_id,
                    session_id=invocation.autoskill_session_id,
                    request_id=invocation.autoskill_request_id,
                    message=message,
                    model=model,
                    state=state,
                )
            async for event in self._with_reconnect(stream, actor, current, session):
                last_event_id = event.event_id or last_event_id
                kind = event.event_type.casefold().replace("-", "_")
                if kind == "error":
                    had_error = True
                    current = current.model_copy(update={"error_observed": True})
                elif kind == "final_answer":
                    current = current.model_copy(update={"final_answer_observed": True})
                elif kind == "request_summary":
                    current = current.model_copy(
                        update={"request_summary_observed": True}
                    )
                elif kind == "done":
                    current = current.model_copy(update={"done_observed": True})
                elif kind == "state_update":
                    current = current.model_copy(update={"state_update_observed": True})
                if kind == "request_summary":
                    value = event.payload.get("data")
                    summary = value if isinstance(value, Mapping) else {"value": value}
                normalized = normalize_upstream_event(
                    event,
                    invocation_id=invocation.invocation_id,
                    cursor=len(self.repository.raw_events(invocation.invocation_id))
                    + 1,
                )
                if event.malformed:
                    malformed_event = event
                if kind == "done":
                    terminal_event = event
                    break
                await self._append(current, event, normalized)
            if terminal_event is not None:
                await self._append(current, terminal_event, None)
            if malformed_event is not None:
                raise KnowledgeWorkspaceError(
                    "AUTOSKILL_PROTOCOL_ERROR",
                    "AutoSkill emitted a malformed event",
                    502,
                )
            if invocation.invocation_id in self._cancelled:
                self.repository.save_invocation(
                    current.model_copy(
                        update={
                            "status": InvocationStatus.CANCELLED,
                            "finished_at": utc_now(),
                        }
                    )
                )
                return
            if (
                had_error
                or not summary
                or str(summary.get("status", "")).casefold()
                not in {"success", "succeeded", "ok", "completed"}
                or not current.done_observed
                or not current.final_answer_observed
                or not current.request_summary_observed
            ):
                raise KnowledgeWorkspaceError(
                    "AUTOSKILL_PROTOCOL_ERROR",
                    "AutoSkill did not provide a successful request_summary",
                    502,
                )
            if (
                current.state_update_observed
                and getattr(self.autoskill, "config", None) is not None
                and self.autoskill.config.state_mode.casefold() == "stateless"
            ):
                try:
                    state_zip = await self.autoskill.get_state_zip(
                        agent_id=invocation.autoskill_agent_id,
                        session_id=invocation.autoskill_session_id,
                        request_id=invocation.autoskill_request_id,
                    )
                except AutoSkillProtocolError as exc:
                    raise KnowledgeWorkspaceError(
                        "AUTOSKILL_PROTOCOL_ERROR", str(exc), 502
                    ) from exc
                state_digest = hashlib.sha256(state_zip).hexdigest()
                state_uri = self.repository.put_object(
                    state_digest, state_zip, suffix=".state.zip"
                )
                self.repository.save_session(
                    session.model_copy(update={"state_uri": state_uri})
                )
            finished = current.model_copy(
                update={
                    "status": InvocationStatus.SUCCEEDED,
                    "request_summary": dict(summary),
                    "finished_at": utc_now(),
                }
            )
            if invocation.kind is InvocationKind.RUN and invocation.revision_id:
                await self._capture_output(
                    actor, finished, invocation.revision_id, session
                )
            self.repository.save_invocation(finished)
            # Artifacts are persisted before terminal success is exposed.
            completed_cursor = (
                len(self.repository.raw_events(invocation.invocation_id)) + 1
            )
            self.repository.append_event(
                invocation.invocation_id,
                {"type": "run.completed", "data": {"status": "succeeded"}},
                {
                    "id": f"{invocation.invocation_id}:{completed_cursor}",
                    "type": "run.completed",
                    "invocation_id": invocation.invocation_id,
                    "occurred_at": utc_now().isoformat(),
                    "data": {
                        "status": "succeeded",
                        "finished_at": finished.finished_at.isoformat()
                        if finished.finished_at
                        else utc_now().isoformat(),
                        "artifact_ids": [
                            item.artifact_id
                            for item in self.repository.artifacts_for_revision(
                                invocation.revision_id,
                                tenant_id=actor.tenant_id,
                                workspace_id=actor.workspace_id,
                            )
                        ]
                        if invocation.revision_id
                        else [],
                        "revision_id": invocation.revision_id,
                    },
                },
                None,
            )
            self.repository.save_draft(
                draft.model_copy(
                    update={"status": DraftStatus.GENERATED, "updated_at": utc_now()}
                )
            )
        except asyncio.CancelledError:
            raise
        except (
            KnowledgeWorkspaceError,
            SkillZipError,
            HtmlArtifactError,
            AutoSkillProtocolError,
            ConnectionServiceError,
        ) as exc:
            safe_message = str(sanitize_event_payload(str(exc)))
            failed = current.model_copy(
                update={
                    "status": InvocationStatus.CANCELLED
                    if invocation.invocation_id in self._cancelled
                    else InvocationStatus.FAILED,
                    "error_code": getattr(exc, "code", "AUTOSKILL_PROTOCOL_ERROR"),
                    "error_message": safe_message,
                    "finished_at": utc_now(),
                }
            )
            self.repository.save_invocation(failed)
            self.repository.save_draft(
                draft.model_copy(
                    update={
                        "status": DraftStatus.CANCELLED
                        if failed.status is InvocationStatus.CANCELLED
                        else DraftStatus.FAILED,
                        "updated_at": utc_now(),
                    }
                )
            )
            normalized = {
                "id": f"{invocation.invocation_id}:failure",
                "type": "run.cancelled"
                if failed.status is InvocationStatus.CANCELLED
                else "run.failed",
                "invocation_id": invocation.invocation_id,
                "occurred_at": utc_now().isoformat(),
                "data": {
                    "status": failed.status.value,
                    "error": {
                        "code": failed.error_code,
                        "message": failed.error_message,
                        "retryable": False,
                    },
                },
            }
            self.repository.append_event(
                invocation.invocation_id,
                {
                    "type": "error",
                    "data": {"code": failed.error_code, "message": safe_message},
                },
                normalized,
                None,
            )
        except Exception as exc:
            failed = current.model_copy(
                update={
                    "status": InvocationStatus.FAILED,
                    "error_code": "AUTOSKILL_PROTOCOL_ERROR",
                    "error_message": type(exc).__name__,
                    "finished_at": utc_now(),
                }
            )
            self.repository.save_invocation(failed)
            self.repository.save_draft(
                draft.model_copy(
                    update={"status": DraftStatus.FAILED, "updated_at": utc_now()}
                )
            )
        finally:
            if lease_id and self.connection_context is not None:
                try:
                    await self.connection_context.revoke(lease_id)
                except Exception:
                    pass
            self._tasks.pop(invocation.invocation_id, None)

    async def _capture_output(
        self,
        actor: Actor,
        invocation: Invocation,
        revision_id: str,
        session: AuthoringSession,
    ) -> None:
        try:
            output = await self.autoskill.download(
                agent_id=invocation.autoskill_agent_id,
                session_id=invocation.autoskill_session_id,
                file_type="output",
            )
        except AutoSkillProtocolError as exc:
            raise KnowledgeWorkspaceError(
                "ARTIFACT_UNAVAILABLE", str(exc), 502
            ) from exc
        media_type = "application/octet-stream"
        encoding = "binary"
        metadata: dict[str, object] = {
            "sha256": hashlib.sha256(output).hexdigest(),
            "size_bytes": len(output),
            "media_type": media_type,
            "encoding": encoding,
            "csp": "default-src 'none'",
            "sandbox": "",
        }
        content = output
        name = "output.bin"
        try:
            if output.lstrip().lower().startswith((b"<html", b"<!doctype html")):
                name, content, metadata = (
                    "output.html",
                    output,
                    validate_html_artifact(output),
                )
            elif output[:2] == b"PK":
                name, content, metadata = validate_output_archive(output)
        except HtmlArtifactError as exc:
            # A real non-HTML result is still an artifact; only HTML receives
            # the HTML viewer policy. Never synthesize a dashboard fallback.
            if exc.code not in {"ARTIFACT_HTML_MISSING", "ARTIFACT_HTML_AMBIGUOUS"}:
                raise
            name = "output.zip" if output[:2] == b"PK" else "output.bin"
            if name == "output.bin":
                try:
                    text = output.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                else:
                    if text.strip():
                        metadata = {
                            "sha256": hashlib.sha256(output).hexdigest(),
                            "size_bytes": len(output),
                            "media_type": "text/plain",
                            "encoding": "utf-8",
                            "csp": "default-src 'none'",
                            "sandbox": "",
                        }
        digest = str(metadata["sha256"])
        uri = self.repository.put_object(
            digest,
            content,
            suffix=".html" if metadata["media_type"] == "text/html" else ".bin",
        )
        artifact = Artifact(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            artifact_id=new_id("artifact"),
            revision_id=revision_id,
            invocation_id=invocation.invocation_id,
            uri=uri,
            sha256=digest,
            media_type=str(metadata["media_type"]),
            encoding=str(metadata["encoding"]),
            size_bytes=int(metadata["size_bytes"]),
            lineage={
                "source": "autoskill.download",
                "output_name": name,
                "autoskill_request_id": invocation.autoskill_request_id,
                "revision_id": revision_id,
                "invocation_id": invocation.invocation_id,
                "connection_ids": list(invocation.connection_ids),
            },
            csp=str(metadata["csp"]),
            sandbox=str(metadata["sandbox"]),
        )
        self.repository.save_artifact(artifact)
        cursor = len(self.repository.raw_events(invocation.invocation_id)) + 1
        self.repository.append_event(
            invocation.invocation_id,
            {"type": "artifact.created", "data": {"artifact_id": artifact.artifact_id}},
            {
                "id": f"{invocation.invocation_id}:{cursor}",
                "type": "artifact.created",
                "invocation_id": invocation.invocation_id,
                "occurred_at": utc_now().isoformat(),
                "data": {
                    "artifact_id": artifact.artifact_id,
                    "revision_id": revision_id,
                    "media_type": artifact.media_type,
                    "sha256": artifact.sha256,
                    "lineage": self.public_artifact(artifact)["lineage"],
                },
            },
            None,
        )

    def _record_request_id(self, invocation: Invocation, request_id: str) -> Invocation:
        """Persist every provider request used by one invocation."""

        persisted = (
            self.repository.get_invocation(
                invocation.invocation_id,
                tenant_id=invocation.tenant_id,
                workspace_id=invocation.workspace_id,
            )
            or invocation
        )
        if request_id in persisted.autoskill_request_ids:
            return persisted
        updated = persisted.model_copy(
            update={
                "autoskill_request_ids": (*persisted.autoskill_request_ids, request_id)
            }
        )
        self.repository.save_invocation(updated)
        return updated

    async def _skill_command(
        self,
        command: str,
        *,
        agent_id: str,
        session_id: str,
        request_id: str,
        name: str | None = None,
        state: bytes | None = None,
        invocation: Invocation | None = None,
    ) -> list[ParsedUpstreamEvent]:
        """Collect one query command and reject malformed or terminal errors.

        Skill queries are part of the revision completion gate.  A provider
        error, malformed event, or missing terminal ``done`` therefore cannot
        be treated as an empty/partial query result. Compatible unknown
        progress events remain durably archived and are otherwise ignored.
        """

        allowed = {
            "planning",
            "action",
            "observation",
            "final_answer",
            "request_summary",
            "state_update",
            "error",
            "done",
        }
        result: list[ParsedUpstreamEvent] = []
        terminal = False
        reconnects = 0
        stream: AsyncIterator[ParsedUpstreamEvent] = self.autoskill.command(
            command,
            agent_id=agent_id,
            session_id=session_id,
            request_id=request_id,
            name=name,
            state=state,
        )
        if invocation is not None:
            self._record_request_id(invocation, request_id)
        while not terminal:
            try:
                async for event in stream:
                    kind = event.event_type.casefold().replace("-", "_")
                    result.append(event)
                    if invocation is not None:
                        self.repository.append_event(
                            invocation.invocation_id,
                            sanitize_event_payload(event.payload),
                            None,
                            f"{request_id}:{event.event_id}"
                            if event.event_id
                            else None,
                        )
                    if event.malformed:
                        raise KnowledgeWorkspaceError(
                            "AUTOSKILL_PROTOCOL_ERROR",
                            f"AutoSkill emitted an invalid {command} event",
                            502,
                        )
                    if kind not in allowed:
                        continue
                    if kind == "error":
                        raise KnowledgeWorkspaceError(
                            "AUTOSKILL_PROTOCOL_ERROR",
                            f"AutoSkill {command} returned an error",
                            502,
                        )
                    if kind == "done":
                        terminal = True
                        break
                if terminal:
                    break
                raise AutoSkillProtocolError(
                    f"AutoSkill {command} disconnected before done"
                )
            except AutoSkillProtocolError:
                max_reconnects = getattr(
                    getattr(self.autoskill, "config", None), "max_reconnects", 2
                )
                if reconnects >= max_reconnects:
                    raise
                reconnects += 1
                last_event_id = next(
                    (item.event_id for item in reversed(result) if item.event_id),
                    None,
                )
                stream = self.autoskill.reconnect(
                    agent_id=agent_id,
                    session_id=session_id,
                    request_id=request_id,
                    last_event_id=last_event_id,
                )
        if not terminal:
            raise KnowledgeWorkspaceError(
                "AUTOSKILL_PROTOCOL_ERROR",
                f"AutoSkill {command} disconnected before done",
                502,
            )
        return result

    async def _with_reconnect(
        self,
        stream: AsyncIterator[ParsedUpstreamEvent],
        actor: Actor,
        invocation: Invocation,
        session: AuthoringSession,
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        current = stream
        reconnects = 0
        while True:
            try:
                async for event in current:
                    yield event
                return
            except AutoSkillProtocolError:
                max_reconnects = getattr(
                    getattr(self.autoskill, "config", None), "max_reconnects", 2
                )
                if reconnects >= max_reconnects:
                    raise
                reconnects += 1
                last = self.repository.raw_events(invocation.invocation_id)
                cursor = (
                    str(last[-1]["upstream_id"])
                    if last and last[-1]["upstream_id"]
                    else None
                )
                current = self.autoskill.reconnect(
                    agent_id=invocation.autoskill_agent_id,
                    session_id=invocation.autoskill_session_id,
                    request_id=invocation.autoskill_request_id,
                    last_event_id=cursor,
                )

    async def cancel(
        self,
        actor: Actor,
        invocation_id: str,
        *,
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> Invocation:
        invocation = self.repository.get_invocation(
            invocation_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if invocation is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "invocation not found", 404)
        if idempotency_key:
            try:
                self.repository.idempotent(
                    f"{actor.tenant_id}:{actor.workspace_id}:{actor.principal_id}:cancel:{invocation_id}",
                    idempotency_key,
                    request_digest,
                    invocation_id,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
        if invocation.status in {
            InvocationStatus.SUCCEEDED,
            InvocationStatus.FAILED,
            InvocationStatus.CANCELLED,
        }:
            return invocation
        self._cancelled.add(invocation_id)
        try:
            await self.autoskill.stop(
                agent_id=invocation.autoskill_agent_id,
                session_id=invocation.autoskill_session_id,
                request_id=invocation.autoskill_request_id,
            )
        except AutoSkillProtocolError:
            # Local cancellation is authoritative even if the upstream stop
            # request races a transport failure.
            pass
        result = invocation.model_copy(
            update={
                "status": InvocationStatus.CANCELLED,
                "finished_at": utc_now(),
                "error_code": "CANCELLED",
            }
        )
        self.repository.save_invocation(result)
        cursor = len(self.repository.raw_events(invocation_id)) + 1
        self.repository.append_event(
            invocation_id,
            {"type": "cancel", "data": {"status": "cancelled"}},
            {
                "id": f"{invocation_id}:{cursor}",
                "type": "run.cancelled",
                "invocation_id": invocation_id,
                "occurred_at": utc_now().isoformat(),
                "data": {
                    "status": "cancelled",
                    "finished_at": result.finished_at.isoformat(),
                },
            },
            None,
        )
        return result

    async def events(
        self, actor: Actor, invocation_id: str, after: int = 0
    ) -> AsyncIterator[dict]:
        invocation = self.repository.get_invocation(
            invocation_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if invocation is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "invocation not found", 404)
        cursor = after
        while True:
            batch = self.repository.events_after(invocation_id, cursor)
            if batch:
                for item in batch:
                    cursor = int(item["sequence"])
                    yield item["event"]
                continue
            current = self.repository.get_invocation(
                invocation_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if current is None or current.status in {
                InvocationStatus.SUCCEEDED,
                InvocationStatus.FAILED,
                InvocationStatus.CANCELLED,
            }:
                return
            yield {"heartbeat": True}
            await asyncio.sleep(0.25)

    async def freeze(
        self,
        actor: Actor,
        draft_id: str,
        invocation_id: str,
        *,
        idempotency_key: str | None = None,
        request_digest: str = "",
        if_match: str | None = None,
    ) -> SkillRevision:
        draft = self.get_draft(actor, draft_id)
        idempotency_scope = f"{actor.tenant_id}:{actor.workspace_id}:{actor.principal_id}:freeze:{draft_id}"
        if idempotency_key:
            try:
                existing_id = self.repository.idempotency_value(
                    idempotency_scope,
                    idempotency_key,
                    request_digest,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
            if existing_id:
                replay = self.repository.get_revision(
                    existing_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
                if replay is not None:
                    return replay
        if if_match:
            if if_match.strip('"') != draft.etag:
                raise KnowledgeWorkspaceError(
                    "ETAG_MISMATCH", "draft was modified by another request", 412
                )
        invocation = self.repository.get_invocation(
            invocation_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        session = self._session(actor, draft_id)
        if (
            invocation is None
            or invocation.draft_id != draft_id
            or invocation.status is not InvocationStatus.SUCCEEDED
        ):
            raise KnowledgeWorkspaceError(
                "REVISION_CONFLICT",
                "invocation is not a successful draft invocation",
                409,
            )
        if (
            not invocation.request_summary
            or invocation.error_code
            or not invocation.final_answer_observed
            or not invocation.request_summary_observed
            or not invocation.done_observed
            or invocation.error_observed
        ):
            raise KnowledgeWorkspaceError(
                "REVISION_CONFLICT", "completion gates are not satisfied", 409
            )
        try:
            # Query the actual service for the Skill list/view and download.
            state = (
                self._session_state(session)
                if getattr(self.autoskill, "config", None) is not None
                and self.autoskill.config.state_mode.casefold() == "stateless"
                else None
            )
            names = await self._skill_command(
                "list_skill",
                agent_id=invocation.autoskill_agent_id,
                session_id=invocation.autoskill_session_id,
                request_id=new_id("request"),
                state=state,
                invocation=invocation,
            )
            skill_name = None
            for event in names:
                if event.event_type == "final_answer":
                    data = event.payload.get("data", {})
                    answer = data.get("answer") if isinstance(data, Mapping) else ""
                    try:
                        payload = json.loads(answer)
                        payload_data = (
                            payload.get("data", {})
                            if isinstance(payload, Mapping)
                            else {}
                        )
                        if isinstance(payload_data, Mapping):
                            skill_data = payload_data.get("data", payload_data)
                            if isinstance(skill_data, Mapping):
                                skills = skill_data.get("skills", [])
                                if isinstance(skills, list) and skills:
                                    first = skills[0]
                                    if isinstance(first, Mapping):
                                        skill_name = first.get("name")
                    except (TypeError, ValueError, IndexError, AttributeError):
                        pass
            if not skill_name:
                raise KnowledgeWorkspaceError(
                    "SKILL_ZIP_INVALID", "AutoSkill did not return a Skill name", 502
                )
            view_request = new_id("request")
            invocation = self._record_request_id(invocation, view_request)
            view_events = await self._skill_command(
                "view_skill",
                agent_id=invocation.autoskill_agent_id,
                session_id=invocation.autoskill_session_id,
                request_id=view_request,
                name=skill_name,
                state=state,
                invocation=invocation,
            )
            view_seen = False
            view_content = ""
            for event in view_events:
                if event.event_type == "final_answer":
                    view_seen = True
                    data = event.payload.get("data", {})
                    answer = data.get("answer") if isinstance(data, Mapping) else ""
                    view_content = str(answer or "").strip()
            if not view_seen or not view_content:
                raise KnowledgeWorkspaceError(
                    "SKILL_ZIP_INVALID",
                    "view_skill did not return readable content",
                    502,
                )
            zip_bytes = await self.autoskill.download(
                agent_id=invocation.autoskill_agent_id,
                session_id=invocation.autoskill_session_id,
                file_type="skill",
                name=skill_name,
            )
            manifest = validate_skill_zip(zip_bytes)
            uri = self.repository.put_object(
                manifest["sha256"], zip_bytes, suffix=".zip"
            )
        except AutoSkillProtocolError as exc:
            raise KnowledgeWorkspaceError(
                "AUTOSKILL_PROTOCOL_ERROR", str(exc), 502
            ) from exc
        number = (
            len(
                self.repository.revisions(
                    draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
                )
            )
            + 1
        )
        revision_id = new_id("rev")
        if idempotency_key:
            try:
                revision_id = self.repository.idempotent(
                    idempotency_scope,
                    idempotency_key,
                    request_digest,
                    revision_id,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
            replay = self.repository.get_revision(
                revision_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if replay is not None:
                return replay
        revision = SkillRevision(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            revision_id=revision_id,
            draft_id=draft_id,
            number=number,
            skill_name=str(skill_name),
            zip_uri=uri,
            sha256=manifest["sha256"],
            manifest={k: v for k, v in manifest.items() if k != "skill_md"},
            created_from_invocation=invocation_id,
        )
        frozen = self.repository.freeze_revision(revision)
        cursor = len(self.repository.raw_events(invocation_id)) + 1
        self.repository.append_event(
            invocation_id,
            {"type": "revision.created", "data": {"revision_id": frozen.revision_id}},
            {
                "id": f"{invocation_id}:{cursor}",
                "type": "revision.created",
                "invocation_id": invocation_id,
                "occurred_at": utc_now().isoformat(),
                "data": {
                    "revision_id": frozen.revision_id,
                    "draft_id": frozen.draft_id,
                    "number": frozen.number,
                    "sha256": frozen.sha256,
                    "skill_name": frozen.skill_name,
                },
            },
            None,
        )
        return frozen

    async def resume_pending(self) -> None:
        for invocation in self.repository.active_invocations():
            if invocation.invocation_id in self._tasks:
                continue
            draft = self.repository.get_draft(
                invocation.draft_id,
                tenant_id=invocation.tenant_id,
                workspace_id=invocation.workspace_id,
            )
            session = self.repository.get_session(
                invocation.draft_id,
                tenant_id=invocation.tenant_id,
                workspace_id=invocation.workspace_id,
            )
            if draft is None or session is None:
                continue
            actor = Actor(
                invocation.tenant_id, invocation.workspace_id, invocation.principal_id
            )
            self._tasks[invocation.invocation_id] = asyncio.create_task(
                self._execute(
                    actor,
                    invocation,
                    draft,
                    session,
                    invocation.message or draft.goal,
                    invocation.model,
                    resume=invocation.status is InvocationStatus.RUNNING,
                )
            )

    async def run_revision(
        self,
        actor: Actor,
        revision_id: str,
        message: str,
        connection_ids: Sequence[str],
        *,
        upload_ids: Sequence[str] = (),
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> Invocation:
        revision = self.repository.get_revision(
            revision_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if revision is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "revision not found", 404)
        if not connection_ids:
            raise KnowledgeWorkspaceError(
                "CONNECTION_NOT_READY", "connection permission is required", 409
            )
        # Run uses a fresh request but the draft's isolated agent/session.
        invocation = self.start(
            actor,
            revision.draft_id,
            InvocationKind.RUN,
            message=message,
            revision_id=revision_id,
            connection_ids=connection_ids,
            upload_ids=upload_ids,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        return invocation

    def get_artifact(self, actor: Actor, artifact_id: str) -> Artifact:
        artifact = self.repository.get_artifact(
            artifact_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if artifact is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "artifact not found", 404)
        return artifact

    def artifact_content(
        self, actor: Actor, artifact_id: str
    ) -> tuple[bytes, str, str]:
        artifact = self.get_artifact(actor, artifact_id)
        return (
            self.repository.read_object(artifact.uri),
            artifact.media_type,
            artifact.csp,
        )

    def list_publications(self, actor: Actor) -> tuple[Publication, ...]:
        return self.repository.list_publications(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )

    def publish(
        self,
        actor: Actor,
        revision_id: str,
        target_space: str,
        *,
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> Publication:
        revision = self.repository.get_revision(
            revision_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if revision is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "revision not found", 404)
        if target_space not in {"personal", "team"}:
            raise KnowledgeWorkspaceError(
                "PUBLISH_GATE_FAILED", "invalid publication target", 422
            )
        if target_space == "team" and not actor.principal_id:
            raise KnowledgeWorkspaceError(
                "PUBLISH_GATE_FAILED", "team publication requires ACL", 403
            )
        successful_runs = [
            item
            for item in self.repository.invocations_for_revision(
                revision_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if (
                item.kind is InvocationKind.RUN
                and item.status is InvocationStatus.SUCCEEDED
                and item.lease_id
            )
        ]
        artifacts = self.repository.artifacts_for_revision(
            revision_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        successful_run_ids = {item.invocation_id for item in successful_runs}
        if not successful_runs or not any(
            artifact.invocation_id in successful_run_ids for artifact in artifacts
        ):
            raise KnowledgeWorkspaceError(
                "PUBLISH_GATE_FAILED",
                "a successful real run and artifact are required",
                409,
            )
        try:
            checked_zip = validate_skill_zip(
                self.repository.read_object(revision.zip_uri)
            )
            if checked_zip["sha256"] != revision.sha256:
                raise KnowledgeWorkspaceError(
                    "PUBLISH_GATE_FAILED", "revision ZIP digest changed", 409
                )
            for artifact in artifacts:
                content = self.repository.read_object(artifact.uri)
                if hashlib.sha256(content).hexdigest() != artifact.sha256:
                    raise KnowledgeWorkspaceError(
                        "PUBLISH_GATE_FAILED", "artifact digest changed", 409
                    )
                if artifact.media_type == "text/html":
                    validate_html_artifact(content)
        except (SkillZipError, HtmlArtifactError, ValueError) as exc:
            raise KnowledgeWorkspaceError(
                "PUBLISH_GATE_FAILED", "immutable asset validation failed", 409
            ) from exc
        publication_id = new_id("pub")
        if idempotency_key:
            try:
                publication_id = self.repository.idempotent(
                    f"{actor.tenant_id}:{actor.workspace_id}:{actor.principal_id}:publish",
                    idempotency_key,
                    request_digest,
                    publication_id,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise KnowledgeWorkspaceError(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency key was reused with different input",
                        409,
                    ) from exc
                raise
            existing = self.repository.get_publication(
                publication_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if existing is not None:
                return existing
        policy_snapshot = {
            "target_space": target_space,
            "revision_sha256": revision.sha256,
            "successful_run_invocation_id": successful_runs[-1].invocation_id,
            "artifact_sha256": [
                item.sha256
                for item in self.repository.artifacts_for_revision(
                    revision_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
            ],
            "consumer_reauthorization_required": True,
        }
        if self.publication_registry is not None:
            try:
                self.publication_registry.register_publication(
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                    publication_id=publication_id,
                    revision_id=revision_id,
                    skill_name=revision.skill_name,
                    revision_sha256=revision.sha256,
                    artifact_sha256=tuple(item.sha256 for item in artifacts),
                    target_space=target_space,
                    published_by=actor.principal_id,
                    policy_snapshot=policy_snapshot,
                )
            except Exception as exc:
                raise KnowledgeWorkspaceError(
                    "PUBLISH_GATE_FAILED",
                    "cross-Agent publication registry rejected the revision",
                    409,
                ) from exc
        return self.repository.save_publication(
            Publication(
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
                publication_id=publication_id,
                revision_id=revision_id,
                target_space=target_space,
                published_by=actor.principal_id,
                policy_snapshot=policy_snapshot,
            )
        )

    async def invoke_publication(
        self,
        actor: Actor,
        publication_id: str,
        message: str,
        connection_ids: Sequence[str],
        *,
        upload_ids: Sequence[str] = (),
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> Invocation:
        publication = self.repository.get_publication(
            publication_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        if publication is None or publication.status != "published":
            raise KnowledgeWorkspaceError("NOT_FOUND", "publication not found", 404)
        if not connection_ids:
            raise KnowledgeWorkspaceError(
                "CONNECTION_NOT_READY", "consumer authorization is required", 403
            )
        revision = self.repository.get_revision(
            publication.revision_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        if revision is None:
            raise KnowledgeWorkspaceError(
                "NOT_FOUND", "published revision not found", 404
            )
        consumer_agent_id = new_id("consumer-agent")
        consumer_session_id = new_id("consumer-session")
        # A consumer invocation gets a fresh request and must be authorized
        # independently; the creator's lease/session is never reused.
        return self.start(
            actor,
            revision.draft_id,
            InvocationKind.RUN,
            message=message,
            revision_id=revision.revision_id,
            connection_ids=connection_ids,
            upload_ids=upload_ids,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            autoskill_agent_id=consumer_agent_id,
            autoskill_session_id=consumer_session_id,
        )
