import React, { useEffect, useMemo } from "react";
import { Clock, FileText, X } from "lucide-react";
import { agentPublicationStore, resourceStore, useStore } from "../../lib/store";
import { historyFromBootstrap } from "../../lib/qualityPublicationClient";

export default function VersionHistoryModal({ onClose }: any) {
  const publications = useStore(agentPublicationStore);
  const resources = useStore(resourceStore);
  const versions = useMemo(() => historyFromBootstrap(publications, resources), [publications, resources]);

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  return (
    <div className="absolute inset-0 z-40 flex justify-end bg-slate-900/20 backdrop-blur-[1px]" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="flex h-full w-96 flex-col border-l border-slate-200 bg-white shadow-[-10px_0_30px_-10px_rgba(0,0,0,0.1)]" role="dialog" aria-modal="true" aria-labelledby="version-modal-title">
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/50 p-5">
          <h2 id="version-modal-title" className="text-lg font-semibold text-slate-900">服务端版本历史</h2>
          <button onClick={onClose} aria-label="关闭" title="关闭" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"><X size={20} /></button>
        </div>
        <div className="border-b border-slate-100 p-6">
          <h3 className="mb-3 flex items-center text-sm font-medium text-slate-800"><FileText size={16} className="mr-2 text-slate-500" /> 数据来源</h3>
          <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">
            仅展示 bootstrap 返回的 resources/publications；缺失则说明服务端没有可证明历史。
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <h3 className="mb-5 flex items-center text-sm font-medium text-slate-800"><Clock size={16} className="mr-2 text-slate-500" /> 版本记录</h3>
          {versions.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">服务端未返回版本历史。</div>
          ) : (
            <div className="relative ml-3 space-y-6 border-l-2 border-slate-100">
              {versions.map((item) => (
                <div key={item.id} className="relative pl-6">
                  <div className="absolute -left-[9px] top-1.5 h-4 w-4 rounded-full border-[3px] border-white bg-blue-500"></div>
                  <div className="rounded-xl border border-slate-200 bg-white p-4">
                    <div className="mb-1.5 flex items-start justify-between gap-2">
                      <div className="text-sm font-medium text-slate-800">{item.label}</div>
                      <div className="text-xs text-slate-400">{item.createdAt || "server"}</div>
                    </div>
                    <div className="text-xs leading-relaxed text-slate-600">{item.detail}</div>
                    <span className="mt-2 inline-flex rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] text-slate-500">{item.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
