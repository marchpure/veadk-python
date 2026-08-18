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

from veadk.cli.generated_agent_codegen import (
    GeneratedAgentProjectRequest,
    GeneratedAgentTestRunRequest,
)


def test_requests_accept_root_and_nested_a2a_registry() -> None:
    payload = {
        "draft": {
            "name": "root",
            "a2aRegistry": {"enabled": False, "registrySpaceId": "root-space"},
            "subAgents": [
                {
                    "name": "child",
                    "a2aRegistry": {
                        "enabled": True,
                        "registrySpaceId": "child-space",
                    },
                }
            ],
        }
    }

    for request_model in (
        GeneratedAgentProjectRequest,
        GeneratedAgentTestRunRequest,
    ):
        request = request_model.model_validate(payload)

        assert request.draft.a2aRegistry.registrySpaceId == "root-space"
        assert request.draft.subAgents[0].a2aRegistry.registrySpaceId == "child-space"


def test_requests_accept_datastudio_capability_package_fields() -> None:
    payload = {
        "draft": {
            "name": "datastudio-agent",
            "selectedSkills": [
                {
                    "source": "datastudio",
                    "folder": "datastudio-semantic-sales",
                    "name": "Sales Semantic Model",
                    "dataStudioAssetType": "semantic_model",
                    "dataStudioAssetId": "sales-semantic",
                    "dataStudioCapabilityKind": "semantic_skill",
                    "dataStudioCapabilityPackage": {
                        "package_type": "semantic_skill",
                        "mdl": {"schema": "byaan.mdl.v1"},
                    },
                    "dataStudioQueryUrl": "/api/external/assets/semantic_model/sales-semantic/query",
                }
            ],
        }
    }

    for request_model in (
        GeneratedAgentProjectRequest,
        GeneratedAgentTestRunRequest,
    ):
        request = request_model.model_validate(payload)
        skill = request.draft.selectedSkills[0]

        assert skill.dataStudioCapabilityKind == "semantic_skill"
        assert skill.dataStudioCapabilityPackage["mdl"]["schema"] == "byaan.mdl.v1"
