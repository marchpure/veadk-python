import { prepareMcpAuth } from "./mcpAuth";
import { activeModelConfiguration } from "./modelSource";
import type { AgentDraft, McpTool } from "./types";

function dataAssetMcpTool(
  asset: NonNullable<AgentDraft["dataAssets"]>[number],
): McpTool | null {
  if (asset.source !== "datastudio" || !asset.dataStudioAssetType || !asset.dataStudioAssetId) {
    return null;
  }
  const slug = asset.folder || `datastudio-${asset.dataStudioAssetType}-${asset.dataStudioAssetId}`;
  const url = asset.dataStudioMcpUrl?.trim();
  if (!url) return null;
  return {
    name: `byaan-${slug}`,
    transport: "http",
    url,
    authToken: "",
    authTokenEnv: "BYAAN_MCP_API_KEY",
    command: "",
    args: [],
  };
}

function withDataAssetTools(node: AgentDraft): AgentDraft {
  const assetTools = (node.dataAssets ?? [])
    .map(dataAssetMcpTool)
    .filter((tool): tool is McpTool => tool !== null);
  const subAgents = node.subAgents.map(withDataAssetTools);
  const workflow = node.workflow
    ? {
        ...node.workflow,
        nodes: node.workflow.nodes.map((workflowNode) => ({
          ...workflowNode,
          agent: withDataAssetTools(workflowNode.agent),
        })),
      }
    : undefined;
  return {
    ...node,
    mcpTools: [...(node.mcpTools ?? []), ...assetTools],
    subAgents,
    ...(workflow ? { workflow } : {}),
  };
}

/** Return the backend codegen API shape, stripping UI/deployment-only fields. */
export function codegenDraft(draft: AgentDraft): AgentDraft {
  const prepared = prepareMcpAuth(withDataAssetTools(draft)).draft;
  const activeModelDraft = activeModelConfiguration(
    prepared,
    prepared.cloudProvider ?? "volcengine",
  );
  return {
    ...activeModelDraft,
    deployment: {
      feishuEnabled: !!draft.deployment?.feishuEnabled,
      modelApiKeyId: draft.deployment?.modelApiKeyId ?? "",
      modelApiKeyName: draft.deployment?.modelApiKeyName ?? "",
    },
  };
}
