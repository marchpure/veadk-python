import React, { useState, useEffect } from 'react';
import { X, Save, Settings, Users, Clock, AlertTriangle, Loader2 } from 'lucide-react';
import { actionLoopStore } from '../../lib/actionLoopStore';
import { commandErrorMessage, runTypedCommand } from '../../lib/qualityPublicationClient';

export default function ActionPolicyModal({ onClose, searchParams }: any) {
  const policies = actionLoopStore.getState().policies;
  const policyId = searchParams?.get('policy_id');
  const policy = policyId ? policies.find(p => p.id === policyId) : policies[0];

  const [form, setForm] = useState({
    metric: policy?.metric || '',
    dimensionScope: policy?.dimensionScope || '',
    threshold: policy?.threshold || '',
    severity: policy?.severity || 'high',
    agentStrategy: policy?.agentStrategy || '',
    autoCreateTodo: policy?.autoCreateTodo || false,
    defaultOwner: policy?.defaultOwner || '',
    slaHours: policy?.slaHours || '',
    reviewer: policy?.reviewer || ''
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const handleSave = async () => {
    setBusy(true);
    setError('');
    try {
      if (!form.metric.trim() || !form.threshold.trim()) {
        setError('请先填写服务端可识别的指标和阈值。');
        return;
      }
      const response = await runTypedCommand({
        command: 'action.update',
        payload: { actionId: `action-policy.upsert:${policy?.id || 'new'}:${form.metric}:${form.threshold}` },
      });
      if (!response.accepted) throw new Error(commandErrorMessage(response));
      setError('action.update 只记录审计意图；Action/Review/Decision 结构化证据链需要 MAIN 暴露持久化契约。');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'ActionPolicy 保存失败。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 z-[100] flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg overflow-hidden animate-in zoom-in-95">
        <div className="flex justify-between items-center p-5 border-b border-slate-100 bg-slate-50 shrink-0">
          <h2 className="text-lg font-bold text-slate-900 flex items-center">
            <Settings size={20} className="mr-2 text-blue-600" />
            行动策略配置 (ActionPolicy)
          </h2>
          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded-lg transition-colors outline-none">
            <X size={20} />
          </button>
        </div>
        
        <div className="p-6 space-y-5 bg-white max-h-[70vh] overflow-y-auto custom-scrollbar">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5">指标 (Metric)</label>
              <input type="text" value={form.metric} onChange={e=>setForm({...form, metric: e.target.value})} placeholder="选择或输入服务端指标 ID" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5">维度范围 (Scope)</label>
              <input type="text" value={form.dimensionScope} onChange={e=>setForm({...form, dimensionScope: e.target.value})} placeholder="可选，使用服务端维度表达式" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5">触发阈值 (Threshold)</label>
              <input type="text" value={form.threshold} onChange={e=>setForm({...form, threshold: e.target.value})} placeholder="例如 comparator + value，由服务端校验" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5">严重级别 (Severity)</label>
              <select value={form.severity} onChange={e=>setForm({...form, severity: e.target.value})} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none bg-white focus:border-blue-500 shadow-sm">
                <option value="low">低</option>
                <option value="medium">中</option>
                <option value="high">高</option>
                <option value="critical">严重</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-bold text-slate-800 mb-1.5">触发后 Agent 建议动作 (Strategy)</label>
            <textarea value={form.agentStrategy} onChange={e=>setForm({...form, agentStrategy: e.target.value})} rows={3} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm resize-none"></textarea>
          </div>

          <div className="flex items-center space-x-2 text-sm font-bold text-slate-800">
            <input type="checkbox" checked={form.autoCreateTodo} onChange={e=>setForm({...form, autoCreateTodo: e.target.checked})} className="rounded text-blue-600 focus:ring-blue-500 w-4 h-4 cursor-pointer" />
            <label className="cursor-pointer" onClick={() => setForm({...form, autoCreateTodo: !form.autoCreateTodo})}>异常发生时自动创建待办 (Auto-create Todo)</label>
          </div>

          <div className="grid grid-cols-2 gap-4 border-t border-slate-100 pt-5">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5 flex items-center"><Users size={14} className="mr-1 text-slate-500"/>默认负责人</label>
              <input type="text" value={form.defaultOwner} onChange={e=>setForm({...form, defaultOwner: e.target.value})} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5 flex items-center"><Clock size={14} className="mr-1 text-slate-500"/>SLA时效 (小时)</label>
              <input type="number" value={form.slaHours} onChange={e=>setForm({...form, slaHours: Number(e.target.value)})} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
            </div>
          </div>
          
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-1.5 flex items-center"><Users size={14} className="mr-1 text-slate-500"/>Review 验收人</label>
            <input type="text" value={form.reviewer} onChange={e=>setForm({...form, reviewer: e.target.value})} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            <AlertTriangle size={14} className="mr-1 inline" />
            Action/Review/Decision 结构化证据链需要 MAIN 扩展共享契约；当前仅可发送 action.update 审计意图。
          </div>
          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        </div>

        <div className="p-4 border-t border-slate-100 bg-slate-50 flex justify-end space-x-3 shrink-0">
          <button onClick={onClose} className="px-5 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 outline-none shadow-sm transition-colors">取消</button>
          <button onClick={() => void handleSave()} disabled={busy} className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm flex items-center outline-none transition-colors disabled:opacity-50">{busy ? <Loader2 size={16} className="mr-1.5 animate-spin"/> : <Save size={16} className="mr-1.5"/>} 保存配置</button>
        </div>
      </div>
    </div>
  );
}
