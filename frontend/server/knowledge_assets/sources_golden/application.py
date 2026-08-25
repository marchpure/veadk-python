"""Public façade for the Worker 1 source and Golden Data domain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from .adapters import (
    LocalSourceAdapter,
    adapter_contract,
    blocked_operation,
    validate_external_configuration,
)
from .catalog import (
    BUILTIN_CONNECTORS,
    bootstrap_connector_catalog,
    connector_catalog,
)
from .lifecycle import ContentAddressedArtifactStore, LocalLifecycle
from .mcp_stdio import McpProcessError, McpProcessStartError, StdioMcpClient
from .models import (
    AccessContext,
    AddDataView,
    CapabilityReason,
    ConnectionDetailView,
    ConnectionInstance,
    ConnectorCatalogView,
    ConnectorCategory,
    AdapterContract,
    CreateConnectionResult,
    DataOverviewView,
    GoldenDataView,
    GoldenAssetDetailView,
    GoldenResourceBinding,
    GoldenAssetSummary,
    GoldenOverview,
    IngestLifecycleResult,
    RefreshResult,
    RefreshRunRecord,
)
from .repository import SourcesGoldenRepository


class SourcesGoldenError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _object_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceGoldenApplication:
    """Small public surface; persistence and adapters stay behind this façade."""

    def __init__(
        self,
        *,
        database_path: str | Path,
        artifact_root: str | Path,
        source_root: str | Path,
        web_resolver=None,
        secret_resolver=None,
        mcp_profiles: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.artifact_root = Path(artifact_root)
        self.source_root = Path(source_root).resolve()
        self.repository = SourcesGoldenRepository(database_path)
        self._local_adapter = LocalSourceAdapter(root=self.source_root)
        self._artifact_store = ContentAddressedArtifactStore(self.artifact_root)
        self._lifecycle = LocalLifecycle(
            source_root=self.source_root,
            artifact_store=self._artifact_store,
        )
        self._web_resolver = web_resolver
        self._mcp_client = StdioMcpClient(secret_resolver=secret_resolver)
        self._mcp_profiles = {
            str(key): dict(value) for key, value in (mcp_profiles or {}).items()
        }

    def mcp_profile_configuration(
        self, profile_id: str, requested_tools: list[str]
    ) -> dict[str, object]:
        profile = self._mcp_profiles.get(profile_id)
        if profile is None:
            raise SourcesGoldenError(
                "MCP_PROFILE_NOT_CONFIGURED",
                "指定的 MCP server profile 未由服务端配置。",
            )
        forbidden = {"command", "args", "cwd", "env"}
        if any(key in profile for key in forbidden) is False:
            raise SourcesGoldenError(
                "MCP_PROFILE_INVALID",
                "MCP server profile 缺少服务端执行配置。",
            )
        configured_tools = [str(item) for item in profile.get("toolAllowlist", [])]
        if requested_tools and not set(requested_tools).issubset(set(configured_tools)):
            raise SourcesGoldenError(
                "MCP_TOOL_NOT_ALLOWED",
                "请求的 MCP tool 不在服务端 profile allowlist 中。",
            )
        configuration = {
            key: value
            for key, value in profile.items()
            if key not in {"profileId", "label"}
        }
        configuration["toolAllowlist"] = requested_tools or configured_tools
        return configuration

    def mcp_profile_catalog(self) -> list[dict[str, object]]:
        """Expose selectable MCP metadata without exposing execution fields."""
        profiles: list[dict[str, object]] = []
        for profile_id, profile in sorted(self._mcp_profiles.items()):
            profiles.append(
                {
                    "profileId": profile_id,
                    "label": str(profile.get("label") or profile_id),
                    "transport": str(profile.get("transport") or "stdio"),
                    "toolAllowlist": [
                        str(item) for item in profile.get("toolAllowlist", [])
                    ],
                }
            )
        return profiles

    def connector_catalog(
        self,
        context: AccessContext,
        *,
        category: ConnectorCategory | None = None,
        query: str | None = None,
    ) -> ConnectorCatalogView:
        del context
        return connector_catalog(category=category, query=query)

    def add_data(
        self, context: AccessContext, *, connector_key: str | None = None
    ) -> AddDataView:
        catalog = self.connector_catalog(context)
        selected = (
            self._definition(connector_key) if connector_key is not None else None
        )
        return AddDataView(
            catalog=catalog,
            selected_connector=selected,
            steps=["configure", "authorize", "discover", "save"],
            can_create=context.role in {"editor", "admin"},
            blocked_reason=(
                selected.reason
                if selected
                and selected.capability_state in {"credential_blocked", "unsupported"}
                else None
            ),
        )

    def bootstrap_projection(self, context: AccessContext) -> dict[str, object]:
        overview = self.data_overview(context)
        return {
            "routes": ["data_overview", "add_data", "connector_catalog"],
            "connections": [
                connection.model_dump(mode="json", by_alias=True)
                for connection in overview.connections
            ],
            "resources": [
                asset.model_dump(mode="json", by_alias=True)
                for asset in overview.golden_assets
            ],
            "workspaceData": {
                "connectorCatalog": bootstrap_connector_catalog(),
                "mcpProfileCatalog": self.mcp_profile_catalog(),
            },
        }

    def create_connection(
        self,
        context: AccessContext,
        *,
        connector_key: str,
        display_name: str,
        scope: str,
        configuration: dict[str, object],
        secret_ref: str | None,
        idempotency_key: str,
        trace_id: str,
    ) -> CreateConnectionResult:
        self._require_write(context)
        if scope not in {"personal", "team"} or not display_name.strip():
            raise SourcesGoldenError(
                "INVALID_CONNECTION",
                "Connection name and scope must be valid.",
            )
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        existing = self.repository.connection_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if existing is not None:
            operation = self._operation_for_existing(existing, trace_id)
            return CreateConnectionResult(
                connection=existing,
                validation=operation,
                discovery=operation.model_copy(update={"operation": "discover"}),
                replayed=True,
            )
        definition = self._definition(connector_key)
        self._validate_form(
            definition,
            configuration,
            secret_ref,
            workspace_id=context.workspace_id,
        )
        if definition.capability_state != "available":
            try:
                validate_external_configuration(
                    definition,
                    configuration,
                    web_resolver=self._web_resolver,
                )
            except ValueError as error:
                raise SourcesGoldenError("INVALID_CONFIGURATION", str(error)) from error
        timestamp = _now()
        public_configuration = self._public_configuration(configuration)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "workspace": context.workspace_id,
                    "principal": context.principal_id,
                    "connector": connector_key,
                    "idempotency": idempotency_key,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        connection_id = f"connection-{digest[:24]}"
        if connector_key == "mcp_custom" and configuration.get("transport") == "stdio":
            validation, discovery = self._create_stdio_mcp_operations(
                context=context,
                connection_id=connection_id,
                configuration=configuration,
                trace_id=trace_id,
            )
            status = "ready"
            last_success_at = timestamp
            last_error = None
        elif definition.capability_state == "available":
            path, validation = self._local_adapter.validate(
                connector_key=connector_key,
                configuration=configuration,
                trace_id=trace_id,
            )
            discovery = self._local_adapter.discover(
                connector_key=connector_key,
                path=path,
                trace_id=trace_id,
                configuration=configuration,
            )
            status = "ready"
            last_success_at = timestamp
            last_error = None
        else:
            effective_definition = (
                definition.model_copy(update={"capability_state": "credential_blocked"})
                if connector_key == "mcp_custom"
                else definition
            )
            validation = blocked_operation(
                effective_definition,
                operation="validate",
                trace_id=trace_id,
            )
            discovery = blocked_operation(
                effective_definition,
                operation="discover",
                trace_id=trace_id,
            )
            status = (
                "config_required"
                if effective_definition.capability_state == "configurable"
                else effective_definition.capability_state
            )
            last_success_at = None
            blocked_reason = CapabilityReason(
                code=(
                    "PROVIDER_EXECUTION_BLOCKED"
                    if effective_definition.capability_state == "credential_blocked"
                    else effective_definition.reason.code
                ),
                message=effective_definition.reason.message,
                retryable=effective_definition.reason.retryable,
            )
            validation = validation.model_copy(update={"reason": blocked_reason})
            discovery = discovery.model_copy(update={"reason": blocked_reason})
            last_error = blocked_reason
        connection = ConnectionInstance(
            id=connection_id,
            workspace_id=context.workspace_id,
            connector_key=connector_key,
            display_name=display_name.strip(),
            scope=scope,
            owner_id=context.principal_id,
            status=status,
            configuration=public_configuration,
            secret_ref=secret_ref,
            sync_mode=definition.sync_modes[0],
            created_at=timestamp,
            updated_at=timestamp,
            last_success_at=last_success_at,
            last_error=last_error,
            discovered_resources=discovery.resources,
        )
        self.repository.save_connection(
            connection, idempotency_key=scoped_idempotency_key
        )
        for operation in (validation, discovery):
            self.repository.record_operation(
                workspace_id=context.workspace_id,
                connection_id=connection.id,
                trace_id=trace_id,
                operation=operation.operation,
                status=operation.status,
                payload=operation.model_dump(mode="json", by_alias=True),
                created_at=timestamp,
            )
        return CreateConnectionResult(
            connection=connection,
            validation=validation,
            discovery=discovery,
        )

    def _create_stdio_mcp_operations(
        self,
        *,
        context: AccessContext,
        connection_id: str,
        configuration: dict[str, object],
        trace_id: str,
    ):
        from .models import ConnectorOperation, DiscoveredResource

        try:
            tools, trace = self._mcp_client.discover(
                workspace_id=context.workspace_id,
                principal_id=context.principal_id,
                connection_id=connection_id,
                configuration=configuration,
                trace_id=trace_id,
            )
            self.repository.save_mcp_trace(trace)
        except ValueError as error:
            raise SourcesGoldenError(
                "MCP_CONFIGURATION_INVALID",
                "stdio MCP configuration is invalid.",
            ) from error
        except McpProcessStartError as error:
            raise SourcesGoldenError(error.code, str(error)) from error
        except McpProcessError as error:
            self.repository.save_mcp_trace(error.trace)
            raise SourcesGoldenError(error.code, str(error)) from error
        resources = []
        for tool in tools:
            if not tool.get("name"):
                continue
            resources.append(
                DiscoveredResource(
                    id="mcp-tool-"
                    + hashlib.sha256(str(tool["name"]).encode()).hexdigest()[:24],
                    name=str(tool["name"]),
                    resource_type="tool",
                    input_schema=_object_mapping(tool.get("inputSchema")),
                    output_schema=_object_mapping(tool.get("outputSchema")),
                )
            )
        reason = CapabilityReason(
            code="MCP_STDIO_READY",
            message="Independent MCP subprocess initialized and tools were discovered.",
        )
        return (
            ConnectorOperation(
                operation="validate",
                status="succeeded",
                trace_id=trace_id,
                reason=reason,
            ),
            ConnectorOperation(
                operation="discover",
                status="succeeded",
                trace_id=trace_id,
                reason=reason,
                resources=resources,
            ),
        )

    def data_overview(self, context: AccessContext) -> DataOverviewView:
        connections = [
            connection
            for connection in self.repository.connections(context.workspace_id)
            if self._can_access_connection(context, connection)
        ]
        by_id = {connection.id: connection for connection in connections}
        golden_assets = [
            GoldenAssetSummary(
                asset_id=revision.asset_id,
                golden_revision_id=revision.id,
                revision=revision.revision,
                display_name=(
                    next(
                        (
                            resource.name
                            for resource in by_id[
                                revision.lineage.connection_id
                            ].discovered_resources
                            if resource.id == revision.lineage.resource_id
                        ),
                        by_id[revision.lineage.connection_id].display_name,
                    )
                ),
                asset_kind=revision.asset_kind,
                connector_key=by_id[revision.lineage.connection_id].connector_key,
                quality_score=revision.quality_score,
                freshness_at=revision.freshness_at,
                owner=revision.owner,
                permissions=revision.permissions,
                trace_id=revision.trace_id,
            )
            for revision in self.repository.latest_golden_assets(context.workspace_id)
            if revision.lineage.connection_id in by_id
        ]
        return DataOverviewView(
            workspace_id=context.workspace_id,
            connections=connections,
            golden_assets=golden_assets,
            can_create=context.role in {"editor", "admin"},
            empty_state=None if connections else "no_connections",
        )

    def connection_detail(
        self, context: AccessContext, connection_id: str
    ) -> ConnectionDetailView:
        connection = self._connection_for_context(context, connection_id)
        actions = ["read"]
        if context.role in {"editor", "admin"}:
            actions.extend(["refresh", "delete", "revoke"])
        return ConnectionDetailView(
            connection=connection,
            connector=self._definition(connection.connector_key),
            actions=actions,
        )

    def adapter_contract(self, connector_key: str) -> AdapterContract:
        return adapter_contract(self._definition(connector_key))

    def ingest(
        self,
        context: AccessContext,
        *,
        connection_id: str,
        resource_id: str | None,
        recipe_operations: list[str],
        tool_arguments: dict[str, object] | None = None,
        idempotency_key: str,
        trace_id: str,
    ) -> IngestLifecycleResult:
        self._require_write(context)
        connection = self._connection_for_context(context, connection_id)
        self._validate_tool_arguments(tool_arguments or {})
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        replay = self.repository.ingest_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if replay is not None:
            return IngestLifecycleResult(
                status="succeeded",
                source_revision=replay[0],
                profile_run=replay[1],
                cleaning_recipe=replay[2],
                clean_run=replay[3],
                golden_asset_revision=replay[4],
                replayed=True,
            )
        if connection.status != "ready":
            raise SourcesGoldenError(
                "CONNECTION_NOT_READY",
                "A blocked connection cannot produce source revisions.",
            )
        if resource_id is None and len(connection.discovered_resources) == 1:
            resource_id = connection.discovered_resources[0].id
        if not resource_id:
            raise SourcesGoldenError(
                "RESOURCE_REQUIRED",
                "Select one discovered source resource.",
            )
        asset_id = (
            "golden-"
            + hashlib.sha256(f"{connection.id}:{resource_id}".encode()).hexdigest()[:24]
        )
        timestamp = _now()
        try:
            materialized = None
            if connection.connector_key == "mcp_custom":
                selected = next(
                    (
                        item
                        for item in connection.discovered_resources
                        if item.id == resource_id and item.resource_type == "tool"
                    ),
                    None,
                )
                if selected is None:
                    raise ValueError("MCP tool was not discovered by this connection")
                try:
                    call = self._mcp_client.call(
                        workspace_id=context.workspace_id,
                        principal_id=context.principal_id,
                        connection_id=connection.id,
                        configuration=connection.configuration,
                        trace_id=trace_id,
                        tool_name=selected.name,
                        tool_arguments=tool_arguments or {},
                    )
                    self.repository.save_mcp_trace(call.trace)
                except McpProcessError as error:
                    self.repository.save_mcp_trace(error.trace)
                    raise
                materialized = self._lifecycle.materialized_mcp(
                    tool_name=call.tool_name,
                    rows=call.rows,
                    fields=call.schema,
                    adapter_run_id=call.structured_result.run_id,
                )
            records = self._lifecycle.build(
                connection=connection,
                resource_id=resource_id,
                operations=recipe_operations,
                recipe_version=self.repository.next_recipe_version(asset_id),
                golden_revision=self.repository.next_golden_revision(
                    context.workspace_id, asset_id
                ),
                principal_id=context.principal_id,
                trace_id=trace_id,
                timestamp=timestamp,
                materialized=materialized,
                tool_arguments=tool_arguments,
            )
        except (
            McpProcessError,
            McpProcessStartError,
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            raise SourcesGoldenError(
                getattr(error, "code", "SOURCE_INGEST_FAILED"), str(error)
            ) from error
        self.repository.save_ingest(
            source=records.source,
            profile=records.profile,
            recipe=records.recipe,
            clean=records.clean,
            golden=records.golden,
            idempotency_key=scoped_idempotency_key,
        )
        return IngestLifecycleResult(
            status="succeeded",
            source_revision=records.source,
            profile_run=records.profile,
            cleaning_recipe=records.recipe,
            clean_run=records.clean,
            golden_asset_revision=records.golden,
        )

    def golden_data(self, context: AccessContext, revision_id: str) -> GoldenDataView:
        revision = self.golden_revision(context, revision_id)
        rows = [
            json.loads(line)
            for line in self._artifact_store.read(revision.storage_ref)
            .decode("utf-8")
            .splitlines()
            if line.strip()
        ]
        return GoldenDataView(
            binding=self.golden_resource_binding(context, revision_id),
            rows=rows,
        )

    def golden_resource_binding(
        self, context: AccessContext, revision_id: str
    ) -> GoldenResourceBinding:
        revision = self.golden_revision(context, revision_id)
        source = self.source_revision(context, revision.lineage.source_revision_id)
        profile = self.repository.profile_run(revision.lineage.profile_run_id)
        connection = self._connection_for_context(
            context, revision.lineage.connection_id
        )
        if profile is None:
            raise SourcesGoldenError(
                "LIFECYCLE_NOT_FOUND",
                "Golden Asset profile is unavailable.",
            )
        resource = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == revision.lineage.resource_id
            ),
            None,
        )
        return GoldenResourceBinding(
            object_id=revision.asset_id,
            revision=revision.id,
            provider_revision=source.id,
            display_name=(resource.name if resource else connection.display_name),
            scope=connection.scope,
            schema_digest=revision.schema_digest,
            content_digest=revision.lineage.content_digest,
            semantic_fields=[field.name for field in profile.fields],
            capabilities=[
                "source.read",
                "golden_data.read",
                "lineage.read",
                "freshness.read",
            ],
            freshness_at=revision.freshness_at,
            data_as_of=revision.data_as_of,
            lineage=revision.lineage,
            permissions=revision.permissions,
            authorized=True,
        )

    def golden_asset_detail(
        self, context: AccessContext, asset_id: str
    ) -> GoldenAssetDetailView:
        asset = self.repository.latest_golden(context.workspace_id, asset_id)
        if asset is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, asset.lineage.connection_id)
        profile = self.repository.profile_run(asset.lineage.profile_run_id)
        clean = self.repository.clean_run(asset.lineage.clean_run_id)
        if profile is None or clean is None:
            raise SourcesGoldenError(
                "LIFECYCLE_NOT_FOUND",
                "Golden Asset profile or clean run is unavailable.",
            )
        quality_report = json.loads(self._artifact_store.read(clean.quality_report_ref))
        preview = [
            json.loads(line)
            for line in self._artifact_store.read(asset.storage_ref)
            .decode("utf-8")
            .splitlines()
            if line.strip()
        ][:100]
        safe_preview = [
            {
                key: (
                    "[REDACTED]"
                    if key in profile.sensitive_fields and value not in (None, "")
                    else value
                )
                for key, value in row.items()
            }
            for row in preview
        ]
        return GoldenAssetDetailView(
            asset=asset,
            overview=GoldenOverview(
                row_count=int(quality_report["outputRows"]),
                field_count=len(profile.fields),
                storage_bytes=asset.storage_ref.bytes,
                quality_score=asset.quality_score,
                freshness_at=asset.freshness_at,
            ),
            preview=safe_preview,
            fields=profile.fields,
            profile=profile,
            lineage=asset.lineage,
            owner=asset.owner,
            permissions=asset.permissions,
            tabs=[
                "overview",
                "preview",
                "fields",
                "lineage",
                "quality",
                "usage",
            ],
        )

    def golden_revision(self, context: AccessContext, revision_id: str):
        revision = self.repository.golden_revision(context.workspace_id, revision_id)
        if revision is None:
            raise SourcesGoldenError(
                "GOLDEN_REVISION_NOT_FOUND",
                "Golden revision does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, revision.lineage.connection_id)
        return revision

    def source_revision(self, context: AccessContext, revision_id: str):
        revision = self.repository.source_revision(context.workspace_id, revision_id)
        if revision is None:
            raise SourcesGoldenError(
                "SOURCE_REVISION_NOT_FOUND",
                "Source revision does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, revision.connection_id)
        return revision

    def refresh(
        self,
        context: AccessContext,
        *,
        asset_id: str,
        idempotency_key: str,
        trace_id: str,
        retry_of: str | None = None,
    ) -> RefreshResult:
        self._require_write(context)
        previous = self.repository.latest_golden(context.workspace_id, asset_id)
        if previous is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        connection = self._connection_for_context(
            context, previous.lineage.connection_id
        )
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        replay = self.repository.refresh_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if replay is not None:
            promoted = (
                self.repository.golden_revision_including_revoked(
                    context.workspace_id, replay.promoted_revision_id
                )
                if replay.promoted_revision_id
                else None
            )
            return RefreshResult(
                run=replay,
                golden_asset_revision=promoted,
                last_good_revision=self.repository.latest_golden(
                    context.workspace_id, asset_id
                ),
            )
        timestamp = _now()
        run_id = (
            "refresh-"
            + hashlib.sha256(
                (
                    f"{context.workspace_id}:{context.principal_id}:{idempotency_key}"
                ).encode()
            ).hexdigest()[:24]
        )
        prior_recipe = self.repository.cleaning_recipe(
            previous.lineage.recipe_id, previous.lineage.recipe_version
        )
        operations: list[str] = (
            list(prior_recipe.operations) if prior_recipe else ["trim"]
        )
        candidate = None
        try:
            candidate = self._lifecycle.build(
                connection=connection,
                resource_id=previous.lineage.resource_id,
                operations=operations,
                recipe_version=self.repository.next_recipe_version(asset_id),
                golden_revision=previous.revision + 1,
                principal_id=context.principal_id,
                trace_id=trace_id,
                timestamp=timestamp,
                materialized=self._mcp_materialized(
                    context=context,
                    connection=connection,
                    resource_id=previous.lineage.resource_id,
                    tool_arguments=previous.lineage.tool_arguments,
                    trace_id=trace_id,
                )
                if connection.connector_key == "mcp_custom"
                else None,
                tool_arguments=previous.lineage.tool_arguments,
            )
            if candidate.golden.schema_digest != previous.schema_digest:
                run = RefreshRunRecord(
                    id=run_id,
                    workspace_id=context.workspace_id,
                    asset_id=asset_id,
                    status="schema_drift",
                    previous_revision_id=previous.id,
                    staging_ref=candidate.golden.storage_ref,
                    reason=CapabilityReason(
                        code="SCHEMA_DRIFT",
                        message="Schema changed; staging output was not promoted.",
                    ),
                    retry_of=retry_of,
                    trace_id=trace_id,
                    started_at=timestamp,
                    finished_at=_now(),
                )
                self.repository.save_refresh(
                    run, idempotency_key=scoped_idempotency_key
                )
                return RefreshResult(run=run, last_good_revision=previous)
            self.repository.save_ingest(
                source=candidate.source,
                profile=candidate.profile,
                recipe=candidate.recipe,
                clean=candidate.clean,
                golden=candidate.golden,
                idempotency_key=(f"refresh-ingest:{scoped_idempotency_key}"),
            )
            run = RefreshRunRecord(
                id=run_id,
                workspace_id=context.workspace_id,
                asset_id=asset_id,
                status="succeeded",
                previous_revision_id=previous.id,
                promoted_revision_id=candidate.golden.id,
                staging_ref=candidate.golden.storage_ref,
                reason=CapabilityReason(
                    code="PROMOTED",
                    message="Staging passed schema, quality, and permission gates.",
                ),
                retry_of=retry_of,
                trace_id=trace_id,
                started_at=timestamp,
                finished_at=_now(),
            )
            self.repository.save_refresh(run, idempotency_key=scoped_idempotency_key)
            return RefreshResult(
                run=run,
                golden_asset_revision=candidate.golden,
                last_good_revision=candidate.golden,
            )
        except (
            McpProcessError,
            McpProcessStartError,
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            code = (
                "PERMISSION_REVOKED"
                if isinstance(error, PermissionError)
                else getattr(error, "code", "SOURCE_READ_FAILED")
            )
            status = "permission_denied" if code == "PERMISSION_REVOKED" else "failed"
            run = RefreshRunRecord(
                id=run_id,
                workspace_id=context.workspace_id,
                asset_id=asset_id,
                status=status,
                previous_revision_id=previous.id,
                staging_ref=candidate.golden.storage_ref if candidate else None,
                reason=CapabilityReason(
                    code=code,
                    message=str(error),
                    retryable=code
                    in {
                        "SOURCE_READ_FAILED",
                        "MCP_PROCESS_START_FAILED",
                        "MCP_PROCESS_EXITED",
                        "MCP_TIMEOUT",
                    },
                ),
                retry_of=retry_of,
                trace_id=trace_id,
                started_at=timestamp,
                finished_at=_now(),
            )
            self.repository.save_refresh(run, idempotency_key=scoped_idempotency_key)
            return RefreshResult(run=run, last_good_revision=previous)

    def retry_refresh(
        self,
        context: AccessContext,
        *,
        failed_run_id: str,
        idempotency_key: str,
        trace_id: str,
    ) -> RefreshResult:
        self._require_write(context)
        previous_run = self.repository.refresh_run(context.workspace_id, failed_run_id)
        if previous_run is None:
            raise SourcesGoldenError(
                "REFRESH_NOT_RETRYABLE",
                "The requested refresh run is not retryable.",
            )
        previous = self.repository.latest_golden(
            context.workspace_id, previous_run.asset_id
        )
        if previous is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, previous.lineage.connection_id)
        if previous_run.status not in {
            "failed",
            "schema_drift",
            "permission_denied",
        }:
            raise SourcesGoldenError(
                "REFRESH_NOT_RETRYABLE",
                "The requested refresh run is not retryable.",
            )
        return self.refresh(
            context,
            asset_id=previous_run.asset_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            retry_of=failed_run_id,
        )

    def cancel_refresh(
        self,
        context: AccessContext,
        *,
        asset_id: str,
        idempotency_key: str,
        trace_id: str,
    ) -> RefreshRunRecord:
        self._require_write(context)
        previous = self.repository.latest_golden(context.workspace_id, asset_id)
        if previous is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, previous.lineage.connection_id)
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        replay = self.repository.refresh_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if replay is not None:
            return replay
        timestamp = _now()
        run = RefreshRunRecord(
            id="refresh-"
            + hashlib.sha256(
                (
                    f"{context.workspace_id}:{context.principal_id}:{idempotency_key}"
                ).encode()
            ).hexdigest()[:24],
            workspace_id=context.workspace_id,
            asset_id=asset_id,
            status="cancelled",
            previous_revision_id=previous.id,
            reason=CapabilityReason(
                code="CANCELLED",
                message="Refresh was cancelled before source processing.",
            ),
            trace_id=trace_id,
            started_at=timestamp,
            finished_at=timestamp,
        )
        self.repository.save_refresh(run, idempotency_key=scoped_idempotency_key)
        return run

    def revoke_connection(
        self,
        context: AccessContext,
        connection_id: str,
        *,
        reason: str,
        trace_id: str,
    ) -> None:
        self._require_write(context)
        connection = self._connection_for_context(context, connection_id)
        timestamp = _now()
        revoked = connection.model_copy(
            update={
                "status": "revoked",
                "updated_at": timestamp,
                "last_error": CapabilityReason(
                    code="PERMISSION_REVOKED", message=reason
                ),
            }
        )
        self.repository.revoke_connection(
            workspace_id=context.workspace_id,
            connection_id=connection_id,
            revoked_at=timestamp,
            replacement=revoked,
        )
        self.repository.record_operation(
            workspace_id=context.workspace_id,
            connection_id=connection_id,
            trace_id=trace_id,
            operation="revoke",
            status="succeeded",
            payload={
                "reason": {
                    "code": "PERMISSION_REVOKED",
                    "message": reason,
                }
            },
            created_at=timestamp,
        )

    def delete_connection(
        self,
        context: AccessContext,
        connection_id: str,
        *,
        trace_id: str,
    ) -> None:
        self.revoke_connection(
            context,
            connection_id,
            reason="Connection deleted by an authorized user.",
            trace_id=trace_id,
        )

    def mcp_process_traces(self, context: AccessContext, connection_id: str):
        self._connection_for_context(context, connection_id, include_revoked=True)
        return self.repository.mcp_traces(context.workspace_id, connection_id)

    def mcp_process_traces_for_workspace(self, context: AccessContext):
        accessible = {
            connection.id
            for connection in self.repository.connections(context.workspace_id)
            if self._can_access_connection(context, connection)
        }
        return [
            trace
            for trace in self.repository.mcp_traces_for_workspace(context.workspace_id)
            if trace.connection_id in accessible
            or trace.principal_id == context.principal_id
        ]

    def _mcp_materialized(
        self,
        *,
        context: AccessContext,
        connection,
        resource_id: str,
        tool_arguments: dict[str, object],
        trace_id: str,
    ):
        selected = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == resource_id and item.resource_type == "tool"
            ),
            None,
        )
        if selected is None:
            raise ValueError("MCP tool was not discovered by this connection")
        try:
            call = self._mcp_client.call(
                workspace_id=context.workspace_id,
                principal_id=context.principal_id,
                connection_id=connection.id,
                configuration=connection.configuration,
                trace_id=trace_id,
                tool_name=selected.name,
                tool_arguments=tool_arguments,
            )
            self.repository.save_mcp_trace(call.trace)
        except McpProcessError as error:
            self.repository.save_mcp_trace(error.trace)
            raise
        return self._lifecycle.materialized_mcp(
            tool_name=call.tool_name,
            rows=call.rows,
            fields=call.schema,
            adapter_run_id=call.structured_result.run_id,
        )

    @staticmethod
    def _require_write(context: AccessContext) -> None:
        if context.role not in {"editor", "admin"}:
            raise SourcesGoldenError(
                "PERMISSION_DENIED", "source.write permission is required."
            )

    @staticmethod
    def _can_access_connection(
        context: AccessContext, connection: ConnectionInstance
    ) -> bool:
        return connection.scope == "team" or connection.owner_id == context.principal_id

    def _connection_for_context(
        self,
        context: AccessContext,
        connection_id: str,
        *,
        include_revoked: bool = False,
    ) -> ConnectionInstance:
        loader = (
            self.repository.connection_including_revoked
            if include_revoked
            else self.repository.connection
        )
        connection = loader(context.workspace_id, connection_id)
        if connection is None:
            raise SourcesGoldenError(
                "CONNECTION_NOT_FOUND",
                "Connection does not exist in the authenticated workspace.",
            )
        if not self._can_access_connection(context, connection):
            raise SourcesGoldenError(
                "PERMISSION_DENIED",
                "Connection is not available to the authenticated principal.",
            )
        return connection

    @staticmethod
    def _scoped_idempotency(context: AccessContext, idempotency_key: str) -> str:
        return f"{context.principal_id}:{idempotency_key}"

    @staticmethod
    def _definition(connector_key: str):
        definition = next(
            (
                item
                for item in BUILTIN_CONNECTORS
                if item.connector_key == connector_key
            ),
            None,
        )
        if definition is None:
            raise SourcesGoldenError(
                "CONNECTOR_NOT_FOUND", "Unknown connector definition."
            )
        return definition

    @staticmethod
    def _validate_form(
        definition,
        configuration: dict[str, object],
        secret_ref: str | None,
        *,
        workspace_id: str,
    ) -> None:
        properties = definition.input_schema.properties
        secret_names = {
            key
            for key in configuration
            if key in {"password", "token", "apiKey", "api_key", "secret", "credential"}
            or "password" in key.casefold()
            or "tokenvalue" in key.casefold()
        }
        if secret_names:
            raise SourcesGoldenError(
                "INLINE_SECRET_REJECTED",
                "Credentials must be supplied only as a secretRef.",
            )
        unknown = set(configuration) - set(properties)
        if unknown:
            raise SourcesGoldenError(
                "INVALID_CONFIGURATION",
                f"Fields are not valid for {definition.connector_key}: {sorted(unknown)}",
            )
        missing = [
            key
            for key in definition.input_schema.required
            if configuration.get(key) in (None, "", [])
        ]
        if missing:
            raise SourcesGoldenError(
                "INVALID_CONFIGURATION", f"Required fields are missing: {missing}"
            )
        if secret_ref is not None and not secret_ref.startswith(
            f"secret://{workspace_id}/"
        ):
            raise SourcesGoldenError(
                "INVALID_SECRET_REFERENCE",
                "secretRef must identify the active workspace's server-side secret store.",
            )

    @staticmethod
    def _validate_tool_arguments(arguments: dict[str, object]) -> None:
        def contains_sensitive_value(value: object) -> bool:
            if isinstance(value, dict):
                return any(
                    any(
                        marker in str(key).casefold().replace("-", "").replace("_", "")
                        for marker in (
                            "password",
                            "token",
                            "secret",
                            "credential",
                            "apikey",
                            "privatekey",
                        )
                    )
                    or contains_sensitive_value(item)
                    for key, item in value.items()
                )
            if isinstance(value, list):
                return any(contains_sensitive_value(item) for item in value)
            return isinstance(value, str) and value.startswith("secret://")

        if contains_sensitive_value(arguments):
            raise SourcesGoldenError(
                "INLINE_SECRET_REJECTED",
                "MCP tool credentials must use runtime secretRef environment injection.",
            )

    @staticmethod
    def _public_configuration(
        configuration: dict[str, object],
    ) -> dict[str, str | int | float | bool | list[str] | dict[str, str]]:
        return {
            key: value
            for key, value in configuration.items()
            if isinstance(value, (str, int, float, bool))
            or (
                isinstance(value, list) and all(isinstance(item, str) for item in value)
            )
            or (
                isinstance(value, dict)
                and all(
                    isinstance(item_key, str) and isinstance(item_value, str)
                    for item_key, item_value in value.items()
                )
            )
        }

    @staticmethod
    def _operation_for_existing(connection: ConnectionInstance, trace_id: str):
        from .models import ConnectorOperation

        succeeded = connection.status == "ready"
        return ConnectorOperation(
            operation="validate",
            status="succeeded" if succeeded else connection.status,
            trace_id=trace_id,
            reason=connection.last_error
            or CapabilityReason(
                code="IDEMPOTENT_REPLAY",
                message="The persisted connection result was replayed.",
            ),
            resources=connection.discovered_resources,
        )
