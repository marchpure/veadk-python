from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "tests/fixtures/knowledge_step3_w4/capability-matrix.json"
OLD_ROUTES = ROOT / "frontend/src/knowledge-workspace/frozen-ui/prototype-route.json"
MAIN_MATRIX = (
    ROOT / "docs/knowledge-assets/implementation/STEP3_PROTOTYPE_CAPABILITY_MATRIX.yaml"
)

NEW_STATE_URLS = {
    "/?file=welcome",
    "/?file=add_data&step=1",
    "/?file=add_data&step=2&source=lark_doc",
    "/?file=add_data&step=2&source=postgresql",
    "/?file=add_data&step=2&source=create_custom",
    "/?modal=v212_entry",
    "/?file=journey_knowledge&step=1&pane=open",
    "/?file=journey_knowledge&step=1&error_state=auth_failed&pane=open",
    "/?file=journey_knowledge&step=7&pane=open",
    "/?file=journey_knowledge&step=8&pane=open",
    "/?file=journey_oracle_excel&step=1&pane=open",
    "/?file=journey_oracle_excel&step=4&pane=open",
    "/?file=journey_oracle_excel&step=7&pane=open",
    "/?file=journey_oracle_excel&step=8&pane=open",
    "/?file=journey_web_api&step=1&pane=open",
    "/?file=journey_web_api&step=7&pane=open",
    "/?file=journey_web_api&step=8&pane=open",
    "/?file=journey_financial_monitor&step=1&pane=open",
    "/?file=journey_financial_monitor&step=6&pane=open",
    "/?file=journey_financial_monitor&step=7&pane=open",
    "/?file=journey_financial_monitor&step=8&pane=open",
    "/?file=journey_workday_mcp&step=1&pane=open",
    "/?file=journey_workday_mcp&step=5&error_state=render_error&pane=open",
    "/?file=journey_workday_mcp&step=7&pane=open",
    "/?file=journey_workday_mcp&step=8&pane=open",
    "/?file=res_dash_finance",
    "/?file=res_dash_finance&modal=action_policy&policy_id=pol_finance",
    "/?file=res_dash_east",
    "/?file=res_dash_east&modal=publish_agent",
    "/?file=res_dash_east&modal=agent_selector",
    "/?file=evaluation_detail&eval_target=res_dash_east",
    "/?file=kg_sales",
    "/?file=kg_sales&pane=open&chat=planning",
    "/?file=res_dash_recruitment",
    "/?file=res_dash_recruitment&dash_tab=action",
    "/?file=res_dash_recruitment&dash_tab=review",
    "/?file=res_dash_recruitment&dash_tab=decision",
    "/?file=res_dash_recruitment&dash_tab=action&highlight_target=todo_vn_hc_1",
    "/?file=res_dash_recruitment&modal=action_policy",
    "/?file=semantic_sales",
    "/?file=res_sample_postgres",
    "/?file=kb_sales",
    "/?file=kb_sales&modal=publish_agent",
}


def route_urls(node: dict[str, object]) -> set[str]:
    urls = {str(node["state_url"])}
    for child in node.get("children", []):
        urls |= route_urls(child)
    return urls


def test_all_43_states_are_uniquely_and_legally_classified() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows = matrix["states"]
    urls = [row["stateUrl"] for row in rows]
    allowed = {
        "STEP3_REAL",
        "STEP3_GATED",
        "STEP4_DEFERRED",
        "EXTERNAL_CREDENTIAL_BLOCKED",
    }
    assert len(rows) == matrix["newRouteCount"] == 43
    assert len(urls) == len(set(urls))
    assert set(urls) == NEW_STATE_URLS
    assert {row["status"] for row in rows} <= allowed


def test_complete_23_state_route_manifest_is_preserved() -> None:
    old_urls = route_urls(json.loads(OLD_ROUTES.read_text(encoding="utf-8")))
    assert len(old_urls) == 23
    assert old_urls <= NEW_STATE_URLS


def test_step4_actions_are_deferred_not_claimed_real() -> None:
    rows = json.loads(MATRIX.read_text(encoding="utf-8"))["states"]
    deferred_journeys = {
        "journey_knowledge",
        "journey_oracle_excel",
        "journey_financial_monitor",
        "journey_workday_mcp",
    }
    step4 = [
        row
        for row in rows
        if (
            "step=8" in row["stateUrl"]
            and any(journey in row["stateUrl"] for journey in deferred_journeys)
        )
        or "publish_agent" in row["stateUrl"]
        or "agent_selector" in row["stateUrl"]
    ]
    assert step4
    assert all(row["status"] == "STEP4_DEFERRED" for row in step4)


def test_worker_matrix_matches_main_route_classifications() -> None:
    main = MAIN_MATRIX.read_text(encoding="utf-8")
    main_rows = dict(
        re.findall(
            r'stateUrl: "([^"]+)".*?status: '
            r"(STEP3_REAL|STEP3_GATED|STEP4_DEFERRED|EXTERNAL_CREDENTIAL_BLOCKED)",
            main,
        )
    )
    worker_rows = {
        row["stateUrl"]: row["status"]
        for row in json.loads(MATRIX.read_text(encoding="utf-8"))["states"]
    }
    assert main_rows == worker_rows


def test_production_graph_has_no_browser_business_state_or_iframe() -> None:
    production = ROOT / "frontend/src/knowledge-workspace/production"
    findings: list[str] = []
    patterns = {
        "localStorage": re.compile(r"\blocalStorage\b"),
        "sessionStorage": re.compile(r"\bsessionStorage\b"),
        "iframe": re.compile(r"<iframe|\bcreateElement\(['\"]iframe"),
        "hardcoded success": re.compile(r"已成功发布|模拟发布|调用成功"),
    }
    for path in production.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        source = path.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            if pattern.search(source):
                findings.append(f"{path.relative_to(ROOT)}: {label}")
    assert findings == []


def test_production_adapter_only_uses_bff_base_path() -> None:
    adapter = (
        ROOT / "frontend/src/knowledge-workspace/production/httpAdapter.ts"
    ).read_text(encoding="utf-8")
    assert 'basePath ?? "/api/knowledge-assets"' in adapter
    assert "http://" not in adapter
    assert "https://" not in adapter
