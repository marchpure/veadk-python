import React, { useState, useEffect } from 'react';
import { X, AlertTriangle, Send, BadgeCheck, Clock } from 'lucide-react';

import { resourceStore } from '../../lib/store';

export default function PublishModal({ onClose, onConfirm, isTeam }: { onClose: () => void, onConfirm: () => void, isTeam?: boolean }) {
  const [selectedDir, setSelectedDir] = useState('t_sales');
  const [permission, setPermission] = useState('read');

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const p = new URLSearchParams(window.location.search);
  const currentId = p.get('file');
  const currentResource = resourceStore.getState().find((r:any) => r.id === currentId || r.resourceId === currentId);
  const resourceName = currentResource ? currentResource.name : "销售总览";

  return (
    <div 
      className="fixed inset-0 bg-slate-900/40 z-[100] flex items-center justify-center p-4 backdrop-blur-sm"
      onClick={(e) => { if(e.target === e.currentTarget) onClose(); }}
      role="dialog" aria-modal="true" aria-labelledby="publish-modal-title"
    >
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden transform transition-all">
        <div className="flex justify-between items-center p-5 border-b border-slate-100">
          <h2 id="publish-modal-title" className="text-lg font-semibold text-slate-900">发布到团队工作区</h2>
          <button onClick={onClose} aria-label="关闭" title="关闭" className="p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded transition-colors"><X size={20} /></button>
        </div>
        <div className="p-6">
          <p className="text-sm text-slate-700 mb-5">
            确定要将 <span className="font-medium text-slate-900">“{resourceName}”</span> 发布到团队工作区吗？
          </p>

          <div className="space-y-4 mb-6">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1.5">目标团队目录</label>
              <select value={selectedDir} onChange={e=>setSelectedDir(e.target.value)} className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 outline-none focus:border-blue-500">
                <option value="t_sales">销售分析目录</option>
                <option value="t_docs">知识文档</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1.5">团队成员权限</label>
              <select value={permission} onChange={e=>setPermission(e.target.value)} className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 outline-none focus:border-blue-500">
                <option value="read">仅可查看</option>
                <option value="comment">可查看与评论</option>
                <option value="reuse">可复用为个人草稿</option>
              </select>
            </div>
          </div>

          {currentResource?.type !== 'document' && currentResource?.artifactType !== 'document' && (
            <div className="border border-slate-200 rounded-xl p-4 mb-5 bg-slate-50">
              <div className="flex justify-between items-center mb-3">
                <h3 className="text-sm font-semibold text-slate-800">发布门禁评测</h3>
                <div className="flex items-center text-green-600 font-bold bg-green-100 px-2 py-0.5 rounded text-sm">
                  <BadgeCheck size={16} className="mr-1" /> 88 分
                </div>
              </div>
              <div className="grid grid-cols-2 gap-y-2 text-xs text-slate-600">
                <div className="flex items-center"><span className="w-2 h-2 rounded-full bg-green-500 mr-2"></span> 数据正确性通过</div>
                <div className="flex items-center"><span className="w-2 h-2 rounded-full bg-green-500 mr-2"></span> 安全扫描通过</div>
                <div className="flex items-center"><span className="w-2 h-2 rounded-full bg-amber-500 mr-2"></span> 2 项未解决风险</div>
                <div className="flex items-center text-slate-400"><Clock size={12} className="mr-1" /> 快照: 刚刚</div>
              </div>
            </div>
          )}

          <div className="bg-amber-50 border border-amber-200/60 rounded-xl p-4 flex items-start mb-6">
            <AlertTriangle size={18} className="text-amber-600 mr-3 shrink-0 mt-0.5" />
            <div className="text-xs text-amber-800 leading-relaxed">
              发布后，团队成员将能查看并复用该版本的产物。<br/>
              <span className="font-semibold block mt-1">注意：您的个人草稿仍会保留且可继续编辑，团队版本一经发布不可直接修改。</span>
            </div>
          </div>
          
          <div className="flex justify-end space-x-3">
            <button onClick={onClose} className="px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-sm font-medium transition-colors">取消</button>
            <button onClick={onConfirm} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors shadow-sm flex items-center">
              确认发布 <Send size={14} className="ml-1.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}