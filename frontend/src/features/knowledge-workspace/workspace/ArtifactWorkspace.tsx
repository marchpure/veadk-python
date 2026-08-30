import { useEffect, useMemo, useRef, useState } from "react";
import { ArtifactViewer, hasRenderableArtifact } from "../artifact/ArtifactViewer";
import type { Artifact, Revision, TemplateKey } from "../domain/types";
import type { AssistantArtifactPreview, ConversationTurnModel } from "../assistant/assistant-model";
import { ArtifactToolbar } from "./ArtifactToolbar";

function artifactKind(artifact: Artifact, revision: Revision | null): TemplateKey {
  const lineageTemplate = artifact.lineage?.template_key;
  if (lineageTemplate === "semantic" || lineageTemplate === "dashboard" || lineageTemplate === "sop") return lineageTemplate;
  return revision?.template_key || "generic";
}

const LABELS: Record<TemplateKey, string> = {
  generic: "运行结果",
  dashboard: "分析看板",
  semantic: "语义模型",
  sop: "业务 SOP",
};

function CloseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>;
}

export function ArtifactWorkspace({
  artifacts,
  revisions,
  turns,
  published,
  onClose,
  onShare,
  onPublish,
  onBindAgent,
  onAdvanced,
}: {
  artifacts: Artifact[];
  revisions: Revision[];
  turns?: ConversationTurnModel[];
  published: boolean;
  onClose?: () => void;
  onShare: () => void;
  onPublish: () => void;
  onBindAgent: () => void;
  onAdvanced: () => void;
}) {
  const currentRevision = revisions.reduce<Revision | null>(
    (current, revision) =>
      !current || revision.number > current.number ? revision : current,
    null,
  );
  const latestByKind = useMemo(() => {
    const result = new Map<TemplateKey, Artifact>();
    for (const artifact of artifacts) {
      const revision = revisions.find((item) => item.revision_id === artifact.revision_id) || currentRevision;
      result.set(artifactKind(artifact, revision), artifact);
    }
    return result;
  }, [artifacts, currentRevision, revisions]);
  const kinds = [...latestByKind.keys()];
  const [activeKind, setActiveKind] = useState<TemplateKey>("generic");
  const [selectedRevisionId, setSelectedRevisionId] = useState<string>("");
  const [viewerRefreshKey, setViewerRefreshKey] = useState(0);
  const pane = useRef<HTMLDivElement>(null);
  const previewState = useMemo<AssistantArtifactPreview | undefined>(() => (
    [...(turns || [])].reverse().find((turn) => turn.artifactPreview)?.artifactPreview
  ), [turns]);
  useEffect(() => {
    if (!latestByKind.has(activeKind) && kinds.length) setActiveKind(kinds.at(-1) || "generic");
  }, [activeKind, kinds, latestByKind]);
  useEffect(() => {
    const latestRevisionId = artifacts.at(-1)?.revision_id || revisions.at(-1)?.revision_id || "";
    if (!selectedRevisionId && latestRevisionId) setSelectedRevisionId(latestRevisionId);
    if (selectedRevisionId && revisions.length && !revisions.some((revision) => revision.revision_id === selectedRevisionId)) {
      setSelectedRevisionId(latestRevisionId);
    }
  }, [artifacts, revisions, selectedRevisionId]);
  const selectedArtifact = selectedRevisionId
    ? artifacts.find((item) => item.revision_id === selectedRevisionId) || null
    : null;
  const activeArtifact = selectedArtifact || latestByKind.get(activeKind) || artifacts.at(-1) || null;
  const hasPreviewSnapshot = (() => {
    if (
      !previewState
      || !["preview", "final"].includes(previewState.status)
      || previewState.mediaType !== "text/html"
      || !previewState.uri
    ) return false;
    try {
      const url = new URL(previewState.uri, window.location.origin);
      if (url.origin !== window.location.origin) return false;
      return previewState.status === "preview"
        ? url.pathname.startsWith("/api/knowledge/v1/artifact-snapshots/")
        : url.pathname.startsWith("/api/knowledge/v1/artifacts/");
    } catch {
      return false;
    }
  })();
  const hasArtifact = hasRenderableArtifact(activeArtifact) || hasPreviewSnapshot;

  const exportArtifact = () => {
    if (!activeArtifact?.uri) return;
    const url = new URL(activeArtifact.uri, window.location.origin);
    if (
      url.origin !== window.location.origin
      || !url.pathname.startsWith("/api/knowledge/v1/artifacts/")
    ) return;
    const link = document.createElement("a");
    link.href = url.toString();
    link.download = activeArtifact.title || "skill-artifact";
    link.rel = "noreferrer";
    link.click();
  };

  return (
    <section className="kw-artifact-workspace" aria-label="Artifact 工作区" ref={pane}>
      <header>
        <div className="kw-artifact-tabs" role="tablist" aria-label="Artifact 类型">
          {kinds.map((kind) => (
            <button type="button" role="tab" aria-selected={kind === activeKind} key={kind} onClick={() => setActiveKind(kind)}>{LABELS[kind]}</button>
          ))}
          {!kinds.length ? <strong>Artifact</strong> : null}
        </div>
        {onClose ? <button type="button" className="kw-workshop-close" aria-label="关闭产物" onClick={onClose}><CloseIcon /></button> : null}
      </header>
      <ArtifactToolbar
        revision={currentRevision}
        published={published}
        hasArtifact={hasArtifact}
        onRefresh={() => setViewerRefreshKey((value) => value + 1)}
        onFullscreen={() => void pane.current?.requestFullscreen?.()}
        onExport={exportArtifact}
        onShare={onShare}
        onPublish={onPublish}
        onBindAgent={onBindAgent}
        onAdvanced={onAdvanced}
      />
      <div className="kw-artifact-stage">
        {activeArtifact || previewState ? (
          <>
            <div className="kw-artifact-version">
              {activeArtifact
                ? `v${revisions.find((item) => item.revision_id === activeArtifact.revision_id)?.number || "—"} · ${new Date(activeArtifact.created_at).toLocaleString("zh-CN")}`
                : "临时预览 · 等待最终 Artifact"}
            </div>
            <ArtifactViewer
              key={viewerRefreshKey}
              artifact={activeArtifact}
              previewState={previewState}
              revisions={revisions}
              selectedRevisionId={selectedRevisionId}
              onSelectRevision={setSelectedRevisionId}
            />
          </>
        ) : (
          <div className="kw-artifact-waiting"><strong>等待产物生成</strong><span>真实 Artifact 创建后会立即显示在这里。</span></div>
        )}
      </div>
    </section>
  );
}
