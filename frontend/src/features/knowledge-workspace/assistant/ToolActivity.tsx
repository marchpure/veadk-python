import type { AssistantActivity } from "./assistant-model";

const STATUS_LABEL: Record<AssistantActivity["status"], string> = {
  pending: "等待中",
  running: "进行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function ToolActivity({ activity }: { activity: AssistantActivity }) {
  const detail = activity.outputSummary
    || activity.errorSummary
    || activity.inputSummary
    || activity.summary;
  return (
    <div className={`kw-activity is-${activity.status}`}>
      <div className="kw-activity-heading">
        <span className="kw-activity-dot" aria-hidden="true" />
        <span className="kw-activity-title">{activity.title}</span>
        <span className="kw-activity-status">{STATUS_LABEL[activity.status]}</span>
        {activity.durationMs !== undefined
          ? <span className="kw-activity-duration">{activity.durationMs}ms</span>
          : null}
      </div>
      {detail ? (
        <details className="kw-activity-detail">
          <summary>查看安全摘要</summary>
          <p>{detail}</p>
        </details>
      ) : null}
    </div>
  );
}
