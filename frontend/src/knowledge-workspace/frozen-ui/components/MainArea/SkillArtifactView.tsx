import React, { useState } from 'react';
import ArtifactHeader from './ArtifactHeader';
import { Play, Code, Fingerprint, History, Users, Database } from 'lucide-react';
import { resourceStore } from '../../lib/store';
import { cn } from '../../lib/utils';

export default function SkillArtifactView({ fileId, searchParams, setSearchParams, showToast }: any) {
  const resource = resourceStore.getState().find((r:any) => r.id === fileId);
  const [activeTab, setActiveTab] = useState('overview');

  const tabs = [
    { id: 'overview', label: '资源概览 (Overview)' },
    { id: 'manifest', label: 'Manifest (Schema/Actions)' },
    { id: 'test', label: '测试控制台 (Console)' },
    { id: 'lineage', label: '血缘 (Lineage)' }
  ];

  return (
    <div className="flex flex-col h-full bg-slate-50/50 w-full min-w-0 p-4 md:p-8 overflow-y-auto custom-scrollbar">
      <div className="max-w-6xl mx-auto w-full space-y-6">
        <ArtifactHeader 
          title={resource?.name || '通用 Skill'} 
          typeLabel="Skill Component" 
          isTeam={resource?.space==='team'} 
          version={resource?.version||'V1.0'} 
          searchParams={searchParams} 
          setSearchParams={setSearchParams} 
          showToast={showToast} 
        />
        
        <div className="flex space-x-6 border-b border-slate-200 mt-2 mb-6 overflow-x-auto custom-scrollbar">
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)} className={cn("pb-3 text-sm font-bold border-b-2 whitespace-nowrap outline-none", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}>
              {tab.label}
            </button>
          ))}
        </div>

        <div className="bg-white border border-slate-200 rounded-[12px] overflow-hidden min-h-[500px] flex flex-col">
          {activeTab === 'overview' && (
            <div className="p-8 flex-1 animate-in fade-in">
              <div className="flex items-center mb-6">
                <div className="w-12 h-12 bg-blue-100 text-blue-700 rounded-xl flex items-center justify-center mr-4 shadow-sm"><Code size={24}/></div>
                <div>
                  <h3 className="font-bold text-slate-900 text-lg">Skill 统一底座 (Kind: {resource?.subtype})</h3>
                  <p className="text-sm text-slate-500">通过统一 manifest 驱动，提供标准化调度与调用接口，不绑定任何单一业务场景。</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-6">
                <div className="bg-slate-50 p-5 rounded-xl border border-slate-100"><div className="text-xs font-bold text-slate-400 mb-2 uppercase">所有者</div><div className="font-medium text-slate-800">{resource?.owner || 'haoxingjun'}</div></div>
                <div className="bg-slate-50 p-5 rounded-xl border border-slate-100"><div className="text-xs font-bold text-slate-400 mb-2 uppercase">发布空间</div><div className="font-medium text-slate-800">{resource?.space === 'team' ? 'Team Publication' : 'Personal Draft'}</div></div>
              </div>
            </div>
          )}
          
          {activeTab === 'manifest' && (
            <div className="p-6 flex-1 bg-[#0d1117] animate-in fade-in">
              <div className="text-green-400 font-mono text-sm whitespace-pre-wrap leading-relaxed">
{`{
  "kind": "${resource?.subtype}",
  "version": "${resource?.version || '1.0'}",
  "actions": [
    { "name": "execute", "description": "Trigger the unified skill process" }
  ],
  "schema": {
    "type": "object",
    "properties": {
      "input": { "type": "string" }
    }
  }
}`}
              </div>
            </div>
          )}

          {activeTab === 'test' && (
            <div className="p-8 flex-1 flex flex-col items-center justify-center bg-slate-50/50 animate-in fade-in">
              <Play size={48} className="text-blue-500 mb-6" />
              <h3 className="font-bold text-slate-800 mb-2 text-lg">等待服务端调用接口</h3>
              <p className="text-sm text-slate-500 mb-6">独立调用测试需要 Invocation seam 返回 operation/result；当前不会创建本地成功态。</p>
              <button disabled className="bg-slate-300 text-white px-8 py-3 rounded-xl font-bold shadow-md outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-70">
                等待 Invocation
              </button>
            </div>
          )}

          {activeTab === 'lineage' && (
            <div className="p-8 flex-1 animate-in fade-in">
              <h3 className="font-bold text-slate-800 mb-6 flex items-center"><Fingerprint size={20} className="mr-2 text-blue-600"/> 数据血缘追溯</h3>
              <div className="bg-slate-50 p-6 rounded-xl border border-slate-200">
                <div className="text-sm font-medium text-slate-700 mb-4 flex items-center"><Database size={16} className="mr-2 text-slate-400"/> 上游依赖源 ID</div>
                <div className="flex gap-2 flex-wrap">
                  {resource?.lineage?.sourceIds?.length ? resource.lineage.sourceIds.map(id => (
                    <span key={id} className="bg-white border border-slate-300 px-3 py-1.5 rounded-lg text-xs font-mono text-slate-600 shadow-sm">{id}</span>
                  )) : (
                    <span className="bg-white border border-slate-300 px-3 py-1.5 rounded-lg text-xs text-slate-500 shadow-sm">无特定上游记录</span>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
