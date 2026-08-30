import { useEffect, useMemo, useRef, useState } from "react";
import { ArtifactViewer } from "../artifact/ArtifactViewer";
import type { Artifact, Revision, TemplateKey } from "../domain/types";
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
  published,
  onClose,
  onRun,
  onShare,
  onPublish,
  onBindAgent,
  onAdvanced,
}: {
  artifacts: Artifact[];
  revisions: Revision[];
  published: boolean;
  onClose?: () => void;
  onRun: () => void;
  onShare: () => void;
  onPublish: () => void;
  onBindAgent: () => void;
  onAdvanced: () => void;
}) {
  const currentRevision = revisions.at(-1) || null;
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
  const pane = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!latestByKind.has(activeKind) && kinds.length) setActiveKind(kinds.at(-1) || "generic");
  }, [activeKind, kinds, latestByKind]);
  const activeArtifact = latestByKind.get(activeKind) || artifacts.at(-1) || null;

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
        onRun={onRun}
        onFullscreen={() => void pane.current?.requestFullscreen?.()}
        onExport={exportArtifact}
        onShare={onShare}
        onPublish={onPublish}
        onBindAgent={onBindAgent}
        onAdvanced={onAdvanced}
      />
      <div className="kw-artifact-stage">
        {activeArtifact ? (
          <>
            <div className="kw-artifact-version">v{revisions.find((item) => item.revision_id === activeArtifact.revision_id)?.number || "—"} · {new Date(activeArtifact.created_at).toLocaleString("zh-CN")}</div>
            <ArtifactViewer artifact={activeArtifact} />
          </>
        ) : (
          <div className="kw-artifact-waiting"><strong>等待产物生成</strong><span>真实 Artifact 创建后会立即显示在这里。</span></div>
        )}
      </div>
    </section>
  );
}
