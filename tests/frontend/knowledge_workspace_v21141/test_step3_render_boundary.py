from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.contracts import (
    DashboardViewModel,
    DashboardKpi,
    ChartViewModel,
    ChartSeries,
    KnowledgeViewModel,
    SemanticViewModel,
    SchemaRef,
    StorageRef,
)
from frontend.server.knowledge_assets.repository import SqliteKnowledgeAssetRepository


def test_trusted_renderers_are_template_specific_and_non_executable() -> None:
    app = KnowledgeAssetApplication(SqliteKnowledgeAssetRepository(":memory:"))
    models = [
        (
            "knowledge",
            KnowledgeViewModel(answer="<img src=x onerror=alert(1)>"),
        ),
        (
            "semantic",
            SemanticViewModel(
                schema_ref=SchemaRef(uri="local://schema", version="1", sha256="0" * 64),
                metric_refs=["revenue"],
            ),
        ),
        (
            "chart",
            ChartViewModel(
                title="<script>unsafe</script>",
                x_field="row",
                y_field="value",
                series=[ChartSeries(name="<iframe>", points=[("1", 1.0)])],
                data_ref=StorageRef(
                    uri="local://data",
                    kind="object",
                    sha256="0" * 64,
                    media_type="application/json",
                ),
            ),
        ),
        (
            "dashboard",
            DashboardViewModel(
                kpis=[DashboardKpi(key="rows", label="Rows", value=1)],
                data_ref=StorageRef(
                    uri="local://data",
                    kind="object",
                    sha256="0" * 64,
                    media_type="application/json",
                ),
            ),
        ),
    ]
    for template, model in models:
        output = app._trusted_html(template, model).decode()
        assert f'data-renderer="{template}-v1"' in output
        assert "<script" not in output.lower()
        assert "<iframe" not in output.lower()
        assert "<img" not in output.lower()
        assert "&lt;img" in output.lower() if template == "knowledge" else True
