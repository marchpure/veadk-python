"""Persistent, versioned TemplateSpec registry for the Skill builder."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from pydantic import TypeAdapter

from .contract_base import TemplateRef, TemplateSpec


def template_digest(spec: TemplateSpec) -> str:
    payload = spec.model_dump(mode="json", by_alias=True)
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def template_ref(spec: TemplateSpec) -> TemplateRef:
    return TemplateRef(
        template_id=spec.template_id,
        version=spec.version,
        digest=template_digest(spec),
    )


def render_spec_md(spec: TemplateSpec) -> str:
    """Portable spec.md representation with a canonical JSON contract block."""

    body = json.dumps(
        spec.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return (
        f"# {spec.display_name}\n\n"
        f"{spec.scenario}\n\n"
        "```template-spec+json\n"
        f"{body}\n"
        "```\n"
    )


def parse_spec_md(content: str) -> TemplateSpec:
    marker = "```template-spec+json\n"
    if marker not in content:
        raise ValueError("spec.md must contain a template-spec+json block")
    payload = content.split(marker, 1)[1].split("\n```", 1)[0]
    return TypeAdapter(TemplateSpec).validate_json(payload)


class SqliteTemplateRegistry:
    """Workspace-scoped storage; built-ins are seeded and immutable."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS template_spec_versions (
              template_id TEXT NOT NULL,
              version TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              digest TEXT NOT NULL,
              spec_json TEXT NOT NULL,
              spec_md TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (template_id, version, workspace_id),
              UNIQUE (digest)
            )
            """
        )
        self.connection.commit()
        self._seed_builtins()

    def put(self, spec: TemplateSpec) -> TemplateRef:
        workspace = "__builtin__" if spec.builtin else str(spec.owner_workspace_id)
        digest = template_digest(spec)
        existing = self.connection.execute(
            """
            SELECT digest FROM template_spec_versions
            WHERE template_id = ? AND version = ? AND workspace_id = ?
            """,
            (spec.template_id, spec.version, workspace),
        ).fetchone()
        if existing and existing["digest"] != digest:
            raise ValueError("TemplateSpec versions are immutable")
        self.connection.execute(
            """
            INSERT OR IGNORE INTO template_spec_versions
              (template_id, version, workspace_id, digest, spec_json, spec_md)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                spec.template_id,
                spec.version,
                workspace,
                digest,
                spec.model_dump_json(by_alias=True),
                render_spec_md(spec),
            ),
        )
        self.connection.commit()
        return template_ref(spec)

    def get(
        self, template_id: str, version: str, workspace_id: str
    ) -> TemplateSpec | None:
        row = self.connection.execute(
            """
            SELECT spec_json FROM template_spec_versions
            WHERE template_id = ? AND version = ?
              AND workspace_id IN (?, '__builtin__')
            ORDER BY CASE WHEN workspace_id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (template_id, version, workspace_id, workspace_id),
        ).fetchone()
        return TemplateSpec.model_validate_json(row["spec_json"]) if row else None

    def list(self, workspace_id: str) -> list[TemplateSpec]:
        rows = self.connection.execute(
            """
            SELECT spec_json FROM template_spec_versions
            WHERE workspace_id IN (?, '__builtin__')
            ORDER BY builtin_sort, template_id, version
            """.replace(
                "builtin_sort",
                "CASE WHEN workspace_id = '__builtin__' THEN 0 ELSE 1 END",
            ),
            (workspace_id,),
        ).fetchall()
        return [TemplateSpec.model_validate_json(row["spec_json"]) for row in rows]

    def copy_builtin(
        self,
        template_id: str,
        version: str,
        *,
        workspace_id: str,
        new_template_id: str,
        new_version: str = "1.0.0",
        display_name: str | None = None,
    ) -> TemplateRef:
        source = self.get(template_id, version, workspace_id)
        if source is None or not source.builtin:
            raise ValueError("only built-in templates can be copied")
        copied = source.model_copy(
            update={
                "template_id": new_template_id,
                "version": new_version,
                "display_name": display_name or source.display_name,
                "builtin": False,
                "owner_workspace_id": workspace_id,
                "copied_from": template_ref(source),
            }
        )
        return self.put(copied)

    def spec_md(self, template_id: str, version: str, workspace_id: str) -> str | None:
        spec = self.get(template_id, version, workspace_id)
        return render_spec_md(spec) if spec else None

    def _seed_builtins(self) -> None:
        for spec in builtin_template_specs():
            self.put(spec)


def builtin_template_specs() -> tuple[TemplateSpec, ...]:
    shared = {
        "version": "1.0.0",
        "input_schema": {"type": "object", "additionalProperties": False},
        "evidence_rules": [
            {
                "evidenceKind": "data_revision",
                "description": "Every conclusion pins its immutable input revision.",
            },
            {
                "evidenceKind": "trace",
                "description": "Every trial run records a trace.",
            },
        ],
        "quality_gates": [
            {
                "gateId": "typed-output",
                "description": "Output validates against its ViewModel.",
            },
            {"gateId": "evidence", "description": "Required evidence is present."},
        ],
        "allowed_actions": ["trial_run", "evaluate", "publish"],
        "compatibility": {"targets": ["agentkit", "mcp", "openapi", "codex"]},
        "builtin": True,
    }
    definitions = (
        (
            "dashboard",
            "经营分析看板",
            "用真实结构化数据生成 KPI、图表、明细与下钻。",
            ["tabular"],
            "analysis",
            "dashboard",
            ["golden.query"],
        ),
        (
            "semantic",
            "语义模型",
            "发现实体、字段、指标、维度、关系并生成 MDL。",
            ["tabular"],
            "semantic",
            "semantic",
            ["schema.discover"],
        ),
        (
            "sop",
            "排查与处置 SOP",
            "把规则、历史记录和工具编排成可验证的执行流程。",
            ["document", "tool"],
            "sop",
            "sop",
            ["knowledge.search", "tool.call"],
        ),
        (
            "knowledge",
            "知识问答",
            "检索授权知识并提供引用，证据不足时拒答。",
            ["knowledge"],
            "knowledge",
            "knowledge",
            ["knowledge.search"],
        ),
        (
            "graph-ontology",
            "知识图谱与本体",
            "从来源证据构建实体、关系并报告冲突。",
            ["tabular"],
            "graph_ontology",
            "graph_ontology",
            ["schema.discover"],
        ),
        (
            "monitoring",
            "指标监控",
            "基于真实观测产生告警、last-good 和失败追踪。",
            ["observation"],
            "monitoring",
            "monitoring",
            ["golden.query"],
        ),
    )
    return tuple(
        TemplateSpec(
            template_id=template_id,
            display_name=name,
            scenario=scenario,
            required_context_kinds=context,
            capability_intent=kind,
            default_renderer=renderer,
            allowed_tools=tools,
            execution_instructions=[
                "Resolve immutable context revisions.",
                "Execute the typed capability.",
                "Validate evidence and render the immutable Skill view.",
            ],
            **shared,
        )
        for template_id, name, scenario, context, kind, renderer, tools in definitions
    )
