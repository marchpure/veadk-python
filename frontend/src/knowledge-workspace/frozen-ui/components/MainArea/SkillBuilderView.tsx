import React, { useState } from 'react';
import { ArrowLeft, CheckCircle2, ChevronRight, Play, Save, Send, Database, Globe, Server, BookOpen, Search, CheckSquare, FileJson, Link as LinkIcon } from 'lucide-react';
import { connectionStore, resourceStore } from '../../lib/store';
import { cn } from '../../lib/utils';
import { createRequestContext } from '../../../production/ports';
import { bootstrapWorkspace, getWorkspaceAdapter } from '../../../production/store';

export default function SkillBuilderView({ searchParams, setSearchParams, showToast }: any) {
  const rawAdapter = searchParams.get('adapter') || 'web_api';
  const adapter = rawAdapter === 'web_discovery' ? 'web_api' : rawAdapter;
  const connections = connectionStore.getState();
  const [selectedConnection, setSelectedConnection] = useState('');
  const [step, setStep] = useState(1);
  const steps = ['选择输入', '发现/解析', '编辑 Manifest', '测试', '保存版本', '发布'];
  
  const [candidateEndpoints, setCandidateEndpoints] = useState<Array<{id: string; path: string; method: string; selected: boolean}>>([]);

  const [mdlCode, setMdlCode] = useState('model DynamicTable {\n  primary_key id\n  dimension category : string\n}');
  const [manifest, setManifest] = useState('{\n  "name": "New Skill",\n  "version": "1.0.0"\n}');
  const [prompt, setPrompt] = useState('');
  const [draft, setDraft] = useState<any>(null);
  const [operation, setOperation] = useState<any>(null);
  const [artifact, setArtifact] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const runAuthoring = async () => {
    if (!prompt.trim()) {
      setError('请输入真实需求，服务端 Agent 将基于当前 Source/Golden 上下文生成草稿。');
      return false;
    }
    setBusy(true);
    setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.start',
        payload: {
          prompt: prompt.trim(),
          resourceRefs: resourceStore.getState()
            .filter((resource: any) =>
              typeof (resource.goldenRevisionId ?? resource.golden_revision_id) === 'string' &&
              typeof (resource.assetId ?? resource.asset_id) === 'string')
            .map((resource: any) => ({
              kind: 'golden_asset',
              object_id: String(resource.assetId ?? resource.asset_id),
              revision: String(resource.goldenRevisionId ?? resource.golden_revision_id),
              scope: resource.space === 'team' ? 'team' : 'personal',
            })),
          scope: 'personal',
          requestedKind: adapter === 'semantic'
            ? 'semantic'
            : adapter === 'mcp_custom' || adapter === 'web_api'
            ? 'analysis'
            : 'knowledge',
          displayName: prompt.trim().slice(0, 80),
        },
      }, createRequestContext());
      const result = response.result ?? {};
      if (!response.accepted || !result.draft) throw new Error(String(result.error?.message ?? 'Agent 未返回 SkillDraft。'));
      setDraft(result.draft);
      setOperation(result.operation ?? null);
      setManifest(JSON.stringify(result.draft.manifest ?? {}, null, 2));
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Agent authoring 失败。');
      return false;
    } finally {
      setBusy(false);
    }
  };

  const executeAuthoring = async () => {
    if (!draft?.draft_id) {
      setError('缺少服务端 SkillDraft，不能执行。');
      return false;
    }
    setBusy(true);
    setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.execute',
        payload: { draftId: draft.draft_id, revision: draft.revision },
      }, createRequestContext());
      const result = response.result ?? {};
      if (!response.accepted || (result.status && !['succeeded', 'ready_for_execution'].includes(String(result.status)))) {
        throw new Error(String(result.error?.message ?? 'Runner 未确认执行成功。'));
      }
      setOperation(result.operation ?? operation);
      setDraft(result.draft ?? draft);
      setArtifact(result.operation?.artifactResult ?? result.operation?.artifact_result ?? null);
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Runner execution 失败。');
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleNext = async () => {
    if (step === 1 && !(await runAuthoring())) return;
    if (step === 4 && !(await executeAuthoring())) return;
    setStep(s => Math.min(6, s + 1));
  };
  const handlePrev = () => setStep(s => Math.max(1, s - 1));
  const handleClose = () => {
    const p = new URLSearchParams(searchParams);
    p.set('file', 'welcome');
    p.delete('adapter');
    setSearchParams(p);
  };

  const handlePublish = async (space: 'personal' | 'team') => {
    if (!draft?.draft_id) { setError('缺少服务端 SkillDraft，不能发布。'); return; }
    setBusy(true); setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'publication.publish',
        payload: { draftId: draft.draft_id, revision: draft.revision, semver: '0.1.0' },
      }, createRequestContext());
      const result = response.result ?? {};
      if (!response.accepted || result.status !== 'succeeded') throw new Error(String(result.error?.message ?? '评测门禁未通过，Skill 未发布。'));
      showToast?.(`Skill 已由服务端发布至 ${space === 'team' ? '团队' : '个人'}空间。`);
    const p = new URLSearchParams(searchParams);
    p.set('file', draft.draft_id);
    p.delete('adapter');
    setSearchParams(p);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '发布失败。');
    } finally { setBusy(false); }
  };

  const renderStepContent = () => {
    switch (step) {
      case 1:
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4">
            <h3 className="font-bold text-slate-800 text-lg">描述真实需求 (Adapter: {adapter})</h3>
            <textarea value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="例如：基于当前 MCP CPU 数据生成利用率趋势 Dashboard，并解释变化原因。" className="w-full min-h-28 px-4 py-3 rounded-lg border border-slate-300 text-sm outline-none focus:border-blue-500" />
            <div className="bg-slate-50 border border-slate-200 p-5 rounded-xl">
              {adapter === 'web_api' && <input type="text" defaultValue={rawAdapter === 'web_discovery' ? 'https://example.com/api' : ''} placeholder="输入网页/API 文档 URL..." className="w-full px-4 py-3 rounded-lg border border-slate-300 text-sm outline-none focus:border-blue-500" />}
              {adapter === 'semantic' && (
                <select value={selectedConnection} onChange={e=>setSelectedConnection(e.target.value)} className="w-full px-4 py-3 rounded-lg border border-slate-300 text-sm outline-none focus:border-blue-500">
                  <option value="">选择已有数据库连接...</option>
                  {connections.map((c:any) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              )}
              {adapter === 'mcp_custom' && <input type="text" placeholder="配置 MCP Endpoint..." className="w-full px-4 py-3 rounded-lg border border-slate-300 text-sm outline-none focus:border-blue-500" />}
              {adapter === 'knowledge_tool' && <select className="w-full px-4 py-3 rounded-lg border border-slate-300 text-sm outline-none focus:border-blue-500"><option>选择知识库来源...</option><option>本地上传或飞书</option></select>}
            </div>
          </div>
        );
      case 2:
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 h-full flex flex-col">
            <h3 className="font-bold text-slate-800 text-lg">发现与解析任务完成</h3>
            {adapter === 'web_api' && (
              <div className="flex-1 border border-slate-200 rounded-xl overflow-hidden shadow-sm">
                <table className="w-full text-sm text-left whitespace-nowrap bg-white">
                  <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                    <tr><th className="px-4 py-3 w-12 text-center">勾选</th><th className="px-4 py-3">Method</th><th className="px-4 py-3">Path</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {candidateEndpoints.map(e => (
                      <tr key={e.id} className="hover:bg-blue-50 cursor-pointer" onClick={() => setCandidateEndpoints(prev => prev.map(p => p.id === e.id ? {...p, selected: !p.selected} : p))}>
                        <td className="px-4 py-3 text-center"><input type="checkbox" checked={e.selected} readOnly className="rounded text-blue-600"/></td>
                        <td className="px-4 py-3 font-mono font-bold text-blue-700">{e.method}</td>
                        <td className="px-4 py-3 font-mono text-slate-700">{e.path}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {adapter === 'semantic' && (
               <div className="flex-1 bg-[#0d1117] p-4 rounded-xl text-slate-300 font-mono text-sm whitespace-pre-wrap"><textarea value={mdlCode} onChange={e=>setMdlCode(e.target.value)} className="w-full h-full bg-transparent outline-none resize-none custom-scrollbar" /></div>
            )}
            {(adapter === 'mcp_custom' || adapter === 'knowledge_tool') && (
               <div className="flex-1 bg-white border border-slate-200 rounded-xl flex items-center justify-center text-slate-500">{draft ? `Agent 已返回 ${draft.plan?.nodes?.length ?? 0} 个计划节点与真实上下文。` : '等待 Agent 基于服务端上下文返回候选。'}</div>
            )}
          </div>
        );
      case 3:
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 h-full flex flex-col">
            <h3 className="font-bold text-slate-800 text-lg">统一编辑 Manifest</h3>
            <div className="flex-1 bg-[#0d1117] p-4 rounded-xl text-green-400 font-mono text-sm"><textarea value={manifest} onChange={e=>setManifest(e.target.value)} className="w-full h-full bg-transparent outline-none resize-none custom-scrollbar" /></div>
          </div>
        );
      case 4:
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 h-full flex flex-col items-center justify-center">
            <Play size={48} className="text-blue-500 mb-4" />
            <h3 className="font-bold text-slate-800 text-lg mb-2">测试控制台就绪</h3>
            <button onClick={() => void executeAuthoring()} disabled={busy} className="bg-blue-600 text-white px-6 py-2.5 rounded-xl font-bold shadow-sm outline-none hover:bg-blue-700 disabled:opacity-50">{busy ? '执行中…' : '由 Runner 执行真实产物'}</button>
          </div>
        );
      case 5:
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 h-full flex flex-col items-center justify-center">
            <Save size={48} className="text-green-500 mb-4" />
            <h3 className="font-bold text-slate-800 text-lg mb-2">保存通用 Skill 版本</h3>
            <p className="text-slate-500 text-sm">服务端 Draft revision：{draft?.revision ?? '—'}；trace：{operation?.trace_id ?? '—'}</p>
            {artifact && (
              <p className="mt-3 max-w-xl break-all rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800">
                Dashboard artifact revision：{artifact.revisionId ?? artifact.revision_id ?? '—'}
                {' · '}HTML digest：{artifact.htmlDigest ?? artifact.html_digest ?? '—'}
              </p>
            )}
          </div>
        );
      case 6:
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 h-full flex flex-col items-center justify-center">
            <Globe size={48} className="text-purple-500 mb-4" />
            <h3 className="font-bold text-slate-800 text-lg mb-4">发布目标</h3>
            <div className="flex space-x-4">
              <button onClick={() => void handlePublish('personal')} disabled={busy} className="px-6 py-3 border border-blue-200 bg-blue-50 text-blue-700 rounded-xl font-bold shadow-sm hover:bg-blue-100 outline-none disabled:opacity-50">保存为个人草稿</button>
              <button onClick={() => void handlePublish('team')} disabled={busy} className="px-6 py-3 bg-blue-600 text-white rounded-xl font-bold shadow-sm hover:bg-blue-700 outline-none disabled:opacity-50">评测通过后发布到团队</button>
            </div>
          </div>
        );
      default: return null;
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 relative animate-in fade-in duration-300 z-50">
      <div className="h-16 px-6 border-b border-slate-200 flex items-center bg-white shrink-0 shadow-sm">
        <button onClick={handleClose} className="p-2 hover:bg-slate-100 rounded-lg text-slate-500 mr-4 outline-none"><ArrowLeft size={18} /></button>
        <h2 className="font-bold text-slate-800 text-lg tracking-tight">通用 Skill Builder <span className="ml-2 text-xs font-mono bg-slate-100 px-2 py-1 rounded text-slate-500">{adapter}</span></h2>
      </div>
      
      <div className="flex flex-col md:flex-row flex-1 overflow-hidden min-w-0">
        <div className="w-full md:w-[240px] bg-white border-r border-slate-200 p-6 shrink-0 flex flex-row md:flex-col gap-4 overflow-x-auto custom-scrollbar shadow-sm z-10">
          {steps.map((s, i) => (
            <div key={s} className={cn("flex items-center text-sm font-bold", step === i + 1 ? "text-blue-600" : step > i + 1 ? "text-green-500" : "text-slate-400")}>
              <div className={cn("w-6 h-6 rounded-full flex items-center justify-center mr-3 shrink-0", step === i + 1 ? "bg-blue-100" : step > i + 1 ? "bg-green-100" : "bg-slate-100")}>{step > i + 1 ? <CheckCircle2 size={12}/> : i + 1}</div>
              <span className="whitespace-nowrap">{s}</span>
            </div>
          ))}
        </div>
        <div className="flex-1 bg-white p-8 overflow-y-auto flex flex-col h-full custom-scrollbar">
          <div className="flex-1 bg-slate-50 border border-slate-200 rounded-2xl p-8 shadow-inner overflow-hidden">
            {error && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
            {renderStepContent()}
          </div>
          <div className="flex justify-between mt-6 pt-4 shrink-0">
            <button onClick={handlePrev} disabled={step === 1} className="px-6 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-xl text-sm font-bold shadow-sm disabled:opacity-50 outline-none">上一步</button>
            {step < 6 ? (
              <button onClick={() => void handleNext()} disabled={busy} className="px-6 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-bold shadow-sm hover:bg-blue-700 flex items-center outline-none disabled:opacity-50">{busy ? '服务端处理中…' : '下一步'} <ChevronRight size={16} className="ml-1"/></button>
            ) : (
              <button disabled className="px-6 py-2.5 bg-green-600 text-white rounded-xl text-sm font-bold shadow-sm opacity-50 flex items-center outline-none"><CheckCircle2 size={16} className="mr-1"/> 待发布</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
