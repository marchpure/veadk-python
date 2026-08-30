import type { AssistantActivity } from "./assistant-model";

const STATUS_LABEL: Record<AssistantActivity["status"], string> = {
  pending: "等待中",
  running: "进行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const KIND_LABEL: Record<AssistantActivity["kind"], string> = {
  turn: "阶段",
  planning: "规划",
  action: "动作",
  tool: "工具",
  observation: "观察",
  progress: "进度",
};

function completedSteps(activity: AssistantActivity): string {
  const steps = activity.steps || [];
  if (!steps.length) return "";
  const done = steps.filter((step) => step.status === "completed").length;
  return `${done}/${steps.length} 步完成`;
}

export function ToolActivity({ activity }: { activity: AssistantActivity }) {
  const detail = activity.summary;
  const stepSummary = completedSteps(activity);
  return (
    <div className={`kw-activity is-${activity.status}`}>
      <div className="kw-activity-heading">
        <span className="kw-activity-dot" aria-hidden="true" />
        <span className="kw-activity-kind">{KIND_LABEL[activity.kind]}</span>
        <span className="kw-activity-title">{activity.title}</span>
        {stepSummary ? <span className="kw-activity-steps">{stepSummary}</span> : null}
        <span className="kw-activity-status">{STATUS_LABEL[activity.status]}</span>
        {activity.durationMs !== undefined
          ? <span className="kw-activity-duration">{activity.durationMs}ms</span>
          : null}
      </div>
      {detail ? (
        <details className="kw-activity-detail">
          <summary>查看摘要</summary>
          <p>{detail}</p>
        </details>
      ) : null}
      {activity.inputSummary ? (
        <details className="kw-activity-detail">
          <summary>查看输入</summary>
          <pre>{activity.inputSummary}</pre>
        </details>
      ) : null}
      {activity.outputSummary ? (
        <details className="kw-activity-detail">
          <summary>查看结果</summary>
          <pre>{activity.outputSummary}</pre>
        </details>
      ) : null}
      {activity.errorSummary ? (
        <details className="kw-activity-detail is-error">
          <summary>查看错误</summary>
          <pre>{activity.errorSummary}</pre>
        </details>
      ) : null}
    </div>
  );
}
