import type { KnowledgeSourceRef } from "../features/knowledge-workspace/domain/types";

export const KNOWLEDGE_SOURCE_RETURN_OPTION_KEY = "knowledge-source:return-option";

export interface KnowledgeSourceCapability {
  id: string;
  enabled: boolean;
}

export interface KnowledgeSourceOption {
  id: string;
  provider: string;
  displayName: string;
  type: string;
  scope: "personal" | "team";
  status: string;
  ready: boolean;
  category?: string;
  refs: KnowledgeSourceRef[];
  selected?: boolean;
}

export interface KnowledgeSourceDataToolSlot {
  id: "data-tools";
  listOptions(signal?: AbortSignal): Promise<KnowledgeSourceOption[]>;
}

export interface KnowledgeSourceAction {
  id: string;
  label: string;
  description: string;
  run(): void;
}

export interface KnowledgeSourceExtension {
  provider: string;
  displayName: string;
  capabilities: readonly KnowledgeSourceCapability[];
  slots?: {
    dataTools?: KnowledgeSourceDataToolSlot;
    createKnowledgeBase?: KnowledgeSourceAction;
  };
}
