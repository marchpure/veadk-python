from __future__ import annotations

from frontend.server.knowledge_assets.contract_views import (
    ChartSeries,
    ChartViewModel,
    SkillViewManifest,
    SkillViewRevision,
    ViewIntent,
)
from frontend.server.knowledge_assets.contract_base import SchemaRef, StorageRef
from frontend.server.knowledge_assets.repository.sqlite import (
    SqliteKnowledgeAssetRepository,
)


def test_bootstrap_exposes_latest_real_skill_view_revision(tmp_path):
    repository = SqliteKnowledgeAssetRepository(tmp_path / "knowledge.db")
    bootstrap = repository.bootstrap("workspace-1", "member")
    assert "skillViewRevision" not in bootstrap.workspace_data

    # This test uses the repository contract directly; the view content is
    # deliberately real typed output, not a frontend fixture.
    view = SkillViewRevision(
        id="view-real",
        skill_revision_id="draft-real:1",
        revision=1,
        manifest=SkillViewManifest(
            id="manifest-real",
            skill_revision_id="draft-real:1",
            renderer_ref="renderer://chart/v1",
            view_model_schema_ref=SchemaRef(
                uri="local://schema/view",
                version="1",
                sha256="0" * 64,
            ),
            allowed_components=["ChartView"],
        ),
        intent=ViewIntent(
            id="intent-real",
            skill_id="draft-real",
            skill_revision=1,
            template="chart",
            purpose="compare",
            result_ref="local://result/real",
        ),
        view_model=ChartViewModel(
            title="Regional revenue",
            x_field="region",
            y_field="revenue",
            series=[ChartSeries(name="analysis", points=[("East", 140.0), ("West", 90.0)])],
            data_ref=StorageRef(
                uri="local://golden/real",
                kind="object",
                sha256="1" * 64,
                media_type="application/x-ndjson",
                bytes=24,
            ),
        ),
        created_at="2026-08-25T00:00:00Z",
    )
    # The view is only exposed when its owning draft exists. This preserves
    # the authorization/lineage boundary of the bootstrap contract.
    repository._connection.execute(
        "INSERT INTO skill_drafts (id, workspace_id, name, description, revision, created_at, updated_at, manifest_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "draft-real",
            "workspace-1",
            "Regional revenue",
            "",
            1,
            "2026-08-25T00:00:00Z",
            "2026-08-25T00:00:00Z",
            "{}",
        ),
    )
    repository.save_skill_view_revision(view)
    bootstrap = repository.bootstrap("workspace-1", "member")
    assert bootstrap.workspace_data["skillViewRevision"]["id"] == "view-real"
    assert bootstrap.workspace_data["skillViewRevision"]["viewModel"]["template"] == "chart"
