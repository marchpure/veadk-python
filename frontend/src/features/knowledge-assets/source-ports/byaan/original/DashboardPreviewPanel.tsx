"use client";

import { Check, Code, Copy, Database, ExternalLink, Eye, FileCode2, FileDown, FileJson, Filter, Hand, Loader2, Maximize2, MoreHorizontal, RefreshCw, Share2, X } from "lucide-react";
import { useState } from "react";

import type { DashboardShare } from "../../../../../adk/knowledgeAssets";
import { formatJson, objectValue } from "../../../../../knowledge-center/knowledgeWorkbenchUtils";
import type { ByaanOriginalWorkspaceModel, DashboardWorkspaceTab } from "./types";

export function DashboardPreviewPanel({
  workspace,
  activeTab,
  onActiveTabChange,
  onRefresh,
  onOpenFullscreen,
  busyShare = false,
  onShareDashboard,
  shareResult,
  onClearShare,
  onRevokeShare,
}: {
  workspace: ByaanOriginalWorkspaceModel;
  activeTab: DashboardWorkspaceTab;
  onActiveTabChange: (tab: DashboardWorkspaceTab) => void;
  onRefresh: () => void;
  onOpenFullscreen: () => void;
  busyShare?: boolean;
  onShareDashboard: () => void;
  shareResult: DashboardShare | null;
  onClearShare: () => void;
  onRevokeShare: (shareId: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copiedShare, setCopiedShare] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const dashboard = workspace.dashboard;
  const codeForDisplay = formatJson(workspace.dashboardSpec);
  const hasPreview = dashboard.tiles.length > 0 || workspace.previewRows.length > 0;
  const dashboardAssetId = String(workspace.selectedDashboard?.asset_id || workspace.buildResult?.dashboard?.asset_id || "");
  const canExportJson = hasPreview && Object.keys(workspace.dashboardSpec).length > 0;
  const canShare = hasPreview && Boolean(dashboardAssetId);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codeForDisplay);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  function exportHtml() {
    if (!hasPreview) return;
    downloadBlob(
      new Blob([dashboardHtml(workspace)], { type: "text/html;charset=utf-8" }),
      `${slug(dashboard.title || workspace.selectedDashboard?.name || "dashboard")}.html`,
    );
  }

  function exportJson() {
    if (!canExportJson) return;
    downloadBlob(
      new Blob(
        [
          JSON.stringify(
            {
              title: dashboard.title,
              dashboard_asset_id: dashboardAssetId,
              dashboard_spec: workspace.dashboardSpec,
              rows: workspace.previewRows,
              query_result: workspace.queryResult?.data ?? null,
              build_result: workspace.buildResult,
            },
            null,
            2,
          ),
        ],
        { type: "application/json;charset=utf-8" },
      ),
      `${slug(dashboard.title || workspace.selectedDashboard?.name || "dashboard")}.json`,
    );
  }

  function createShare() {
    if (!canShare || busyShare) return;
    onShareDashboard();
    setShareModalOpen(true);
  }

  async function copyShareLink() {
    if (!shareResult?.share_url) return;
    await navigator.clipboard.writeText(shareResult.share_url);
    setCopiedShare(true);
    window.setTimeout(() => setCopiedShare(false), 1800);
  }

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
          <button type="button" disabled title="PDF export is not configured for local Studio">
            <FileDown className="kc-native-icon" />
          </button>
          <button type="button" onClick={exportHtml} disabled={!hasPreview} title={hasPreview ? "Export current dashboard HTML" : "Run a query or build dashboard before exporting HTML"}>
            <FileCode2 className="kc-native-icon" />
          </button>
          <button type="button" onClick={exportJson} disabled={!canExportJson} title={canExportJson ? "Export dashboard spec and evidence JSON" : "Build dashboard evidence before exporting JSON"}>
            <FileJson className="kc-native-icon" />
          </button>
          <button type="button" onClick={createShare} disabled={!canShare || busyShare} title={canShare ? "Create share link" : "Generate a dashboard asset before sharing"}>
            {busyShare ? <Loader2 className="kc-native-icon kc-spin" /> : <Share2 className="kc-native-icon" />}
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
      {shareModalOpen ? (
        <ShareDashboardModal
          share={shareResult}
          sharing={busyShare}
          copied={copiedShare}
          onCopy={() => void copyShareLink()}
          onOpen={() => {
            if (shareResult?.share_url) window.open(shareResult.share_url, "_blank", "noopener,noreferrer");
          }}
          onRevoke={() => {
            if (shareResult?.share_id) onRevokeShare(shareResult.share_id);
          }}
          onClose={() => {
            setShareModalOpen(false);
            setCopiedShare(false);
            if (shareResult?.revoked_at) onClearShare();
          }}
        />
      ) : null}
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

function dashboardHtml(workspace: ByaanOriginalWorkspaceModel): string {
  const rows = workspace.previewRows.slice(0, 20);
  const columns = Object.keys(rows[0] ?? {});
  const table = rows.length
    ? `<table><thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead><tbody>${rows
        .map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(String(row[column] ?? ""))}</td>`).join("")}</tr>`)
        .join("")}</tbody></table>`
    : "<p>No rows returned.</p>";
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(workspace.dashboard.title || "Dashboard")}</title><style>body{font-family:system-ui,sans-serif;margin:24px;color:#111827}table{border-collapse:collapse;width:100%;margin-top:16px}th,td{border:1px solid #d1d5db;padding:8px;text-align:left}th{background:#f3f4f6}.tile{border:1px solid #d1d5db;border-radius:8px;padding:12px;margin:8px 0}</style></head><body><h1>${escapeHtml(workspace.dashboard.title || "Dashboard")}</h1><p>${escapeHtml(workspace.dashboard.description || "Governed dashboard export")}</p>${workspace.dashboard.tiles.map((tile) => `<div class="tile"><strong>${escapeHtml(String(objectValue(tile).title || objectValue(tile).id || "Tile"))}</strong><br><span>${escapeHtml(String(objectValue(tile).data_view_id || ""))}</span></div>`).join("")}${table}</body></html>`;
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "dashboard";
}

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

function ShareDashboardModal({
  share,
  sharing,
  copied,
  onCopy,
  onOpen,
  onRevoke,
  onClose,
}: {
  share: DashboardShare | null;
  sharing: boolean;
  copied: boolean;
  onCopy: () => void;
  onOpen: () => void;
  onRevoke: () => void;
  onClose: () => void;
}) {
  const revoked = Boolean(share?.revoked_at);
  return (
    <div className="byaan-share-backdrop" role="dialog" aria-modal="true" aria-label="Dashboard share link">
      <div className="byaan-share-modal">
        <header>
          <div>
            <h2>Share dashboard</h2>
            <p>{revoked ? "This link has been revoked." : "Local link ready for this generated dashboard snapshot."}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close share dialog"><X className="kc-native-icon" /></button>
        </header>
        {sharing && !share ? (
          <div className="byaan-share-loading"><Loader2 className="kc-native-icon kc-spin" />Creating share link...</div>
        ) : share ? (
          <div className="byaan-share-body">
            <label>
              <span>Share URL</span>
              <input readOnly value={share.share_url} />
            </label>
            <div className="byaan-share-meta">
              <span>{share.asset_version || "v1"}</span>
              <span>{share.visibility}</span>
              {share.created_at ? <span>{new Date(share.created_at).toLocaleString()}</span> : null}
            </div>
            <footer>
              <button type="button" onClick={onCopy} disabled={revoked}>
                {copied ? <Check className="kc-native-icon" /> : <Copy className="kc-native-icon" />}
                {copied ? "Copied" : "Copy link"}
              </button>
              <button type="button" onClick={onOpen} disabled={revoked}>
                <ExternalLink className="kc-native-icon" />
                Open
              </button>
              <button type="button" onClick={onRevoke} disabled={revoked || sharing} className="is-danger">
                {sharing ? <Loader2 className="kc-native-icon kc-spin" /> : <X className="kc-native-icon" />}
                Revoke
              </button>
            </footer>
          </div>
        ) : (
          <div className="byaan-share-loading">Share link was not created.</div>
        )}
      </div>
    </div>
  );
}
