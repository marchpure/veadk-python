from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
    SourcesGoldenError,
)

pytestmark = pytest.mark.skipif(
    os.getenv("STEP3B_LIVE_DATABASES") != "1",
    reason="set STEP3B_LIVE_DATABASES=1 for local container certification",
)


@pytest.fixture(params=["postgresql", "mysql"])
def live_database(request: pytest.FixtureRequest) -> Iterator[dict[str, object]]:
    password = os.environ.get("STEP3B_DB_PASSWORD")
    if not password:
        pytest.skip("STEP3B_DB_PASSWORD is required for live database certification")
    connector_key = str(request.param)
    port = 55_000 if connector_key == "postgresql" else 55_001
    schema = "public" if connector_key == "postgresql" else "knowledge"
    table = "step3b_connector_orders"
    if connector_key == "postgresql":
        import psycopg2

        connection = psycopg2.connect(
            host="127.0.0.1",
            port=port,
            dbname="knowledge",
            user="step3b",
            password=password,
        )
    else:
        import pymysql

        connection = pymysql.connect(
            host="127.0.0.1",
            port=port,
            database="knowledge",
            user="step3b",
            password=password,
            autocommit=True,
        )
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        cursor.execute(
            f"CREATE TABLE {table} "
            "(order_id VARCHAR(32) PRIMARY KEY, amount INTEGER NOT NULL)"
        )
        cursor.execute(
            f"INSERT INTO {table} (order_id, amount) VALUES ('A-1', 12), ('B-2', 5)"
        )
    connection.commit()
    connection.close()
    yield {
        "connector_key": connector_key,
        "host": "127.0.0.1",
        "port": port,
        "database": "knowledge",
        "schema": schema,
        "table": table,
        "password": password,
    }
    if connector_key == "postgresql":
        import psycopg2

        connection = psycopg2.connect(
            host="127.0.0.1",
            port=port,
            dbname="knowledge",
            user="step3b",
            password=password,
        )
    else:
        import pymysql

        connection = pymysql.connect(
            host="127.0.0.1",
            port=port,
            database="knowledge",
            user="step3b",
            password=password,
            autocommit=True,
        )
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    connection.commit()
    connection.close()


def _context() -> AccessContext:
    return AccessContext(
        workspace_id="workspace-step3b-live",
        principal_id="user-step3b-live",
        role="editor",
    )


def _application(
    root: Path, database: dict[str, object], *, password: str | None = None
) -> SourceGoldenApplication:
    runtime_password = password or str(database["password"])
    return SourceGoldenApplication(
        database_path=root / "sources-golden.sqlite3",
        artifact_root=root / "artifacts",
        source_root=root / "uploads",
        web_resolver=lambda _host: ["127.0.0.1"],
        network_allow_private_hosts={"127.0.0.1"},
        secret_resolver=lambda _ref: json.dumps(
            {"username": "step3b", "password": runtime_password}
        ),
    )


def _configuration(database: dict[str, object]) -> dict[str, object]:
    return {
        "host": database["host"],
        "port": database["port"],
        "database": database["database"],
        "schemaAllowlist": [database["schema"]],
        "tableAllowlist": [database["table"]],
        "query": (
            f"SELECT * FROM {database['schema']}.{database['table']} "
            "WHERE amount >= :minimum ORDER BY order_id"
        ),
        "queryParameters": {"minimum": 10},
        "pageSize": 1,
        "rowLimit": 10,
        "byteLimit": 10_000,
        "timeoutSeconds": 5,
    }


def _mutate(database: dict[str, object], statement: str) -> None:
    if database["connector_key"] == "postgresql":
        import psycopg2

        connection = psycopg2.connect(
            host=str(database["host"]),
            port=int(str(database["port"])),
            dbname=str(database["database"]),
            user="step3b",
            password=str(database["password"]),
        )
    else:
        import pymysql

        connection = pymysql.connect(
            host=str(database["host"]),
            port=int(str(database["port"])),
            database=str(database["database"]),
            user="step3b",
            password=str(database["password"]),
            autocommit=True,
        )
    with connection.cursor() as cursor:
        cursor.execute(statement)
    connection.commit()
    connection.close()


def test_live_database_lifecycle_survives_refresh_and_restart(
    tmp_path: Path,
    live_database: dict[str, object],
) -> None:
    application = _application(tmp_path, live_database)
    connector_key = str(live_database["connector_key"])
    created = application.create_connection(
        _context(),
        connector_key=connector_key,
        display_name=f"Live {connector_key}",
        scope="team",
        configuration=_configuration(live_database),
        secret_ref=f"secret://workspace-step3b-live/{connector_key}",
        idempotency_key=f"{connector_key}-create",
        trace_id=f"trace-{connector_key}-create",
    )

    assert created.connection.status == "ready"
    assert len(created.discovery.resources) == 1
    resource = created.discovery.resources[0]
    assert resource.name == live_database["table"]
    assert {field.name for field in resource.fields} == {"order_id", "amount"}

    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=resource.id,
        recipe_operations=[],
        idempotency_key=f"{connector_key}-ingest",
        trace_id=f"trace-{connector_key}-ingest",
    )
    assert application.golden_data(
        _context(), ingested.golden_asset_revision.id
    ).rows == [{"amount": 12, "order_id": "A-1"}]

    _mutate(
        live_database,
        f"UPDATE {live_database['table']} SET amount = 14 WHERE order_id = 'A-1'",
    )
    refreshed = application.refresh(
        _context(),
        asset_id=ingested.golden_asset_revision.asset_id,
        idempotency_key=f"{connector_key}-refresh",
        trace_id=f"trace-{connector_key}-refresh",
    )
    assert refreshed.run.status == "succeeded"
    assert refreshed.golden_asset_revision is not None
    assert application.golden_data(
        _context(), refreshed.golden_asset_revision.id
    ).rows == [{"amount": 14, "order_id": "A-1"}]

    reopened = _application(tmp_path, live_database)
    restored = reopened.golden_revision(_context(), refreshed.golden_asset_revision.id)
    assert restored.lineage.content_digest == (
        refreshed.golden_asset_revision.lineage.content_digest
    )


def test_live_database_wrong_password_is_typed_and_preserves_last_good(
    tmp_path: Path,
    live_database: dict[str, object],
) -> None:
    connector_key = str(live_database["connector_key"])
    application = _application(tmp_path, live_database)
    created = application.create_connection(
        _context(),
        connector_key=connector_key,
        display_name=f"Live {connector_key}",
        scope="team",
        configuration=_configuration(live_database),
        secret_ref=f"secret://workspace-step3b-live/{connector_key}",
        idempotency_key=f"{connector_key}-auth-create",
        trace_id=f"trace-{connector_key}-auth-create",
    )
    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=[],
        idempotency_key=f"{connector_key}-auth-ingest",
        trace_id=f"trace-{connector_key}-auth-ingest",
    )

    rejected = _application(
        tmp_path,
        live_database,
        password="definitely-not-the-database-password",
    )
    refreshed = rejected.refresh(
        _context(),
        asset_id=ingested.golden_asset_revision.asset_id,
        idempotency_key=f"{connector_key}-wrong-password",
        trace_id=f"trace-{connector_key}-wrong-password",
    )

    assert refreshed.run.status == "failed"
    assert refreshed.run.reason.code == "DATABASE_AUTHENTICATION_FAILED"
    assert refreshed.last_good_revision == ingested.golden_asset_revision
    trace = rejected.connector_trace(
        _context(),
        created.connection.id,
        f"trace-{connector_key}-wrong-password",
    )
    assert trace.operations[-2].status == "failed"
    assert trace.operations[-2].reason.code == "DATABASE_AUTHENTICATION_FAILED"


def test_live_database_adapter_rejects_write_sql_before_connecting(
    tmp_path: Path,
    live_database: dict[str, object],
) -> None:
    configuration = _configuration(live_database)
    configuration["query"] = (
        f"UPDATE {live_database['schema']}.{live_database['table']} "
        "SET amount = :minimum"
    )

    with pytest.raises(SourcesGoldenError) as failure:
        _application(tmp_path, live_database).create_connection(
            _context(),
            connector_key=str(live_database["connector_key"]),
            display_name="Write query must fail",
            scope="team",
            configuration=configuration,
            secret_ref=(
                f"secret://workspace-step3b-live/{live_database['connector_key']}"
            ),
            idempotency_key=f"{live_database['connector_key']}-write-query",
            trace_id=f"trace-{live_database['connector_key']}-write-query",
        )

    assert failure.value.code == "DATABASE_CONFIGURATION_INVALID"
    assert "read-only" in failure.value.message


def test_live_database_row_limit_is_typed_and_traced(
    tmp_path: Path,
    live_database: dict[str, object],
) -> None:
    connector_key = str(live_database["connector_key"])
    configuration = _configuration(live_database)
    configuration["queryParameters"] = {"minimum": 0}
    configuration["rowLimit"] = 1
    application = _application(tmp_path, live_database)
    created = application.create_connection(
        _context(),
        connector_key=connector_key,
        display_name=f"Bounded {connector_key}",
        scope="team",
        configuration=configuration,
        secret_ref=f"secret://workspace-step3b-live/{connector_key}",
        idempotency_key=f"{connector_key}-row-limit-create",
        trace_id=f"trace-{connector_key}-row-limit-create",
    )

    with pytest.raises(SourcesGoldenError) as failure:
        application.ingest(
            _context(),
            connection_id=created.connection.id,
            resource_id=created.discovery.resources[0].id,
            recipe_operations=[],
            idempotency_key=f"{connector_key}-row-limit-ingest",
            trace_id=f"trace-{connector_key}-row-limit-ingest",
        )

    assert failure.value.code == "DATABASE_ROW_LIMIT"
    trace = application.connector_trace(
        _context(),
        created.connection.id,
        f"trace-{connector_key}-row-limit-ingest",
    )
    assert trace.operations[-2].status == "failed"
    assert trace.operations[-2].reason.code == "DATABASE_ROW_LIMIT"


def test_live_database_byte_limit_is_typed_and_traced(
    tmp_path: Path,
    live_database: dict[str, object],
) -> None:
    connector_key = str(live_database["connector_key"])
    configuration = _configuration(live_database)
    configuration["byteLimit"] = 8
    application = _application(tmp_path, live_database)
    created = application.create_connection(
        _context(),
        connector_key=connector_key,
        display_name=f"Byte bounded {connector_key}",
        scope="team",
        configuration=configuration,
        secret_ref=f"secret://workspace-step3b-live/{connector_key}",
        idempotency_key=f"{connector_key}-byte-limit-create",
        trace_id=f"trace-{connector_key}-byte-limit-create",
    )

    with pytest.raises(SourcesGoldenError) as failure:
        application.ingest(
            _context(),
            connection_id=created.connection.id,
            resource_id=created.discovery.resources[0].id,
            recipe_operations=[],
            idempotency_key=f"{connector_key}-byte-limit-ingest",
            trace_id=f"trace-{connector_key}-byte-limit-ingest",
        )

    assert failure.value.code == "DATABASE_BYTE_LIMIT"
    trace = application.connector_trace(
        _context(),
        created.connection.id,
        f"trace-{connector_key}-byte-limit-ingest",
    )
    assert trace.operations[-2].status == "failed"
    assert trace.operations[-2].reason.code == "DATABASE_BYTE_LIMIT"


def test_live_database_schema_drift_preserves_last_good_after_restart(
    tmp_path: Path,
    live_database: dict[str, object],
) -> None:
    connector_key = str(live_database["connector_key"])
    application = _application(tmp_path, live_database)
    created = application.create_connection(
        _context(),
        connector_key=connector_key,
        display_name=f"Schema guarded {connector_key}",
        scope="team",
        configuration=_configuration(live_database),
        secret_ref=f"secret://workspace-step3b-live/{connector_key}",
        idempotency_key=f"{connector_key}-schema-create",
        trace_id=f"trace-{connector_key}-schema-create",
    )
    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=[],
        idempotency_key=f"{connector_key}-schema-ingest",
        trace_id=f"trace-{connector_key}-schema-ingest",
    )
    _mutate(
        live_database,
        f"ALTER TABLE {live_database['table']} ADD COLUMN note VARCHAR(64)",
    )

    refreshed = application.refresh(
        _context(),
        asset_id=ingested.golden_asset_revision.asset_id,
        idempotency_key=f"{connector_key}-schema-refresh",
        trace_id=f"trace-{connector_key}-schema-refresh",
    )

    assert refreshed.run.status == "schema_drift"
    assert refreshed.run.reason.code == "SCHEMA_DRIFT"
    assert refreshed.golden_asset_revision is None
    assert refreshed.last_good_revision == ingested.golden_asset_revision
    reopened = _application(tmp_path, live_database)
    detail = reopened.golden_asset_detail(
        _context(),
        ingested.golden_asset_revision.asset_id,
    )
    assert detail.asset.id == ingested.golden_asset_revision.id
