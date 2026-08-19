/*
 * Source-level port of BYAAN Notebook/Dashboard workspace.
 *
 * Migrated structure:
 * - client/src/components/QueryEditor.tsx
 * - client/src/components/NotebookQueryPanel.tsx
 * - client/src/components/QueryResults.tsx
 * - client/src/components/QueryRunnerDocked.tsx
 * - client/src/components/DashboardPreviewPanel.tsx
 * - client/src/features/dashboard/pages/DashboardWorkspacePage.tsx workspace concepts.
 *
 * Removed runtime seams: BYAAN ApiService, store, router, shadcn package imports,
 * Tauri file APIs, and independent app shell. AgentKit adapters/controllers provide
 * semantic skill selection, AskTable execution, dashboard draft persistence, and refresh.
 */
import { Database, LayoutDashboard, RefreshCw } from "lucide-react";
import type { FormEvent } from "react";

import type {
  AskDataQueryResult,
  DashboardShare,
  DashboardSkillBuildResult,
  KnowledgeAssetMetadata,
} from "../../../../adk/knowledgeAssets";
import {
  type ByaanSourcePortStatus,
  type ByaanSourcePortViewModel,
} from "../../adapters/byaanAskTableAdapter";
import { formatJson } from "../../../../knowledge-center/knowledgeWorkbenchUtils";
import { DashboardPreviewPanel } from "./original/DashboardPreviewPanel";
import QueryRunnerDocked from "./original/QueryRunnerDocked";
import type { ByaanOriginalWorkspaceModel, DashboardWorkspaceTab, QueryResult } from "./original/types";

export type ByaanDashboardTab = DashboardWorkspaceTab;

export function ByaanNotebookDashboardSourcePort({
  viewModel,
  semanticSkills,
  selectedSemanticAssetId,
  onSemanticAssetChange,
  dashboardAssetId,
  onDashboardAssetChange,
  dashboardSkills,
  metric,
  dimension,
  question,
  onMetricChange,
  onDimensionChange,
  onQuestionChange,
  onQuery,
  busyQuery,
  busyBuild,
  queryResult,
  buildResult,
  dashboardName,
  dashboardIntent,
  onDashboardNameChange,
  onDashboardIntentChange,
  onBuildDashboard,
  busyShare = false,
  onShareDashboard,
  shareResult,
  onClearShare,
  onRevokeShare,
  activeTab,
  onActiveTabChange,
  onRefresh,
  onFullscreen,
}: {
  viewModel: ByaanSourcePortViewModel;
  semanticSkills: KnowledgeAssetMetadata[];
  selectedSemanticAssetId: string;
  onSemanticAssetChange: (value: string) => void;
  dashboardAssetId: string;
  onDashboardAssetChange: (value: string) => void;
  dashboardSkills: KnowledgeAssetMetadata[];
  metric: string;
  dimension: string;
  question: string;
  onMetricChange: (value: string) => void;
  onDimensionChange: (value: string) => void;
  onQuestionChange: (value: string) => void;
  onQuery: (event: FormEvent<HTMLFormElement>) => void;
  busyQuery: boolean;
  busyBuild: boolean;
  queryResult: AskDataQueryResult | null;
  buildResult: DashboardSkillBuildResult | null;
  dashboardName: string;
  dashboardIntent: string;
  onDashboardNameChange: (value: string) => void;
  onDashboardIntentChange: (value: string) => void;
  onBuildDashboard: (event: FormEvent<HTMLFormElement>) => void;
  busyShare?: boolean;
  onShareDashboard: () => void;
  shareResult: DashboardShare | null;
  onClearShare: () => void;
  onRevokeShare: (shareId: string) => void;
  activeTab: ByaanDashboardTab;
  onActiveTabChange: (value: ByaanDashboardTab) => void;
  onRefresh: () => void;
  onFullscreen: () => void;
}) {
  const workspace: ByaanOriginalWorkspaceModel = {
    notebook: viewModel.notebook,
    dashboard: viewModel.dashboard,
    dashboardSpec: viewModel.dashboardSpec,
    previewRows: viewModel.previewRows,
    queryResult,
    buildResult,
    selectedSkill: viewModel.selectedSkill,
    selectedDashboard: viewModel.selectedDashboard,
  };
  const originalQueryResult = toOriginalQueryResult(queryResult, viewModel);
  const submitQuery = () => onQuery(syntheticSubmitEvent());
  const submitDashboard = () => onBuildDashboard(syntheticSubmitEvent());

  return (
    <section className="kc-byaan-source-port byaan-workspace-page" data-source-port="byaan-notebook-dashboard">
      <header className="byaan-workspace-header">
        <div>
          <LayoutDashboard className="kc-native-icon" />
          <span>
            <strong>Notebook / Dashboard Workspace</strong>
            <small>{viewModel.selectedSkill?.name || "AgentKit governed Semantic Skill"}</small>
          </span>
        </div>
        <div className="kc-byaan-head-actions">
          <select value={dashboardAssetId} onChange={(event) => onDashboardAssetChange(event.target.value)}>
            <option value="">Dashboard asset</option>
            {dashboardSkills.map((asset) => (
              <option key={asset.asset_id} value={asset.asset_id}>{asset.name} · {asset.version || "v1"}</option>
            ))}
          </select>
          <input value={dashboardName} onChange={(event) => onDashboardNameChange(event.target.value)} aria-label="Dashboard name" />
          <input value={dashboardIntent} onChange={(event) => onDashboardIntentChange(event.target.value)} aria-label="Dashboard intent" />
          <button type="button" onClick={onRefresh}><RefreshCw className="kc-native-icon" />Refresh</button>
        </div>
      </header>

      <ByaanStatusStrip status={viewModel.status} />
      <div className="kc-byaan-workspace-grid byaan-notebook-dashboard-grid">
        <QueryRunnerDocked
          semanticSkills={semanticSkills}
          selectedSemanticAssetId={selectedSemanticAssetId}
          onSemanticAssetChange={onSemanticAssetChange}
          metric={metric}
          dimension={dimension}
          metrics={viewModel.metrics}
          dimensions={viewModel.dimensions}
          onMetricChange={onMetricChange}
          onDimensionChange={onDimensionChange}
          initialQuery={question}
          onQueryChange={onQuestionChange}
          queryResult={originalQueryResult}
          isExecuting={busyQuery}
          onExecute={submitQuery}
          onBuildDashboard={submitDashboard}
          isBuildingDashboard={busyBuild}
        />
        <DashboardPreviewPanel
          workspace={workspace}
          activeTab={activeTab}
          onActiveTabChange={onActiveTabChange}
          onRefresh={onRefresh}
          onOpenFullscreen={onFullscreen}
          busyShare={busyShare}
          onShareDashboard={onShareDashboard}
          shareResult={shareResult}
          onClearShare={onClearShare}
          onRevokeShare={onRevokeShare}
        />
      </div>
    </section>
  );
}

export function ByaanBlockedNotebookShell({
  status,
  onRefresh,
}: {
  status: ByaanSourcePortStatus;
  onRefresh: () => void;
}) {
  return (
    <section className="kc-byaan-source-port is-blocked byaan-workspace-page" data-testid="ask-dashboard-workbench">
      <header className="byaan-workspace-header">
        <div>
          <LayoutDashboard className="kc-native-icon" />
          <span>
            <strong>Notebook / Dashboard Workspace</strong>
            <small>Blocked: no published Semantic Skill</small>
          </span>
        </div>
        <div className="kc-byaan-head-actions">
          <button type="button" onClick={onRefresh}><RefreshCw className="kc-native-icon" />Refresh</button>
        </div>
      </header>
      <ByaanStatusStrip status={status} />
      <div className="kc-byaan-blocked-shell" data-testid="askdashboard-not-configured-blocked" role="status">
        <section className="kc-byaan-original-query-editor bg-[#1e1e1e] border-b border-[#404040] p-6">
          <div className="flex items-center gap-2 text-white">
            <Database className="kc-native-icon" />
            Query Editor
          </div>
          <div className="kc-byaan-editor-shell is-readonly">
            <textarea value="Select a published Semantic Skill before asking governed data questions." disabled readOnly />
            <em>blocked · no model</em>
          </div>
          <div className="kc-byaan-editor-actions">
            <button type="button" disabled>Execute</button>
            <button type="button" disabled>Stop</button>
            <button type="button" disabled>Dashboard</button>
          </div>
        </section>
        <section className="kc-byaan-ready-state">
          <Database className="kc-native-state-icon" />
          <strong>需要已发布 Semantic Skill</strong>
          <span>AskTable 和 Dashboard 只通过受治理语义能力查询；当前状态为 blocked，不会伪造 query 或 dashboard 成功。</span>
        </section>
      </div>
    </section>
  );
}

function toOriginalQueryResult(
  result: AskDataQueryResult | null,
  viewModel: ByaanSourcePortViewModel,
): QueryResult | null {
  if (!result) return null;
  const notebook = viewModel.notebook;
  return {
    query: notebook.sql || notebook.editorQuery,
    results: notebook.rows,
    executionTime: `${notebook.executionTime} ms`,
    rowCount: notebook.rowCount,
    returnedCount: notebook.returnedCount,
    totalCount: notebook.returnedCount,
    limited: false,
    error: result.status === "completed" ? undefined : result.status,
    metricDefinition: notebook.metricDefinition,
    policyDecision: notebook.policyDecision,
    freshness: notebook.freshness,
    evidence: notebook.evidence,
    lineage: notebook.lineage,
    rawResult: result.status === "completed" ? undefined : formatJson(result),
  };
}

function syntheticSubmitEvent(): FormEvent<HTMLFormElement> {
  return {
    preventDefault() {
      return undefined;
    },
  } as FormEvent<HTMLFormElement>;
}

function ByaanStatusStrip({ status }: { status: ByaanSourcePortStatus }) {
  return (
    <div className="kc-agent-status-strip" data-testid="askdashboard-agent-status-strip">
      <StatusChip label="Job" value={status.jobStatus} />
      <StatusChip label="Agent" value={status.agentStatus} />
      <StatusChip label="Runner" value={status.runnerBackend} />
      <StatusChip label="Mode" value={status.generationMode} />
      <StatusChip label="Blocked" value={status.blockedReason} />
    </div>
  );
}

function StatusChip({ label, value }: { label: string; value: string }) {
  return <span><strong>{label}</strong><em>{value}</em></span>;
}
