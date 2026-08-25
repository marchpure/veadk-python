import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Clock3, Loader2, RefreshCw, X } from "lucide-react";

export type BuildTask = {
  id: string;
  label: string;
  status: string | null;
  detail?: string;
  error?: string;
};

const TASK_DEFINITIONS = [
  { id: "materials", label: "准备素材", tasks: ["添加数据或知识", "自动检查与清洗", "可信数据版本"] },
  { id: "capability", label: "定义能力", tasks: ["定义 Agent 能力", "预览与调试"] },
  { id: "quality", label: "质量与发布", tasks: ["质量检查", "发布门禁", "发布给 Agent"] },
] as const;

function statusLabel(status: string | null): string {
  if (!status) return "待服务端确认";
  if (["succeeded", "completed", "passed", "ready"].includes(status)) return "已完成";
  if (["running", "queued", "accepted", "planning", "evaluating", "publishing"].includes(status)) return "处理中";
  if (["failed", "error", "credential_blocked"].includes(status)) return "需要处理";
  return status;
}

function statusIcon(status: string | null) {
  if (["succeeded", "completed", "passed", "ready"].includes(status ?? "")) {
    return <CheckCircle2 size={16} className="text-emerald-600" />;
  }
  if (["running", "queued", "accepted", "planning", "evaluating", "publishing"].includes(status ?? "")) {
    return <Loader2 size={16} className="animate-spin text-blue-600" />;
  }
  if (["failed", "error", "credential_blocked"].includes(status ?? "")) {
    return <AlertTriangle size={16} className="text-amber-600" />;
  }
  return <Clock3 size={16} className="text-slate-400" />;
}

function textFromUnknown(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) return value;
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  for (const key of ["message", "detail", "reason", "description"]) {
    if (typeof record[key] === "string" && record[key].trim()) {
      return record[key] as string;
    }
  }
  return undefined;
}

export function readModelRetryable(readModel: Record<string, unknown> | null): boolean {
  if (!readModel) return false;
  if (readModel.retryable === true || readModel.canRetry === true) return true;
  if (["failed", "error", "timeout", "credential_blocked"].includes(String(readModel.status))) {
    return true;
  }
  if (["failed", "error", "timeout", "credential_blocked"].includes(String(readModel.executionState))) {
    return true;
  }
  return Boolean(
    textFromUnknown(readModel.error) ||
    textFromUnknown(readModel.lastError) ||
    textFromUnknown(readModel.failure),
  ) && readModel.retryable !== false;
}

export function tasksFromReadModel(readModel: Record<string, unknown> | null): BuildTask[] {
  const rawTasks = Array.isArray(readModel?.buildTasks)
    ? readModel.buildTasks
    : Array.isArray(readModel?.tasks)
      ? readModel.tasks
      : [];
  let offset = 0;
  return TASK_DEFINITIONS.flatMap((group) => {
    const groupTasks = group.tasks.map((label, taskIndex) => {
    const index = offset + taskIndex;
    const raw = rawTasks[index];
    const task = raw && typeof raw === "object" ? raw as Record<string, unknown> : null;
    return {
      id: `build-task-${index + 1}`,
      label,
      status: typeof task?.status === "string" ? task.status : null,
      detail: textFromUnknown(task?.detail),
      error: textFromUnknown(task?.error),
    };
    });
    offset += group.tasks.length;
    return groupTasks;
  });
}

export default function BuildDetailsDrawer({
  readModel,
  onRetry,
  onClose,
}: {
  readModel: Record<string, unknown> | null;
  onRetry: () => void;
  onClose: () => void;
}) {
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    materials: true,
    capability: true,
    quality: true,
  });
  const tasks = tasksFromReadModel(readModel);
  const retryable = readModelRetryable(readModel);
  const readModelError = textFromUnknown(readModel?.error) ??
    textFromUnknown(readModel?.lastError) ??
    textFromUnknown(readModel?.failure);
  let taskOffset = 0;

  return (
    <div
      className="fixed inset-0 z-[90] flex justify-end bg-slate-950/30"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        aria-label="构建详情"
        role="dialog"
        aria-modal="true"
        className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between border-b border-slate-100 pb-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">Build details</p>
            <h2 className="mt-1 text-lg font-semibold text-slate-900">构建详情</h2>
            <p className="mt-1 text-xs text-slate-500">状态、错误和重试能力来自当前 Skill 草稿的服务端 read model。</p>
          </div>
          <button type="button" aria-label="关闭构建详情" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-800">
            <X size={18} />
          </button>
        </div>

        <div className="mt-5 space-y-3">
          {TASK_DEFINITIONS.map((group) => {
            const start = taskOffset;
            taskOffset += group.tasks.length;
            const groupTasks = tasks.slice(start, start + group.tasks.length);
            const isOpen = openGroups[group.id] !== false;
            return (
              <section key={group.id} className="overflow-hidden rounded-xl border border-slate-200">
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => setOpenGroups((previous) => ({ ...previous, [group.id]: !isOpen }))}
                  className="flex w-full items-center justify-between bg-slate-50 px-4 py-3 text-left text-sm font-semibold text-slate-800 hover:bg-slate-100"
                >
                  <span>{group.label}</span>
                  {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                {isOpen ? (
                  <ol className="space-y-2 p-3">
                    {groupTasks.map((task) => (
                      <li key={task.id} className="flex gap-3 rounded-lg border border-slate-100 p-3">
                        <span className="mt-0.5 shrink-0">{statusIcon(task.status)}</span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center justify-between gap-3 text-sm font-medium text-slate-800">
                            {task.label}
                            <span className="shrink-0 text-xs font-normal text-slate-500">{statusLabel(task.status)}</span>
                          </span>
                          {task.detail ? <span className="mt-1 block text-xs leading-5 text-slate-500">{task.detail}</span> : null}
                          {task.error ? <span className="mt-1 block text-xs leading-5 text-red-700">{task.error}</span> : null}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </section>
            );
          })}
        </div>

        {readModelError ? (
          <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-800">
            <div className="font-medium">构建任务错误</div>
            <div>{readModelError}</div>
          </div>
        ) : null}
        {retryable ? (
          <button type="button" onClick={onRetry} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-medium text-blue-700 hover:bg-blue-100">
            <RefreshCw size={15} /> 重试构建任务
          </button>
        ) : null}
      </aside>
    </div>
  );
}
