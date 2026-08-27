"""Knowledge Workspace orchestration and completion gates."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from .autoskill import AutoSkillClient, AutoSkillProtocolError
from .connection import ConnectionInvocationContextPort
from .html_artifact import HtmlArtifactError, validate_output_archive
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
    new_id,
    utc_now,
)
from .repository import KnowledgeWorkspaceRepository
from .sse import ParsedUpstreamEvent, normalize_upstream_event
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
    ) -> None:
        self.repository = repository
        self.autoskill = autoskill
        self.connection_context = connection_context
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancelled: set[str] = set()

    def create_draft(
        self,
        actor: Actor,
        goal: str,
        connection_ids: Sequence[str],
        *,
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> SkillDraft:
        if not goal.strip():
            raise KnowledgeWorkspaceError("INVALID_REQUEST", "goal is required", 400)
        unique = tuple(dict.fromkeys(str(item) for item in connection_ids))
        if not unique:
            raise KnowledgeWorkspaceError("CONNECTION_NOT_READY", "at least one connection is required", 409)
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
                    raise KnowledgeWorkspaceError("IDEMPOTENCY_CONFLICT", "idempotency key was reused with different input", 409) from exc
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
            connection_ids=unique,
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
    ) -> SkillDraft:
        draft = self.get_draft(actor, draft_id)
        if if_match and if_match.strip('"') != draft.etag:
            raise KnowledgeWorkspaceError("ETAG_MISMATCH", "draft was modified by another request", 412)
        if draft.status == DraftStatus.GENERATING:
            raise KnowledgeWorkspaceError("INVOCATION_ACTIVE", "draft has an active invocation", 409)
        updates: dict[str, object] = {
            "etag": new_id("etag"),
            "status": DraftStatus.EDITING,
            "updated_at": utc_now(),
        }
        if goal is not None:
            if not goal.strip():
                raise KnowledgeWorkspaceError("INVALID_REQUEST", "goal is required", 400)
            updates["goal"] = goal.strip()
        if connection_ids is not None:
            unique = tuple(dict.fromkeys(str(item) for item in connection_ids))
            if not unique:
                raise KnowledgeWorkspaceError("CONNECTION_NOT_READY", "at least one connection is required", 409)
            updates["connection_ids"] = unique
        updated = draft.model_copy(update=updates)
        self.repository.save_draft(updated)
        return updated

    def list_drafts(self, actor: Actor) -> tuple[SkillDraft, ...]:
        return self.repository.list_drafts(tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)

    def get_draft(self, actor: Actor, draft_id: str) -> SkillDraft:
        draft = self.repository.get_draft(draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
        if draft is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "draft not found", 404)
        return draft

    def _session(self, actor: Actor, draft_id: str) -> AuthoringSession:
        session = self.repository.get_session(draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
        if session is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "authoring session not found", 404)
        return session

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
        lease_id: str | None = None,
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> Invocation:
        draft = self.get_draft(actor, draft_id)
        session = self._session(actor, draft_id)
        effective_connection_ids = tuple(connection_ids) or draft.connection_ids
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
                    raise KnowledgeWorkspaceError("IDEMPOTENCY_CONFLICT", "idempotency key was reused with different input", 409) from exc
                raise
            existing = self.repository.get_invocation(
                invocation_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if existing is not None:
                return existing
        if draft.status == DraftStatus.GENERATING:
            raise KnowledgeWorkspaceError("INVOCATION_ACTIVE", "draft already has an active invocation", 409)
        invocation = Invocation(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            invocation_id=invocation_id,
            draft_id=draft_id,
            revision_id=revision_id,
            connection_ids=effective_connection_ids,
            lease_id=lease_id,
            authoring_session_id=session.authoring_session_id,
            kind=kind,
            autoskill_agent_id=session.autoskill_agent_id,
            autoskill_session_id=session.autoskill_session_id,
            autoskill_request_id=new_id("request"),
        )
        self.repository.save_invocation(invocation)
        self.repository.save_draft(draft.model_copy(update={"status": DraftStatus.GENERATING, "updated_at": utc_now()}))
        task = asyncio.create_task(self._execute(actor, invocation, draft, session, message or draft.goal, model))
        self._tasks[invocation.invocation_id] = task
        return invocation

    async def _append(self, invocation: Invocation, event: ParsedUpstreamEvent, normalized: dict | None) -> int:
        return self.repository.append_event(invocation.invocation_id, event.payload, normalized, event.event_id)

    async def _execute(self, actor: Actor, invocation: Invocation, draft: SkillDraft, session: AuthoringSession, message: str, model: str | None) -> None:
        current = invocation.model_copy(update={"status": InvocationStatus.RUNNING, "started_at": utc_now()})
        self.repository.save_invocation(current)
        self.repository.append_event(invocation.invocation_id, {"type": "run.started"}, {"id": f"{invocation.invocation_id}:0", "type": "run.started", "invocation_id": invocation.invocation_id, "occurred_at": utc_now().isoformat(), "data": {"kind": invocation.kind.value, "status": "running", "draft_id": draft.draft_id}}, None)
        had_error = False
        summary: Mapping | None = None
        last_event_id: str | None = None
        lease_id = invocation.lease_id
        terminal_event: ParsedUpstreamEvent | None = None
        try:
            if lease_id is None and self.connection_context is not None and invocation.connection_ids:
                allowed_actions = (
                    ("connection.execute",)
                    if invocation.kind is InvocationKind.RUN
                    else ("connection.execute", "connection.read")
                )
                lease = await self.connection_context.issue(
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                    principal_id=actor.principal_id,
                    invocation_id=invocation.invocation_id,
                    connection_ids=invocation.connection_ids,
                    allowed_actions=allowed_actions,
                    ttl_seconds=1800,
                )
                lease_id = lease.lease_id
                current = current.model_copy(update={"lease_id": lease_id})
                self.repository.save_invocation(current)
            if invocation.kind is InvocationKind.GENERATE:
                stream = self.autoskill.command("create_skill", agent_id=session.autoskill_agent_id, session_id=session.autoskill_session_id, request_id=invocation.autoskill_request_id, prompt=message, model=model)
            elif invocation.kind is InvocationKind.UPDATE:
                stream = self.autoskill.command("update_skill", agent_id=session.autoskill_agent_id, session_id=session.autoskill_session_id, request_id=invocation.autoskill_request_id, prompt=message, model=model)
            else:
                stream = self.autoskill.invoke(agent_id=session.autoskill_agent_id, session_id=session.autoskill_session_id, request_id=invocation.autoskill_request_id, message=message, model=model)
            async for event in self._with_reconnect(stream, actor, current, session):
                last_event_id = event.event_id or last_event_id
                kind = event.event_type.casefold().replace("-", "_")
                if kind == "error":
                    had_error = True
                    current = current.model_copy(update={"error_observed": True})
                elif kind == "final_answer":
                    current = current.model_copy(update={"final_answer_observed": True})
                elif kind == "request_summary":
                    current = current.model_copy(update={"request_summary_observed": True})
                elif kind == "done":
                    current = current.model_copy(update={"done_observed": True})
                if kind == "request_summary":
                    value = event.payload.get("data")
                    summary = value if isinstance(value, Mapping) else {"value": value}
                normalized = normalize_upstream_event(event, invocation_id=invocation.invocation_id, cursor=len(self.repository.raw_events(invocation.invocation_id)) + 1)
                if kind == "done":
                    terminal_event = event
                    break
                await self._append(current, event, normalized)
            if terminal_event is not None:
                await self._append(current, terminal_event, None)
            if invocation.invocation_id in self._cancelled:
                self.repository.save_invocation(current.model_copy(update={"status": InvocationStatus.CANCELLED, "finished_at": utc_now()}))
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
                raise KnowledgeWorkspaceError("AUTOSKILL_PROTOCOL_ERROR", "AutoSkill did not provide a successful request_summary", 502)
            finished = current.model_copy(update={"status": InvocationStatus.SUCCEEDED, "request_summary": dict(summary), "finished_at": utc_now()})
            self.repository.save_invocation(finished)
            completed_cursor = len(self.repository.raw_events(invocation.invocation_id)) + 1
            self.repository.append_event(
                invocation.invocation_id,
                {"type": "run.completed", "data": {"status": "succeeded"}},
                {
                    "id": f"{invocation.invocation_id}:{completed_cursor}",
                    "type": "run.completed",
                    "invocation_id": invocation.invocation_id,
                    "occurred_at": utc_now().isoformat(),
                    "data": {"status": "succeeded", "request_summary": dict(summary)},
                },
                None,
            )
            self.repository.save_draft(draft.model_copy(update={"status": DraftStatus.GENERATED, "updated_at": utc_now()}))
            if invocation.kind is InvocationKind.RUN and invocation.revision_id:
                await self._capture_output(actor, finished, invocation.revision_id, session)
        except asyncio.CancelledError:
            raise
        except (KnowledgeWorkspaceError, SkillZipError, HtmlArtifactError, AutoSkillProtocolError) as exc:
            failed = current.model_copy(update={"status": InvocationStatus.CANCELLED if invocation.invocation_id in self._cancelled else InvocationStatus.FAILED, "error_code": getattr(exc, "code", "AUTOSKILL_PROTOCOL_ERROR"), "error_message": str(exc), "finished_at": utc_now()})
            self.repository.save_invocation(failed)
            self.repository.save_draft(draft.model_copy(update={"status": DraftStatus.CANCELLED if failed.status is InvocationStatus.CANCELLED else DraftStatus.FAILED, "updated_at": utc_now()}))
            normalized = {"id": f"{invocation.invocation_id}:failure", "type": "run.cancelled" if failed.status is InvocationStatus.CANCELLED else "run.failed", "invocation_id": invocation.invocation_id, "occurred_at": utc_now().isoformat(), "data": {"status": failed.status.value, "error": {"code": failed.error_code, "message": failed.error_message, "retryable": False}}}
            self.repository.append_event(invocation.invocation_id, {"type": "error", "data": {"code": failed.error_code, "message": failed.error_message}}, normalized, None)
        except Exception as exc:
            failed = current.model_copy(update={"status": InvocationStatus.FAILED, "error_code": "AUTOSKILL_PROTOCOL_ERROR", "error_message": type(exc).__name__, "finished_at": utc_now()})
            self.repository.save_invocation(failed)
            self.repository.save_draft(draft.model_copy(update={"status": DraftStatus.FAILED, "updated_at": utc_now()}))
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
                agent_id=session.autoskill_agent_id,
                session_id=session.autoskill_session_id,
                file_type="output",
            )
        except AutoSkillProtocolError as exc:
            raise KnowledgeWorkspaceError("ARTIFACT_UNAVAILABLE", str(exc), 502) from exc
        media_type = "application/octet-stream"
        encoding = "binary"
        metadata: dict[str, object] = {
            "sha256": hashlib.sha256(output).hexdigest(),
            "size_bytes": len(output),
            "media_type": media_type,
            "encoding": encoding,
            "csp": "default-src 'none'",
            "sandbox": "allow-same-origin",
        }
        content = output
        name = "output.bin"
        try:
            name, content, metadata = validate_output_archive(output)
        except HtmlArtifactError as exc:
            # A real non-HTML result is still an artifact; only HTML receives
            # the HTML viewer policy. Never synthesize a dashboard fallback.
            if exc.code not in {"ARTIFACT_HTML_MISSING", "ARTIFACT_HTML_AMBIGUOUS", "ARTIFACT_OUTPUT_INVALID"}:
                raise
            name = "output.zip" if output[:2] == b"PK" else "output.bin"
        digest = str(metadata["sha256"])
        uri = self.repository.put_object(digest, content, suffix=".html" if metadata["media_type"] == "text/html" else ".bin")
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
            },
            csp=str(metadata["csp"]),
            sandbox=str(metadata["sandbox"]),
        )
        self.repository.save_artifact(artifact)

    async def _with_reconnect(self, stream: AsyncIterator[ParsedUpstreamEvent], actor: Actor, invocation: Invocation, session: AuthoringSession) -> AsyncIterator[ParsedUpstreamEvent]:
        try:
            async for event in stream:
                yield event
        except AutoSkillProtocolError:
            # Reconnect observes the existing request. It never invokes again.
            last = self.repository.raw_events(invocation.invocation_id)
            cursor = str(last[-1]["upstream_id"]) if last and last[-1]["upstream_id"] else None
            async for event in self.autoskill.reconnect(agent_id=session.autoskill_agent_id, session_id=session.autoskill_session_id, request_id=invocation.autoskill_request_id, last_event_id=cursor):
                yield event

    async def cancel(self, actor: Actor, invocation_id: str) -> Invocation:
        invocation = self.repository.get_invocation(invocation_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
        if invocation is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "invocation not found", 404)
        if invocation.status in {InvocationStatus.SUCCEEDED, InvocationStatus.FAILED, InvocationStatus.CANCELLED}:
            return invocation
        self._cancelled.add(invocation_id)
        await self.autoskill.stop(agent_id=invocation.autoskill_agent_id, session_id=invocation.autoskill_session_id, request_id=invocation.autoskill_request_id)
        result = invocation.model_copy(update={"status": InvocationStatus.CANCELLED, "finished_at": utc_now(), "error_code": "CANCELLED"})
        self.repository.save_invocation(result)
        return result

    async def events(self, actor: Actor, invocation_id: str, after: int = 0) -> AsyncIterator[dict]:
        invocation = self.repository.get_invocation(invocation_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
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
            current = self.repository.get_invocation(invocation_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
            if current is None or current.status in {InvocationStatus.SUCCEEDED, InvocationStatus.FAILED, InvocationStatus.CANCELLED}:
                return
            yield {"heartbeat": True}
            await asyncio.sleep(0.25)

    async def freeze(self, actor: Actor, draft_id: str, invocation_id: str) -> SkillRevision:
        draft = self.get_draft(actor, draft_id)
        invocation = self.repository.get_invocation(invocation_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
        session = self._session(actor, draft_id)
        if invocation is None or invocation.draft_id != draft_id or invocation.status is not InvocationStatus.SUCCEEDED:
            raise KnowledgeWorkspaceError("REVISION_CONFLICT", "invocation is not a successful draft invocation", 409)
        if (
            not invocation.request_summary
            or invocation.error_code
            or not invocation.final_answer_observed
            or not invocation.request_summary_observed
            or not invocation.done_observed
            or invocation.error_observed
        ):
            raise KnowledgeWorkspaceError("REVISION_CONFLICT", "completion gates are not satisfied", 409)
        view_events = self.repository.raw_events(invocation_id)
        viewed = any(str(item["raw"].get("type", "")).casefold() in {"final_answer", "done"} for item in view_events)
        if not viewed:
            raise KnowledgeWorkspaceError("REVISION_CONFLICT", "AutoSkill view_skill/download gates are missing", 409)
        try:
            # Query the actual service for the Skill list/view and download.
            names = await self.autoskill.command("list_skill", agent_id=session.autoskill_agent_id, session_id=session.autoskill_session_id, request_id=new_id("request"))
            skill_name = None
            async for event in names:
                if event.event_type == "final_answer":
                    data = event.payload.get("data", {})
                    answer = data.get("answer") if isinstance(data, Mapping) else ""
                    try:
                        payload = json.loads(answer)
                        skill_name = payload.get("data", {}).get("skills", [{}])[0].get("name")
                    except (TypeError, ValueError, IndexError, AttributeError):
                        pass
                if event.event_type == "done":
                    break
            if not skill_name:
                raise KnowledgeWorkspaceError("SKILL_ZIP_INVALID", "AutoSkill did not return a Skill name", 502)
            view_request = new_id("request")
            view_stream = self.autoskill.command("view_skill", agent_id=session.autoskill_agent_id, session_id=session.autoskill_session_id, request_id=view_request, name=skill_name)
            view_seen = False
            async for event in view_stream:
                view_seen = view_seen or event.event_type == "final_answer"
                if event.event_type == "done":
                    break
            if not view_seen:
                raise KnowledgeWorkspaceError("SKILL_ZIP_INVALID", "view_skill did not return readable content", 502)
            zip_bytes = await self.autoskill.download(agent_id=session.autoskill_agent_id, session_id=session.autoskill_session_id, file_type="skill", name=skill_name)
            manifest = validate_skill_zip(zip_bytes)
            uri = self.repository.put_object(manifest["sha256"], zip_bytes, suffix=".zip")
        except AutoSkillProtocolError as exc:
            raise KnowledgeWorkspaceError("AUTOSKILL_PROTOCOL_ERROR", str(exc), 502) from exc
        number = len(self.repository.revisions(draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)) + 1
        revision = SkillRevision(tenant_id=actor.tenant_id, workspace_id=actor.workspace_id, revision_id=new_id("rev"), draft_id=draft_id, number=number, skill_name=str(skill_name), zip_uri=uri, sha256=manifest["sha256"], manifest={k: v for k, v in manifest.items() if k != "skill_md"}, created_from_invocation=invocation_id)
        return self.repository.freeze_revision(revision)

    async def run_revision(
        self,
        actor: Actor,
        revision_id: str,
        message: str,
        connection_ids: Sequence[str],
        *,
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> Invocation:
        revision = self.repository.get_revision(revision_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
        if revision is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "revision not found", 404)
        if not connection_ids:
            raise KnowledgeWorkspaceError("CONNECTION_NOT_READY", "connection permission is required", 409)
        # Run uses a fresh request but the draft's isolated agent/session.
        invocation = self.start(
            actor,
            revision.draft_id,
            InvocationKind.RUN,
            message=message,
            revision_id=revision_id,
            connection_ids=connection_ids,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        return invocation

    def get_artifact(self, actor: Actor, artifact_id: str) -> Artifact:
        artifact = self.repository.get_artifact(artifact_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
        if artifact is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "artifact not found", 404)
        return artifact

    def publish(
        self,
        actor: Actor,
        revision_id: str,
        target_space: str,
        *,
        idempotency_key: str | None = None,
        request_digest: str = "",
    ) -> Publication:
        revision = self.repository.get_revision(revision_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
        if revision is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "revision not found", 404)
        if target_space not in {"personal", "team"}:
            raise KnowledgeWorkspaceError("PUBLISH_GATE_FAILED", "invalid publication target", 422)
        if target_space == "team" and not actor.principal_id:
            raise KnowledgeWorkspaceError("PUBLISH_GATE_FAILED", "team publication requires ACL", 403)
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
                    raise KnowledgeWorkspaceError("IDEMPOTENCY_CONFLICT", "idempotency key was reused with different input", 409) from exc
                raise
            existing = self.repository.get_publication(
                publication_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if existing is not None:
                return existing
        return self.repository.save_publication(Publication(tenant_id=actor.tenant_id, workspace_id=actor.workspace_id, publication_id=publication_id, revision_id=revision_id, target_space=target_space, published_by=actor.principal_id))

    async def invoke_publication(
        self,
        actor: Actor,
        publication_id: str,
        message: str,
        connection_ids: Sequence[str],
        *,
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
            raise KnowledgeWorkspaceError("CONNECTION_NOT_READY", "consumer authorization is required", 403)
        revision = self.repository.get_revision(
            publication.revision_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        if revision is None:
            raise KnowledgeWorkspaceError("NOT_FOUND", "published revision not found", 404)
        # A consumer invocation gets a fresh request and must be authorized
        # independently; the creator's lease/session is never reused.
        return self.start(
            actor,
            revision.draft_id,
            InvocationKind.RUN,
            message=message,
            revision_id=revision.revision_id,
            connection_ids=connection_ids,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
