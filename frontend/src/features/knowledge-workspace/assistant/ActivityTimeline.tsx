import type { AssistantActivity } from "./assistant-model";
import { ToolActivity } from "./ToolActivity";

export function ActivityTimeline({
  activities,
  status,
}: {
  activities: AssistantActivity[];
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
}) {
  if (!activities.length) {
    return status === "queued" || status === "running"
      ? <div className="kw-activity-empty">正在等待执行事件…</div>
      : null;
  }
  const toolCount = new Set(
    activities.filter((item) => item.kind === "tool").map((item) => item.callId || item.id),
  ).size;
  const summary = `已${status === "running" || status === "queued" ? "进行" : "完成"} ${activities.length} 个步骤、调用 ${toolCount} 个能力`;
  return (
    <details
      className="kw-activity-timeline"
      open={status === "running" || status === "queued"}
    >
      <summary>{summary}</summary>
      <div className="kw-activity-list">
        {activities.map((activity) => (
          <ToolActivity activity={activity} key={`${activity.kind}:${activity.callId || activity.id}`} />
        ))}
      </div>
    </details>
  );
}
