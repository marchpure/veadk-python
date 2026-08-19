import type {
  AskDataQueryResult,
  DashboardSkillBuildResult,
  KnowledgeAssetBuildJob,
  KnowledgeAssetMetadata,
} from "../../../adk/knowledgeAssets";
import {
  askDataToNotebookViewModel,
  capabilityValues,
  dashboardSpec,
  dashboardSpecToByaanViewModel,
  objectValue,
  rowsFromSpec,
  type ByaanDashboardViewModel,
  type ByaanNotebookViewModel,
} from "../../../knowledge-center/knowledgeWorkbenchUtils";

export type ByaanSourcePortStatus = {
  jobStatus: string;
  agentStatus: string;
  runnerBackend: string;
  generationMode: string;
  blockedReason: string;
};

export type ByaanSourcePortViewModel = {
  selectedSkill: KnowledgeAssetMetadata | null;
  selectedDashboard: KnowledgeAssetMetadata | null;
  notebook: ByaanNotebookViewModel;
  dashboard: ByaanDashboardViewModel;
  dashboardSpec: Record<string, unknown>;
  metrics: string[];
  dimensions: string[];
  previewRows: Array<Record<string, unknown>>;
  latestDashboardJob: KnowledgeAssetBuildJob | null;
  status: ByaanSourcePortStatus;
};

export function createByaanAskTableSourcePortViewModel(input: {
  semanticSkills: KnowledgeAssetMetadata[];
  dashboardSkills: KnowledgeAssetMetadata[];
  buildJobs: KnowledgeAssetBuildJob[];
  selectedSemanticAssetId: string;
  selectedDashboardAssetId: string;
  question: string;
  busyQuery: boolean;
  queryResult: AskDataQueryResult | null;
  buildResult: DashboardSkillBuildResult | null;
}): ByaanSourcePortViewModel {
  const selectedSkill =
    input.semanticSkills.find((asset) => asset.asset_id === input.selectedSemanticAssetId) ??
    input.semanticSkills[0] ??
    null;
  const selectedDashboard =
    input.buildResult?.dashboard ??
    input.dashboardSkills.find((asset) => asset.asset_id === input.selectedDashboardAssetId) ??
    input.dashboardSkills[0] ??
    null;
  const spec = input.buildResult?.dashboard
    ? dashboardSpec(input.buildResult.dashboard)
    : dashboardSpec(selectedDashboard);
  const previewRows = input.queryResult?.data.rows?.length ? input.queryResult.data.rows : rowsFromSpec(spec);
  const latestDashboardJob =
    (input.buildResult?.job_id ? input.buildJobs.find((job) => job.id === input.buildResult?.job_id) : null) ??
    input.buildJobs.find((job) => job.job_type.includes("dashboard") && job.asset_id === selectedDashboard?.asset_id) ??
    input.buildJobs.find((job) => job.job_type.includes("dashboard")) ??
    null;
  return {
    selectedSkill,
    selectedDashboard,
    notebook: askDataToNotebookViewModel(input.queryResult, input.question, input.busyQuery),
    dashboard: dashboardSpecToByaanViewModel(spec, selectedDashboard),
    dashboardSpec: spec,
    metrics: capabilityValues(selectedSkill, "metrics"),
    dimensions: capabilityValues(selectedSkill, "dimensions"),
    previewRows,
    latestDashboardJob,
    status: byaanStatusModel({
      selectedSkill,
      selectedDashboard,
      latestDashboardJob,
      queryResult: input.queryResult,
      buildResult: input.buildResult,
    }),
  };
}

export function byaanStatusModel({
  selectedSkill,
  selectedDashboard,
  latestDashboardJob,
  queryResult,
  buildResult,
}: {
  selectedSkill: KnowledgeAssetMetadata | null;
  selectedDashboard: KnowledgeAssetMetadata | null;
  latestDashboardJob: KnowledgeAssetBuildJob | null;
  queryResult: AskDataQueryResult | null;
  buildResult: DashboardSkillBuildResult | null;
}): ByaanSourcePortStatus {
  const dashboardRuntime = objectValue(selectedDashboard?.capability_package?.runtime);
  const queryExecution = objectValue((queryResult?.data as unknown as Record<string, unknown> | undefined)?.execution);
  const buildOutput = objectValue(latestDashboardJob?.output);
  const blockedReasons = latestDashboardJob?.output?.blocked_reasons;
  const gateBlockers = selectedDashboard?.gate?.blockers;
  return {
    jobStatus: buildResult?.status || latestDashboardJob?.status || queryResult?.status || "idle",
    agentStatus: String(
      buildOutput.agent_status ||
        selectedDashboard?.provenance?.agent_status ||
        selectedSkill?.provenance?.agent_status ||
        "agentkit_native_asktable_dashboard",
    ),
    runnerBackend: String(
      buildOutput.runner_backend ||
        selectedDashboard?.provenance?.runner_backend ||
        dashboardRuntime.transport ||
        (queryExecution.governed_rest ? "agentkit_governed_rest" : "") ||
        "agentkit_governed_rest",
    ),
    generationMode: String(
      buildOutput.generation_mode ||
        buildOutput.askdata_status ||
        queryExecution.mode ||
        selectedDashboard?.capabilities?.generation_mode ||
        selectedSkill?.capabilities?.generation_mode ||
        "governed_semantic_query",
    ),
    blockedReason: String(
      latestDashboardJob?.error?.message ||
        (Array.isArray(blockedReasons) && blockedReasons.length ? blockedReasons.map(String).join(", ") : "") ||
        (Array.isArray(gateBlockers) && gateBlockers.length ? gateBlockers.join(", ") : "") ||
        (queryResult?.status === "blocked" ? queryResult.data.policyDecision?.reason : "") ||
        "none",
    ),
  };
}

export function byaanBlockedStatus(): ByaanSourcePortStatus {
  return {
    jobStatus: "blocked",
    agentStatus: "blocked_no_semantic_skill",
    runnerBackend: "agentkit_governed_rest",
    generationMode: "not_configured",
    blockedReason: "no published Semantic Skill",
  };
}
