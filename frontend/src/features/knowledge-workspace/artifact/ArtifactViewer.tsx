import { useEffect, useState } from "react";
import { withAuth } from "../../../adk/auth";
import type { Artifact } from "../domain/types";

interface ArtifactViewerProps {
  artifact: Artifact | null;
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

export function ArtifactViewer({ artifact }: ArtifactViewerProps) {
  const [state, setState] = useState<"idle" | "loading" | "loaded" | "error">("idle");

  useEffect(() => {
    setState(artifact ? "loading" : "idle");
  }, [artifact]);

  if (!artifact) {
    return <div className="kw-empty-artifact">运行成功后，HTML Artifact 会在这里呈现。</div>;
  }
  const uri = artifact.uri ? controlledArtifactUrl(artifact.uri) : null;
  if (!uri) {
    return <div className="kw-artifact-status" role="status">Artifact 已生成，等待受控 URL。</div>;
  }

  return (
    <section className="kw-artifact-viewer" aria-label="HTML Artifact">
      <div className="kw-artifact-meta">
        <span>{artifact.title || "运行结果"}</span>
        <code title={artifact.sha256}>sha256:{artifact.sha256.slice(0, 12)}…</code>
      </div>
      {state === "loading" ? <div className="kw-artifact-status">正在加载 Artifact…</div> : null}
      <iframe
        title={artifact.title || "HTML Artifact"}
        src={uri}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        onLoad={() => setState("loaded")}
        onError={() => setState("error")}
        className={state === "loaded" ? "is-loaded" : "is-pending"}
      />
      {state === "error" ? (
        <div className="kw-artifact-status is-error" role="alert">
          Artifact 加载失败。请检查权限或重新运行。
        </div>
      ) : null}
    </section>
  );
}
