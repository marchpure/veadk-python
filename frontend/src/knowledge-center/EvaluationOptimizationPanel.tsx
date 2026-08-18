import type {
  KnowledgeAssetOptimizationSnapshot,
} from "../adk/knowledgeAssets";

export function EvaluationOptimizationPanel({
  snapshots,
}: {
  snapshots: KnowledgeAssetOptimizationSnapshot[];
}) {
  const groups = snapshots.flatMap((snapshot) =>
    snapshot.groups.map((group) => ({
      snapshot,
      group,
    })),
  );
  return (
    <section className="kc-eval-optimizations">
      <header>
        <h3>优化建议</h3>
        <span>{groups.length} groups</span>
      </header>
      {groups.length === 0 ? (
        <div className="kc-eval-empty">
          <strong>暂无优化项</strong>
          <span>低分或 failed cases 会生成建议，但不会自动修改 MDL 或 dashboard_spec。</span>
        </div>
      ) : (
        <div className="kc-eval-optimization-list">
          {groups.map(({ snapshot, group }, index) => (
            <article key={`${snapshot.targetKind}:${snapshot.targetAssetId}:${index}`}>
              <header>
                <strong>{group.module}</strong>
                <em className={`kc-eval-status is-${group.priority}`}>{group.priority}</em>
              </header>
              <span>{snapshot.targetKind} · {snapshot.targetAssetId}</span>
              <ul>
                {group.items.map((item) => (
                  <li key={`${item.suggestion}:${item.reason}`}>
                    <strong>{item.suggestion}</strong>
                    <p>{item.reason}</p>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
