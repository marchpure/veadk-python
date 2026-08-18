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

from veadk import Agent
import os
from urllib.parse import urljoin, urlparse
import requests
from pathlib import Path as _Path
from google.adk.code_executors import UnsafeLocalCodeExecutor
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

def _datastudio_query_url(path_or_url: str) -> str:
    """Resolve and validate a Data Studio query URL before reading BYAAN_MCP_API_KEY."""
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

def query_datastudio_semantic_model_9172f615_8b39_4280_81a6_9ca14cfc0be5(metric: str, dimension: str | None = None, grain: str | None = None, filters: dict | None = None, time_range: dict | None = None, limit: int = 100) -> dict:
    """Query the Byaan semantic model Oracle Sales Semantic Model session-h-oracle-20260818145458 through the REST external API.

    Use exact metric ids/names from this asset: ticket_count.
    Use exact dimension ids/names from this asset: store, sell_date, sell_state, sell_type.
    Time field: hd.SELLDATE.
    """
    query_url = _datastudio_query_url("/api/external/assets/semantic_model/9172f615-8b39-4280-81a6-9ca14cfc0be5/query")
    token = os.environ["BYAAN_MCP_API_KEY"]
    payload = {"metric": metric, "dimension": dimension, "grain": grain, "filters": filters or {}, "time_range": time_range or {}, "limit": limit}
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    response = requests.post(
        query_url,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("data", body) if isinstance(body, dict) else {"data": body}

skills_agent = SkillToolset(
    skills=[
        load_skill_from_dir(_Path(__file__).parent.parent.parent / "skills" / "datastudio-semantic-model-9172f615-8b39-4280-81a6-9ca14cfc0be5"),
    ],
    code_executor=UnsafeLocalCodeExecutor(),
)

INSTRUCTION_AGENT = """You answer Oracle sales questions using the selected Byaan Data Studio semantic model. Always call the Data Studio REST tool before answering. Final answers must include the real numeric values, compiled SQL, metric definition, snapshot freshness, and permission policy evidence. Deny customer name, phone, contact, and document detail requests as policy denied. For cross-country sales amount, answer blocked_pending_currency_confirmation unless currency is confirmed."""

agent = Agent(
    name="oracle_semantic_agent",
    description="Answers governed Oracle sales questions from Byaan Data Studio.",
    instruction=INSTRUCTION_AGENT,
    tools=[query_datastudio_semantic_model_9172f615_8b39_4280_81a6_9ca14cfc0be5, skills_agent],
    model_name="doubao-seed-1-6-250615",
)

AGENT_DISPLAY_NAMES = {'oracle_semantic_agent': 'Oracle Semantic Agent'}
AGENT_DRAFT = {'name': 'Oracle Semantic Agent', 'description': 'Answers governed Oracle sales questions from Byaan Data Studio.', 'instruction': 'You answer Oracle sales questions using the selected Byaan Data Studio semantic model. Always call the Data Studio REST tool before answering. Final answers must include the real numeric values, compiled SQL, metric definition, snapshot freshness, and permission policy evidence. Deny customer name, phone, contact, and document detail requests as policy denied. For cross-country sales amount, answer blocked_pending_currency_confirmation unless currency is confirmed.', 'agentType': 'llm', 'maxIterations': 3, 'a2aUrl': '', 'model': '', 'modelSource': 'ark', 'modelName': 'doubao-seed-1-6-250615', 'modelProvider': '', 'modelApiBase': '', 'tools': [], 'skills': [], 'memory': {'shortTerm': False, 'longTerm': False}, 'knowledgebase': False, 'tracing': False, 'subAgents': [], 'builtinTools': [], 'customTools': [], 'mcpTools': [], 'a2aRegistry': {'enabled': False, 'registrySpaceId': '', 'registryTopK': '', 'registryRegion': '', 'registryEndpoint': ''}, 'shortTermBackend': 'local', 'longTermBackend': 'local', 'autoSaveSession': False, 'knowledgebaseBackend': 'viking', 'knowledgebaseIndex': '', 'tracingExporters': [], 'selectedSkills': [{'source': 'datastudio', 'folder': 'datastudio-semantic-model-9172f615-8b39-4280-81a6-9ca14cfc0be5', 'name': 'Oracle Sales Semantic Model session-h-oracle-20260818145458', 'description': 'Governed Oracle semantic model over sanitized DuckDB snapshot.', 'slug': '', 'namespace': 'public', 'localFiles': [], 'skillSpaceId': '', 'skillSpaceName': '', 'skillSpaceRegion': '', 'skillId': '', 'version': '', 'dataStudioAssetType': 'semantic_model', 'dataStudioAssetId': '9172f615-8b39-4280-81a6-9ca14cfc0be5', 'dataStudioVersion': 'v1', 'dataStudioGateScore': 100.0, 'dataStudioMetrics': ['ticket_count'], 'dataStudioPermissionHint': 'Use only governed aggregate data returned by Byaan.', 'dataStudioQueryUrl': '/api/external/assets/semantic_model/9172f615-8b39-4280-81a6-9ca14cfc0be5/query', 'dataStudioTimeField': 'hd.SELLDATE', 'dataStudioDimensions': ['store', 'sell_date', 'sell_state', 'sell_type'], 'dataStudioEvidence': ['{"kind":"metric_definition","title":"Ticket Count","metric":"ticket_count","definition":"Count of distinct sales bill IDs for posted, non-cancelled tickets in the 2026-07-17 through 2026-08-15 snapshot window.","formula":"count(distinct hd.BILLID)","filter":"hd.CANCELSIGN = \'N\' AND hd.STATUS = \'002\' AND hd.SELLSTATEID IN (\'01\',\'02\') AND hd.SELLDATE >= DATE \'2026-07-17\' AND hd.SELLDATE <= DATE \'2026-08-15\'","lineage":[{"id":"oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw","snapshot_id":"oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw","hash":"c67a52d9f8d2eaf92d6a7ca1b09aee321cf4da176499c618ef0e53214eb166eb","sha256":"c67a52d9f8d2eaf92d6a7ca1b09aee321cf4da176499c618ef0e53214eb166eb","data_through":"2026-08-15","manifest_schema":"oracle.sales.snapshot.manifest.v2","provenance":"sanitized-from-snapshot"},{"policy":"oracle.sales.privacy.v1","filters":{"CANCELSIGN":"N","STATUS":"002","SELLSTATEID":["01","02"],"SELLDATE":["2026-07-17","2026-08-15"]},"golden_results":{"cross_country_sales_amount":"blocked_pending_currency_confirmation","customer_name_phone_policy":"denied","relative_time_anchor":"max(SELLDATE)=2026-08-15","ticket_count_last_30_snapshot_days":86,"top_3_stores_by_ticket_count":[{"store":"VNPTTE","ticket_count":56},{"store":"SG - ANTA VIVO City","ticket_count":9},{"store":"HARAVAN_ANTA_VN","ticket_count":5}]}}]}', '{"kind":"permission_policy","title":"Semantic model external query policy","policy":{"allowedMetrics":["ticket_count"],"allowedDimensions":["store","sell_date","sell_state","sell_type"]}}']}], 'workflow': None, 'deployment': {'feishuEnabled': False}}

# ADK 加载器要求：顶层 agent 必须命名为 root_agent
root_agent = agent
