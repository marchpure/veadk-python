import React, { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Library, Loader2, Network, Plus, Search, Workflow } from "lucide-react";
import ArtifactHeader from "./ArtifactHeader";
import { DomainRequestError, getGraphProjection, getGraphQueryResult, mutateGraph, queryGraph } from "../../../production/domainClient";
import { cn } from "../../lib/utils";

export default function KnowledgeGraphView({ isTeam = false, searchParams, setSearchParams, showToast, fileId = "kg_sales" }: any) {
  const [activeTab, setActiveTab] = useState(searchParams.get("kg_tab") || "graph");
  const [projection, setProjection] = useState<any>({ entities: [], relationships: [], constraints: [], lineage: [], revision: 0 });
  const [selectedEntity, setSelectedEntity] = useState("");
  const [queryInput, setQueryInput] = useState("");
  const [queryMode, setQueryMode] = useState<"neighbors" | "path">("neighbors");
  const [pathTarget, setPathTarget] = useState("");
  const [queryResult, setQueryResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const queryResultId = searchParams.get("graph_query_result_id");

  const reload = async () => {
    try {
      setProjection(await getGraphProjection(fileId));
    } catch (cause) {
      setError(cause instanceof DomainRequestError ? cause.message : "图谱读取失败");
    }
  };
  useEffect(() => { void reload(); }, [fileId]);
  useEffect(() => {
    if (!queryResultId) return;
    let active = true;
    void getGraphQueryResult(fileId, queryResultId).then((result) => {
      if (active) {
        setQueryResult(result);
        setActiveTab("query");
        if (result.mode === "path" || result.mode === "neighbors") setQueryMode(result.mode);
        if (typeof result.entityId === "string") setQueryInput(result.entityId);
        if (typeof result.from === "string") setQueryInput(result.from);
        if (typeof result.to === "string") setPathTarget(result.to);
      }
    }).catch((cause) => {
      if (active) setError(cause instanceof DomainRequestError ? cause.message : "图查询结果读取失败");
    });
    return () => { active = false; };
  }, [fileId, queryResultId]);

  const addEntity = async () => {
    const name = globalThis.prompt?.("请输入实体类型");
    if (!name?.trim()) return;
    setBusy(true);
    try {
      const result = await mutateGraph(fileId, { operation: "upsert_entity", entity: { id: name.trim().toLowerCase().replace(/\s+/g, "_"), type: name.trim(), properties: [], constraints: [] } });
      setProjection(result);
      showToast?.("实体已形成服务端 graph revision");
    } catch (cause) {
      setError(cause instanceof DomainRequestError ? cause.message : "实体变更失败");
    } finally { setBusy(false); }
  };

  const addRelationship = async () => {
    const from = globalThis.prompt?.("请输入起点实体 ID");
    const to = globalThis.prompt?.("请输入终点实体 ID");
    const type = globalThis.prompt?.("请输入关系类型");
    if (!from?.trim() || !to?.trim() || !type?.trim()) return;
    setBusy(true);
    try {
      const relationshipId = `${from.trim()}-${to.trim()}-${type.trim().toLowerCase().replace(/\s+/g, "_")}`;
      const result = await mutateGraph(fileId, {
        operation: "upsert_relationship",
        relationship: { id: relationshipId, from: from.trim(), to: to.trim(), type: type.trim() },
      });
      setProjection(result);
      showToast?.("关系已形成服务端 graph revision");
    } catch (cause) {
      setError(cause instanceof DomainRequestError ? cause.message : "关系变更失败");
    } finally { setBusy(false); }
  };

  const executeGraphQuery = async () => {
    if (!queryInput.trim()) return;
    setBusy(true);
    try {
      const query = queryMode === "neighbors"
        ? { mode: "neighbors", entityId: queryInput.trim() }
        : { mode: "path", from: queryInput.trim(), to: pathTarget.trim() };
      const result = await queryGraph(fileId, query);
      setQueryResult(result);
      const next = new URLSearchParams(searchParams);
      next.set("graph_query_result_id", String(result.queryResultId || ""));
      setSearchParams(next);
      showToast?.("已发送请求，等待状态刷新。");
    } catch (cause) {
      setError(cause instanceof DomainRequestError ? cause.message : "图查询失败");
    } finally { setBusy(false); }
  };

  const expandNeighbors = async (entityId: string) => {
    setSelectedEntity(entityId);
    setBusy(true);
    setError("");
    try {
      const result = await queryGraph(fileId, { mode: "neighbors", entityId });
      setQueryResult(result);
      const next = new URLSearchParams(searchParams);
      next.set("graph_query_result_id", String(result.queryResultId || ""));
      setSearchParams(next);
      setActiveTab("query");
      showToast?.("已从服务端展开实体邻居");
    } catch (cause) {
      setError(cause instanceof DomainRequestError ? cause.message : "邻居展开失败");
    } finally { setBusy(false); }
  };

  const tabs = [{ id: "ontology", label: "本体", icon: Library }, { id: "graph", label: "图谱", icon: Network }, { id: "query", label: "路径/邻居查询", icon: Search }];
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full flex flex-col h-full min-w-0">
      <ArtifactHeader title="销售业务知识图谱" typeLabel="Knowledge Graph" isTeam={isTeam} version={`V${projection.revision || 0}`}
        searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />
      <div className="flex items-center justify-between border-b border-slate-200 mt-2 mb-4">
        <div className="flex gap-6">{tabs.map((tab) => <button key={tab.id} onClick={() => { setActiveTab(tab.id); const next = new URLSearchParams(searchParams); next.set("kg_tab", tab.id); setSearchParams(next); }}
          className={cn("pb-3 text-sm font-bold border-b-2 flex items-center", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500")}><tab.icon size={16} className="mr-2" />{tab.label}</button>)}</div>
        <button onClick={() => { const next = new URLSearchParams(searchParams); next.set("pane", "open"); next.set("chat", "planning"); setSearchParams(next); }} className="mb-2 px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-bold">图谱构建助手（右侧 Agent）</button>
      </div>
      {error && <div role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      <div className="flex-1 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-6">
        {activeTab === "ontology" && <div>
          <div className="flex justify-between items-center mb-4"><div className="text-sm text-slate-600">服务端 typed projection revision V{projection.revision || 0}</div>
            <div className="flex gap-2">
              <button onClick={() => void addEntity()} disabled={busy || isTeam} className="px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-bold"><Plus size={14} className="inline mr-1" />新增实体</button>
              <button onClick={() => void addRelationship()} disabled={busy || isTeam} className="px-3 py-2 rounded-lg border border-blue-200 bg-white text-blue-700 text-xs font-bold"><Workflow size={14} className="inline mr-1" />新增关系</button>
            </div></div>
          {projection.entities.length === 0 ? <div className="h-64 flex items-center justify-center text-sm text-slate-400">暂无服务端实体</div> :
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">{projection.entities.map((entity: any) => <div key={entity.id} className="rounded-xl border border-slate-200 bg-white p-4"><div className="font-bold text-slate-800">{entity.type}</div><div className="mt-2 text-xs text-slate-500">ID: {entity.id}</div><div className="mt-1 text-xs text-slate-500">约束: {(entity.constraints || []).join(", ") || "无"}</div></div>)}</div>}
          <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="text-sm font-bold text-slate-700">投影约束</div>
              <div className="mt-2 text-xs text-slate-500">{projection.constraints?.length ? JSON.stringify(projection.constraints) : "暂无服务端约束"}</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="text-sm font-bold text-slate-700">Lineage</div>
              <div className="mt-2 text-xs text-slate-500">{projection.lineage?.length ? JSON.stringify(projection.lineage) : "暂无服务端 lineage"}</div>
            </div>
          </div>
        </div>}
        {activeTab === "graph" && <div className="min-h-[420px] flex flex-col items-center justify-center">
          {projection.entities.length === 0 ? <div className="text-sm text-slate-400">暂无 typed graph projection</div> : <div className="flex flex-wrap justify-center gap-8">
            {projection.entities.map((entity: any) => <button key={entity.id} onClick={() => setSelectedEntity(entity.id)} className={cn("rounded-full border-2 bg-white px-8 py-4 font-bold shadow-sm", selectedEntity === entity.id ? "border-blue-600 ring-4 ring-blue-100" : "border-slate-300")}>{entity.type}</button>)}
          </div>}
          {selectedEntity && <div className="mt-8 flex flex-col items-center gap-3 text-sm text-slate-600">
            <div>已选实体：{selectedEntity}</div>
            <button onClick={() => void expandNeighbors(selectedEntity)} disabled={busy} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white">
              {busy ? <Loader2 size={14} className="inline mr-1 animate-spin" /> : <Search size={14} className="inline mr-1" />}展开服务端邻居
            </button>
          </div>}
          {projection.relationships.length > 0 && <div className="mt-10 w-full max-w-3xl rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-3 text-sm font-bold text-slate-700">服务端关系 projection</div>
            <div className="space-y-2 text-xs text-slate-600">
              {projection.relationships.map((relationship: any) => <div key={relationship.id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                <span className="font-mono">{relationship.from} → {relationship.to}</span><span className="font-bold text-blue-700">{relationship.type}</span>
              </div>)}
            </div>
          </div>}
        </div>}
        {activeTab === "query" && <div className="max-w-3xl mx-auto">
          <div className="mb-3 flex gap-2">
            <button onClick={() => setQueryMode("neighbors")} className={cn("rounded-lg px-3 py-2 text-xs font-bold", queryMode === "neighbors" ? "bg-blue-600 text-white" : "bg-white text-slate-600 border border-slate-200")}>邻居</button>
            <button onClick={() => setQueryMode("path")} className={cn("rounded-lg px-3 py-2 text-xs font-bold", queryMode === "path" ? "bg-blue-600 text-white" : "bg-white text-slate-600 border border-slate-200")}>路径</button>
          </div>
          <div className="flex gap-3">
            <input value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder={queryMode === "neighbors" ? "输入实体 ID，例如 customer" : "起点实体 ID"} className="flex-1 rounded-lg border border-slate-300 px-4 py-3 text-sm" />
            {queryMode === "path" && <input value={pathTarget} onChange={(event) => setPathTarget(event.target.value)} placeholder="终点实体 ID" className="flex-1 rounded-lg border border-slate-300 px-4 py-3 text-sm" />}
            <button onClick={() => void executeGraphQuery()} disabled={busy || (queryMode === "path" && !pathTarget.trim())} className="rounded-lg bg-blue-600 px-4 py-3 text-white text-sm font-bold">{busy ? <Loader2 size={16} className="animate-spin" /> : <Workflow size={16} />}</button>
          </div>
          {queryResult && <div className="mt-5 rounded-xl border border-green-200 bg-green-50 p-5"><div className="font-bold text-green-800 flex items-center"><CheckCircle2 size={16} className="mr-2" />查询结果 {queryResult.queryResultId}</div>
            <pre className="mt-3 whitespace-pre-wrap text-xs text-slate-700">{JSON.stringify(queryResult, null, 2)}</pre></div>}
          {!queryResult && <div className="mt-16 text-center text-sm text-slate-400"><AlertTriangle size={24} className="mx-auto mb-2" />请输入服务端实体 ID 执行邻居查询</div>}
        </div>}
      </div>
    </div>
  );
}
