"""Explicit real VEADK + MCP smoke command for W2 P0 evidence.

Run with a credentialed model and a W1-owned MCP endpoint:

  MODEL_AGENT_API_KEY=... MODEL_AGENT_MODEL=... \
  W2_MCP_SERVER_URL=... W2_MCP_BEARER_TOKEN=... \
  python -m frontend.server.skill_authoring.real_smoke

The command exits non-zero when credentials, the MCP endpoint, a real tool
call, a trace, or a valid typed BuildPlan is unavailable.  It never falls
back to LocalPlanningHarness.
"""

from __future__ import annotations

import asyncio
import os
import sys

from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from .models import (
    ContextEnvelope,
    FreshnessPolicy,
    ResourceRef,
    ResolvedResource,
    Scope,
    SkillKind,
)
from .ports import InMemoryResourceResolver, McpToolBundle, VeADKModelGateway


async def main() -> int:
    api_key = os.getenv("MODEL_AGENT_API_KEY")
    model_name = os.getenv("MODEL_AGENT_MODEL")
    server_url = os.getenv("W2_MCP_SERVER_URL")
    bearer = os.getenv("W2_MCP_BEARER_TOKEN")
    if not all((api_key, model_name, server_url, bearer)):
        print(
            "real smoke blocked: MODEL_AGENT_API_KEY, MODEL_AGENT_MODEL, "
            "W2_MCP_SERVER_URL and W2_MCP_BEARER_TOKEN are required",
            file=sys.stderr,
        )
        return 2

    ref = ResourceRef(
        kind="golden_asset",
        object_id="maintenance_backlog",
        revision="golden_rev_1",
        scope=Scope.PERSONAL,
    )
    resource = ResolvedResource(
        ref=ref,
        display_name="maintenance backlog",
        provider_revision=ref.revision,
        schema_digest="provided_by_w1",
        capabilities=("read", "profile"),
        semantic_fields=("site", "created_at", "backlog_count"),
    )
    resolver = InMemoryResourceResolver((resource,))
    resolver.grant("smoke_caller", "smoke_workspace", ref)
    envelope = ContextEnvelope(
        caller_id="smoke_caller",
        workspace_id="smoke_workspace",
        prompt="Compare maintenance backlog by site over time.",
        resource_refs=(ref,),
        permissions=("resource:read",),
        fixed_revisions=(ref.revision,),
        freshness=FreshnessPolicy(max_age_seconds=3600),
    )
    context = await resolver.resolve(envelope, envelope.resource_refs)
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=server_url,
            headers={"Authorization": f"Bearer {bearer}"},
        ),
        tool_filter=None,
    )
    gateway = VeADKModelGateway(
        mcp_tools=McpToolBundle(
            tools=(toolset,),
            schemas={"source": "W1 MCP schema discovery at runtime"},
        ),
        model_name=model_name,
        model_api_key=api_key,
        model_api_base=os.getenv("MODEL_AGENT_API_BASE"),
    )
    plan = await gateway.propose_plan(context, requested_kind=SkillKind.ANALYSIS)
    evidence = gateway.execution_evidence
    if evidence is None or evidence.status != "succeeded":
        print("real smoke failed: no successful Agent evidence", file=sys.stderr)
        return 1
    if not evidence.tool_calls:
        print("real smoke failed: no MCP tool call in Runner evidence", file=sys.stderr)
        return 1
    print(
        {
            "session_id": evidence.session_id,
            "trace_id": evidence.trace_id,
            "status": evidence.status,
            "events": [event.model_dump(mode="json") for event in evidence.events],
            "tool_calls": [
                call.model_dump(mode="json") for call in evidence.tool_calls
            ],
            "skill_draft_kind": plan.intent.value,
            "build_plan_digest": plan.plan_digest,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
