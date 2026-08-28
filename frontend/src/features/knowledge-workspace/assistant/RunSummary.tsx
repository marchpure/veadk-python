import type { ConversationTurnModel } from "./assistant-model";

const STATUS_LABEL: Record<ConversationTurnModel["status"], string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function duration(turn: ConversationTurnModel): string {
  if (!turn.startedAt) return "—";
  const end = turn.finishedAt ? Date.parse(turn.finishedAt) : Date.now();
  const milliseconds = Math.max(0, end - Date.parse(turn.startedAt));
  if (milliseconds < 1_000) return `${milliseconds}ms`;
  return `${(milliseconds / 1_000).toFixed(1)}s`;
}

export function RunSummary({ turn }: { turn: ConversationTurnModel }) {
  const summary = turn.requestSummary;
  return (
    <div className="kw-run-summary">
      <span className={`kw-run-status is-${turn.status}`}>{STATUS_LABEL[turn.status]}</span>
      <span>{duration(turn)}</span>
      {summary?.model ? <span>{summary.model}</span> : null}
      {summary ? (
        <span>
          Skill：使用 {summary.skills.used} · 创建 {summary.skills.created} · 更新 {summary.skills.updated}
        </span>
      ) : null}
      {summary?.usage && Object.keys(summary.usage).length ? (
        <details>
          <summary>高级信息</summary>
          <dl>
            {Object.entries(summary.usage).map(([key, value]) => (
              <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}
