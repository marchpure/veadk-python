import React, { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, FileText, Globe, LayoutDashboard, Loader2, Search, ToyBrick, X } from "lucide-react";
import { agentPublicationStore, useStore } from "../../lib/store";
import { createRequestContext } from "../../../production/ports";
import { getWorkspaceAdapter } from "../../../production/store";
import { asRecord, commandErrorMessage, inlineJsonStorageRef, publishedSkillOptions } from "../../lib/qualityPublicationClient";

export default function AgentResourceSelectorModal({ onClose }: { onClose: () => void }) {
  const publications = useStore(agentPublicationStore);
  const publishedAgents = publishedSkillOptions(publications);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [inputJson, setInputJson] = useState('{"question":"请基于当前数据生成摘要"}');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  const getIcon = (type: string) => {
    if (type === "dashboard") return <LayoutDashboard size={16} className="text-purple-600" />;
    if (type === "knowledge_base") return <FileText size={16} className="text-emerald-600" />;
    return <Globe size={16} className="text-blue-600" />;
  };

  const filtered = publishedAgents.filter((item) => item.name.toLowerCase().includes(query.toLowerCase()));

  const invokeSelected = async () => {
    const item = publishedAgents.find((value) => value.id === selectedId);
    if (!item) {
      setError("请选择 Registry 中真实 Published Skill。");
      return;
    }
    if (!item.callerRef) {
      setError("当前 bootstrap 未提供 server-derived callerRef；禁止使用浏览器伪造 callerId 调用。");
      return;
    }
    let parsedInput: unknown;
    try {
      parsedInput = JSON.parse(inputJson);
    } catch {
      setError("输入必须是 JSON。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await getWorkspaceAdapter().command({
        command: "invocation.start",
        payload: {
          skillVersionId: item.id,
          skillViewRevisionId: item.skillViewRevisionId,
          inputRef: await inlineJsonStorageRef(parsedInput, "agent-invocation"),
          callerId: item.callerRef,
        },
      }, createRequestContext());
      if (!response.accepted) throw new Error(commandErrorMessage(response as any));
      setResult(response.result ?? {});
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "调用失败。");
    } finally {
      setBusy(false);
    }
  };

  const invocation = asRecord(result?.invocation);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 bg-slate-50 p-5">
          <h2 className="flex items-center text-lg font-bold text-slate-900"><ToyBrick size={20} className="mr-2 text-blue-600" />Agent 资源选择器</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 outline-none hover:bg-slate-200"><X size={20} /></button>
        </div>

        <div className="border-b border-slate-100 p-4">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-2.5 text-slate-400" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索服务端 Registry 中的 Published Skill" className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-4 text-sm outline-none focus:border-blue-500" />
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto bg-slate-50/50 p-4 md:grid-cols-[1fr_280px]">
          <div className="space-y-3">
            {filtered.length === 0 ? (
              <div className="flex h-48 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white text-slate-400">
                <ToyBrick size={32} className="mb-3 opacity-30" />
                <div className="text-sm font-medium text-slate-500">暂无服务端 Published Skill</div>
              </div>
            ) : filtered.map((item) => (
              <label key={item.id} className="flex cursor-pointer items-start rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-all hover:border-blue-400">
                <input type="radio" name="agent_resource" checked={selectedId === item.id} onChange={() => setSelectedId(item.id)} className="mr-4 mt-1" />
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center font-bold text-slate-900">{getIcon(String(item.manifest?.kind ?? item.manifest?.template ?? "skill"))}<span className="ml-2 truncate">{item.name}</span></div>
                    <span className="flex items-center rounded border border-green-200 bg-green-50 px-2 py-0.5 text-[10px] font-medium text-green-700"><CheckCircle2 size={12} className="mr-1" />已发布</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                    <span className="rounded border border-slate-100 bg-slate-50 px-1.5 py-0.5">ID: {item.id}</span>
                    <span className="rounded border border-slate-100 bg-slate-50 px-1.5 py-0.5">版本: {item.version}</span>
                    <span className="rounded border border-slate-100 bg-slate-50 px-1.5 py-0.5">View: {item.skillViewRevisionId}</span>
                  </div>
                </div>
              </label>
            ))}
          </div>

          <div className="space-y-3">
            <label className="block text-xs font-bold text-slate-700">真实输入 JSON</label>
            <textarea value={inputJson} onChange={(event) => setInputJson(event.target.value)} rows={8} className="w-full rounded-lg border border-slate-300 p-3 font-mono text-xs outline-none focus:border-blue-500" />
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              <AlertTriangle size={14} className="mr-1 inline" />调用必须使用服务端 Registry 项和服务端派生 callerRef；缺失时 fail closed。
            </div>
            {result && (
              <pre className="max-h-52 overflow-auto rounded-lg bg-slate-950 p-3 text-[10px] text-slate-100">
                {JSON.stringify({
                  traceId: invocation.traceId,
                  dataRevisionRefs: result.dataRevisionRefs,
                  status: result.status,
                  result,
                }, null, 2)}
              </pre>
            )}
          </div>
        </div>
        {error && <div role="alert" className="border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

        <div className="flex shrink-0 justify-end gap-3 border-t border-slate-100 bg-white p-4">
          <button onClick={onClose} className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-bold text-slate-700">取消</button>
          <button onClick={() => void invokeSelected()} disabled={busy} className="flex items-center rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-bold text-white disabled:opacity-50">
            {busy && <Loader2 size={14} className="mr-1.5 animate-spin" />}调用 Skill
          </button>
        </div>
      </div>
    </div>
  );
}
