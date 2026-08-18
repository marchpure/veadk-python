"""SQLite persistence helpers for Knowledge Asset evaluation."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..repository import (
    KnowledgeAssetNotFound,
    KnowledgeAssetRepository,
    dumps_json,
    loads_json,
    utc_now_sql,
)


def install_evaluation_repository_methods() -> None:
    """Attach evaluation methods to ``KnowledgeAssetRepository``.

    The main store already owns SQLite initialization and locking. Keeping these
    methods in the evaluation package avoids mixing the evaluation domain logic
    into the broader asset repository source.
    """

    if hasattr(KnowledgeAssetRepository, "create_eval_suite"):
        return

    KnowledgeAssetRepository.create_eval_suite = create_eval_suite  # type: ignore[attr-defined]
    KnowledgeAssetRepository.list_eval_suites = list_eval_suites  # type: ignore[attr-defined]
    KnowledgeAssetRepository.get_eval_suite = get_eval_suite  # type: ignore[attr-defined]
    KnowledgeAssetRepository.create_eval_case = create_eval_case  # type: ignore[attr-defined]
    KnowledgeAssetRepository.list_eval_cases = list_eval_cases  # type: ignore[attr-defined]
    KnowledgeAssetRepository.create_eval_run = create_eval_run  # type: ignore[attr-defined]
    KnowledgeAssetRepository.update_eval_run = update_eval_run  # type: ignore[attr-defined]
    KnowledgeAssetRepository.list_eval_runs = list_eval_runs  # type: ignore[attr-defined]
    KnowledgeAssetRepository.get_eval_run = get_eval_run  # type: ignore[attr-defined]
    KnowledgeAssetRepository.create_eval_result = create_eval_result  # type: ignore[attr-defined]
    KnowledgeAssetRepository.list_eval_results = list_eval_results  # type: ignore[attr-defined]
    KnowledgeAssetRepository.put_eval_optimization = put_eval_optimization  # type: ignore[attr-defined]
    KnowledgeAssetRepository.list_eval_optimizations = list_eval_optimizations  # type: ignore[attr-defined]


def create_eval_suite(self: KnowledgeAssetRepository, row: dict[str, Any]) -> dict[str, Any]:
    with self._write() as conn:  # type: ignore[attr-defined]
        self.get_space(row["space_id"], conn=conn)
        conn.execute(
            """
            INSERT INTO knowledge_asset_eval_suites (
                id, space_id, name, description, target_kind, target_asset_id
            )
            VALUES (
                :id, :space_id, :name, :description, :target_kind,
                :target_asset_id
            )
            """,
            row,
        )
        return get_eval_suite(self, row["id"], conn=conn)


def list_eval_suites(
    self: KnowledgeAssetRepository,
    *,
    space_id: str | None = None,
    target_kind: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if space_id:
        clauses.append("s.space_id = ?")
        params.append(space_id)
    if target_kind:
        clauses.append("s.target_kind = ?")
        params.append(target_kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with self._read() as conn:  # type: ignore[attr-defined]
        return _rows(
            conn.execute(
                f"""
                SELECT s.*, count(c.id) AS case_count
                FROM knowledge_asset_eval_suites s
                LEFT JOIN knowledge_asset_eval_cases c ON c.suite_id = s.id
                {where}
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id
                """,
                tuple(params),
            )
        )


def get_eval_suite(
    self: KnowledgeAssetRepository,
    suite_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    active = conn or self._connect()  # type: ignore[attr-defined]
    try:
        row = active.execute(
            """
            SELECT s.*, count(c.id) AS case_count
            FROM knowledge_asset_eval_suites s
            LEFT JOIN knowledge_asset_eval_cases c ON c.suite_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (suite_id,),
        ).fetchone()
        if row is None:
            raise KnowledgeAssetNotFound("Knowledge asset eval suite not found.")
        return dict(row)
    finally:
        if conn is None:
            active.close()


def create_eval_case(self: KnowledgeAssetRepository, row: dict[str, Any]) -> dict[str, Any]:
    with self._write() as conn:  # type: ignore[attr-defined]
        suite = get_eval_suite(self, row["suite_id"], conn=conn)
        row.setdefault("target_kind", suite["target_kind"])
        conn.execute(
            """
            INSERT INTO knowledge_asset_eval_cases (
                id, suite_id, target_kind, input, question, intent,
                expected_metric, expected_dimensions_json,
                expected_sql_contains_json, expected_policy_decision,
                expected_dashboard_tiles_json, expected_evidence_keys_json,
                tags_json
            )
            VALUES (
                :id, :suite_id, :target_kind, :input, :question, :intent,
                :expected_metric, :expected_dimensions_json,
                :expected_sql_contains_json, :expected_policy_decision,
                :expected_dashboard_tiles_json, :expected_evidence_keys_json,
                :tags_json
            )
            """,
            row,
        )
        conn.execute(
            f"UPDATE knowledge_asset_eval_suites SET updated_at = {utc_now_sql()} WHERE id = ?",
            (row["suite_id"],),
        )
        return _case_payload(get_eval_case(self, row["id"], conn=conn))


def get_eval_case(
    self: KnowledgeAssetRepository,
    case_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    active = conn or self._connect()  # type: ignore[attr-defined]
    try:
        row = active.execute(
            "SELECT * FROM knowledge_asset_eval_cases WHERE id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            raise KnowledgeAssetNotFound("Knowledge asset eval case not found.")
        return dict(row)
    finally:
        if conn is None:
            active.close()


def list_eval_cases(
    self: KnowledgeAssetRepository,
    *,
    suite_id: str,
) -> list[dict[str, Any]]:
    with self._read() as conn:  # type: ignore[attr-defined]
        return [
            _case_payload(row)
            for row in _rows(
                conn.execute(
                    """
                    SELECT * FROM knowledge_asset_eval_cases
                    WHERE suite_id = ?
                    ORDER BY created_at ASC, id
                    """,
                    (suite_id,),
                )
            )
        ]


def create_eval_run(self: KnowledgeAssetRepository, row: dict[str, Any]) -> dict[str, Any]:
    with self._write() as conn:  # type: ignore[attr-defined]
        get_eval_suite(self, row["suite_id"], conn=conn)
        conn.execute(
            """
            INSERT INTO knowledge_asset_eval_runs (
                id, suite_id, target_kind, target_asset_id, status, score,
                started_at, completed_at, model_status, generation_mode,
                result_summary_json
            )
            VALUES (
                :id, :suite_id, :target_kind, :target_asset_id, :status, :score,
                :started_at, :completed_at, :model_status, :generation_mode,
                :result_summary_json
            )
            """,
            row,
        )
        return get_eval_run(self, row["id"], conn=conn)


def update_eval_run(
    self: KnowledgeAssetRepository,
    run_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    if not patch:
        return get_eval_run(self, run_id)
    fields = ", ".join(f"{key} = :{key}" for key in patch)
    params = {**patch, "id": run_id}
    with self._write() as conn:  # type: ignore[attr-defined]
        cursor = conn.execute(
            f"UPDATE knowledge_asset_eval_runs SET {fields}, updated_at = {utc_now_sql()} "
            "WHERE id = :id",
            params,
        )
        if cursor.rowcount == 0:
            raise KnowledgeAssetNotFound("Knowledge asset eval run not found.")
        return get_eval_run(self, run_id, conn=conn)


def list_eval_runs(
    self: KnowledgeAssetRepository,
    *,
    suite_id: str | None = None,
    target_kind: str | None = None,
    target_asset_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if suite_id:
        clauses.append("suite_id = ?")
        params.append(suite_id)
    if target_kind:
        clauses.append("target_kind = ?")
        params.append(target_kind)
    if target_asset_id:
        clauses.append("target_asset_id = ?")
        params.append(target_asset_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    bounded = max(1, min(int(limit), 100))
    with self._read() as conn:  # type: ignore[attr-defined]
        return _rows(
            conn.execute(
                f"""
                SELECT * FROM knowledge_asset_eval_runs
                {where}
                ORDER BY updated_at DESC, id
                LIMIT ?
                """,
                tuple([*params, bounded]),
            )
        )


def get_eval_run(
    self: KnowledgeAssetRepository,
    run_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    active = conn or self._connect()  # type: ignore[attr-defined]
    try:
        row = active.execute(
            "SELECT * FROM knowledge_asset_eval_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KnowledgeAssetNotFound("Knowledge asset eval run not found.")
        return dict(row)
    finally:
        if conn is None:
            active.close()


def create_eval_result(
    self: KnowledgeAssetRepository,
    row: dict[str, Any],
) -> dict[str, Any]:
    with self._write() as conn:  # type: ignore[attr-defined]
        get_eval_run(self, row["run_id"], conn=conn)
        get_eval_case(self, row["case_id"], conn=conn)
        conn.execute(
            """
            INSERT INTO knowledge_asset_eval_results (
                id, run_id, case_id, status, score, reason, actual_output_json,
                actual_sql, actual_rows_preview_json,
                actual_policy_decision_json, actual_freshness_json,
                tool_calls_json, evidence_json, dashboard_spec_diff_json
            )
            VALUES (
                :id, :run_id, :case_id, :status, :score, :reason,
                :actual_output_json, :actual_sql, :actual_rows_preview_json,
                :actual_policy_decision_json, :actual_freshness_json,
                :tool_calls_json, :evidence_json, :dashboard_spec_diff_json
            )
            """,
            row,
        )
        return _result_payload(get_eval_result(self, row["id"], conn=conn))


def get_eval_result(
    self: KnowledgeAssetRepository,
    result_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    active = conn or self._connect()  # type: ignore[attr-defined]
    try:
        row = active.execute(
            "SELECT * FROM knowledge_asset_eval_results WHERE id = ?",
            (result_id,),
        ).fetchone()
        if row is None:
            raise KnowledgeAssetNotFound("Knowledge asset eval result not found.")
        return dict(row)
    finally:
        if conn is None:
            active.close()


def list_eval_results(
    self: KnowledgeAssetRepository,
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    with self._read() as conn:  # type: ignore[attr-defined]
        return [
            _result_payload(row)
            for row in _rows(
                conn.execute(
                    """
                    SELECT * FROM knowledge_asset_eval_results
                    WHERE run_id = ?
                    ORDER BY created_at ASC, id
                    """,
                    (run_id,),
                )
            )
        ]


def put_eval_optimization(
    self: KnowledgeAssetRepository,
    row: dict[str, Any],
) -> dict[str, Any]:
    with self._write() as conn:  # type: ignore[attr-defined]
        conn.execute(
            """
            INSERT INTO knowledge_asset_eval_optimizations (
                target_kind, target_asset_id, generated_at, source_run_ids_json,
                groups_json
            )
            VALUES (
                :target_kind, :target_asset_id, :generated_at,
                :source_run_ids_json, :groups_json
            )
            ON CONFLICT(target_kind, target_asset_id) DO UPDATE SET
                generated_at = excluded.generated_at,
                source_run_ids_json = excluded.source_run_ids_json,
                groups_json = excluded.groups_json
            """,
            row,
        )
        stored = conn.execute(
            """
            SELECT * FROM knowledge_asset_eval_optimizations
            WHERE target_kind = ? AND target_asset_id = ?
            """,
            (row["target_kind"], row["target_asset_id"]),
        ).fetchone()
        return dict(stored)


def list_eval_optimizations(
    self: KnowledgeAssetRepository,
    *,
    target_kind: str | None = None,
    target_asset_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if target_kind:
        clauses.append("target_kind = ?")
        params.append(target_kind)
    if target_asset_id:
        clauses.append("target_asset_id = ?")
        params.append(target_asset_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with self._read() as conn:  # type: ignore[attr-defined]
        return _rows(
            conn.execute(
                f"""
                SELECT * FROM knowledge_asset_eval_optimizations
                {where}
                ORDER BY generated_at DESC, target_kind, target_asset_id
                """,
                tuple(params),
            )
        )


def _case_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "expected_dimensions": loads_json(row.get("expected_dimensions_json"), []),
        "expected_sql_contains": loads_json(row.get("expected_sql_contains_json"), []),
        "expected_dashboard_tiles": loads_json(
            row.get("expected_dashboard_tiles_json"),
            [],
        ),
        "expected_evidence_keys": loads_json(row.get("expected_evidence_keys_json"), []),
        "tags": loads_json(row.get("tags_json"), []),
    }


def _result_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "actual_output": loads_json(row.get("actual_output_json"), None),
        "actual_rows_preview": loads_json(row.get("actual_rows_preview_json"), []),
        "actual_policy_decision": loads_json(
            row.get("actual_policy_decision_json"),
            {},
        ),
        "actual_freshness": loads_json(row.get("actual_freshness_json"), {}),
        "tool_calls": loads_json(row.get("tool_calls_json"), []),
        "evidence": loads_json(row.get("evidence_json"), []),
        "dashboard_spec_diff": loads_json(row.get("dashboard_spec_diff_json"), {}),
    }


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


__all__ = ["install_evaluation_repository_methods", "dumps_json", "loads_json"]
