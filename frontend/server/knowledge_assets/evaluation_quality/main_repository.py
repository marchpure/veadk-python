from __future__ import annotations

import sqlite3
from typing import Any

from .models import EvaluationRun, EvaluationSuite, FixPlan, PolicyGateResult


class MainEvaluationRepository:
    """Main-owned persistence adapter for the Worker 4 domain service.

    The evaluation service remains Worker 4's domain implementation.  This
    adapter only maps its repository port onto Main's already-open database
    connection, so suite/run/gate/fix records share the BFF transaction store.
    """

    def __init__(self, connection) -> None:
        self.connection = connection
        self._sqlite = isinstance(connection, sqlite3.Connection)
        self._placeholder = "?" if self._sqlite else "%s"

    def _query(self, sql: str, params: tuple[Any, ...] = ()):
        if self._sqlite:
            return self.connection.execute(sql, params)
        return self.connection.execute(
            sql.replace("?", self._placeholder), params
        )

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()):
        return self._query(sql, params).fetchone()

    def next_suite_version(self, suite_id: str) -> int:
        row = self._fetchone(
            "SELECT COALESCE(MAX(version), 0) + 1 AS version "
            "FROM evaluation_quality_suites WHERE suite_id = ?",
            (suite_id,),
        )
        return int(row["version"])

    def save_suite(self, suite: EvaluationSuite) -> None:
        self._query(
            "INSERT INTO evaluation_quality_suites "
            "(suite_id, version, payload_json) VALUES (?, ?, ?)",
            (suite.id, suite.version, suite.model_dump_json()),
        )

    def suite(self, suite_id: str, version: int) -> EvaluationSuite | None:
        row = self._fetchone(
            "SELECT payload_json FROM evaluation_quality_suites "
            "WHERE suite_id = ? AND version = ?",
            (suite_id, version),
        )
        return EvaluationSuite.model_validate_json(row["payload_json"]) if row else None

    def save_run(self, run: EvaluationRun) -> None:
        self._query(
            "INSERT INTO evaluation_quality_runs "
            "(run_id, status, payload_json) VALUES (?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "status = excluded.status, payload_json = excluded.payload_json",
            (run.id, run.status, run.model_dump_json()),
        )

    def run(self, run_id: str) -> EvaluationRun | None:
        row = self._fetchone(
            "SELECT payload_json FROM evaluation_quality_runs WHERE run_id = ?",
            (run_id,),
        )
        return EvaluationRun.model_validate_json(row["payload_json"]) if row else None

    def save_gate(self, gate: PolicyGateResult) -> None:
        self._query(
            "INSERT INTO evaluation_quality_gates (gate_id, payload_json) "
            "VALUES (?, ?) ON CONFLICT(gate_id) DO UPDATE SET "
            "payload_json = excluded.payload_json",
            (gate.id, gate.model_dump_json()),
        )

    def gate(self, gate_id: str) -> PolicyGateResult | None:
        row = self._fetchone(
            "SELECT payload_json FROM evaluation_quality_gates WHERE gate_id = ?",
            (gate_id,),
        )
        return (
            PolicyGateResult.model_validate_json(row["payload_json"]) if row else None
        )

    def save_fix_plan(self, plan: FixPlan) -> None:
        self._query(
            "INSERT INTO evaluation_quality_fix_plans (plan_id, payload_json) "
            "VALUES (?, ?) ON CONFLICT(plan_id) DO UPDATE SET "
            "payload_json = excluded.payload_json",
            (plan.id, plan.model_dump_json()),
        )

    def fix_plan(self, plan_id: str) -> FixPlan | None:
        row = self._fetchone(
            "SELECT payload_json FROM evaluation_quality_fix_plans WHERE plan_id = ?",
            (plan_id,),
        )
        return FixPlan.model_validate_json(row["payload_json"]) if row else None
