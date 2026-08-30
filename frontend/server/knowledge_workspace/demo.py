"""Commercial W5 demo tenant bootstrap boundary.

This module is deliberately not imported by the existing W4 route wiring.  The
integration worker can mount ``mount_demo_routes`` when the demo flag is
explicitly enabled.  It keeps demo metadata tenant-scoped and never turns a
fixture or a configured-but-unvalidated connection into a green state.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .service import Actor


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "anta-sports-daily",
        "title": "安踏经营日报",
        "source": "本地 PostgreSQL 示例订单/门店数据",
        "skill_type": "Semantic + Dashboard",
        "connection_kind": "postgresql",
        "actions": ("postgresql.discover_resources", "postgresql.execute_read_query"),
        "goal": "按门店和日期查询订单、GMV、客单价，并生成经营日报看板。",
    },
    {
        "scenario_id": "im-after-sales",
        "title": "智己售后排障",
        "source": "本地 Web Action/API + 历史案例知识",
        "skill_type": "SOP",
        "connection_kind": "rest_openapi",
        "actions": ("rest.invoke",),
        "goal": "基于历史案例和实时车辆故障信息生成带证据的售后排障 SOP。",
    },
    {
        "scenario_id": "haidilao-inspection",
        "title": "海底捞门店巡检",
        "source": "本地可调用表单/API",
        "skill_type": "SOP + Dashboard",
        "connection_kind": "form_api",
        "actions": ("rest.invoke",),
        "goal": "提交并汇总门店巡检表，输出异常项、负责人和整改待办。",
    },
)

COMMON_GATE_EVIDENCE = {
    "validate",
    "discover",
    "lease",
    "autoskill_create",
    "autoskill_validate",
    "revision",
    "artifact_html",
}
PRIMARY_SCENARIO_ID = "anta-sports-daily"

DemoGate = Callable[[dict[str, Any]], Awaitable[Mapping[str, Any]]]
DemoGateFactory = Callable[[Actor], DemoGate]


@dataclass(frozen=True)
class DemoConfig:
    enabled: bool = False
    seed_version: str = "w5-v1"
    database: str = ".veadk/knowledge-demo.sqlite3"

    @classmethod
    def from_env(cls) -> DemoConfig:
        raw = os.getenv("KNOWLEDGE_DEMO_ENABLED", "false").strip().casefold()
        return cls(
            enabled=raw in {"1", "true", "yes", "on"},
            seed_version=os.getenv("KNOWLEDGE_DEMO_SEED_VERSION", "w5-v1").strip()
            or "w5-v1",
            database=os.getenv(
                "KNOWLEDGE_DEMO_STATE_DB", ".veadk/knowledge-demo.sqlite3"
            ),
        )


class DemoSeedStore:
    """Small durable idempotency ledger; only the requested tenant is mutable."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        if str(database) != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(database), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_seed (
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              seed_version TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (tenant_id, workspace_id, seed_version)
            )
            """
        )
        self._db.commit()

    def get(self, actor: Actor, seed_version: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM demo_seed WHERE tenant_id=? AND workspace_id=? AND seed_version=?",
                (actor.tenant_id, actor.workspace_id, seed_version),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def put(
        self, actor: Actor, seed_version: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        now = utc_iso()
        value = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
        with self._lock:
            existing = self._db.execute(
                "SELECT payload FROM demo_seed WHERE tenant_id=? AND workspace_id=? AND seed_version=?",
                (actor.tenant_id, actor.workspace_id, seed_version),
            ).fetchone()
            if existing:
                return json.loads(existing["payload"])
            self._db.execute(
                "INSERT INTO demo_seed VALUES(?,?,?,?,?,?)",
                (actor.tenant_id, actor.workspace_id, seed_version, value, now, now),
            )
            self._db.commit()
        # Return the same JSON-canonical shape that a subsequent read returns
        # (notably lists instead of tuples), so idempotency is observable.
        return json.loads(value)

    def reset(self, actor: Actor, seed_version: str) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "DELETE FROM demo_seed WHERE tenant_id=? AND workspace_id=? AND seed_version=?",
                (actor.tenant_id, actor.workspace_id, seed_version),
            )
            self._db.commit()
        return cursor.rowcount == 1


def _initial_state(actor: Actor, seed_version: str) -> dict[str, Any]:
    """Return cards without claiming any connection or skill is ready."""
    return {
        "status": "not_initialized",
        "tenant_id": actor.tenant_id,
        "workspace_id": actor.workspace_id,
        "seed_version": seed_version,
        "source": "demo_seed",
        "provenance": "knowledge-commercial-w5",
        "created_at": utc_iso(),
        "scenarios": [
            {
                **scenario,
                "data_source": scenario["source"],
                "created_at": utc_iso(),
                "status": "not_initialized",
                "connection_status": "not_verified",
                "skill_status": "not_generated",
                "last_verified_at": None,
                "next_step": "运行显式 seed 命令；需要本地服务、Connection Service 和 AutoSkill。",
            }
            for scenario in SCENARIOS
        ],
    }


def _public_state(value: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(value, ensure_ascii=False))
    # The ledger is safe to return, but identity is still only useful to the
    # current tenant and never includes credentials, leases, or runtime URLs.
    result.pop("tenant_id", None)
    result.pop("workspace_id", None)
    return result


def build_demo_manifest(
    actor: Actor, config: DemoConfig, store: DemoSeedStore
) -> dict[str, Any]:
    if not config.enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "scenarios": [],
            "next_step": "管理员需显式设置 KNOWLEDGE_DEMO_ENABLED=true。",
        }
    state = store.get(actor, config.seed_version)
    if state is None:
        state = _initial_state(actor, config.seed_version)
    return {
        "enabled": True,
        "status": state["status"],
        "seed_version": config.seed_version,
        "source": "demo_seed",
        "provenance": "knowledge-commercial-w5",
        "scenarios": state["scenarios"],
        "next_step": (
            "运行 seed 命令初始化真实连接与 Skill。"
            if state["status"] != "ready"
            else "可打开 Skill、查看连接或用自己的数据复制。"
        ),
    }


class DemoSeedCoordinator:
    """Create the visible ledger after real gates have passed.

    ``gate`` is injected by integration/bootstrap code.  It must execute
    validate/discover/lease/query or invoke and AutoSkill generation; this
    class intentionally has no fixture-success path.
    """

    def __init__(self, config: DemoConfig, store: DemoSeedStore) -> None:
        self.config = config
        self.store = store

    async def seed(
        self,
        actor: Actor,
        *,
        gate: DemoGate,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("DEMO_DISABLED: set KNOWLEDGE_DEMO_ENABLED=true")
        existing = self.store.get(actor, self.config.seed_version)
        if existing is not None:
            return existing
        completed: list[dict[str, Any]] = []
        for scenario in SCENARIOS:
            try:
                result = dict(await gate(dict(scenario)))
                self._validate_gate_result(scenario, result)
            except RuntimeError as exc:
                if scenario["scenario_id"] == PRIMARY_SCENARIO_ID:
                    raise
                completed.append(
                    {
                        **scenario,
                        "status": "blocked",
                        "connection_status": "not_verified",
                        "skill_status": "not_generated",
                        "created_at": utc_iso(),
                        "source": "demo_seed",
                        "data_source": scenario["source"],
                        "seed_version": self.config.seed_version,
                        "provenance": "knowledge-commercial-w5",
                        "last_verified_at": None,
                        "next_step": str(exc)[:500],
                    }
                )
                continue
            generated_skills = {
                str(item).strip().casefold()
                for item in result.get("skill_types_generated", [])
                if str(item).strip()
            }
            completed.append(
                {
                    **scenario,
                    "status": "ready",
                    "connection_status": "verified",
                    "skill_status": "generated",
                    "connection_id": str(result.get("connection_id") or ""),
                    "draft_id": str(result.get("draft_id") or ""),
                    "authoring_session_id": str(
                        result.get("authoring_session_id") or ""
                    ),
                    "publication_id": str(result.get("publication_id") or ""),
                    "revision_ids": [
                        str(item) for item in result.get("revision_ids", [])
                    ],
                    "artifact_ids": [
                        str(item) for item in result.get("artifact_ids", [])
                    ],
                    "skill_types_generated": sorted(generated_skills),
                    "created_at": utc_iso(),
                    "source": "demo_seed",
                    "data_source": scenario["source"],
                    "seed_version": self.config.seed_version,
                    "provenance": "knowledge-commercial-w5",
                    "last_verified_at": result.get("last_verified_at") or utc_iso(),
                    "next_step": "可打开 Skill、查看连接、重新验证或复制到自己的数据。",
                }
            )
        payload = _initial_state(actor, self.config.seed_version)
        payload.update(
            {"status": "ready", "scenarios": completed, "updated_at": utc_iso()}
        )
        return self.store.put(actor, self.config.seed_version, payload)

    @staticmethod
    def _validate_gate_result(
        scenario: Mapping[str, Any], result: Mapping[str, Any]
    ) -> None:
        if result.get("connection_status") != "verified":
            raise RuntimeError(
                f"{scenario['scenario_id']}: real connection validate/discover did not pass"
            )
        if result.get("skill_status") != "generated":
            raise RuntimeError(
                f"{scenario['scenario_id']}: real AutoSkill generation did not pass"
            )
        observed = {str(item) for item in result.get("evidence", []) if str(item)}
        required = COMMON_GATE_EVIDENCE | {
            "query" if scenario["connection_kind"] == "postgresql" else "invoke"
        }
        if scenario["scenario_id"] == "im-after-sales":
            required.add("openviking")
        missing = sorted(required - observed)
        if missing:
            raise RuntimeError(
                f"{scenario['scenario_id']}: real gate evidence is incomplete "
                f"({', '.join(missing)})"
            )
        required_skills = {
            item.strip().casefold()
            for item in str(scenario["skill_type"]).replace("+", ",").split(",")
            if item.strip()
        }
        generated_skills = {
            str(item).strip().casefold()
            for item in result.get("skill_types_generated", [])
            if str(item).strip()
        }
        missing_skills = sorted(required_skills - generated_skills)
        revision_ids = [str(item) for item in result.get("revision_ids", [])]
        artifact_ids = [str(item) for item in result.get("artifact_ids", [])]
        navigation_ids = {
            key: str(result.get(key) or "")
            for key in (
                "connection_id",
                "draft_id",
                "authoring_session_id",
                "publication_id",
            )
        }
        if (
            missing_skills
            or not revision_ids
            or not artifact_ids
            or not all(navigation_ids.values())
        ):
            raise RuntimeError(
                f"{scenario['scenario_id']}: the combined Skill needs a real "
                "generation, immutable revision, HTML artifact, and navigation IDs"
            )


def mount_demo_routes(
    app: FastAPI,
    *,
    config: DemoConfig | None = None,
    store: DemoSeedStore | None = None,
    actor_resolver: Callable[[Request], Actor],
    gate: DemoGate | None = None,
    gate_factory: DemoGateFactory | None = None,
    prefix: str = "/api/knowledge/v1/demo",
) -> None:
    """Optional W5 wiring; callers choose when to mount it."""
    resolved_config = config or DemoConfig.from_env()
    resolved_store = store or DemoSeedStore(resolved_config.database)

    @app.get(prefix + "/manifest")
    async def manifest(request: Request) -> JSONResponse:
        actor = actor_resolver(request)
        return JSONResponse(
            {"data": build_demo_manifest(actor, resolved_config, resolved_store)}
        )

    @app.post(prefix + "/seed")
    async def seed(request: Request) -> JSONResponse:
        actor = actor_resolver(request)
        resolved_gate = gate_factory(actor) if gate_factory is not None else gate
        if resolved_gate is None:
            return JSONResponse(
                {
                    "error": {
                        "code": "DEMO_NOT_WIRED",
                        "message": "真实 Connection/AutoSkill seed gate 尚未接入",
                        "retryable": False,
                        "next_step": "配置本地服务、Connection Service、AutoSkill 和 OpenViking 后重试。",
                    }
                },
                status_code=503,
            )
        try:
            result = await DemoSeedCoordinator(resolved_config, resolved_store).seed(
                actor, gate=resolved_gate
            )
        except RuntimeError as exc:
            return JSONResponse(
                {
                    "error": {
                        "code": "DEMO_SEED_FAILED",
                        "message": str(exc),
                        "retryable": True,
                    }
                },
                status_code=409,
            )
        return JSONResponse({"data": _public_state(result)})

    @app.post(prefix + "/reset")
    async def reset(request: Request) -> JSONResponse:
        actor = actor_resolver(request)
        body = await request.json()
        version = str(body.get("seed_version") or resolved_config.seed_version)
        if version != resolved_config.seed_version:
            return JSONResponse(
                {
                    "error": {
                        "code": "DEMO_RESET_SCOPE",
                        "message": "只能 reset 当前 seed_version",
                    }
                },
                status_code=400,
            )
        deleted = resolved_store.reset(actor, version)
        return JSONResponse({"data": {"deleted": deleted, "seed_version": version}})


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(manifest), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
