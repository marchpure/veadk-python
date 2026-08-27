"""Executable adapters for credential-backed external providers.

Drivers are imported lazily so catalog and validation remain available in a
minimal deployment. A missing credential or driver is a typed blocker, never
a fabricated provider success.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import ModuleType
from typing import cast
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from ..security import validate_database_limits, validate_read_only_sql
from .adapters import _infer_mapping_fields
from .connector_adapter import (
    ConnectorAdapter,
    ConnectorAdapterError,
    ConnectorCertification,
    ConnectorReadResult,
    ConnectorRequest,
    ConnectorStage,
    succeeded_operation,
    validate_configuration,
)
from .http_transport import SecureHttpTransport, validate_network_endpoint
from .models import (
    ConnectorDefinition,
    ConnectorOperation,
    DiscoveredField,
    DiscoveredResource,
    SourceType,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class ProviderSpec:
    driver: str
    package: str
    install_command: str
    verification_command: str
    missing_condition: str
    required_secret_fields: tuple[str, ...]
    checkpoint: str


class ProviderConnectorAdapter(ConnectorAdapter):
    """Common fail-closed lifecycle for one external provider."""

    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        spec: ProviderSpec,
        secret_resolver: Callable[[str], str | None],
    ) -> None:
        self.definition = definition
        self.spec = spec
        self.connector_keys = frozenset({definition.connector_key})
        self._secret_resolver = secret_resolver

    @property
    def certification(self) -> ConnectorCertification:
        return ConnectorCertification(
            connector_key=self.definition.connector_key,
            implementation=f"{type(self).__module__}.{type(self).__name__}",
            driver=self.spec.driver,
            install_command=self.spec.install_command,
            verification_command=self.spec.verification_command,
            missing_condition=self.spec.missing_condition,
            required_secret_fields=self.spec.required_secret_fields,
            provider_scopes=tuple(self.definition.permissions.provider_scopes),
            checkpoint=self.spec.checkpoint,
        )

    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        validate_configuration(self.definition, request.configuration)
        self._validate_provider_configuration(request.configuration)
        return succeeded_operation(
            "validate",
            request,
            code="PROVIDER_CONFIGURATION_VALIDATED",
            message=f"{self.definition.name} configuration passed local validation.",
        )

    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        self._credentials(request)
        self._load_driver()
        return succeeded_operation(
            "authenticate",
            request,
            code="PROVIDER_CREDENTIAL_READY",
            message=f"{self.definition.name} credential and official driver are available.",
        )

    def authorize(self, request: ConnectorRequest) -> ConnectorOperation:
        self.authenticate(request)
        return succeeded_operation(
            "authorize",
            request,
            code="PROVIDER_AUTHORIZATION_READY",
            message=f"{self.definition.name} authorization will be verified by discovery.",
        )

    def introspect(self, request: ConnectorRequest) -> ConnectorOperation:
        if not request.discovered_resources:
            return self.discover(request).model_copy(update={"operation": "introspect"})
        return succeeded_operation(
            "introspect",
            request,
            code="PROVIDER_SCHEMA_INTROSPECTED",
            message=f"{self.definition.name} resource metadata was introspected.",
            resources=list(request.discovered_resources),
        )

    def sample(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return succeeded_operation(
            "sample",
            request,
            code="PROVIDER_SAMPLE_READ",
            message=f"{self.definition.name} returned a bounded sample.",
            resources=[request.resource] if request.resource else [],
        )

    def ingest(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._stage_success("ingest", request)

    def profile(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._stage_success("profile", request)

    def clean(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._stage_success("clean", request)

    def golden(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._stage_success("golden", request)

    def refresh(self, request: ConnectorRequest) -> ConnectorReadResult:
        return request.read_cache.load(lambda: self.read(request))

    def checkpoint(self, request: ConnectorRequest) -> Mapping[str, str]:
        return request.read_cache.load(lambda: self.read(request)).checkpoint

    def close(self, request: ConnectorRequest) -> ConnectorOperation:
        return self._stage_success("close", request)

    def _stage_success(
        self, stage: ConnectorStage, request: ConnectorRequest
    ) -> ConnectorOperation:
        return succeeded_operation(
            stage,
            request,
            code="PROVIDER_STAGE_SUCCEEDED",
            message=f"{self.definition.name} lifecycle stage completed.",
        )

    def _credentials(self, request: ConnectorRequest) -> dict[str, object]:
        if not request.secret_ref:
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_REQUIRED",
                f"{self.definition.name} requires a server-side secretRef.",
                stage="authenticate",
            )
        if not request.secret_ref.startswith(f"secret://{request.workspace_id}/"):
            raise ConnectorAdapterError(
                "INVALID_SECRET_REFERENCE",
                "secretRef must belong to the active workspace.",
                stage="authenticate",
            )
        value = self._secret_resolver(request.secret_ref)
        if value is None:
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_UNAVAILABLE",
                f"{self.definition.name} secretRef could not be resolved.",
                stage="authenticate",
            )
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = {"accessToken": value}
        if not isinstance(decoded, dict):
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_INVALID",
                f"{self.definition.name} secret must be a JSON object.",
                stage="authenticate",
            )
        missing = [
            name
            for name in self.spec.required_secret_fields
            if not isinstance(decoded.get(name), str) or not decoded.get(name)
        ]
        if missing:
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_INVALID",
                f"{self.definition.name} secret is missing fields: {missing}.",
                stage="authenticate",
            )
        return {str(key): item for key, item in decoded.items()}

    def _load_driver(self) -> ModuleType:
        try:
            return importlib.import_module(self.spec.driver)
        except ImportError as error:
            raise ConnectorAdapterError(
                "EXTERNAL_DRIVER_UNAVAILABLE",
                (
                    f"{self.definition.name} requires the official "
                    f"{self.spec.package} driver."
                ),
                stage="authenticate",
            ) from error

    def _validate_provider_configuration(
        self, configuration: Mapping[str, object]
    ) -> None:
        del configuration


class ExternalDatabaseAdapter(ProviderConnectorAdapter):
    """Read-only adapters for Oracle, SQL Server, ClickHouse and warehouses."""

    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        spec: ProviderSpec,
        secret_resolver: Callable[[str], str | None],
        resolver: Callable[[str], list[str]] | None,
        allow_private_hosts: set[str],
    ) -> None:
        super().__init__(
            definition=definition,
            spec=spec,
            secret_resolver=secret_resolver,
        )
        self._resolver = resolver
        self._allow_private_hosts = frozenset(allow_private_hosts)

    def _validate_provider_configuration(
        self, configuration: Mapping[str, object]
    ) -> None:
        schemas, tables = _database_allowlists(configuration)
        del schemas, tables
        if self.definition.connector_key not in {"snowflake", "bigquery"}:
            host = str(configuration["host"])
            port = _integer(configuration, "port", 0)
            try:
                validate_network_endpoint(
                    _network_endpoint(host, port),
                    resolver=self._resolver,
                    allow_private_hosts=self._allow_private_hosts,
                )
            except (OSError, ValueError) as error:
                raise ConnectorAdapterError(
                    "DATABASE_ENDPOINT_FORBIDDEN",
                    "Database endpoint failed the network safety policy.",
                    stage="validate",
                ) from error
        query = configuration.get("query")
        parameters = configuration.get("queryParameters", {})
        if parameters is not None and not isinstance(parameters, dict):
            raise ConnectorAdapterError(
                "DATABASE_PARAMETERS_INVALID",
                "Database queryParameters must be an object.",
                stage="validate",
            )
        if isinstance(query, str) and query.strip():
            try:
                validate_read_only_sql(
                    query,
                    parameters=cast(dict[str, object], parameters or {}),
                )
                _validate_query_allowlist(query, configuration)
            except (TypeError, ValueError) as error:
                raise ConnectorAdapterError(
                    "DATABASE_QUERY_INVALID",
                    str(error),
                    stage="validate",
                ) from error
        try:
            validate_database_limits(
                row_limit=_integer(configuration, "rowLimit", 10_000),
                byte_limit=_integer(configuration, "byteLimit", 50 * 1024 * 1024),
                timeout_seconds=_integer(configuration, "timeoutSeconds", 30),
            )
        except ValueError as error:
            raise ConnectorAdapterError(
                "DATABASE_LIMIT_INVALID", str(error), stage="validate"
            ) from error
        page_size = _integer(configuration, "pageSize", 1_000)
        if page_size > _integer(configuration, "rowLimit", 10_000):
            raise ConnectorAdapterError(
                "DATABASE_LIMIT_INVALID",
                "pageSize must not exceed rowLimit.",
                stage="validate",
            )

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.authenticate(request)
        pinned = self._pin_endpoint(request, stage="discover")
        try:
            resources = self._discover(request)
            self._verify_endpoint_pin(
                request,
                pinned=pinned,
                stage="discover",
            )
        except ConnectorAdapterError:
            raise
        except Exception as error:
            raise _provider_failure(
                self.definition.name, "DATABASE_DISCOVERY_FAILED", "discover", error
            ) from error
        if not resources:
            raise ConnectorAdapterError(
                "DATABASE_ALLOWLIST_EMPTY",
                "Database allowlists matched no readable tables.",
                stage="discover",
            )
        return succeeded_operation(
            "discover",
            request,
            code="DATABASE_RESOURCES_DISCOVERED",
            message="The provider returned allowlisted table metadata.",
            resources=resources,
        )

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        self.authenticate(request)
        if request.resource is None:
            raise ConnectorAdapterError(
                "DATABASE_RESOURCE_REQUIRED",
                "Select one discovered database table.",
                stage="read",
            )
        pinned = self._pin_endpoint(request, stage="read")
        try:
            rows = self._read_rows(request)
            self._verify_endpoint_pin(request, pinned=pinned, stage="read")
        except ConnectorAdapterError:
            raise
        except Exception as error:
            raise _provider_failure(
                self.definition.name, "DATABASE_READ_FAILED", "read", error
            ) from error
        return _read_result(
            connector_key=self.definition.connector_key,
            source_type="database",
            locator=(
                f"{self.definition.connector_key}://"
                f"{request.resource.schema_name}.{request.resource.name}"
            ),
            rows=rows,
        )

    def _pin_endpoint(
        self,
        request: ConnectorRequest,
        *,
        stage: ConnectorStage,
    ) -> frozenset[str]:
        if self.definition.connector_key in {"snowflake", "bigquery"}:
            return frozenset()
        host = str(request.configuration["host"])
        port = _integer(request.configuration, "port", 0)
        try:
            return validate_network_endpoint(
                _network_endpoint(host, port),
                resolver=self._resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
        except (OSError, ValueError) as error:
            raise ConnectorAdapterError(
                "DATABASE_ENDPOINT_FORBIDDEN",
                "Database endpoint failed the network safety policy.",
                stage=stage,
            ) from error

    def _verify_endpoint_pin(
        self,
        request: ConnectorRequest,
        *,
        pinned: frozenset[str],
        stage: ConnectorStage,
    ) -> None:
        if not pinned:
            return
        try:
            current = self._pin_endpoint(request, stage=stage)
        except ConnectorAdapterError as error:
            raise ConnectorAdapterError(
                "DATABASE_DNS_REBINDING",
                "Database endpoint resolution changed during the request.",
                stage=stage,
            ) from error
        if current != pinned:
            raise ConnectorAdapterError(
                "DATABASE_DNS_REBINDING",
                "Database endpoint resolution changed during the request.",
                stage=stage,
            )

    def _connect(self, request: ConnectorRequest):
        key = self.definition.connector_key
        config = request.configuration
        credentials = self._credentials(request)
        driver = self._load_driver()
        timeout = _integer(config, "timeoutSeconds", 30)
        if key == "oracle":
            return driver.connect(
                user=credentials["username"],
                password=credentials["password"],
                dsn=driver.makedsn(
                    config["host"],
                    config["port"],
                    service_name=config["serviceName"],
                ),
            )
        if key == "sqlserver":
            connection_string = (
                str(credentials.get("connectionString") or "")
                or "DRIVER={ODBC Driver 18 for SQL Server};"
                f"SERVER={config['host']},{config['port']};"
                f"DATABASE={config['database']};UID={credentials['username']};"
                f"PWD={credentials['password']};Encrypt=yes;"
                "TrustServerCertificate=no;"
            )
            return driver.connect(connection_string, timeout=timeout)
        if key == "clickhouse":
            return driver.get_client(
                host=config["host"],
                port=config["port"],
                database=config["database"],
                username=credentials["username"],
                password=credentials["password"],
                connect_timeout=timeout,
                send_receive_timeout=timeout,
            )
        if key in {"doris", "starrocks"}:
            connection = driver.connect(
                host=str(config["host"]),
                port=_integer(config, "port", 0),
                database=str(config["database"]),
                user=str(credentials["username"]),
                password=str(credentials["password"]),
                connect_timeout=timeout,
                read_timeout=timeout,
                write_timeout=timeout,
                autocommit=False,
            )
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute("START TRANSACTION READ ONLY")
            return connection
        if key == "snowflake":
            return driver.connect(
                account=config["account"],
                warehouse=config["warehouse"],
                database=config["database"],
                user=credentials["username"],
                password=credentials["password"],
                login_timeout=timeout,
                network_timeout=timeout,
            )
        if key == "hive":
            auth = str(credentials.get("auth") or "LDAP")
            return driver.Connection(
                host=config["host"],
                port=config["port"],
                database=config["database"],
                username=credentials["username"],
                password=credentials["password"],
                auth=auth,
            )
        raise ConnectorAdapterError(
            "DATABASE_DRIVER_UNAVAILABLE",
            f"{self.definition.name} runtime is not configured.",
            stage="authenticate",
        )

    def _discover(self, request: ConnectorRequest) -> list[DiscoveredResource]:
        key = self.definition.connector_key
        if key == "bigquery":
            return self._discover_bigquery(request)
        if key == "clickhouse":
            client = self._connect(request)
            try:
                schemas, tables = _database_allowlists(request.configuration)
                result = client.query(
                    """
                    SELECT database, table, name, type
                    FROM system.columns
                    WHERE database IN %(schemas)s
                    ORDER BY database, table, position
                    """,
                    parameters={"schemas": tuple(schemas)},
                )
                metadata = result.result_rows
            finally:
                client.close()
            return _metadata_resources(key, metadata, tables)
        connection = self._connect(request)
        try:
            schemas, tables = _database_allowlists(request.configuration)
            cursor = connection.cursor()
            try:
                if key == "oracle":
                    markers = ",".join(f":{index + 1}" for index in range(len(schemas)))
                    cursor.execute(
                        "SELECT owner, table_name, column_name, data_type, nullable "
                        f"FROM all_tab_columns WHERE owner IN ({markers}) "
                        "ORDER BY owner, table_name, column_id",
                        [schema.upper() for schema in schemas],
                    )
                else:
                    marker = "%s" if key in {"doris", "starrocks", "hive"} else "?"
                    markers = ",".join(marker for _ in schemas)
                    cursor.execute(
                        "SELECT table_schema, table_name, column_name, "
                        "data_type, is_nullable FROM information_schema.columns "
                        f"WHERE table_schema IN ({markers}) "
                        "ORDER BY table_schema, table_name, ordinal_position",
                        schemas,
                    )
                metadata = cursor.fetchall()
            finally:
                cursor.close()
        finally:
            connection.close()
        return _metadata_resources(key, metadata, tables)

    def _discover_bigquery(self, request: ConnectorRequest) -> list[DiscoveredResource]:
        credentials = self._credentials(request)
        module = self._load_driver()
        service_account = importlib.import_module("google.oauth2.service_account")
        credential = service_account.Credentials.from_service_account_info(credentials)
        client = module.Client(
            project=request.configuration["projectId"],
            credentials=credential,
        )
        dataset = str(request.configuration["datasetId"])
        _schemas, tables = _database_allowlists(request.configuration)
        resources = []
        for item in client.list_tables(dataset, max_results=1_000):
            if item.table_id not in tables:
                continue
            table = client.get_table(item.reference)
            resources.append(
                DiscoveredResource(
                    id=_resource_id("bigquery", dataset, item.table_id),
                    name=item.table_id,
                    schema_name=dataset,
                    resource_type="table",
                    row_count=min(
                        int(table.num_rows or 0),
                        _integer(request.configuration, "rowLimit", 10_000),
                    ),
                    fields=[
                        DiscoveredField(
                            name=field.name,
                            data_type=field.field_type.casefold(),
                            nullable=field.mode != "REQUIRED",
                        )
                        for field in table.schema
                    ],
                )
            )
        client.close()
        return resources

    def _read_rows(self, request: ConnectorRequest) -> list[dict[str, object]]:
        key = self.definition.connector_key
        config = request.configuration
        resource = request.resource
        assert resource is not None
        _require_resource(config, resource)
        limit = _integer(config, "rowLimit", 10_000)
        byte_limit = _integer(config, "byteLimit", 50 * 1024 * 1024)
        query = config.get("query")
        parameters = cast(dict[str, object], config.get("queryParameters") or {})
        if key == "bigquery":
            return self._read_bigquery(request, limit=limit, byte_limit=byte_limit)
        if isinstance(query, str) and query.strip():
            validate_read_only_sql(query, parameters=parameters)
            _validate_query_allowlist(query, config)
            statement = query.rstrip().rstrip(";")
        else:
            statement = (
                f"SELECT * FROM {_quote(resource.schema_name, key)}."
                f"{_quote(resource.name, key)}"
            )
        if key == "clickhouse":
            client = self._connect(request)
            try:
                result = client.query(
                    f"SELECT * FROM ({statement}) AS bounded_source LIMIT {limit + 1}",
                    parameters=parameters,
                )
                rows = [
                    {
                        str(name): _json_value(value)
                        for name, value in zip(result.column_names, row)
                    }
                    for row in result.result_rows
                ]
            finally:
                client.close()
        else:
            connection = self._connect(request)
            try:
                cursor = connection.cursor()
                try:
                    if key == "oracle":
                        bound = dict(parameters)
                        # Oracle bind names may not begin with an underscore
                        # when using the thin ``oracledb`` driver. Keep this
                        # adapter-owned name distinct from user parameters
                        # while remaining valid for Oracle's bind parser.
                        bound["adapter_limit"] = limit + 1
                        cursor.execute(
                            f"SELECT * FROM ({statement}) "
                            "WHERE ROWNUM <= :adapter_limit",
                            bound,
                        )
                    elif key == "sqlserver":
                        bound_query, values = _qmark_query(statement, parameters)
                        cursor.execute(
                            f"SELECT TOP {limit + 1} * FROM ({bound_query}) bounded_source",
                            values,
                        )
                    else:
                        if key in {"doris", "starrocks"}:
                            bound_query, values = _format_query(statement, parameters)
                            cursor.execute(
                                f"SELECT * FROM ({bound_query}) bounded_source "
                                f"LIMIT {limit + 1}",
                                values,
                            )
                        elif key in {"snowflake", "hive"}:
                            bound_query = _pyformat_query(statement, parameters)
                            cursor.execute(
                                f"SELECT * FROM ({bound_query}) bounded_source "
                                f"LIMIT {limit + 1}",
                                parameters,
                            )
                        else:
                            cursor.execute(
                                f"SELECT * FROM ({statement}) bounded_source "
                                f"LIMIT {limit + 1}",
                                parameters,
                            )
                    names = [str(item[0]) for item in cursor.description or ()]
                    raw_rows: list[object] = []
                    page_size = min(_integer(config, "pageSize", 1_000), limit + 1)
                    while len(raw_rows) <= limit:
                        page = cursor.fetchmany(
                            min(page_size, limit + 1 - len(raw_rows))
                        )
                        if not page:
                            break
                        raw_rows.extend(page)
                    rows = []
                    for raw_row in raw_rows:
                        if not hasattr(raw_row, "__getitem__") or not hasattr(
                            raw_row, "__len__"
                        ):
                            raise TypeError("database driver returned a non-sequence row")
                        rows.append(
                            {
                                name: _json_value(raw_row[index])
                                for index, name in enumerate(names)
                            }
                        )
                finally:
                    cursor.close()
            finally:
                connection.close()
        return _enforce_rows(rows, limit=limit, byte_limit=byte_limit)

    def _read_bigquery(
        self,
        request: ConnectorRequest,
        *,
        limit: int,
        byte_limit: int,
    ) -> list[dict[str, object]]:
        module = self._load_driver()
        credentials = self._credentials(request)
        service_account = importlib.import_module("google.oauth2.service_account")
        credential = service_account.Credentials.from_service_account_info(credentials)
        client = module.Client(
            project=request.configuration["projectId"],
            credentials=credential,
        )
        resource = request.resource
        assert resource is not None
        query = request.configuration.get("query")
        if not isinstance(query, str) or not query.strip():
            query = (
                f"SELECT * FROM `{request.configuration['projectId']}."
                f"{resource.schema_name}.{resource.name}`"
            )
        parameters = cast(
            dict[str, object],
            request.configuration.get("queryParameters") or {},
        )
        validate_read_only_sql(query, parameters=parameters)
        _validate_query_allowlist(query.replace("`", ""), request.configuration)
        query, query_parameters = _bigquery_bind_parameters(module, query, parameters)
        job_config = module.QueryJobConfig(
            maximum_bytes_billed=byte_limit,
            use_query_cache=True,
            query_parameters=query_parameters,
        )
        try:
            result = client.query(
                f"SELECT * FROM ({query.rstrip().rstrip(';')}) LIMIT {limit + 1}",
                job_config=job_config,
                timeout=_integer(request.configuration, "timeoutSeconds", 30),
            ).result(max_results=limit + 1)
            rows = [
                {str(key): _json_value(value) for key, value in dict(row).items()}
                for row in result
            ]
        finally:
            client.close()
        return _enforce_rows(rows, limit=limit, byte_limit=byte_limit)


class ObjectStorageAdapter(ProviderConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        spec: ProviderSpec,
        secret_resolver: Callable[[str], str | None],
        resolver: Callable[[str], list[str]] | None,
        allow_private_hosts: set[str],
    ) -> None:
        super().__init__(
            definition=definition,
            spec=spec,
            secret_resolver=secret_resolver,
        )
        self._resolver = resolver
        self._allow_private_hosts = frozenset(allow_private_hosts)

    def _validate_provider_configuration(
        self, configuration: Mapping[str, object]
    ) -> None:
        prefix = configuration.get("objectPrefix", "")
        if (
            not isinstance(prefix, str)
            or prefix.startswith("/")
            or ".." in prefix.split("/")
        ):
            raise ConnectorAdapterError(
                "OBJECT_PREFIX_INVALID",
                "Object prefix must be relative and must not contain traversal.",
                stage="validate",
            )
        _integer(configuration, "maxObjects", 1_000)
        _integer(configuration, "maxObjectBytes", 10 * 1024 * 1024)
        _integer(configuration, "timeoutSeconds", 30)
        endpoint = configuration.get("endpoint")
        if endpoint is not None:
            if (
                not isinstance(endpoint, str)
                or urlsplit(endpoint).scheme not in {"http", "https"}
                or not urlsplit(endpoint).hostname
                or urlsplit(endpoint).username
                or urlsplit(endpoint).password
            ):
                raise ConnectorAdapterError(
                    "OBJECT_ENDPOINT_INVALID",
                    (
                        "Object storage endpoint must be an absolute HTTP(S) "
                        "URL without credentials."
                    ),
                    stage="validate",
                )
            try:
                validate_network_endpoint(
                    endpoint,
                    resolver=self._resolver,
                    allow_private_hosts=self._allow_private_hosts,
                )
            except (OSError, ValueError) as error:
                raise ConnectorAdapterError(
                    "OBJECT_ENDPOINT_FORBIDDEN",
                    str(error),
                    stage="validate",
                ) from error

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.authenticate(request)
        try:
            resources = (
                self._s3_resources(request)
                if self.definition.connector_key == "s3"
                else self._oss_resources(request)
            )
        except ConnectorAdapterError:
            raise
        except Exception as error:
            raise _provider_failure(
                self.definition.name, "OBJECT_DISCOVERY_FAILED", "discover", error
            ) from error
        return succeeded_operation(
            "discover",
            request,
            code="OBJECTS_DISCOVERED",
            message="Allowlisted object keys were discovered.",
            resources=resources,
        )

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        self.authenticate(request)
        if request.resource is None:
            raise ConnectorAdapterError(
                "OBJECT_RESOURCE_REQUIRED",
                "Select one discovered object.",
                stage="read",
            )
        try:
            if self.definition.connector_key == "s3":
                content, checkpoint, media_type = self._s3_read(request)
            else:
                content, checkpoint, media_type = self._oss_read(request)
            rows = _object_rows(request.resource.name, content, media_type)
        except ConnectorAdapterError:
            raise
        except Exception as error:
            raise _provider_failure(
                self.definition.name, "OBJECT_READ_FAILED", "read", error
            ) from error
        return _read_result(
            connector_key=self.definition.connector_key,
            source_type=_object_source_type(request.resource.name, media_type),
            locator=f"{self.definition.connector_key}://{request.configuration['bucket']}/{request.resource.name}",
            rows=rows,
            raw_content=content,
            media_type=_object_media_type(request.resource.name, media_type),
            checkpoint=checkpoint,
        )

    def _s3_client(self, request: ConnectorRequest):
        module = self._load_driver()
        config_module = importlib.import_module("botocore.config")
        credentials = self._credentials(request)
        timeout = _integer(request.configuration, "timeoutSeconds", 30)
        return module.client(
            "s3",
            aws_access_key_id=credentials["accessKeyId"],
            aws_secret_access_key=credentials["secretAccessKey"],
            aws_session_token=credentials.get("sessionToken"),
            region_name=request.configuration.get("region"),
            endpoint_url=request.configuration.get("endpoint"),
            config=config_module.Config(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": 0},
                s3={"addressing_style": "path"},
            ),
        )

    def _s3_resources(self, request: ConnectorRequest) -> list[DiscoveredResource]:
        client = self._s3_client(request)
        pinned = self._pin_endpoint(request, stage="discover")
        try:
            paginator = client.get_paginator("list_objects_v2")
            resources = []
            max_objects = _integer(request.configuration, "maxObjects", 1_000)
            for page in paginator.paginate(
                Bucket=request.configuration["bucket"],
                Prefix=request.configuration.get("objectPrefix", ""),
                PaginationConfig={"MaxItems": max_objects},
            ):
                for item in page.get("Contents", []):
                    key = str(item["Key"])
                    resources.append(_object_resource("s3", key, int(item["Size"])))
                    if len(resources) >= max_objects:
                        self._verify_endpoint_pin(
                            request, pinned=pinned, stage="discover"
                        )
                        return resources
            self._verify_endpoint_pin(request, pinned=pinned, stage="discover")
            return resources
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _s3_read(self, request: ConnectorRequest) -> tuple[bytes, dict[str, str], str]:
        client = self._s3_client(request)
        resource = request.resource
        assert resource is not None
        self._require_object(request, resource.name)
        pinned = self._pin_endpoint(request, stage="read")
        body = None
        try:
            response = client.get_object(
                Bucket=request.configuration["bucket"], Key=resource.name
            )
            body = response["Body"]
            maximum = _integer(
                request.configuration, "maxObjectBytes", 10 * 1024 * 1024
            )
            content = body.read(maximum + 1)
            if len(content) > maximum:
                raise ConnectorAdapterError(
                    "OBJECT_SIZE_LIMIT",
                    "Object exceeds the configured byte limit.",
                    stage="read",
                )
            checkpoint = {
                key: str(value)
                for key, value in {
                    "etag": response.get("ETag"),
                    "versionId": response.get("VersionId"),
                }.items()
                if value
            }
            self._verify_endpoint_pin(request, pinned=pinned, stage="read")
            return (
                content,
                checkpoint,
                str(response.get("ContentType") or "application/octet-stream"),
            )
        finally:
            close_body = getattr(body, "close", None)
            if callable(close_body):
                close_body()
            close_client = getattr(client, "close", None)
            if callable(close_client):
                close_client()

    def _oss_bucket(self, request: ConnectorRequest):
        module = self._load_driver()
        credentials = self._credentials(request)
        auth = module.Auth(credentials["accessKeyId"], credentials["accessKeySecret"])
        return module.Bucket(
            auth,
            request.configuration["endpoint"],
            request.configuration["bucket"],
            connect_timeout=_integer(request.configuration, "timeoutSeconds", 30),
        )

    def _oss_resources(self, request: ConnectorRequest) -> list[DiscoveredResource]:
        module = self._load_driver()
        bucket = self._oss_bucket(request)
        pinned = self._pin_endpoint(request, stage="discover")
        resources = []
        maximum = _integer(request.configuration, "maxObjects", 1_000)
        for item in module.ObjectIterator(
            bucket, prefix=request.configuration.get("objectPrefix", "")
        ):
            resources.append(_object_resource("oss", item.key, int(item.size)))
            if len(resources) >= maximum:
                break
        self._verify_endpoint_pin(request, pinned=pinned, stage="discover")
        return resources

    def _oss_read(self, request: ConnectorRequest) -> tuple[bytes, dict[str, str], str]:
        bucket = self._oss_bucket(request)
        resource = request.resource
        assert resource is not None
        self._require_object(request, resource.name)
        pinned = self._pin_endpoint(request, stage="read")
        response = bucket.get_object(resource.name)
        try:
            maximum = _integer(
                request.configuration, "maxObjectBytes", 10 * 1024 * 1024
            )
            content = response.read(maximum + 1)
            if len(content) > maximum:
                raise ConnectorAdapterError(
                    "OBJECT_SIZE_LIMIT",
                    "Object exceeds the configured byte limit.",
                    stage="read",
                )
            self._verify_endpoint_pin(request, pinned=pinned, stage="read")
            return (
                content,
                {"etag": str(response.etag)},
                str(response.headers.get("Content-Type", "application/octet-stream")),
            )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _effective_endpoint(self, request: ConnectorRequest) -> str:
        endpoint = request.configuration.get("endpoint")
        if isinstance(endpoint, str) and endpoint:
            return endpoint
        region = request.configuration.get("region")
        host = f"s3.{region}.amazonaws.com" if region else "s3.amazonaws.com"
        return f"https://{host}"

    def _pin_endpoint(
        self, request: ConnectorRequest, *, stage: ConnectorStage
    ) -> frozenset[str]:
        try:
            return validate_network_endpoint(
                self._effective_endpoint(request),
                resolver=self._resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
        except (OSError, ValueError) as error:
            raise ConnectorAdapterError(
                "OBJECT_ENDPOINT_FORBIDDEN",
                "Object storage endpoint failed the network safety policy.",
                stage=stage,
            ) from error

    def _verify_endpoint_pin(
        self,
        request: ConnectorRequest,
        *,
        pinned: frozenset[str],
        stage: ConnectorStage,
    ) -> None:
        try:
            current = validate_network_endpoint(
                self._effective_endpoint(request),
                resolver=self._resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
        except (OSError, ValueError) as error:
            raise ConnectorAdapterError(
                "OBJECT_DNS_REBINDING",
                "Object storage endpoint resolution changed during the request.",
                stage=stage,
            ) from error
        if current != pinned:
            raise ConnectorAdapterError(
                "OBJECT_DNS_REBINDING",
                "Object storage endpoint resolution changed during the request.",
                stage=stage,
            )

    @staticmethod
    def _require_object(request: ConnectorRequest, key: str) -> None:
        prefix = str(request.configuration.get("objectPrefix") or "")
        if (
            not key
            or key.startswith("/")
            or ".." in key.split("/")
            or not key.startswith(prefix)
        ):
            raise ConnectorAdapterError(
                "OBJECT_RESOURCE_NOT_ALLOWED",
                "Object key is outside the configured prefix.",
                stage="authorize",
            )


class KafkaConnectorAdapter(ProviderConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        spec: ProviderSpec,
        secret_resolver: Callable[[str], str | None],
        resolver: Callable[[str], list[str]] | None,
        allow_private_hosts: set[str],
    ) -> None:
        super().__init__(
            definition=definition,
            spec=spec,
            secret_resolver=secret_resolver,
        )
        self._resolver = resolver
        self._allow_private_hosts = frozenset(allow_private_hosts)

    def _validate_provider_configuration(
        self, configuration: Mapping[str, object]
    ) -> None:
        _integer(configuration, "maxMessages", 1_000)
        _integer(configuration, "maxMessageBytes", 1_000_000)
        _integer(configuration, "timeoutSeconds", 30)
        self._broker_addresses(configuration, stage="validate")

    def _consumer(self, request: ConnectorRequest):
        module = self._load_driver()
        credentials = self._credentials(request)
        timeout_ms = _integer(request.configuration, "timeoutSeconds", 30) * 1_000
        values = {
            "bootstrap.servers": ",".join(
                cast(list[str], request.configuration["bootstrapServers"])
            ),
            "group.id": request.configuration["consumerGroup"],
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "socket.timeout.ms": timeout_ms,
            "request.timeout.ms": timeout_ms,
            **{str(key): value for key, value in credentials.items()},
        }
        return module.Consumer(values)

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.authenticate(request)
        pinned = self._broker_addresses(request.configuration, stage="discover")
        consumer = self._consumer(request)
        try:
            metadata = consumer.list_topics(
                timeout=_integer(request.configuration, "timeoutSeconds", 30)
            )
            allowed = cast(list[str], request.configuration["topics"])
            resources = [
                DiscoveredResource(
                    id=_resource_id("kafka", "topic", topic),
                    name=topic,
                    resource_type="operation",
                )
                for topic in allowed
                if topic in metadata.topics
            ]
            self._verify_broker_addresses(
                request.configuration, pinned=pinned, stage="discover"
            )
        except Exception as error:
            raise _provider_failure(
                "Kafka", "KAFKA_DISCOVERY_FAILED", "discover", error
            ) from error
        finally:
            consumer.close()
        if not resources:
            raise ConnectorAdapterError(
                "KAFKA_TOPIC_NOT_FOUND",
                "Kafka topic allowlist matched no readable topics.",
                stage="discover",
            )
        return succeeded_operation(
            "discover",
            request,
            code="KAFKA_TOPICS_DISCOVERED",
            message="Allowlisted Kafka topics were discovered.",
            resources=resources,
        )

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        self.authenticate(request)
        resource = request.resource
        topics = _string_list(request.configuration, "topics")
        if resource is None or resource.name not in topics:
            raise ConnectorAdapterError(
                "KAFKA_TOPIC_NOT_ALLOWED",
                "Kafka topic is outside the configured allowlist.",
                stage="authorize",
            )
        consumer = self._consumer(request)
        pinned = self._broker_addresses(request.configuration, stage="read")
        rows: list[dict[str, object]] = []
        checkpoints: dict[str, str] = {}
        maximum = _integer(request.configuration, "maxMessages", 1_000)
        max_bytes = _integer(request.configuration, "maxMessageBytes", 1_000_000)
        total = 0
        try:
            consumer.subscribe([resource.name])
            timeout = _integer(request.configuration, "timeoutSeconds", 30)
            for _ in range(maximum):
                message = consumer.poll(timeout=min(timeout, 1))
                if message is None:
                    break
                if message.error():
                    raise RuntimeError(str(message.error()))
                value = message.value() or b""
                total += len(value)
                if total > max_bytes:
                    raise ConnectorAdapterError(
                        "KAFKA_OUTPUT_LIMIT",
                        "Kafka messages exceed the configured byte limit.",
                        stage="read",
                    )
                decoded = json.loads(value)
                rows.append(
                    decoded if isinstance(decoded, dict) else {"value": decoded}
                )
                checkpoints[f"{message.topic()}:{message.partition()}"] = str(
                    message.offset()
                )
            self._verify_broker_addresses(
                request.configuration, pinned=pinned, stage="read"
            )
        except ConnectorAdapterError:
            raise
        except Exception as error:
            raise _provider_failure(
                "Kafka", "KAFKA_READ_FAILED", "read", error
            ) from error
        finally:
            consumer.close()
        return _read_result(
            connector_key="kafka",
            source_type="json",
            locator=f"kafka://{resource.name}",
            rows=rows,
            checkpoint=checkpoints,
        )

    def _broker_addresses(
        self,
        configuration: Mapping[str, object],
        *,
        stage: ConnectorStage,
    ) -> dict[str, frozenset[str]]:
        servers = configuration.get("bootstrapServers")
        if not isinstance(servers, list) or not servers:
            raise ConnectorAdapterError(
                "KAFKA_BROKER_INVALID",
                "Kafka bootstrapServers must contain host:port entries.",
                stage=stage,
            )
        addresses: dict[str, frozenset[str]] = {}
        for value in servers:
            try:
                host, port = _parse_kafka_broker(value)
                addresses[f"{host}:{port}"] = validate_network_endpoint(
                    _network_endpoint(host, port),
                    resolver=self._resolver,
                    allow_private_hosts=self._allow_private_hosts,
                )
            except (OSError, ValueError) as error:
                code = (
                    "KAFKA_BROKER_INVALID"
                    if "host:port" in str(error)
                    else "KAFKA_BROKER_FORBIDDEN"
                )
                raise ConnectorAdapterError(
                    code,
                    (
                        "Kafka bootstrap server is invalid."
                        if code == "KAFKA_BROKER_INVALID"
                        else "Kafka broker failed the network safety policy."
                    ),
                    stage=stage,
                ) from error
        return addresses

    def _verify_broker_addresses(
        self,
        configuration: Mapping[str, object],
        *,
        pinned: dict[str, frozenset[str]],
        stage: ConnectorStage,
    ) -> None:
        try:
            current = self._broker_addresses(configuration, stage=stage)
        except ConnectorAdapterError as error:
            raise ConnectorAdapterError(
                "KAFKA_DNS_REBINDING",
                "Kafka broker resolution changed during the request.",
                stage=stage,
            ) from error
        if current != pinned:
            raise ConnectorAdapterError(
                "KAFKA_DNS_REBINDING",
                "Kafka broker resolution changed during the request.",
                stage=stage,
            )


class LarkOfficeConnectorAdapter(ProviderConnectorAdapter):
    """Lark OpenAPI adapter with ACL-preserving user-token reads."""

    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        spec: ProviderSpec,
        secret_resolver: Callable[[str], str | None],
        transport: SecureHttpTransport,
    ) -> None:
        super().__init__(
            definition=definition,
            spec=spec,
            secret_resolver=secret_resolver,
        )
        self._http = transport

    def _load_driver(self) -> ModuleType:
        # Lark OpenAPI is an HTTPS protocol; no optional Python SDK is required.
        return ModuleType("https")

    def _validate_provider_configuration(
        self, configuration: Mapping[str, object]
    ) -> None:
        _integer(configuration, "pageSize", 100)
        _integer(configuration, "maxPages", 10)
        _integer(configuration, "maxResponseBytes", 5 * 1024 * 1024)
        _integer(configuration, "timeoutSeconds", 30)
        _integer(configuration, "rateLimitPerMinute", 60)
        _integer(configuration, "refreshSeconds", 3_600)
        key = self.definition.connector_key
        if key == "lark_meeting":
            try:
                start = date.fromisoformat(str(configuration["dateFrom"]))
                end = date.fromisoformat(str(configuration["dateTo"]))
            except (KeyError, ValueError) as error:
                raise ConnectorAdapterError(
                    "LARK_DATE_RANGE_INVALID",
                    "Meeting dateFrom/dateTo must be ISO calendar dates.",
                    stage="validate",
                ) from error
            if start > end or (
                _lark_meeting_window(configuration)[1]
                - _lark_meeting_window(configuration)[0]
                >= 40 * 24 * 60 * 60
            ):
                raise ConnectorAdapterError(
                    "LARK_DATE_RANGE_INVALID",
                    "Meeting date range must be ordered and shorter than 40 days.",
                    stage="validate",
                )
        if key in {"lark_group", "lark_chat"}:
            value = configuration.get("timeRange")
            match = re.fullmatch(
                r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?",
                str(value or ""),
            )
            if not match or not any(int(item or "0") > 0 for item in match.groups()):
                raise ConnectorAdapterError(
                    "LARK_TIME_RANGE_INVALID",
                    "Chat timeRange must be a positive ISO-8601 day/hour/minute duration.",
                    stage="validate",
                )
        if key == "lark_sheet":
            _lark_cell_range(configuration.get("cellRange", "A1:Z1000"))

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.authenticate(request)
        if self.definition.connector_key == "lark_sheet":
            return self._discover_sheet(request)
        read = self._fetch(request)
        name = _lark_resource_ref(self.definition.connector_key, request.configuration)
        resource = DiscoveredResource(
            id=_resource_id("lark", self.definition.connector_key, name),
            name=name,
            resource_type=(
                "table"
                if self.definition.connector_key in {"lark_sheet", "lark_base"}
                else "document"
            ),
            row_count=len(read.rows),
            fields=[
                DiscoveredField(name=field, data_type=kind, nullable=nullable)
                for field, kind, nullable in read.fields
            ],
        )
        return succeeded_operation(
            "discover",
            request,
            code="LARK_RESOURCE_DISCOVERED",
            message="Lark returned the resource under the caller's inherited ACL.",
            resources=[resource],
        )

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        self.authenticate(request)
        if self.definition.connector_key == "lark_sheet":
            return self._fetch_sheet(request)
        return self._fetch(request)

    def _discover_sheet(self, request: ConnectorRequest) -> ConnectorOperation:
        token = _reference_token(request.configuration["sheetRef"])
        endpoint = _lark_endpoint("lark_sheet", request.configuration)
        envelope = self._lark_json_request(
            request,
            method="GET",
            endpoint=endpoint,
        )
        data = envelope.get("data")
        sheets = data.get("sheets") if isinstance(data, dict) else None
        if not isinstance(sheets, list):
            raise ConnectorAdapterError(
                "LARK_RESPONSE_INVALID",
                "Lark spreadsheet metadata did not contain a sheet list.",
                stage="discover",
            )
        selected_name = request.configuration.get("sheetName")
        resources: list[DiscoveredResource] = []
        for value in sheets:
            if not isinstance(value, dict):
                continue
            sheet_id = value.get("sheet_id")
            title = value.get("title")
            if (
                not isinstance(sheet_id, str)
                or not sheet_id
                or not isinstance(title, str)
                or not title
                or selected_name
                and title != selected_name
            ):
                continue
            grid = value.get("grid_properties")
            row_count = grid.get("row_count") if isinstance(grid, dict) else None
            resources.append(
                DiscoveredResource(
                    id=_resource_id("lark_sheet", token, sheet_id),
                    name=title,
                    schema_name=sheet_id,
                    resource_type="table",
                    row_count=(
                        int(row_count)
                        if isinstance(row_count, int) and row_count >= 0
                        else None
                    ),
                )
            )
        if not resources:
            raise ConnectorAdapterError(
                "LARK_SHEET_NOT_FOUND",
                "No readable worksheet matched the configured sheet name.",
                stage="discover",
            )
        return succeeded_operation(
            "discover",
            request,
            code="LARK_RESOURCE_DISCOVERED",
            message="Lark returned the selected worksheets under the caller's ACL.",
            resources=resources,
        )

    def _fetch_sheet(self, request: ConnectorRequest) -> ConnectorReadResult:
        resource = request.resource
        if (
            resource is None
            or resource.resource_type != "table"
            or not resource.schema_name
        ):
            raise ConnectorAdapterError(
                "LARK_SHEET_RESOURCE_REQUIRED",
                "Select one discovered worksheet before reading cells.",
                stage="read",
            )
        token = quote(_reference_token(request.configuration["sheetRef"]), safe="")
        sheet_id = quote(resource.schema_name, safe="")
        cell_range = quote(
            _lark_cell_range(request.configuration.get("cellRange", "A1:Z1000")),
            safe=":",
        )
        base = str(
            request.configuration.get("apiBaseUrl")
            or "https://open.feishu.cn/open-apis"
        ).rstrip("/")
        endpoint = (
            f"{base}/sheets/v2/spreadsheets/{token}/values/{sheet_id}!{cell_range}"
        )
        envelope = self._lark_json_request(
            request,
            method="GET",
            endpoint=_with_query(
                endpoint,
                {
                    "valueRenderOption": "UnformattedValue",
                    "dateTimeRenderOption": "FormattedString",
                    "user_id_type": "open_id",
                },
            ),
        )
        data = envelope.get("data")
        value_range = data.get("valueRange") if isinstance(data, dict) else None
        values = value_range.get("values") if isinstance(value_range, dict) else None
        if not isinstance(values, list) or not all(
            isinstance(row, list) for row in values
        ):
            raise ConnectorAdapterError(
                "LARK_RESPONSE_INVALID",
                "Lark spreadsheet cell response did not contain row values.",
                stage="read",
            )
        rows = _sheet_rows(values)
        raw = json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        revision = (
            value_range.get("revision")
            if isinstance(value_range, dict)
            else data.get("revision")
            if isinstance(data, dict)
            else None
        )
        checkpoint = {"contentDigest": hashlib.sha256(raw).hexdigest()}
        if isinstance(revision, int):
            checkpoint["providerRevision"] = str(revision)
        return _read_result(
            connector_key="lark_sheet",
            source_type="office",
            locator=endpoint,
            rows=rows,
            raw_content=raw,
            checkpoint=checkpoint,
        )

    def _lark_json_request(
        self,
        request: ConnectorRequest,
        *,
        method: str,
        endpoint: str,
        body: object | None = None,
    ) -> dict[str, object]:
        credentials = self._credentials(request)
        try:
            payload = self._http.request(
                method=method,
                url=endpoint,
                trace_id=request.trace_id,
                timeout_seconds=_integer(request.configuration, "timeoutSeconds", 30),
                max_response_bytes=_integer(
                    request.configuration,
                    "maxResponseBytes",
                    5 * 1024 * 1024,
                ),
                rate_limit_per_minute=_integer(
                    request.configuration, "rateLimitPerMinute", 60
                ),
                accepted_media_types={"application/json", "*+json"},
                headers={"Authorization": f"Bearer {credentials['accessToken']}"},
                json_body=body,
            )
        except Exception as error:
            raise _lark_transport_error(error) from error
        try:
            envelope = json.loads(payload.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConnectorAdapterError(
                "LARK_RESPONSE_INVALID",
                "Lark OpenAPI returned invalid JSON.",
                stage="read",
            ) from error
        if not isinstance(envelope, dict):
            raise ConnectorAdapterError(
                "LARK_RESPONSE_INVALID",
                "Lark OpenAPI returned an invalid response envelope.",
                stage="read",
            )
        if envelope.get("code") not in {None, 0}:
            raise _lark_api_error(envelope)
        return {str(key): value for key, value in envelope.items()}

    def _fetch(self, request: ConnectorRequest) -> ConnectorReadResult:
        credentials = self._credentials(request)
        token = str(credentials["accessToken"])
        key = self.definition.connector_key
        endpoint = _lark_endpoint(key, request.configuration)
        max_pages = _integer(request.configuration, "maxPages", 10)
        max_bytes = _integer(request.configuration, "maxResponseBytes", 5 * 1024 * 1024)
        timeout = _integer(request.configuration, "timeoutSeconds", 30)
        rate = _integer(request.configuration, "rateLimitPerMinute", 60)
        rows: list[dict[str, object]] = []
        page_token = ""
        raw_pages: list[bytes] = []
        try:
            for _page in range(max_pages):
                method, current, body = _lark_request(
                    key,
                    request.configuration,
                    endpoint=endpoint,
                    page_token=page_token,
                    page_size=_integer(request.configuration, "pageSize", 100),
                )
                payload = self._http.request(
                    method=method,
                    url=current,
                    trace_id=request.trace_id,
                    timeout_seconds=timeout,
                    max_response_bytes=max(max_bytes - sum(map(len, raw_pages)), 1),
                    rate_limit_per_minute=rate,
                    accepted_media_types={"application/json", "*+json"},
                    headers={"Authorization": f"Bearer {token}"},
                    json_body=body,
                )
                raw_pages.append(payload.content)
                envelope = json.loads(payload.content)
                if not isinstance(envelope, dict) or envelope.get("code") not in {
                    None,
                    0,
                }:
                    raise _lark_api_error(envelope)
                data = envelope.get("data", envelope)
                page_rows, page_token, has_more = _lark_rows(data)
                if key in {"lark_group", "lark_chat"} and bool(
                    request.configuration.get("includeAttachments")
                ):
                    page_rows = [_with_attachment_metadata(row) for row in page_rows]
                if key == "lark_meeting":
                    page_rows = self._filter_meetings_by_attendee(request, page_rows)
                rows.extend(page_rows)
                if not has_more:
                    break
            else:
                raise ConnectorAdapterError(
                    "LARK_PAGINATION_LIMIT",
                    "Lark pagination exceeds the configured page limit.",
                    stage="read",
                )
        except ConnectorAdapterError:
            raise
        except Exception as error:
            message = str(error).casefold()
            if "status 404" in message or "not found" in message:
                raise ConnectorAdapterError(
                    "OFFICE_RESOURCE_DELETED",
                    "The Lark source no longer exists.",
                    stage="read",
                ) from error
            if "status 401" in message or "status 403" in message:
                raise ConnectorAdapterError(
                    "OFFICE_PERMISSION_REVOKED",
                    "Lark access was denied or revoked for this resource.",
                    stage="authorize",
                ) from error
            raise _provider_failure(
                self.definition.name, "LARK_READ_FAILED", "read", error
            ) from error
        raw = json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        if len(raw) > max_bytes:
            raise ConnectorAdapterError(
                "LARK_OUTPUT_LIMIT",
                "Lark content exceeds the configured byte limit.",
                stage="read",
            )
        checkpoint = {
            "contentDigest": hashlib.sha256(raw).hexdigest(),
            **({"pageToken": page_token} if page_token else {}),
        }
        return _read_result(
            connector_key=self.definition.connector_key,
            source_type="office",
            locator=endpoint,
            rows=rows,
            raw_content=raw,
            checkpoint=checkpoint,
        )

    def _filter_meetings_by_attendee(
        self,
        request: ConnectorRequest,
        rows: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        configured = request.configuration.get("attendees")
        if not isinstance(configured, list) or not configured:
            return rows
        expected = frozenset(str(value) for value in configured)
        base = str(
            request.configuration.get("apiBaseUrl")
            or "https://open.feishu.cn/open-apis"
        ).rstrip("/")
        calendar_id = quote(
            _reference_token(request.configuration["calendarRef"]), safe=""
        )
        page_size = min(_integer(request.configuration, "pageSize", 100), 100)
        max_pages = _integer(request.configuration, "maxPages", 10)
        selected: list[dict[str, object]] = []
        for row in rows:
            event_id = row.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise ConnectorAdapterError(
                    "LARK_RESPONSE_INVALID",
                    "Lark calendar returned an event without an event ID.",
                    stage="read",
                )
            endpoint = (
                f"{base}/calendar/v4/calendars/{calendar_id}/events/"
                f"{quote(event_id, safe='')}/attendees"
            )
            attendees: list[dict[str, object]] = []
            page_token = ""
            for _page in range(max_pages):
                envelope = self._lark_json_request(
                    request,
                    method="GET",
                    endpoint=_with_query(
                        endpoint,
                        {
                            "page_size": str(page_size),
                            "user_id_type": "open_id",
                            **({"page_token": page_token} if page_token else {}),
                        },
                    ),
                )
                data = envelope.get("data", envelope)
                page_rows, page_token, has_more = _lark_rows(data)
                attendees.extend(page_rows)
                if not has_more:
                    break
            else:
                raise ConnectorAdapterError(
                    "LARK_PAGINATION_LIMIT",
                    "Lark attendee pagination exceeds the configured page limit.",
                    stage="read",
                )
            identifiers = {
                str(attendee[field])
                for attendee in attendees
                for field in (
                    "user_id",
                    "chat_id",
                    "room_id",
                    "third_party_email",
                )
                if attendee.get(field)
            }
            if expected.issubset(identifiers):
                selected.append({**row, "attendees": attendees})
        return selected


def provider_specifications() -> dict[str, ProviderSpec]:
    database_defaults = {
        "required_secret_fields": ("username", "password"),
        "checkpoint": "content digest plus discovered schema digest",
    }
    return {
        "oracle": ProviderSpec(
            "oracledb",
            "python-oracledb",
            "uv pip install oracledb",
            _verification_command("oracle"),
            "Oracle DSN and a read-only username/password secret are required.",
            **database_defaults,
        ),
        "sqlserver": ProviderSpec(
            "pyodbc",
            "pyodbc",
            "uv pip install pyodbc",
            _verification_command("sqlserver"),
            "SQL Server endpoint, ODBC Driver 18, and read-only credentials are required.",
            **database_defaults,
        ),
        "clickhouse": ProviderSpec(
            "clickhouse_connect",
            "clickhouse-connect",
            "uv pip install clickhouse-connect",
            _verification_command("clickhouse"),
            "ClickHouse endpoint and read-only credentials are required.",
            **database_defaults,
        ),
        "doris": ProviderSpec(
            "pymysql",
            "PyMySQL",
            "uv pip install pymysql",
            _verification_command("doris"),
            "Doris MySQL endpoint and read-only credentials are required.",
            **database_defaults,
        ),
        "starrocks": ProviderSpec(
            "pymysql",
            "PyMySQL",
            "uv pip install pymysql",
            _verification_command("starrocks"),
            "StarRocks MySQL endpoint and read-only credentials are required.",
            **database_defaults,
        ),
        "snowflake": ProviderSpec(
            "snowflake.connector",
            "snowflake-connector-python",
            "uv pip install snowflake-connector-python",
            _verification_command("snowflake"),
            "Snowflake account/warehouse and read-only credentials are required.",
            **database_defaults,
        ),
        "bigquery": ProviderSpec(
            "google.cloud.bigquery",
            "google-cloud-bigquery",
            "uv pip install google-cloud-bigquery",
            _verification_command("bigquery"),
            "A BigQuery service-account secret with dataset read permission is required.",
            (
                "type",
                "project_id",
                "private_key_id",
                "private_key",
                "client_email",
                "client_id",
                "token_uri",
            ),
            "query job id plus content digest",
        ),
        "hive": ProviderSpec(
            "pyhive.hive",
            "PyHive",
            "uv pip install 'PyHive[hive]'",
            _verification_command("hive"),
            "HiveServer2 endpoint and read-only credentials are required.",
            **database_defaults,
        ),
        "s3": ProviderSpec(
            "boto3",
            "boto3",
            "uv pip install boto3",
            _verification_command("s3"),
            "An AWS credential secret with ListBucket/GetObject is required.",
            ("accessKeyId", "secretAccessKey"),
            "ETag and VersionId",
        ),
        "oss": ProviderSpec(
            "oss2",
            "oss2",
            "uv pip install oss2",
            _verification_command("oss"),
            "An OSS endpoint and credential secret with list/get permission are required.",
            ("accessKeyId", "accessKeySecret"),
            "ETag",
        ),
        "kafka": ProviderSpec(
            "confluent_kafka",
            "confluent-kafka",
            "uv pip install confluent-kafka",
            _verification_command("kafka"),
            "Kafka brokers and a consumer credential/config secret are required.",
            (),
            "topic-partition offsets",
        ),
    }


def lark_provider_spec(key: str) -> ProviderSpec:
    return ProviderSpec(
        driver="https",
        package="Lark OpenAPI",
        install_command='python -c "import httpx; print(httpx.__version__)"',
        verification_command=_verification_command(key),
        missing_condition=(
            f"A user access token with the catalog scopes and access to {key} is required."
        ),
        required_secret_fields=("accessToken",),
        checkpoint="provider page token plus content digest",
    )


def _verification_command(key: str) -> str:
    return (
        "STEP3B_CONNECTOR_CONFIGURATION_JSON='<json>' "
        "STEP3B_CONNECTOR_SECRET_JSON='<secret-json>' "
        "python -m "
        "frontend.server.knowledge_assets.sources_golden.provider_verify "
        f"{key}"
    )


def _database_allowlists(
    configuration: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    schemas = configuration.get("schemaAllowlist")
    tables = configuration.get("tableAllowlist")
    if (
        not isinstance(schemas, list)
        or not schemas
        or not all(
            isinstance(item, str) and _IDENTIFIER.fullmatch(item) for item in schemas
        )
    ):
        raise ConnectorAdapterError(
            "DATABASE_SCHEMA_ALLOWLIST_INVALID",
            "Database schemaAllowlist must contain valid identifiers.",
            stage="validate",
        )
    if (
        not isinstance(tables, list)
        or not tables
        or not all(
            isinstance(item, str) and _IDENTIFIER.fullmatch(item) for item in tables
        )
    ):
        raise ConnectorAdapterError(
            "DATABASE_TABLE_ALLOWLIST_INVALID",
            "Database tableAllowlist must contain valid identifiers.",
            stage="validate",
        )
    return list(dict.fromkeys(schemas)), list(dict.fromkeys(tables))


def _validate_query_allowlist(query: str, configuration: Mapping[str, object]) -> None:
    schemas, tables = _database_allowlists(configuration)
    references = re.findall(
        r"\b(?:FROM|JOIN)\s+"
        r"(?:(?:[`\"]?([A-Za-z_][A-Za-z0-9_$]*)[`\"]?)\.)?"
        r"(?:[`\"]?([A-Za-z_][A-Za-z0-9_$]*)[`\"]?)",
        query,
        flags=re.IGNORECASE,
    )
    if not references:
        raise ValueError("database query must read an allowlisted table")
    for schema, table in references:
        if table not in tables or schema and schema not in schemas:
            raise PermissionError(
                "database query references a table outside the configured allowlist"
            )


def _require_resource(
    configuration: Mapping[str, object], resource: DiscoveredResource
) -> None:
    schemas, tables = _database_allowlists(configuration)
    if resource.schema_name not in schemas or resource.name not in tables:
        raise ConnectorAdapterError(
            "DATABASE_RESOURCE_NOT_ALLOWED",
            "Database resource is outside the configured allowlists.",
            stage="authorize",
        )


def _metadata_resources(
    key: str,
    metadata: object,
    allowed_tables: list[str],
) -> list[DiscoveredResource]:
    grouped: dict[tuple[str, str], list[DiscoveredField]] = {}
    if not isinstance(metadata, Iterable):
        raise TypeError("database metadata must be iterable")
    for raw_row in metadata:
        if not hasattr(raw_row, "__getitem__") or not hasattr(raw_row, "__len__"):
            raise TypeError("database metadata row must be a sequence")
        row = list(raw_row)
        schema, table, field, data_type, *nullable = row
        if str(table) not in allowed_tables:
            continue
        grouped.setdefault((str(schema), str(table)), []).append(
            DiscoveredField(
                name=str(field),
                data_type=str(data_type).casefold(),
                nullable=not nullable
                or str(nullable[0]).casefold() in {"yes", "y", "true"},
            )
        )
    return [
        DiscoveredResource(
            id=_resource_id(key, schema, table),
            name=table,
            schema_name=schema,
            resource_type="table",
            fields=fields,
        )
        for (schema, table), fields in grouped.items()
    ]


def _quote(value: str | None, key: str) -> str:
    if value is None or not _IDENTIFIER.fullmatch(value):
        raise ConnectorAdapterError(
            "DATABASE_IDENTIFIER_INVALID",
            "Database identifier is invalid.",
            stage="validate",
        )
    if key == "sqlserver":
        return f"[{value}]"
    if key in {"doris", "starrocks", "hive"}:
        return f"`{value}`"
    return f'"{value}"'


def _qmark_query(
    query: str, parameters: Mapping[str, object]
) -> tuple[str, list[object]]:
    names = re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", query)
    return (
        re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", "?", query),
        [parameters[name] for name in names],
    )


def _format_query(
    query: str, parameters: Mapping[str, object]
) -> tuple[str, list[object]]:
    names = re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", query)
    return (
        re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", "%s", query),
        [parameters[name] for name in names],
    )


def _pyformat_query(query: str, parameters: Mapping[str, object]) -> str:
    return re.sub(
        r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)",
        lambda match: (
            f"%({match.group(1)})s" if match.group(1) in parameters else match.group(0)
        ),
        query,
    )


def _bigquery_bind_parameters(
    module: ModuleType,
    query: str,
    parameters: Mapping[str, object],
) -> tuple[str, list[object]]:
    names = re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", query)
    bound: list[object] = []
    for name in dict.fromkeys(names):
        value = parameters[name]
        if isinstance(value, bool):
            kind = "BOOL"
        elif isinstance(value, int):
            kind = "INT64"
        elif isinstance(value, float):
            kind = "FLOAT64"
        elif isinstance(value, str):
            kind = "STRING"
        else:
            raise ConnectorAdapterError(
                "DATABASE_PARAMETERS_INVALID",
                ("BigQuery named parameters must be non-null JSON scalar values."),
                stage="validate",
            )
        bound.append(module.ScalarQueryParameter(name, kind, value))
    return (
        re.sub(
            r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)",
            lambda match: f"@{match.group(1)}",
            query,
        ),
        bound,
    )


def _integer(configuration: Mapping[str, object], key: str, default: int) -> int:
    value = configuration.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConnectorAdapterError(
            "PROVIDER_LIMIT_INVALID",
            f"{key} must be a positive integer.",
            stage="validate",
        )
    return value


def _string_list(configuration: Mapping[str, object], key: str) -> list[str]:
    value = configuration.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ConnectorAdapterError(
            "PROVIDER_CONFIGURATION_INVALID",
            f"{key} must be a non-empty string list.",
            stage="validate",
        )
    return list(dict.fromkeys(value))


def _resource_id(provider: str, schema: str, name: str) -> str:
    return (
        "provider-resource-"
        + hashlib.sha256(f"{provider}:{schema}:{name}".encode()).hexdigest()[:24]
    )


def _read_result(
    *,
    connector_key: str,
    source_type: SourceType,
    locator: str,
    rows: list[dict[str, object]],
    raw_content: bytes | None = None,
    media_type: str = "application/json",
    checkpoint: dict[str, str] | None = None,
) -> ConnectorReadResult:
    raw = (
        raw_content
        or json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    digest = hashlib.sha256(raw).hexdigest()
    return ConnectorReadResult(
        source_type=source_type,
        source_locator=locator,
        raw_content=raw,
        rows=rows,
        fields=_infer_mapping_fields(rows),
        media_type=media_type,
        adapter_run_id=f"{connector_key}-run-{digest[:24]}",
        checkpoint=checkpoint or {"contentDigest": digest},
    )


def _enforce_rows(
    rows: list[dict[str, object]], *, limit: int, byte_limit: int
) -> list[dict[str, object]]:
    if len(rows) > limit:
        raise ConnectorAdapterError(
            "DATABASE_ROW_LIMIT",
            "Database result exceeds the configured row limit.",
            stage="read",
        )
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
    if len(raw) > byte_limit:
        raise ConnectorAdapterError(
            "DATABASE_BYTE_LIMIT",
            "Database result exceeds the configured byte limit.",
            stage="read",
        )
    return rows


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _object_resource(provider: str, key: str, size: int) -> DiscoveredResource:
    return DiscoveredResource(
        id=_resource_id(provider, "object", key),
        name=key,
        resource_type="file",
        row_count=None,
        fields=[DiscoveredField(name="content", data_type="string", nullable=False)],
        output_schema={"bytes": size},
    )


def _object_rows(key: str, content: bytes, media_type: str) -> list[dict[str, object]]:
    suffix = key.rsplit(".", 1)[-1].casefold() if "." in key else ""
    if media_type.endswith("json") or suffix in {"json", "jsonl", "ndjson"}:
        text = content.decode("utf-8")
        if suffix in {"jsonl", "ndjson"}:
            value = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            value = json.loads(text)
        rows = value if isinstance(value, list) else [value]
        if not all(isinstance(row, dict) for row in rows):
            raise ConnectorAdapterError(
                "OBJECT_FORMAT_INVALID",
                "JSON object storage content must contain row objects.",
                stage="read",
            )
        return [{str(name): item for name, item in row.items()} for row in rows]
    if media_type == "text/csv" or suffix == "csv":
        try:
            reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
            if not reader.fieldnames or any(not name for name in reader.fieldnames):
                raise ValueError("CSV header is required")
            return [{str(name): value for name, value in row.items()} for row in reader]
        except (UnicodeDecodeError, csv.Error, ValueError) as error:
            raise ConnectorAdapterError(
                "OBJECT_FORMAT_INVALID",
                "CSV object storage content is invalid.",
                stage="read",
            ) from error
    if media_type.startswith("text/") or suffix in {
        "txt",
        "md",
        "markdown",
        "html",
        "htm",
    }:
        return [
            {"text": line}
            for line in content.decode("utf-8").splitlines()
            if line.strip()
        ]
    raise ConnectorAdapterError(
        "OBJECT_FORMAT_UNSUPPORTED",
        "Object media type is not safe for direct ingestion.",
        stage="read",
    )


def _object_source_type(key: str, media_type: str) -> SourceType:
    suffix = key.rsplit(".", 1)[-1].casefold() if "." in key else ""
    if media_type.endswith("json") or suffix in {"json", "jsonl", "ndjson"}:
        return "json"
    if media_type == "text/csv" or suffix == "csv":
        return "csv"
    if media_type == "text/markdown" or suffix in {"md", "markdown"}:
        return "markdown"
    if media_type == "text/html" or suffix in {"html", "htm"}:
        return "html"
    return "text"


def _object_media_type(key: str, media_type: str) -> str:
    if media_type != "application/octet-stream":
        return media_type
    suffix = key.rsplit(".", 1)[-1].casefold() if "." in key else ""
    return {
        "csv": "text/csv",
        "json": "application/json",
        "jsonl": "application/x-ndjson",
        "ndjson": "application/x-ndjson",
        "md": "text/markdown",
        "markdown": "text/markdown",
        "html": "text/html",
        "htm": "text/html",
        "txt": "text/plain",
    }.get(suffix, media_type)


def _parse_kafka_broker(value: object) -> tuple[str, int]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Kafka broker must use host:port")
    raw = value.strip()
    if raw.startswith("["):
        closing = raw.find("]")
        if closing < 2 or closing + 1 >= len(raw) or raw[closing + 1] != ":":
            raise ValueError("Kafka broker must use [IPv6]:port")
        host = raw[1:closing]
        port_text = raw[closing + 2 :]
    else:
        if raw.count(":") != 1:
            raise ValueError("Kafka broker must use host:port")
        host, port_text = raw.rsplit(":", 1)
    if not host or not port_text.isdigit():
        raise ValueError("Kafka broker must use host:port")
    port = int(port_text)
    if port < 1 or port > 65_535:
        raise ValueError("Kafka broker port is invalid")
    return host, port


def _network_endpoint(host: str, port: int) -> str:
    bracketed = f"[{host}]" if ":" in host else host
    return f"https://{bracketed}:{port}"


def _lark_resource_ref(key: str, configuration: Mapping[str, object]) -> str:
    names = {
        "lark_doc": "documentRef",
        "lark_wiki": "wikiRef",
        "lark_drive": "folderRef",
        "lark_meeting": "calendarRef",
        "lark_minutes": "minutesRef",
        "lark_group": "chatRef",
        "lark_chat": "chatRef",
        "lark_sheet": "sheetRef",
        "lark_base": "tableRef",
        "lark_mail": "folder",
    }
    return str(configuration[names[key]])


def _reference_token(value: object) -> str:
    raw = str(value)
    parsed = urlsplit(raw)
    if parsed.scheme and parsed.netloc:
        query = parse_qs(parsed.query)
        for name in ("token", "document_id", "table_id", "sheet_id"):
            if query.get(name):
                return query[name][0]
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[-1]
    return raw


def _lark_endpoint(key: str, configuration: Mapping[str, object]) -> str:
    base = str(
        configuration.get("apiBaseUrl") or "https://open.feishu.cn/open-apis"
    ).rstrip("/")
    ref = quote(_reference_token(_lark_resource_ref(key, configuration)), safe="")
    if key == "lark_base":
        app = quote(_reference_token(configuration["appRef"]), safe="")
        path = f"/bitable/v1/apps/{app}/tables/{ref}/records"
    else:
        path = {
            "lark_doc": f"/docx/v1/documents/{ref}/raw_content",
            "lark_wiki": f"/wiki/v2/spaces/{ref}/nodes",
            "lark_drive": "/drive/v1/files",
            "lark_meeting": (f"/calendar/v4/calendars/{ref}/events/instance_view"),
            "lark_minutes": f"/minutes/v1/minutes/{ref}/transcript",
            "lark_group": "/im/v1/messages",
            "lark_chat": "/im/v1/messages",
            "lark_sheet": f"/sheets/v3/spreadsheets/{ref}/sheets/query",
            "lark_mail": "/mail/v1/user_mailboxes/me/search",
        }[key]
    endpoint = base + path
    if key == "lark_drive":
        endpoint = _with_query(endpoint, {"folder_token": ref})
    return endpoint


def _lark_request(
    key: str,
    configuration: Mapping[str, object],
    *,
    endpoint: str,
    page_token: str,
    page_size: int,
) -> tuple[str, str, object | None]:
    query = {
        "page_size": str(page_size),
        **({"page_token": page_token} if page_token else {}),
    }
    if key == "lark_meeting":
        start_time, end_time = _lark_meeting_window(configuration)
        return (
            "GET",
            _with_query(
                endpoint,
                {
                    "start_time": str(start_time),
                    "end_time": str(end_time),
                    "user_id_type": "open_id",
                },
            ),
            None,
        )
    if key in {"lark_group", "lark_chat"}:
        start, end = _lark_time_window(str(configuration["timeRange"]))
        return (
            "GET",
            _with_query(
                endpoint,
                {
                    **query,
                    "container_id_type": "chat",
                    "container_id": quote(
                        _reference_token(configuration["chatRef"]), safe=""
                    ),
                    "start_time": str(start),
                    "end_time": str(end),
                    "sort_type": "ByCreateTimeAsc",
                },
            ),
            None,
        )
    if key == "lark_sheet":
        sheet_name = configuration.get("sheetName")
        if isinstance(sheet_name, str) and sheet_name:
            query["sheet_name"] = sheet_name
    if key == "lark_base":
        view = configuration.get("viewRef")
        if isinstance(view, str) and view:
            query["view_id"] = _reference_token(view)
    if key == "lark_mail":
        body: dict[str, object] = {
            "filter": {"folder": [str(configuration["folder"]).casefold()]}
        }
        search = configuration.get("query")
        if isinstance(search, str) and search:
            body["query"] = search
        return "POST", _with_query(endpoint, query), body
    return "GET", _with_query(endpoint, query), None


def _lark_time_window(value: str) -> tuple[int, int]:
    match = re.fullmatch(
        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?",
        value,
    )
    if not match:
        raise ValueError("invalid Lark time range")
    days, hours, minutes = (int(item or "0") for item in match.groups())
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days, hours=hours, minutes=minutes)
    return int(start.timestamp()), int(end.timestamp())


def _lark_meeting_window(
    configuration: Mapping[str, object],
) -> tuple[int, int]:
    zone = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(
        date.fromisoformat(str(configuration["dateFrom"])),
        time.min,
        tzinfo=zone,
    )
    end = datetime.combine(
        date.fromisoformat(str(configuration["dateTo"])),
        time.max.replace(microsecond=0),
        tzinfo=zone,
    )
    return int(start.timestamp()), int(end.timestamp())


def _lark_cell_range(value: object) -> str:
    if not isinstance(value, str):
        raise ConnectorAdapterError(
            "LARK_SHEET_RANGE_INVALID",
            "Spreadsheet cellRange must be a bounded A1 range.",
            stage="validate",
        )
    match = re.fullmatch(
        r"([A-Za-z]{1,3})([1-9][0-9]{0,6}):"
        r"([A-Za-z]{1,3})([1-9][0-9]{0,6})",
        value,
    )
    if not match:
        raise ConnectorAdapterError(
            "LARK_SHEET_RANGE_INVALID",
            "Spreadsheet cellRange must be a bounded A1 range.",
            stage="validate",
        )
    start_column, start_row, end_column, end_row = match.groups()
    if (
        _column_number(start_column) > _column_number(end_column)
        or int(start_row) > int(end_row)
        or (_column_number(end_column) - _column_number(start_column) + 1)
        * (int(end_row) - int(start_row) + 1)
        > 100_000
    ):
        raise ConnectorAdapterError(
            "LARK_SHEET_RANGE_INVALID",
            "Spreadsheet cellRange is reversed or exceeds 100,000 cells.",
            stage="validate",
        )
    return value.upper()


def _column_number(value: str) -> int:
    result = 0
    for character in value.upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _sheet_rows(values: list[list[object]]) -> list[dict[str, object]]:
    if not values:
        return []
    width = max(len(row) for row in values)
    raw_headers = values[0]
    headers: list[str] = []
    used: dict[str, int] = {}
    for index in range(width):
        value = raw_headers[index] if index < len(raw_headers) else None
        base = str(value).strip() if value not in (None, "") else f"column_{index + 1}"
        occurrence = used.get(base, 0) + 1
        used[base] = occurrence
        headers.append(base if occurrence == 1 else f"{base}_{occurrence}")
    return [
        {
            header: _json_value(row[index]) if index < len(row) else None
            for index, header in enumerate(headers)
        }
        for row in values[1:]
        if any(value not in (None, "") for value in row)
    ]


def _with_attachment_metadata(row: dict[str, object]) -> dict[str, object]:
    body = row.get("body")
    content = body.get("content") if isinstance(body, dict) else None
    metadata: list[dict[str, str]] = []
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            for key in ("file_key", "image_key"):
                value = decoded.get(key)
                if isinstance(value, str) and value:
                    metadata.append({"type": key.removesuffix("_key"), "key": value})
    return {**row, "attachment_metadata": metadata}


def _lark_api_error(envelope: object) -> ConnectorAdapterError:
    code = envelope.get("code") if isinstance(envelope, dict) else None
    message = str(envelope.get("msg") or "") if isinstance(envelope, dict) else ""
    lowered = message.casefold()
    if code in {99991663, 99991668, 99991672} or any(
        marker in lowered for marker in ("permission", "forbidden", "access denied")
    ):
        return ConnectorAdapterError(
            "OFFICE_PERMISSION_REVOKED",
            "Lark access was denied or revoked for this resource.",
            stage="authorize",
        )
    if code in {1061003, 1061007, 1254043, 1254045, 234002, 14005} or any(
        marker in lowered for marker in ("not found", "has been delete", "deleted")
    ):
        return ConnectorAdapterError(
            "OFFICE_RESOURCE_DELETED",
            "The Lark source no longer exists.",
            stage="read",
        )
    return ConnectorAdapterError(
        "LARK_API_ERROR",
        "Lark OpenAPI returned an application error.",
        stage="read",
        retryable=True,
    )


def _lark_transport_error(error: Exception) -> ConnectorAdapterError:
    message = str(error).casefold()
    if "status 401" in message or "status 403" in message:
        return ConnectorAdapterError(
            "OFFICE_PERMISSION_REVOKED",
            "Lark access was denied or revoked for this resource.",
            stage="authorize",
        )
    if "status 404" in message or "not found" in message:
        return ConnectorAdapterError(
            "OFFICE_RESOURCE_DELETED",
            "The Lark source no longer exists.",
            stage="read",
        )
    if isinstance(error, TimeoutError):
        return ConnectorAdapterError(
            "LARK_TIMEOUT",
            "Lark OpenAPI did not respond within the configured timeout.",
            stage="read",
            retryable=True,
        )
    if "rate limit" in message:
        return ConnectorAdapterError(
            "LARK_RATE_LIMITED",
            "Lark OpenAPI rate limited the request.",
            stage="read",
            retryable=True,
        )
    if "byte limit" in message:
        return ConnectorAdapterError(
            "LARK_OUTPUT_LIMIT",
            "Lark content exceeds the configured byte limit.",
            stage="read",
        )
    return ConnectorAdapterError(
        "LARK_READ_FAILED",
        "Lark could not complete the provider operation.",
        stage="read",
        retryable=True,
    )


def _with_query(url: str, values: Mapping[str, str]) -> str:
    parsed = urlsplit(url)
    current = {key: item[-1] for key, item in parse_qs(parsed.query).items()}
    current.update(values)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(current), "")
    )


def _lark_rows(
    value: object,
) -> tuple[list[dict[str, object]], str, bool]:
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            rows = value["items"]
        elif isinstance(value.get("records"), list):
            rows = value["records"]
        elif isinstance(value.get("content"), str):
            rows = [{"text": value["content"]}]
        else:
            rows = [value]
        page_token = str(value.get("page_token") or "")
        has_more = bool(value.get("has_more"))
    else:
        rows = [value]
        page_token = ""
        has_more = False
    normalized = [row if isinstance(row, dict) else {"value": row} for row in rows]
    return (
        [{str(key): item for key, item in row.items()} for row in normalized],
        page_token,
        has_more,
    )


def _provider_failure(
    name: str,
    code: str,
    stage: ConnectorStage,
    error: Exception,
) -> ConnectorAdapterError:
    text = str(error).casefold()
    if any(
        marker in text
        for marker in (
            "unauthorized",
            "forbidden",
            "access denied",
            "authentication failed",
            "authorization failed",
            "sasl authentication",
        )
    ):
        return ConnectorAdapterError(
            "PROVIDER_PERMISSION_DENIED",
            f"{name} denied the requested read permission.",
            stage="authorize",
        )
    if "timed out" in text or "timeout" in text:
        return ConnectorAdapterError(
            "PROVIDER_TIMEOUT",
            f"{name} exceeded the configured timeout.",
            stage=stage,
            retryable=True,
        )
    return ConnectorAdapterError(
        code,
        f"{name} could not complete the provider operation.",
        stage=stage,
        retryable=True,
    )
