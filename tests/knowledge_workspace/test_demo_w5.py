from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.server.knowledge_workspace.demo import (
    DemoConfig,
    DemoSeedCoordinator,
    DemoSeedStore,
    build_demo_manifest,
    mount_demo_routes,
)
from frontend.server.knowledge_workspace.service import Actor

ACTOR = Actor("demo-tenant", "demo-workspace", "demo-principal")


def test_disabled_by_default_is_empty_and_does_not_leak_demo_cards() -> None:
    manifest = build_demo_manifest(
        ACTOR, DemoConfig(enabled=False), DemoSeedStore(":memory:")
    )
    assert manifest == {
        "enabled": False,
        "status": "disabled",
        "scenarios": [],
        "next_step": "管理员需显式设置 KNOWLEDGE_DEMO_ENABLED=true。",
    }


def test_seed_is_idempotent_and_scoped_to_tenant_workspace_version(
    tmp_path: Path,
) -> None:
    store = DemoSeedStore(tmp_path / "demo.sqlite")
    coordinator = DemoSeedCoordinator(
        DemoConfig(enabled=True, seed_version="w5-v1"), store
    )
    calls: list[str] = []

    async def gate(scenario: dict[str, object]) -> dict[str, object]:
        calls.append(str(scenario["scenario_id"]))
        evidence = {
            "validate",
            "discover",
            "lease",
            "autoskill_create",
            "autoskill_validate",
            "revision",
            "artifact_html",
        }
        evidence.add(
            "query" if scenario["connection_kind"] == "postgresql" else "invoke"
        )
        if scenario["scenario_id"] == "im-after-sales":
            evidence.add("openviking")
        required_skills = {
            item.strip().casefold()
            for item in str(scenario["skill_type"]).replace("+", ",").split(",")
            if item.strip()
        }
        return {
            "connection_status": "verified",
            "skill_status": "generated",
            "evidence": sorted(evidence),
            "skill_types_generated": sorted(required_skills),
            "last_verified_at": "2026-08-30T00:00:00+00:00",
            "connection_id": f"real-{scenario['scenario_id']}",
            "draft_id": f"draft-{scenario['scenario_id']}",
            "authoring_session_id": f"session-{scenario['scenario_id']}",
            "publication_id": f"publication-{scenario['scenario_id']}",
            "revision_ids": [
                f"revision-{scenario['scenario_id']}-{item}" for item in required_skills
            ],
            "artifact_ids": [
                f"artifact-{scenario['scenario_id']}-{item}" for item in required_skills
            ],
        }

    first = asyncio.run(coordinator.seed(ACTOR, gate=gate))
    second = asyncio.run(coordinator.seed(ACTOR, gate=gate))
    assert first == second
    assert calls == [
        "anta-sports-daily",
        "im-after-sales",
        "haidilao-inspection",
    ]
    assert first["source"] == "demo_seed"
    assert first["seed_version"] == "w5-v1"
    assert all(item["status"] == "ready" for item in first["scenarios"])
    assert first["scenarios"][0]["draft_id"] == "draft-anta-sports-daily"
    assert first["scenarios"][0]["authoring_session_id"] == "session-anta-sports-daily"
    assert first["scenarios"][0]["publication_id"] == "publication-anta-sports-daily"

    other = Actor("other-tenant", ACTOR.workspace_id, ACTOR.principal_id)
    third = asyncio.run(coordinator.seed(other, gate=gate))
    assert third["tenant_id"] == other.tenant_id
    assert len(calls) == 6


def test_seed_fails_closed_when_primary_real_gate_is_not_verified() -> None:
    coordinator = DemoSeedCoordinator(
        DemoConfig(enabled=True), DemoSeedStore(":memory:")
    )

    async def blocked(_: dict[str, object]) -> dict[str, object]:
        return {"connection_status": "not_verified", "skill_status": "generated"}

    with pytest.raises(RuntimeError, match="validate/discover"):
        asyncio.run(coordinator.seed(ACTOR, gate=blocked))


def test_seed_keeps_optional_scenarios_explicitly_blocked() -> None:
    coordinator = DemoSeedCoordinator(
        DemoConfig(enabled=True), DemoSeedStore(":memory:")
    )

    async def primary_only(scenario: dict[str, object]) -> dict[str, object]:
        scenario_id = str(scenario["scenario_id"])
        if scenario_id != "anta-sports-daily":
            raise RuntimeError(f"{scenario_id}: lifecycle is not wired")
        return {
            "connection_status": "verified",
            "skill_status": "generated",
            "evidence": [
                "validate",
                "discover",
                "lease",
                "query",
                "autoskill_create",
                "autoskill_validate",
                "revision",
                "artifact_html",
            ],
            "skill_types_generated": ["semantic", "dashboard"],
            "connection_id": "connection-primary",
            "draft_id": "draft-primary",
            "authoring_session_id": "session-primary",
            "publication_id": "publication-primary",
            "revision_ids": ["revision-primary"],
            "artifact_ids": ["artifact-primary"],
        }

    seeded = asyncio.run(coordinator.seed(ACTOR, gate=primary_only))
    assert seeded["status"] == "ready"
    assert [item["status"] for item in seeded["scenarios"]] == [
        "ready",
        "blocked",
        "blocked",
    ]
    assert all(
        item["connection_status"] == "not_verified"
        and item["skill_status"] == "not_generated"
        for item in seeded["scenarios"][1:]
    )


def test_routes_are_tenant_scoped_and_reset_requires_current_version(
    tmp_path: Path,
) -> None:
    app = FastAPI()
    store = DemoSeedStore(tmp_path / "demo.sqlite")

    def actor(_: object) -> Actor:
        return ACTOR

    async def gate(scenario: dict[str, object]) -> dict[str, object]:
        evidence = {
            "validate",
            "discover",
            "lease",
            "autoskill_create",
            "autoskill_validate",
            "revision",
            "artifact_html",
        }
        evidence.add(
            "query" if scenario["connection_kind"] == "postgresql" else "invoke"
        )
        if scenario["scenario_id"] == "im-after-sales":
            evidence.add("openviking")
        required_skills = {
            item.strip().casefold()
            for item in str(scenario["skill_type"]).replace("+", ",").split(",")
            if item.strip()
        }
        return {
            "connection_status": "verified",
            "skill_status": "generated",
            "evidence": sorted(evidence),
            "skill_types_generated": sorted(required_skills),
            "connection_id": f"connection-{scenario['scenario_id']}",
            "draft_id": f"draft-{scenario['scenario_id']}",
            "authoring_session_id": f"session-{scenario['scenario_id']}",
            "publication_id": f"publication-{scenario['scenario_id']}",
            "revision_ids": [f"revision-{item}" for item in required_skills],
            "artifact_ids": [f"artifact-{item}" for item in required_skills],
        }

    gate_actors: list[Actor] = []

    def gate_factory(actor: Actor):  # type: ignore[no-untyped-def]
        gate_actors.append(actor)
        return gate

    mount_demo_routes(
        app,
        config=DemoConfig(enabled=True, seed_version="w5-v1"),
        store=store,
        actor_resolver=actor,  # type: ignore[arg-type]
        gate_factory=gate_factory,
    )
    client = TestClient(app)
    assert (
        client.get("/api/knowledge/v1/demo/manifest").json()["data"]["status"]
        == "not_initialized"
    )
    seeded = client.post("/api/knowledge/v1/demo/seed")
    assert seeded.status_code == 200
    assert seeded.json()["data"]["status"] == "ready"
    assert "tenant_id" not in seeded.json()["data"]
    assert gate_actors == [ACTOR]
    wrong = client.post("/api/knowledge/v1/demo/reset", json={"seed_version": "w5-v0"})
    assert wrong.status_code == 400
    right = client.post("/api/knowledge/v1/demo/reset", json={"seed_version": "w5-v1"})
    assert right.json()["data"]["deleted"] is True


def test_contract_manifests_keep_oracle_as_unconnected_configuration_example() -> None:
    seed = json.loads(Path("demo/seed-manifest.json").read_text())
    assert seed["enabled_by_default"] is False
    assert seed["idempotency"]["key"] == [
        "tenant_id",
        "workspace_id",
        "seed_version",
    ]
    assert all("validate" in scenario["requires"] for scenario in seed["scenarios"])
    assert seed["oracle_configuration_example"]["connected"] is False


def test_local_mcp_provider_implements_initialize_discover_and_call() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "demo-services/local_service.py",
            "--service",
            "mcp",
            "--port",
            "28093",
        ]
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:28093/healthz", timeout=0.1)
                break
            except OSError:
                import time

                time.sleep(0.02)

        def rpc(method: str, params: dict[str, object] | None = None) -> dict[str, Any]:
            request = urllib.request.Request(
                "http://127.0.0.1:28093/mcp",
                data=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": params or {},
                    }
                ).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            return json.load(urllib.request.urlopen(request, timeout=2))

        assert (
            rpc("initialize")["result"]["serverInfo"]["name"]
            == "knowledge-commercial-demo"
        )  # type: ignore[index]
        tools = rpc("tools/list")["result"]["tools"]  # type: ignore[index]
        assert tools[0]["name"] == "inspect_store"  # type: ignore[index]
        called = rpc(
            "tools/call",
            {"name": "inspect_store", "arguments": {"store_id": "store-sh"}},
        )
        assert "98" in called["result"]["content"][0]["text"]  # type: ignore[index]
    finally:
        process.terminate()
        process.wait(timeout=5)
