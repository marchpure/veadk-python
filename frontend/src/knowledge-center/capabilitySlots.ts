import React from "react";

export type CapabilitySlotKind =
  | "retrieval_binding"
  | "semantic_skill"
  | "dashboard_skill"
  | "askdata";

export type CapabilitySlotStatus =
  | "registered"
  | "needs_configuration"
  | "auth_required"
  | "importing"
  | "indexed"
  | "ready"
  | "failed"
  | "credential_expired"
  | "draft"
  | "published"
  | "disabled";

export type CapabilityPublishState = "draft" | "published" | "archived";

export type CapabilityNextAction = {
  label: string;
  description: string;
  action: "configure" | "build" | "publish" | "retry" | "open" | "select_source";
  disabled?: boolean;
};

export type KnowledgeCapabilityCardProps = {
  id: string;
  name: string;
  kind: CapabilitySlotKind;
  status: CapabilitySlotStatus;
  publish_state?: CapabilityPublishState;
  source_ids: string[];
  created_at?: string;
  description?: string;
  next_cta?: CapabilityNextAction;
};

export type CapabilityBuildJobStatus =
  | "succeeded"
  | "failed"
  | "blocked"
  | "cancelled"
  | "running"
  | "queued";

export type CapabilityBuildJobView = {
  id: string;
  status: CapabilityBuildJobStatus;
  job_type: string;
  source_id?: string;
  asset_id?: string;
  error_message?: string;
  logs_ref?: string;
  created_at?: string;
  updated_at?: string;
};

export type CapabilityPanelSlotContext = {
  kind: Extract<CapabilitySlotKind, "semantic_skill" | "dashboard_skill" | "askdata">;
  capabilities: KnowledgeCapabilityCardProps[];
  build_jobs: CapabilityBuildJobView[];
  source_id?: string;
  on_request_build?: (kind: CapabilityPanelSlotContext["kind"], sourceId?: string) => void;
};

export type CapabilityPanelSlotProps = {
  kind: CapabilityPanelSlotContext["kind"];
  capabilities?: KnowledgeCapabilityCardProps[];
  build_jobs?: CapabilityBuildJobView[];
  source_id?: string;
  on_request_build?: CapabilityPanelSlotContext["on_request_build"];
  render: (context: CapabilityPanelSlotContext) => React.ReactNode;
};

export function CapabilityPanelSlot({
  kind,
  capabilities = [],
  build_jobs = [],
  source_id,
  on_request_build,
  render,
}: CapabilityPanelSlotProps): React.ReactElement {
  return React.createElement(
    React.Fragment,
    null,
    render({ kind, capabilities, build_jobs, source_id, on_request_build }),
  );
}
