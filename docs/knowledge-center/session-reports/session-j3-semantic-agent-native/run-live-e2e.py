from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib import request
from urllib.error import HTTPError

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent
SCREENSHOTS = ROOT / "screenshots"
BASE_URL = os.getenv("J3_E2E_BASE_URL", "http://127.0.0.1:18765")
API_URL = BASE_URL.rstrip("/")
WORKBENCH_SELECTOR = "[data-testid='semantic-builder-workspace']"


def api_get(path: str) -> dict:
    with request.urlopen(f"{API_URL}{path}", timeout=30) as response:
        return json.load(response)


def api_post(path: str, payload: dict, *, timeout: int = 30) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except HTTPError as error:
        text = error.read().decode("utf-8")
        raise RuntimeError(f"{path} failed: HTTP {error.code} {text}") from error
    if path.endswith("/stream"):
        return {"raw": text}
    return json.loads(text)


def sse_events(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = line.removeprefix("data: ")
        payload = json.loads(data)
        payload["_event"] = event_type
        events.append(payload)
    return events


def seed() -> dict:
    suffix = str(int(time.time()))
    space = api_post(
        "/api/knowledge-assets/spaces",
        {"name": f"Session J3 E2E {suffix}", "region": "local"},
    )
    source = api_post(
        "/api/knowledge-assets/sources",
        {
            "space_id": space["id"],
            "source_type": "database",
            "provider": "duckdb",
            "name": "Sales DB",
            "status": "ready",
        },
    )
    doc = api_post(
        "/api/knowledge-assets/sources",
        {
            "space_id": space["id"],
            "source_type": "file",
            "provider": "manual",
            "name": "Sales playbook",
            "status": "indexed",
            "metadata": {
                "content": (
                    "Ticket count means distinct billid. GMV is sum(amount) minus "
                    "refund_amount. Store is a dimension table. customer_phone is PII."
                )
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
                            {"name": "billid", "type": "varchar"},
                            {"name": "store_id", "type": "number"},
                            {"name": "sell_date", "type": "date"},
                            {"name": "amount", "type": "decimal"},
                            {"name": "refund_amount", "type": "decimal"},
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
        },
    )
    few_shot = api_post(
        "/api/knowledge-assets/semantic/question-sql-pairs",
        {
            "space_id": space["id"],
            "question": "按门店看票数",
            "sql": "SELECT store_id, COUNT(DISTINCT billid) FROM sales_order GROUP BY 1",
            "tables": ["sales_order"],
            "notes": "Session J3 E2E few-shot",
        },
    )
    instruction = api_post(
        "/api/knowledge-assets/semantic/instructions",
        {
            "space_id": space["id"],
            "instruction": "票数必须使用 COUNT(DISTINCT billid)。",
            "is_default": True,
        },
    )
    return {
        "space": space,
        "source": source,
        "doc": doc,
        "snapshot": snapshot,
        "few_shot": few_shot,
        "instruction": instruction,
    }


def run_api_flow(seeded: dict) -> dict:
    stream = api_post(
        "/api/knowledge-assets/semantic-build/stream",
        {
            "space_id": seeded["space"]["id"],
            "source_ids": [seeded["source"]["id"]],
            "document_source_ids": [seeded["doc"]["id"]],
            "snapshot_ids": [seeded["snapshot"]["id"]],
            "name": "J3 Sales Semantic",
            "intent": "build sales semantic draft",
            "target_domain": "sales",
            "publish": True,
        },
        timeout=240,
    )
    events = sse_events(stream["raw"])
    final = [item for item in events if item["_event"] == "job_status"][-1]
    job_id = final["payload"]["job_id"]
    job = api_get(f"/api/knowledge-assets/build-jobs/{job_id}")
    pack_id = job["output"]["semantic_pack_id"]
    conversation_id = job["output"]["conversation_id"]
    detail_after_start = api_get(f"/api/knowledge-assets/semantic-packs/{pack_id}/detail")
    refined = api_post(
        f"/api/knowledge-assets/semantic-builder/conversations/{conversation_id}/messages",
        {
            "semantic_pack_id": pack_id,
            "message": "把票数定义改成去重 billid，隐藏客户手机号，并增加按月份趋势的 View。",
        },
        timeout=240,
    )
    target_revision_id = refined["latest_revision"]["id"]
    accepted = api_post(
        f"/api/knowledge-assets/semantic-builder/conversations/{conversation_id}/revisions/{target_revision_id}/accept",
        {"message": "接受本次 Agent patch。"},
    )
    view = api_post(
        f"/api/knowledge-assets/semantic-builder/drafts/{pack_id}/views",
        {
            "name": "月度门店票数趋势",
            "description": "按月份和门店查看去重票数趋势。",
            "base_metric": "sales_order_count",
            "dimensions": ["store_id"],
            "time_grain": "month",
        },
    )
    published = api_post(
        f"/api/knowledge-assets/semantic-builder/drafts/{pack_id}/publish",
        {"publish": True},
    )
    detail = api_get(f"/api/knowledge-assets/semantic-packs/{pack_id}/detail")
    return {
        "events": events,
        "job": job,
        "pack_id": pack_id,
        "conversation_id": conversation_id,
        "start_publish_state": detail_after_start["asset"]["publish_state"],
        "refined": {
            "latest_revision": refined["latest_revision"],
            "diff": refined["diff"],
        },
        "accepted": accepted["latest_revision"],
        "view": view["view"],
        "published": {
            "publish_state": published["publish_state"],
            "revision": published.get("revision"),
        },
        "detail": detail,
    }


def open_knowledge_assets(page: Page) -> None:
    if page.get_by_role("button", name="知识资产").is_visible(timeout=2500):
        page.get_by_role("button", name="知识资产").click()


def open_ui(page: Page, seeded: dict, pack_id: str) -> int:
    page.goto(f"{BASE_URL}/knowledge-assets", wait_until="networkidle")
    if page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").is_visible(timeout=2500):
        page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").fill("sessionj3")
        page.get_by_label("进入").click()
    open_knowledge_assets(page)
    expect(page.get_by_text(seeded["space"]["name"]).first).to_be_visible(timeout=30_000)
    page.get_by_text(seeded["space"]["name"], exact=True).first.click()
    page.get_by_text("语义构建", exact=True).first.click()
    expect(page.locator(WORKBENCH_SELECTOR)).to_be_visible(timeout=30_000)
    expect(page.locator("[data-testid='semantic-feedback-input']")).to_be_visible(timeout=30_000)
    expect(page.get_by_text("语义草案 Review")).to_be_visible(timeout=30_000)
    expect(page.get_by_text("published").first).to_be_visible(timeout=30_000)
    page.locator("[data-source-port='wren-modeling']").get_by_role("button", name="运行详情").click()
    expect(page.locator("[data-testid='semantic-agent-timeline']")).to_be_visible(timeout=30_000)
    page.screenshot(path=SCREENSHOTS / "desktop-agent-run.png", full_page=True)
    page.get_by_role("button", name="Close run details").click()
    expect(page.get_by_role("dialog", name="Semantic run details")).not_to_be_visible(timeout=10_000)
    page.screenshot(path=SCREENSHOTS / "desktop-semantic-builder.png", full_page=True)
    page.locator("[data-testid='semantic-feedback-input']").fill("把 GMV 扣除退款")
    page.locator(".kc-semantic-feedback").get_by_role("button", name="让 Agent 调整草案").click()
    expect(page.locator("[data-testid='semantic-patch-diff']")).to_be_visible(timeout=90_000)
    page.screenshot(path=SCREENSHOTS / "desktop-patch-diff.png", full_page=True)

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{BASE_URL}/knowledge-assets", wait_until="networkidle")
    if page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").is_visible(timeout=2500):
        page.get_by_placeholder("用户名（字母 + 数字，最多 16 位）").fill("sessionj3")
        page.get_by_label("进入").click()
    open_knowledge_assets(page)
    page.get_by_text(seeded["space"]["name"], exact=True).first.click()
    page.get_by_text("语义构建", exact=True).first.click()
    expect(page.locator(WORKBENCH_SELECTOR)).to_be_visible(timeout=30_000)
    expect(page.get_by_role("tablist", name="Wren modeling mobile panes")).to_be_visible(timeout=30_000)
    overflow = page.evaluate(
        "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth"
    )
    page.screenshot(path=SCREENSHOTS / "mobile-semantic-builder.png", full_page=True)
    return overflow


def main() -> None:
    started = time.time()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    health = api_get("/api/knowledge-assets/health")
    runner_configured = bool(health["agents"]["semantic_builder"].get("configured"))
    result: dict = {
        "schema": "session-j3.semantic-builder.live-e2e.v1",
        "base_url": BASE_URL,
        "runner_configured": runner_configured,
        "health": health,
        "used_fallback": False,
        "live_runner_unavailable": False,
        "passed": False,
    }
    if not runner_configured:
        result["live_runner_unavailable"] = True
        result["reason"] = "AGENT_NOT_CONFIGURED"
    else:
        seeded = seed()
        api_flow = run_api_flow(seeded)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            overflow = open_ui(page, seeded, api_flow["pack_id"])
            browser.close()
        detail = api_flow["detail"]
        history = detail["asset"]["capability_package"].get("draft_revision_history", [])
        result.update(
            {
                "seed": {
                    "space_id": seeded["space"]["id"],
                    "source_id": seeded["source"]["id"],
                    "document_source_id": seeded["doc"]["id"],
                    "snapshot_id": seeded["snapshot"]["id"],
                },
                "api_flow": {
                    "job_status": api_flow["job"]["status"],
                    "start_publish_state": api_flow["start_publish_state"],
                    "final_publish_state": detail["asset"]["publish_state"],
                    "conversation_id": api_flow["conversation_id"],
                    "agent_run_id": detail["asset"]["provenance"].get("agent_run_id"),
                    "runner_backend": detail["asset"]["provenance"].get("runner_backend"),
                    "refine_revision_status": api_flow["refined"]["latest_revision"]["status"],
                    "accept_revision_status": api_flow["accepted"]["status"],
                    "publish_revision_status": (api_flow["published"]["revision"] or {}).get("status"),
                    "views": len(detail["structured_mdl"].get("views") or []),
                    "few_shot": len(detail["few_shot"]),
                    "instructions": len(detail["instructions"]),
                    "event_types": [event["_event"] for event in api_flow["events"]],
                    "history_operations": [item.get("operation") for item in history if isinstance(item, dict)],
                },
                "mobile": {"horizontal_overflow_px": overflow},
                "screenshots": [
                    "screenshots/desktop-semantic-builder.png",
                    "screenshots/mobile-semantic-builder.png",
                    "screenshots/desktop-agent-run.png",
                    "screenshots/desktop-patch-diff.png",
                ],
            }
        )
        result["passed"] = (
            api_flow["job"]["status"] == "succeeded"
            and api_flow["start_publish_state"] == "draft"
            and detail["asset"]["publish_state"] == "published"
            and detail["asset"]["provenance"].get("runner_backend") == "veadk.Agent+Runner"
            and "run_semantic_builder_agent" in json.dumps(api_flow["events"], ensure_ascii=False)
            and "refine" in result["api_flow"]["history_operations"]
            and "accept" in result["api_flow"]["history_operations"]
            and "publish" in result["api_flow"]["history_operations"]
            and result["api_flow"]["views"] >= 1
            and overflow <= 4
        )
    result["duration_seconds"] = round(time.time() - started, 2)
    (ROOT / "live-e2e-result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["passed"] and not result.get("live_runner_unavailable"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
