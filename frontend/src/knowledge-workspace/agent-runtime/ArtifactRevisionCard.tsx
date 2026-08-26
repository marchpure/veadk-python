import type { ArtifactRevision } from "./contracts";

export function ArtifactRevisionCard({
  artifact,
}: {
  artifact: ArtifactRevision;
}) {
  const hasDiff = artifact.before !== undefined || artifact.after !== undefined;
  return (
    <article className="agent-artifact">
      <span className="agent-artifact__eyebrow">
        {artifact.viewRevisionId ? "ViewRevision" : "Artifact revision"}
      </span>
      <strong>{artifact.label}</strong>
      <span>
        {artifact.revision ? `Revision ${artifact.revision}` : artifact.id}
      </span>
      {artifact.baseRevision && (
        <small>
          {`基于 revision ${artifact.baseRevision} → ${artifact.revision ?? "new"}`}
          {artifact.newDigest ? ` · digest ${artifact.newDigest}` : ""}
        </small>
      )}
      {hasDiff && (
        <details className="agent-artifact__diff">
          <summary>查看变更</summary>
          <div className="agent-artifact__diff-grid">
            <div><span>Before</span><pre>{JSON.stringify(artifact.before, null, 2)}</pre></div>
            <div><span>After</span><pre>{JSON.stringify(artifact.after, null, 2)}</pre></div>
          </div>
        </details>
      )}
      {artifact.uri && (
        <a href={artifact.uri} target="_blank" rel="noreferrer noopener">
          打开产物
        </a>
      )}
    </article>
  );
}
