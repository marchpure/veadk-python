import React, { useEffect, useState } from "react";
import { AlertTriangle, Download, FileCode2, FileJson, Loader2, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { commandErrorMessage, runTypedCommand } from "../../lib/qualityPublicationClient";

export default function ExportModal({ onClose, showToast, searchParams }: { onClose: () => void; showToast: (message: string) => void; searchParams?: URLSearchParams }) {
  const [format, setFormat] = useState<"json" | "csv" | "html">("html");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [artifactRef, setArtifactRef] = useState<Record<string, unknown> | null>(null);
  const resourceId = searchParams?.get("file") || searchParams?.get("draft_id") || "";

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  const handleExport = async () => {
    if (!resourceId) {
      setError("缺少 resourceId，无法请求服务端导出。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await runTypedCommand({
        command: "artifact.export",
        payload: { resourceId, format },
      });
      if (!response.accepted) throw new Error(commandErrorMessage(response));
      const ref = response.result?.artifactRef || response.result?.artifact_ref;
      if (!ref || typeof ref !== "object") throw new Error("服务端未返回 artifactRef。");
      setArtifactRef(ref as Record<string, unknown>);
      showToast("服务端已接受请求。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导出失败。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} role="dialog" aria-modal="true" aria-labelledby="export-modal-title">
      <div className="flex w-full max-w-[500px] flex-col overflow-hidden rounded-2xl bg-white shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 p-5">
          <h2 id="export-modal-title" className="text-lg font-semibold text-slate-900">导出产物</h2>
          <button onClick={onClose} aria-label="关闭" title="关闭" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"><X size={20} /></button>
        </div>
        <div className="border-b border-slate-100 p-5">
          <div className="mb-3 text-sm text-slate-600">导出只接受服务端 `artifact.export` 返回的 artifactRef；不会在浏览器生成文件或模拟下载。</div>
          <div className="grid grid-cols-3 gap-2">
            {(["html", "json", "csv"] as const).map((item) => (
              <button key={item} onClick={() => setFormat(item)} className={cn("rounded-xl border px-3 py-3 text-sm font-bold uppercase", format === item ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-600")}>
                {item === "html" ? <FileCode2 size={16} className="mr-1 inline" /> : <FileJson size={16} className="mr-1 inline" />}
                {item}
              </button>
            ))}
          </div>
        </div>
        <div className="p-5">
          {artifactRef ? (
            <pre className="max-h-64 overflow-auto rounded-xl bg-slate-950 p-3 text-[10px] text-slate-100">{JSON.stringify(artifactRef, null, 2)}</pre>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">等待服务端返回导出引用。</div>
          )}
          {error && <div role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"><AlertTriangle size={14} className="mr-1 inline" />{error}</div>}
        </div>
        <div className="flex shrink-0 justify-end border-t border-slate-100 bg-slate-50 p-5">
          <button onClick={() => void handleExport()} disabled={busy} className="flex w-full items-center justify-center rounded-xl bg-blue-600 py-2.5 text-sm font-medium text-white disabled:opacity-50">
            {busy ? <Loader2 size={18} className="mr-2 animate-spin" /> : <Download size={18} className="mr-2" />}
            请求服务端导出
          </button>
        </div>
      </div>
    </div>
  );
}
