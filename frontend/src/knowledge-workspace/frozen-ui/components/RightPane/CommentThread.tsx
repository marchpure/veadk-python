import React, { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, MessageSquare, RotateCcw, Send, Wand2, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { commandErrorMessage, nextStableId, postKnowledgeCommand } from "../../lib/qualityPublicationClient";

type ServerComment = {
  id: string;
  elementId: string;
  versionId: string;
  content: string;
  resolved: boolean;
};

const initialComments: ServerComment[] = [];

export default function CommentThread({ fileId, commentTarget, searchParams, setSearchParams, showToast }: any) {
  const version = searchParams.get("version") || "1";
  const [input, setInput] = useState("");
  const [comments] = useState<ServerComment[]>(initialComments);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [fixPlan, setFixPlan] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("CommentThread persistence contract is not yet exposed by MAIN; writes fail closed unless evaluation-fix can bind an existing run.");

  const unresolved = useMemo(() => comments.filter((item) => !item.resolved), [comments]);
  const visibleComments = useMemo(
    () => comments.filter((item) => item.versionId === version && (!commentTarget || item.elementId === commentTarget || item.elementId === "general")),
    [commentTarget, comments, version],
  );

  const closeThread = () => {
    const p = new URLSearchParams(searchParams);
    p.delete("comment_target");
    p.delete("pane");
    setSearchParams(p);
  };

  const command = async (label: string, name: string, payload: Record<string, unknown>) => {
    setBusy(label);
    setError("");
    try {
      const response = await postKnowledgeCommand({ command: name, payload });
      if (!response.accepted) throw new Error(commandErrorMessage(response));
      return response.result ?? {};
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "知识服务请求失败。";
      setError(message);
      showToast?.("服务端未接受，评论状态未本地伪造。");
      return null;
    } finally {
      setBusy(null);
    }
  };

  const createComment = async () => {
    if (!input.trim()) return;
    const actionId = `comment.create:${fileId}:${commentTarget || "general"}:${nextStableId("comment")}`;
    const result = await command("comment-create", "action.update", { actionId });
    if (!result) return;
    setError("CommentThread 持久化契约尚未由 MAIN 暴露；action.update 只记录审计意图，不能在浏览器伪造评论记录。");
  };

  const proposeFix = async (ids: string[], all = false) => {
    const runId = searchParams.get("evaluation_run_id");
    if (!runId) {
      setError("缺少 evaluation_run_id，无法把评论修复映射到持久化 EvaluationRun。需要 MAIN 暴露 CommentThread 聚合或传入 run 绑定。");
      return;
    }
    const payload = {
      runId,
      affectedCaseIds: ids,
      conflicts: [],
      patch: {
        id: nextStableId("comment-patch"),
        baseDraftRevision: `${fileId}:1`,
        operations: [{
          op: "replace_interaction",
          path: "/interaction/comment-resolution",
          before: "unresolved",
          after: "server-fix-plan",
        }],
      },
      ...(all ? {} : { issueCaseIds: ids }),
    };
    const result = await command(
      all ? "comment-fix-all" : "comment-fix-one",
      all ? "evaluation-fix.propose-all-unresolved" : "evaluation-fix.propose",
      payload,
    );
    if (result?.fixPlan) setFixPlan(result.fixPlan as Record<string, unknown>);
  };

  const applyFix = async () => {
    const planId = String(fixPlan?.id ?? "");
    if (!planId) return;
    const result = await command("comment-fix-apply", "evaluation-fix.apply", { planId });
    if (result?.fixPlan) {
      setFixPlan(result.fixPlan as Record<string, unknown>);
      setError("FixPlan 已由服务端更新；评论 resolved 状态需等待 MAIN 暴露 CommentThread 读模型后刷新。");
    }
  };

  const retryFailed = async () => {
    const planId = String(fixPlan?.id ?? "");
    if (!planId) {
      setError("失败项重试需要服务端返回的 FixPlan/rerun 记录。");
      return;
    }
    await command("comment-fix-retry", "evaluation-run.retry", { runId: String(fixPlan.rerunId ?? planId) });
  };

  const undoFix = async () => {
    const planId = String(fixPlan?.id ?? "");
    if (!planId) return;
    const result = await command("comment-fix-undo", "evaluation-fix.undo", { planId });
    if (result?.fixPlan) setFixPlan(result.fixPlan as Record<string, unknown>);
  };

  const toggleSelected = (id: string) => {
    setSelectedIds((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    );
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <div className="shrink-0 border-b border-slate-200 bg-slate-50/50 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">评论与修复跟进</h3>
            <div className="mt-0.5 text-xs text-slate-500">artifact={fileId}; version={version}; target={commentTarget || "general"}</div>
          </div>
          <button onClick={closeThread} className="rounded p-1 text-slate-400 outline-none hover:bg-slate-100"><X size={18} /></button>
        </div>
        <div className="mt-3 flex gap-2">
          <button onClick={() => setSelectedIds(unresolved.map((item) => item.id))} className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600">
            全选未解决 ({unresolved.length})
          </button>
          <button onClick={() => void proposeFix(selectedIds, false)} disabled={selectedIds.length === 0 || busy !== null} className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-bold text-blue-700 disabled:opacity-50">
            单条/选中修复
          </button>
          <button onClick={() => void proposeFix(unresolved.map((item) => item.id), true)} disabled={unresolved.length === 0 || busy !== null} className="rounded-md border border-purple-200 bg-purple-50 px-2 py-1 text-xs font-bold text-purple-700 disabled:opacity-50">
            全部未解决
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto bg-slate-50 p-4">
        {visibleComments.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-slate-400">
            <MessageSquare size={32} className="mb-3 opacity-30" />
            <span className="text-sm">暂无服务端评论记录</span>
          </div>
        ) : (
          <div className="space-y-3">
            {visibleComments.map((item) => (
              <div key={item.id} className={cn("rounded-xl border bg-white p-4 shadow-sm", item.resolved ? "border-green-200 opacity-70" : "border-slate-200")}>
                <div className="flex items-start gap-3">
                  {!item.resolved && (
                    <input type="checkbox" checked={selectedIds.includes(item.id)} onChange={() => toggleSelected(item.id)} />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 text-xs text-slate-500">{item.elementId}</div>
                    <div className="text-sm text-slate-800">{item.content}</div>
                  </div>
                  {item.resolved && <CheckCircle2 size={16} className="text-green-600" />}
                </div>
              </div>
            ))}
          </div>
        )}

        {fixPlan && (
          <div className="mt-4 rounded-xl border border-blue-200 bg-white p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between text-sm font-bold text-slate-800">
              <span><Wand2 size={15} className="mr-1 inline text-blue-600" />服务端 FixPlan</span>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">{String(fixPlan.status ?? "proposed")}</span>
            </div>
            <pre className="max-h-40 overflow-auto rounded-lg bg-slate-950 p-3 text-[10px] text-slate-100">{JSON.stringify(fixPlan, null, 2)}</pre>
            <div className="mt-3 grid grid-cols-3 gap-2">
              <button onClick={() => void applyFix()} disabled={busy !== null} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">应用结果并回归</button>
              <button onClick={() => void retryFailed()} disabled={busy !== null} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:opacity-50">失败项重试</button>
              <button onClick={() => void undoFix()} disabled={busy !== null} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:opacity-50"><RotateCcw size={12} className="mr-1 inline" />整体撤销</button>
            </div>
          </div>
        )}

        {busy && <div className="mt-3 flex items-center rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"><Loader2 size={14} className="mr-2 animate-spin" />等待服务端：{busy}</div>}
        {error && <div role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"><AlertTriangle size={14} className="mr-1 inline" />{error}</div>}
      </div>

      <div className="shrink-0 border-t border-slate-200 bg-white p-4">
        <div className="rounded-xl border border-slate-300 bg-slate-50 p-2.5 focus-within:border-blue-500 focus-within:bg-white">
          <textarea
            className="w-full resize-none bg-transparent p-1.5 text-sm outline-none placeholder:text-slate-400"
            rows={2}
            placeholder="输入评论；提交后等待服务端 action.update 确认"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void createComment();
              }
            }}
          />
          <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2">
            <div className="rounded-md border border-slate-200 bg-slate-100 px-2 py-1 text-[10px] font-medium text-slate-500">目标版本: {version}</div>
            <button onClick={() => void createComment()} disabled={!input.trim() || busy !== null} className="flex items-center rounded-lg bg-blue-600 px-3 py-1.5 font-medium text-white outline-none disabled:opacity-50">
              <Send size={14} className="mr-1.5" />发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
