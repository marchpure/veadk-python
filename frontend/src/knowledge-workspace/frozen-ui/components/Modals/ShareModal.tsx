import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, Copy, History, Link as LinkIcon, Loader2, Play, RefreshCw, Send, ShieldAlert, Users, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { asRecord, commandErrorMessage, runTypedCommand } from "../../lib/qualityPublicationClient";

export default function ShareModal({ onClose, searchParams, showToast }: any) {
  const [activeTab, setActiveTab] = useState<"access" | "refresh" | "delivery" | "history">("access");
  const [scope, setScope] = useState<"team" | "public" | "private">("team");
  const [mode, setMode] = useState<"realtime" | "snapshot">("snapshot");
  const [refreshType, setRefreshType] = useState<"manual" | "hourly" | "daily" | "weekly" | "cron">("manual");
  const [cronExpr, setCronExpr] = useState("0 9 * * *");
  const [deliveryChannel, setDeliveryChannel] = useState("email");
  const [deliveryRecipients, setDeliveryRecipients] = useState("data-team@company.com");
  const [allowOld, setAllowOld] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [shareGrant, setShareGrant] = useState<Record<string, unknown> | null>(null);
  const [refreshRuns, setRefreshRuns] = useState<Record<string, unknown>[]>([]);
  const [copied, setCopied] = useState(false);
  const resourceId = searchParams?.get("file") || searchParams?.get("draft_id") || "";
  const hasSensitivity = !(searchParams?.get("eval_applied") === "true" || searchParams?.get("version") === "v2.2");

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  const scheduleSummary = useMemo(
    () => refreshType === "cron" ? cronExpr : refreshType,
    [cronExpr, refreshType],
  );

  const createShare = async () => {
    if (!resourceId) {
      setError("缺少 resourceId，无法请求服务端分享。");
      return;
    }
    if (scope === "public" && hasSensitivity) {
      setError("PII/安全门未通过，公开分享必须由服务端拒绝；请先完成质量门回归。");
      return;
    }
    setBusy("resource.share");
    setError("");
    try {
      const response = await runTypedCommand({
        command: "resource.share",
        payload: { resourceId },
      });
      if (!response.accepted) throw new Error(commandErrorMessage(response));
      const result = asRecord(response.result);
      const grant = asRecord(result.shareGrant ?? result.share_grant);
      if (!grant.id) throw new Error("服务端未返回 shareGrant。");
      setShareGrant(grant);
      showToast?.("已发送请求，等待状态刷新。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "分享失败。");
    } finally {
      setBusy(null);
    }
  };

  const requestRefresh = async (trigger: "manual" | "schedule") => {
    if (!resourceId) {
      setError("缺少 skillId，无法请求服务端刷新。");
      return;
    }
    setBusy(trigger === "manual" ? "refresh.run" : "refresh-schedule");
    setError("");
    try {
      if (trigger === "schedule") {
        const response = await runTypedCommand({
          command: "action.update",
          payload: { actionId: `refresh-schedule.upsert:${resourceId}:${scheduleSummary}:${deliveryChannel}` },
        });
        if (!response.accepted) throw new Error(commandErrorMessage(response));
        setError("RefreshSchedule 持久化契约尚未由 MAIN 暴露；当前仅记录了 action.update 审计意图。");
        return;
      }
      const response = await runTypedCommand({
        command: "refresh.run",
        payload: { skillId: resourceId, trigger },
      });
      if (!response.accepted) throw new Error(commandErrorMessage(response));
      const run = asRecord(asRecord(response.result).refreshRun ?? asRecord(response.result).refresh_run);
      if (run.id) setRefreshRuns((current) => [run, ...current]);
      showToast?.("已发送请求，等待状态刷新。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "刷新失败。");
    } finally {
      setBusy(null);
    }
  };

  const copyLink = async () => {
    const url = String(shareGrant?.id ? `server-share://${shareGrant.id}` : "");
    if (!url) {
      setError("没有服务端 shareGrant，不能复制分享链接。");
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      showToast?.("已发送请求，等待状态刷新。");
    } catch {
      setError("浏览器剪贴板不可用；服务端分享记录未受影响。");
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} role="dialog" aria-modal="true" aria-labelledby="share-modal-title">
      <div className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl md:flex-row">
        <div className="flex min-w-0 flex-[1.2] flex-col border-r border-slate-200">
          <div className="flex shrink-0 items-center justify-between border-b border-slate-100 p-4">
            <h2 id="share-modal-title" className="text-lg font-semibold text-slate-900">分享、刷新与交付</h2>
            <button onClick={onClose} className="rounded p-1 text-slate-400 outline-none hover:bg-slate-100 md:hidden"><X size={20} /></button>
          </div>
          <div className="flex shrink-0 space-x-1 overflow-x-auto border-b border-slate-100 bg-slate-50 px-4 pt-2">
            {[
              { id: "access", label: "访问权限", icon: Users },
              { id: "refresh", label: "数据刷新", icon: RefreshCw },
              { id: "delivery", label: "定时交付", icon: Send },
              { id: "history", label: "运行历史", icon: History },
            ].map((tab) => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id as any)} className={cn("flex items-center whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium outline-none", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}>
                <tab.icon size={16} className="mr-2" />{tab.label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto bg-white p-5 md:p-6">
            {activeTab === "access" && (
              <div className="space-y-5">
                <div className="space-y-2">
                  {(["team", "public", "private"] as const).map((item) => (
                    <button key={item} onClick={() => setScope(item)} className={cn("w-full rounded-xl border p-3 text-left", scope === item ? "border-blue-500 bg-blue-50 text-blue-800" : "border-slate-200 text-slate-700")}>
                      <span className="font-bold">{item === "team" ? "团队内公开" : item === "public" ? "互联网公开" : "私密指定成员"}</span>
                      <span className="ml-2 text-xs text-slate-500">由服务端授权记录决定最终可见性</span>
                    </button>
                  ))}
                </div>
                {scope === "public" && hasSensitivity && (
                  <div className="flex items-start rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
                    <ShieldAlert size={14} className="mr-2 mt-0.5 shrink-0" />检测到质量门未证明 PII/安全通过，公开分享 fail closed。
                  </div>
                )}
                <button onClick={() => void createShare()} disabled={busy !== null} className="w-full rounded-xl bg-slate-800 px-6 py-2.5 text-sm font-medium text-white disabled:opacity-50">请求服务端分享</button>
              </div>
            )}

            {activeTab === "refresh" && (
              <div className="space-y-5">
                <div className="grid grid-cols-2 gap-3">
                  <button onClick={() => setMode("snapshot")} className={cn("rounded-xl border p-4 text-left text-sm", mode === "snapshot" ? "border-blue-500 bg-blue-50" : "border-slate-200")}>版本快照</button>
                  <button onClick={() => setMode("realtime")} className={cn("rounded-xl border p-4 text-left text-sm", mode === "realtime" ? "border-blue-500 bg-blue-50" : "border-slate-200")}>实时/自动刷新</button>
                </div>
                <select value={refreshType} onChange={(event) => setRefreshType(event.target.value as any)} className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm">
                  <option value="manual">手动刷新</option><option value="hourly">每小时</option><option value="daily">每天</option><option value="weekly">每周</option><option value="cron">自定义 Cron</option>
                </select>
                {refreshType === "cron" && <input value={cronExpr} onChange={(event) => setCronExpr(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2.5 font-mono text-sm" />}
                <div className="grid grid-cols-2 gap-2">
                  <button onClick={() => void requestRefresh("manual")} disabled={busy !== null} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">手动刷新</button>
                  <button onClick={() => void requestRefresh("schedule")} disabled={mode !== "realtime" || busy !== null} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-bold text-slate-700 disabled:opacity-50">保存周期计划</button>
                </div>
              </div>
            )}

            {activeTab === "delivery" && (
              <div className="space-y-4">
                <select value={deliveryChannel} onChange={(event) => setDeliveryChannel(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm">
                  <option value="email">邮件</option><option value="feishu">飞书机器人</option><option value="slack">Slack</option>
                </select>
                <input value={deliveryRecipients} onChange={(event) => setDeliveryRecipients(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm" />
                <label className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  <input type="checkbox" checked={allowOld} onChange={(event) => setAllowOld(event.target.checked)} />
                  刷新失败后允许发送 last-good revision
                </label>
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">交付计划需要 MAIN 的 RefreshSchedule/Delivery contract；当前不会本地伪造。</div>
              </div>
            )}

            {activeTab === "history" && (
              <div className="space-y-3">
                {refreshRuns.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">暂无本次会话服务端 refresh.run 返回记录；持久化历史需 MAIN 暴露读模型。</div>
                ) : refreshRuns.map((run) => (
                  <div key={String(run.id)} className="rounded-xl border border-slate-200 bg-white p-3 text-xs">
                    <div className="font-bold text-slate-800">{String(run.id)}</div>
                    <div className="mt-1 text-slate-600">status={String(run.status)}; last-good={String(run.lastGoodRevision ?? run.last_good_revision ?? "—")}; error={String(run.errorCode ?? run.error_code ?? "—")}</div>
                  </div>
                ))}
              </div>
            )}

            {busy && <div className="mt-4 flex items-center rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"><Loader2 size={14} className="mr-2 animate-spin" />等待服务端：{busy}</div>}
            {error && <div role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"><AlertTriangle size={14} className="mr-1 inline" />{error}</div>}
          </div>
        </div>

        <div className="flex min-h-[360px] min-w-0 flex-1 flex-col border-t border-slate-200 bg-slate-50 md:border-t-0">
          <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white/50 p-5">
            <h3 className="text-sm font-semibold text-slate-800">服务端结果</h3>
            <button onClick={onClose} className="hidden rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600 md:block"><X size={20} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {shareGrant ? (
              <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-2 flex items-center text-sm font-bold text-slate-800"><LinkIcon size={14} className="mr-2 text-blue-600" />ShareGrant</div>
                <pre className="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 text-[10px] text-slate-100">{JSON.stringify(shareGrant, null, 2)}</pre>
                <button onClick={() => void copyLink()} className="mt-3 flex items-center rounded-lg bg-slate-800 px-3 py-2 text-xs font-bold text-white">
                  {copied ? <CheckCircle2 size={14} className="mr-1" /> : <Copy size={14} className="mr-1" />}复制 server-share 引用
                </button>
              </div>
            ) : (
              <div className="flex h-full flex-col items-center justify-center text-center text-slate-400">
                <Clock size={32} className="mb-3 opacity-50" />
                <p className="text-sm">等待服务端返回分享或刷新证据</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
