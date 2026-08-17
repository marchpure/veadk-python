from __future__ import annotations

import runpy
import sys

import pytest

from veadk.cli.generated_agent_codegen import (
    AgentDraft,
    SelectedSkill,
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
    assert 'os.environ["BYAAN_MCP_API_KEY"]' in agent_py
    assert "DATASTUDIO_BASE_URL" in files[".env.example"]
    assert "BYAAN_MCP_API_KEY" in files[".env.example"]
    assert "requests>=2.32.0" in files["requirements.txt"]
    assert "/api/mcp/assets" not in agent_py


@pytest.mark.asyncio
async def test_datastudio_selected_skill_is_not_materialized_as_skill_folder() -> None:
    draft = AgentDraft(
        name="datastudio-agent",
        instruction="Answer with governed assets.",
        selectedSkills=[
            SelectedSkill(
                source="datastudio",
                folder="datastudio-dashboard-sales",
                name="Sales Dashboard",
                dataStudioAssetType="dashboard",
                dataStudioAssetId="sales-dashboard",
            )
        ],
    )
    project = generate_project_from_draft(draft)
    await materialize_selected_skills(draft, project)

    assert all(not file.path.startswith("skills/") for file in project.files)


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
        + agent_py,
        encoding="utf-8",
    )
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")
    monkeypatch.delenv("BYAAN_MCP_API_KEY", raising=False)
    original_veadk = sys.modules.get("veadk")
    try:
        namespace = runpy.run_path(str(target))
    finally:
        if original_veadk is None:
            sys.modules.pop("veadk", None)
        else:
            sys.modules["veadk"] = original_veadk

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
