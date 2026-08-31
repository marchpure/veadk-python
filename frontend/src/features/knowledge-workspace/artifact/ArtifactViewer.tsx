import { useEffect, useMemo, useRef, useState } from "react";
import {
  Download,
  ExternalLink,
  FileCode2,
  Maximize2,
  RefreshCw,
} from "lucide-react";
import { withAuth } from "../../../adk/auth";
import { withLocalUser } from "../../../adk/identity";
import type { AssistantArtifactPreview } from "../assistant/assistant-model";
import type { Artifact, PresentationManifest, Revision } from "../domain/types";
import { useDelayedValue } from "./useDelayedValue";

type ArtifactPane = "preview" | "source" | "log";

interface ArtifactViewerProps {
  artifact: Artifact | null;
  previewState?: AssistantArtifactPreview;
  revisions?: Revision[];
  selectedRevisionId?: string;
  onSelectRevision?: (revisionId: string) => void;
}

interface ControlledArtifactSource {
  href: string;
  rawHref: string;
  kind: "final" | "preview";
  sandbox: string;
}

const PREVIEW_DEBOUNCE_MS = 320;

export function hasRenderableArtifact(artifact: Artifact | null | undefined): boolean {
  return Boolean(
    artifact
    && artifact.media_type === "text/html"
    && artifact.uri
    && controlledArtifactUrl(artifact.uri),
  );
}

function controlledArtifactUrl(uri: string): string | null {
  try {
    const url = new URL(uri, window.location.origin);
    if (
      url.origin !== window.location.origin ||
      !url.pathname.startsWith("/api/knowledge/v1/artifacts/")
    ) return null;
    return withAuth(url.toString());
  } catch {
    return null;
  }
}

function controlledPreviewSnapshotUrl(uri: string | undefined): string | null {
  if (!uri) return null;
  try {
    const url = new URL(uri, window.location.origin);
    if (
      url.origin !== window.location.origin ||
      !url.pathname.startsWith("/api/knowledge/v1/artifact-snapshots/")
    ) return null;
    return withAuth(url.toString());
  } catch {
    return null;
  }
}

function sourceFor(
  artifact: Artifact | null,
  previewState?: AssistantArtifactPreview,
): ControlledArtifactSource | null {
  if (artifact?.media_type === "text/html" && artifact.uri) {
    const href = controlledArtifactUrl(artifact.uri);
    if (href) return { href, rawHref: artifact.uri, kind: "final", sandbox: artifact.sandbox || "" };
  }
  if (previewState?.status === "preview" && previewState.mediaType === "text/html") {
    const href = controlledPreviewSnapshotUrl(previewState.uri);
    if (href) return { href, rawHref: previewState.uri || "", kind: "preview", sandbox: previewState.sandbox || "" };
  }
  if (previewState?.status === "final" && previewState.mediaType === "text/html" && previewState.uri) {
    const href = controlledArtifactUrl(previewState.uri);
    if (href) return { href, rawHref: previewState.uri, kind: "final", sandbox: previewState.sandbox || "" };
  }
  return null;
}

function artifactTitle(artifact: Artifact | null, previewState?: AssistantArtifactPreview): string {
  return artifact?.title || previewState?.title || "HTML Artifact";
}

function artifactSha(artifact: Artifact | null, previewState?: AssistantArtifactPreview): string | undefined {
  return artifact?.sha256 || previewState?.sha256;
}

function presentationMetadata(artifact: Artifact | null): PresentationManifest | null {
  if (artifact?.presentation) return artifact.presentation;
  const value = artifact?.lineage?.presentation;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as unknown as PresentationManifest;
}

function sourceText(artifact: Artifact | null, previewState?: AssistantArtifactPreview): string {
  if (artifact?.lineage) return JSON.stringify(artifact.lineage, null, 2);
  if (previewState?.status === "final" && previewState.source) return previewState.source;
  if (previewState?.source) return previewState.source;
  return "Source is available only after AutoSkill emits a legal HTML snapshot or final artifact lineage.";
}

function logLines(artifact: Artifact | null, previewState?: AssistantArtifactPreview): string[] {
  const lines = previewState?.log?.length ? [...previewState.log] : [];
  if (previewState?.message) lines.push(previewState.message);
  if (artifact) {
    lines.push(`final artifact ${artifact.artifact_id}`);
    lines.push(`revision ${artifact.revision_id}`);
    lines.push(`sha256 ${artifact.sha256}`);
  }
  return lines.length ? lines : ["Waiting for a valid AutoSkill HTML snapshot."];
}

export function ArtifactViewer({
  artifact,
  previewState,
  revisions = [],
  selectedRevisionId,
  onSelectRevision,
}: ArtifactViewerProps) {
  const [pane, setPane] = useState<ArtifactPane>("preview");
  const [loadState, setLoadState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [refreshKey, setRefreshKey] = useState(0);
  const [authenticatedSource, setAuthenticatedSource] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const source = useMemo(() => sourceFor(artifact, previewState), [artifact, previewState]);
  const debouncedSource = useDelayedValue(
    source,
    source?.kind === "preview" ? PREVIEW_DEBOUNCE_MS : 0,
  );
  const sha = artifactSha(artifact, previewState);
  const title = artifactTitle(artifact, previewState);
  const logs = logLines(artifact, previewState);
  const presentation = presentationMetadata(artifact);
  const surface = presentation?.surface;

  useEffect(() => {
    if (!source) {
      setLoadState("idle");
      return undefined;
    }
    setLoadState("loading");
    return undefined;
  }, [source]);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setAuthenticatedSource(null);
    if (!debouncedSource) return () => undefined;
    const controller = new AbortController();
    void fetch(debouncedSource.href, {
      headers: withLocalUser({ Accept: "text/html" }),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Artifact preview HTTP ${response.status}`);
        const blob = await response.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setAuthenticatedSource(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setAuthenticatedSource(null);
      });
    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [debouncedSource, refreshKey]);

  const download = () => {
    const href = source?.href;
    if (!href) return;
    const link = document.createElement("a");
    link.href = href;
    link.download = `${title.replace(/[^\w.-]+/g, "-") || "skill-artifact"}.html`;
    link.rel = "noreferrer";
    link.click();
  };

  const refresh = () => {
    if (!source) return;
    setLoadState("loading");
    setRefreshKey((value) => value + 1);
  };

  const fullscreen = () => {
    void wrapRef.current?.requestFullscreen?.();
  };

  const illegalPreview =
    previewState?.status === "blocked" || previewState?.status === "error";

  if (!artifact && !previewState) {
    return <div className="kw-empty-artifact">等待 AutoSkill 生成合法 HTML Artifact。</div>;
  }

  return (
    <section className="kw-artifact-viewer" aria-label="HTML Artifact" ref={wrapRef}>
      <div className="kw-artifact-meta">
        <div className="kw-artifact-identity">
          <span>{title}</span>
          {sha ? <code title={sha}>sha256:{sha.slice(0, 12)}...</code> : null}
          {surface ? <span className="kw-artifact-surface">{surface}</span> : null}
        </div>
        <div className="kw-artifact-controls">
          {revisions.length > 1 ? (
            <select
              aria-label="选择版本"
              value={selectedRevisionId || artifact?.revision_id || previewState?.revisionId || ""}
              onChange={(event) => onSelectRevision?.(event.target.value)}
            >
              {revisions.map((revision) => (
                <option value={revision.revision_id} key={revision.revision_id}>
                  v{revision.number} · {revision.skill_name}
                </option>
              ))}
            </select>
          ) : null}
          <button type="button" title="刷新预览" aria-label="刷新预览" onClick={refresh} disabled={!source}>
            <RefreshCw size={14} />
          </button>
          <button type="button" title="全屏" aria-label="全屏" onClick={fullscreen}>
            <Maximize2 size={14} />
          </button>
          <button type="button" title="下载 HTML" aria-label="下载 HTML" onClick={download} disabled={!source}>
            <Download size={14} />
          </button>
        </div>
      </div>
      {presentation ? (
        <dl className="kw-artifact-presentation-meta" aria-label="Artifact metadata">
          <div><dt>Surface</dt><dd>{String(presentation.surface || "generic")}</dd></div>
          <div><dt>Source</dt><dd>{String(presentation.source || "—")}</dd></div>
          <div><dt>Viewport</dt><dd>
            {typeof presentation.viewport === "object" && presentation.viewport
              ? `${String((presentation.viewport as Record<string, unknown>).width)} × ${String((presentation.viewport as Record<string, unknown>).height)}`
              : "—"}
          </dd></div>
        </dl>
      ) : null}
      <div className="kw-artifact-pane-tabs" role="tablist" aria-label="Artifact 视图">
        {(["preview", "source", "log"] as const).map((id) => (
          <button
            type="button"
            role="tab"
            aria-selected={pane === id}
            key={id}
            onClick={() => setPane(id)}
          >
            {id === "preview" ? "Preview" : id === "source" ? "Source" : "Log"}
            {id === "log" && logs.length ? <span>{logs.length}</span> : null}
          </button>
        ))}
      </div>
      <div className="kw-artifact-pane-body" role="tabpanel">
        {pane === "preview" ? (
          <>
            {loadState === "loading" && source ? (
              <div className="kw-artifact-skeleton" role="status">
                <span />
                <span />
                <span />
              </div>
            ) : null}
            {authenticatedSource && debouncedSource && artifact && debouncedSource.kind === "final" ? (
              <iframe
                key={`${authenticatedSource}:${refreshKey}`}
                title={title}
                src={authenticatedSource}
                sandbox={artifact.sandbox || ""}
                referrerPolicy="no-referrer"
                onLoad={() => setLoadState("loaded")}
                onError={() => setLoadState("error")}
                className={loadState === "loaded" ? "is-loaded" : "is-pending"}
              />
            ) : authenticatedSource && debouncedSource ? (
              <iframe
                key={`${authenticatedSource}:${refreshKey}`}
                title={title}
                src={authenticatedSource}
                sandbox={debouncedSource.sandbox || ""}
                referrerPolicy="no-referrer"
                onLoad={() => setLoadState("loaded")}
                onError={() => setLoadState("error")}
                className={loadState === "loaded" ? "is-loaded" : "is-pending"}
              />
            ) : (
              <div className={`kw-artifact-status${illegalPreview ? " is-error" : ""}`} role={illegalPreview ? "alert" : "status"}>
                {previewState?.message || "尚未收到完整、合法的 HTML 快照。"}
              </div>
            )}
            {loadState === "error" ? (
              <div className="kw-artifact-status is-error" role="alert">
                Artifact 加载失败。请检查权限或使用刷新重试。
              </div>
            ) : null}
          </>
        ) : null}
        {pane === "source" ? (
          <textarea
            className="kw-artifact-source"
            value={sourceText(artifact, previewState)}
            readOnly
            aria-label="Artifact source"
          />
        ) : null}
        {pane === "log" ? (
          <div className="kw-artifact-log">
            {logs.map((line, index) => <p key={`${index}:${line}`}>{line}</p>)}
            {source?.rawHref ? (
              <p><FileCode2 size={13} /> {source.rawHref}</p>
            ) : null}
            {artifact?.uri ? (
              <p><ExternalLink size={13} /> controlled same-origin artifact URL</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
