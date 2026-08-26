import type { AuthoringEvent, TimelineState } from "./contracts";
import { StatusIcon } from "./icons";

function activityLabel(event: AuthoringEvent | undefined): string {
  if (!event) return "正在理解需求";
  if (event.type === "context.resolving") return "正在解析上下文";
  if (event.type === "context.resolved") return "上下文已准备";
  if (event.type === "agent.started") {
    return event.payload.role === "router" ? "正在理解需求" : "正在组织回答";
  }
  if (event.type.startsWith("tool.")) {
    return event.public_summary || "正在调用工具";
  }
  if (event.type.startsWith("plan.")) return event.public_summary || "正在执行计划";
  if (event.type === "artifact.revision.created") return "正在生成 Skill";
  return event.public_summary || "Agent 正在工作";
}

export function ActivityStatus({ state }: { state: TimelineState }) {
  const hasAnswer = state.answerText.length > 0;
  const activeEvent = [...state.events].reverse().find((event) =>
    event.type.startsWith("context.")
    || event.type === "agent.started"
    || event.type.startsWith("tool.")
    || event.type.startsWith("plan.step.")
    || event.type === "artifact.revision.created"
  );
  const isActive = [
    "connecting",
    "running",
    "reconnecting",
    "stopping",
  ].includes(state.status);
  if (!isActive) return null;
  return (
    <div
      className={`agent-activity${hasAnswer ? " agent-activity--compact" : ""}`}
      role="status"
      aria-label="Agent activity"
    >
      <StatusIcon className="agent-icon" />
      <span>
        {state.status === "reconnecting"
          ? "连接中断，正在恢复"
          : state.status === "stopping"
            ? "正在停止"
            : activityLabel(activeEvent)}
      </span>
    </div>
  );
}
