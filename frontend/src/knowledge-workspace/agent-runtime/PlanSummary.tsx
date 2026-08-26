import type { PlanStep } from "./contracts";
import { ChevronIcon, StatusIcon } from "./icons";

const PLAN_STATUS_LABELS: Record<PlanStep["status"], string> = {
  pending: "待处理",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
};

export function PlanSummary({ steps }: { steps: PlanStep[] }) {
  if (steps.length < 2) return null;
  const active = steps.find((step) => step.status === "running")
    ?? steps.find((step) => step.status === "failed")
    ?? steps.at(-1);
  const completed = steps.filter((step) => step.status === "completed").length;
  return (
    <details className="agent-plan">
      <summary>
        <StatusIcon className="agent-icon" />
        <span>{active?.label ?? "Plan"}</span>
        <span className="agent-plan__count">{completed}/{steps.length}</span>
        <ChevronIcon className="agent-chevron" />
      </summary>
      <ol>
        {steps.map((step) => (
          <li key={step.id} data-status={step.status}>
            <StatusIcon className="agent-icon" />
            <span className="agent-plan__step-label">{step.label}</span>
            <span
              className="agent-plan__step-status"
              data-status={step.status}
            >
              {PLAN_STATUS_LABELS[step.status]}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}
