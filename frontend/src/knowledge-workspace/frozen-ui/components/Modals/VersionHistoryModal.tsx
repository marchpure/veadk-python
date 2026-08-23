import React, { useEffect } from 'react';
import { X, Clock, ArrowRightLeft, FileText, RotateCcw } from 'lucide-react';

export default function VersionHistoryModal({ onClose, searchParams }: any) {
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const evalApplied = searchParams?.get('eval_applied') === 'true' || searchParams?.get('version') === 'v2.2';
  const versions = [
    ...(evalApplied ? [{ id: 'V2.2', time: '刚刚', author: '您', desc: '应用了评测建议，优化了图表配色对比度', isCurrent: true, type: 'draft' }] : []),
    { id: 'V2.1', time: '10分钟前', author: '您', desc: '修改了标题并调整筛选器', isCurrent: !evalApplied, type: 'draft' },
    { id: 'v2.0', time: '昨天 15:30', author: '您', desc: '发布到团队', type: 'published' },
    { id: 'v1.0', time: '2023-10-24', author: '系统', desc: 'AI自动生成初版', type: 'auto' },
  ];

  return (
    <div 
      className="absolute inset-0 bg-slate-900/20 z-40 backdrop-blur-[1px] flex justify-end"
      onClick={(e) => { if(e.target === e.currentTarget) onClose(); }}
    >
      <div 
        className="w-96 h-full bg-white shadow-[-10px_0_30px_-10px_rgba(0,0,0,0.1)] flex flex-col border-l border-slate-200 animate-in slide-in-from-right-full duration-300"
        role="dialog" aria-modal="true" aria-labelledby="version-modal-title"
      >
        <div className="flex justify-between items-center p-5 border-b border-slate-100 bg-slate-50/50">
          <h2 id="version-modal-title" className="text-lg font-semibold text-slate-900">来源与版本历史</h2>
          <button onClick={onClose} aria-label="关闭" title="关闭" className="p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded transition-colors"><X size={20} /></button>
        </div>
      
      <div className="p-6 border-b border-slate-100">
        <h3 className="text-sm font-medium text-slate-800 mb-3 flex items-center"><FileText size={16} className="mr-2 text-slate-500" /> 数据来源</h3>
        <div className="bg-blue-50 rounded-lg p-3 text-sm text-blue-900 border border-blue-100 flex justify-between items-center">
          <span className="font-medium">销售数据集</span>
          <span className="text-xs text-blue-600">上次同步: 2小时前</span>
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-6">
        <h3 className="text-sm font-medium text-slate-800 mb-5 flex items-center"><Clock size={16} className="mr-2 text-slate-500" /> 版本记录</h3>
        
        <div className="relative border-l-2 border-slate-100 ml-3 space-y-6">
          {versions.map((v, i) => (
            <div key={v.id} className="relative pl-6">
              <div className={`absolute -left-[9px] top-1.5 w-4 h-4 rounded-full border-[3px] border-white ${v.isCurrent ? 'bg-blue-500 shadow-[0_0_0_2px_rgba(59,130,246,0.2)]' : 'bg-slate-300'}`}></div>
              <div className={`bg-white border rounded-xl p-4 transition-shadow hover:shadow-sm ${v.isCurrent ? 'border-blue-200 ring-1 ring-blue-50' : 'border-slate-200'}`}>
                <div className="flex justify-between items-start mb-1.5">
                  <div className="font-medium text-slate-800 text-sm flex items-center">
                    {v.id} 
                    {v.isCurrent && <span className="ml-2 bg-blue-100 text-blue-700 text-[10px] px-1.5 py-0.5 rounded border border-blue-200">当前草稿</span>}
                    {v.type === 'published' && <span className="ml-2 bg-green-100 text-green-700 text-[10px] px-1.5 py-0.5 rounded border border-green-200">已发布</span>}
                  </div>
                  <div className="text-xs text-slate-400 font-medium">{v.time}</div>
                </div>
                <div className="text-xs text-slate-600 mb-3 leading-relaxed">{v.desc}</div>
                {!v.isCurrent && (
                  <div className="flex items-center space-x-3 border-t border-slate-100 pt-3">
                    <button className="text-xs text-slate-600 font-medium hover:text-blue-600 flex items-center transition-colors">
                      <ArrowRightLeft size={12} className="mr-1" /> 查看差异
                    </button>
                    <div className="w-px h-3 bg-slate-200"></div>
                    <button className="text-xs text-slate-600 font-medium hover:text-blue-600 flex items-center transition-colors">
                      <RotateCcw size={12} className="mr-1" /> 恢复为新版本
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
    </div>
  );
}