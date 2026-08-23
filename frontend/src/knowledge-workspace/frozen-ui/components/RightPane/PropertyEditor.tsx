import React, { useState, useEffect } from 'react';
import { X, Sparkles, Wand2, ArrowRight, MessageSquare } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function PropertyEditor({ editTarget, searchParams, setSearchParams, showToast }: any) {
  const chartTitle = searchParams.get('chartTitle') || '按周销售与利润趋势';
  const chartType = searchParams.get('chartType') || 'line';

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        const p = new URLSearchParams(searchParams);
        p.delete('edit');
        setSearchParams(p);
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [searchParams, setSearchParams]);

  const closeEditor = () => {
    const p = new URLSearchParams(searchParams);
    p.delete('edit');
    setSearchParams(p);
  };

  const handleTitleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const p = new URLSearchParams(searchParams);
    p.set('chartTitle', e.target.value);
    setSearchParams(p);
  };

  const handleTypeChange = (type: string) => {
    const p = new URLSearchParams(searchParams);
    p.set('chartType', type);
    setSearchParams(p);
  };

  const applyChanges = () => {
    showToast('修改已成功应用');
    closeEditor();
  };

  const cancelChanges = () => {
    const p = new URLSearchParams(searchParams);
    p.delete('chartTitle');
    p.delete('chartType');
    p.delete('edit');
    setSearchParams(p);
  };

  const renderContent = () => {
    if (editTarget === 'chart_trend') {
      return (
        <div className="flex flex-col h-full">
          <div className="space-y-6">
            <div>
              <h4 className="text-sm font-medium text-slate-800 mb-2">图表标题</h4>
              <input type="text" value={chartTitle} onChange={handleTitleChange} className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-shadow" />
            </div>
            <div>
              <h4 className="text-sm font-medium text-slate-800 mb-2">图表类型</h4>
              <div className="grid grid-cols-2 gap-2">
                <button 
                  className={cn("border py-2 rounded-lg text-sm font-medium transition-colors outline-none focus:ring-2 focus:ring-blue-300", chartType === 'line' ? "border-blue-600 bg-blue-50 text-blue-700 ring-1 ring-blue-500" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50")}
                  onClick={() => handleTypeChange('line')}
                >
                  折线图
                </button>
                <button 
                  className={cn("border py-2 rounded-lg text-sm font-medium transition-colors outline-none focus:ring-2 focus:ring-blue-300", chartType === 'bar' ? "border-blue-600 bg-blue-50 text-blue-700 ring-1 ring-blue-500" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50")}
                  onClick={() => handleTypeChange('bar')}
                >
                  柱状图
                </button>
              </div>
            </div>
            <div className="pt-6 border-t border-slate-200 mt-6">
            <div className="flex space-x-2 mb-4">
              <button className="flex-1 py-1.5 bg-purple-50 text-purple-700 rounded text-xs font-medium hover:bg-purple-100 transition-colors outline-none focus:ring-2 focus:ring-purple-300" onClick={() => {
                const item = { id: editTarget, name: editTarget, type: 'element', artifactId: searchParams.get('file') };
                window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
                const p = new URLSearchParams(searchParams);
                p.delete('edit');
                p.set('action', 'ai_edit_element');
                p.set('target_elements', editTarget);
                setSearchParams(p);
              }}><Wand2 size={14} className="inline mr-1 -mt-0.5"/>用 AI 修改</button>
              <button className="flex-1 py-1.5 bg-blue-50 text-blue-700 rounded text-xs font-medium hover:bg-blue-100 transition-colors outline-none focus:ring-2 focus:ring-blue-300" onClick={() => {
                const p = new URLSearchParams(searchParams);
                p.delete('edit');
                p.set('comment_target', editTarget);
                setSearchParams(p);
              }}><MessageSquare size={14} className="inline mr-1 -mt-0.5"/>评论</button>
            </div>
            
            <h4 className="text-sm font-medium text-slate-800 mb-3 flex items-center">
              <Sparkles size={14} className="text-purple-600 mr-1.5" />
              AI 辅助修改
            </h4>
            <textarea 
              className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 resize-none h-24 mb-3 transition-shadow"
              placeholder="例如：将销售额和利润分开两个Y轴显示..."
            ></textarea>
              <button className="w-full bg-purple-600 text-white hover:bg-purple-700 py-2 rounded-lg text-sm font-medium transition-colors flex justify-center items-center shadow-sm outline-none focus:ring-2 focus:ring-purple-300">
                <Wand2 size={14} className="mr-1.5" /> 预览修改
              </button>
            </div>
          </div>
          
          <div className="mt-auto pt-6 flex space-x-3 pb-2">
            <button className="flex-1 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors outline-none focus:ring-2 focus:ring-slate-200" onClick={cancelChanges}>取消</button>
            <button className="flex-1 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm outline-none focus:ring-2 focus:ring-blue-300" onClick={applyChanges}>应用修改</button>
          </div>
        </div>
      );
    }
    
    // Generic fallback for other elements
    return (
      <div className="flex flex-col items-center justify-center text-center text-slate-500 py-12 px-4">
        <div className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center mb-4">
          <Sparkles size={20} className="text-slate-400" />
        </div>
        <h4 className="text-sm font-medium text-slate-700 mb-2">已选中元素 ({editTarget})</h4>
        <p className="text-xs leading-relaxed mb-6">您可以在此快速编辑该元素的属性，或使用 AI 助手进行智能调整。</p>
        
        <div className="flex space-x-2 w-full mb-6">
          <button className="flex-1 py-2 bg-purple-50 text-purple-700 rounded-lg text-xs font-medium hover:bg-purple-100 transition-colors outline-none focus:ring-2 focus:ring-purple-300" onClick={() => {
            const item = { id: editTarget, name: editTarget, type: 'element', artifactId: searchParams.get('file') };
            window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
            const p = new URLSearchParams(searchParams);
            p.delete('edit');
            p.set('action', 'ai_edit_element');
            p.set('target_elements', editTarget);
            setSearchParams(p);
          }}><Wand2 size={14} className="inline mr-1 -mt-0.5"/>用 AI 修改</button>
          <button className="flex-1 py-2 bg-blue-50 text-blue-700 rounded-lg text-xs font-medium hover:bg-blue-100 transition-colors outline-none focus:ring-2 focus:ring-blue-300" onClick={() => {
            const p = new URLSearchParams(searchParams);
            p.delete('edit');
            p.set('comment_target', editTarget);
            setSearchParams(p);
          }}><MessageSquare size={14} className="inline mr-1 -mt-0.5"/>评论</button>
        </div>

        <button className="text-sm text-blue-600 font-medium hover:text-blue-700 flex items-center outline-none focus:ring-2 focus:ring-blue-300 rounded px-2 py-1" onClick={closeEditor}>
          完成编辑 <ArrowRight size={14} className="ml-1" />
        </button>
      </div>
    );
  };

  return (
    <div 
      className="h-full min-h-0 flex flex-col overflow-hidden bg-white relative"
      role="dialog"
      aria-modal="true"
      aria-labelledby="property-editor-title"
    >
      <div className="shrink-0 flex items-center justify-between p-4 border-b border-slate-200 bg-slate-50/50">
        <h3 id="property-editor-title" className="font-medium text-slate-800">属性编辑</h3>
        <button onClick={closeEditor} aria-label="关闭" title="关闭" className="p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded transition-colors outline-none">
          <X size={18} />
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-5">
        {renderContent()}
      </div>
    </div>
  );
}