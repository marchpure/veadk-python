"""The single server-owned catalog for the 37 frozen connector definitions."""

from __future__ import annotations

from collections import Counter

from .models import (
    CapabilityReason,
    CapabilityState,
    ConnectorCatalogView,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorPermission,
    FormField,
    FormSchema,
)


def _field(
    field_type: str,
    title: str,
    *,
    required: bool = False,
    description: str = "",
    default: str | int | bool | list[str] | None = None,
    options: list[str] | None = None,
    secret_reference: bool = False,
) -> FormField:
    return FormField(
        type=field_type,
        title=title,
        required=required,
        description=description,
        default=default,
        options=options or [],
        secret_reference=secret_reference,
    )


def _schema(**fields: FormField) -> FormSchema:
    return FormSchema(
        properties=fields,
        required=[key for key, value in fields.items() if value.required],
    )


EMPTY_SCHEMA = FormSchema(properties={})
SECRET_REF_SCHEMA = _schema(
    secretRef=_field(
        "string",
        "Secret reference",
        required=True,
        description="Reference in the server-side secret store (secret://…), never a value.",
        secret_reference=True,
    )
)


def _reason(state: CapabilityState, code: str | None = None) -> CapabilityReason:
    defaults = {
        "available": (
            "AVAILABLE",
            "This connector has a real local adapter and durable lifecycle.",
        ),
        "configurable": (
            "CONFIG_REQUIRED",
            "A definition can be configured, but no provider result is claimed.",
        ),
        "credential_blocked": (
            "CREDENTIAL_REQUIRED",
            "A real provider adapter contract exists; usable secretRef/configuration is required.",
        ),
        "unsupported": (
            "ADAPTER_NOT_IMPLEMENTED",
            "The catalog entry is visible, but no production adapter is implemented.",
        ),
    }
    default_code, message = defaults[state]
    return CapabilityReason(code=code or default_code, message=message)


def _permissions(
    *,
    provider_scopes: list[str] | None = None,
    inherits_source_acl: bool = False,
) -> ConnectorPermission:
    return ConnectorPermission(
        read_scopes=["workspace.member", "source.read"],
        manage_scopes=["workspace.member", "source.write"],
        provider_scopes=provider_scopes or [],
        inherits_source_acl=inherits_source_acl,
    )


def _definition(
    key: str,
    category: ConnectorCategory,
    name: str,
    description: str,
    capabilities: list[str],
    state: CapabilityState,
    input_schema: FormSchema,
    credential_schema: FormSchema = EMPTY_SCHEMA,
    discovery_modes: list[str] | None = None,
    sync_modes: list[str] | None = None,
    permissions: ConnectorPermission | None = None,
    reason_code: str | None = None,
) -> ConnectorDefinition:
    return ConnectorDefinition(
        connector_key=key,
        category=category,
        name=name,
        description=description,
        capabilities=capabilities,
        capability_state=state,
        input_schema=input_schema,
        credential_schema=credential_schema,
        discovery_modes=discovery_modes or ["validate", "discover", "introspect"],
        sync_modes=sync_modes or ["incremental"],
        permissions=permissions or _permissions(),
        reason=_reason(state, reason_code),
    )


def _office_definitions() -> list[ConnectorDefinition]:
    oauth = SECRET_REF_SCHEMA
    inherited = _permissions(
        provider_scopes=["offline_access", "resource.read"],
        inherits_source_acl=True,
    )
    return [
        _definition(
            "lark_doc",
            "office",
            "飞书文档",
            "同步飞书文档内容",
            ["unstructured", "permission_inheritance"],
            "credential_blocked",
            _schema(
                documentRef=_field("string", "Document URL or token", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_wiki",
            "office",
            "飞书知识库 Wiki",
            "整库同步与结构解析",
            ["unstructured", "hierarchy"],
            "credential_blocked",
            _schema(
                wikiRef=_field("string", "Wiki space or node", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_drive",
            "office",
            "飞书云盘",
            "读取云盘文件资源",
            ["file", "multi_format"],
            "credential_blocked",
            _schema(
                folderRef=_field("string", "Drive folder", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_meeting",
            "office",
            "飞书会议",
            "按条件选取并导入会议纪要",
            ["meeting_notes", "date_range"],
            "credential_blocked",
            _schema(
                calendarRef=_field("string", "Calendar", required=True),
                dateFrom=_field("string", "Start date", required=True),
                dateTo=_field("string", "End date", required=True),
                attendees=_field("string_array", "Attendees"),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_minutes",
            "office",
            "飞书妙记",
            "单篇或批量会议纪要",
            ["transcript"],
            "credential_blocked",
            _schema(
                minutesRef=_field("string", "Minutes URL or token", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_group",
            "office",
            "飞书群聊/话题消息",
            "读取有权限的群聊与话题",
            ["conversation", "attachments"],
            "credential_blocked",
            _schema(
                chatRef=_field("string", "Group chat", required=True),
                timeRange=_field("string", "Time range", required=True),
                includeAttachments=_field(
                    "boolean", "Include attachment metadata", default=False
                ),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_chat",
            "office",
            "单聊记录",
            "读取有权限的单聊对话",
            ["conversation"],
            "credential_blocked",
            _schema(
                userRef=_field("string", "Conversation participant", required=True),
                timeRange=_field("string", "Time range", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_sheet",
            "office",
            "飞书电子表格",
            "读取表格数据为结构化表",
            ["structured"],
            "credential_blocked",
            _schema(
                sheetRef=_field("string", "Spreadsheet URL or token", required=True),
                sheetName=_field("string", "Sheet name"),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_base",
            "office",
            "飞书多维表格 Base",
            "读取 Base 数据表与视图",
            ["relational"],
            "credential_blocked",
            _schema(
                appRef=_field("string", "Base app token", required=True),
                tableRef=_field("string", "Table ID", required=True),
                viewRef=_field("string", "View ID"),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
        _definition(
            "lark_mail",
            "office",
            "飞书邮件",
            "提取指定条件的邮件内容",
            ["mail_search"],
            "credential_blocked",
            _schema(
                folder=_field("string", "Mail folder", required=True),
                query=_field("string", "Search query"),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited,
        ),
    ]


def _file_definitions() -> list[ConnectorDefinition]:
    def file_ref(title: str) -> FormSchema:
        return _schema(sourceRef=_field("file", title, required=True))

    return [
        _definition(
            "csv",
            "file",
            "CSV",
            "UTF-8 comma-separated tabular data",
            ["structured", "profile", "clean"],
            "available",
            file_ref("CSV file"),
            discovery_modes=["validate", "introspect", "sample"],
            sync_modes=["full"],
        ),
        _definition(
            "excel",
            "file",
            "Excel",
            "Excel workbook (.xlsx/.xls)",
            ["structured", "multi_sheet", "profile", "clean"],
            "available",
            _schema(
                sourceRef=_field("file", "Excel file", required=True),
                sheetAllowlist=_field("string_array", "Sheets"),
            ),
            discovery_modes=["validate", "discover", "introspect", "sample"],
            sync_modes=["full"],
        ),
        _definition(
            "json",
            "file",
            "JSON",
            "Nested or line-delimited JSON",
            ["semi_structured"],
            "unsupported",
            file_ref("JSON file"),
            sync_modes=["full"],
        ),
        _definition(
            "parquet",
            "file",
            "Parquet",
            "Columnar Parquet object",
            ["structured", "columnar"],
            "unsupported",
            file_ref("Parquet file"),
            sync_modes=["full"],
        ),
        _definition(
            "doc_txt",
            "file",
            "PDF/Markdown/TXT/HTML",
            "PDF import is available; Markdown uses local_file; TXT/HTML remain unsupported.",
            ["document", "pdf", "profile", "clean"],
            "available",
            file_ref("PDF document"),
            discovery_modes=["validate", "introspect", "sample"],
            sync_modes=["full"],
            reason_code="PDF_ADAPTER_AVAILABLE",
        ),
        _definition(
            "local_file",
            "file",
            "本地 Markdown",
            "Bounded local Markdown selection",
            ["document", "profile", "clean"],
            "available",
            file_ref("Markdown file"),
            discovery_modes=["validate", "introspect", "sample"],
            sync_modes=["full"],
        ),
        _definition(
            "s3",
            "file",
            "AWS S3",
            "Amazon object storage",
            ["object_storage"],
            "credential_blocked",
            _schema(
                bucket=_field("string", "Bucket", required=True),
                objectPrefix=_field("string", "Object prefix"),
            ),
            SECRET_REF_SCHEMA,
        ),
        _definition(
            "oss",
            "file",
            "Aliyun OSS",
            "Aliyun object storage",
            ["object_storage"],
            "credential_blocked",
            _schema(
                bucket=_field("string", "Bucket", required=True),
                objectPrefix=_field("string", "Object prefix"),
            ),
            SECRET_REF_SCHEMA,
        ),
    ]


def _db_form(*, oracle: bool = False) -> FormSchema:
    fields = {
        "host": _field("string", "Host", required=True),
        "port": _field("integer", "Port", required=True),
        ("serviceName" if oracle else "database"): _field(
            "string", "Service name" if oracle else "Database", required=True
        ),
        "schemaAllowlist": _field("string_array", "Allowed schemas"),
        "query": _field("string", "Read-only parameterized query"),
        "rowLimit": _field("integer", "Maximum rows", default=10_000),
        "byteLimit": _field("integer", "Maximum bytes", default=52_428_800),
        "timeoutSeconds": _field("integer", "Timeout in seconds", default=30),
    }
    return _schema(**fields)


def _database_definitions() -> list[ConnectorDefinition]:
    definitions = [
        _definition(
            "postgresql",
            "db",
            "PostgreSQL",
            "Open-source relational database",
            ["relational", "read_only"],
            "credential_blocked",
            _db_form(),
            SECRET_REF_SCHEMA,
            sync_modes=["full", "incremental"],
        ),
        _definition(
            "mysql",
            "db",
            "MySQL",
            "Relational database",
            ["relational", "read_only"],
            "credential_blocked",
            _db_form(),
            SECRET_REF_SCHEMA,
            sync_modes=["full", "incremental"],
        ),
        _definition(
            "oracle",
            "db",
            "Oracle",
            "Enterprise relational database",
            ["relational", "read_only"],
            "credential_blocked",
            _db_form(oracle=True),
            SECRET_REF_SCHEMA,
            sync_modes=["full", "incremental"],
        ),
        _definition(
            "sqlserver",
            "db",
            "SQL Server",
            "Microsoft relational database",
            ["relational", "read_only"],
            "credential_blocked",
            _db_form(),
            SECRET_REF_SCHEMA,
            sync_modes=["full", "incremental"],
        ),
        _definition(
            "sqlite",
            "db",
            "SQLite",
            "Read-only local SQLite database",
            ["relational", "local", "profile", "clean"],
            "available",
            _schema(
                sourceRef=_field("file", "SQLite database", required=True),
                tableAllowlist=_field("string_array", "Allowed tables"),
                query=_field("string", "Read-only parameterized query"),
                rowLimit=_field("integer", "Maximum rows", default=10_000),
            ),
            discovery_modes=["validate", "discover", "introspect", "sample"],
            sync_modes=["full"],
        ),
    ]
    for key, name, capabilities in [
        ("clickhouse", "ClickHouse", ["olap", "columnar"]),
        ("doris", "Doris", ["olap", "realtime"]),
        ("starrocks", "StarRocks", ["olap"]),
        ("snowflake", "Snowflake", ["cloud_warehouse"]),
        ("bigquery", "BigQuery", ["cloud_warehouse"]),
        ("hive", "Hive", ["warehouse"]),
    ]:
        if key == "snowflake":
            form = _schema(
                account=_field("string", "Account", required=True),
                warehouse=_field("string", "Warehouse", required=True),
                database=_field("string", "Database", required=True),
            )
        elif key == "bigquery":
            form = _schema(
                projectId=_field("string", "Project ID", required=True),
                datasetId=_field("string", "Dataset ID", required=True),
            )
        else:
            form = _db_form()
        definitions.append(
            _definition(
                key,
                "db",
                name,
                f"{name} data source",
                capabilities,
                "credential_blocked",
                form,
                SECRET_REF_SCHEMA,
            )
        )
    return definitions


def _web_form(label: str = "Endpoint") -> FormSchema:
    return _schema(
        endpoint=_field("url", label, required=True),
        operationAllowlist=_field("string_array", "Allowed operations"),
        paginationMode=_field(
            "select",
            "Pagination",
            default="none",
            options=["none", "cursor", "offset", "link_header"],
        ),
        refreshSeconds=_field("integer", "Refresh interval", default=3600),
        termsRef=_field("url", "Terms reference"),
    )


def _api_definitions() -> list[ConnectorDefinition]:
    return [
        _definition(
            "rest_api",
            "api",
            "REST / OpenAPI",
            "HTTP API endpoint",
            ["http", "pagination", "read_only"],
            "credential_blocked",
            _web_form(),
            SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
        ),
        _definition(
            "graphql",
            "api",
            "GraphQL",
            "GraphQL query endpoint",
            ["graphql", "read_only"],
            "credential_blocked",
            _schema(
                endpoint=_field("url", "Endpoint", required=True),
                query=_field("string", "Query", required=True),
                operationAllowlist=_field("string_array", "Allowed operations"),
                paginationMode=_field(
                    "select", "Pagination", options=["none", "cursor"]
                ),
                refreshSeconds=_field("integer", "Refresh interval", default=3600),
            ),
            SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
        ),
        _definition(
            "web_discovery",
            "api",
            "Web API Discovery",
            "Discover a public site's API surface without fabricating operations",
            ["web", "discovery"],
            "credential_blocked",
            _web_form("Target URL"),
            SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
        ),
        _definition(
            "webhook",
            "api",
            "Webhook",
            "Inbound event receiver",
            ["event_driven"],
            "configurable",
            _schema(
                listenPath=_field("string", "Listener path", required=True),
                schemaRef=_field("string", "Payload schema reference", required=True),
            ),
            SECRET_REF_SCHEMA,
            discovery_modes=["validate"],
            sync_modes=["realtime"],
        ),
        _definition(
            "kafka",
            "api",
            "Kafka",
            "Kafka topic stream",
            ["stream"],
            "credential_blocked",
            _schema(
                bootstrapServers=_field(
                    "string_array", "Bootstrap servers", required=True
                ),
                topics=_field("string_array", "Topic allowlist", required=True),
                consumerGroup=_field("string", "Consumer group", required=True),
            ),
            SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
        ),
    ]


def _custom_definitions() -> list[ConnectorDefinition]:
    return [
        _definition(
            "mcp_custom",
            "custom",
            "MCP Server",
            "Model Context Protocol server",
            ["tools", "untrusted_output"],
            "configurable",
            _schema(
                transport=_field(
                    "select",
                    "Transport",
                    required=True,
                    options=["stdio", "streamable_http", "sse"],
                ),
                command=_field("string", "Executable (stdio)"),
                args=_field("string_array", "Arguments"),
                env=_field("object", "Environment variable references"),
                cwd=_field("string", "Working directory"),
                startupTimeoutSeconds=_field("integer", "Startup timeout", default=10),
                callTimeoutSeconds=_field("integer", "Call timeout", default=30),
                endpoint=_field("url", "Remote endpoint"),
                oauthScopeRef=_field("string", "OAuth scope reference"),
                toolAllowlist=_field("string_array", "Allowed tools", required=True),
                outputBytes=_field(
                    "integer", "Maximum output bytes", default=1_000_000
                ),
            ),
            EMPTY_SCHEMA,
            discovery_modes=["validate", "discover_tools"],
            sync_modes=["realtime"],
        ),
        _definition(
            "custom_http",
            "custom",
            "自定义 HTTP Connector",
            "User-authored bounded HTTP definition",
            ["http", "custom_definition"],
            "configurable",
            _schema(
                name=_field("string", "Definition name", required=True),
                endpoint=_field("url", "Base URL", required=True),
                method=_field(
                    "select", "Method", options=["GET", "HEAD"], default="GET"
                ),
                paginationMode=_field(
                    "select", "Pagination", options=["none", "cursor", "offset"]
                ),
                refreshSeconds=_field("integer", "Refresh interval", default=3600),
            ),
            SECRET_REF_SCHEMA,
            discovery_modes=["validate"],
            sync_modes=["realtime"],
        ),
        _definition(
            "openapi_spec",
            "custom",
            "上传 OpenAPI Spec",
            "Static OpenAPI definition upload",
            ["openapi", "static_definition"],
            "unsupported",
            _schema(
                specRef=_field("file", "OpenAPI YAML or JSON", required=True),
                operationAllowlist=_field("string_array", "Allowed operations"),
            ),
            SECRET_REF_SCHEMA,
            discovery_modes=["parse", "list_operations"],
            sync_modes=["realtime"],
        ),
    ]


BUILTIN_CONNECTORS: tuple[ConnectorDefinition, ...] = tuple(
    _office_definitions()
    + _file_definitions()
    + _database_definitions()
    + _api_definitions()
    + _custom_definitions()
)

assert len(BUILTIN_CONNECTORS) == 37
assert len({item.connector_key for item in BUILTIN_CONNECTORS}) == 37


def connector_catalog(
    *, category: ConnectorCategory | None = None, query: str | None = None
) -> ConnectorCatalogView:
    normalized = (query or "").strip().casefold()
    rows = [
        item
        for item in BUILTIN_CONNECTORS
        if (category is None or item.category == category)
        and (
            not normalized
            or normalized in item.connector_key.casefold()
            or normalized in item.name.casefold()
            or normalized in item.description.casefold()
        )
    ]
    counts = Counter(item.category for item in BUILTIN_CONNECTORS)
    category_names: tuple[ConnectorCategory, ...] = (
        "office",
        "file",
        "db",
        "api",
        "custom",
    )
    return ConnectorCatalogView(
        connectors=rows,
        categories={
            category_name: counts[category_name] for category_name in category_names
        },
        total=len(rows),
    )


def bootstrap_connector_catalog() -> list[dict[str, object]]:
    """Project the typed catalog into the frozen Workspace bootstrap shape."""
    field_types = {
        "integer": "number",
        "url": "string",
        "string_array": "string",
    }
    return [
        {
            "connectorKey": definition.connector_key,
            "category": definition.category,
            "name": definition.name,
            "desc": definition.description,
            "capabilities": definition.capabilities,
            "inputSchema": {
                key: field_types.get(field.type, field.type)
                for key, field in definition.input_schema.properties.items()
            },
            "credentialSchema": (
                {
                    key: ("secret_ref" if field.secret_reference else field.type)
                    for key, field in definition.credential_schema.properties.items()
                }
                or None
            ),
            "discoveryPipeline": definition.discovery_modes,
            "syncModes": definition.sync_modes,
            "capabilityState": definition.capability_state,
            "reason": definition.reason.model_dump(mode="json", by_alias=True),
            "permissions": definition.permissions.model_dump(
                mode="json", by_alias=True
            ),
        }
        for definition in BUILTIN_CONNECTORS
    ]
