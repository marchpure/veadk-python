import React, { useState, useEffect } from 'react';
import { X, Send, ToyBrick, ShieldCheck } from 'lucide-react';
import { resourceStore, agentPublicationStore, getResourceDescriptor } from '../../lib/store';
import { useSearchParams } from 'react-router-dom';
import { createRequestContext } from '../../../production/ports';
import { bootstrapWorkspace, getWorkspaceAdapter } from '../../../production/store';

export default function PublishAgentModal({ onClose, showToast, fileId }: { onClose: () => void, showToast: any, fileId: string }) {
  const [searchParams] = useSearchParams();
  const allResources = resourceStore.getState();
  const descriptor = getResourceDescriptor(fileId, searchParams, allResources);
  
  const resourceName = descriptor?.name as string;
  const version = descriptor?.version as string;
  const identity = descriptor?.identity as string;
  const artifactType = descriptor?.artifactType as string;

  const publications = agentPublicationStore.getState();
  const existing = publications.find((a:any) => a.resourceId === identity);

  const [visibility, setVisibility] = useState(existing?.visibility || 'team');

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const handleConfirm = async () => {
    if (!descriptor) return;
    if (descriptor.resourceKind !== 'skill_draft') {
      setError('只有服务端 SkillDraft 可进入真实 publication.publish。');
      return;
    }
    setBusy(true); setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'publication.publish',
        payload: {
          draftId: identity,
          revision: Number(descriptor.revision ?? 1),
          semver: String(version || '0.1.0').replace(/^V/i, ''),
        },
      }, createRequestContext());
      const result = response.result ?? {};
      if (!response.accepted || result.status !== 'succeeded') {
        throw new Error(String(result.error?.message ?? 'Evaluation/PolicyGate 未通过，发布被拒绝。'));
      }
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      showToast?.('服务端已确认发布。');
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '发布失败。');
    } finally { setBusy(false); }
  };

  const handleCancelPublish = () => {
    if (!descriptor) return;
    setError('取消发布必须由服务端撤销命令确认；当前未执行本地删除。');
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 z-[100] flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in" onClick={(e) => { if(e.target===e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden animate-in zoom-in-95 border border-slate-200">
        <div className="flex justify-between items-center p-5 border-b border-slate-100 bg-slate-50 shrink-0">
          <h2 className="text-lg font-bold text-slate-900 flex items-center"><ToyBrick size={20} className="mr-2 text-blue-600"/> 发布到 Agent</h2>
          <button onClick={onClose} className="p-1 hover:bg-slate-200 rounded-lg text-slate-400 transition-colors outline-none"><X size={20}/></button>
        </div>
        
        <div className="p-6">
          <div className="text-sm text-slate-700 mb-5 leading-relaxed bg-slate-50 p-4 rounded-xl border border-slate-100">
            <span className="font-bold text-slate-900 block mb-1">“{resourceName}” ({version})</span>
            发布后，其他平台的 Agent 可搜索并选择此资源。
          </div>

          <div className="space-y-4 mb-2">
            <div>
              <label className="block text-xs font-bold text-slate-800 mb-1.5">可见范围</label>
              <select value={visibility} onChange={e=>setVisibility(e.target.value)} className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500 shadow-sm bg-white font-medium">
                <option value="personal">仅个人可用</option>
                <option value="team">团队公开可用</option>
              </select>
            </div>
          </div>
          {error && <div role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        </div>

        <div className="p-4 border-t border-slate-100 bg-slate-50 flex justify-end items-center gap-3">
          {existing && (
            <button onClick={handleCancelPublish} className="text-sm text-red-600 font-bold hover:bg-red-50 px-4 py-2 rounded-lg transition-colors outline-none mr-auto">取消发布</button>
          )}
          {!existing && (
            <button onClick={onClose} className="px-5 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 outline-none shadow-sm transition-colors">取消</button>
          )}
          <button onClick={() => void handleConfirm()} disabled={busy} className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm flex items-center outline-none focus:ring-2 focus:ring-blue-500 transition-colors disabled:opacity-50">
            {existing ? '更新范围' : '确认发布'}
          </button>
        </div>
      </div>
    </div>
  );
}
