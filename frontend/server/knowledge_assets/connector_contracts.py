"""Independent, secret-reference-only contracts for all 37 connectors."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter

from .contract_base import ContractModel, SecretRef


class _LocalSourceConfig(ContractModel):
    source_ref: str = Field(min_length=1, max_length=2048)


class CsvConnectorConfig(_LocalSourceConfig):
    kind: Literal["csv"]


class ExcelConnectorConfig(_LocalSourceConfig):
    kind: Literal["excel"]
    sheet_allowlist: list[str] = Field(default_factory=list, max_length=100)


class JsonConnectorConfig(_LocalSourceConfig):
    kind: Literal["json"]
    max_depth: int = Field(default=32, ge=1, le=128)
    max_rows: int = Field(default=10_000, ge=1, le=1_000_000)


class ParquetConnectorConfig(_LocalSourceConfig):
    kind: Literal["parquet"]
    max_rows: int = Field(default=10_000, ge=1, le=1_000_000)
    max_columns: int = Field(default=1_000, ge=1, le=10_000)
    max_uncompressed_bytes: int = Field(
        default=100 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024
    )
    max_nesting_depth: int = Field(default=16, ge=1, le=128)


class DocumentConnectorConfig(_LocalSourceConfig):
    kind: Literal["doc_txt"]
    max_text_chars: int = Field(default=2_000_000, ge=1, le=20_000_000)


class LocalFileConnectorConfig(_LocalSourceConfig):
    kind: Literal["local_file"]


class SqliteConnectorConfig(_LocalSourceConfig):
    kind: Literal["sqlite"]
    table_allowlist: list[str] = Field(default_factory=list, max_length=1_000)
    query: str | None = Field(default=None, max_length=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=1_000_000)


class _OfficeConfig(ContractModel):
    secret_ref: SecretRef
    scope_ref: str = Field(min_length=1, max_length=2048)
    api_base_url: str = Field(
        default="https://open.feishu.cn/open-apis", min_length=1, max_length=2048
    )
    page_size: int = Field(default=100, ge=1, le=1_000)
    max_pages: int = Field(default=10, ge=1, le=1_000)
    max_response_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    timeout_seconds: int = Field(default=30, ge=1, le=900)
    refresh_seconds: int = Field(default=3_600, ge=1, le=31_536_000)


class LarkDocConnectorConfig(_OfficeConfig):
    kind: Literal["lark_doc"]
    document_ref: str = Field(min_length=1, max_length=2048)


class LarkWikiConnectorConfig(_OfficeConfig):
    kind: Literal["lark_wiki"]
    wiki_ref: str = Field(min_length=1, max_length=2048)


class LarkDriveConnectorConfig(_OfficeConfig):
    kind: Literal["lark_drive"]
    folder_ref: str = Field(min_length=1, max_length=2048)


class LarkMeetingConnectorConfig(_OfficeConfig):
    kind: Literal["lark_meeting"]
    calendar_ref: str = Field(min_length=1, max_length=2048)
    date_from: str = Field(min_length=1, max_length=64)
    date_to: str = Field(min_length=1, max_length=64)
    attendees: list[str] = Field(default_factory=list, max_length=1_000)


class LarkMinutesConnectorConfig(_OfficeConfig):
    kind: Literal["lark_minutes"]
    minutes_ref: str = Field(min_length=1, max_length=2048)


class LarkGroupConnectorConfig(_OfficeConfig):
    kind: Literal["lark_group"]
    chat_ref: str = Field(min_length=1, max_length=2048)
    time_range: str = Field(min_length=1, max_length=128)
    include_attachments: bool = False


class LarkChatConnectorConfig(_OfficeConfig):
    kind: Literal["lark_chat"]
    chat_ref: str = Field(min_length=1, max_length=2048)
    time_range: str = Field(min_length=1, max_length=128)


class LarkSheetConnectorConfig(_OfficeConfig):
    kind: Literal["lark_sheet"]
    sheet_ref: str = Field(min_length=1, max_length=2048)
    sheet_name: str | None = Field(default=None, max_length=256)
    cell_range: str = Field(default="A1:Z1000", min_length=3, max_length=128)


class LarkBaseConnectorConfig(_OfficeConfig):
    kind: Literal["lark_base"]
    app_ref: str = Field(min_length=1, max_length=2048)
    table_ref: str = Field(min_length=1, max_length=2048)
    view_ref: str | None = Field(default=None, max_length=2048)


class LarkMailConnectorConfig(_OfficeConfig):
    kind: Literal["lark_mail"]
    folder: str = Field(min_length=1, max_length=256)
    query: str | None = Field(default=None, max_length=4096)


class _DatabaseConfig(ContractModel):
    secret_ref: SecretRef
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65_535)
    database: str = Field(min_length=1, max_length=256)
    schema_allowlist: list[str] = Field(min_length=1, max_length=1_000)
    table_allowlist: list[str] = Field(min_length=1, max_length=10_000)
    query: str | None = Field(default=None, max_length=100_000)
    query_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    page_size: int = Field(default=1_000, ge=1, le=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=1_000_000)
    byte_limit: int = Field(default=50 * 1024 * 1024, ge=1)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class PostgresqlConnectorConfig(_DatabaseConfig):
    kind: Literal["postgresql"]


class MysqlConnectorConfig(_DatabaseConfig):
    kind: Literal["mysql"]


class SqlserverConnectorConfig(_DatabaseConfig):
    kind: Literal["sqlserver"]


class ClickhouseConnectorConfig(_DatabaseConfig):
    kind: Literal["clickhouse"]


class DorisConnectorConfig(_DatabaseConfig):
    kind: Literal["doris"]


class StarrocksConnectorConfig(_DatabaseConfig):
    kind: Literal["starrocks"]


class HiveConnectorConfig(_DatabaseConfig):
    kind: Literal["hive"]


class OracleConnectorConfig(ContractModel):
    kind: Literal["oracle"]
    secret_ref: SecretRef
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65_535)
    service_name: str = Field(min_length=1, max_length=256)
    schema_allowlist: list[str] = Field(min_length=1, max_length=1_000)
    table_allowlist: list[str] = Field(min_length=1, max_length=10_000)
    query: str | None = Field(default=None, max_length=100_000)
    query_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    page_size: int = Field(default=1_000, ge=1, le=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=1_000_000)
    byte_limit: int = Field(default=50 * 1024 * 1024, ge=1)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class SnowflakeConnectorConfig(ContractModel):
    kind: Literal["snowflake"]
    secret_ref: SecretRef
    account: str = Field(min_length=1, max_length=256)
    warehouse: str = Field(min_length=1, max_length=256)
    database: str = Field(min_length=1, max_length=256)
    schema_allowlist: list[str] = Field(min_length=1, max_length=1_000)
    table_allowlist: list[str] = Field(min_length=1, max_length=10_000)
    query: str | None = Field(default=None, max_length=100_000)
    query_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    page_size: int = Field(default=1_000, ge=1, le=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=1_000_000)
    byte_limit: int = Field(default=50 * 1024 * 1024, ge=1)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class BigqueryConnectorConfig(ContractModel):
    kind: Literal["bigquery"]
    secret_ref: SecretRef
    project_id: str = Field(min_length=1, max_length=256)
    dataset_id: str = Field(min_length=1, max_length=256)
    schema_allowlist: list[str] = Field(min_length=1, max_length=1_000)
    table_allowlist: list[str] = Field(min_length=1, max_length=10_000)
    query: str | None = Field(default=None, max_length=100_000)
    query_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    page_size: int = Field(default=1_000, ge=1, le=100_000)
    row_limit: int = Field(default=10_000, ge=1, le=1_000_000)
    byte_limit: int = Field(default=50 * 1024 * 1024, ge=1)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class _ObjectStorageConfig(ContractModel):
    secret_ref: SecretRef
    bucket: str = Field(min_length=1, max_length=256)
    object_prefix: str = Field(default="", max_length=2048)
    region: str | None = Field(default=None, max_length=256)
    max_objects: int = Field(default=1_000, ge=1, le=1_000_000)
    max_object_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class S3ConnectorConfig(_ObjectStorageConfig):
    kind: Literal["s3"]
    endpoint: str | None = Field(default=None, max_length=2048)


class OssConnectorConfig(_ObjectStorageConfig):
    kind: Literal["oss"]
    endpoint: str = Field(min_length=1, max_length=2048)


class _HttpConfig(ContractModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef | None = None
    operation_allowlist: list[str] = Field(min_length=1, max_length=1_000)
    max_rows: int = Field(default=10_000, ge=1, le=1_000_000)
    max_response_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    timeout_seconds: int = Field(default=30, ge=1, le=900)
    refresh_seconds: int = Field(default=3_600, ge=1, le=31_536_000)


class RestApiConnectorConfig(_HttpConfig):
    kind: Literal["rest_api"]
    pagination_mode: Literal["none", "cursor", "offset", "link_header"] = "none"
    page_size: int = Field(default=100, ge=1, le=100_000)
    max_pages: int = Field(default=10, ge=1, le=1_000)
    terms_ref: str | None = Field(default=None, max_length=2048)


class GraphqlConnectorConfig(_HttpConfig):
    kind: Literal["graphql"]
    query: str = Field(min_length=1, max_length=100_000)


class WebDiscoveryConnectorConfig(_HttpConfig):
    kind: Literal["web_discovery"]
    pagination_mode: Literal["none", "cursor", "offset", "link_header"] = "none"
    page_size: int = Field(default=100, ge=1, le=100_000)
    max_pages: int = Field(default=10, ge=1, le=1_000)
    terms_ref: str | None = Field(default=None, max_length=2048)


class WebhookConnectorConfig(ContractModel):
    kind: Literal["webhook"]
    secret_ref: SecretRef
    listen_path: str = Field(min_length=1, max_length=2048)
    schema_ref: str = Field(min_length=1, max_length=2048)
    max_event_bytes: int = Field(default=1_000_000, ge=1, le=100 * 1024 * 1024)
    max_events: int = Field(default=10_000, ge=1, le=1_000_000)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)


class KafkaConnectorConfig(ContractModel):
    kind: Literal["kafka"]
    secret_ref: SecretRef
    bootstrap_servers: list[str] = Field(min_length=1, max_length=100)
    topics: list[str] = Field(min_length=1, max_length=1_000)
    consumer_group: str = Field(min_length=1, max_length=256)
    max_messages: int = Field(default=1_000, ge=1, le=1_000_000)
    max_message_bytes: int = Field(default=1_000_000, ge=1, le=100 * 1024 * 1024)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


class McpCustomConnectorConfig(ContractModel):
    kind: Literal["mcp_custom"]
    transport: Literal["stdio", "streamable_http", "sse"]
    command: str | None = Field(default=None, max_length=2048)
    args: list[str] = Field(default_factory=list, max_length=100)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = Field(default=None, max_length=2048)
    endpoint: str | None = Field(default=None, max_length=2048)
    secret_ref: SecretRef | None = None
    oauth_scope_ref: str | None = Field(default=None, max_length=2048)
    tool_allowlist: list[str] = Field(min_length=1, max_length=1_000)
    startup_timeout_seconds: float = Field(default=10, gt=0, le=900)
    call_timeout_seconds: float = Field(default=30, gt=0, le=900)
    max_pages: int = Field(default=10, ge=1, le=1_000)
    output_bytes: int = Field(default=1_000_000, ge=1, le=100 * 1024 * 1024)


class CustomHttpConnectorConfig(_HttpConfig):
    kind: Literal["custom_http"]
    name: str = Field(min_length=1, max_length=256)
    method: Literal["GET", "HEAD"] = "GET"
    pagination_mode: Literal["none", "cursor", "offset"] = "none"
    page_size: int = Field(default=100, ge=1, le=100_000)
    max_pages: int = Field(default=10, ge=1, le=1_000)


class OpenapiSpecConnectorConfig(ContractModel):
    kind: Literal["openapi_spec"]
    spec_ref: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef | None = None
    operation_allowlist: list[str] = Field(min_length=1, max_length=1_000)
    server_url: str | None = Field(default=None, max_length=2048)
    max_rows: int = Field(default=10_000, ge=1, le=1_000_000)
    max_response_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    timeout_seconds: int = Field(default=30, ge=1, le=900)


ConnectorKindConfig = Annotated[
    LarkDocConnectorConfig
    | LarkWikiConnectorConfig
    | LarkDriveConnectorConfig
    | LarkMeetingConnectorConfig
    | LarkMinutesConnectorConfig
    | LarkGroupConnectorConfig
    | LarkChatConnectorConfig
    | LarkSheetConnectorConfig
    | LarkBaseConnectorConfig
    | LarkMailConnectorConfig
    | CsvConnectorConfig
    | ExcelConnectorConfig
    | JsonConnectorConfig
    | ParquetConnectorConfig
    | DocumentConnectorConfig
    | LocalFileConnectorConfig
    | S3ConnectorConfig
    | OssConnectorConfig
    | PostgresqlConnectorConfig
    | MysqlConnectorConfig
    | OracleConnectorConfig
    | SqlserverConnectorConfig
    | SqliteConnectorConfig
    | ClickhouseConnectorConfig
    | DorisConnectorConfig
    | StarrocksConnectorConfig
    | SnowflakeConnectorConfig
    | BigqueryConnectorConfig
    | HiveConnectorConfig
    | RestApiConnectorConfig
    | GraphqlConnectorConfig
    | WebDiscoveryConnectorConfig
    | WebhookConnectorConfig
    | KafkaConnectorConfig
    | McpCustomConnectorConfig
    | CustomHttpConnectorConfig
    | OpenapiSpecConnectorConfig,
    Field(discriminator="kind"),
]

_ADAPTER = TypeAdapter(ConnectorKindConfig)


def validate_kind_config(value: object) -> ConnectorKindConfig:
    """Validate one catalog connector without contacting its provider."""
    if isinstance(value, dict) and value.get("kind") == "oracle" and "dsnRef" in value:
        value = {key: item for key, item in value.items() if key != "dsnRef"} | {
            "host": "legacy-dsn",
            "port": 1521,
            "serviceName": "legacy",
            "tableAllowlist": ["legacy"],
        }
    return _ADAPTER.validate_python(value)


def validate_runtime_connector_config(
    *,
    kind: str,
    endpoint: str,
    options: dict[str, object] | None,
) -> ConnectorKindConfig:
    """Compatibility adapter from the narrow STEP 1 runtime envelope."""
    values = dict(options or {})
    aliases = {
        "markdown": "local_file",
        "pdf": "doc_txt",
        "office": "doc_txt",
        "web_api": "rest_api",
        "web_url": "web_discovery",
        "openapi": "openapi_spec",
        "mcp": "mcp_custom",
    }
    canonical = aliases.get(kind, kind)
    values["kind"] = canonical
    if canonical in {"local_file", "doc_txt", "csv"}:
        values.setdefault("sourceRef", endpoint)
    elif canonical in {"rest_api", "web_discovery"}:
        values.setdefault("endpoint", endpoint)
        values.setdefault("operationAllowlist", ["read"])
    elif canonical == "mcp_custom":
        values.setdefault("transport", "streamable_http")
        values.setdefault("endpoint", endpoint)
        values.setdefault("toolAllowlist", ["read"])
    elif canonical == "oracle":
        # The legacy SPI carried an opaque DSN. Its adapter never opens the
        # provider; retain strict limits while mapping it to inert placeholders.
        values.pop("dsnRef", None)
        values.setdefault("host", "legacy-dsn")
        values.setdefault("port", 1521)
        values.setdefault("serviceName", "legacy")
        values.setdefault("tableAllowlist", ["legacy"])
    if kind == "published_skill":
        raise ValueError("published_skill is not one of the 37 source connectors")
    return validate_kind_config(values)


def connector_config_schema() -> dict[str, object]:
    """Return the generated schema with one discriminator target per connector."""
    return _ADAPTER.json_schema()
