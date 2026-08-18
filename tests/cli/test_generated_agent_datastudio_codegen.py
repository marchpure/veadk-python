from __future__ import annotations

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
