# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate a minimal VeADK project from Studio AgentDraft JSON."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_PYTHON_LICENSE_HEADER = """# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
"""

_DATASTUDIO_URL_HELPERS = '''
def _datastudio_query_url(path_or_url: str) -> str:
    """Resolve and validate a Data Studio query URL before attaching BYAAN_MCP_API_KEY."""
    base = os.environ["DATASTUDIO_BASE_URL"].rstrip("/")
    parsed_base = urlparse(base)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
        raise ValueError("DATASTUDIO_BASE_URL must be an http(s) URL")

    candidate = (path_or_url or "").strip()
    if candidate.startswith("/"):
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme or parsed_candidate.netloc:
            raise ValueError("Data Studio query URL must not be protocol-relative")
        url = urljoin(f"{base}/", candidate.lstrip("/"))
    else:
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme not in {"http", "https"} or not parsed_candidate.netloc:
            raise ValueError("Data Studio query URL must be relative or http(s)")
        if parsed_candidate.scheme != parsed_base.scheme or parsed_candidate.netloc != parsed_base.netloc:
            raise ValueError("Data Studio query URL origin does not match DATASTUDIO_BASE_URL")
        url = candidate

    parsed_url = urlparse(url)
    if parsed_url.scheme != parsed_base.scheme or parsed_url.netloc != parsed_base.netloc:
        raise ValueError("Data Studio query URL origin does not match DATASTUDIO_BASE_URL")
    if not parsed_url.path.startswith("/api/external/assets/"):
        raise ValueError("Data Studio query URL must target /api/external/assets")
    return url
'''.strip()


class GeneratedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str


class GeneratedProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    files: list[GeneratedFile]


class CustomTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    description: str = ""


class McpTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    transport: Literal["http", "stdio"] = "http"
    url: str = ""
    authToken: str = ""
    authTokenEnv: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)


class SelectedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["skillhub", "local", "skillspace", "datastudio"] = "skillhub"
    folder: str = ""
    name: str = ""
    description: str = ""
    slug: str = ""
    namespace: str = "public"
    localFiles: list[GeneratedFile] = Field(default_factory=list)
    skillSpaceId: str = ""
    skillSpaceName: str = ""
    skillId: str = ""
    version: str = ""
    dataStudioAssetType: Literal["dashboard", "semantic_model"] | str = ""
    dataStudioAssetId: str = ""
    dataStudioVersion: str = ""
    dataStudioGateScore: float | None = None
    dataStudioMetrics: list[str] = Field(default_factory=list)
    dataStudioExampleQuestions: list[str] = Field(default_factory=list)
    dataStudioPermissionHint: str = ""
    dataStudioQueryUrl: str = ""
    dataStudioMcpUrl: str = ""
    dataStudioTimeField: str = ""
    dataStudioDimensions: list[str] = Field(default_factory=list)
    dataStudioEvidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_folder(self) -> "SelectedSkill":
        if not self.folder:
            self.folder = self.name or self.dataStudioAssetId or self.slug.rsplit("/", 1)[-1] or "skill"
        if not self.name:
            self.name = self.folder
        return self


class DeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feishuEnabled: bool = False
    modelApiKeyId: str = ""
    modelApiKeyName: str = ""
    envValues: dict[str, str] = Field(default_factory=dict)


class AgentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    description: str = ""
    instruction: str = ""
    agentType: Literal["llm", "sequential", "parallel", "loop", "a2a"] = "llm"
    modelName: str = ""
    modelProvider: str = ""
    modelApiBase: str = ""
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    customTools: list[CustomTool] = Field(default_factory=list)
    mcpTools: list[McpTool] = Field(default_factory=list)
    selectedSkills: list[SelectedSkill] = Field(default_factory=list)
    dataAssets: list[SelectedSkill] = Field(default_factory=list)
    subAgents: list["AgentDraft"] = Field(default_factory=list)
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)


class GeneratedAgentProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: AgentDraft


def normalize_and_validate_draft(raw: Any) -> AgentDraft:
    if isinstance(raw, AgentDraft):
        return raw
    return AgentDraft.model_validate(raw)


def debug_runtime_env_from_draft(draft: AgentDraft) -> dict[str, str]:
    values = dict(draft.deployment.envValues)
    for sub_agent in draft.subAgents:
        values.update(debug_runtime_env_from_draft(sub_agent))
    return values


def generate_project_from_draft(raw: AgentDraft | dict[str, Any]) -> GeneratedProject:
    draft = normalize_and_validate_draft(raw)
    project_name = ident(draft.name, "agent")
    agent_py = _render_agent_py(project_name, draft)
    env_example = render_env_example(draft)
    files = [
        GeneratedFile(path="app.py", content=_render_app_py(project_name)),
        GeneratedFile(path="agents/__init__.py", content=""),
        GeneratedFile(path=f"agents/{project_name}/__init__.py", content="from .agent import root_agent\n"),
        GeneratedFile(path=f"agents/{project_name}/agent.py", content=agent_py),
        GeneratedFile(path=".env.example", content=env_example),
        GeneratedFile(path="requirements.txt", content="veadk-python>=0.2.9\nrequests>=2.32.0\n"),
        GeneratedFile(path="README.md", content=f"# {draft.name or project_name}\n"),
    ]
    return GeneratedProject(name=project_name, files=files)


def render_env_example(draft: AgentDraft) -> str:
    lines = [
        "# Copy to .env and fill real values.",
        "MODEL_AGENT_API_KEY=replace-with-your-model-api-key",
    ]
    if _data_assets(draft):
        lines.extend(
            [
                "DATASTUDIO_BASE_URL=https://byaan.example",
                "BYAAN_MCP_API_KEY=replace-with-your-byaan-api-key",
            ]
        )
    return "\n".join(lines) + "\n"


def ident(raw: str, fallback: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", (raw or "").strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return fallback
    if value[0].isdigit():
        return f"a_{value}"
    return value


def _py_str(value: str) -> str:
    escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _py_triple(value: str) -> str:
    escaped = (value or "").replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return f'"""{escaped}"""'


def _data_assets(draft: AgentDraft) -> list[SelectedSkill]:
    return [
        asset
        for asset in draft.dataAssets
        if asset.source == "datastudio"
        and asset.dataStudioAssetType in {"dashboard", "semantic_model"}
        and asset.dataStudioAssetId.strip()
    ]


def _query_url_literal(asset: SelectedSkill) -> str:
    explicit = (asset.dataStudioQueryUrl or "").strip()
    if explicit:
        return _py_str(explicit)
    asset_type = asset.dataStudioAssetType.strip()
    asset_id = asset.dataStudioAssetId.strip()
    return _py_str(f"/api/external/assets/{asset_type}/{asset_id}/query")


def _tool_name(asset: SelectedSkill) -> str:
    return ident(f"query_{asset.folder or asset.name or asset.dataStudioAssetId}", "query_datastudio_asset")


def _render_datastudio_tool(asset: SelectedSkill) -> str:
    function_name = _tool_name(asset)
    asset_label = asset.name or asset.dataStudioAssetId
    query_url = _query_url_literal(asset)
    return f'''
def {function_name}(query: str = "", filters: dict | None = None, limit: int = 100) -> dict:
    """Query the Byaan Data Studio asset {asset_label} through the REST external API."""
    query_url = _datastudio_query_url({query_url})
    token = os.environ["BYAAN_MCP_API_KEY"]
    payload = {{"query": query, "filters": filters or {{}}, "limit": limit}}
    response = requests.post(
        query_url,
        json=payload,
        headers={{"Authorization": f"Bearer {{token}}"}},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("data", body) if isinstance(body, dict) else {{"data": body}}
'''.strip()


def _render_agent_py(project_name: str, draft: AgentDraft) -> str:
    assets = _data_assets(draft)
    imports = [
        _PYTHON_LICENSE_HEADER.rstrip(),
        "from google.adk.agents import Agent",
    ]
    if assets:
        imports.extend(["import os", "from urllib.parse import urljoin, urlparse", "import requests"])
    tool_blocks = [_render_datastudio_tool(asset) for asset in assets]
    tool_names = [_tool_name(asset) for asset in assets]
    instruction = draft.instruction or "You are a helpful assistant."
    kwargs = [
        f"name={_py_str(project_name)}",
        f"description={_py_str(draft.description or draft.name or 'A VeADK agent.')}",
        f"instruction={_py_triple(instruction)}",
    ]
    if tool_names:
        kwargs.append(f"tools=[{', '.join(tool_names)}]")
    helper_blocks = [_DATASTUDIO_URL_HELPERS] if assets else []
    body = "\n\n".join([*imports, *helper_blocks, *tool_blocks])
    return (
        body
        + "\n\nroot_agent = Agent(\n    "
        + ",\n    ".join(kwargs)
        + ",\n)\n\nagent = root_agent\n"
    )


def _render_app_py(project_name: str) -> str:
    return (
        _PYTHON_LICENSE_HEADER
        + f"\nfrom agents.{project_name}.agent import root_agent\n\n"
        + "if __name__ == \"__main__\":\n"
        + "    print(f\"Loaded agent: {root_agent.name}\")\n"
    )
