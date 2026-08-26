"""Read-only PostgreSQL/MySQL adapters with bounded discovery and reads."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from ..security import validate_database_limits, validate_read_only_sql
from .adapters import _infer_mapping_fields
from .connector_adapter import ConnectorAdapterError
from .http_transport import validate_network_endpoint
from .models import (
    CapabilityReason,
    ConnectorOperation,
    DiscoveredField,
    DiscoveredResource,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _database_endpoint(host: str, port: int) -> str:
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{bracketed}:{port}"


@dataclass(frozen=True)
class DatabaseReadResult:
    source_locator: str
    raw_content: bytes
    rows: list[dict[str, object]]
    fields: list[tuple[str, str, bool]]
    media_type: str
    adapter_run_id: str
    checkpoint: dict[str, str]


@dataclass(frozen=True)
class DatabaseOptions:
    host: str
    port: int
    database: str
    username: str
    password: str
    row_limit: int
    byte_limit: int
    timeout: int
    page_size: int


class SqlDatabaseAdapter:
    CONNECTORS = frozenset({"postgresql", "mysql"})

    def __init__(
        self,
        *,
        secret_resolver: Callable[[str], str | None] | None = None,
        resolver: Callable[[str], list[str]] | None = None,
        allow_private_hosts: set[str] | None = None,
    ) -> None:
        self._secret_resolver = secret_resolver or (lambda _ref: None)
        self._resolver = resolver
        self._allow_private_hosts = frozenset(allow_private_hosts or ())

    def discover(
        self,
        *,
        connector_key: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        trace_id: str,
    ) -> ConnectorOperation:
        options = self._options(connector_key, configuration, secret_ref)
        pinned = self._pin_endpoint(options, stage="discover")
        try:
            with closing(
                self._connection(connector_key, options, configuration)
            ) as connection:
                resources = self._discover_resources(
                    connector_key,
                    connection,
                    configuration,
                    row_limit=options.row_limit,
                )
                self._verify_endpoint_pin(
                    options,
                    pinned=pinned,
                    stage="discover",
                )
        except Exception as error:
            mapped = _database_error(connector_key, error, stage="discover")
            if mapped is error:
                raise
            raise mapped from error
        if not resources:
            raise ValueError("database allowlists matched no readable tables")
        return ConnectorOperation(
            operation="discover",
            status="succeeded",
            trace_id=trace_id,
            reason=CapabilityReason(
                code="DATABASE_RESOURCES_DISCOVERED",
                message="The read-only database session discovered allowlisted tables.",
            ),
            resources=resources,
        )

    def read(
        self,
        *,
        connector_key: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        resource: DiscoveredResource,
        parameters: Mapping[str, object] | None,
        trace_id: str,
    ) -> DatabaseReadResult:
        options = self._options(connector_key, configuration, secret_ref)
        pinned = self._pin_endpoint(options, stage="read")
        query_parameters = _parameter_map(parameters)
        raw_query = configuration.get("query")
        try:
            with closing(
                self._connection(connector_key, options, configuration)
            ) as connection:
                if isinstance(raw_query, str) and raw_query.strip():
                    validate_read_only_sql(raw_query, parameters=query_parameters)
                    _validate_query_allowlist(raw_query, configuration)
                    inner_query = _bind_named_parameters(
                        raw_query.rstrip().rstrip(";"),
                        query_parameters,
                        placeholder="%s",
                    )
                    query = f"SELECT * FROM ({inner_query}) AS bounded_source LIMIT %s"
                    values = [
                        query_parameters[name] for name in _parameter_names(raw_query)
                    ]
                    values.append(options.row_limit + 1)
                else:
                    schema = resource.schema_name
                    table = resource.name
                    _require_allowlisted_resource(configuration, schema, table)
                    query = (
                        f"SELECT * FROM {_quoted_identifier(schema, connector_key)}."
                        f"{_quoted_identifier(table, connector_key)} LIMIT %s"
                    )
                    values = [options.row_limit + 1]
                with connection.cursor() as cursor:
                    cursor.execute(query, values)
                    names = [str(item[0]) for item in (cursor.description or ())]
                    raw_rows = []
                    page_size = options.page_size
                    while len(raw_rows) <= options.row_limit:
                        page = cursor.fetchmany(
                            min(
                                page_size,
                                options.row_limit + 1 - len(raw_rows),
                            )
                        )
                        if not page:
                            break
                        raw_rows.extend(page)
                self._verify_endpoint_pin(options, pinned=pinned, stage="read")
        except Exception as error:
            mapped = _database_error(connector_key, error, stage="read")
            if mapped is error:
                raise
            raise mapped from error
        if len(raw_rows) > options.row_limit:
            raise ConnectorAdapterError(
                "DATABASE_ROW_LIMIT",
                "Database result exceeds the configured row limit.",
                stage="read",
            )
        rows = [
            {name: _json_compatible(row[index]) for index, name in enumerate(names)}
            for row in raw_rows
        ]
        raw = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(raw) > options.byte_limit:
            raise ConnectorAdapterError(
                "DATABASE_BYTE_LIMIT",
                "Database result exceeds the configured byte limit.",
                stage="read",
            )
        digest = hashlib.sha256(raw).hexdigest()
        return DatabaseReadResult(
            source_locator=(
                f"{connector_key}://{configuration['host']}:"
                f"{configuration['port']}/{configuration['database']}/"
                f"{resource.schema_name}.{resource.name}"
            ),
            raw_content=raw,
            rows=rows,
            fields=_infer_mapping_fields(rows)
            if rows
            else [
                (field.name, field.data_type, field.nullable)
                for field in resource.fields
            ],
            media_type="application/json",
            adapter_run_id=f"database-run-{digest[:24]}",
            checkpoint={"contentDigest": digest},
        )

    def _options(
        self,
        connector_key: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
    ) -> DatabaseOptions:
        if connector_key not in self.CONNECTORS:
            raise ValueError("database adapter does not support this connector")
        if not secret_ref:
            raise PermissionError("database secretRef is required")
        raw_secret = self._secret_resolver(secret_ref)
        if raw_secret is None:
            raise PermissionError("database secretRef could not be resolved")
        try:
            credentials = json.loads(raw_secret)
        except json.JSONDecodeError as error:
            raise ValueError(
                "database secret must contain a JSON username/password object"
            ) from error
        if (
            not isinstance(credentials, dict)
            or not isinstance(credentials.get("username"), str)
            or not isinstance(credentials.get("password"), str)
        ):
            raise TypeError(
                "database secret must contain string username and password fields"
            )
        host = configuration.get("host")
        port = configuration.get("port")
        database = configuration.get("database")
        if (
            not isinstance(host, str)
            or not host
            or isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
            or not isinstance(database, str)
            or not database
        ):
            raise ValueError("database host, port, and database are required")
        row_limit = _positive_integer(configuration, "rowLimit", 10_000)
        byte_limit = _positive_integer(configuration, "byteLimit", 50 * 1024 * 1024)
        timeout = _positive_integer(configuration, "timeoutSeconds", 30)
        page_size = _positive_integer(configuration, "pageSize", 1_000)
        page_size = min(page_size, row_limit)
        validate_database_limits(
            row_limit=row_limit,
            byte_limit=byte_limit,
            timeout_seconds=timeout,
        )
        _allowlists(configuration)
        return DatabaseOptions(
            host=host,
            port=port,
            database=database,
            username=credentials["username"],
            password=credentials["password"],
            row_limit=row_limit,
            byte_limit=byte_limit,
            timeout=timeout,
            page_size=page_size,
        )

    def _pin_endpoint(
        self,
        options: DatabaseOptions,
        *,
        stage: str,
    ) -> frozenset[str]:
        try:
            return validate_network_endpoint(
                _database_endpoint(options.host, options.port),
                resolver=self._resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
        except (OSError, ValueError) as error:
            raise ConnectorAdapterError(
                "DATABASE_ENDPOINT_FORBIDDEN",
                "Database endpoint failed the network safety policy.",
                stage="discover" if stage == "discover" else "read",
            ) from error

    def _verify_endpoint_pin(
        self,
        options: DatabaseOptions,
        *,
        pinned: frozenset[str],
        stage: str,
    ) -> None:
        try:
            current = self._pin_endpoint(options, stage=stage)
        except ConnectorAdapterError as error:
            raise ConnectorAdapterError(
                "DATABASE_DNS_REBINDING",
                "Database endpoint resolution changed during the request.",
                stage="discover" if stage == "discover" else "read",
            ) from error
        if current != pinned:
            raise ConnectorAdapterError(
                "DATABASE_DNS_REBINDING",
                "Database endpoint resolution changed during the request.",
                stage="discover" if stage == "discover" else "read",
            )

    def options(
        self,
        connector_key: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        *,
        workspace_id: str,
    ) -> DatabaseOptions:
        """Validate credentials and options without opening a database socket."""
        if not secret_ref:
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_REQUIRED",
                "Database secretRef is required.",
                stage="authenticate",
            )
        if not secret_ref.startswith(f"secret://{workspace_id}/"):
            raise ConnectorAdapterError(
                "INVALID_SECRET_REFERENCE",
                "secretRef must belong to the active workspace.",
                stage="authenticate",
            )
        return self._options(connector_key, configuration, secret_ref)

    @staticmethod
    def _connection(
        connector_key: str,
        options: DatabaseOptions,
        configuration: Mapping[str, object],
    ):
        if connector_key == "postgresql":
            import psycopg2

            connection = psycopg2.connect(
                host=options.host,
                port=options.port,
                dbname=options.database,
                user=options.username,
                password=options.password,
                connect_timeout=options.timeout,
            )
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET LOCAL statement_timeout = %s",
                    (options.timeout * 1000,),
                )
            return connection

        import pymysql

        connection = pymysql.connect(
            host=options.host,
            port=options.port,
            database=options.database,
            user=options.username,
            password=options.password,
            connect_timeout=options.timeout,
            read_timeout=options.timeout,
            write_timeout=options.timeout,
            charset="utf8mb4",
            autocommit=False,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute(
                "SET SESSION MAX_EXECUTION_TIME=%s",
                (options.timeout * 1000,),
            )
        return connection

    @staticmethod
    def _discover_resources(
        connector_key: str,
        connection,
        configuration: Mapping[str, object],
        *,
        row_limit: int,
    ) -> list[DiscoveredResource]:
        schemas, tables = _allowlists(configuration)
        placeholder = "%s"
        if connector_key == "postgresql":
            query = """
                SELECT table_schema, table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = ANY(%s)
                ORDER BY table_schema, table_name, ordinal_position
            """
            values: list[object] = [schemas]
        else:
            markers = ", ".join(placeholder for _ in schemas)
            query = f"""
                SELECT table_schema, table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema IN ({markers})
                ORDER BY table_schema, table_name, ordinal_position
            """
            values = list(schemas)
        with connection.cursor() as cursor:
            cursor.execute(query, values)
            metadata = cursor.fetchall()
        grouped: dict[tuple[str, str], list[DiscoveredField]] = {}
        for schema, table, field, data_type, nullable in metadata:
            if tables and str(table) not in tables:
                continue
            grouped.setdefault((str(schema), str(table)), []).append(
                DiscoveredField(
                    name=str(field),
                    data_type=str(data_type),
                    nullable=str(nullable).casefold() == "yes",
                )
            )
        resources: list[DiscoveredResource] = []
        for (schema, table), fields in grouped.items():
            quoted_schema = _quoted_identifier(schema, connector_key)
            quoted_table = _quoted_identifier(table, connector_key)
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {quoted_schema}.{quoted_table}")
                count = int(cursor.fetchone()[0])
            resources.append(
                DiscoveredResource(
                    id=_resource_id(connector_key, schema, table),
                    name=table,
                    schema_name=schema,
                    resource_type="table",
                    row_count=min(count, row_limit),
                    fields=fields,
                )
            )
        return resources


def _allowlists(
    configuration: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    schemas = configuration.get("schemaAllowlist")
    tables = configuration.get("tableAllowlist")
    if not isinstance(schemas, list) or not schemas:
        raise ValueError("database schemaAllowlist must not be empty")
    if not all(
        isinstance(item, str) and _IDENTIFIER.fullmatch(item) for item in schemas
    ):
        raise ValueError("database schemaAllowlist contains an invalid identifier")
    if not isinstance(tables, list) or not tables:
        raise ValueError("database tableAllowlist must not be empty")
    if not all(
        isinstance(item, str) and _IDENTIFIER.fullmatch(item) for item in tables
    ):
        raise ValueError("database tableAllowlist contains an invalid identifier")
    return list(dict.fromkeys(schemas)), list(dict.fromkeys(tables))


def _require_allowlisted_resource(
    configuration: Mapping[str, object],
    schema: str | None,
    table: str,
) -> None:
    schemas, tables = _allowlists(configuration)
    if schema not in schemas or table not in tables:
        raise PermissionError("database resource is outside the configured allowlist")


def _validate_query_allowlist(
    query: str,
    configuration: Mapping[str, object],
) -> None:
    schemas, tables = _allowlists(configuration)
    references = re.findall(
        r"\b(?:FROM|JOIN)\s+"
        r"(?:(?:\"([A-Za-z_][A-Za-z0-9_$]*)\"|([A-Za-z_][A-Za-z0-9_$]*))\.)?"
        r"(?:\"([A-Za-z_][A-Za-z0-9_$]*)\"|([A-Za-z_][A-Za-z0-9_$]*))",
        query,
        flags=re.IGNORECASE,
    )
    if not references:
        raise ValueError("database query must read an allowlisted table")
    for quoted_schema, schema, quoted_table, table in references:
        actual_schema = quoted_schema or schema
        actual_table = quoted_table or table
        if actual_table not in tables or (
            actual_schema is not None and actual_schema not in schemas
        ):
            raise PermissionError(
                "database query references a table outside the configured allowlist"
            )


def _quoted_identifier(value: str | None, connector_key: str) -> str:
    if value is None or not _IDENTIFIER.fullmatch(value):
        raise ValueError("database identifier is invalid")
    quote = '"' if connector_key == "postgresql" else "`"
    return f"{quote}{value}{quote}"


def _parameter_names(query: str) -> list[str]:
    return re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", query)


def _bind_named_parameters(
    query: str,
    parameters: Mapping[str, object],
    *,
    placeholder: str,
) -> str:
    validate_read_only_sql(query, parameters=dict(parameters))
    return re.sub(
        r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)",
        lambda match: placeholder if match.group(1) in parameters else match.group(0),
        query,
    )


def _parameter_map(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not all(isinstance(key, str) for key in value):
        raise ValueError("database query parameters must have string names")
    return dict(value)


def _positive_integer(
    configuration: Mapping[str, object], key: str, default: int
) -> int:
    value = configuration.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"database {key} must be a positive integer")
    return value


def _resource_id(connector_key: str, schema: str, table: str) -> str:
    digest = hashlib.sha256(f"{connector_key}:{schema}:{table}".encode()).hexdigest()
    return f"database-table-{digest[:24]}"


def _json_compatible(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _database_error(
    connector_key: str,
    error: Exception,
    *,
    stage: str,
) -> Exception:
    if isinstance(error, ConnectorAdapterError):
        return error
    if connector_key == "postgresql":
        try:
            import psycopg2
        except ImportError:
            return ConnectorAdapterError(
                "DATABASE_DRIVER_UNAVAILABLE",
                "The PostgreSQL driver is not installed on the server.",
                stage="discover" if stage == "discover" else "read",
            )
        if not isinstance(error, psycopg2.Error):
            return error
        code = getattr(error, "pgcode", None)
        message = str(error).casefold()
        if code == "28P01" or "password authentication failed" in message:
            return ConnectorAdapterError(
                "DATABASE_AUTHENTICATION_FAILED",
                "PostgreSQL rejected the configured credential reference.",
                stage="authenticate",
            )
        if code == "57014":
            return ConnectorAdapterError(
                "DATABASE_TIMEOUT",
                "PostgreSQL exceeded the configured execution timeout.",
                stage="discover" if stage == "discover" else "read",
                retryable=True,
            )
    else:
        try:
            import pymysql
        except ImportError:
            return ConnectorAdapterError(
                "DATABASE_DRIVER_UNAVAILABLE",
                "The MySQL driver is not installed on the server.",
                stage="discover" if stage == "discover" else "read",
            )
        if not isinstance(error, pymysql.MySQLError):
            return error
        number = error.args[0] if error.args else None
        if number in {1044, 1045, 1698}:
            return ConnectorAdapterError(
                "DATABASE_AUTHENTICATION_FAILED",
                "MySQL rejected the configured credential reference.",
                stage="authenticate",
            )
        if number in {1317, 3024}:
            return ConnectorAdapterError(
                "DATABASE_TIMEOUT",
                "MySQL exceeded the configured execution timeout.",
                stage="discover" if stage == "discover" else "read",
                retryable=True,
            )
    return ConnectorAdapterError(
        "DATABASE_UNAVAILABLE" if stage == "discover" else "DATABASE_READ_FAILED",
        (
            f"{connector_key} could not be reached with the configured connection."
            if stage == "discover"
            else f"{connector_key} could not complete the bounded read."
        ),
        stage="discover" if stage == "discover" else "read",
        retryable=True,
    )
