import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Code, Fingerprint, ListTree, Loader2, Save } from "lucide-react";
import ArtifactHeader from "./ArtifactHeader";
import { DomainRequestError, getSemanticModel, getSemanticSourceRevisions, saveSemanticRevision, validateSemanticModel } from "../../../production/domainClient";
import { cn } from "../../lib/utils";

const EMPTY_MDL = `model Sales {
  primary_key id
  dimension region : string
  measure revenue : number
}`;

export default function SemanticView({ fileId = "semantic_sales", isTeam = false, searchParams, setSearchParams, showToast }: any) {
  const [activeTab, setActiveTab] = useState(searchParams.get("semantic_tab") || "mdl");
  const [mdl, setMdl] = useState("");
  const [revision, setRevision] = useState(0);
  const [validation, setValidation] = useState<any>(null);
  const [goldenSchema, setGoldenSchema] = useState<any>(null);
  const [goldenAssetRevision, setGoldenAssetRevision] = useState<any>(null);
  const [sourceRevisions, setSourceRevisions] = useState<any[]>([]);
  const [sourceRevisionId, setSourceRevisionId] = useState(searchParams.get("source_revision_id") || "");
  const [saveState, setSaveState] = useState<"idle" | "validating" | "saving">("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void getSemanticModel(fileId).then((result) => {
      if (!active) return;
      setMdl(String(result.mdl || ""));
      setRevision(Number(result.revision || 0));
      setValidation(result.revision ? result.schema : null);
      setGoldenSchema(result.goldenSchema || null);
      setGoldenAssetRevision(result.goldenAssetRevision || null);
      setSourceRevisionId(String(
        result.sourceRevisionId ||
        result.goldenAssetRevision?.sourceRevisionRefs?.[0] ||
        searchParams.get("source_revision_id") ||
        "",
      ));
    }).catch((cause) => {
      if (active) setError(cause instanceof DomainRequestError ? cause.message : "语义模型读取失败");
    });
    void getSemanticSourceRevisions().then((result) => {
      if (active) {
        const items = Array.isArray(result.items) ? result.items : [];
        setSourceRevisions(items);
        const requested = searchParams.get("source_revision_id");
        if (requested && items.some((item: any) => item.id === requested)) setSourceRevisionId(requested);
      }
    }).catch(() => {
      if (active) setSourceRevisions([]);
    });
    return () => { active = false; };
  }, [fileId]);

  const fields = useMemo(() => {
    const serverFields = validation?.schema?.fields;
    if (Array.isArray(serverFields)) return serverFields.map(String);
    const matches = mdl.matchAll(/^\s*(?:primary_key|dimension|measure|time|calculated)\s+(\w+)\s*(?::|$)/gm);
    return [...matches].map((match) => match[1]);
  }, [mdl, validation]);

  const runValidation = async () => {
    setSaveState("validating");
    setError("");
    try {
      const result = await validateSemanticModel(fileId, mdl, sourceRevisionId || undefined);
      setValidation(result);
      if (!result.valid) {
        showToast?.("校验阻断：服务端拒绝了当前语义模型");
      }
      return Boolean(result.valid);
    } catch (cause) {
      setError(cause instanceof DomainRequestError ? cause.message : "语义模型校验失败");
      return false;
    } finally {
      setSaveState("idle");
    }
  };

  const persistSemanticRevision = async () => {
    if (!(await runValidation())) return;
    setSaveState("saving");
    try {
      const result = await saveSemanticRevision(fileId, { mdl, expectedRevision: revision, sourceRevisionId: sourceRevisionId || undefined });
      setRevision(Number(result.revision));
      setValidation(result.validation);
      setGoldenSchema(result.goldenSchema || null);
      setGoldenAssetRevision(result.goldenAssetRevision || null);
      setSourceRevisionId(String(
        result.sourceRevisionId ||
        result.goldenAssetRevision?.sourceRevisionRefs?.[0] ||
        sourceRevisionId ||
        "",
      ));
      showToast?.('已发送请求，等待状态刷新。');
      const next = new URLSearchParams(searchParams);
      next.set("version", `V${result.revision}`);
      setSearchParams(next);
    } catch (cause) {
      setError(cause instanceof DomainRequestError ? cause.message : "语义 revision 保存失败");
    } finally {
      setSaveState("idle");
    }
  };

  const tabs = [
    { id: "canvas", label: "模型画布", icon: ListTree },
    { id: "mdl", label: "MDL 编辑器（真源）", icon: Code },
    { id: "lineage", label: "血缘与校验", icon: Fingerprint },
  ];

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full flex flex-col h-full min-w-0">
      <ArtifactHeader title={searchParams.get("custom_name") || "销售主题模型"} typeLabel="Semantic Model"
        isTeam={isTeam} version={`V${revision}`} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />
      <div className="flex space-x-6 border-b border-slate-200 mt-2 mb-4 shrink-0">
        {tabs.map((tab) => <button key={tab.id} onClick={() => setActiveTab(tab.id)}
          className={cn("pb-3 text-sm font-bold border-b-2 flex items-center", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500")}>
          <tab.icon size={16} className="mr-2" />{tab.label}
        </button>)}
      </div>
      {error && <div role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      <div className="flex-1 overflow-hidden bg-white border border-slate-200 rounded-xl min-h-[500px]">
        {activeTab === "mdl" && (
          <div className="h-full flex flex-col bg-[#0d1117]">
            <div className="p-4 border-b border-slate-700 flex items-center justify-between">
              <span className="text-slate-200 text-sm font-bold">服务端 MDL revision {revision}</span>
              <div className="flex gap-2">
                <button onClick={() => void runValidation()} disabled={saveState !== "idle"} className="px-3 py-2 rounded-lg bg-slate-700 text-slate-100 text-xs font-bold">
                  {saveState === "validating" ? <Loader2 size={14} className="animate-spin inline mr-1" /> : null}服务端校验
                </button>
                <button onClick={() => void persistSemanticRevision()} disabled={isTeam || saveState !== "idle"} className="px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-bold">
                  <Save size={14} className="inline mr-1" />保存新 revision
                </button>
              </div>
            </div>
            <div className="px-4 py-3 border-b border-slate-700">
              <label className="block text-xs text-slate-400 mb-1">绑定 Golden data SourceRevision（可选）</label>
              <select value={sourceRevisionId} onChange={(event) => {
                const value = event.target.value;
                setSourceRevisionId(value);
                const next = new URLSearchParams(searchParams);
                if (value) next.set("source_revision_id", value); else next.delete("source_revision_id");
                setSearchParams(next);
              }} className="w-full rounded-lg bg-slate-800 border border-slate-600 text-slate-200 px-3 py-2 text-xs">
                <option value="">MDL-only（不绑定数据源）</option>
                {sourceRevisions.map((source) => <option key={source.id} value={source.id}>{source.title || source.filename} · {source.id}</option>)}
              </select>
            </div>
            {!mdl && <div className="px-4 py-3 text-xs text-amber-300 border-b border-slate-700">服务端尚无模型，请输入 MDL 后校验保存。</div>}
            <textarea value={mdl} onChange={(event) => setMdl(event.target.value)} placeholder={EMPTY_MDL}
              className="flex-1 w-full resize-none bg-transparent p-5 text-sm leading-7 text-slate-200 font-mono outline-none" spellCheck={false} />
          </div>
        )}
        {activeTab === "canvas" && (
          <div className="h-full overflow-auto bg-slate-50 p-6">
            <div className="mb-4 text-sm text-slate-600">画布来自服务端 MDL projection；当前字段 {fields.length} 个。</div>
            {fields.length === 0 ? <div className="h-64 flex items-center justify-center text-sm text-slate-400">暂无服务端语义模型</div> :
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {fields.map((field) => <div key={field} className="rounded-xl border border-blue-200 bg-white p-4 shadow-sm"><div className="font-bold text-blue-900">{field}</div><div className="mt-2 text-xs text-slate-500">字段来自 MDL revision V{revision}</div></div>)}
              </div>}
          </div>
        )}
        {activeTab === "lineage" && (
          <div className="h-full overflow-auto p-6 bg-slate-50">
            {validation ? <div className="space-y-4">
              <div className={cn("rounded-xl border p-4 flex items-center", validation.valid ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-800")}>
                {validation.valid ? <CheckCircle2 size={18} className="mr-2" /> : <AlertTriangle size={18} className="mr-2" />}
                {validation.valid ? "服务端校验通过" : "服务端校验失败"}
              </div>
              {Array.isArray(validation.errors) && validation.errors.map((item: any, index: number) => <div key={index} className="text-sm text-red-700">第 {item.line} 行：{item.message}</div>)}
              <div className="text-sm text-slate-600">服务端 revision：V{revision}；字段：{fields.join(", ") || "—"}</div>
              <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-600">
                <div className="font-bold text-slate-700">Golden Asset / Schema</div>
                <div className="mt-1 font-mono">asset: {goldenAssetRevision?.id || "MDL-only"}</div>
                <div className="mt-1">source columns: {Array.isArray(goldenSchema?.columns) ? goldenSchema.columns.join(", ") : "语义模型 schema"}</div>
              </div>
            </div> : <div className="h-64 flex items-center justify-center text-sm text-slate-400">请先运行服务端校验</div>}
          </div>
        )}
      </div>
    </div>
  );
}
