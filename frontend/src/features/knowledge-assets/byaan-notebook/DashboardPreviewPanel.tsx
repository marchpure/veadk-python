import { useState } from "react";
import { Check, Code, Copy, Database, ExternalLink, Eye, FileCode2, FileDown, FileJson, Loader2, Maximize2, MoreHorizontal, RefreshCw, Share2, Sparkles, X } from "lucide-react";

import { QueryRunnerDocked } from "./QueryRunnerDocked";
import type { DashboardShare } from "../../../adk/knowledgeAssets";
import type { ByaanDashboardPreviewModel } from "./types";

type TabKey = "preview" | "code" | "queries";

export function DashboardPreviewPanel({
  preview,
  onRefresh,
  onOpenFullscreen,
  onBuildDashboard,
  buildDashboardDisabled = false,
  buildDashboardDisabledReason = "",
  onShareDashboard,
  shareResult,
  onClearShare,
  onRevokeShare,
  sharing = false,
}: {
  preview: ByaanDashboardPreviewModel;
  onRefresh: () => void;
  onOpenFullscreen: () => void;
  onBuildDashboard: () => void;
  buildDashboardDisabled?: boolean;
  buildDashboardDisabledReason?: string;
  onShareDashboard: () => void;
  shareResult: DashboardShare | null;
  onClearShare: () => void;
  onRevokeShare: (shareId: string) => void;
  sharing?: boolean;
}) {
  const [activeTab, setActiveTab] = useState<TabKey>("preview");
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [copiedShare, setCopiedShare] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const hasPreview = preview.processedHtmlContent.trim().length > 0;
  const hasCode = preview.generatedCode.trim().length > 0;
  const canExportHtml = hasPreview;
  const canExportJson = hasPreview && Object.keys(preview.dashboardSpec).length > 0;
  const canShare = hasPreview && Boolean(preview.dashboardAssetId) && !preview.isGenerating;
  const shareDisabledReason = preview.isGenerating
    ? "Dashboard is still generating"
    : hasPreview
      ? "Dashboard asset is not ready"
      : "Generate a dashboard preview before sharing";

  function exportHtml() {
    if (!canExportHtml) return;
    const html = preview.processedHtmlContent;
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `${slug(preview.title || "dashboard")}.html`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(href);
    setShowMoreMenu(false);
  }

  function exportJson() {
    if (!canExportJson) return;
    downloadBlob(
      new Blob([
        JSON.stringify({
          title: preview.title,
          dashboard_asset_id: preview.dashboardAssetId,
          dashboard_spec: preview.dashboardSpec,
          query: preview.querySnapshot,
          evidence: preview.evidenceSnapshot,
        }, null, 2),
      ], { type: "application/json;charset=utf-8" }),
      `${slug(preview.title || "dashboard")}.json`,
    );
    setShowMoreMenu(false);
  }

  function createShare() {
    if (!canShare || sharing) return;
    onShareDashboard();
    setShareModalOpen(true);
  }

  async function copyShareLink() {
    if (!shareResult?.share_url) return;
    await navigator.clipboard.writeText(shareResult.share_url);
    setCopiedShare(true);
    window.setTimeout(() => setCopiedShare(false), 1800);
  }

  async function copyCode() {
    if (!hasCode) return;
    await navigator.clipboard.writeText(preview.generatedCode);
    setCopiedCode(true);
    window.setTimeout(() => setCopiedCode(false), 1600);
  }

  return (
    <div className="byaan-dashboard-preview h-full flex flex-col bg-[#202124] border-l border-[#dfe3e8] relative">
      <div className="flex min-h-[44px] flex-shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[#34383f] px-3 py-1.5">
        <div className="flex items-center gap-1">
          <div className="flex gap-[2px]">
            <PreviewTab active={activeTab === "preview"} onClick={() => setActiveTab("preview")} icon={<Eye className="h-3 w-3" />}>Preview</PreviewTab>
            <PreviewTab active={activeTab === "code"} onClick={() => setActiveTab("code")} icon={<Code className="h-3 w-3" />}>Code</PreviewTab>
            <PreviewTab active={activeTab === "queries"} onClick={() => setActiveTab("queries")} icon={<Database className="h-3 w-3" />}>Queries</PreviewTab>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="flex items-center gap-1.5 rounded-[5px] border border-[#404040] bg-[#232323] px-2.5 py-[3px] text-[11px]">
            <span className="h-[5px] w-[5px] rounded-full bg-green-400" />
            <span className="font-medium text-[#e5e5e5]">{preview.versionInfo}</span>
          </span>
          <button
            onClick={onBuildDashboard}
            disabled={preview.isGenerating || buildDashboardDisabled}
            aria-label="Generate dashboard"
            title={buildDashboardDisabled ? buildDashboardDisabledReason : "Generate dashboard"}
            className="rounded-[5px] border border-[#404040] bg-[#232323] px-2.5 py-[5px] text-xs font-medium text-[#e5e5e5] transition-colors hover:bg-[#2a2a2a] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {preview.isGenerating ? <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> : <Sparkles className="mr-1 inline h-3 w-3" />}
            Generate
          </button>
          <button onClick={onRefresh} className="byaan-toolbar-icon" title="Refresh"><RefreshCw className="h-3.5 w-3.5" /></button>
          <div className="relative">
            <button onClick={() => setShowMoreMenu((value) => !value)} className="byaan-toolbar-icon" title="More actions"><MoreHorizontal className="h-3.5 w-3.5" /></button>
            {showMoreMenu ? (
              <div className="absolute right-0 top-full z-20 mt-1 w-48 rounded-lg border border-[#404040] bg-[#1f2024] py-1 shadow-xl">
                <button className="byaan-menu-item" disabled title="PDF export not configured"><FileDown className="h-3.5 w-3.5" />Export PDF</button>
                <button className="byaan-menu-item" onClick={exportHtml} disabled={!canExportHtml} title={canExportHtml ? "Export current dashboard HTML" : "暂无可导出的 HTML"}><FileCode2 className="h-3.5 w-3.5" />Export HTML</button>
                <button className="byaan-menu-item" onClick={exportJson} disabled={!canExportJson} title={canExportJson ? "Export dashboard spec and evidence JSON" : "暂无可导出的 JSON"}><FileJson className="h-3.5 w-3.5" />Export JSON</button>
                <button className="byaan-menu-item" onClick={onOpenFullscreen}><Maximize2 className="h-3.5 w-3.5" />Fullscreen</button>
              </div>
            ) : null}
          </div>
          <button
            onClick={createShare}
            disabled={!canShare || sharing}
            className="rounded-[5px] border border-[#4b5563] bg-[#f8fafc] px-3 py-[5px] text-xs font-medium text-[#18181b] transition-colors hover:bg-white disabled:cursor-not-allowed disabled:bg-[#3f3f46] disabled:text-[#a1a1aa]"
            title={canShare ? "Create share link" : shareDisabledReason}
          >
            {sharing ? <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> : <Share2 className="mr-1 inline h-3 w-3" />}
            Share
          </button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {activeTab === "preview" ? (
          <div className="flex h-full min-h-0 flex-col bg-[#0a0a0a]">
            {hasPreview ? (
              <iframe className="h-full w-full border-0" srcDoc={preview.processedHtmlContent} title="Dashboard Preview" sandbox="allow-scripts allow-forms allow-popups allow-modals" />
            ) : (
              <div className="relative flex h-full items-center justify-center overflow-hidden">
                <div className="relative z-10 px-8 text-center">
                  <div className="mb-6 inline-flex h-20 w-20 items-center justify-center rounded-2xl border border-purple-500/20 bg-gradient-to-br from-purple-500/10 to-[#ff7a1a]/10">
                    {preview.isGenerating ? <Loader2 className="h-10 w-10 animate-spin text-purple-300" /> : <Eye className="h-10 w-10 text-purple-400/50" />}
                  </div>
                  <h3 className="mb-2 text-lg font-semibold text-gray-300">{preview.isGenerating ? "Creating your dashboard..." : "Preview Area"}</h3>
                  <p className="mx-auto max-w-sm text-sm leading-relaxed text-gray-500">
                    {preview.isGenerating ? "Dashboard build is running. Preview appears as soon as the governed build completes." : "Run AskTable, then generate a dashboard to enable preview, share, and export."}
                  </p>
                  {!preview.isGenerating && preview.queryResult ? (
                    <button
                      onClick={onBuildDashboard}
                      disabled={buildDashboardDisabled}
                      title={buildDashboardDisabled ? buildDashboardDisabledReason : "Generate dashboard"}
                      className="mt-5 rounded-md border border-[#404040] bg-[#1a1a1a] px-3 py-2 text-xs text-[#e5e5e5] hover:bg-[#2a2a2a] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Generate dashboard
                    </button>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        ) : activeTab === "code" ? (
          <div className="flex h-full flex-col bg-[#0a0a0a]">
            <div className="flex flex-shrink-0 items-center justify-between border-b border-[#1f1f1f] px-4 py-3">
              <div>
                <p className="text-xs text-gray-400">Dashboard HTML</p>
                {preview.isGenerating ? <p className="mt-1 flex items-center gap-1 text-[11px] text-purple-300"><Sparkles className="h-3 w-3" />Streaming live edits</p> : null}
              </div>
              <button
                className="rounded-md border border-[#404040] bg-[#1a1a1a] p-2 text-white transition-colors hover:bg-[#2a2a2a] disabled:cursor-not-allowed disabled:opacity-50"
                title={hasCode ? "Copy dashboard code" : "No dashboard code to copy"}
                disabled={!hasCode}
                onClick={() => void copyCode()}
              >
                {copiedCode ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              </button>
            </div>
            <pre className="min-h-0 flex-1 overflow-auto p-5 font-mono text-xs leading-6 text-[#d4d4d8]">{hasCode ? preview.generatedCode : "// No HTML code available"}</pre>
          </div>
        ) : (
          <QueryRunnerDocked event={preview.queryResult} />
        )}
      </div>

      <div className="flex flex-shrink-0 items-center gap-2 border-t border-[#2a2a2a] px-3 py-[6px] text-[11px]">
        <span className={`h-[5px] w-[5px] rounded-full ${preview.isGenerating ? "animate-pulse bg-purple-400" : "bg-green-400"}`} />
        <span className="text-gray-400">{preview.isGenerating ? "Generating..." : "Ready"}</span>
        <div className="flex-1" />
        <button onClick={exportHtml} disabled={!canExportHtml} title={canExportHtml ? "Export current dashboard HTML" : "暂无可导出的 HTML"} className="inline-flex items-center gap-1 px-2 py-0.5 text-gray-400 transition-colors hover:text-white disabled:cursor-not-allowed disabled:opacity-50"><FileCode2 className="h-3 w-3" />HTML</button>
        <button onClick={exportJson} disabled={!canExportJson} title={canExportJson ? "Export dashboard spec and evidence JSON" : "暂无可导出的 JSON"} className="inline-flex items-center gap-1 px-2 py-0.5 text-gray-400 transition-colors hover:text-white disabled:cursor-not-allowed disabled:opacity-50"><FileJson className="h-3 w-3" />JSON</button>
        <button onClick={onOpenFullscreen} className="inline-flex items-center gap-1 px-2 py-0.5 text-gray-400 transition-colors hover:text-white"><Maximize2 className="h-3 w-3" />Focus</button>
      </div>

      {shareModalOpen ? (
        <ShareDashboardModal
          share={shareResult}
          sharing={sharing}
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

function PreviewTab({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-[5px] px-2.5 py-[5px] text-xs font-medium transition-colors ${active ? "bg-[#2a2a2a] text-white" : "text-gray-400 hover:text-white"}`}
    >
      {icon}
      {children}
    </button>
  );
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
          <button type="button" onClick={onClose} aria-label="Close share dialog"><X className="h-4 w-4" /></button>
        </header>
        {sharing && !share ? (
          <div className="byaan-share-loading"><Loader2 className="h-4 w-4 animate-spin" />Creating share link...</div>
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
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy link"}
              </button>
              <button type="button" onClick={onOpen} disabled={revoked}>
                <ExternalLink className="h-3.5 w-3.5" />
                Open
              </button>
              <button type="button" onClick={onRevoke} disabled={revoked || sharing} className="is-danger">
                {sharing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
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
