from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frontend.server.knowledge_domains.runtime import create_app
from frontend.server.knowledge_domains.service import DomainService


def test_upload_persists_source_golden_chunks_and_skill_draft(tmp_path):
    service = DomainService(tmp_path / "domains.sqlite3")
    created = service.create_knowledge_base(
        "workspace", "Policies", "Sales policies", "personal"
    )
    result = service.add_source(
        created["id"],
        filename="policy.md",
        title="Policy",
        description="",
        tags="sales",
        media_type="text/markdown",
        content=b"# Returns\n\nA return requires an order receipt.",
        chunk_strategy="heading",
        trace_id="trace-upload",
    )

    assert result["sourceRevision"]["status"] == "ready"
    assert (
        result["goldenAssetRevision"]["sourceRevisionId"]
        == result["sourceRevision"]["id"]
    )
    assert result["index"]["chunkCount"] == 1
    assert result["chunks"][0]["text"].startswith("# Returns")
    assert result["skillDraft"]["id"] == created["skillDraft"]["id"]
    summary = service.knowledge_base_summary(created["id"])
    assert summary["skillDraft"]["id"] == created["skillDraft"]["id"]
    assert summary["skillDraft"]["manifest"]["spec"]["sourceRevisionRefs"] == [
        result["sourceRevision"]["id"]
    ]
    assert summary["sources"][0]["sourceRevisionId"] == result["sourceRevision"]["id"]
    assert (
        summary["sources"][0]["goldenAssetRevision"]["sourceRevisionId"]
        == result["sourceRevision"]["id"]
    )
    assert summary["contextRef"] == result["knowledgeContextRef"]
    assert (
        service.document(result["document"]["id"])["contextRef"]
        == result["documentContextRef"]
    )


def test_query_returns_real_answer_citations_session_and_trace(tmp_path):
    service = DomainService(tmp_path / "domains.sqlite3")
    created = service.create_knowledge_base("workspace", "Policies", "", "personal")
    service.add_source(
        created["id"],
        filename="policy.txt",
        title="Returns",
        description="",
        tags="",
        media_type="text/plain",
        content=b"Returns require an order receipt.",
        chunk_strategy="auto",
    )

    result = service.ask(created["id"], "What do returns require?", 3)

    assert "order receipt" in result["answer"]
    assert result["citations"][0]["title"] == "Returns"
    assert result["sessionId"]
    assert result["traceId"]
    assert result["queryResultId"]
    assert result["skill"]["runtime"] == "worker3-knowledge"
    persisted = service.knowledge_query_result(created["id"], result["queryResultId"])
    assert persisted["question"] == "What do returns require?"
    assert persisted["answer"] == result["answer"]
    assert persisted["citations"] == result["citations"]
    assert persisted["traceId"] == result["traceId"]


def test_pdf_upload_extracts_text_and_persists_chunks(tmp_path):
    from pypdf import PdfWriter

    import io

    service = DomainService(tmp_path / "domains.sqlite3")
    created = service.create_knowledge_base("workspace", "PDF Policies", "", "personal")
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf = io.BytesIO()
    writer.write(pdf)

    result = service.add_source(
        created["id"],
        filename="policy.pdf",
        title="Policy PDF",
        description="",
        tags="",
        media_type="application/pdf",
        content=pdf.getvalue(),
        chunk_strategy="auto",
    )

    assert result["sourceRevision"]["status"] == "ready"
    assert result["index"]["status"] == "ready"


def test_semantic_invalid_revision_is_rejected_and_valid_revision_has_diff(tmp_path):
    service = DomainService(tmp_path / "domains.sqlite3")
    invalid = service.validate_mdl("model Sales {\n measure bad : unknown_col\n}")
    assert invalid["valid"] is False

    first = service.save_semantic(
        "semantic_sales", "model Sales {\n dimension region : string\n}", 0
    )
    second = service.save_semantic(
        "semantic_sales",
        "model Sales {\n dimension region : string\n measure revenue : number\n}",
        first["revision"],
    )
    assert second["revision"] == 2
    assert "revenue" in second["diff"]["addedFields"]
    assert second["impact"]["affectedAssets"] == []
    assert second["validation"]["schema"]["models"][0]["fields"][1]["name"] == "revenue"
    assert second["goldenAssetRevision"]["assetKind"] == "semantic"
    assert (
        service.get_semantic("semantic_sales")["goldenSchema"]["models"][0]["name"]
        == "Sales"
    )


def test_semantic_source_revision_persists_inferred_golden_schema_and_rejects_unknown_fields(
    tmp_path,
):
    service = DomainService(tmp_path / "domains.sqlite3")
    created = service.create_knowledge_base("workspace", "Sales", "", "personal")
    source = service.add_source(
        created["id"],
        filename="sales.csv",
        title="Sales",
        description="",
        tags="",
        media_type="text/csv",
        content=b"region,revenue,day\nEast,12,2026-08-01\nWest,8,2026-08-02\n",
        chunk_strategy="fixed",
    )
    source_revision_id = source["sourceRevision"]["id"]

    with pytest.raises(ValueError, match="Golden data schema"):
        service.save_semantic(
            "semantic_sales",
            "model Sales {\n measure profit : number\n}",
            0,
            source_revision_id,
        )

    saved = service.save_semantic(
        "semantic_sales",
        "model Sales {\n dimension region : string\n measure revenue : number\n time day : date\n}",
        0,
        source_revision_id,
    )
    assert saved["goldenAssetRevision"]["assetKind"] == "dataset"
    assert saved["goldenAssetRevision"]["sourceRevisionRefs"] == [source_revision_id]
    assert saved["goldenSchema"] == {
        "sourceRevisionId": source_revision_id,
        "columns": ["region", "revenue", "day"],
        "numeric": ["revenue"],
        "dimensions": ["region"],
        "dates": ["day"],
        "rowCount": 2,
    }
    loaded = service.get_semantic("semantic_sales")
    assert loaded["goldenAssetRevision"]["id"] == saved["goldenAssetRevision"]["id"]
    assert loaded["sourceRevisionId"] == source_revision_id
    assert loaded["goldenSchema"]["columns"] == ["region", "revenue", "day"]
    assert loaded["contextRef"] == saved["contextRef"]
    other = service.save_semantic(
        "semantic_sales_other",
        "model Sales {\n dimension region : string\n measure revenue : number\n time day : date\n}",
        0,
        source_revision_id,
    )
    assert other["goldenAssetRevision"]["id"] != saved["goldenAssetRevision"]["id"]


def test_graph_mutation_and_query_are_durable(tmp_path):
    service = DomainService(tmp_path / "domains.sqlite3")
    service.mutate_graph(
        "graph_sales",
        {
            "operation": "upsert_entity",
            "entity": {"id": "customer", "type": "Customer"},
        },
    )
    service.mutate_graph(
        "graph_sales",
        {
            "operation": "upsert_entity",
            "entity": {"id": "order", "type": "Order"},
        },
    )
    mutated = service.mutate_graph(
        "graph_sales",
        {
            "operation": "upsert_relationship",
            "relationship": {
                "id": "places",
                "from": "customer",
                "to": "order",
                "type": "PLACES",
            },
        },
    )
    assert mutated["revision"] == 3
    queried = service.query_graph(
        "graph_sales", {"mode": "path", "from": "customer", "to": "order"}
    )
    assert queried["relationships"][0]["id"] == "places"
    assert queried["entities"] == ["customer", "order"]
    assert queried["queryResultId"]
    assert (
        service.graph_query_result("graph_sales", queried["queryResultId"]) == queried
    )
    assert service.graph("graph_sales")["revision"] == 3
    assert service.graph("graph_sales")["contextRef"] == mutated["contextRef"]
    with pytest.raises(ValueError):
        service.mutate_graph(
            "graph_sales",
            {
                "operation": "upsert_relationship",
                "relationship": {
                    "id": "invalid",
                    "from": "customer",
                    "to": "missing",
                    "type": "PLACES",
                },
            },
        )


def test_graph_query_rejects_missing_path_or_neighbor_target(tmp_path):
    service = DomainService(tmp_path / "domains.sqlite3")
    with pytest.raises(ValueError):
        service.query_graph("graph_sales", {"mode": "path", "from": "customer"})
    with pytest.raises(ValueError):
        service.query_graph("graph_sales", {"mode": "neighbors"})


def test_http_graph_path_query_preserves_from_alias(tmp_path):
    client = TestClient(create_app(database_path=tmp_path / "domains.sqlite3"))
    for entity_id, entity_type in (("customer", "Customer"), ("order", "Order")):
        response = client.post(
            "/api/knowledge-domains/v1/graphs/graph_sales/mutations",
            json={
                "operation": "upsert_entity",
                "entity": {"id": entity_id, "type": entity_type},
            },
        )
        assert response.status_code == 200
    response = client.post(
        "/api/knowledge-domains/v1/graphs/graph_sales/mutations",
        json={
            "operation": "upsert_relationship",
            "relationship": {
                "id": "places",
                "from": "customer",
                "to": "order",
                "type": "PLACES",
            },
        },
    )
    assert response.status_code == 200
    queried = client.post(
        "/api/knowledge-domains/v1/graphs/graph_sales/queries",
        json={"mode": "path", "from": "customer", "to": "order"},
    )
    assert queried.status_code == 200
    assert queried.json()["entities"] == ["customer", "order"]
    result_id = queried.json()["queryResultId"]
    persisted = client.get(
        f"/api/knowledge-domains/v1/graphs/graph_sales/queries/{result_id}"
    )
    assert persisted.status_code == 200
    assert persisted.json() == queried.json()


def test_http_query_result_and_semantic_source_revision_round_trips(tmp_path):
    client = TestClient(create_app(database_path=tmp_path / "domains.sqlite3"))
    created = client.post(
        "/api/knowledge-domains/v1/knowledge-bases",
        json={"name": "Sales", "description": "", "scope": "personal"},
    )
    source = client.post(
        f"/api/knowledge-domains/v1/knowledge-bases/{created.json()['id']}/sources",
        files={"file": ("sales.csv", b"region,revenue\nEast,12\n", "text/csv")},
        data={
            "title": "Sales",
            "description": "",
            "tags": "",
            "chunk_strategy": "fixed",
        },
    )
    assert source.status_code == 200
    source_revision_id = source.json()["sourceRevision"]["id"]
    source_revisions = client.get("/api/knowledge-domains/v1/semantic-source-revisions")
    assert source_revisions.status_code == 200
    assert source_revisions.json()["items"][0]["id"] == source_revision_id

    answer = client.post(
        f"/api/knowledge-domains/v1/knowledge-bases/{created.json()['id']}/query",
        json={"question": "What is revenue?", "topK": 3},
    )
    assert answer.status_code == 200
    persisted = client.get(
        f"/api/knowledge-domains/v1/knowledge-bases/{created.json()['id']}/query-results/"
        f"{answer.json()['queryResultId']}"
    )
    assert persisted.status_code == 200
    assert persisted.json()["answer"] == answer.json()["answer"]

    semantic = client.post(
        "/api/knowledge-domains/v1/semantic-models/sales/revisions",
        json={
            "mdl": "model Sales {\n dimension region : string\n measure revenue : number\n}",
            "expectedRevision": 0,
            "sourceRevisionId": source_revision_id,
        },
    )
    assert semantic.status_code == 200
    assert semantic.json()["goldenSchema"]["columns"] == ["region", "revenue"]


def test_http_upload_and_credential_blocked_feishu(tmp_path):
    client = TestClient(create_app(database_path=tmp_path / "domains.sqlite3"))
    created = client.post(
        "/api/knowledge-domains/v1/knowledge-bases",
        json={"name": "Policies", "description": "", "scope": "personal"},
    )
    assert created.status_code == 200
    uploaded = client.post(
        f"/api/knowledge-domains/v1/knowledge-bases/{created.json()['id']}/sources",
        files={
            "file": ("policy.md", b"Returns require an order receipt.", "text/markdown")
        },
        data={
            "title": "Policy",
            "description": "",
            "tags": "",
            "chunk_strategy": "auto",
        },
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["document"]["content"] == "Returns require an order receipt."
    document = client.get(
        f"/api/knowledge-domains/v1/documents/{uploaded.json()['document']['id']}"
    )
    assert document.status_code == 200
    assert document.json()["chunks"][0]["text"] == "Returns require an order receipt."
    feishu = client.post(
        "/api/knowledge-domains/v1/connectors/feishu/inspect",
        json={"url": "https://feishu.cn/docx/abc"},
    )
    assert feishu.status_code == 200
    assert feishu.json()["status"] == "credential_blocked"


def test_credentialed_feishu_inspect_and_sync_use_server_connector(tmp_path):
    calls = []

    def fetcher(url, credential):
        calls.append((url, credential))
        return {
            "documentId": "docx-token",
            "title": "退货流程",
            "content": "# 退货流程\n\n需要订单号和审批人。",
            "filename": "feishu-docx-token.md",
            "url": url,
        }

    client = TestClient(
        create_app(
            database_path=tmp_path / "domains.sqlite3",
            feishu_fetcher=fetcher,
        )
    )
    created = client.post(
        "/api/knowledge-domains/v1/knowledge-bases",
        json={"name": "Policies", "description": "", "scope": "personal"},
    )
    url = "https://feishu.cn/docx/docx-token"
    headers = {"Authorization": "Bearer server-credential"}

    inspected = client.post(
        "/api/knowledge-domains/v1/connectors/feishu/inspect",
        json={"url": url},
        headers=headers,
    )
    assert inspected.status_code == 200
    assert inspected.json()["status"] == "ready"
    assert inspected.json()["document"]["id"] == "docx-token"

    synced = client.post(
        f"/api/knowledge-domains/v1/knowledge-bases/{created.json()['id']}/sources/feishu:sync",
        json={"url": url, "includeChildren": True},
        headers=headers,
    )
    assert synced.status_code == 200
    assert synced.json()["document"]["title"] == "退货流程"
    assert synced.json()["connector"]["includeChildren"] is True
    assert calls == [(url, "server-credential"), (url, "server-credential")]


def test_http_domain_routes_enforce_authenticated_workspace_and_role(tmp_path):
    def identity(request):
        return (
            request.headers.get("X-Test-Workspace", "workspace-a"),
            request.headers.get("X-Test-Role", "editor"),
        )

    client = TestClient(
        create_app(
            database_path=tmp_path / "domains.sqlite3",
            identity_resolver=identity,
        )
    )
    created = client.post(
        "/api/knowledge-domains/v1/knowledge-bases",
        json={"name": "Private", "description": "", "scope": "personal"},
    )
    assert created.status_code == 200
    assert (
        client.get(
            f"/api/knowledge-domains/v1/knowledge-bases/{created.json()['id']}",
            headers={"X-Test-Workspace": "workspace-b"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/knowledge-domains/v1/graphs/private-graph/mutations",
            json={
                "operation": "upsert_entity",
                "entity": {"id": "customer", "type": "Customer"},
            },
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/knowledge-domains/v1/graphs/private-graph",
            headers={"X-Test-Workspace": "workspace-b"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/knowledge-domains/v1/graphs/viewer-graph/mutations",
            json={
                "operation": "upsert_entity",
                "entity": {"id": "customer", "type": "Customer"},
            },
            headers={"X-Test-Role": "viewer"},
        ).status_code
        == 403
    )
