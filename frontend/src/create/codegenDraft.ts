import type { AgentDraft } from "./types.ts";

export function codegenDraft(draft: AgentDraft): AgentDraft {
  return {
    ...draft,
    mcpTools: [...(draft.mcpTools ?? [])],
    dataAssets: (draft.dataAssets ?? []).map((asset) => ({
      ...asset,
      dataStudioMcpUrl: "",
    })),
    deployment: {
      feishuEnabled: !!draft.deployment?.feishuEnabled,
      modelApiKeyId: draft.deployment?.modelApiKeyId ?? "",
      modelApiKeyName: draft.deployment?.modelApiKeyName ?? "",
    },
  };
}
