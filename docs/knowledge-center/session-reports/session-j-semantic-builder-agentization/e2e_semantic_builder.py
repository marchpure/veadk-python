from __future__ import annotations

import json
import time
from pathlib import Path
from urllib import request

from playwright.sync_api import Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parent
SCREENSHOTS = ROOT / "screenshots"
API_URL = "http://127.0.0.1:8000"
BASE_URL = API_URL


def api_get(path: str) -> dict:
    with request.urlopen(f"{API_URL}{path}", timeout=20) as response:
        return json.load(response)


def click_text(page: Page, text: str) -> None:
    target = page.get_by_text(text, exact=True).first
    expect(target).to_be_visible(timeout=20_000)
    target.click()


def open_knowledge_center(page: Page) -> None:
    page.goto(BASE_URL, wait_until="networkidle")
    if page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").is_visible(timeout=3_000):
        page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").fill("sessionj")
        page.get_by_label("进入").click()
        expect(page.get_by_label("知识资产")).to_be_visible(timeout=20_000)
    try:
        page.get_by_label("知识资产").click(timeout=8_000)
    except Exception:
        page.get_by_title("知识资产").click(timeout=8_000)
    expect(page.get_by_text("资产空间", exact=True).first).to_be_visible(timeout=20_000)


def run_desktop(page: Page) -> dict:
    page.set_viewport_size({"width": 1440, "height": 900})
    open_knowledge_center(page)
    click_text(page, "语义构建")
    expect(page.locator("[data-testid='semantic-builder-workbench']")).to_be_visible(timeout=20_000)
    page.locator("[data-testid='semantic-builder-workbench']").get_by_role("button", name="生成语义").click()
    expect(page.locator("[data-testid='semantic-agent-timeline']").get_by_text("tool_call_start").first).to_be_visible(timeout=60_000)
    expect(page.get_by_text("Graph / Evidence / Alignments")).to_be_visible(timeout=60_000)
    expect(page.get_by_text("published · v1").first).to_be_visible(timeout=30_000)
    wren = page.locator("[data-source-port='wren-modeling']")
    expect(wren).to_be_visible(timeout=20_000)
    wren.scroll_into_view_if_needed()
    expect(wren.get_by_role("button", name="sales_order").first).to_be_visible(timeout=20_000)
    page.screenshot(path=SCREENSHOTS / "desktop-modeling-workbench.png", full_page=True)

    click_text(page, "New Model")
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)
    dialog.get_by_role("textbox", name="Name", exact=True).fill("Browser Draft Model")
    dialog.get_by_role("textbox", name="Table", exact=True).fill("browser_draft_model")
    dialog.get_by_role("textbox", name="Fields, one per line as name:type[:pk]").fill("draft_id:number:pk\nlabel:varchar")
    click_text(page, "Save Draft")
    expect(page.get_by_text("1 local").first).to_be_visible(timeout=10_000)

    click_text(page, "New")
    expect(page.get_by_role("dialog")).to_be_visible(timeout=10_000)
    click_text(page, "Close")

    inspector = page.locator("[data-testid='wren-source-port-inspector']")
    inspector.get_by_role("button", name="MDL / Raw", exact=True).click()
    expect(inspector.get_by_text("Selected Raw JSON")).to_be_visible(timeout=10_000)
    inspector.get_by_role("button", name="Evidence", exact=True).click()
    expect(inspector.get_by_role("heading", name="Evidence")).to_be_visible(timeout=10_000)
    expect(inspector.get_by_role("heading", name="Alignments")).to_be_visible(timeout=10_000)
    page.screenshot(path=SCREENSHOTS / "desktop-evidence-alignments.png", full_page=True)

    health = api_get("/api/knowledge-assets/health")
    jobs = api_get("/api/knowledge-assets/build-jobs")["items"]
    latest_job = next(job for job in jobs if job["job_type"] == "semantic_skill")
    events = api_get(f"/api/knowledge-assets/semantic-build/{latest_job['id']}/events")["items"]
    detail = api_get(f"/api/knowledge-assets/semantic-packs/{latest_job['result_skill_id']}/detail")
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
        },
    }


def run_mobile(page: Page) -> dict:
    page.set_viewport_size({"width": 390, "height": 844})
    open_knowledge_center(page)
    click_text(page, "语义构建")
    expect(page.locator("[data-testid='semantic-builder-workbench']")).to_be_visible(timeout=20_000)
    expect(page.get_by_role("tablist", name="Wren modeling mobile panes")).to_be_visible(timeout=20_000)
    click_text(page, "Metadata")
    expect(page.locator("[data-testid='wren-source-port-inspector']")).to_be_visible(timeout=20_000)
    overflow = page.evaluate(
        "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth"
    )
    page.screenshot(path=SCREENSHOTS / "mobile-metadata-pane.png", full_page=True)
    return {"horizontalOverflowPx": overflow}


def main() -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        desktop = run_desktop(page)
        mobile = run_mobile(page)
        browser.close()
    result = {
        "schema": "session-j.semantic-builder.e2e.v1",
        "baseUrl": BASE_URL,
        "apiUrl": API_URL,
        "durationSeconds": round(time.time() - started, 2),
        "desktop": desktop,
        "mobile": mobile,
        "screenshots": [
            str(SCREENSHOTS / "desktop-modeling-workbench.png"),
            str(SCREENSHOTS / "desktop-evidence-alignments.png"),
            str(SCREENSHOTS / "mobile-metadata-pane.png"),
        ],
        "passed": (
            desktop["latestJob"]["status"] == "succeeded"
            and desktop["latestJob"]["publish_state"] == "published"
            and "tool_call_start" in desktop["eventTypes"]
            and desktop["detail"]["alignments"] > 0
            and mobile["horizontalOverflowPx"] <= 4
        ),
    }
    (ROOT / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
