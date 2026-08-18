from __future__ import annotations

import json
import runpy
import sys

import pytest

from veadk.cli.generated_agent_codegen import (
    AgentDraft,
    SelectedSkill,
    debug_runtime_env_from_draft,
    generate_project_from_draft,
)
from veadk.cli.generated_agent_security import DebugPolicyError, validate_project_policy
from veadk.cli.generated_agent_skills import materialize_selected_skills


def _file_map(project) -> dict[str, str]:
    return {file.path: file.content for file in project.files}


def _assert_no_secret_leaks(files: dict[str, str]) -> None:
    joined = "\n".join(files.values())
    forbidden = [
        "must-not-enter-skill",
        "must-not-ship",
        "must-not-enter-draft",
        "redacted-connection-placeholder",
        "redacted-authorization-placeholder",
        "ciphertext",
        "DATASTUDIO_API_KEY",
    ]
    for value in forbidden:
        assert value not in joined


def test_datastudio_selected_skill_generates_rest_query_tool() -> None:
    project = generate_project_from_draft(
        AgentDraft(
            name="datastudio-agent",
            instruction="Answer with governed assets.",
            selectedSkills=[
                SelectedSkill(
                    source="datastudio",
                    folder="datastudio-dashboard-sales",
                    name="Sales Dashboard",
                    dataStudioAssetType="dashboard",
                    dataStudioAssetId="sales-dashboard",
                    dataStudioQueryUrl="/api/external/assets/dashboard/sales-dashboard/query",
                )
            ],
        )
    )
    files = _file_map(project)
    agent_py = files["agents/datastudio_agent/agent.py"]

    assert "requests.post(" in agent_py
    assert "_datastudio_query_url(" in agent_py
    assert "filters: dict | None = None" in agent_py
    assert "data_view_ids: list[str] | None = None" in agent_py
    assert 'mode: str = "summary"' in agent_py
    assert 'os.environ["BYAAN_MCP_API_KEY"]' in agent_py
    assert "DATASTUDIO_BASE_URL" in files[".env.example"]
    assert "BYAAN_MCP_API_KEY" in files[".env.example"]
    assert "requests>=2.32.0" in files["requirements.txt"]
    assert "/api/mcp/assets" not in agent_py
    assert "load_skill_from_dir(" in agent_py
    assert '"skills" / "datastudio-dashboard-sales"' in agent_py


@pytest.mark.asyncio
async def test_datastudio_selected_skill_materializes_skill_md_and_loads_it() -> None:
    draft = AgentDraft(
        name="datastudio-agent",
        instruction="Answer with governed assets.",
        selectedSkills=[
            SelectedSkill(
                source="datastudio",
                folder="datastudio-dashboard-sales",
                name="Sales Dashboard",
                description="Revenue dashboard.",
                dataStudioAssetType="dashboard",
                dataStudioAssetId="sales-dashboard",
                dataStudioCapabilityKind="dashboard_skill",
                dataStudioCapabilityPackage={
                    "package_type": "dashboard_skill",
                    "runtime": {
                        "query_url": "/api/external/assets/dashboard/sales-dashboard/query",
                        "api_key": "must-not-enter-skill",
                    },
                    "dashboard": {
                        "data_views": [{"id": "daily-gmv", "kind": "semantic_metric"}],
                    },
                    "governance": {
                        "allowed_metrics": ["GMV", "orders"],
                        "connection_obj_encrypted": "ciphertext",
                    },
                },
                dataStudioVersion="v2026.08",
                dataStudioGateScore=98,
                dataStudioMetrics=["GMV", "orders"],
                dataStudioDimensions=["region", "channel"],
                dataStudioTimeField="pay_date",
                dataStudioPermissionHint="Aggregate only; no buyer identifiers.",
                dataStudioExampleQuestions=["What was GMV last week?"],
                dataStudioEvidence=[
                    "sql: select sum(gmv) from sales",
                    "snapshot: oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw",
                    "data_through: 2026-08-15",
                    "hash: c67a52d9f8d2eaf92d6a7ca1b09aee321cf4da176499c618ef0e53214eb166eb",
                ],
            )
        ],
    )
    project = generate_project_from_draft(draft)
    await materialize_selected_skills(draft, project)
    files = _file_map(project)

    skill_md = files["skills/datastudio-dashboard-sales/SKILL.md"]
    assert "name: datastudio-dashboard-sales" in skill_md
    assert "asset_type: dashboard" in skill_md
    assert "asset_id: sales-dashboard" in skill_md
    assert "capability_kind: dashboard_skill" in skill_md
    assert "- Capability: `dashboard_skill`" in skill_md
    assert "## Capability Package" in skill_md
    assert "package_type: dashboard_skill" in skill_md
    assert "must-not-enter-skill" not in skill_md
    assert "ciphertext" not in skill_md
    assert "[REDACTED]" in skill_md
    assert "- Version: `v2026.08`" in skill_md
    assert "- GMV" in skill_md
    assert "- region" in skill_md
    assert "- `pay_date`" in skill_md
    assert "Aggregate only; no buyer identifiers." in skill_md
    assert "Every answer must cite SQL" in skill_md
    assert "Every answer must include snapshot freshness" in skill_md
    assert "Call the generated Data Studio REST function tool for every answer" in skill_md
    assert "customer names, phone numbers, addresses" in skill_md
    assert "snapshot: oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw" in skill_md
    assert '"skills" / "datastudio-dashboard-sales"' in files["agents/datastudio_agent/agent.py"]


@pytest.mark.asyncio
async def test_datastudio_skill_folder_fallback_matches_agent_loader() -> None:
    draft = AgentDraft(
        name="semantic-agent",
        selectedSkills=[
            SelectedSkill(
                source="datastudio",
                folder="",
                name="Sales Semantic Model",
                dataStudioAssetType="semantic_model",
                dataStudioAssetId="sales-semantic",
            )
        ],
    )
    project = generate_project_from_draft(draft)
    await materialize_selected_skills(draft, project)
    files = _file_map(project)

    assert "skills/datastudio-semantic-model-sales-semantic/SKILL.md" in files
    assert (
        '"skills" / "datastudio-semantic-model-sales-semantic"'
        in files["agents/semantic_agent/agent.py"]
    )


def test_datastudio_semantic_model_generates_typed_query_tool() -> None:
    project = generate_project_from_draft(
        AgentDraft(
            name="semantic-agent",
            selectedSkills=[
                SelectedSkill(
                    source="datastudio",
                    folder="datastudio-semantic-sales",
                    name="Sales Semantic Model",
                    dataStudioAssetType="semantic_model",
                    dataStudioAssetId="sales-semantic",
                    dataStudioMetrics=["revenue_revenue"],
                    dataStudioDimensions=["revenue_region"],
                    dataStudioTimeField="revenue.paid_at",
                )
            ],
        )
    )
    agent_py = _file_map(project)["agents/semantic_agent/agent.py"]

    assert "metric: str" in agent_py
    assert "dimension: str | None = None" in agent_py
    assert "grain: str | None = None" in agent_py
    assert "time_range: dict | None = None" in agent_py
    assert '"metric": metric' in agent_py
    assert '"time_range": time_range or {}' in agent_py
    assert "Use exact metric ids/names from this asset: revenue_revenue." in agent_py
    assert "Use exact dimension ids/names from this asset: revenue_region." in agent_py
    assert "Time field: revenue.paid_at." in agent_py


@pytest.mark.asyncio
async def test_datastudio_semantic_skill_packages_mdl_snapshot() -> None:
    draft = AgentDraft(
        name="semantic-agent",
        selectedSkills=[
            SelectedSkill(
                source="datastudio",
                folder="datastudio-semantic-sales",
                name="Sales Semantic Model",
                dataStudioAssetType="semantic_model",
                dataStudioAssetId="sales-semantic",
                dataStudioCapabilityKind="semantic_skill",
                dataStudioCapabilityPackage={
                    "package_type": "semantic_skill",
                    "runtime": {
                        "query_url": "/api/external/assets/semantic_model/sales-semantic/query"
                    },
                    "mdl": {
                        "schema": "byaan.mdl.v1",
                        "model": {"slug": "sales-semantic", "version": "v1"},
                        "metrics": [{"id": "revenue_revenue", "formula": "sum(revenue)"}],
                        "dimensions": [{"id": "revenue_region", "field": "region"}],
                        "relationships": [
                            {
                                "id": "orders_to_region",
                                "from": "orders",
                                "to": "region",
                                "cardinality": "many-to-one",
                            }
                        ],
                    },
                    "governance": {
                        "allowed_metrics": ["revenue_revenue"],
                        "allowed_dimensions": ["revenue_region"],
                        "raw_sql_fallback": False,
                    },
                    "api_key": "must-not-ship",
                },
            )
        ],
    )
    project = generate_project_from_draft(draft)
    await materialize_selected_skills(draft, project)

    files = _file_map(project)
    skill_md = files["skills/datastudio-semantic-sales/SKILL.md"]
    assert "capability_kind: semantic_skill" in skill_md
    assert "- Capability: `semantic_skill`" in skill_md
    assert "schema: byaan.mdl.v1" in skill_md
    assert "revenue_revenue" in skill_md
    assert "orders_to_region" in skill_md
    assert "MDL is bundled inside this Semantic Skill" in skill_md
    assert "must-not-ship" not in skill_md
    assert "api_key: '[REDACTED]'" in skill_md


@pytest.mark.asyncio
async def test_datastudio_semantic_skill_materializes_production_package() -> None:
    draft = AgentDraft(
        name="oracle-semantic-agent",
        instruction="Answer with governed Oracle semantic metrics.",
        selectedSkills=[
            SelectedSkill(
                source="datastudio",
                folder="datastudio-semantic-oracle-sales",
                name="Oracle Sales Semantic Model",
                description="Sanitized Oracle sales semantic model.",
                dataStudioAssetType="semantic_model",
                dataStudioAssetId="oracle-sales",
                dataStudioCapabilityKind="semantic_skill",
                dataStudioCapabilityPackage={
                    "package_type": "semantic_skill",
                    "source_ids": [
                        {"kind": "database", "id": "oracle-sales-sanitized"},
                        {"kind": "document", "id": "feishu-sales-handbook"},
                    ],
                    "runtime": {
                        "query_url": "/api/external/assets/semantic_model/oracle-sales/query",
                        "api_key": "must-not-enter-skill",
                    },
                    "mdl": {
                        "schema": "byaan.mdl.v1",
                        "model": {
                            "id": "oracle-sales",
                            "slug": "oracle-sales",
                            "version": "v3",
                        },
                        "entities": [
                            {
                                "id": "sales_order",
                                "table": "SALES_ORDER",
                                "primary_key": "ORDER_ID",
                                "fields": [
                                    {
                                        "name": "ORDER_ID",
                                        "source_field": "ORDER_ID",
                                        "type": "number",
                                        "role": "primary_key",
                                    },
                                    {
                                        "name": "SELL_DATE",
                                        "source_field": "SELL_DATE",
                                        "type": "date",
                                        "role": "time",
                                    },
                                ],
                            },
                            {
                                "id": "store",
                                "table": "STORE",
                                "primary_key": "STORE_ID",
                                "fields": [
                                    {
                                        "name": "STORE_ID",
                                        "source_field": "STORE_ID",
                                        "type": "number",
                                        "role": "primary_key",
                                    }
                                ],
                            },
                        ],
                        "relationships": [
                            {
                                "id": "sales_order_to_store",
                                "from": "sales_order",
                                "to": "store",
                                "join_fields": [
                                    {"from": "STORE_ID", "to": "STORE_ID"}
                                ],
                                "cardinality": "many-to-one",
                            }
                        ],
                        "metrics": [
                            {
                                "id": "ticket_count",
                                "name": "ticket_count",
                                "business_name": "Ticket Count",
                                "definition": "Number of sanitized sales tickets.",
                                "formula": "count_distinct(ORDER_ID)",
                                "time_field": "SELL_DATE",
                                "dimensions": ["store"],
                            }
                        ],
                        "dimensions": [
                            {
                                "id": "store",
                                "entity": "store",
                                "field": "STORE_NAME",
                                "description": "Sanitized store name.",
                            }
                        ],
                    },
                    "governance": {
                        "allowed_metrics": ["ticket_count"],
                        "allowed_dimensions": ["store", "SELL_DATE"],
                        "raw_sql_fallback": False,
                        "usage_policy": {
                            "permission_hint": "Aggregates only.",
                            "masked_fields": ["CUST_NAME", "CUST_TEL"],
                        },
                        "connection_obj_encrypted": "ciphertext",
                    },
                    "evidence": [
                        {
                            "kind": "metric_definition",
                            "metric": "ticket_count",
                            "definition": "Number of sanitized sales tickets.",
                        }
                    ],
                },
                dataStudioVersion="v3",
                dataStudioMetrics=["ticket_count"],
                dataStudioDimensions=["store", "SELL_DATE"],
                dataStudioTimeField="SELL_DATE",
                dataStudioPermissionHint="Aggregates only; customer/contact fields denied.",
                dataStudioQueryUrl="/api/external/assets/semantic_model/oracle-sales/query",
                dataStudioSourceCoverage=[
                    "飞书销售手册",
                    "Oracle 销售库",
                ],
                dataStudioFreshness={
                    "status": "current",
                    "snapshotId": "oracle-local-extract-sanitized",
                    "snapshotHash": "abc123",
                },
                dataStudioProvenance={
                    "datasource_kind": "oracle",
                    "connection_string": "redacted-connection-placeholder",
                },
                dataStudioUsagePolicy={
                    "permission_hint": "Aggregates only.",
                    "masked_fields": ["CUST_NAME", "CUST_TEL"],
                    "Authorization": "redacted-authorization-placeholder",
                },
            )
        ],
    )
    project = generate_project_from_draft(draft)
    await materialize_selected_skills(draft, project)
    files = _file_map(project)

    expected_paths = {
        "skills/datastudio-semantic-oracle-sales/manifest.json",
        "skills/datastudio-semantic-oracle-sales/SKILL.md",
        "skills/datastudio-semantic-oracle-sales/mdl/models.json",
        "skills/datastudio-semantic-oracle-sales/mdl/fields.json",
        "skills/datastudio-semantic-oracle-sales/mdl/relationships.json",
        "skills/datastudio-semantic-oracle-sales/mdl/metrics.json",
        "skills/datastudio-semantic-oracle-sales/mdl/dimensions.json",
        "skills/datastudio-semantic-oracle-sales/mdl/permissions.json",
        "skills/datastudio-semantic-oracle-sales/mdl/freshness.json",
        "skills/datastudio-semantic-oracle-sales/tools/query.py",
        "skills/datastudio-semantic-oracle-sales/policies/access.json",
        "skills/datastudio-semantic-oracle-sales/policies/masking.json",
        "skills/datastudio-semantic-oracle-sales/policies/refusal.json",
        "skills/datastudio-semantic-oracle-sales/evals/suite.json",
        "skills/datastudio-semantic-oracle-sales/evals/evidence.json",
    }
    assert expected_paths.issubset(files)

    manifest = json.loads(files["skills/datastudio-semantic-oracle-sales/manifest.json"])
    assert manifest["schema"] == "agentkit.semantic_skill.manifest.v1"
    assert manifest["asset"]["capability_kind"] == "semantic_skill"
    assert manifest["runtime"]["transport"] == "datastudio_external_rest"
    assert manifest["runtime"]["direct_database_access"] is False
    assert manifest["source_ids"] == [
        {"id": "oracle-sales-sanitized", "kind": "database"},
        {"id": "feishu-sales-handbook", "kind": "document"},
    ]

    metrics = json.loads(files["skills/datastudio-semantic-oracle-sales/mdl/metrics.json"])
    relationships = json.loads(
        files["skills/datastudio-semantic-oracle-sales/mdl/relationships.json"]
    )
    access_policy = json.loads(
        files["skills/datastudio-semantic-oracle-sales/policies/access.json"]
    )
    masking_policy = json.loads(
        files["skills/datastudio-semantic-oracle-sales/policies/masking.json"]
    )
    eval_suite = json.loads(files["skills/datastudio-semantic-oracle-sales/evals/suite.json"])
    tool_py = files["skills/datastudio-semantic-oracle-sales/tools/query.py"]
    agent_py = files["agents/oracle_semantic_agent/agent.py"]

    assert metrics["metrics"][0]["id"] == "ticket_count"
    assert relationships["relationships"][0]["id"] == "sales_order_to_store"
    assert access_policy["query_path"] == "Data Studio external asset REST only"
    assert access_policy["raw_sql_fallback"] is False
    assert "CUST_TEL" in masking_policy["masked_fields"]
    assert eval_suite["contract_version"] == "evaluation.suite_version.v1"
    assert {case["case_id"] for case in eval_suite["cases"]} == {
        "metric-sql-policy-freshness",
        "customer-contact-policy-denial",
    }
    assert "requests.post(" in tool_py
    assert "BYAAN_MCP_API_KEY" in tool_py
    assert "cx_Oracle" not in tool_py
    assert "oracledb" not in tool_py
    assert "direct_database_access" not in tool_py
    assert '"dataStudioCapabilityPackage":' not in agent_py
    assert "'dataStudioCapabilityPackage':" in agent_py
    assert "[REDACTED]" in agent_py
    _assert_no_secret_leaks(files)


def test_datastudio_debug_runtime_env_allows_rest_credentials() -> None:
    env = debug_runtime_env_from_draft(
        AgentDraft(
            name="semantic-agent",
            selectedSkills=[
                SelectedSkill(
                    source="datastudio",
                    folder="datastudio-semantic-sales",
                    dataStudioAssetType="semantic_model",
                    dataStudioAssetId="sales-semantic",
                )
            ],
            deployment={
                "envValues": {
                    "DATASTUDIO_BASE_URL": "http://127.0.0.1:18000",
                    "BYAAN_MCP_API_KEY": "byaan_live_gate_test",
                    "DATASTUDIO_API_KEY": "must-not-enter-runner",
                }
            },
        )
    )

    assert env["DATASTUDIO_BASE_URL"] == "http://127.0.0.1:18000"
    assert env["BYAAN_MCP_API_KEY"] == "byaan_live_gate_test"
    assert "DATASTUDIO_API_KEY" not in env


def test_generated_datastudio_tool_rejects_cross_origin_query_url(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = generate_project_from_draft(
        AgentDraft(
            name="datastudio-agent",
            selectedSkills=[
                SelectedSkill(
                    source="datastudio",
                    folder="datastudio-dashboard-sales",
                    dataStudioAssetType="dashboard",
                    dataStudioAssetId="sales-dashboard",
                    dataStudioQueryUrl="https://evil.example/api/external/assets/dashboard/sales-dashboard/query",
                )
            ],
        )
    )
    agent_py = _file_map(project)["agents/datastudio_agent/agent.py"]
    target = tmp_path / "agent.py"
    target.write_text(
        "import sys, types\n"
        "veadk = types.ModuleType('veadk')\n"
        "class Agent:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.__dict__.update(kwargs)\n"
        "veadk.Agent = Agent\n"
        "sys.modules['veadk'] = veadk\n"
        "google = types.ModuleType('google')\n"
        "adk = types.ModuleType('google.adk')\n"
        "code_executors = types.ModuleType('google.adk.code_executors')\n"
        "skills = types.ModuleType('google.adk.skills')\n"
        "skill_toolset = types.ModuleType('google.adk.tools.skill_toolset')\n"
        "tools = types.ModuleType('google.adk.tools')\n"
        "class UnsafeLocalCodeExecutor:\n"
        "    pass\n"
        "def load_skill_from_dir(path):\n"
        "    return {'path': str(path)}\n"
        "class SkillToolset:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.__dict__.update(kwargs)\n"
        "code_executors.UnsafeLocalCodeExecutor = UnsafeLocalCodeExecutor\n"
        "skills.load_skill_from_dir = load_skill_from_dir\n"
        "skill_toolset.SkillToolset = SkillToolset\n"
        "sys.modules['google'] = google\n"
        "sys.modules['google.adk'] = adk\n"
        "sys.modules['google.adk.code_executors'] = code_executors\n"
        "sys.modules['google.adk.skills'] = skills\n"
        "sys.modules['google.adk.tools'] = tools\n"
        "sys.modules['google.adk.tools.skill_toolset'] = skill_toolset\n"
        + agent_py,
        encoding="utf-8",
    )
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")
    monkeypatch.delenv("BYAAN_MCP_API_KEY", raising=False)
    module_names = [
        "veadk",
        "google",
        "google.adk",
        "google.adk.code_executors",
        "google.adk.skills",
        "google.adk.tools",
        "google.adk.tools.skill_toolset",
    ]
    originals = {name: sys.modules.get(name) for name in module_names}
    try:
        namespace = runpy.run_path(str(target))
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    class _Requests:
        called = False

        @staticmethod
        def post(*_args, **_kwargs):
            _Requests.called = True
            raise AssertionError("requests.post must not receive the bearer token")

    namespace["requests"] = _Requests

    with pytest.raises(ValueError, match="origin"):
        namespace["query_datastudio_dashboard_sales"]()
    assert _Requests.called is False


def test_project_policy_rejects_invalid_datastudio_query_url() -> None:
    for query_url in [
        "//evil.example/api/external/assets/dashboard/sales-dashboard/query",
        "/api/private/assets/dashboard/sales-dashboard/query",
        "ftp://byaan.example/api/external/assets/dashboard/sales-dashboard/query",
    ]:
        with pytest.raises(DebugPolicyError):
            validate_project_policy(
                AgentDraft(
                    name="datastudio-agent",
                    selectedSkills=[
                        SelectedSkill(
                            source="datastudio",
                            folder="datastudio-dashboard-sales",
                            dataStudioAssetType="dashboard",
                            dataStudioAssetId="sales-dashboard",
                            dataStudioQueryUrl=query_url,
                        )
                    ],
                )
            )
