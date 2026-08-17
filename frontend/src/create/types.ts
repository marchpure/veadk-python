import type { McpTool, SelectedSkill } from "./skills/types.ts";

export interface AgentDraft {
  name: string;
  description: string;
  instruction: string;
  agentType: "llm" | "sequential" | "parallel" | "loop" | "a2a";
  tools: string[];
  skills: string[];
  customTools: Array<{ name: string; description: string }>;
  mcpTools: McpTool[];
  selectedSkills: SelectedSkill[];
  dataAssets: SelectedSkill[];
  subAgents: AgentDraft[];
  deployment: {
    feishuEnabled: boolean;
    modelApiKeyId?: string;
    modelApiKeyName?: string;
    envValues?: Record<string, string>;
  };
}

export function emptyDraft(): AgentDraft {
  return {
    name: "",
    description: "",
    instruction: "",
    agentType: "llm",
    tools: [],
    skills: [],
    customTools: [],
    mcpTools: [],
    selectedSkills: [],
    dataAssets: [],
    subAgents: [],
    deployment: { feishuEnabled: false },
  };
}
