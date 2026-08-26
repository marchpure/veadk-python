"""Independent local acceptance harness for the six formal Skill HTML bundles."""

from __future__ import annotations

from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
from pathlib import Path
import tempfile

from .contract_views import (
    ChartSeries,
    DashboardChart,
    DashboardFilter,
    DashboardKpi,
    DashboardViewModel,
    GraphEdge,
    GraphNode,
    GraphOntologyViewModel,
    KnowledgeCitation,
    KnowledgeViewModel,
    MonitoringObservationView,
    MonitoringViewModel,
    SchemaRef,
    SemanticViewField,
    SemanticViewModel,
    SemanticViewRelationship,
    SopStepEvidence,
    SopStepResult,
    SopViewModel,
    StorageRef,
    ViewCell,
    ViewField,
)
from .trusted_renderers import compile_with_visual_feedback

ZERO = "0" * 64


def acceptance_models() -> dict[str, object]:
    data = StorageRef(
        uri="local://acceptance/fixture-revision-7",
        kind="object",
        sha256=ZERO,
        media_type="text/csv",
    )
    schema = SchemaRef(uri="local://acceptance/schema-7", version="7", sha256=ZERO)
    return {
        "dashboard": DashboardViewModel(
            title="Operations overview",
            fields=[
                ViewField(name="period", label="Period", data_type="date"),
                ViewField(name="volume", label="Volume", data_type="number"),
            ],
            kpis=[
                DashboardKpi(key="volume", label="Volume", value=184, trend="up"),
                DashboardKpi(
                    key="success", label="Success rate", value="98.4", unit="%"
                ),
                DashboardKpi(
                    key="backlog", label="Backlog", value=12, unit="items", trend="down"
                ),
            ],
            charts=[
                DashboardChart(
                    chart_id="volume-trend",
                    title="Volume by period",
                    x_field="period",
                    y_field="volume",
                    chart_type="line",
                    series=[
                        ChartSeries(
                            name="Volume", points=[("W1", 72), ("W2", 109), ("W3", 184)]
                        )
                    ],
                ),
                DashboardChart(
                    chart_id="volume-by-region",
                    title="Volume by region",
                    x_field="region",
                    y_field="volume",
                    chart_type="bar",
                    series=[
                        ChartSeries(
                            name="Volume",
                            points=[("North", 88), ("South", 54), ("West", 42)],
                        )
                    ],
                ),
            ],
            rows=[
                [
                    ViewCell(field="period", value="W1"),
                    ViewCell(field="volume", value=72),
                ],
                [
                    ViewCell(field="period", value="W3"),
                    ViewCell(field="volume", value=184),
                ],
            ],
            filters=[
                DashboardFilter(field="period", operator="in", values=["W1", "W3"])
            ],
            insights=[
                "Volume rose across the pinned periods; the largest typed change is W2 → W3."
            ],
            freshness_at="fixture-revision-7",
            data_ref=data,
        ),
        "semantic": SemanticViewModel(
            schema_ref=schema,
            entities=["Order", "Customer", "Product"],
            fields=[
                SemanticViewField(
                    name="order_id", role="entity", source_field="order_id"
                ),
                SemanticViewField(
                    name="amount",
                    role="measure",
                    aggregation="sum",
                    unit="CNY",
                    source_field="amount",
                ),
            ],
            metric_refs=["sum(amount)"],
            dimension_refs=["order_id"],
            relationships=[
                SemanticViewRelationship(
                    source="Order",
                    target="Customer",
                    relation="belongs_to",
                    join_type="many_to_one",
                    evidence_locator="schema://order-customer",
                ),
                SemanticViewRelationship(
                    source="Order",
                    target="Product",
                    relation="contains",
                    join_type="many_to_one",
                    evidence_locator="schema://order-product",
                ),
                SemanticViewRelationship(
                    source="Customer",
                    target="Order",
                    relation="places",
                    join_type="one_to_many",
                    evidence_locator="schema://customer-order",
                ),
            ],
            mdl="entity Order { measure amount: number { aggregate: sum } }",
        ),
        "sop": SopViewModel(
            title="Signal triage",
            trigger="A diagnostic signal is received",
            scope="service / production",
            step_results=[
                SopStepResult(
                    step_id="collect",
                    title="Collect diagnostic signal",
                    status="succeeded",
                    evidence=[
                        SopStepEvidence(
                            kind="tool_result",
                            locator="tool://signal",
                            summary="Signal payload pinned",
                        )
                    ],
                ),
                SopStepResult(
                    step_id="confirm",
                    title="Confirm remediation",
                    status="awaiting_confirmation",
                    tool_refs=["diagnostic.signal.read"],
                    input_summary="signal_id=fixture-signal-7",
                    evidence=[
                        SopStepEvidence(
                            kind="decision",
                            locator="decision://threshold",
                            summary="Threshold requires review",
                        )
                    ],
                ),
                SopStepResult(
                    step_id="history",
                    title="Compare historical incidents",
                    status="succeeded",
                    branch="true",
                    tool_refs=["ticket.history.search"],
                    input_summary="scope=service / production",
                    evidence=[
                        SopStepEvidence(
                            kind="source_citation",
                            locator="tickets://history/r4",
                            summary="Two related incidents found",
                        )
                    ],
                ),
            ],
            recommendation="Review the proposed remediation with the on-call owner.",
            outputs={"severity": "warning", "confidence": 0.91},
            run_state="awaiting_confirmation",
        ),
        "knowledge": KnowledgeViewModel(
            answer="The approved procedure requires two checks before release.",
            citations=[
                KnowledgeCitation(
                    citation_id=f"c-{index}",
                    source_revision_id=f"source-r{index}",
                    title=title,
                    locator=f"document://handbook#{index}.1",
                )
                for index, title in enumerate(
                    [
                        "Release handbook",
                        "Rollback policy",
                        "Change calendar",
                        "Incident review",
                        "Access standard",
                    ],
                    1,
                )
            ],
        ),
        "graph-ontology": GraphOntologyViewModel(
            nodes=[
                GraphNode(
                    id=f"node-{index}",
                    label=f"Node {index}",
                    entity_type="service" if index % 2 else "resource",
                )
                for index in range(12)
            ],
            edges=[
                GraphEdge(
                    source=f"Node {index}",
                    target=f"Node {(index + 1) % 12}",
                    relation="depends_on",
                    confidence=0.8,
                    evidence_locator=f"topology://edge-{index}",
                )
                for index in range(15)
            ],
            evidence_locators=["topology://revision-3"],
        ),
        "monitoring": MonitoringViewModel(
            metric_refs=["queue_latency"],
            values=[("10:00", 110), ("10:05", 142), ("10:10", 184)],
            observations=[
                MonitoringObservationView(
                    metric="queue_latency",
                    latest=184,
                    previous=142,
                    change_rate=0.30,
                    duration_seconds=300,
                    freshness_at=datetime.now().isoformat(),
                    last_good_revision_id="observation-r12",
                ),
                MonitoringObservationView(
                    metric="success_rate",
                    latest=0.984,
                    previous=0.991,
                    change_rate=-0.007,
                    duration_seconds=300,
                    freshness_at=datetime.now().isoformat(),
                    last_good_revision_id="observation-r12",
                ),
                MonitoringObservationView(
                    metric="call_volume",
                    latest=1840,
                    previous=1720,
                    change_rate=0.069,
                    duration_seconds=300,
                    freshness_at=datetime.now().isoformat(),
                    last_good_revision_id=None,
                ),
            ],
            alerts=["queue latency crossed warning threshold"],
            failure_trace=["refresh-r13: source response delayed"],
            call_volume=1840,
            success_rate=0.984,
            latency_ms=184,
            stale=True,
            status="stale",
        ),
    }


def alternate_acceptance_models() -> dict[str, object]:
    """A second structural fixture set, not used by production defaults."""

    base = acceptance_models()
    dashboard = base["dashboard"].model_copy(
        update={
            "title": "Warehouse capacity",
            "kpis": [
                DashboardKpi(key="capacity", label="Capacity", value=62, unit="%"),
                DashboardKpi(
                    key="throughput", label="Throughput", value=418, unit="units"
                ),
            ],
            "charts": [
                DashboardChart(
                    chart_id="capacity-by-site",
                    title="Capacity by site",
                    x_field="site",
                    y_field="capacity",
                    chart_type="bar",
                    series=[
                        ChartSeries(
                            name="Capacity", points=[("A", 42), ("B", 62), ("C", 78)]
                        )
                    ],
                ),
                DashboardChart(
                    chart_id="throughput-distribution",
                    title="Throughput distribution",
                    x_field="bucket",
                    y_field="throughput",
                    chart_type="area",
                    series=[
                        ChartSeries(
                            name="Throughput",
                            points=[("0-2h", 110), ("2-4h", 210), ("4h+", 98)],
                        )
                    ],
                ),
            ],
            "insights": [
                "Capacity is uneven across sites; the typed distribution points to a mid-window bottleneck."
            ],
        }
    )
    semantic = base["semantic"].model_copy(
        update={
            "entities": ["Shipment", "Warehouse", "Carrier", "Route"],
            "metric_refs": ["avg(transit_hours)", "count(shipment_id)"],
        }
    )
    sop = base["sop"].model_copy(
        update={
            "title": "Store hygiene inspection",
            "trigger": "A scheduled store inspection begins",
            "scope": "store / dining floor",
        }
    )
    knowledge = base["knowledge"].model_copy(
        update={
            "answer": "The inspection standard requires a documented check, owner assignment, and follow-up evidence."
        }
    )
    graph = base["graph-ontology"].model_copy(
        update={
            "nodes": [
                GraphNode(
                    id=f"asset-{index}", label=f"Asset {index}", entity_type="asset"
                )
                for index in range(14)
            ]
        }
    )
    monitoring = base["monitoring"].model_copy(
        update={
            "metric_refs": ["error_rate", "queue_depth"],
            "status": "alert",
            "stale": False,
            "alerts": [
                "error rate crossed critical threshold",
                "queue depth is rising",
            ],
        }
    )
    return {
        "dashboard": dashboard,
        "semantic": semantic,
        "sop": sop,
        "knowledge": knowledge,
        "graph-ontology": graph,
        "monitoring": monitoring,
    }


def write_acceptance_site(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    links: list[str] = []
    attempts: list[dict[str, object]] = []
    scenarios = (
        ("primary", acceptance_models(), "executive"),
        ("alternate", alternate_acceptance_models(), "operational"),
    )
    for scenario, models, direction in scenarios:
        for template, model in models.items():
            filename = f"{template.replace('-', '_')}-{scenario}.html"
            compiled = compile_with_visual_feedback(
                template,
                model,
                data_revision_refs=[f"fixture-{scenario}-7"],
                direction=direction,
            )
            (output / filename).write_bytes(compiled.html)
            attempts.append(
                {
                    "template": template,
                    "scenario": scenario,
                    "selectedDirection": compiled.direction,
                    "attempts": [
                        {
                            "round": item.round,
                            "direction": item.direction,
                            "score": item.score,
                            "corePass": item.core_pass,
                            "reasons": list(item.reasons),
                        }
                        for item in compiled.attempts
                    ],
                }
            )
            links.append(f'<li><a href="{filename}">{template} · {scenario}</a></li>')
    (output / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>W3 Skill HTML acceptance</title>"
        "<style>body{font:16px system-ui;max-width:720px;margin:60px auto}li{margin:14px 0}"
        "a{color:#1769e0}</style><h1>W3 Skill HTML acceptance</h1>"
        "<p>Six formal immutable HTML compiler outputs from typed acceptance ViewModels.</p>"
        f"<ul>{''.join(links)}</ul>",
        encoding="utf-8",
    )
    import json

    (output / "visual-evaluation.json").write_text(
        json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix="veadk-w3-html-"))
    write_acceptance_site(output)
    print(f"Acceptance site: {output / 'index.html'}")
    if args.serve:
        import os

        os.chdir(output)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), SimpleHTTPRequestHandler)
        print(f"http://127.0.0.1:{args.port}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()


if __name__ == "__main__":
    main()
