import React, { useState, useEffect } from 'react';
import { X, Save, Settings, Users, Clock } from 'lucide-react';
import { actionLoopStore } from '../../lib/actionLoopStore';

export default function ActionPolicyModal({ onClose, showToast, searchParams }: { onClose: () => void, showToast: any, searchParams?: any }) {
  const policies = actionLoopStore.getState().policies;
  const policyId = searchParams?.get('policy_id');
  const policy = policyId ? policies.find(p => p.id === policyId) : policies[0];

  const [form, setForm] = useState({
    metric: policy?.metric || '招聘需求',
    dimensionScope: policy?.dimensionScope || '国家=越南；岗位=销售',
    threshold: policy?.threshold || '周环比 > 30%',
    severity: policy?.severity || 'high',
    agentStrategy: policy?.agentStrategy || '',
    autoCreateTodo: policy?.autoCreateTodo || false,
    defaultOwner: policy?.defaultOwner || 'Linh Nguyen',
    slaHours: policy?.slaHours || 24,
    reviewer: policy?.reviewer || '张总监 (VP of HR)'
  });

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const handleSave = () => {
    if (policy) {
      actionLoopStore.setState(prev => {
        const newPolicies = prev.policies.map(p => p.id === policy.id ? { ...p, ...form } : p);
        return { ...prev, policies: newPolicies };
      });
    }
    showToast?.('行动策略 (ActionPolicy) 保存成功');
    onClose();
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
              <input type="text" value={form.metric} onChange={e=>setForm({...form, metric: e.target.value})} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5">维度范围 (Scope)</label>
              <input type="text" value={form.dimensionScope} onChange={e=>setForm({...form, dimensionScope: e.target.value})} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-1.5">触发阈值 (Threshold)</label>
              <input type="text" value={form.threshold} onChange={e=>setForm({...form, threshold: e.target.value})} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
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
        </div>

        <div className="p-4 border-t border-slate-100 bg-slate-50 flex justify-end space-x-3 shrink-0">
          <button onClick={onClose} className="px-5 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 outline-none shadow-sm transition-colors">取消</button>
          <button onClick={handleSave} className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm flex items-center outline-none transition-colors"><Save size={16} className="mr-1.5"/> 保存配置</button>
        </div>
      </div>
    </div>
  );
}