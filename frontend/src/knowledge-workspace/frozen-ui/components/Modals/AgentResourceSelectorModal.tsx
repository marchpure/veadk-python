import React, { useEffect, useState } from 'react';
import { X, Search, ToyBrick, CheckCircle2, FileText, LayoutDashboard, Globe } from 'lucide-react';
import { agentPublicationStore, useStore } from '../../lib/store';
import { createRequestContext } from '../../../production/ports';
import { getWorkspaceAdapter } from '../../../production/store';

export default function AgentResourceSelectorModal({ onClose }: { onClose: () => void }) {
  const publishedAgents = useStore(agentPublicationStore);
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const getIcon = (type: string) => {
    if (type === 'dashboard') return <LayoutDashboard size={16} className="text-purple-600" />;
    if (type === 'knowledge_base') return <FileText size={16} className="text-emerald-600" />;
    return <Globe size={16} className="text-blue-600" />;
  };

  const filtered = publishedAgents.filter((a:any) => a.name.toLowerCase().includes(query.toLowerCase()));

  const invokeSelected = async () => {
    const item: any = publishedAgents.find((value: any) => value.id === selectedId);
    if (!item) { setError('请选择服务端已发布的 Skill。'); return; }
    const skillVersionId = item.skillVersionId || item.id;
    setBusy(true); setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'invocation.start',
        payload: {
          skillVersionId,
          skillViewRevisionId: item.skillViewRevisionId || item.skillViewRef || '',
          inputRef: {
            uri: 'inline://agent-selector-input',
            kind: 'inline',
            sha256: '0'.repeat(64),
            mediaType: 'application/json',
          },
          callerId: 'browser-not-authoritative',
        },
      }, createRequestContext());
      const result = response.result ?? {};
      if (!response.accepted || result.status !== 'succeeded') {
        throw new Error(String(result.error?.message ?? '服务端 invocation 未成功。'));
      }
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '调用失败。');
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 z-[100] flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in" onClick={(e) => { if(e.target===e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-xl overflow-hidden animate-in zoom-in-95 border border-slate-200">
        <div className="flex justify-between items-center p-5 border-b border-slate-100 bg-slate-50 shrink-0">
          <h2 className="text-lg font-bold text-slate-900 flex items-center"><ToyBrick size={20} className="mr-2 text-blue-600"/> Agent 资源选择器 (测试)</h2>
          <button onClick={onClose} className="p-1 hover:bg-slate-200 rounded-lg text-slate-400 transition-colors outline-none"><X size={20}/></button>
        </div>
        
        <div className="p-4 border-b border-slate-100">
           <div className="relative">
             <Search size={16} className="absolute left-3 top-2.5 text-slate-400" />
             <input type="text" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索已发布为 Agent 的资源名称..." className="w-full pl-9 pr-4 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:border-blue-500 bg-white transition-colors shadow-sm" />
           </div>
        </div>

        <div className="p-4 h-80 overflow-y-auto custom-scrollbar bg-slate-50/50">
           {filtered.length === 0 ? (
             <div className="flex flex-col items-center justify-center h-full text-slate-400">
               <ToyBrick size={32} className="mb-3 opacity-30" />
               <div className="text-sm font-medium text-slate-500">{query ? '未找到匹配资源' : '暂无已发布的资源'}</div>
             </div>
           ) : (
             <div className="space-y-3">
               {filtered.map((item:any) => (
                 <label key={item.id} className="flex items-start p-4 bg-white border border-slate-200 rounded-xl cursor-pointer hover:border-blue-400 hover:shadow-md shadow-sm transition-all group">
                   <input type="radio" name="agent_resource" checked={selectedId === item.id} onChange={() => setSelectedId(item.id)} className="mt-1 mr-4 rounded-full text-blue-600 focus:ring-blue-500 cursor-pointer w-4 h-4" />
                   <div className="flex-1 min-w-0">
                     <div className="flex items-center justify-between mb-1">
                       <div className="font-bold text-slate-900 flex items-center">{getIcon(item.artifactType)}<span className="ml-2 truncate max-w-[200px]">{item.name}</span></div>
                       <span className="text-[10px] bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded font-medium flex items-center"><CheckCircle2 size={12} className="mr-1"/>已发布</span>
                     </div>
                     <div className="flex items-center space-x-2 text-[10px] text-slate-500 font-mono mt-2">
                       <span className="bg-slate-50 border border-slate-100 px-1.5 py-0.5 rounded">ID: {item.id}</span>
                       <span className="bg-slate-50 border border-slate-100 px-1.5 py-0.5 rounded">版本: {item.version}</span>
                       <span className="bg-slate-50 border border-slate-100 px-1.5 py-0.5 rounded">范围: {item.visibility === 'team' ? '团队公开' : '个人'}</span>
                     </div>
                   </div>
                 </label>
               ))}
             </div>
           )}
        </div>
        {error && <div role="alert" className="px-4 py-2 text-sm text-red-700 bg-red-50 border-t border-red-200">{error}</div>}

        <div className="p-4 border-t border-slate-100 bg-white flex justify-end space-x-3 shrink-0">
          <button onClick={onClose} className="px-5 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 outline-none shadow-sm transition-colors">取消</button>
          <button onClick={() => void invokeSelected()} disabled={busy} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm flex items-center outline-none transition-colors disabled:opacity-50">
            {busy ? '服务端调用中…' : '调用 Skill'}
          </button>
        </div>
      </div>
    </div>
  );
}
