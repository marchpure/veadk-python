from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
from pydantic import JsonValue

from frontend.server.knowledge_assets.sources_golden import (
    SourceGoldenApplication,
    provider_adapters,
)
from frontend.server.knowledge_assets.sources_golden.connector_adapter import (
    ConnectorAdapterError,
    ConnectorReadCache,
    ConnectorRequest,
)
from frontend.server.knowledge_assets.sources_golden.mcp_remote import (
    RemoteMcpClient,
    RemoteMcpError,
)
from frontend.server.knowledge_assets.sources_golden.models import (
    DiscoveredResource,
    RemoteMcpExchange,
    RemoteMcpTrace,
)


def _application(
    tmp_path: Path,
    *,
    secret: dict[str, object],
) -> SourceGoldenApplication:
    return SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps(secret),
    )


def _bigquery_request() -> ConnectorRequest:
    return ConnectorRequest(
        connector_key="bigquery",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "projectId": "knowledge-project",
            "datasetId": "reporting",
            "schemaAllowlist": ["reporting"],
            "tableAllowlist": ["orders"],
            "pageSize": 50,
            "rowLimit": 100,
            "byteLimit": 100_000,
            "timeoutSeconds": 5,
        },
        secret_ref="secret://workspace-step3b/bigquery",
        trace_id="trace-bigquery",
    )


def test_bigquery_rejects_incomplete_service_account_before_loading_sdk(
    tmp_path: Path,
) -> None:
    adapter = _application(
        tmp_path,
        secret={
            "type": "service_account",
            "project_id": "knowledge-project",
            "client_email": "reader@example.invalid",
        },
    ).connector_adapters()["bigquery"]

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.authenticate(_bigquery_request())

    assert failure.value.code == "EXTERNAL_CREDENTIAL_INVALID"
    assert failure.value.stage == "authenticate"


def test_bigquery_binds_named_parameters_with_official_query_parameter_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class QueryJobConfig:
        query_parameters: list[ScalarQueryParameter]

        def __init__(self, **values: object) -> None:
            self.__dict__.update(values)

    class ScalarQueryParameter:
        def __init__(self, name: str, kind: str, value: object) -> None:
            self.name = name
            self.kind = kind
            self.value = value

    class QueryResult:
        def result(self, *, max_results: int):
            captured["max_results"] = max_results
            return [{"order_id": "A-1", "amount": 12}]

    class Client:
        def __init__(self, **values: object) -> None:
            captured["client"] = values

        def query(
            self,
            query: str,
            *,
            job_config: QueryJobConfig,
            timeout: int,
        ) -> QueryResult:
            captured["query"] = query
            captured["job_config"] = job_config
            captured["timeout"] = timeout
            return QueryResult()

        def close(self) -> None:
            captured["closed"] = True

    module = SimpleNamespace(
        Client=Client,
        QueryJobConfig=QueryJobConfig,
        ScalarQueryParameter=ScalarQueryParameter,
    )
    service_account = SimpleNamespace(
        Credentials=SimpleNamespace(
            from_service_account_info=lambda value: ("credential", value)
        )
    )
    real_import = provider_adapters.importlib.import_module
    monkeypatch.setattr(
        provider_adapters.importlib,
        "import_module",
        lambda name: (
            service_account
            if name == "google.oauth2.service_account"
            else real_import(name)
        ),
    )
    adapter = _application(
        tmp_path,
        secret={
            "type": "service_account",
            "project_id": "knowledge-project",
            "private_key_id": "key-id",
            "private_key": "runtime-private-key",
            "client_email": "reader@example.invalid",
            "client_id": "client-id",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    ).connector_adapters()["bigquery"]
    monkeypatch.setattr(adapter, "_load_driver", lambda: module)
    base = _bigquery_request()
    request = ConnectorRequest(
        **{
            **base.__dict__,
            "configuration": {
                **base.configuration,
                "query": (
                    "SELECT * FROM reporting.orders "
                    "WHERE amount >= :minimum AND active = :active"
                ),
                "queryParameters": {"minimum": 10, "active": True},
            },
            "resource": DiscoveredResource(
                id="orders",
                name="orders",
                schema_name="reporting",
                resource_type="table",
            ),
        }
    )

    result = adapter.read(request)

    assert result.rows == [{"order_id": "A-1", "amount": 12}]
    assert ":minimum" not in str(captured["query"])
    assert "@minimum" in str(captured["query"])
    job_config = captured["job_config"]
    assert isinstance(job_config, QueryJobConfig)
    assert [
        (parameter.name, parameter.kind, parameter.value)
        for parameter in job_config.query_parameters
    ] == [
        ("minimum", "INT64", 10),
        ("active", "BOOL", True),
    ]
    assert captured["timeout"] == 5
    assert captured["closed"] is True


@pytest.mark.parametrize("connector_key", ["doris", "starrocks"])
def test_mysql_protocol_warehouses_quote_default_reads_with_backticks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connector_key: str,
) -> None:
    captured: dict[str, object] = {}

    class Cursor:
        description = (("order_id",),)

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: str, parameters: object | None = None) -> None:
            if statement.startswith("SELECT * FROM"):
                captured["statement"] = statement
                captured["parameters"] = parameters

        def fetchmany(self, _size: int):
            if captured.get("fetched"):
                return []
            captured["fetched"] = True
            return [("A-1",)]

        def close(self) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            captured["closed"] = True

    adapter = _application(
        tmp_path,
        secret={"username": "reader", "password": "runtime-password"},
    ).connector_adapters()[connector_key]
    monkeypatch.setattr(adapter, "_load_driver", lambda: object())
    monkeypatch.setattr(adapter, "_connect", lambda _request: Connection())
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "host": "warehouse.example",
            "port": 9030,
            "database": "analytics",
            "schemaAllowlist": ["reporting"],
            "tableAllowlist": ["orders"],
            "pageSize": 50,
            "rowLimit": 100,
            "byteLimit": 100_000,
            "timeoutSeconds": 5,
        },
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}",
        resource=DiscoveredResource(
            id="orders",
            name="orders",
            schema_name="reporting",
            resource_type="table",
        ),
    )

    result = adapter.read(request)

    assert result.rows == [{"order_id": "A-1"}]
    assert "`reporting`.`orders`" in str(captured["statement"])
    assert '"reporting"."orders"' not in str(captured["statement"])
    assert captured["parameters"] == []
    assert captured["closed"] is True


@pytest.mark.parametrize("connector_key", ["doris", "starrocks"])
def test_mysql_protocol_warehouses_set_read_only_transaction_without_dialect_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connector_key: str,
) -> None:
    statements: list[str] = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: str, _parameters: object | None = None) -> None:
            statements.append(statement)
            if connector_key in {"doris", "starrocks"} and statement == "START TRANSACTION READ ONLY":
                raise AssertionError("Doris-family dialect-invalid transaction statement")

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    adapter = _application(
        tmp_path,
        secret={"username": "reader", "password": "runtime-password"},
    ).connector_adapters()[connector_key]
    connection = Connection()
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "host": "warehouse.example",
            "port": 9030,
            "database": "analytics",
            "schemaAllowlist": ["reporting"],
            "tableAllowlist": ["orders"],
        },
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}",
    )

    class Driver:
        @staticmethod
        def connect(**_kwargs: object) -> Connection:
            return connection

    # _connect is the only place that emits dialect-specific read-only
    # transaction setup; invoke it through the adapter's real implementation.
    monkeypatch.setattr(adapter, "_load_driver", lambda: Driver())
    adapter._connect(request)

    if connector_key in {"doris", "starrocks"}:
        assert statements == [
            "SET SESSION TRANSACTION READ ONLY",
            "SET TRANSACTION READ ONLY",
            "START TRANSACTION",
        ]


@pytest.mark.parametrize(
    ("auth", "expected_password"),
    [("NONE", False), ("LDAP", True), ("CUSTOM", True)],
)
def test_hive_connection_passes_password_only_for_password_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth: str,
    expected_password: bool,
) -> None:
    captured: dict[str, object] = {}

    class Driver:
        @staticmethod
        def Connection(**kwargs: object) -> object:
            captured.update(kwargs)
            return object()

    adapter = _application(
        tmp_path,
        secret={"username": "reader", "password": "runtime-password", "auth": auth},
    ).connector_adapters()["hive"]
    request = ConnectorRequest(
        connector_key="hive",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "host": "hive.example",
            "port": 10000,
            "database": "knowledge",
            "schemaAllowlist": ["knowledge"],
            "tableAllowlist": ["orders"],
        },
        secret_ref="secret://workspace-step3b/hive",
        trace_id=f"trace-hive-auth-{auth.casefold()}",
    )
    monkeypatch.setattr(adapter, "_load_driver", lambda: Driver())

    adapter._connect(request)

    assert captured["auth"] == auth
    assert captured["username"] == "reader"
    assert ("password" in captured) is expected_password


@pytest.mark.parametrize(
    ("connector_key", "expected_placeholder"),
    [("snowflake", "%(minimum)s"), ("hive", "%(minimum)s")],
)
def test_warehouse_named_parameters_use_the_driver_parameter_style(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connector_key: str,
    expected_placeholder: str,
) -> None:
    captured: dict[str, object] = {}

    class Cursor:
        description = (("amount",),)

        def execute(self, statement: str, parameters: object) -> None:
            captured["statement"] = statement
            captured["parameters"] = parameters

        def fetchmany(self, _size: int):
            if captured.get("fetched"):
                return []
            captured["fetched"] = True
            return [(12,)]

        def close(self) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            return None

    adapter = _application(
        tmp_path,
        secret={"username": "reader", "password": "runtime-password"},
    ).connector_adapters()[connector_key]
    monkeypatch.setattr(adapter, "_load_driver", lambda: object())
    monkeypatch.setattr(adapter, "_connect", lambda _request: Connection())
    common: dict[str, JsonValue] = {
        "database": "analytics",
        "schemaAllowlist": ["reporting"],
        "tableAllowlist": ["orders"],
        "query": (
            "SELECT amount FROM reporting.orders "
            "WHERE amount >= :minimum AND region = :region"
        ),
        "queryParameters": {"minimum": 10, "region": "north"},
        "pageSize": 50,
        "rowLimit": 100,
        "byteLimit": 100_000,
        "timeoutSeconds": 5,
    }
    configuration = (
        {
            **common,
            "account": "organization-account",
            "warehouse": "reporting",
        }
        if connector_key == "snowflake"
        else {**common, "host": "hive.example", "port": 10_000}
    )
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration=configuration,
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}",
        resource=DiscoveredResource(
            id="orders",
            name="orders",
            schema_name="reporting",
            resource_type="table",
        ),
    )

    result = adapter.read(request)

    assert result.rows == [{"amount": 12}]
    statement = str(captured["statement"])
    assert ":minimum" not in statement
    assert expected_placeholder in statement
    assert captured["parameters"] == {"minimum": 10, "region": "north"}


@pytest.mark.parametrize(
    "connector_key",
    ["oracle", "sqlserver", "clickhouse", "doris", "starrocks", "hive"],
)
def test_external_databases_reject_private_endpoint_without_allowlist(
    tmp_path: Path,
    connector_key: str,
) -> None:
    database: dict[str, JsonValue] = {
        "host": "database.example",
        "port": 443,
        "database": "analytics",
        "schemaAllowlist": ["reporting"],
        "tableAllowlist": ["orders"],
    }
    if connector_key == "oracle":
        database["serviceName"] = database.pop("database")
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["127.0.0.1"],
        secret_resolver=lambda _ref: json.dumps(
            {"username": "reader", "password": "runtime-password"}
        ),
    )
    adapter = application.connector_adapters()[connector_key]
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration=database,
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}-private-endpoint",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.discover(request)

    assert failure.value.code == "DATABASE_ENDPOINT_FORBIDDEN"
    assert failure.value.stage == "validate"


def test_oracle_read_uses_driver_safe_bound_parameter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["127.0.0.1"],
        network_allow_private_hosts={"127.0.0.1"},
        secret_resolver=lambda _ref: json.dumps(
            {"username": "reader", "password": "runtime-password"}
        ),
    )
    adapter = application.connector_adapters()["oracle"]
    captured: dict[str, object] = {}

    class Cursor:
        description = [("amount", "NUMBER", True)]
        fetched = False

        def execute(self, statement: str, parameters: object) -> None:
            captured["statement"] = statement
            captured["parameters"] = parameters

        def fetchmany(self, _size: int) -> list[tuple[int]]:
            if self.fetched:
                return []
            self.fetched = True
            return [(12,)]

        def close(self) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            return None

    monkeypatch.setattr(adapter, "_connect", lambda _request: Connection())
    monkeypatch.setattr(
        adapter,
        "_pin_endpoint",
        lambda _request, stage: frozenset({"127.0.0.1"}),
    )
    monkeypatch.setattr(
        adapter,
        "_verify_endpoint_pin",
        lambda request, pinned, stage: None,
    )
    request = ConnectorRequest(
        connector_key="oracle",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "host": "127.0.0.1",
            "port": 1521,
            "serviceName": "FREEPDB1",
            "schemaAllowlist": ["REPORTING"],
            "tableAllowlist": ["ORDERS"],
            "query": "SELECT * FROM REPORTING.ORDERS",
            "queryParameters": {},
            "rowLimit": 10,
            "pageSize": 10,
            "byteLimit": 10000,
            "timeoutSeconds": 5,
        },
        secret_ref="secret://workspace-step3b/oracle",
        trace_id="trace-oracle-bound",
        resource=DiscoveredResource(
            id="reporting.orders",
            name="ORDERS",
            schema_name="REPORTING",
            resource_type="table",
        ),
    )

    result = adapter.read(request)

    assert result.rows == [{"amount": 12}]
    assert "ROWNUM <= :adapter_limit" in str(captured["statement"])
    assert captured["parameters"]["adapter_limit"] == 11


def test_external_database_accepts_driver_row_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["127.0.0.1"],
        network_allow_private_hosts={"127.0.0.1"},
        secret_resolver=lambda _ref: json.dumps(
            {"username": "reader", "password": "runtime-password"}
        ),
    )
    adapter = application.connector_adapters()["sqlserver"]

    class DriverRow:
        def __init__(self, *values: object) -> None:
            self.values = values

        def __getitem__(self, index: int) -> object:
            return self.values[index]

        def __len__(self) -> int:
            return len(self.values)

    class Cursor:
        description = [("amount", "int", True)]
        finished = False

        def execute(self, statement: str, parameters: object) -> None:
            del statement, parameters

        def fetchall(self) -> list[DriverRow]:
            return [
                DriverRow("dbo", "ORDERS", "amount", "int", "NO"),
            ]

        def fetchmany(self, _size: int) -> list[DriverRow]:
            if self.finished:
                return []
            self.finished = True
            return [DriverRow(12)]

        def close(self) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            return None

    monkeypatch.setattr(adapter, "_connect", lambda _request: Connection())
    monkeypatch.setattr(
        adapter,
        "_pin_endpoint",
        lambda _request, stage: frozenset({"127.0.0.1"}),
    )
    monkeypatch.setattr(
        adapter,
        "_verify_endpoint_pin",
        lambda request, pinned, stage: None,
    )
    configuration = {
        "host": "127.0.0.1",
        "port": 1433,
        "database": "knowledge",
        "schemaAllowlist": ["dbo"],
        "tableAllowlist": ["ORDERS"],
        "query": "SELECT * FROM dbo.ORDERS",
        "queryParameters": {},
        "rowLimit": 10,
        "pageSize": 10,
        "byteLimit": 10000,
        "timeoutSeconds": 5,
    }
    request = ConnectorRequest(
        connector_key="sqlserver",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration=configuration,
        secret_ref="secret://workspace-step3b/sqlserver",
        trace_id="trace-sqlserver-row",
        resource=DiscoveredResource(
            id="dbo.orders",
            name="ORDERS",
            schema_name="dbo",
            resource_type="table",
        ),
    )

    # The adapter's driver loading and credential connection are outside this
    # seam; exercise the exact row-shape conversion used by discovery/read.
    discovery = adapter._discover(request)
    assert discovery[0].name == "ORDERS"
    result = adapter._read_rows(request)
    assert result == [{"amount": 12}]


@pytest.mark.parametrize(
    "connector_key",
    ["oracle", "sqlserver", "clickhouse", "doris", "starrocks", "hive"],
)
def test_external_databases_reject_dns_rebinding_during_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connector_key: str,
) -> None:
    resolutions = iter(
        [
            ["93.184.216.34"],
            ["93.184.216.34"],
            ["93.184.216.35"],
        ]
    )
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: next(resolutions),
        secret_resolver=lambda _ref: json.dumps(
            {"username": "reader", "password": "runtime-password"}
        ),
    )
    adapter = application.connector_adapters()[connector_key]
    monkeypatch.setattr(adapter, "_load_driver", lambda: object())
    monkeypatch.setattr(
        adapter,
        "_discover",
        lambda _request: [
            DiscoveredResource(
                id="reporting.orders",
                name="orders",
                schema_name="reporting",
                resource_type="table",
            )
        ],
    )
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "host": "database.example",
            "port": 1521 if connector_key == "oracle" else 443,
            **(
                {"serviceName": "ORCL"}
                if connector_key == "oracle"
                else {"database": "analytics"}
            ),
            "schemaAllowlist": ["reporting"],
            "tableAllowlist": ["orders"],
        },
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}-rebinding",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.discover(request)

    assert failure.value.code == "DATABASE_DNS_REBINDING"
    assert failure.value.stage == "discover"


@pytest.mark.parametrize("connector_key", ["s3", "oss"])
def test_object_storage_rejects_private_endpoint_resolution(
    tmp_path: Path,
    connector_key: str,
) -> None:
    configuration = {
        "bucket": "knowledge-data",
        "objectPrefix": "safe/",
        "endpoint": "https://storage.example",
        "maxObjects": 100,
        "maxObjectBytes": 100_000,
        "timeoutSeconds": 5,
    }
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["127.0.0.1"],
    )
    adapter = application.connector_adapters()[connector_key]
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration=configuration,
        secret_ref=None,
        trace_id=f"trace-{connector_key}-private-endpoint",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.validate(request)

    assert failure.value.code == "OBJECT_ENDPOINT_FORBIDDEN"
    assert failure.value.stage == "validate"


@pytest.mark.parametrize("connector_key", ["s3", "oss"])
def test_object_storage_maps_dns_failure_to_typed_validation_error(
    tmp_path: Path,
    connector_key: str,
) -> None:
    def unavailable(_host: str) -> list[str]:
        raise OSError("fixture DNS unavailable")

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=unavailable,
    )
    adapter = application.connector_adapters()[connector_key]
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "bucket": "knowledge-data",
            "objectPrefix": "safe/",
            "endpoint": "https://storage.example",
        },
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}-dns-unavailable",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.validate(request)

    assert failure.value.code == "OBJECT_ENDPOINT_FORBIDDEN"
    assert failure.value.stage == "validate"


def test_s3_read_rejects_dns_rebinding_around_the_sdk_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = iter(
        [
            ["93.184.216.34"],
            ["93.184.216.34"],
            ["127.0.0.1"],
        ]
    )

    class Body:
        def read(self, _maximum: int) -> bytes:
            return b'[{"order_id":"A-1"}]'

    class Client:
        def get_object(self, **_values: object) -> dict[str, object]:
            return {
                "Body": Body(),
                "ETag": '"etag-1"',
                "ContentType": "application/json",
            }

    boto3 = SimpleNamespace(client=lambda *_args, **_kwargs: Client())
    botocore_config = SimpleNamespace(Config=lambda **values: values)
    real_import = provider_adapters.importlib.import_module
    monkeypatch.setattr(
        provider_adapters.importlib,
        "import_module",
        lambda name: (
            boto3
            if name == "boto3"
            else botocore_config
            if name == "botocore.config"
            else real_import(name)
        ),
    )
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: next(resolutions),
        secret_resolver=lambda _ref: json.dumps(
            {
                "accessKeyId": "runtime-access-key",
                "secretAccessKey": "runtime-secret-key",
            }
        ),
    )
    adapter = application.connector_adapters()["s3"]
    request = ConnectorRequest(
        connector_key="s3",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "bucket": "knowledge-data",
            "objectPrefix": "safe/",
            "endpoint": "https://storage.example",
            "maxObjects": 100,
            "maxObjectBytes": 100_000,
            "timeoutSeconds": 5,
        },
        secret_ref="secret://workspace-step3b/s3",
        trace_id="trace-s3-rebinding",
        resource=DiscoveredResource(
            id="object-1",
            name="safe/orders.json",
            resource_type="file",
        ),
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.read(request)

    assert failure.value.code == "OBJECT_DNS_REBINDING"
    assert failure.value.stage == "read"


def test_s3_csv_read_preserves_format_and_applies_sdk_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Body:
        def read(self, _maximum: int) -> bytes:
            return b"order_id,amount\nA-1,12\n"

        def close(self) -> None:
            captured["body_closed"] = True

    class Client:
        def get_object(self, **_values: object) -> dict[str, object]:
            return {
                "Body": Body(),
                "ETag": '"etag-1"',
                "ContentType": "application/octet-stream",
            }

        def close(self) -> None:
            captured["client_closed"] = True

    def config(**values: object) -> dict[str, object]:
        captured["config"] = values
        return values

    def client(*_args: object, **values: object) -> Client:
        captured["client_values"] = values
        return Client()

    boto3 = SimpleNamespace(client=client)
    botocore_config = SimpleNamespace(Config=config)
    real_import = provider_adapters.importlib.import_module
    monkeypatch.setattr(
        provider_adapters.importlib,
        "import_module",
        lambda name: (
            boto3
            if name == "boto3"
            else botocore_config
            if name == "botocore.config"
            else real_import(name)
        ),
    )
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps(
            {
                "accessKeyId": "runtime-access-key",
                "secretAccessKey": "runtime-secret-key",
            }
        ),
    )
    request = ConnectorRequest(
        connector_key="s3",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "bucket": "knowledge-data",
            "objectPrefix": "safe/",
            "endpoint": "https://storage.example",
            "maxObjects": 100,
            "maxObjectBytes": 100_000,
            "timeoutSeconds": 5,
        },
        secret_ref="secret://workspace-step3b/s3",
        trace_id="trace-s3-csv",
        resource=DiscoveredResource(
            id="object-1",
            name="safe/orders.csv",
            resource_type="file",
        ),
    )

    result = application.connector_adapters()["s3"].read(request)

    assert result.source_type == "csv"
    assert result.media_type == "text/csv"
    assert result.rows == [{"order_id": "A-1", "amount": "12"}]
    assert captured["config"] == {
        "connect_timeout": 5,
        "read_timeout": 5,
        "retries": {"max_attempts": 0},
        "s3": {"addressing_style": "path"},
    }
    assert captured["body_closed"] is True
    assert captured["client_closed"] is True


def test_kafka_rejects_private_broker_resolution_without_explicit_allowlist(
    tmp_path: Path,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["127.0.0.1"],
    )
    request = ConnectorRequest(
        connector_key="kafka",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "bootstrapServers": ["broker.example:9093"],
            "topics": ["inventory"],
            "consumerGroup": "knowledge",
            "maxMessages": 100,
            "maxMessageBytes": 100_000,
            "timeoutSeconds": 5,
        },
        secret_ref=None,
        trace_id="trace-kafka-private",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        application.connector_adapters()["kafka"].validate(request)

    assert failure.value.code == "KAFKA_BROKER_FORBIDDEN"
    assert failure.value.stage == "validate"


def test_kafka_ipv6_broker_configures_bounded_consumer_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Consumer:
        def __init__(self, values: dict[str, object]) -> None:
            captured["values"] = values

        def subscribe(self, topics: list[str]) -> None:
            captured["topics"] = topics

        def poll(self, *, timeout: int) -> None:
            captured["poll_timeout"] = timeout

        def close(self) -> None:
            captured["closed"] = True

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["2001:4860:4860::8888"],
        secret_resolver=lambda _ref: "{}",
    )
    adapter = application.connector_adapters()["kafka"]
    monkeypatch.setattr(
        adapter,
        "_load_driver",
        lambda: SimpleNamespace(Consumer=Consumer),
    )
    request = ConnectorRequest(
        connector_key="kafka",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "bootstrapServers": ["[2001:4860:4860::8888]:9093"],
            "topics": ["inventory"],
            "consumerGroup": "knowledge",
            "maxMessages": 100,
            "maxMessageBytes": 100_000,
            "timeoutSeconds": 5,
        },
        secret_ref="secret://workspace-step3b/kafka",
        trace_id="trace-kafka-ipv6",
        resource=DiscoveredResource(
            id="topic-inventory",
            name="inventory",
            resource_type="operation",
        ),
    )

    result = adapter.read(request)

    values = captured["values"]
    assert isinstance(values, dict)
    assert values["bootstrap.servers"] == "[2001:4860:4860::8888]:9093"
    assert values["socket.timeout.ms"] == 5_000
    assert values["request.timeout.ms"] == 5_000
    assert captured["poll_timeout"] == 1
    assert captured["closed"] is True
    assert result.rows == []


@pytest.mark.parametrize(
    ("message", "expected_code", "expected_stage"),
    [
        ("SASL authentication failed", "PROVIDER_PERMISSION_DENIED", "authorize"),
        ("Local: Timed out", "PROVIDER_TIMEOUT", "discover"),
    ],
)
def test_kafka_discovery_maps_auth_and_timeout_to_typed_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_code: str,
    expected_stage: str,
) -> None:
    class Consumer:
        def __init__(self, _values: dict[str, object]) -> None:
            return None

        def list_topics(self, *, timeout: int) -> object:
            assert timeout == 5
            raise RuntimeError(message)

        def close(self) -> None:
            return None

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: "{}",
    )
    adapter = application.connector_adapters()["kafka"]
    monkeypatch.setattr(
        adapter,
        "_load_driver",
        lambda: SimpleNamespace(Consumer=Consumer),
    )
    request = ConnectorRequest(
        connector_key="kafka",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "bootstrapServers": ["broker.example:9093"],
            "topics": ["inventory"],
            "consumerGroup": "knowledge",
            "maxMessages": 100,
            "maxMessageBytes": 100_000,
            "timeoutSeconds": 5,
        },
        secret_ref="secret://workspace-step3b/kafka",
        trace_id="trace-kafka-error",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.discover(request)

    assert failure.value.code == expected_code
    assert failure.value.stage == expected_stage


@pytest.mark.parametrize(
    ("connector_key", "specific", "expected_code"),
    [
        (
            "lark_meeting",
            {
                "calendarRef": "calendar-token",
                "dateFrom": "2026-08-25",
                "dateTo": "2026-08-01",
            },
            "LARK_DATE_RANGE_INVALID",
        ),
        (
            "lark_meeting",
            {
                "calendarRef": "calendar-token",
                "dateFrom": "2026-08-01",
                "dateTo": "2026-09-10",
            },
            "LARK_DATE_RANGE_INVALID",
        ),
        (
            "lark_group",
            {"chatRef": "chat-token", "timeRange": "last week"},
            "LARK_TIME_RANGE_INVALID",
        ),
        (
            "lark_chat",
            {"chatRef": "chat-token", "timeRange": "P0D"},
            "LARK_TIME_RANGE_INVALID",
        ),
    ],
)
def test_lark_rejects_invalid_date_and_time_ranges(
    tmp_path: Path,
    connector_key: str,
    specific: dict[str, JsonValue],
    expected_code: str,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
    )
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            **specific,
            "scopeRef": f"scope-{connector_key}",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 50,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        },
        secret_ref=None,
        trace_id=f"trace-{connector_key}-invalid-range",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        application.connector_adapters()[connector_key].validate(request)

    assert failure.value.code == expected_code
    assert failure.value.stage == "validate"


def test_lark_meeting_read_sends_date_and_attendee_filters(
    tmp_path: Path,
) -> None:
    captured: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = unquote(urlsplit(str(request.url)).path)
        if path.endswith("/calendar/v4/calendars/calendar-token/events/instance_view"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            {"event_id": "event-matching", "summary": "Keep"},
                            {"event_id": "event-other", "summary": "Drop"},
                        ]
                    },
                },
            )
        if path.endswith(
            "/calendar/v4/calendars/calendar-token/events/event-matching/attendees"
        ):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            {"type": "user", "user_id": "ou_a"},
                            {"type": "user", "user_id": "ou_b"},
                        ],
                        "has_more": False,
                    },
                },
            )
        assert path.endswith(
            "/calendar/v4/calendars/calendar-token/events/event-other/attendees"
        )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [{"type": "user", "user_id": "ou_a"}],
                    "has_more": False,
                },
            },
        )

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps({"accessToken": "runtime-token"}),
        http_transport=httpx.MockTransport(handle),
    )
    request = ConnectorRequest(
        connector_key="lark_meeting",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "calendarRef": "calendar-token",
            "dateFrom": "2026-08-01",
            "dateTo": "2026-08-25",
            "attendees": ["ou_a", "ou_b"],
            "scopeRef": "scope-lark-meeting",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 30,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        },
        secret_ref="secret://workspace-step3b/lark",
        trace_id="trace-lark-meeting",
    )

    result = application.connector_adapters()["lark_meeting"].read(request)

    assert [item.method for item in captured] == ["GET", "GET", "GET"]
    instance_query = parse_qs(urlsplit(str(captured[0].url)).query)
    assert instance_query == {
        "start_time": ["1785513600"],
        "end_time": ["1787673599"],
        "user_id_type": ["open_id"],
    }
    for attendee_request in captured[1:]:
        assert parse_qs(urlsplit(str(attendee_request.url)).query) == {
            "page_size": ["30"],
            "user_id_type": ["open_id"],
        }
    assert result.rows == [
        {
            "event_id": "event-matching",
            "summary": "Keep",
            "attendees": [
                {"type": "user", "user_id": "ou_a"},
                {"type": "user", "user_id": "ou_b"},
            ],
        }
    ]


@pytest.mark.parametrize(
    ("connector_key", "specific", "expected_method", "expected_query", "expected_body"),
    [
        (
            "lark_group",
            {
                "chatRef": "oc_group",
                "timeRange": "P7D",
                "includeAttachments": True,
            },
            "GET",
            {
                "container_id": ["oc_group"],
                "container_id_type": ["chat"],
                "sort_type": ["ByCreateTimeAsc"],
            },
            None,
        ),
        (
            "lark_base",
            {
                "appRef": "app_token",
                "tableRef": "tbl_token",
                "viewRef": "viw_token",
            },
            "GET",
            {"view_id": ["viw_token"]},
            None,
        ),
        (
            "lark_mail",
            {"folder": "INBOX", "query": "budget"},
            "POST",
            {},
            {"filter": {"folder": ["inbox"]}, "query": "budget"},
        ),
    ],
)
def test_lark_reads_apply_source_specific_selection_parameters(
    tmp_path: Path,
    connector_key: str,
    specific: dict[str, JsonValue],
    expected_method: str,
    expected_query: dict[str, list[str]],
    expected_body: dict[str, object] | None,
) -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "message_id": "om_1",
                            "body": {"content": json.dumps({"file_key": "file_1"})},
                        }
                    ]
                },
            },
        )

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps({"accessToken": "runtime-token"}),
        http_transport=httpx.MockTransport(handle),
    )
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            **specific,
            "scopeRef": f"scope-{connector_key}",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 30,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        },
        secret_ref="secret://workspace-step3b/lark",
        trace_id=f"trace-{connector_key}",
    )

    result = application.connector_adapters()[connector_key].read(request)

    assert captured["method"] == expected_method
    query = parse_qs(urlsplit(str(captured["url"])).query)
    for name, value in expected_query.items():
        assert query[name] == value
    assert captured["body"] == expected_body
    if connector_key == "lark_group":
        assert query["start_time"][0].isdigit()
        assert query["end_time"][0].isdigit()
        assert result.rows[0]["attachment_metadata"] == [
            {"type": "file", "key": "file_1"}
        ]


@pytest.mark.parametrize(
    ("status", "body", "expected_code", "expected_stage"),
    [
        (
            200,
            {"code": 99991672, "msg": "permission denied"},
            "OFFICE_PERMISSION_REVOKED",
            "authorize",
        ),
        (
            200,
            {"code": 1061007, "msg": "file has been deleted"},
            "OFFICE_RESOURCE_DELETED",
            "read",
        ),
        (403, {}, "OFFICE_PERMISSION_REVOKED", "authorize"),
        (404, {}, "OFFICE_RESOURCE_DELETED", "read"),
    ],
)
def test_lark_distinguishes_revoked_acl_from_deleted_resource(
    tmp_path: Path,
    status: int,
    body: dict[str, object],
    expected_code: str,
    expected_stage: str,
) -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps({"accessToken": "runtime-token"}),
        http_transport=httpx.MockTransport(handle),
    )
    request = ConnectorRequest(
        connector_key="lark_doc",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "documentRef": "doc-token",
            "scopeRef": "scope-lark-doc",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 30,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        },
        secret_ref="secret://workspace-step3b/lark",
        trace_id="trace-lark-error",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        application.connector_adapters()["lark_doc"].read(request)

    assert failure.value.code == expected_code
    assert failure.value.stage == expected_stage


def test_lark_refresh_checkpoint_changes_only_when_content_changes(
    tmp_path: Path,
) -> None:
    content = {"value": "first"}

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 0, "data": {"content": content["value"]}},
        )

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps({"accessToken": "runtime-token"}),
        http_transport=httpx.MockTransport(handle),
    )
    adapter = application.connector_adapters()["lark_doc"]
    request = ConnectorRequest(
        connector_key="lark_doc",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "documentRef": "doc-token",
            "scopeRef": "scope-lark-doc",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 30,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        },
        secret_ref="secret://workspace-step3b/lark",
        trace_id="trace-lark-refresh",
    )

    first = adapter.refresh(request)
    same = adapter.refresh(
        ConnectorRequest(
            **{
                **request.__dict__,
                "trace_id": "trace-lark-same",
                "read_cache": ConnectorReadCache(),
            }
        )
    )
    content["value"] = "second"
    changed = adapter.refresh(
        ConnectorRequest(
            **{
                **request.__dict__,
                "trace_id": "trace-lark-changed",
                "read_cache": ConnectorReadCache(),
            }
        )
    )

    assert first.checkpoint == same.checkpoint
    assert first.checkpoint["contentDigest"] != changed.checkpoint["contentDigest"]


def test_remote_mcp_invalid_tool_payload_returns_a_persistable_failed_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RemoteMcpClient()
    succeeded = RemoteMcpTrace(
        id="mcp-remote-trace-test",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        connection_id="connection-step3b",
        correlation_id="trace-mcp-invalid-result",
        transport="streamable_http",
        endpoint="https://mcp.example/rpc",
        status="succeeded",
        exchanges=[
            RemoteMcpExchange(
                sequence=1,
                method="initialize",
                status="succeeded",
                response_digest="a" * 64,
            ),
            RemoteMcpExchange(
                sequence=2,
                method="tools/list",
                status="succeeded",
                response_digest="b" * 64,
            ),
            RemoteMcpExchange(
                sequence=3,
                method="tools/call",
                status="succeeded",
                response_digest="c" * 64,
            ),
        ],
        started_at="2026-08-25T00:00:00+00:00",
        finished_at="2026-08-25T00:00:01+00:00",
    )
    monkeypatch.setattr(
        client,
        "_run",
        lambda **_kwargs: (
            [],
            {"content": [{"type": "text", "text": "not-json"}]},
            succeeded,
            frozenset(),
        ),
    )

    with pytest.raises(RemoteMcpError) as failure:
        client.call(
            workspace_id="workspace-step3b",
            principal_id="user-step3b",
            connection_id="connection-step3b",
            configuration={
                "transport": "streamable_http",
                "endpoint": "https://mcp.example/rpc",
                "toolAllowlist": ["inventory.read"],
            },
            secret_ref=None,
            trace_id="trace-mcp-invalid-result",
            tool_name="inventory.read",
            tool_arguments={},
        )

    assert failure.value.code == "MCP_INVALID_TOOL_RESULT"
    assert failure.value.trace.status == "failed"
    assert failure.value.trace.error_code == "MCP_INVALID_TOOL_RESULT"
    assert failure.value.trace.exchanges[-1].status == "failed"
    assert failure.value.trace.exchanges[-1].error_code == "MCP_INVALID_TOOL_RESULT"


def test_remote_mcp_adapter_persists_trace_and_redacts_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "runtime-mcp-secret-sentinel"
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps(
            {"Authorization": f"Bearer {sentinel}"}
        ),
    )
    adapter = application.connector_adapters()["mcp_custom"]
    succeeded = RemoteMcpTrace(
        id="mcp-remote-trace-persist",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        connection_id="connection-step3b",
        correlation_id="trace-mcp-persist",
        transport="streamable_http",
        endpoint="https://mcp.example/rpc",
        status="succeeded",
        exchanges=[
            RemoteMcpExchange(
                sequence=1,
                method="tools/call",
                status="succeeded",
                response_digest="a" * 64,
            )
        ],
        started_at="2026-08-25T00:00:00+00:00",
        finished_at="2026-08-25T00:00:01+00:00",
    )
    monkeypatch.setattr(
        application._remote_mcp_client,
        "_run",
        lambda **_kwargs: (
            [],
            {
                "structuredContent": {
                    "rows": [
                        {
                            "api_token": sentinel,
                            "note": f"value={sentinel}",
                        }
                    ]
                }
            },
            succeeded,
            frozenset({sentinel, f"Bearer {sentinel}"}),
        ),
    )
    request = ConnectorRequest(
        connector_key="mcp_custom",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        connection_id="connection-step3b",
        configuration={
            "transport": "streamable_http",
            "endpoint": "https://mcp.example/rpc",
            "toolAllowlist": ["inventory.read"],
            "startupTimeoutSeconds": 5,
            "callTimeoutSeconds": 5,
            "maxPages": 5,
            "outputBytes": 100_000,
        },
        secret_ref="secret://workspace-step3b/mcp",
        trace_id="trace-mcp-persist",
        resource=DiscoveredResource(
            id="mcp-tool-" + hashlib.sha256(b"inventory.read").hexdigest()[:24],
            name="inventory.read",
            resource_type="tool",
        ),
    )

    result = adapter.read(request)

    assert result.rows == [{"api_token": "[REDACTED]", "note": "value=[REDACTED]"}]
    traces = application.repository.connector_traces(
        "workspace-step3b", "connection-step3b"
    )
    assert len(traces) == 1
    assert sentinel not in traces[0].model_dump_json()


def test_remote_mcp_adapter_persists_post_protocol_parse_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
    )
    adapter = application.connector_adapters()["mcp_custom"]
    succeeded = RemoteMcpTrace(
        id="mcp-remote-trace-parse-failure",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        connection_id="connection-step3b",
        correlation_id="trace-mcp-parse-failure",
        transport="streamable_http",
        endpoint="https://mcp.example/rpc",
        status="succeeded",
        exchanges=[
            RemoteMcpExchange(
                sequence=1,
                method="tools/call",
                status="succeeded",
                response_digest="a" * 64,
            )
        ],
        started_at="2026-08-25T00:00:00+00:00",
        finished_at="2026-08-25T00:00:01+00:00",
    )
    monkeypatch.setattr(
        application._remote_mcp_client,
        "_run",
        lambda **_kwargs: (
            [],
            {"content": [{"type": "text", "text": "not-json"}]},
            succeeded,
            frozenset(),
        ),
    )
    request = ConnectorRequest(
        connector_key="mcp_custom",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        connection_id="connection-step3b",
        configuration={
            "transport": "streamable_http",
            "endpoint": "https://mcp.example/rpc",
            "toolAllowlist": ["inventory.read"],
            "startupTimeoutSeconds": 5,
            "callTimeoutSeconds": 5,
            "maxPages": 5,
            "outputBytes": 100_000,
        },
        secret_ref=None,
        trace_id="trace-mcp-parse-failure",
        resource=DiscoveredResource(
            id="mcp-tool-" + hashlib.sha256(b"inventory.read").hexdigest()[:24],
            name="inventory.read",
            resource_type="tool",
        ),
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.read(request)

    assert failure.value.code == "MCP_INVALID_TOOL_RESULT"
    traces = application.repository.connector_traces(
        "workspace-step3b", "connection-step3b"
    )
    assert len(traces) == 1
    assert traces[0].status == "failed"
    assert traces[0].error_code == "MCP_INVALID_TOOL_RESULT"
