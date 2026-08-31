from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_artifact import build_html, metrics, read_rows  # noqa: E402


def test_dashboard_metrics_are_derived_from_csv() -> None:
    result = metrics(read_rows())
    assert result["store_count"] == 2
    assert result["average"] == 4.25
    assert result["exceptions"] == 2
    assert result["in_progress"] == 2


def test_dashboard_contains_gold_contract_and_no_external_fetch() -> None:
    document = build_html()
    assert document.count('data-kpi=') == 4
    assert document.count('data-chart=') == 2
    assert "<svg" in document
    assert "fetch(" not in document
    assert "haidilao-inspections.csv" in document
