from __future__ import annotations

import json
import re
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai import types

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.service import KnowledgeAssetStore


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "dashboard askdata test key")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        service=KnowledgeAssetStore(
            repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
        ),
    )
    return TestClient(app)


def _client_with_streaming_runner(tmp_path, monkeypatch, runner) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "dashboard askdata stream test key")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        service=KnowledgeAssetStore(
            repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
        ),
        asktable_streaming_runner=runner,
    )
    return TestClient(app)


class FakeAskTableStreamingRunner:
    def health(self) -> dict[str, object]:
        return {
            "configured": True,
            "status": "available",
            "runner_backend": "fake-streaming-runner",
            "model_name": "fake-model",
        }

    async def run(
        self,
        *,
        instruction: str,
        message: str,
        session_id: str,
        conversation_id: str,
        semantic_asset: dict[str, object],
        tools: dict[str, object],
    ):
        call = types.Part.from_function_call(
            name="query_semantic_skill",
            args={"question": message, "metric": "ticket_count", "dimensions": ["store"]},
        )
        yield _event(
            author="studio_asktable_streaming_agent",
            role="model",
            part=call,
            conversation_id=conversation_id,
            session_id=session_id,
        )
        response = await tools["query_semantic_skill"](
            question=message,
            metric="ticket_count",
            dimensions=["store"],
        )
        yield _event(
            author="studio_asktable_streaming_agent",
            role="user",
            part=types.Part.from_function_response(
                name="query_semantic_skill",
                response=response,
            ),
            conversation_id=conversation_id,
            session_id=session_id,
        )
        yield _event(
            author="studio_asktable_streaming_agent",
            role="model",
            part=types.Part.from_text(
                text="VNPTTE has 56 tickets. SQL and metric evidence are included in the tool result.",
            ),
            conversation_id=conversation_id,
            session_id=session_id,
        )


def _event(
    *,
    author: str,
    role: str,
    part: types.Part,
    conversation_id: str,
    session_id: str,
) -> dict[str, object]:
    return {
        "author": author,
        "conversation_id": conversation_id,
        "session_id": session_id,
        "content": {
            "role": role,
            "parts": [part.model_dump(mode="json", by_alias=True, exclude_none=True)],
        },
    }


def _sse_events(response) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in response.text.split("\n\n"):
        data_lines = [
            line.removeprefix("data:").strip()
            for line in frame.splitlines()
            if line.startswith("data:")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


def test_askdata_query_returns_required_evidence(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "oracle-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
            "mode": "offline",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    data = body["data"]
    assert data["rows"] == [
        {"store": "VNPTTE", "ticket_count": 56},
        {"store": "SG - ANTA VIVO City", "ticket_count": 9},
    ]
    assert "SALES_ORDER" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"]["status"] == "fresh"
    assert data["execution"]["governed_rest"] is True
    assert data["execution"]["direct_database_access"] is False
    assert "secret" not in response.text.lower()


def test_asktable_query_compatibility_route_returns_required_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/asktable/query",
        json={
            "semantic_asset_id": "oracle-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
            "mode": "offline",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    data = body["data"]
    assert "SALES_ORDER" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"]["status"] == "fresh"
    assert data["execution"]["governed_rest"] is True


def test_askdata_uses_e2_schema_only_governed_query_without_fixture_result(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(
        client,
        asset_id="schema-only-sales",
        governed_result=False,
        artifacts_mdl=True,
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "schema-only-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
            "mode": "offline",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    data = body["data"]
    assert data["rows"] == []
    assert data["returnedCount"] == 0
    assert "SELECT" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["decision"] == "allow"
    assert data["execution"]["mode"] == "schema_only"
    assert data["execution"]["governed_rest"] is True
    assert data["execution"]["direct_database_access"] is False
    assert "COUNT(DISTINCT" in data["sql"]


def test_askdata_accepts_current_e2_inline_mdl_package_without_fixture_result(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(
        client,
        asset_id="e2-inline-sales",
        governed_result=False,
        artifacts_mdl=False,
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "e2-inline-sales",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "question": "按门店统计最近销售票数 Top 3",
            "mode": "offline",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution"]["mode"] == "schema_only"
    assert data["rows"] == []
    assert data["returnedCount"] == 0
    assert data["sql"].startswith("SELECT")
    assert "COUNT(DISTINCT" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["direct_database_access"] is False


def test_schema_only_package_fails_closed_in_production_mode(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(
        client,
        asset_id="schema-only-sales",
        governed_result=False,
        artifacts_mdl=True,
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "schema-only-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 400
    assert "schema_only" in response.text


def test_askdata_production_uses_local_sqlite_governed_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    db_path = tmp_path / "sales.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE sales_order_summary (
              order_id INTEGER PRIMARY KEY,
              order_date TEXT NOT NULL,
              store_name TEXT NOT NULL,
              paid_amount REAL NOT NULL
            );
            INSERT INTO sales_order_summary VALUES
              (1, '2026-08-01', 'Union Square', 900.0),
              (2, '2026-08-02', 'Union Square', 780.0),
              (3, '2026-08-03', 'Pike Place', 420.0);
            """
        )
        conn.commit()
    finally:
        conn.close()
    _semantic_skill(
        client,
        asset_id="local-sqlite-sales",
        governed_result=False,
        local_sqlite_path=str(db_path),
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "local-sqlite-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    data = body["data"]
    assert data["rows"] == [
        {"store": "Union Square", "ticket_count": 2},
        {"store": "Pike Place", "ticket_count": 1},
    ]
    assert data["returnedCount"] == 2
    assert data["policyDecision"]["decision"] == "allow"
    assert data["execution"]["result_source"] == "local_sqlite_governed_runtime"
    assert data["execution"]["production_completed"] is True
    assert data["execution"]["raw_sql_fallback"] is False
    assert data["execution"]["direct_database_access"] is False
    assert data["production_completed"] is True
    assert "schema_only" not in data["execution_mode"]


def test_dashboard_share_create_get_revoke_and_public_page(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)
    build = client.post(
        "/api/knowledge-assets/build/dashboard-skill",
        json={
            "semantic_asset_id": "oracle-sales",
            "name": "Oracle Sales Dashboard",
            "intent": "按门店查看销售票数",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "publish": True,
        },
    )
    assert build.status_code == 201
    asset_id = build.json()["dashboard_asset_id"]

    share = client.post(
        f"/api/knowledge-assets/assets/dashboard/{asset_id}/share",
        json={
            "visibility": "local_link",
            "dashboard_html": "<main><h1>Shared Dashboard</h1><script>window.__ok=true</script></main>",
            "dashboard_spec": build.json()["preview"],
            "query": {
                "sql": "SELECT store_name FROM SALES_ORDER",
                "metricDefinition": "Count distinct tickets.",
            },
            "evidence": {
                "policyDecision": {"decision": "allow"},
                "freshness": {"status": "fresh"},
            },
        },
    )
    assert share.status_code == 201
    payload = share.json()
    share_id = payload["share_id"]
    assert payload["asset_id"] == asset_id
    assert payload["share_url"] == f"/share/knowledge-assets/dashboard/{share_id}"
    assert payload["sanitized_snapshot"]["dashboard"]["html"].startswith("<main>")

    fetched = client.get(f"/api/knowledge-assets/shares/{share_id}")
    assert fetched.status_code == 200
    assert fetched.json()["share_id"] == share_id

    page = client.get(f"/share/knowledge-assets/dashboard/{share_id}")
    assert page.status_code == 200
    assert "Shared Dashboard" in page.text
    assert "SQL / Metric" in page.text

    revoked = client.post(f"/api/knowledge-assets/shares/{share_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"]
    assert client.get(f"/api/knowledge-assets/shares/{share_id}").status_code == 404
    assert client.get(f"/share/knowledge-assets/dashboard/{share_id}").status_code == 404


def test_dashboard_share_expiry_hides_api_and_public_page(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)
    build = client.post(
        "/api/knowledge-assets/build/dashboard-skill",
        json={
            "semantic_asset_id": "oracle-sales",
            "name": "Expired Dashboard",
            "intent": "按门店查看销售票数",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "publish": True,
        },
    )
    assert build.status_code == 201
    asset_id = build.json()["dashboard_asset_id"]

    share = client.post(
        f"/api/knowledge-assets/assets/dashboard/{asset_id}/share",
        json={
            "expires_at": "2000-01-01T00:00:00Z",
            "dashboard_html": "<main><h1>Expired Dashboard</h1></main>",
            "dashboard_spec": build.json()["preview"],
        },
    )

    assert share.status_code == 201
    share_id = share.json()["share_id"]
    assert client.get(f"/api/knowledge-assets/shares/{share_id}").status_code == 404
    assert client.get(f"/share/knowledge-assets/dashboard/{share_id}").status_code == 404


def test_dashboard_share_snapshot_redacts_secrets(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)
    build = client.post(
        "/api/knowledge-assets/build/dashboard-skill",
        json={
            "semantic_asset_id": "oracle-sales",
            "name": "Secret Safe Dashboard",
            "intent": "按门店查看销售票数",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "publish": True,
        },
    )
    assert build.status_code == 201
    asset_id = build.json()["dashboard_asset_id"]

    response = client.post(
        f"/api/knowledge-assets/assets/dashboard/{asset_id}/share",
        json={
            "dashboard_html": "<main data-token='abc'>authorization: Bearer abc</main>",
            "dashboard_spec": {
                "connection_string": "postgres://user:pass@example/db",
                "api_key": "abc",
                "ak": "access",
                "sk": "secret",
                "data_views": [
                    {
                        "id": "primary",
                        "sql": "SELECT 1",
                        "rows": [{"authorization": "Bearer abc", "cookie": "sid=abc"}],
                    }
                ],
            },
            "query": {
                "sql": "SELECT 1",
                "token": "abc",
                "authorization": "Bearer abc",
                "cookie": "sid=abc",
                "password": "pw",
            },
            "evidence": {"secret": "abc", "policyDecision": {"decision": "allow"}},
        },
    )

    assert response.status_code == 201
    text = json.dumps(response.json()["sanitized_snapshot"]).lower()
    for forbidden in [
        "bearer abc",
        "sid=abc",
        "postgres://user:pass",
        '"api_key": "abc"',
        '"authorization": "bearer abc"',
        '"cookie": "sid=abc"',
        '"password": "pw"',
        '"ak": "access"',
        '"sk": "secret"',
    ]:
        assert forbidden not in text
    assert "[redacted]" in text


def test_schema_only_query_sanitizes_mdl_metadata_in_sql_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(
        client,
        asset_id="schema-only-sales",
        governed_result=False,
        artifacts_mdl=True,
        malicious_metadata=True,
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "schema-only-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "filters": {"region; DROP TABLE audit": "SG' OR '1'='1"},
            "question": "按门店查看销售票数",
            "mode": "offline",
        },
    )

    assert response.status_code == 200
    sql = response.json()["data"]["sql"]
    assert "DROP" not in sql
    assert "--" not in sql
    assert "COUNT(DISTINCT" in sql
    assert '"sales_order_TABLE_users"' in sql
    assert '"store_name_TABLE_users"' in sql
    assert '"region_TABLE_audit"' in sql
    assert "SG'' OR ''1''=''1" in sql
    assert "ticket_id) FROM" not in sql


def test_askdata_denies_customer_contact_questions(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "oracle-sales",
            "question": "列出 customer phone contact",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["data"]["policyDecision"]["decision"] == "deny"
    assert body["data"]["sql"].startswith("-- policy denied")
    assert body["data"]["metricDefinition"] == "Count distinct tickets."
    assert body["data"]["freshness"]["status"] == "blocked"


def test_dashboard_skill_build_records_skill_package_and_job(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    space_id = _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/build/dashboard-skill",
        json={
            "space_id": space_id,
            "semantic_asset_id": "oracle-sales",
            "name": "Oracle Sales Dashboard",
            "intent": "按门店查看销售票数",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "publish": True,
            "mode": "offline",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "succeeded"
    dashboard = body["dashboard"]
    assert dashboard["asset_type"] == "dashboard"
    assert dashboard["publish_state"] == "published"
    package = dashboard["capability_package"]
    assert package["runtime"]["query_url"].startswith(
        "/api/knowledge-assets/assets/dashboard/"
    )
    assert package["runtime"]["direct_database_access"] is False
    assert "dashboard_spec.json" in package["artifacts"]
    assert "tools/query_dashboard_metric.py" in package["artifacts"]
    tool = package["artifacts"]["tools/query_dashboard_metric.py"]
    assert "STUDIO_BASE_URL" in tool
    assert "STUDIO_GOVERNED_QUERY_TOKEN" in tool
    assert "startswith(\"//\")" in tool
    assert "must stay on Studio origin" in tool
    assert "/api/knowledge-assets/assets/dashboard/" in tool
    assert not re.search(r"DATASTUDIO_(API_KEY|BASE_URL)", tool)
    assert "direct_database_access" not in tool
    assert "password" not in response.text.lower()
    assert "client_secret" not in response.text.lower()

    run = client.post(
        f"/api/knowledge-assets/assets/dashboard/{body['dashboard_asset_id']}/query",
        json={"data_view_ids": ["primary_metric"]},
    )
    assert run.status_code == 200
    run_body = run.json()
    assert run_body["contract_version"] == "dashboard.run.v1"
    view = run_body["views"][0]
    assert view["policyDecision"]["decision"] == "allow"
    assert view["result"] == [
        {"store": "VNPTTE", "ticket_count": 56},
        {"store": "SG - ANTA VIVO City", "ticket_count": 9},
    ]
    assert view["sql"]
    assert view["metricDefinition"] == "Count distinct tickets."
    assert view["freshness"]["status"] == "fresh"


def test_dashboard_skill_build_accepts_e2_schema_only_semantic_package(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    space_id = _semantic_skill(
        client,
        asset_id="schema-only-sales",
        governed_result=False,
        artifacts_mdl=True,
    )

    response = client.post(
        "/api/knowledge-assets/build/dashboard-skill",
        json={
            "space_id": space_id,
            "semantic_asset_id": "schema-only-sales",
            "name": "Schema Only Sales Dashboard",
            "intent": "按门店查看销售票数",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "publish": True,
            "mode": "offline",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["askdata"]["data"]["execution"]["mode"] == "schema_only"
    views = body["preview"]["data_views"]
    assert views[0]["rows"] == []
    assert views[0]["sql"]
    assert views[0]["policyDecision"]["decision"] == "allow"


def test_semantic_asset_query_route_matches_e2_governed_contract(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client, artifacts_mdl=True)

    response = client.post(
        "/api/external/assets/semantic_model/oracle-sales/query",
        json={
            "metric": "ticket_count",
            "dimensions": ["store"],
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "agentkit.semantic_query_result.v1"
    data = body["data"]
    assert data["rows"][0]["ticket_count"] == 56
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"]["as_of"] == "2026-08-18T00:00:00Z"


def test_askdata_normalizes_byaan_external_query_result_shape(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client, asset_id="byaan-sales", byaan_shape=True)

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "byaan-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rows"] == [{"store": "VNPTTE", "ticket_count": 56}]
    assert data["metric"]["name"] == "Ticket Count"
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"] == {
        "status": "fresh",
        "as_of": "2026-08-18T06:55:06Z",
    }


def test_askdata_stream_emits_tool_result_final_answer_and_persists_events(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client_with_streaming_runner(
        tmp_path,
        monkeypatch,
        FakeAskTableStreamingRunner(),
    )
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/askdata/stream",
        json={
            "semantic_asset_id": "oracle-sales",
            "message": "列出异常波动，并给出 SQL 和口径证据",
            "metric": "ticket_count",
            "dimensions": ["store"],
        },
    )

    assert response.status_code == 200
    events = _sse_events(response)
    assert any(
        event["content"]["parts"][0].get("functionCall", {}).get("name")
        == "query_semantic_skill"
        for event in events
    )
    response_event = next(
        event
        for event in events
        if event["content"]["parts"][0].get("functionResponse", {}).get("name")
        == "query_semantic_skill"
    )
    tool_payload = response_event["content"]["parts"][0]["functionResponse"]["response"]
    assert tool_payload["success"] is True
    assert "SALES_ORDER" in tool_payload["sql"]
    assert tool_payload["metricDefinition"] == "Count distinct tickets."
    assert tool_payload["policyDecision"]["decision"] == "allow"
    assert tool_payload["freshness"]["status"] == "fresh"
    assert tool_payload["lineage"]
    assert tool_payload["evidence"]
    assert tool_payload["execution"]["direct_database_access"] is False
    assert "secret" not in response.text.lower()

    response_index = events.index(response_event)
    final_text_events = [
        event
        for event in events[response_index + 1 :]
        if event["content"]["parts"][0].get("text")
    ]
    assert final_text_events
    assert "VNPTTE" in final_text_events[-1]["content"]["parts"][0]["text"]

    conversation_id = response_event["conversation_id"]
    persisted = client.get(
        f"/api/knowledge-assets/askdata/conversations/{conversation_id}"
    )
    assert persisted.status_code == 200
    body = persisted.json()
    assert body["semantic_asset_id"] == "oracle-sales"
    assert body["messages"][0]["role"] == "user"
    assert body["tool_events"][0]["tool_name"] == "query_semantic_skill"
    assert body["tool_events"][0]["response"]["sql"]


def test_asktable_stream_compatibility_route_persists_conversation(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client_with_streaming_runner(
        tmp_path,
        monkeypatch,
        FakeAskTableStreamingRunner(),
    )
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/asktable/stream",
        json={
            "semantic_asset_id": "oracle-sales",
            "message": "列出异常波动，并给出 SQL 和口径证据",
            "metric": "ticket_count",
            "dimensions": ["store"],
        },
    )

    assert response.status_code == 200
    events = _sse_events(response)
    response_event = next(
        event
        for event in events
        if event["content"]["parts"][0].get("functionResponse", {}).get("name")
        == "query_semantic_skill"
    )
    conversation_id = response_event["conversation_id"]

    persisted = client.get(
        f"/api/knowledge-assets/asktable/conversations/{conversation_id}"
    )

    assert persisted.status_code == 200
    body = persisted.json()
    assert body["semantic_asset_id"] == "oracle-sales"
    assert body["tool_events"][0]["response"]["sql"]


def test_askdata_stream_blocks_without_model_config(tmp_path, monkeypatch) -> None:
    for name in (
        "MODEL_AGENT_API_KEY",
        "ARK_API_KEY",
        "OPENAI_API_KEY",
        "VEADK_SEMANTIC_BUILDER_API_KEY",
        "VEADK_KNOWLEDGE_AGENT_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/askdata/stream",
        json={
            "semantic_asset_id": "oracle-sales",
            "message": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    events = _sse_events(response)
    response_event = next(
        event
        for event in events
        if event["content"]["parts"][0].get("functionResponse", {}).get("name")
        == "query_semantic_skill"
    )
    tool_payload = response_event["content"]["parts"][0]["functionResponse"]["response"]
    assert tool_payload["success"] is False
    assert tool_payload["status"] == "blocked"
    assert tool_payload["policyDecision"]["decision"] == "deny"
    assert "not configured" in response.text


def _semantic_skill(
    client: TestClient,
    *,
    asset_id: str = "oracle-sales",
    governed_result: bool = True,
    artifacts_mdl: bool = False,
    byaan_shape: bool = False,
    malicious_metadata: bool = False,
    local_sqlite_path: str | None = None,
) -> str:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "Oracle"}).json()
    mdl = {
        "schema": "agentkit.mdl.v1",
        "model": {"id": asset_id, "slug": asset_id, "version": "v1"},
        "entities": [{"id": "sales", "table": "sales_order"}],
        "metrics": [
            {
                "id": "ticket_count",
                "name": "Ticket Count",
                "formula": "count_distinct(ticket_id)",
                "definition": "Count distinct tickets.",
                "time_field": "sell_date",
                "evidence": [{"kind": "metric", "title": "ticket"}],
            }
        ],
        "dimensions": [
            {"id": "store", "name": "Store", "field": "store_name"},
            {"id": "sell_date", "name": "Sell Date", "field": "sell_date", "kind": "time"},
        ],
        "permissions": {
            "raw_sql_fallback": False,
            "permission_hint": "Aggregates only.",
            "denied_fields": [{"field": "customer_phone"}],
        },
        "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
    }
    if malicious_metadata:
        mdl["entities"][0]["table"] = "sales_order; DROP TABLE users"
        mdl["metrics"][0]["formula"] = "count(distinct ticket_id) FROM users --"
        mdl["metrics"][0]["field"] = "ticket_id"
        mdl["metrics"][0]["kind"] = "count_distinct"
        mdl["dimensions"][0]["field"] = "store_name; DROP TABLE users"
    result = {
        "schema": "agentkit.semantic_query_result.v1",
        "data": {
            "rows": [
                {"store": "VNPTTE", "ticket_count": 56},
                {"store": "SG - ANTA VIVO City", "ticket_count": 9},
            ],
            "returnedCount": 2,
            "metric": {
                "id": "ticket_count",
                "name": "Ticket Count",
                "definition": "Count distinct tickets.",
                "formula": "count_distinct(ticket_id)",
            },
            "dimensions": [{"id": "store", "name": "Store", "field": "store_name"}],
            "sql": (
                "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count "
                "FROM SALES_ORDER GROUP BY store_name ORDER BY ticket_count DESC LIMIT 100"
            ),
            "metricDefinition": "Count distinct tickets.",
            "policyDecision": {
                "decision": "allow",
                "reason": "Aggregates only.",
                "raw_sql_fallback": False,
                "denied_fields": [{"field": "customer_phone"}],
            },
            "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
            "lineage": [{"kind": "snapshot", "title": "oracle sanitized"}],
            "evidence": [{"kind": "metric", "title": "ticket"}],
            "execution": {
                "mode": "governed_semantic_skill_fixture",
                "governed_rest": True,
                "direct_database_access": False,
                "raw_sql_fallback": False,
            },
        },
        "mock": False,
    }
    if byaan_shape:
        result = {
            "status": "completed",
            "resolvedMetric": "Ticket Count",
            "result": [{"store": "VNPTTE", "ticket_count": 56}],
            "returnedCount": 1,
            "sql": (
                "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count "
                "FROM SALES_ORDER GROUP BY store_name ORDER BY ticket_count DESC LIMIT 100"
            ),
            "lineage": [{"kind": "snapshot", "title": "oracle sanitized"}],
            "freshness": "2026-08-18T06:55:06Z",
            "policyDecision": "allowed",
        }
    package = {
        "package_type": "semantic_skill",
        "runtime": {
            "transport": "agentkit_governed_rest",
            "query_url": f"/api/knowledge-assets/assets/semantic_model/{asset_id}/query",
            "direct_database_access": False,
            "raw_sql_fallback": False,
        },
        "governance": {
            "raw_sql_fallback": False,
            "usage_policy": {"permission_hint": "Aggregates only."},
        },
    }
    if artifacts_mdl:
        package["artifacts"] = {
            "mdl/models.json": {
                "schema": mdl["schema"],
                "model": mdl["model"],
                "entities": mdl["entities"],
            },
            "mdl/metrics.json": {"schema": "agentkit.mdl.metrics.v1", "metrics": mdl["metrics"]},
            "mdl/dimensions.json": {
                "schema": "agentkit.mdl.dimensions.v1",
                "dimensions": mdl["dimensions"],
            },
            "mdl/permissions.json": {
                "schema": "agentkit.mdl.permissions.v1",
                "permissions": mdl["permissions"],
            },
            "mdl/freshness.json": {
                "schema": "agentkit.mdl.freshness.v1",
                "freshness": mdl["freshness"],
            },
        }
    else:
        package["mdl"] = mdl
    if governed_result:
        package["governed_query_result"] = result
    if local_sqlite_path:
        package["runtime"]["local_sqlite"] = {
            "datasource_id": "test_local_sales",
            "path": local_sqlite_path,
            "view": "sales_order_summary",
            "metric_fields": {"ticket_count": "order_id"},
            "dimension_fields": {"store": "store_name", "sell_date": "order_date"},
            "field_map": {"ticket_id": "order_id", "sell_date": "order_date"},
        }
    response = client.post(
        "/api/knowledge-assets/skill-packages",
        json={
            "space_id": space["id"],
            "asset_type": "semantic_model",
            "asset_id": asset_id,
            "capability_kind": "semantic_skill",
            "name": "Oracle Sales",
            "status": "ready",
            "publish_state": "published",
            "type": "semantic_skill",
            "query_url": f"/api/knowledge-assets/assets/semantic_model/{asset_id}/query",
            "capability_package": package,
            "capabilities": {
                "metrics": ["ticket_count"],
                "dimensions": ["store", "sell_date"],
            },
            "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
            "usage_policy": {"permission_hint": "Aggregates only."},
        },
    )
    assert response.status_code == 201
    return space["id"]
