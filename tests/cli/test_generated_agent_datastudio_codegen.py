from __future__ import annotations

import json
import py_compile
import runpy

import pytest

from veadk.cli.generated_agent_codegen import (
    AgentDraft,
    DeploymentConfig,
    SelectedSkill,
    debug_runtime_env_from_draft,
    generate_project_from_draft,
)
from veadk.cli.generated_agent_security import DebugPolicyError, validate_project_policy


def _file_map(project) -> dict[str, str]:
    return {file.path: file.content for file in project.files}


def test_datastudio_asset_generates_rest_query_tool(tmp_path) -> None:
    draft = AgentDraft(
        name="datastudio-agent",
        instruction="Answer with governed assets.",
        dataAssets=[
            SelectedSkill(
                source="datastudio",
                folder="datastudio-dashboard-sales",
                name="Sales Dashboard",
                dataStudioAssetType="dashboard",
                dataStudioAssetId="sales-dashboard",
            )
        ],
        deployment=DeploymentConfig(envValues={"BYAAN_MCP_API_KEY": "live-byaan-secret"}),
    )

    project = generate_project_from_draft(draft)
    files = _file_map(project)
    agent_py = files["agents/datastudio_agent/agent.py"]
    target = tmp_path / "agent.py"
    target.write_text(agent_py, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)

    assert "requests.post(" in agent_py
    assert "/api/external/assets/dashboard/sales-dashboard/query" in agent_py
    assert 'os.environ["BYAAN_MCP_API_KEY"]' in agent_py
    assert "DATASTUDIO_BASE_URL" in agent_py
    assert "/api/mcp/assets" not in agent_py
    assert "TrustedMcpToolset" not in agent_py
    assert "DATASTUDIO_API_KEY" not in json.dumps(files)
    assert "live-byaan-secret" not in json.dumps(files)
    assert debug_runtime_env_from_draft(draft)["BYAAN_MCP_API_KEY"] == "live-byaan-secret"


def test_datastudio_asset_with_explicit_query_url_uses_external_rest_contract() -> None:
    project = generate_project_from_draft(
        AgentDraft(
            name="datastudio-agent",
            dataAssets=[
                SelectedSkill(
                    source="datastudio",
                    folder="datastudio-model-retention",
                    dataStudioAssetType="semantic_model",
                    dataStudioAssetId="retention",
                    dataStudioQueryUrl="https://byaan.example/api/external/assets/semantic_model/retention/query",
                )
            ],
        )
    )
    agent_py = _file_map(project)["agents/datastudio_agent/agent.py"]

    assert "https://byaan.example/api/external/assets/semantic_model/retention/query" in agent_py
    assert "DATASTUDIO_BASE_URL" in agent_py
    assert "/api/mcp/assets" not in agent_py


def test_generated_datastudio_tool_rejects_cross_origin_query_url(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = generate_project_from_draft(
        AgentDraft(
            name="datastudio-agent",
            dataAssets=[
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
        "google = types.ModuleType('google')\n"
        "adk = types.ModuleType('google.adk')\n"
        "agents = types.ModuleType('google.adk.agents')\n"
        "class Agent:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.__dict__.update(kwargs)\n"
        "agents.Agent = Agent\n"
        "sys.modules['google'] = google\n"
        "sys.modules['google.adk'] = adk\n"
        "sys.modules['google.adk.agents'] = agents\n"
        + agent_py,
        encoding="utf-8",
    )
    monkeypatch.setenv("DATASTUDIO_BASE_URL", "https://byaan.example")
    monkeypatch.delenv("BYAAN_MCP_API_KEY", raising=False)
    namespace = runpy.run_path(str(target))

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


def test_project_policy_rejects_legacy_datastudio_mcp_url() -> None:
    draft = AgentDraft(
        name="datastudio-agent",
        dataAssets=[
            SelectedSkill(
                source="datastudio",
                folder="datastudio-dashboard-sales",
                dataStudioAssetType="dashboard",
                dataStudioAssetId="sales-dashboard",
                dataStudioMcpUrl="https://byaan.example/api/mcp/assets/dashboard/sales-dashboard",
            )
        ],
    )

    with pytest.raises(DebugPolicyError, match="REST query_url"):
        validate_project_policy(draft)


def test_project_policy_rejects_protocol_relative_and_non_external_query_url() -> None:
    for query_url in [
        "//evil.example/api/external/assets/dashboard/sales-dashboard/query",
        "/api/private/assets/dashboard/sales-dashboard/query",
        "ftp://byaan.example/api/external/assets/dashboard/sales-dashboard/query",
    ]:
        draft = AgentDraft(
            name="datastudio-agent",
            dataAssets=[
                SelectedSkill(
                    source="datastudio",
                    folder="datastudio-dashboard-sales",
                    dataStudioAssetType="dashboard",
                    dataStudioAssetId="sales-dashboard",
                    dataStudioQueryUrl=query_url,
                )
            ],
        )
        with pytest.raises(DebugPolicyError):
            validate_project_policy(draft)
