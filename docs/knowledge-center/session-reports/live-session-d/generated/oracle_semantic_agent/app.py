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

from inspect import signature

from agents.oracle_semantic_agent.agent import AGENT_DISPLAY_NAMES, AGENT_DRAFT, root_agent
from agents.oracle_semantic_agent.dynamic_a2a import enable_dynamic_a2a_tools
from veadk.integrations.agentkit import create_agentkit_app, run_agentkit_app

_app_options = {
    "enable_feishu": False,
}
if "agent_draft" in signature(create_agentkit_app).parameters:
    _app_options["agent_draft"] = AGENT_DRAFT

app = create_agentkit_app(
    root_agent,
    AGENT_DISPLAY_NAMES,
    **_app_options,
)

_agent_info_index = next(
    index
    for index, route in enumerate(app.router.routes)
    if getattr(route, "path", "") == "/web/agent-info/{app_name}"
)
_agent_info_route = app.router.routes.pop(_agent_info_index)
_agent_info_handler = _agent_info_route.endpoint

@app.get("/web/agent-info/{app_name}")
def agent_info_with_draft(app_name: str):
    return {**_agent_info_handler(app_name), "draft": AGENT_DRAFT}

app.router.routes.insert(_agent_info_index, app.router.routes.pop())

enable_dynamic_a2a_tools(app, root_agent)

if __name__ == "__main__":
    run_agentkit_app(app)
