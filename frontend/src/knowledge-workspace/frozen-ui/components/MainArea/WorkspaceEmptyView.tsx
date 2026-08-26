import React, { useState } from 'react';
import { FileText, Plus, AlertCircle } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function WorkspaceEmptyView({ searchParams, setSearchParams }: any) {
  const [chatInput, setChatInput] = useState('');
  const [showGuide, setShowGuide] = useState(false);

  const handleOpenTemplates = () => {
    const p = new URLSearchParams(searchParams);
    p.set('file', 'skill_builder');
    p.set('source', 'template_library');
    setSearchParams(p);
  };

  const handleAddData = () => {
    const p = new URLSearchParams(searchParams);
    p.set('file', 'add_data');
    p.set('step', '1');
    setSearchParams(p);
  };

  const handleChat = () => {
    if (!chatInput.trim()) return;
    setShowGuide(true);
    const el = document.getElementById('a11y-live-region');
    if (el) el.textContent = "需要先连接数据、上传知识或选择模板。";
  };

  return (
    <div className="h-full w-full flex flex-col bg-white overflow-y-auto custom-scrollbar">
      <div className="flex-1 flex flex-col items-center py-20 px-6 max-w-4xl mx-auto w-full">
        <h1 className="text-3xl font-bold text-slate-900 mb-3 tracking-tight">开始第一次分析</h1>
        <p className="text-slate-500 mb-12 text-[15px] text-center max-w-lg">轻松接入您的业务数据，通过对话式探索，快速生成专业的分析看板与图表。</p>
        
        {/* 3 Steps */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12 w-full">
          <div className="flex flex-col items-center text-center">
            <div className="w-10 h-10 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-sm mb-4">1</div>
            <h3 className="font-semibold text-slate-800 text-sm mb-2">数据连接</h3>
            <p className="text-xs text-slate-500 leading-relaxed max-w-[200px]">接入数据库、API 或上传本地文件</p>
          </div>
          <div className="flex flex-col items-center text-center relative">
            <div className="hidden md:block absolute top-5 -left-1/2 w-full h-px bg-slate-200"></div>
            <div className="w-10 h-10 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-sm mb-4 relative z-10">2</div>
            <h3 className="font-semibold text-slate-800 text-sm mb-2">添加上下文</h3>
            <p className="text-xs text-slate-500 leading-relaxed max-w-[200px]">加入数据、产物、知识等资源，或直接对话</p>
          </div>
          <div className="flex flex-col items-center text-center relative">
            <div className="hidden md:block absolute top-5 -left-1/2 w-full h-px bg-slate-200"></div>
            <div className="w-10 h-10 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-sm mb-4 relative z-10">3</div>
            <h3 className="font-semibold text-slate-800 text-sm mb-2">生成并沉淀资产</h3>
            <p className="text-xs text-slate-500 leading-relaxed max-w-[200px]">自动生成分析产物并发布协作</p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-4 mb-16">
          <button 
            onClick={handleAddData}
            className="flex items-center justify-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            <Plus size={16} /> <span>连接数据</span>
          </button>
          <button 
            onClick={handleOpenTemplates}
            className="flex items-center justify-center space-x-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 px-6 py-2.5 rounded-lg text-sm font-medium transition-colors outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-2"
          >
            <FileText size={16} className="text-slate-400" /> <span>选择模板 / spec.md</span>
          </button>
        </div>

        {/* Compact Chat Input */}
        <div className="w-full relative max-w-2xl">
          <div className={cn("bg-white border rounded-[12px] overflow-hidden transition-colors focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500 relative shadow-sm", showGuide ? "border-amber-300 ring-1 ring-amber-300" : "border-slate-200")}>
            <div className="flex items-center p-1.5">
              <input 
                type="text"
                placeholder="描述要构建的 Skill，例如：根据已选资源生成周报..."
                value={chatInput}
                onChange={e => { setChatInput(e.target.value); setShowGuide(false); }}
                onKeyDown={e => { if (e.key === 'Enter') handleChat(); }}
                className="w-full px-4 py-2.5 text-sm outline-none bg-transparent"
              />
              <button 
                onClick={handleChat}
                className="bg-blue-600 text-white px-4 py-2.5 rounded-lg text-xs font-medium hover:bg-blue-700 transition-colors outline-none focus:ring-2 focus:ring-blue-500 mr-1 shrink-0 flex items-center shadow-sm"
              >
                发送
              </button>
            </div>
            
            {showGuide && (
              <div className="bg-amber-50 px-4 py-3 border-t border-amber-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-in fade-in">
                <div className="flex items-center text-sm font-medium text-amber-800">
                  <AlertCircle size={16} className="mr-2 text-amber-600 shrink-0" /> 需要先连接数据或提供上下文
                </div>
                <div className="flex gap-2">
                  <button onClick={handleAddData} className="px-3 py-1.5 bg-white border border-amber-200 text-amber-800 rounded-md text-xs font-medium hover:bg-amber-100 transition-colors outline-none focus:ring-2 focus:ring-amber-500 whitespace-nowrap">打开连接器</button>
                  <button onClick={handleOpenTemplates} className="px-3 py-1.5 bg-amber-600 text-white rounded-md text-xs font-medium hover:bg-amber-700 transition-colors outline-none focus:ring-2 focus:ring-amber-500 whitespace-nowrap">选择模板</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
