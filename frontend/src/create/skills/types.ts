export type DataStudioAssetType = "dashboard" | "semantic_model";
export type SkillSource = "skillhub" | "local" | "skillspace" | "datastudio";

export interface McpTool {
  name: string;
  transport: "http" | "stdio";
  url?: string;
  authToken?: string;
  authTokenEnv?: string;
  command?: string;
  args?: string[];
}

export interface SelectedSkill {
  source: SkillSource;
  folder: string;
  name: string;
  description?: string;
  localFiles?: Array<{ path: string; content: string }>;
  dataStudioAssetType?: DataStudioAssetType;
  dataStudioAssetId?: string;
  dataStudioVersion?: string;
  dataStudioGateScore?: number;
  dataStudioMetrics?: string[];
  dataStudioExampleQuestions?: string[];
  dataStudioPermissionHint?: string;
  dataStudioQueryUrl?: string;
  dataStudioMcpUrl?: string;
  dataStudioTimeField?: string;
  dataStudioDimensions?: string[];
  dataStudioEvidence?: string[];
}

export interface SkillHit extends SelectedSkill {
  id: string;
}
