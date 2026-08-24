"""Application use cases behind the Studio BFF."""

from __future__ import annotations

import hashlib
import csv
import json
from pathlib import Path
from urllib.parse import urlparse

from .contracts import (
    CommandResponse,
    CommandResult,
    DraftCommandResult,
    ErrorEnvelope,
    LegacySkillManifestInput,
    InvocationStartPayload,
    InvocationStartResult,
    OperationEvent,
    OperationResponse,
    PublicationPublishPayload,
    PublicationPublishResult,
    RefreshRunPayload,
    RefreshRunResult,
    RefreshRun,
    SkillDraft,
    SkillDraftRunPayload,
    SkillDraftRunResult,
    SkillManifest,
    SourceCleanPayload,
    SourceCleanResult,
    SourceProfilePayload,
    SourceProfileResult,
    SourceRevision,
    NotReadyCommandResult,
    ProfileRun,
    CleaningRecipe,
    CleanRun,
    GoldenAssetRevision,
    OwnerRef,
    PermissionRef,
    SchemaRef,
    StorageRef,
    adapt_legacy_manifest,
    now_iso,
)
from .policies import validate_manifest_policy
from .ports import AuditRecorderPort
from .repository import (
    KnowledgeAssetRepositoryError,
    KnowledgeAssetRepository,
)


class KnowledgeAssetApplication:
    def __init__(
        self,
        repository: KnowledgeAssetRepository,
        *,
        audit_recorder: AuditRecorderPort | None = None,
    ) -> None:
        self.repository = repository
        self.audit_recorder = audit_recorder or repository

    def bootstrap(self, workspace_id: str, role: str):
        return self.repository.bootstrap(workspace_id, role)

    def create_skill_draft(
        self,
        payload: dict[str, object],
        *,
        request_id: str,
        idempotency_key: str,
    ) -> CommandResponse:
        workspace_id = str(payload["workspace_id"])
        name = str(payload["name"])
        description = str(payload.get("description", ""))
        source_refs = [str(item) for item in payload.get("source_refs", [])]
        try:
            draft, replayed = self.repository.create_skill_draft(
                workspace_id=workspace_id,
                name=name,
                description=description,
                source_refs=source_refs,
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
        except KnowledgeAssetRepositoryError:
            raise
        for source_ref in source_refs:
            self._register_local_source(
                source_ref, workspace_id=workspace_id, request_id=request_id
            )
        operation_id = self._operation_id(idempotency_key)
        self.repository.create_operation(operation_id, request_id)
        if replayed:
            existing_operation = self.repository.operation(operation_id)
            if existing_operation is not None:
                return CommandResponse(
                    accepted=True,
                    request_id=request_id,
                    operation_id=operation_id,
                    result=existing_operation.result,
                )
        return self._complete_operation(
            operation_id=operation_id,
            request_id=request_id,
            workspace_id=workspace_id,
            action="skill-draft.create",
            resource_id=draft.id,
            draft=draft,
            replayed=replayed,
        )

    def _register_local_source(
        self, source_ref: str, *, workspace_id: str, request_id: str
    ) -> SourceRevision | None:
        path = self._local_path(source_ref)
        if path is None or not path.is_file():
            return None
        suffix = path.suffix.lower()
        if suffix not in {".md", ".markdown", ".csv"}:
            return None
        content = path.read_bytes()
        if len(content) > 10 * 1024 * 1024:
            raise KnowledgeAssetRepositoryError(
                "SOURCE_TOO_LARGE", "本地来源超过 10 MiB 限制。"
            )
        if b"\x00" in content:
            raise KnowledgeAssetRepositoryError(
                "SOURCE_UNSAFE_CONTENT", "本地来源包含不允许的二进制内容。"
            )
        digest = hashlib.sha256(content).hexdigest()
        source_type = "csv" if suffix == ".csv" else "markdown"
        schema_digest = self._schema_digest(content, source_type)
        revision = SourceRevision(
            id=f"source-{digest[:24]}",
            source_type=source_type,
            content_ref=StorageRef(
                uri=f"local://{digest}",
                kind="object",
                sha256=digest,
                media_type="text/csv" if source_type == "csv" else "text/markdown",
                bytes=len(content),
            ),
            schema_ref=SchemaRef(
                uri=f"local://schema/source/{schema_digest}",
                version="1",
                sha256=schema_digest,
            ),
            permission_ref=PermissionRef(
                uri=f"permission://workspace/{workspace_id}",
                version="1",
            ),
            source_digest=digest,
            created_at=now_iso(),
        )
        self.repository.save_source_revision(revision, workspace_id, str(path))
        return revision

    @staticmethod
    def _schema_digest(content: bytes, source_type: str) -> str:
        if source_type == "csv":
            first_line = content.decode("utf-8").splitlines()[0] if content else ""
            schema = {"format": "csv", "columns": next(csv.reader([first_line]), [])}
        else:
            schema = {"format": "markdown", "columns": ["text"]}
        return hashlib.sha256(
            json.dumps(schema, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _local_path(source_ref: str) -> Path | None:
        parsed = urlparse(source_ref)
        if parsed.scheme in {"http", "https", "secret"}:
            return None
        raw = Path(parsed.path if parsed.scheme == "file" else source_ref).expanduser()
        if raw.is_symlink():
            raise KnowledgeAssetRepositoryError(
                "SOURCE_UNSAFE_PATH", "本地来源不得通过符号链接读取。"
            )
        return raw.resolve()

    def _source_path(self, source_revision_id: str) -> Path:
        path = getattr(self.repository, "source_path", lambda _id: None)(source_revision_id)
        if path is None:
            raise KnowledgeAssetRepositoryError(
                "SOURCE_NOT_FOUND", "本地来源不存在。", details={"sourceRevisionId": source_revision_id}
            )
        return Path(path)

    def _run_profile(self, payload: SourceProfilePayload, request_id: str) -> SourceProfileResult:
        source = self.repository.source_revision(payload.source_revision_id)
        if source is None:
            raise KnowledgeAssetRepositoryError("SOURCE_NOT_FOUND", "来源不存在。")
        path = self._source_path(source.id)
        content = path.read_text(encoding="utf-8")
        columns: list[str] = []
        rows: list[dict[str, str]] = []
        lines: list[str] = []
        if source.source_type == "csv":
            rows = list(csv.DictReader(content.splitlines()))
            sample = rows[: payload.sample_limit]
            columns = list(rows[0].keys()) if rows else []
            nonempty = sum(bool(value) for row in sample for value in row.values())
            total = max(len(sample) * max(len(columns), 1), 1)
            report = {"format": "csv", "rows": len(rows), "columns": columns, "sample": sample}
        else:
            lines = [line for line in content.splitlines() if line.strip()]
            sample = lines[: payload.sample_limit]
            nonempty = len(sample)
            total = max(len(sample), 1)
            report = {"format": "markdown", "lines": len(lines), "sample": sample}
        report_digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        structure = {
            "format": source.source_type,
            "columns": columns if source.source_type == "csv" else ["text"],
            "rowCount": len(rows) if source.source_type == "csv" else len(lines),
        }
        structure_digest = hashlib.sha256(
            json.dumps(structure, sort_keys=True).encode()
        ).hexdigest()
        cost = {"bytesRead": path.stat().st_size, "sampleRows": len(sample)}
        cost_digest = hashlib.sha256(
            json.dumps(cost, sort_keys=True).encode()
        ).hexdigest()
        sensitive = [
            column for column in columns
            if any(token in column.lower() for token in ("email", "phone", "token", "secret"))
        ]
        run = ProfileRun(
            id=f"profile-{source.id}", source_revision_id=source.id, status="succeeded",
            report_ref=StorageRef(uri=f"local://profile/{report_digest}", kind="inline",
                                  sha256=report_digest, media_type="application/json"),
            structure_ref=StorageRef(uri=f"local://structure/{structure_digest}", kind="inline",
                                     sha256=structure_digest, media_type="application/json"),
            quality_score=nonempty / total, started_at=now_iso(), finished_at=now_iso(),
            sensitive_classification=sensitive,
            estimated_cost_ref=StorageRef(uri=f"local://cost/{cost_digest}", kind="inline",
                                          sha256=cost_digest, media_type="application/json"),
        )
        self.repository.save_profile_run(run)
        return SourceProfileResult(
            source_revision_id=source.id, status="succeeded", profile_run=run,
            error=None,
        )

    def _run_clean(
        self, payload: SourceCleanPayload, workspace_id: str
    ) -> SourceCleanResult:
        source = self.repository.source_revision(payload.source_revision_id)
        if source is None:
            raise KnowledgeAssetRepositoryError("SOURCE_NOT_FOUND", "来源不存在。")
        source_workspace = getattr(
            self.repository, "source_workspace", lambda _id: None
        )(source.id)
        if source_workspace:
            workspace_id = source_workspace
        path = self._source_path(source.id)
        raw = path.read_text(encoding="utf-8")
        operations = ["trim", "deduplicate"]
        recipe_digest = hashlib.sha256(
            json.dumps({"source": source.id, "operations": operations}, sort_keys=True).encode()
        ).hexdigest()
        recipe = CleaningRecipe(
            id=payload.recipe_id, version=1, operations=operations,
            source_revision_id=source.id, recipe_digest=recipe_digest,
        )
        self.repository.save_cleaning_recipe(recipe)
        if source.source_type == "csv":
            rows = list(csv.DictReader(raw.splitlines()))
            seen = set()
            cleaned = []
            for row in rows:
                item = {key: value.strip() for key, value in row.items()}
                marker = json.dumps(item, sort_keys=True)
                if marker not in seen:
                    seen.add(marker)
                    cleaned.append(item)
            output = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in cleaned) + "\n"
            media_type = "application/x-ndjson"
        else:
            lines = []
            seen = set()
            for line in raw.splitlines():
                value = line.strip()
                if value and value not in seen:
                    seen.add(value)
                    lines.append(value)
            output = "\n".join(lines) + "\n"
            media_type = "text/plain"
        digest = hashlib.sha256(output.encode()).hexdigest()
        artifact = self._artifact_path(digest)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(output, encoding="utf-8")
        storage = StorageRef(uri=f"local://golden/{digest}", kind="object", sha256=digest,
                             media_type=media_type, bytes=len(output.encode()))
        clean = CleanRun(
            id=f"clean-{source.id}-{recipe.version}", source_revision_id=source.id,
            recipe_id=recipe.id, status="succeeded", output_ref=storage,
            started_at=now_iso(), finished_at=now_iso(),
        )
        self.repository.save_clean_run(clean)
        lineage = hashlib.sha256(f"{source.source_digest}:{recipe.recipe_digest}:{digest}".encode()).hexdigest()
        golden = GoldenAssetRevision(
            id=f"golden-{digest[:24]}", asset_kind="dataset" if source.source_type == "csv" else "knowledge",
            revision=1, schema_ref=SchemaRef(uri=f"local://schema/{digest}", version="1", sha256=digest),
            storage_ref=storage, source_revision_refs=[source.id], recipe_ref=recipe.id,
            quality_run_ref=clean.id, owner=OwnerRef(workspace_id=workspace_id, principal_id="local"),
            permissions_ref=source.permission_ref, lineage_digest=lineage,
            freshness_at=now_iso(), last_good=True,
        )
        golden = self.repository.save_golden_asset_revision(golden)
        return SourceCleanResult(
            source_revision_id=source.id, recipe_id=recipe.id, status="succeeded", clean_run=clean,
            golden_asset_revision=golden,
        )

    @staticmethod
    def _artifact_path(digest: str) -> Path:
        return Path(".veadk/knowledge-assets/artifacts") / f"{digest}.jsonl"

    def save_manifest(
        self,
        payload: dict[str, object],
        *,
        request_id: str,
        idempotency_key: str,
    ) -> CommandResponse:
        draft_id = str(payload["draft_id"])
        base_revision = int(payload["base_revision"])
        raw_manifest = payload["manifest"]
        if isinstance(raw_manifest, SkillManifest):
            manifest = raw_manifest
        else:
            legacy = LegacySkillManifestInput.model_validate(raw_manifest)
            draft = self.repository.draft(draft_id)
            if draft is None:
                raise KnowledgeAssetRepositoryError(
                    "DRAFT_NOT_FOUND",
                    "Skill 草稿不存在。",
                    details={"draftId": draft_id},
                )
            manifest = adapt_legacy_manifest(
                legacy,
                draft_id=draft.id,
                workspace_id=draft.workspace_id,
            )
        validate_manifest_policy(manifest)
        draft, replayed = self.repository.save_manifest(
            draft_id=draft_id,
            base_revision=base_revision,
            manifest=manifest,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        operation_id = self._operation_id(idempotency_key)
        self.repository.create_operation(operation_id, request_id)
        if replayed:
            existing_operation = self.repository.operation(operation_id)
            if existing_operation is not None:
                return CommandResponse(
                    accepted=True,
                    request_id=request_id,
                    operation_id=operation_id,
                    result=existing_operation.result,
                )
        return self._complete_operation(
            operation_id=operation_id,
            request_id=request_id,
            workspace_id=draft.workspace_id,
            action="skill-draft.save-manifest",
            resource_id=draft.id,
            draft=draft,
            replayed=replayed,
        )

    @staticmethod
    def _operation_id(idempotency_key: str) -> str:
        return "op-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]

    def _complete_operation(
        self,
        *,
        operation_id: str,
        request_id: str,
        workspace_id: str,
        action: str,
        resource_id: str,
        draft: SkillDraft,
        replayed: bool,
    ) -> CommandResponse:
        typed_result = DraftCommandResult(
            result_type=action,
            draft=draft,
            replayed=replayed,
        )
        accepted = OperationEvent(
            operation_id=operation_id,
            event_id=f"{operation_id}:accepted",
            sequence=1,
            occurred_at=now_iso(),
            type="accepted",
            terminal=False,
        )
        succeeded = OperationEvent(
            operation_id=operation_id,
            event_id=f"{operation_id}:succeeded",
            sequence=2,
            occurred_at=now_iso(),
            type="succeeded",
            terminal=True,
            result=typed_result,
        )
        self.repository.append_operation_event(operation_id, accepted, status="running")
        self.repository.append_operation_event(
            operation_id,
            succeeded,
            status="succeeded",
            result=typed_result.model_dump(mode="json", by_alias=True),
        )
        self.audit_recorder.record_audit(
            request_id=request_id,
            operation_id=operation_id,
            workspace_id=workspace_id,
            action=action,
            resource_id=resource_id,
            outcome="succeeded",
            details={"revision": str(draft.revision)},
        )
        return CommandResponse(
            accepted=True,
            request_id=request_id,
            operation_id=operation_id,
            result=typed_result,
        )

    def stream_events(self, operation_id: str, after: int = 0) -> list[OperationEvent]:
        operation = self.repository.operation(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        return [event for event in operation.events if event.sequence > after]

    def unsupported(
        self,
        command: str,
        request_id: str,
        payload: dict[str, object],
        *,
        workspace_id: str = "workspace-local",
    ) -> CommandResponse:
        result: CommandResult
        if command == "source.profile":
            typed = SourceProfilePayload.model_validate(payload)
            if self.repository.source_revision(typed.source_revision_id) is None:
                result = SourceProfileResult(
                    source_revision_id=typed.source_revision_id,
                    error=self._not_ready_error(command, request_id),
                )
                return CommandResponse(accepted=False, request_id=request_id, result=result)
            result = self._run_profile(typed, request_id)
        elif command == "source.clean":
            typed = SourceCleanPayload.model_validate(payload)
            if self.repository.source_revision(typed.source_revision_id) is None:
                result = SourceCleanResult(
                    source_revision_id=typed.source_revision_id,
                    recipe_id=typed.recipe_id,
                    error=self._not_ready_error(command, request_id),
                )
                return CommandResponse(accepted=False, request_id=request_id, result=result)
            draft = self.repository.draft(str(payload.get("draft_id", "")))
            workspace_id = draft.workspace_id if draft else "workspace-local"
            result = self._run_clean(typed, workspace_id)
        elif command == "skill-draft.run":
            typed = SkillDraftRunPayload.model_validate(payload)
            draft = self.repository.draft(typed.draft_id)
            if draft is None:
                result = SkillDraftRunResult(
                    draft_id=typed.draft_id,
                    error=self._not_ready_error(command, request_id),
                )
                return CommandResponse(accepted=False, request_id=request_id, result=result)
            golden = self.repository.latest_golden_asset_revision(draft.workspace_id)
            result = SkillDraftRunResult(
                draft_id=typed.draft_id, status="succeeded",
                golden_asset_revision=golden,
            )
        elif command == "resource.revoke":
            resource_id = str(payload["resource_id"])
            reason = str(payload.get("reason", "revoked"))
            golden = self.repository.latest_golden_asset_revision(workspace_id)
            if golden is not None and golden.id == resource_id:
                self.repository.revoke_asset(resource_id, workspace_id, request_id, reason)
            result = NotReadyCommandResult(
                command=command,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "publication.publish":
            typed = PublicationPublishPayload.model_validate(payload)
            result = PublicationPublishResult(
                draft_id=typed.draft_id,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "refresh.run":
            typed = RefreshRunPayload.model_validate(payload)
            draft = self.repository.draft(typed.skill_id)
            if draft is None or draft.workspace_id != workspace_id:
                result = RefreshRunResult(
                    skill_id=typed.skill_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="SKILL_NOT_FOUND",
                        message="待刷新的 Skill 不存在或不属于当前工作区。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            else:
                previous = self.repository.latest_golden_asset_revision(workspace_id)
                run = RefreshRun(
                    id=f"refresh-{hashlib.sha256(request_id.encode()).hexdigest()[:24]}",
                    skill_id=typed.skill_id,
                    trigger=typed.trigger,
                    status="running",
                    current_revision=previous.revision if previous else None,
                    last_good_revision=previous.revision if previous else None,
                    started_at=now_iso(),
                )
                try:
                    sources = self.repository.source_revisions_for_workspace(workspace_id)
                    if not sources:
                        raise KnowledgeAssetRepositoryError(
                            "SOURCE_NOT_FOUND", "没有可刷新的来源。"
                        )
                    source = sources[-1]
                    current_bytes = self._source_path(source.id).read_bytes()
                    current_schema = self._schema_digest(current_bytes, source.source_type)
                    if source.schema_ref and current_schema != source.schema_ref.sha256:
                        raise KnowledgeAssetRepositoryError(
                            "SCHEMA_CHANGED", "来源结构已变化，刷新被安全门禁拒绝。"
                        )
                    current_digest = hashlib.sha256(current_bytes).hexdigest()
                    if current_digest != source.source_digest:
                        source = self._register_local_source(
                            str(self._source_path(source.id)),
                            workspace_id=workspace_id,
                            request_id=request_id,
                        )
                        assert source is not None
                    self._run_profile(
                        SourceProfilePayload(source_revision_id=source.id),
                        request_id,
                    )
                    cleaned = self._run_clean(
                        SourceCleanPayload(
                            source_revision_id=source.id,
                            recipe_id=f"refresh-{source.id}",
                        ),
                        workspace_id,
                    )
                    run = run.model_copy(update={
                        "status": "succeeded",
                        "staging_ref": cleaned.golden_asset_revision.storage_ref,
                        "current_revision": cleaned.golden_asset_revision.revision,
                        "last_good_revision": cleaned.golden_asset_revision.revision,
                        "finished_at": now_iso(),
                    })
                    result = RefreshRunResult(
                        skill_id=typed.skill_id, status="succeeded",
                        refresh_run=run,
                    )
                except (KnowledgeAssetRepositoryError, OSError, UnicodeError) as error:
                    code = getattr(error, "code", "SOURCE_READ_FAILED")
                    run = run.model_copy(update={
                        "status": "failed", "error_code": code,
                        "finished_at": now_iso(),
                    })
                    result = RefreshRunResult(
                        skill_id=typed.skill_id, status="failed",
                        refresh_run=run,
                        error=ErrorEnvelope(
                            code=code,
                            message=str(error),
                            retryable=False,
                            request_id=request_id,
                        ),
                    )
                self.repository.save_refresh_run(run)
        elif command == "invocation.start":
            typed = InvocationStartPayload.model_validate(payload)
            result = InvocationStartResult(
                skill_version_id=typed.skill_version_id,
                error=self._not_ready_error(command, request_id),
            )
        else:
            result = InvocationStartResult(
                skill_version_id="unsupported",
                error=self._not_ready_error(command, request_id),
            )
        return CommandResponse(
            accepted=getattr(result, "status", "not_ready") == "succeeded",
            request_id=request_id,
            result=result,
        )

    @staticmethod
    def _not_ready_error(command: str, request_id: str) -> ErrorEnvelope:
        return ErrorEnvelope(
            code="COMMAND_NOT_READY",
            message=f"命令 {command} 尚未在当前 STEP 1 应用波次开放。",
            retryable=False,
            request_id=request_id,
        )

    def operation(self, operation_id: str) -> OperationResponse | None:
        return self.repository.operation(operation_id)

    def cancel(self, operation_id: str, request_id: str) -> OperationResponse:
        return self.repository.cancel_operation(operation_id, request_id)
