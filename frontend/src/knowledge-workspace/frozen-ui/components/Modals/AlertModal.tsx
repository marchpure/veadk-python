import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BellRing, History, Loader2, Save, Send, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { commandErrorMessage, runTypedCommand } from "../../lib/qualityPublicationClient";

export default function AlertModal({ onClose, searchParams, setSearchParams }: any) {
  const [activeTab, setActiveTab] = useState<"alert" | "history">("alert");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("AlertRule 持久化、测试发送和历史读模型需要 MAIN 暴露共享契约；当前 UI fail closed。");
  const [auditIntents, setAuditIntents] = useState<Record<string, unknown>[]>([]);
  const fileId = searchParams.get("file") || "";
  const [alertConfig, setAlertConfig] = useState({
    metric: searchParams.get("alert_metric") || "通用业务指标",
    operator: "<",
    threshold: "-5.0",
    duration: "持续 5 分钟",
    silence: "1 小时",
    channels: ["feishu"],
    frequency: "1",
  });
  const preview = useMemo(
    () => `${alertConfig.metric} ${alertConfig.operator} ${alertConfig.threshold}% for ${alertConfig.duration}`,
    [alertConfig],
  );

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  const command = async (label: string, actionId: string) => {
    setBusy(label);
    setError("");
    try {
      const response = await runTypedCommand({
        command: "action.update",
        payload: { actionId },
      });
      if (!response.accepted) throw new Error(commandErrorMessage(response));
      setAuditIntents((current) => [
        { id: actionId, status: "audit-intent-acknowledged", requestId: response.requestId },
        ...current,
      ]);
      setError("AlertRule 持久化/测试发送契约尚未由 MAIN 暴露；当前仅记录 action.update 审计意图。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "告警命令失败。");
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    await command("alert-rule.upsert", `alert-rule.upsert:${fileId}:${preview}`);
    const p = new URLSearchParams(searchParams);
    p.delete("alert_metric");
    setSearchParams(p);
  };

  const handleTestRun = async () => {
    await command("alert-rule.test-send", `alert-rule.test-send:${fileId}:${preview}`);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} role="dialog">
      <div className="flex w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 bg-slate-50 p-5">
          <h2 className="flex items-center text-lg font-bold text-slate-900"><BellRing size={20} className="mr-2 text-blue-600" />刷新与告警规则</h2>
          <button onClick={onClose} className="rounded p-1 text-slate-400 outline-none hover:bg-slate-200 hover:text-slate-600"><X size={20} /></button>
        </div>
        <div className="flex shrink-0 space-x-1 border-b border-slate-100 bg-slate-50 px-4 pt-2">
          <button onClick={() => setActiveTab("alert")} className={cn("flex items-center border-b-2 px-4 py-2.5 text-sm font-bold", activeTab === "alert" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500")}><AlertTriangle size={16} className="mr-2" />规则配置</button>
          <button onClick={() => setActiveTab("history")} className={cn("flex items-center border-b-2 px-4 py-2.5 text-sm font-bold", activeTab === "history" ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500")}><History size={16} className="mr-2" />服务端记录</button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto bg-white p-6">
          {activeTab === "alert" ? (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <label className="col-span-2 block text-sm font-bold text-slate-800">监控指标
                  <input value={alertConfig.metric} onChange={(event) => setAlertConfig((current) => ({ ...current, metric: event.target.value }))} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-blue-500" />
                </label>
                <label className="block text-sm font-bold text-slate-800">触发操作符
                  <select value={alertConfig.operator} onChange={(event) => setAlertConfig((current) => ({ ...current, operator: event.target.value }))} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm">
                    <option value="<">低于</option><option value=">">高于</option><option value="==">等于</option>
                  </select>
                </label>
                <label className="block text-sm font-bold text-slate-800">阈值
                  <input value={alertConfig.threshold} onChange={(event) => setAlertConfig((current) => ({ ...current, threshold: event.target.value }))} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 font-mono text-sm" />
                </label>
                <label className="block text-sm font-bold text-slate-800">检查频率
                  <select value={alertConfig.frequency} onChange={(event) => setAlertConfig((current) => ({ ...current, frequency: event.target.value }))} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm">
                    <option value="1">每 1 分钟</option><option value="5">每 5 分钟</option><option value="60">每小时</option>
                  </select>
                </label>
                <label className="block text-sm font-bold text-slate-800">静默期
                  <select value={alertConfig.silence} onChange={(event) => setAlertConfig((current) => ({ ...current, silence: event.target.value }))} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm">
                    <option>1 小时</option><option>24 小时</option><option>不静默</option>
                  </select>
                </label>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
                <div className="font-mono text-slate-700">WHEN [{preview}]</div>
                <div className="mt-2 text-xs text-slate-500">渠道: {alertConfig.channels.join(", ")}；真实通知 adapter 未配置时必须由服务端失败返回。</div>
                <button onClick={() => void handleTestRun()} disabled={busy !== null} className="mt-3 flex items-center rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs font-bold text-blue-700 disabled:opacity-50"><Send size={12} className="mr-1" />测试发送并记录历史</button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {auditIntents.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">暂无服务端告警记录；需要 AlertRule 读模型。</div>
              ) : auditIntents.map((item) => (
                <div key={String(item.id)} className="rounded-xl border border-slate-200 bg-white p-3 text-xs">
                  <div className="font-bold text-slate-800">{String(item.id)}</div>
                  <div className="mt-1 text-slate-500">status={String(item.status)}; request={String(item.requestId)}; durable AlertRule history requires MAIN contract</div>
                </div>
              ))}
            </div>
          )}
          {busy && <div className="mt-4 flex items-center rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"><Loader2 size={14} className="mr-2 animate-spin" />等待服务端：{busy}</div>}
          {error && <div role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        </div>
        <div className="flex shrink-0 justify-end gap-3 border-t border-slate-100 bg-slate-50 p-5">
          <button onClick={onClose} className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-bold text-slate-700">取消</button>
          <button onClick={() => void handleSave()} disabled={busy !== null} className="flex items-center rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-bold text-white disabled:opacity-50"><Save size={16} className="mr-1.5" />保存设置</button>
        </div>
      </div>
    </div>
  );
}
