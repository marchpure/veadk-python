"""Worker-owned typed contracts for source catalog and Golden Data views."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from ..contract_base import ContractModel

ConnectorCategory = Literal["office", "file", "db", "api", "custom"]
CapabilityState = Literal[
    "available", "configurable", "credential_blocked", "unsupported"
]
SyncMode = Literal["full", "incremental", "realtime"]
SourceType = Literal[
    "markdown",
    "text",
    "html",
    "csv",
    "excel",
    "json",
    "parquet",
    "pdf",
    "sqlite",
    "mcp",
    "http",
    "database",
    "office",
]
CleaningOperation = Literal["trim", "deduplicate", "normalize", "redact"]
McpMethod = Literal[
    "initialize",
    "notifications/initialized",
    "tools/list",
    "tools/call",
    "shutdown",
    "stdio/eof",
]
RemoteMcpMethod = Literal["initialize", "tools/list", "tools/call", "close"]
McpTraceStatus = Literal["succeeded", "failed", "timed_out"]
McpShutdownMode = Literal["jsonrpc", "stdio_eof", "forced_termination"]
ConnectorOperationName = Literal[
    "validate",
    "authenticate",
    "authorize",
    "discover",
    "introspect",
    "sample",
    "read",
    "ingest",
    "profile",
    "clean",
    "golden",
    "refresh",
    "checkpoint",
    "close",
    "revoke",
    "delete",
]
FormFieldType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "file",
    "url",
    "select",
    "string_array",
    "object",
]


class AccessContext(ContractModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    principal_id: str = Field(min_length=1, max_length=256)
    role: Literal["viewer", "editor", "admin"]


class FormField(ContractModel):
    type: FormFieldType
    title: str
    description: str = ""
    required: bool = False
    default: str | int | float | bool | list[str] | None = None
    options: list[str] = Field(default_factory=list)
    secret_reference: bool = False
    format: str | None = None
    min: float | None = None
    max: float | None = None
    conditional: dict[str, object] | None = None


class FormSchema(ContractModel):
    properties: dict[str, FormField]
    required: list[str] = Field(default_factory=list)
    additional_properties: Literal[False] = False


class ConnectorPermission(ContractModel):
    read_scopes: list[str]
    manage_scopes: list[str]
    provider_scopes: list[str] = Field(default_factory=list)
    inherits_source_acl: bool = False


class CapabilityReason(ContractModel):
    code: str
    message: str
    retryable: bool = False


class ConnectorDefinition(ContractModel):
    connector_key: str
    category: ConnectorCategory
    name: str
    description: str
    capabilities: list[str]
    capability_state: CapabilityState
    input_schema: FormSchema
    credential_schema: FormSchema
    discovery_modes: list[str]
    sync_modes: list[SyncMode]
    permissions: ConnectorPermission
    reason: CapabilityReason


class CreateCustomConnectorAction(ContractModel):
    connector_key: Literal["create_custom"] = "create_custom"
    capability_state: Literal["unsupported"] = "unsupported"
    required_permission: str = "connector.definition.create"


class ConnectorCatalogView(ContractModel):
    view: Literal["connector_catalog"] = "connector_catalog"
    connectors: list[ConnectorDefinition]
    create_custom_action: CreateCustomConnectorAction = Field(
        default_factory=CreateCustomConnectorAction
    )
    categories: dict[ConnectorCategory, int]
    total: int


ConnectionStatus = Literal[
    "ready", "config_required", "credential_blocked", "unsupported", "revoked"
]
OperationStatus = Literal[
    "succeeded", "config_required", "credential_blocked", "unsupported", "failed"
]


class DiscoveredField(ContractModel):
    name: str
    data_type: str
    nullable: bool = True


class DiscoveredResource(ContractModel):
    id: str
    name: str
    resource_type: Literal["file", "table", "document", "operation", "tool"]
    schema_name: str | None = None
    row_count: int | None = Field(default=None, ge=0)
    fields: list[DiscoveredField] = Field(default_factory=list)
    input_schema: dict[str, object] | None = None
    output_schema: dict[str, object] | None = None
    permission: Literal["read", "denied"] = "read"


class ConnectorOperation(ContractModel):
    operation: ConnectorOperationName
    status: OperationStatus
    trace_id: str
    reason: CapabilityReason
    resources: list[DiscoveredResource] = Field(default_factory=list)


class ConnectorOperationRecord(ContractModel):
    id: str
    workspace_id: str
    connection_id: str
    trace_id: str
    operation: str
    status: OperationStatus
    reason: CapabilityReason
    resources: list[DiscoveredResource] = Field(default_factory=list)
    checkpoint: dict[str, str] = Field(default_factory=dict)
    created_at: str


class ConnectorEventRecord(ContractModel):
    id: str
    workspace_id: str
    connection_id: str
    sequence: int = Field(ge=1)
    event_type: str
    trace_id: str
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: JsonValue
    created_at: str


class ConnectorTraceView(ContractModel):
    trace_id: str
    workspace_id: str
    connection_id: str
    operations: list[ConnectorOperationRecord] = Field(default_factory=list)
    events: list[ConnectorEventRecord] = Field(default_factory=list)


class ConnectorCapabilityEvidence(ContractModel):
    catalog: Literal["present"] = "present"
    form: Literal["validated"] = "validated"
    adapter: str
    validation: Literal["implemented"] = "implemented"
    authentication: Literal["implemented"] = "implemented"
    authorization: Literal["implemented"] = "implemented"
    discovery: Literal["implemented"] = "implemented"
    read: Literal["implemented"] = "implemented"
    refresh: Literal["implemented"] = "implemented"
    checkpoint: str
    typed_error: Literal["implemented"] = "implemented"
    verification_category: Literal[
        "LIVE_VERIFIED",
        "LOCAL_PROTOCOL_VERIFIED",
        "CREDENTIAL_BLOCKED",
        "UNSUPPORTED",
    ]
    live_e2e: Literal["passed", "external_blocked"]
    credential_state: Literal["not_required", "available", "external_blocked"]
    blocker: str | None = None
    evidence: list[str] = Field(min_length=1)


class ConnectorCapabilityRow(ContractModel):
    connector_key: str
    category: ConnectorCategory
    capability_state: CapabilityState
    permissions: ConnectorPermission
    certification: ConnectorCertificationView
    capability: ConnectorCapabilityEvidence


class ConnectorCertificationView(ContractModel):
    implementation: str
    driver: str
    install_command: str
    verification_command: str
    missing_condition: str
    required_secret_fields: list[str]
    provider_scopes: list[str]
    checkpoint: str


class ConnectorCapabilityMatrix(ContractModel):
    schema_version: Literal["knowledge-assets.step3b.w1-capability-matrix.v1"] = (
        "knowledge-assets.step3b.w1-capability-matrix.v1"
    )
    total: Literal[37] = 37
    connectors: list[ConnectorCapabilityRow] = Field(min_length=37, max_length=37)


class ConnectionInstance(ContractModel):
    id: str
    workspace_id: str
    connector_key: str
    display_name: str
    scope: Literal["personal", "team"]
    owner_id: str
    status: ConnectionStatus
    configuration: dict[str, JsonValue]
    secret_ref: str | None = None
    sync_mode: Literal["full", "incremental", "realtime", "local"]
    created_at: str
    updated_at: str
    last_success_at: str | None = None
    last_error: CapabilityReason | None = None
    discovered_resources: list[DiscoveredResource] = Field(default_factory=list)
    golden_revision_ids: list[str] = Field(default_factory=list)


class ConnectionViewModel(ContractModel):
    """The only connection representation safe to expose to browser clients."""

    id: str
    workspace_id: str
    connector_key: str
    display_name: str
    scope: Literal["personal", "team"]
    owner_id: str
    status: ConnectionStatus
    sync_mode: Literal["full", "incremental", "realtime", "local"]
    created_at: str
    updated_at: str
    last_success_at: str | None = None
    last_error: CapabilityReason | None = None
    discovered_resources: list[DiscoveredResource] = Field(default_factory=list)
    golden_revision_ids: list[str] = Field(default_factory=list)


class CreateConnectionResult(ContractModel):
    connection: ConnectionViewModel
    validation: ConnectorOperation
    discovery: ConnectorOperation
    replayed: bool = False


class DataOverviewView(ContractModel):
    view: Literal["data_overview"] = "data_overview"
    workspace_id: str
    connections: list[ConnectionViewModel]
    golden_assets: list[GoldenAssetSummary] = Field(default_factory=list)
    can_create: bool
    add_data_route: Literal["add_data"] = "add_data"
    empty_state: str | None = None


class ConnectionDetailView(ContractModel):
    view: Literal["connection_detail"] = "connection_detail"
    connection: ConnectionViewModel
    connector: ConnectorDefinition
    actions: list[str]


class AdapterContract(ContractModel):
    connector_key: str
    protocol: str
    operations: list[str]
    configuration_schema: FormSchema
    credential_schema: FormSchema
    security_controls: list[str]
    execution_state: Literal[
        "available", "configurable", "credential_blocked", "unsupported"
    ]


class ArtifactRef(ContractModel):
    uri: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str
    bytes: int = Field(ge=0)


class AssetOwner(ContractModel):
    workspace_id: str
    principal_id: str


class AssetPermission(ContractModel):
    workspace_id: str
    scope: Literal["personal", "team"]
    can_read: bool
    can_write: bool
    inherited_from_connection_id: str
    version: int = Field(ge=1)


class SourceRevisionRecord(ContractModel):
    id: str
    workspace_id: str
    connection_id: str
    resource_id: str
    source_type: SourceType
    content_ref: ArtifactRef
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str
    permission_version: int = Field(ge=1)
    checkpoint: dict[str, str] = Field(default_factory=dict)
    created_at: str
    trace_id: str


class ProfileField(ContractModel):
    name: str
    data_type: str
    nullable: bool
    null_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    sensitive: bool = False


class ProfileRunRecord(ContractModel):
    id: str
    source_revision_id: str
    status: Literal["succeeded", "failed", "cancelled"]
    row_count: int = Field(ge=0)
    fields: list[ProfileField]
    quality_score: float = Field(ge=0, le=1)
    sensitive_fields: list[str]
    report_ref: ArtifactRef
    sample_ref: ArtifactRef
    started_at: str
    finished_at: str
    trace_id: str


class CleaningRecipeRecord(ContractModel):
    id: str
    asset_id: str
    version: int = Field(ge=1)
    source_revision_id: str
    operations: list[CleaningOperation]
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str


class CleanRunRecord(ContractModel):
    id: str
    source_revision_id: str
    recipe_id: str
    status: Literal["succeeded", "failed", "cancelled"]
    output_ref: ArtifactRef
    quality_report_ref: ArtifactRef
    started_at: str
    finished_at: str
    trace_id: str


class GoldenLineage(ContractModel):
    connection_id: str
    resource_id: str
    source_revision_id: str
    profile_run_id: str
    recipe_id: str
    recipe_version: int = Field(ge=1)
    clean_run_id: str
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    correlation_id: str
    adapter_run_id: str | None = None
    checkpoint: dict[str, str] = Field(default_factory=dict)
    lineage_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_arguments: dict[str, object] = Field(default_factory=dict)


class GoldenAssetRevisionRecord(ContractModel):
    id: str
    asset_id: str
    revision: int = Field(ge=1)
    asset_kind: Literal["dataset", "knowledge"]
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    storage_ref: ArtifactRef
    owner: AssetOwner
    permissions: AssetPermission
    lineage: GoldenLineage
    quality_score: float = Field(ge=0, le=1)
    freshness_at: str
    data_as_of: str
    last_good: bool = True
    trace_id: str


class IngestLifecycleResult(ContractModel):
    status: Literal["succeeded"]
    source_revision: SourceRevisionRecord
    profile_run: ProfileRunRecord
    cleaning_recipe: CleaningRecipeRecord
    clean_run: CleanRunRecord
    golden_asset_revision: GoldenAssetRevisionRecord
    replayed: bool = False


class GoldenAssetSummary(ContractModel):
    asset_id: str
    golden_revision_id: str
    revision: int
    display_name: str
    asset_kind: Literal["dataset", "knowledge"]
    connector_key: str
    quality_score: float
    freshness_at: str
    owner: AssetOwner
    permissions: AssetPermission
    trace_id: str


class GoldenOverview(ContractModel):
    row_count: int = Field(ge=0)
    field_count: int = Field(ge=0)
    storage_bytes: int = Field(ge=0)
    quality_score: float = Field(ge=0, le=1)
    freshness_at: str


class GoldenAssetDetailView(ContractModel):
    view: Literal["golden_asset_detail"] = "golden_asset_detail"
    asset: GoldenAssetRevisionRecord
    overview: GoldenOverview
    preview: list[dict[str, object]]
    fields: list[ProfileField]
    profile: ProfileRunRecord
    lineage: GoldenLineage
    owner: AssetOwner
    permissions: AssetPermission
    tabs: list[Literal["overview", "preview", "fields", "lineage", "quality", "usage"]]
    usage: list[dict[str, object]] = Field(default_factory=list)


class GoldenResourceBinding(ContractModel):
    kind: Literal["golden_asset"] = "golden_asset"
    object_id: str
    revision: str
    provider_revision: str
    display_name: str
    scope: Literal["personal", "team"]
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_fields: list[str]
    capabilities: list[str]
    freshness_at: str
    data_as_of: str
    lineage: GoldenLineage
    permissions: AssetPermission
    authorized: bool = True


class GoldenContextReference(ContractModel):
    """Browser-safe immutable reference resolved again at execution time."""

    kind: Literal["golden_asset"] = "golden_asset"
    object_id: str = Field(min_length=1, max_length=160)
    revision: str = Field(min_length=1, max_length=160)
    provider_revision: str = Field(min_length=1, max_length=160)


class GoldenDataView(ContractModel):
    view: Literal["golden_data"] = "golden_data"
    binding: GoldenResourceBinding
    rows: list[dict[str, object]]


class AddDataView(ContractModel):
    view: Literal["add_data"] = "add_data"
    catalog: ConnectorCatalogView
    selected_connector: ConnectorDefinition | None = None
    steps: list[Literal["configure", "authorize", "discover", "save"]]
    can_create: bool
    blocked_reason: CapabilityReason | None = None


class RefreshRunRecord(ContractModel):
    id: str
    workspace_id: str
    asset_id: str
    status: Literal[
        "succeeded", "failed", "cancelled", "schema_drift", "permission_denied"
    ]
    previous_revision_id: str | None = None
    promoted_revision_id: str | None = None
    staging_ref: ArtifactRef | None = None
    reason: CapabilityReason
    retry_of: str | None = None
    trace_id: str
    started_at: str
    finished_at: str


class RefreshResult(ContractModel):
    run: RefreshRunRecord
    golden_asset_revision: GoldenAssetRevisionRecord | None = None
    last_good_revision: GoldenAssetRevisionRecord | None = None


class McpExchange(ContractModel):
    sequence: int = Field(ge=1)
    method: McpMethod
    request_id: int | None = None
    status: Literal["sent", "succeeded", "failed"]
    response_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = None


class McpProcessTrace(ContractModel):
    id: str
    workspace_id: str
    principal_id: str
    connection_id: str
    correlation_id: str
    pid: int = Field(gt=0)
    command: str
    args: list[str]
    cwd: str
    shell: Literal[False] = False
    environment_count: int = Field(ge=0)
    protocol_version: str | None = None
    server_name: str | None = None
    exit_code: int | None = None
    status: McpTraceStatus
    shutdown_mode: McpShutdownMode
    process_reaped: bool
    exchanges: list[McpExchange]
    started_at: str
    finished_at: str


class RemoteMcpExchange(ContractModel):
    sequence: int = Field(ge=1)
    method: RemoteMcpMethod
    status: Literal["succeeded", "failed"]
    response_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = None


class RemoteMcpTrace(ContractModel):
    id: str
    workspace_id: str
    principal_id: str
    connection_id: str
    correlation_id: str
    transport: Literal["streamable_http", "sse"]
    endpoint: str
    protocol_version: str | None = None
    server_name: str | None = None
    session_id_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: McpTraceStatus
    error_code: str | None = None
    exchanges: list[RemoteMcpExchange]
    started_at: str
    finished_at: str


class StdioMcpConfiguration(ContractModel):
    transport: Literal["stdio"]
    command: str = Field(min_length=1, max_length=2048)
    args: list[str] = Field(default_factory=list, max_length=128)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = Field(min_length=1, max_length=2048)
    startup_timeout_seconds: float = Field(default=10, gt=0, le=300)
    call_timeout_seconds: float = Field(default=30, gt=0, le=300)
    tool_allowlist: list[str] = Field(min_length=1, max_length=100)
    output_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)


class RemoteMcpConfiguration(ContractModel):
    transport: Literal["streamable_http", "sse"]
    endpoint: str = Field(min_length=1, max_length=2048)
    oauth_scope_ref: str | None = Field(default=None, max_length=2048)
    startup_timeout_seconds: float = Field(default=10, gt=0, le=300)
    call_timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_pages: int = Field(default=10, ge=1, le=100)
    tool_allowlist: list[str] = Field(min_length=1, max_length=100)
    output_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)


class McpToolDescriptor(ContractModel):
    name: str
    description: str = ""
    input_schema: dict[str, object]
    output_schema: dict[str, object] | None = None


class McpToolCallRequest(ContractModel):
    connection_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    workspace_id: str
    correlation_id: str


class McpStructuredResult(ContractModel):
    tool_name: str
    rows: list[dict[str, object]]
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_as_of: str
    correlation_id: str
    run_id: str
