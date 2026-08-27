"""The single server-owned catalog for the 37 frozen connector definitions."""

from __future__ import annotations

from .catalog_projection import bootstrap_catalog, connector_catalog_view
from .catalog_schema import (
    EMPTY_SCHEMA,
    OPTIONAL_SECRET_REF_SCHEMA,
    SECRET_REF_SCHEMA,
)
from .catalog_schema import (
    definition as _definition,
)
from .catalog_schema import (
    field as _field,
)
from .catalog_schema import (
    permission_policy as _permissions,
)
from .catalog_schema import (
    schema as _schema,
)
from .models import (
    ConnectorCatalogView,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorPermission,
    FormField,
    FormSchema,
)


def _office_definitions() -> list[ConnectorDefinition]:
    oauth = SECRET_REF_SCHEMA

    def office_schema(**fields: FormField) -> FormSchema:
        return _schema(
            **fields,
            apiBaseUrl=_field(
                "url",
                "Lark OpenAPI base URL",
                default="https://open.feishu.cn/open-apis",
            ),
            pageSize=_field("integer", "Page size", default=100),
            maxPages=_field("integer", "Maximum pages", default=10),
            maxResponseBytes=_field(
                "integer", "Maximum response bytes", default=5 * 1024 * 1024
            ),
            rateLimitPerMinute=_field(
                "integer", "Maximum requests per minute", default=60
            ),
            timeoutSeconds=_field("integer", "Request timeout", default=30),
            refreshSeconds=_field("integer", "Refresh interval", default=3600),
        )

    def inherited(*provider_scopes: str) -> ConnectorPermission:
        return _permissions(
            provider_scopes=["offline_access", *provider_scopes],
            inherits_source_acl=True,
        )

    return [
        _definition(
            "lark_doc",
            "office",
            "飞书文档",
            "同步飞书文档内容",
            ["unstructured", "permission_inheritance"],
            "available",
            office_schema(
                documentRef=_field("string", "Document URL or token", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("docx:document:readonly"),
        ),
        _definition(
            "lark_wiki",
            "office",
            "飞书知识库 Wiki",
            "整库同步与结构解析",
            ["unstructured", "hierarchy"],
            "available",
            office_schema(
                wikiRef=_field("string", "Wiki space or node", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("wiki:wiki:readonly"),
        ),
        _definition(
            "lark_drive",
            "office",
            "飞书云盘",
            "读取云盘文件资源",
            ["file", "multi_format"],
            "available",
            office_schema(
                folderRef=_field("string", "Drive folder", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("drive:drive:readonly"),
        ),
        _definition(
            "lark_meeting",
            "office",
            "飞书会议",
            "按条件选取并导入会议纪要",
            ["meeting_notes", "date_range"],
            "available",
            office_schema(
                calendarRef=_field("string", "Calendar", required=True),
                dateFrom=_field("string", "Start date", required=True),
                dateTo=_field("string", "End date", required=True),
                attendees=_field("string_array", "Attendees"),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited(
                "calendar:calendar:readonly",
                "calendar:calendar.event:read",
                "vc:meeting:readonly",
            ),
        ),
        _definition(
            "lark_minutes",
            "office",
            "飞书妙记",
            "单篇或批量会议纪要",
            ["transcript"],
            "available",
            office_schema(
                minutesRef=_field("string", "Minutes URL or token", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("minutes:minutes:readonly"),
        ),
        _definition(
            "lark_group",
            "office",
            "飞书群聊/话题消息",
            "读取有权限的群聊与话题",
            ["conversation", "attachments"],
            "available",
            office_schema(
                chatRef=_field("string", "Group chat", required=True),
                timeRange=_field("string", "Time range", required=True),
                includeAttachments=_field(
                    "boolean", "Include attachment metadata", default=False
                ),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("im:chat:readonly", "im:message:readonly"),
        ),
        _definition(
            "lark_chat",
            "office",
            "单聊记录",
            "读取有权限的单聊对话",
            ["conversation"],
            "available",
            office_schema(
                chatRef=_field("string", "Direct-message chat ID", required=True),
                timeRange=_field("string", "Time range", required=True),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("im:chat:readonly", "im:message:readonly"),
        ),
        _definition(
            "lark_sheet",
            "office",
            "飞书电子表格",
            "读取表格数据为结构化表",
            ["structured"],
            "available",
            office_schema(
                sheetRef=_field("string", "Spreadsheet URL or token", required=True),
                sheetName=_field("string", "Sheet name"),
                cellRange=_field(
                    "string",
                    "Bounded A1 cell range",
                    default="A1:Z1000",
                ),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("sheets:spreadsheet:readonly"),
        ),
        _definition(
            "lark_base",
            "office",
            "飞书多维表格 Base",
            "读取 Base 数据表与视图",
            ["relational"],
            "available",
            office_schema(
                appRef=_field("string", "Base app token", required=True),
                tableRef=_field("string", "Table ID", required=True),
                viewRef=_field("string", "View ID"),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("bitable:app:readonly"),
        ),
        _definition(
            "lark_mail",
            "office",
            "飞书邮件",
            "提取指定条件的邮件内容",
            ["mail_search"],
            "available",
            office_schema(
                folder=_field("string", "Mail folder", required=True),
                query=_field("string", "Search query"),
                scopeRef=_field("string", "Authorized scope", required=True),
            ),
            oauth,
            permissions=inherited("mail:user_mailbox.message:readonly"),
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
            "Excel workbook (.xlsx)",
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
            ["semi_structured", "profile", "clean"],
            "available",
            _schema(
                sourceRef=_field("file", "JSON file", required=True),
                maxDepth=_field("integer", "Maximum nesting depth", default=32),
                maxRows=_field("integer", "Maximum records", default=10_000),
            ),
            discovery_modes=["validate", "introspect", "sample"],
            sync_modes=["full"],
        ),
        _definition(
            "parquet",
            "file",
            "Parquet",
            "Columnar Parquet object",
            ["structured", "columnar", "profile", "clean"],
            "available",
            _schema(
                sourceRef=_field("file", "Parquet file", required=True),
                maxRows=_field("integer", "Maximum records", default=10_000),
                maxColumns=_field("integer", "Maximum columns", default=1_000),
                maxUncompressedBytes=_field(
                    "integer",
                    "Maximum uncompressed bytes",
                    default=100 * 1024 * 1024,
                ),
                maxNestingDepth=_field(
                    "integer", "Maximum schema nesting depth", default=16
                ),
            ),
            discovery_modes=["validate", "introspect", "sample"],
            sync_modes=["full"],
        ),
        _definition(
            "doc_txt",
            "file",
            "PDF/Markdown/TXT/HTML",
            "Bounded text extraction for PDF, Markdown, plain text, and HTML.",
            ["document", "pdf", "markdown", "text", "html", "profile", "clean"],
            "available",
            _schema(
                sourceRef=_field(
                    "file", "PDF, Markdown, TXT, or HTML file", required=True
                ),
                maxTextChars=_field(
                    "integer", "Maximum extracted characters", default=2_000_000
                ),
            ),
            discovery_modes=["validate", "introspect", "sample"],
            sync_modes=["full"],
            reason_code="DOCUMENT_ADAPTER_AVAILABLE",
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
            "available",
            _schema(
                bucket=_field("string", "Bucket", required=True),
                objectPrefix=_field("string", "Object prefix"),
                region=_field("string", "Region"),
                endpoint=_field("url", "S3-compatible endpoint"),
                maxObjects=_field("integer", "Maximum objects", default=1_000),
                maxObjectBytes=_field(
                    "integer", "Maximum object bytes", default=10 * 1024 * 1024
                ),
                timeoutSeconds=_field("integer", "Request timeout", default=30),
            ),
            SECRET_REF_SCHEMA,
            permissions=_permissions(provider_scopes=["s3:ListBucket", "s3:GetObject"]),
        ),
        _definition(
            "oss",
            "file",
            "Aliyun OSS",
            "Aliyun object storage",
            ["object_storage"],
            "available",
            _schema(
                bucket=_field("string", "Bucket", required=True),
                objectPrefix=_field("string", "Object prefix"),
                endpoint=_field("url", "OSS endpoint", required=True),
                region=_field("string", "Region"),
                maxObjects=_field("integer", "Maximum objects", default=1_000),
                maxObjectBytes=_field(
                    "integer", "Maximum object bytes", default=10 * 1024 * 1024
                ),
                timeoutSeconds=_field("integer", "Request timeout", default=30),
            ),
            SECRET_REF_SCHEMA,
            permissions=_permissions(
                provider_scopes=["oss:ListObjects", "oss:GetObject"]
            ),
        ),
    ]


def _db_form(*, oracle: bool = False) -> FormSchema:
    fields = {
        "host": _field("string", "Host", required=True),
        "port": _field("integer", "Port", required=True),
        ("serviceName" if oracle else "database"): _field(
            "string", "Service name" if oracle else "Database", required=True
        ),
        "schemaAllowlist": _field("string_array", "Allowed schemas", required=True),
        "tableAllowlist": _field("string_array", "Allowed tables", required=True),
        "query": _field("string", "Read-only parameterized query"),
        "queryParameters": _field("object", "Bound query parameters"),
        "pageSize": _field("integer", "Fetch page size", default=1_000),
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
            "available",
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
            "available",
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
            "available",
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
            "available",
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
                schemaAllowlist=_field(
                    "string_array", "Allowed schemas", required=True
                ),
                tableAllowlist=_field("string_array", "Allowed tables", required=True),
                query=_field("string", "Read-only parameterized query"),
                queryParameters=_field("object", "Bound query parameters"),
                pageSize=_field("integer", "Fetch page size", default=1_000),
                rowLimit=_field("integer", "Maximum rows", default=10_000),
                byteLimit=_field(
                    "integer", "Maximum bytes billed/result bytes", default=52_428_800
                ),
                timeoutSeconds=_field("integer", "Timeout in seconds", default=30),
            )
        elif key == "bigquery":
            form = _schema(
                projectId=_field("string", "Project ID", required=True),
                datasetId=_field("string", "Dataset ID", required=True),
                schemaAllowlist=_field(
                    "string_array", "Allowed datasets", required=True
                ),
                tableAllowlist=_field("string_array", "Allowed tables", required=True),
                query=_field("string", "Read-only parameterized query"),
                queryParameters=_field("object", "Bound query parameters"),
                pageSize=_field("integer", "Fetch page size", default=1_000),
                rowLimit=_field("integer", "Maximum rows", default=10_000),
                byteLimit=_field(
                    "integer", "Maximum bytes billed/result bytes", default=52_428_800
                ),
                timeoutSeconds=_field("integer", "Timeout in seconds", default=30),
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
                "available",
                form,
                SECRET_REF_SCHEMA,
                permissions=_permissions(
                    provider_scopes=["schema.metadata.read", "table.data.read"]
                ),
            )
        )
    return definitions


def _web_form(label: str = "Endpoint") -> FormSchema:
    return _schema(
        endpoint=_field("url", label, required=True),
        operationAllowlist=_field("string_array", "Allowed operations", required=True),
        paginationMode=_field(
            "select",
            "Pagination",
            default="none",
            options=["none", "cursor", "offset", "link_header"],
        ),
        pageSize=_field("integer", "Page size", default=100),
        maxPages=_field("integer", "Maximum pages", default=10),
        maxRows=_field("integer", "Maximum records", default=10_000),
        maxResponseBytes=_field(
            "integer", "Maximum response bytes", default=5 * 1024 * 1024
        ),
        rateLimitPerMinute=_field("integer", "Maximum requests per minute", default=60),
        timeoutSeconds=_field("integer", "Request timeout in seconds", default=30),
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
            "available",
            _web_form(),
            OPTIONAL_SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
        ),
        _definition(
            "graphql",
            "api",
            "GraphQL",
            "GraphQL query endpoint",
            ["graphql", "read_only"],
            "available",
            _schema(
                endpoint=_field("url", "Endpoint", required=True),
                query=_field("string", "Query", required=True),
                operationAllowlist=_field(
                    "string_array", "Allowed operations", required=True
                ),
                maxRows=_field("integer", "Maximum records", default=10_000),
                maxResponseBytes=_field(
                    "integer",
                    "Maximum response bytes",
                    default=5 * 1024 * 1024,
                ),
                rateLimitPerMinute=_field(
                    "integer", "Maximum requests per minute", default=60
                ),
                timeoutSeconds=_field(
                    "integer", "Request timeout in seconds", default=30
                ),
                refreshSeconds=_field("integer", "Refresh interval", default=3600),
            ),
            OPTIONAL_SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
        ),
        _definition(
            "web_discovery",
            "api",
            "Web API Discovery",
            "Discover a public site's API surface without fabricating operations",
            ["web", "discovery"],
            "available",
            _web_form("Target URL"),
            OPTIONAL_SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
        ),
        _definition(
            "webhook",
            "api",
            "Webhook",
            "Inbound event receiver",
            ["event_driven"],
            "available",
            _schema(
                listenPath=_field("string", "Listener path", required=True),
                schemaRef=_field("string", "Payload schema reference", required=True),
                maxEventBytes=_field(
                    "integer", "Maximum event bytes", default=1_000_000
                ),
                maxEvents=_field("integer", "Maximum retained events", default=10_000),
                rateLimitPerMinute=_field(
                    "integer", "Maximum deliveries per minute", default=60
                ),
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
            "available",
            _schema(
                bootstrapServers=_field(
                    "string_array", "Bootstrap servers", required=True
                ),
                topics=_field("string_array", "Topic allowlist", required=True),
                consumerGroup=_field("string", "Consumer group", required=True),
                maxMessages=_field("integer", "Maximum messages", default=1_000),
                maxMessageBytes=_field(
                    "integer", "Maximum message bytes", default=1_000_000
                ),
                timeoutSeconds=_field("integer", "Poll timeout", default=30),
            ),
            SECRET_REF_SCHEMA,
            sync_modes=["realtime"],
            permissions=_permissions(
                provider_scopes=["topic.describe", "topic.read", "group.read"]
            ),
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
            "available",
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
                startupTimeoutSeconds=_field("number", "Startup timeout", default=10),
                callTimeoutSeconds=_field("number", "Call timeout", default=30),
                maxPages=_field("integer", "Maximum discovery pages", default=10),
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
            "available",
            _schema(
                name=_field("string", "Definition name", required=True),
                endpoint=_field("url", "Base URL", required=True),
                operationAllowlist=_field(
                    "string_array", "Allowed operations", required=True
                ),
                method=_field(
                    "select", "Method", options=["GET", "HEAD"], default="GET"
                ),
                paginationMode=_field(
                    "select", "Pagination", options=["none", "cursor", "offset"]
                ),
                pageSize=_field("integer", "Page size", default=100),
                maxPages=_field("integer", "Maximum pages", default=10),
                maxRows=_field("integer", "Maximum records", default=10_000),
                maxResponseBytes=_field(
                    "integer",
                    "Maximum response bytes",
                    default=5 * 1024 * 1024,
                ),
                rateLimitPerMinute=_field(
                    "integer", "Maximum requests per minute", default=60
                ),
                timeoutSeconds=_field(
                    "integer", "Request timeout in seconds", default=30
                ),
                refreshSeconds=_field("integer", "Refresh interval", default=3600),
            ),
            OPTIONAL_SECRET_REF_SCHEMA,
            discovery_modes=["validate"],
            sync_modes=["realtime"],
        ),
        _definition(
            "openapi_spec",
            "custom",
            "上传 OpenAPI Spec",
            "Static OpenAPI definition upload",
            ["openapi", "static_definition", "read_only", "profile", "clean"],
            "available",
            _schema(
                specRef=_field("file", "OpenAPI YAML or JSON", required=True),
                operationAllowlist=_field(
                    "string_array", "Allowed operations", required=True
                ),
                serverUrl=_field("url", "Server URL override"),
                maxRows=_field("integer", "Maximum records", default=10_000),
                maxResponseBytes=_field(
                    "integer", "Maximum response bytes", default=5 * 1024 * 1024
                ),
                rateLimitPerMinute=_field(
                    "integer", "Maximum requests per minute", default=60
                ),
                timeoutSeconds=_field(
                    "integer", "Request timeout in seconds", default=30
                ),
            ),
            OPTIONAL_SECRET_REF_SCHEMA,
            discovery_modes=["validate", "parse", "list_operations", "sample"],
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
    *,
    category: ConnectorCategory | None = None,
    query: str | None = None,
    enabled_provider_connectors: frozenset[str] = frozenset(),
) -> ConnectorCatalogView:
    return connector_catalog_view(
        BUILTIN_CONNECTORS,
        category=category,
        query=query,
        enabled_provider_connectors=enabled_provider_connectors,
    )


def bootstrap_connector_catalog(
    *,
    enabled_provider_connectors: frozenset[str] = frozenset(),
) -> list[dict[str, object]]:
    """Project the typed catalog into the frozen Workspace bootstrap shape."""
    return bootstrap_catalog(
        BUILTIN_CONNECTORS,
        enabled_provider_connectors=enabled_provider_connectors,
    )
