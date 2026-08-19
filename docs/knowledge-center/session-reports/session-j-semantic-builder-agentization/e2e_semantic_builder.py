from __future__ import annotations

import json
import time
from pathlib import Path
from urllib import request
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent
SCREENSHOTS = ROOT / "screenshots"
API_URL = "http://127.0.0.1:8000"
BASE_URL = API_URL
WORKBENCH_SELECTOR = "[data-testid='semantic-builder-workspace']"
BROWSER_QUESTION = "Browser E2E sales by month"
BROWSER_SQL = "select strftime('%Y-%m', order_date) as month, sum(amount) as sales from sales_order group by 1"
BROWSER_INSTRUCTION = (
    "Use order_date as the default sales time grain for browser E2E checks."
)
BROWSER_FEEDBACK = "把 ticket_count 定义改成 distinct order_id，并隐藏 customer_phone。"
BROWSER_VIEW_NAME = "Browser monthly sales trend"
BROWSER_VIEW_ID = "view_browser_monthly_sales_trend"


def api_get(path: str) -> dict:
    with request.urlopen(f"{API_URL}{path}", timeout=20) as response:
        return json.load(response)


def api_post(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=20) as response:
        return json.load(response)


def seed_session_space() -> dict:
    suffix = str(int(time.time()))
    space = api_post(
        "/api/knowledge-assets/spaces",
        {
            "name": f"Session J E2E {suffix}",
            "description": "Semantic builder browser verification",
            "region": "local",
        },
    )
    source = api_post(
        "/api/knowledge-assets/sources",
        {
            "space_id": space["id"],
            "source_type": "database",
            "provider": "sqlite",
            "name": "Sales DB",
            "description": "Seeded schema source for Session J browser gate.",
            "status": "ready",
            "capabilities": {"can_build_semantic_skill": True},
            "metadata": {"profile": "browser-e2e"},
        },
    )
    doc = api_post(
        "/api/knowledge-assets/sources",
        {
            "space_id": space["id"],
            "source_type": "file",
            "provider": "manual",
            "name": "Sales playbook",
            "description": "Ticket Count means distinct order IDs by Store.",
            "status": "indexed",
            "metadata": {
                "content": "Ticket Count means distinct order IDs. Revenue is sum(amount). Store is the reporting entity. Use order_date for monthly grain."
            },
        },
    )
    snapshot = api_post(
        "/api/knowledge-assets/snapshots",
        {
            "space_id": space["id"],
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": f"sales-schema-{suffix}",
            "capability_kind": "retrieval_binding",
            "name": "Sales schema snapshot",
            "kind": "schema_snapshot",
            "schema": {
                "tables": [
                    {
                        "name": "sales_order",
                        "primary_key": ["order_id"],
                        "columns": [
                            {"name": "order_id", "type": "number", "primary_key": True},
                            {"name": "store_id", "type": "number"},
                            {"name": "order_date", "type": "date"},
                            {"name": "amount", "type": "decimal"},
                            {"name": "customer_phone", "type": "varchar"},
                        ],
                    },
                    {
                        "name": "store",
                        "primary_key": ["store_id"],
                        "columns": [
                            {"name": "store_id", "type": "number", "primary_key": True},
                            {"name": "store_name", "type": "varchar"},
                            {"name": "region", "type": "varchar"},
                        ],
                    },
                ]
            },
            "profile": {
                "snapshot": {
                    "id": f"browser-e2e-{suffix}",
                    "hash": f"session-j-{suffix}",
                }
            },
        },
    )
    return {"space": space, "source": source, "doc": doc, "snapshot": snapshot}


def click_text(page: Page, text: str) -> None:
    target = page.get_by_text(text, exact=True).first
    expect(target).to_be_visible(timeout=20_000)
    target.click()


def open_knowledge_center(page: Page, space_name: str | None = None) -> None:
    page.goto(BASE_URL, wait_until="networkidle")
    if page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").is_visible(
        timeout=3_000
    ):
        page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").fill("sessionj")
        page.get_by_label("进入").click()
        expect(page.get_by_label("知识资产")).to_be_visible(timeout=20_000)
    try:
        page.get_by_label("知识资产").click(timeout=8_000)
    except PlaywrightError:
        page.get_by_title("知识资产").click(timeout=8_000)
    expect(page.get_by_text("资产空间", exact=True).first).to_be_visible(timeout=20_000)
    if space_name:
        click_text(page, space_name)
        expect(page.get_by_role("heading", name=space_name, exact=True)).to_be_visible(
            timeout=20_000
        )


def open_semantic_builder(page: Page, space_name: str) -> None:
    open_knowledge_center(page, space_name)
    click_text(page, "语义构建")
    workbench = page.locator(WORKBENCH_SELECTOR)
    expect(workbench).to_be_visible(timeout=20_000)
    expect(workbench.get_by_text("Sales DB", exact=True)).to_be_visible(timeout=20_000)
    workbench.locator(".kc-data-context-trigger").click()
    expect(
        page.locator("[data-testid='semantic-data-context-selector']").get_by_text(
            "Sales playbook", exact=True
        )
    ).to_be_visible(timeout=20_000)
    workbench.locator(".kc-data-context-trigger").click()


def add_browser_few_shot(page: Page) -> None:
    page.get_by_role("button", name="教 Agent 问数口径", exact=True).first.click()
    panel = page.locator("[data-testid='semantic-few-shot-panel']")
    expect(panel).to_be_visible(timeout=20_000)
    if panel.get_by_text(BROWSER_QUESTION, exact=True).count():
        return
    panel.get_by_role("textbox", name="Question", exact=True).fill(BROWSER_QUESTION)
    panel.get_by_role("textbox", name="SQL", exact=True).fill(BROWSER_SQL)
    panel.get_by_role("textbox", name="Notes", exact=True).fill(
        "created by Session J Playwright gate"
    )
    panel.get_by_role("button", name="Add question-SQL pair").click()
    expect(panel.get_by_text(BROWSER_QUESTION, exact=True)).to_be_visible(
        timeout=20_000
    )


def add_browser_instruction(page: Page) -> None:
    drawer = page.get_by_role("dialog", name="Semantic training examples")
    if drawer.is_visible(timeout=2_000):
        drawer.get_by_role("button", name="规则/禁用口径", exact=True).click()
    else:
        page.get_by_role("button", name="规则/禁用口径", exact=True).first.click()
    panel = page.locator("[data-testid='semantic-instructions-panel']")
    expect(panel).to_be_visible(timeout=20_000)
    if panel.get_by_text(BROWSER_INSTRUCTION, exact=True).count():
        return
    panel.get_by_role("textbox", name="Instruction", exact=True).fill(
        BROWSER_INSTRUCTION
    )
    panel.get_by_role("combobox", name="Scope", exact=True).select_option("global")
    panel.get_by_role("button", name="Add instruction").click()
    expect(panel.get_by_text(BROWSER_INSTRUCTION, exact=True)).to_be_visible(
        timeout=20_000
    )


def close_training_drawer(page: Page) -> None:
    page.get_by_role("button", name="Close training drawer").click()
    expect(
        page.get_by_role("dialog", name="Semantic training examples")
    ).not_to_be_visible(timeout=10_000)


def close_run_details_if_open(page: Page) -> None:
    drawer = page.get_by_role("dialog", name="Semantic run details")
    if drawer.is_visible(timeout=2_000):
        drawer.get_by_role("button", name="Close run details").click()
        expect(drawer).not_to_be_visible(timeout=10_000)


def refine_semantic_draft(page: Page) -> None:
    form = page.locator(".kc-semantic-feedback")
    expect(form.get_by_text("告诉 Agent 如何调整语义", exact=True)).to_be_visible(
        timeout=20_000
    )
    form.get_by_role("textbox").fill(BROWSER_FEEDBACK)
    form.get_by_role("button", name="让 Agent 调整草案").click()
    diff = page.locator("[data-testid='semantic-patch-diff']")
    expect(diff).to_be_visible(timeout=20_000)
    expect(
        diff.get_by_text("metrics").or_(diff.get_by_text("policy")).first
    ).to_be_visible(timeout=20_000)


def create_browser_view(page: Page) -> None:
    page.get_by_role("button", name="New View", exact=True).click()
    dialog = page.get_by_role("dialog", name="New semantic view")
    expect(dialog).to_be_visible(timeout=10_000)
    dialog.get_by_label("View 名称").fill(BROWSER_VIEW_NAME)
    dialog.get_by_label("说明").fill(
        "Browser-created persisted view draft for monthly sales trend."
    )
    dialog.get_by_label("Base metric").fill("ticket_count")
    dialog.get_by_label("Dimensions（逗号分隔）").fill("store_id, region")
    dialog.get_by_label("Time grain").select_option("month")
    dialog.get_by_role("button", name="保存 View 草案").click()
    expect(dialog).not_to_be_visible(timeout=20_000)
    expect(
        page.locator("[data-testid='semantic-patch-diff']").get_by_text("views")
    ).to_be_visible(timeout=20_000)


def publish_refined_draft(page: Page) -> None:
    publish = page.locator("[data-source-port='wren-modeling']").get_by_role(
        "button", name="Publish", exact=True
    )
    expect(publish).to_be_enabled(timeout=20_000)
    publish.click()
    expect(
        page.locator("[data-source-port='wren-modeling']")
        .get_by_text("published")
        .first
    ).to_be_visible(timeout=30_000)


def verify_reload_persistence(page: Page, space_name: str) -> None:
    page.reload(wait_until="networkidle")
    if page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").is_visible(
        timeout=3_000
    ):
        page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").fill("sessionj")
        page.get_by_label("进入").click()
        expect(page.get_by_label("知识资产")).to_be_visible(timeout=20_000)
    if not page.locator(WORKBENCH_SELECTOR).is_visible(timeout=5_000):
        try:
            page.get_by_label("知识资产").click(timeout=8_000)
        except PlaywrightError:
            page.get_by_title("知识资产").click(timeout=8_000)
        click_text(page, space_name)
        click_text(page, "语义构建")
    expect(page.locator(WORKBENCH_SELECTOR)).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="教 Agent 问数口径", exact=True).first.click()
    expect(
        page.locator("[data-testid='semantic-few-shot-panel']").get_by_text(
            BROWSER_QUESTION, exact=True
        )
    ).to_be_visible(timeout=20_000)
    page.get_by_role("dialog", name="Semantic training examples").get_by_role(
        "button", name="规则/禁用口径", exact=True
    ).click()
    expect(
        page.locator("[data-testid='semantic-instructions-panel']").get_by_text(
            BROWSER_INSTRUCTION, exact=True
        )
    ).to_be_visible(timeout=20_000)
    close_training_drawer(page)
    expect(page.get_by_text("published · v1").first).to_be_visible(timeout=30_000)
    expect(page.get_by_text("语义草案 Review")).to_be_visible(timeout=30_000)
    expect(page.get_by_text(BROWSER_VIEW_ID).first).to_have_count(1, timeout=30_000)
    page.get_by_role("button", name="运行详情", exact=True).click()
    expect(
        page.locator("[data-testid='semantic-agent-timeline']")
        .get_by_text("tool_call_start")
        .first
    ).to_be_visible(timeout=30_000)
    close_run_details_if_open(page)


def run_desktop(page: Page, seed: dict) -> dict:
    page.set_viewport_size({"width": 1440, "height": 900})
    open_semantic_builder(page, seed["space"]["name"])
    add_browser_few_shot(page)
    add_browser_instruction(page)
    close_training_drawer(page)
    page.locator(WORKBENCH_SELECTOR).get_by_role("button", name="生成语义").click()
    expect(
        page.locator("[data-testid='semantic-agent-timeline']")
        .get_by_text("tool_call_start")
        .first
    ).to_be_visible(timeout=60_000)
    expect(page.get_by_text("语义草案 Review")).to_be_visible(timeout=60_000)
    expect(page.get_by_text("published · v1").first).to_be_visible(timeout=30_000)
    close_run_details_if_open(page)
    wren = page.locator("[data-source-port='wren-modeling']")
    expect(wren).to_be_visible(timeout=20_000)
    wren.scroll_into_view_if_needed()
    expect(wren.get_by_role("button", name="sales_order").first).to_be_visible(
        timeout=20_000
    )
    page.screenshot(path=SCREENSHOTS / "desktop-modeling-workbench.png", full_page=True)

    refine_semantic_draft(page)
    create_browser_view(page)
    publish_refined_draft(page)

    inspector = page.locator("[data-testid='wren-source-port-inspector']")
    inspector.get_by_role("button", name="Advanced", exact=True).click()
    expect(inspector.get_by_text("Selected Raw JSON")).to_be_visible(timeout=10_000)
    inspector.get_by_role("button", name="Evidence", exact=True).click()
    expect(inspector.get_by_role("heading", name="Evidence")).to_be_visible(
        timeout=10_000
    )
    expect(inspector.get_by_role("heading", name="Alignments")).to_be_visible(
        timeout=10_000
    )
    page.screenshot(
        path=SCREENSHOTS / "desktop-evidence-alignments.png", full_page=True
    )
    verify_reload_persistence(page, seed["space"]["name"])
    page.screenshot(path=SCREENSHOTS / "desktop-reload-persistence.png", full_page=True)

    health = api_get("/api/knowledge-assets/health")
    jobs = api_get(
        f"/api/knowledge-assets/build-jobs?space_id={quote(seed['space']['id'])}"
    )["items"]
    latest_job = next(job for job in jobs if job["job_type"] == "semantic_skill")
    events = api_get(f"/api/knowledge-assets/semantic-build/{latest_job['id']}/events")[
        "items"
    ]
    detail = api_get(
        f"/api/knowledge-assets/semantic-packs/{latest_job['result_skill_id']}/detail"
    )
    skill_packages = api_get(
        f"/api/knowledge-assets/skill-packages?space_id={quote(seed['space']['id'])}"
    )["items"]
    semantic_skills = [
        item
        for item in skill_packages
        if item.get("capability_kind") == "semantic_skill"
        or item.get("asset_type") == "semantic_model"
    ]
    raw_views = (
        detail["structured_mdl"].get("views")
        if isinstance(detail["structured_mdl"], dict)
        else []
    )
    views = raw_views if isinstance(raw_views, list) else []
    return {
        "health": health,
        "latestJob": {
            "id": latest_job["id"],
            "status": latest_job["status"],
            "result_skill_id": latest_job["result_skill_id"],
            "publish_state": latest_job["output"].get("publish_state"),
            "agent_status": latest_job["output"].get("agent_status"),
        },
        "eventTypes": [event["event_type"] for event in events],
        "eventCount": len(events),
        "detail": {
            "semantic_pack_id": detail["semantic_pack_id"],
            "publish_state": detail["asset"]["publish_state"],
            "few_shot": len(detail["few_shot"]),
            "instructions": len(detail["instructions"]),
            "graph_objects": len(detail["graph_objects"]),
            "graph_relations": len(detail["graph_relations"]),
            "alignments": len(detail["alignments"]),
            "browser_question_persisted": any(
                pair["question"] == BROWSER_QUESTION for pair in detail["few_shot"]
            ),
            "browser_instruction_persisted": any(
                instruction["instruction"] == BROWSER_INSTRUCTION
                for instruction in detail["instructions"]
            ),
            "browser_view_persisted": any(
                isinstance(view, dict)
                and (
                    view.get("business_name") == BROWSER_VIEW_NAME
                    or view.get("name") == BROWSER_VIEW_ID
                    or view.get("id") == BROWSER_VIEW_ID
                )
                for view in views
            ),
            "refine_revision_persisted": any(
                isinstance(item, dict) and item.get("message") == BROWSER_FEEDBACK
                for item in detail["asset"]["capability_package"].get(
                    "revision_history", []
                )
            ),
        },
        "semanticSkillCount": len(semantic_skills),
        "semanticSkillNames": [item["name"] for item in semantic_skills],
    }


def run_mobile(page: Page, seed: dict) -> dict:
    page.set_viewport_size({"width": 390, "height": 844})
    open_knowledge_center(page, seed["space"]["name"])
    click_text(page, "语义构建")
    expect(page.locator(WORKBENCH_SELECTOR)).to_be_visible(timeout=20_000)
    expect(
        page.get_by_role("tablist", name="Wren modeling mobile panes")
    ).to_be_visible(timeout=20_000)
    click_text(page, "Inspector")
    expect(page.locator("[data-testid='wren-source-port-inspector']")).to_be_visible(
        timeout=20_000
    )
    expect(page.get_by_text("语义草案 Review")).to_be_visible(timeout=20_000)
    overflow = page.evaluate(
        "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth"
    )
    page.screenshot(path=SCREENSHOTS / "mobile-metadata-pane.png", full_page=True)
    return {"horizontalOverflowPx": overflow}


def main() -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    started = time.time()
    seed = seed_session_space()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        desktop = run_desktop(page, seed)
        mobile = run_mobile(page, seed)
        browser.close()
    result = {
        "schema": "session-j.semantic-builder.e2e.v1",
        "baseUrl": BASE_URL,
        "apiUrl": API_URL,
        "seed": {
            "space_id": seed["space"]["id"],
            "source_id": seed["source"]["id"],
            "document_source_id": seed["doc"]["id"],
            "snapshot_id": seed["snapshot"]["id"],
        },
        "durationSeconds": round(time.time() - started, 2),
        "desktop": desktop,
        "mobile": mobile,
        "screenshots": [
            str(SCREENSHOTS / "desktop-modeling-workbench.png"),
            str(SCREENSHOTS / "desktop-evidence-alignments.png"),
            str(SCREENSHOTS / "desktop-reload-persistence.png"),
            str(SCREENSHOTS / "mobile-metadata-pane.png"),
        ],
        "passed": (
            desktop["latestJob"]["status"] == "succeeded"
            and desktop["latestJob"]["publish_state"] == "published"
            and "tool_call_start" in desktop["eventTypes"]
            and desktop["detail"]["alignments"] > 0
            and desktop["detail"]["browser_question_persisted"]
            and desktop["detail"]["browser_instruction_persisted"]
            and desktop["detail"]["browser_view_persisted"]
            and desktop["detail"]["refine_revision_persisted"]
            and desktop["semanticSkillCount"] == 1
            and mobile["horizontalOverflowPx"] <= 4
        ),
    }
    (ROOT / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
