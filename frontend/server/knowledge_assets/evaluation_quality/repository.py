from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import EvaluationRun, EvaluationSuite, FixPlan, PolicyGateResult


class SqliteEvaluationRepository:
    """Worker-owned durable store; integration into the public repo is proposed."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evaluation_quality_suites (
                  suite_id TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  payload_json TEXT NOT NULL,
                  PRIMARY KEY (suite_id, version)
                );
                CREATE TABLE IF NOT EXISTS evaluation_quality_runs (
                  run_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluation_quality_gates (
                  gate_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluation_quality_fix_plans (
                  plan_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );
                """
            )

    def next_suite_version(self, suite_id: str) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS version "
            "FROM evaluation_quality_suites WHERE suite_id = ?",
            (suite_id,),
        ).fetchone()
        return int(row["version"])

    def save_suite(self, suite: EvaluationSuite) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO evaluation_quality_suites "
                "(suite_id, version, payload_json) VALUES (?, ?, ?)",
                (suite.id, suite.version, suite.model_dump_json()),
            )

    def suite(self, suite_id: str, version: int) -> EvaluationSuite | None:
        row = self._connection.execute(
            "SELECT payload_json FROM evaluation_quality_suites "
            "WHERE suite_id = ? AND version = ?",
            (suite_id, version),
        ).fetchone()
        return EvaluationSuite.model_validate_json(row["payload_json"]) if row else None

    def save_run(self, run: EvaluationRun) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO evaluation_quality_runs "
                "(run_id, status, payload_json) VALUES (?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "status = excluded.status, payload_json = excluded.payload_json",
                (run.id, run.status, run.model_dump_json()),
            )

    def run(self, run_id: str) -> EvaluationRun | None:
        row = self._connection.execute(
            "SELECT payload_json FROM evaluation_quality_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return EvaluationRun.model_validate_json(row["payload_json"]) if row else None

    def save_gate(self, gate: PolicyGateResult) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO evaluation_quality_gates (gate_id, payload_json) "
                "VALUES (?, ?) ON CONFLICT(gate_id) DO UPDATE SET "
                "payload_json = excluded.payload_json",
                (gate.id, gate.model_dump_json()),
            )

    def gate(self, gate_id: str) -> PolicyGateResult | None:
        row = self._connection.execute(
            "SELECT payload_json FROM evaluation_quality_gates WHERE gate_id = ?",
            (gate_id,),
        ).fetchone()
        return PolicyGateResult.model_validate_json(row["payload_json"]) if row else None

    def save_fix_plan(self, plan: FixPlan) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO evaluation_quality_fix_plans (plan_id, payload_json) "
                "VALUES (?, ?) ON CONFLICT(plan_id) DO UPDATE SET "
                "payload_json = excluded.payload_json",
                (plan.id, plan.model_dump_json()),
            )

    def fix_plan(self, plan_id: str) -> FixPlan | None:
        row = self._connection.execute(
            "SELECT payload_json FROM evaluation_quality_fix_plans WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()
        return FixPlan.model_validate_json(row["payload_json"]) if row else None
