"use client";

import { Check, Code, Copy, Database, Eye, FileCode2, FileDown, Filter, Hand, Maximize2, MoreHorizontal, RefreshCw, Share2 } from "lucide-react";
import { useState } from "react";

import { formatJson, objectValue } from "../../../../../knowledge-center/knowledgeWorkbenchUtils";
import type { ByaanOriginalWorkspaceModel, DashboardWorkspaceTab } from "./types";

export function DashboardPreviewPanel({
  workspace,
  activeTab,
  onActiveTabChange,
  onRefresh,
  onOpenFullscreen,
}: {
  workspace: ByaanOriginalWorkspaceModel;
  activeTab: DashboardWorkspaceTab;
  onActiveTabChange: (tab: DashboardWorkspaceTab) => void;
  onRefresh: () => void;
  onOpenFullscreen: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const dashboard = workspace.dashboard;
  const codeForDisplay = formatJson(workspace.dashboardSpec);
  const hasPreview = dashboard.tiles.length > 0 || workspace.previewRows.length > 0;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codeForDisplay);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="kc-byaan-dashboard-preview h-full flex flex-col bg-[#1a1a1a] border-l border-[#2a2a2a] relative">
      <div className="kc-byaan-preview-toolbar flex items-center justify-between px-3 h-[42px] border-b border-[#2a2a2a] flex-shrink-0 relative z-10">
        <div className="kc-byaan-preview-tabs flex items-center gap-1">
          <div className="kc-byaan-preview-tab-list flex gap-[2px]">
            <ToolbarTab active={activeTab === "dashboard"} onClick={() => onActiveTabChange("dashboard")} icon={<Eye className="kc-native-icon" />} label="Preview" />
            <ToolbarTab active={activeTab === "code"} onClick={() => onActiveTabChange("code")} icon={<Code className="kc-native-icon" />} label="Code" />
            <ToolbarTab active={activeTab === "data"} onClick={() => onActiveTabChange("data")} icon={<Database className="kc-native-icon" />} label="Queries" />
            <ToolbarTab active={activeTab === "lineage"} onClick={() => onActiveTabChange("lineage")} icon={<Filter className="kc-native-icon" />} label="Lineage" />
          </div>
        </div>
        <div className="kc-byaan-preview-actions flex items-center gap-1.5">
          <span className="kc-byaan-version-chip">
            <span />
            v{workspace.selectedDashboard?.version || "1"}
          </span>
          <div className="w-px h-[18px] bg-[#262626] mx-0.5" />
          <button type="button" disabled={!hasPreview} title="Grab element">
            <Hand className="kc-native-icon" />
          </button>
          <button type="button" onClick={onRefresh} title="Refresh">
            <RefreshCw className="kc-native-icon" />
          </button>
          <button type="button" disabled title="Export PDF">
            <FileDown className="kc-native-icon" />
          </button>
          <button type="button" disabled title="Export HTML">
            <FileCode2 className="kc-native-icon" />
          </button>
          <button type="button" disabled title="Share">
            <Share2 className="kc-native-icon" />
          </button>
          <button type="button" onClick={onOpenFullscreen} title="Open fullscreen">
            <Maximize2 className="kc-native-icon" />
          </button>
          <button type="button" title="More">
            <MoreHorizontal className="kc-native-icon" />
          </button>
        </div>
      </div>

      <div className="kc-byaan-preview-body flex-1 min-h-0">
        {activeTab === "dashboard" ? (
          <DashboardCanvas workspace={workspace} hasPreview={hasPreview} />
        ) : activeTab === "code" ? (
          <div className="kc-byaan-code-workspace">
            <header>
              <strong>dashboard_spec.json</strong>
              <button type="button" onClick={handleCopy}>
                {copied ? <Check className="kc-native-icon" /> : <Copy className="kc-native-icon" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </header>
            <pre><code>{codeForDisplay}</code></pre>
          </div>
        ) : activeTab === "data" ? (
          <QueriesPanel workspace={workspace} />
        ) : (
          <LineagePanel workspace={workspace} />
        )}
      </div>
    </div>
  );
}

function ToolbarTab({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button type="button" onClick={onClick} className={active ? "is-active" : ""}>
      {icon}
      {label}
    </button>
  );
}

function DashboardCanvas({ workspace, hasPreview }: { workspace: ByaanOriginalWorkspaceModel; hasPreview: boolean }) {
  const { dashboard, previewRows } = workspace;
  return (
    <div className="kc-byaan-dashboard-canvas" data-testid="dashboard-preview-pane">
      {hasPreview ? (
        <>
          <header>
            <div>
              <h3>{dashboard.title || workspace.selectedDashboard?.name || "Dashboard preview"}</h3>
              <p>{dashboard.description}</p>
            </div>
            <span className="kc-native-badge is-success">governed</span>
          </header>
          <div className="kc-byaan-filter-bar">
            <Filter className="kc-native-icon" />
            {dashboard.filters.length
              ? dashboard.filters.map((filter, index) => <span key={index}>{String(objectValue(filter).label || objectValue(filter).id || "filter")}</span>)
              : <span>All filters</span>}
          </div>
          <div className="kc-byaan-dashboard-tiles">
            {dashboard.tiles.length
              ? dashboard.tiles.map((tile, index) => <DashboardTile key={String(objectValue(tile).id || index)} tile={objectValue(tile)} rows={previewRows} />)
              : <DashboardTile tile={{ title: "Waiting for query", type: "kpi", data_view_id: "primary_metric" }} rows={previewRows} />}
          </div>
          <div className="kc-byaan-data-views">
            {dashboard.dataViews.slice(0, 6).map((view, index) => {
              const record = objectValue(view);
              return (
                <section key={String(record.id || index)}>
                  <strong>{String(record.title || record.name || record.id || `view_${index + 1}`)}</strong>
                  <span>{String(record.metric || record.metric_id || record.kind || "governed data view")}</span>
                </section>
              );
            })}
          </div>
        </>
      ) : (
        <div className="kc-byaan-blank-dashboard">
          <Database className="kc-native-state-icon" />
          <strong>Data Here</strong>
          <span>Your dashboard content will appear here once you add visualizations</span>
        </div>
      )}
    </div>
  );
}

function DashboardTile({ tile, rows }: { tile: Record<string, unknown>; rows: Array<Record<string, unknown>> }) {
  const type = String(tile.type || "tile").toLowerCase();
  return (
    <article className={`is-${type}`}>
      <span>{type}</span>
      <strong>{String(tile.title || tile.id || "KPI")}</strong>
      <small>{String(tile.data_view_id || "primary_metric")}</small>
      {type.includes("chart") || type.includes("bar") || type.includes("line") ? <Sparkline rows={rows} /> : null}
    </article>
  );
}

function Sparkline({ rows }: { rows: Array<Record<string, unknown>> }) {
  const values = rows
    .slice(0, 8)
    .map((row) => Object.values(row).find((value) => typeof value === "number"))
    .filter((value): value is number => typeof value === "number");
  const bars = values.length ? values : [8, 14, 11, 18, 16, 22];
  const max = Math.max(...bars, 1);
  return <div className="kc-byaan-sparkline">{bars.map((value, index) => <span key={index} style={{ height: `${Math.max(14, (value / max) * 100)}%` }} />)}</div>;
}

function QueriesPanel({ workspace }: { workspace: ByaanOriginalWorkspaceModel }) {
  return (
    <section className="kc-byaan-data-workspace">
      <MiniTable rows={workspace.previewRows} />
      <div className="kc-byaan-data-catalog">
        {workspace.dashboard.queries.map((query) => (
          <EvidenceBlock key={String(query.id)} title={String(query.title)} value={String(query.sql || "-- no SQL")} />
        ))}
      </div>
    </section>
  );
}

function LineagePanel({ workspace }: { workspace: ByaanOriginalWorkspaceModel }) {
  return (
    <section className="kc-byaan-lineage-workspace" data-testid="dashboard-query-evidence-panel">
      <EvidenceBlock title="metricDefinition" value={formatJson(workspace.queryResult?.data.metricDefinition ?? objectValue(workspace.dashboard.queries[0]).metricDefinition)} />
      <EvidenceBlock title="policyDecision" value={formatJson(workspace.queryResult?.data.policyDecision ?? objectValue(workspace.dashboard.queries[0]).policyDecision)} />
      <EvidenceBlock title="freshness" value={formatJson(workspace.queryResult?.data.freshness ?? objectValue(workspace.dashboard.queries[0]).freshness)} />
      <EvidenceBlock title="lineage" value={formatJson(workspace.queryResult?.data.lineage ?? objectValue(workspace.dashboard.queries[0]).lineage)} />
      <EvidenceBlock title="evidence" value={formatJson(workspace.queryResult?.data.evidence ?? objectValue(workspace.dashboard.queries[0]).evidence)} />
    </section>
  );
}

function MiniTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = Object.keys(rows[0] ?? {}).slice(0, 10);
  if (!rows.length || !columns.length) {
    return <div className="kc-byaan-result-empty"><Database className="kc-native-icon" /><span>No data found</span></div>;
  }
  return (
    <div className="kc-byaan-result-table">
      <table>
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.slice(0, 20).map((row, index) => (
            <tr key={index}>{columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceBlock({ title, value }: { title: string; value: string }) {
  return <section><h3>{title}</h3><pre><code>{value}</code></pre></section>;
}
