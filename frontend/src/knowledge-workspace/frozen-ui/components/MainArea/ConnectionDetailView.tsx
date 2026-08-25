import React from 'react';
import ArtifactHeader from './ArtifactHeader';
import { Database, FileSpreadsheet, Server, Cloud, Webhook, ShieldCheck, Activity, Key, Fingerprint, Plus, Play, Info } from 'lucide-react';
import { resourceStore, connectionStore, getRegistry } from '../../lib/store';

export default function ConnectionDetailView({ fileId, searchParams, setSearchParams, showToast }: any) {
  const resource = resourceStore.getState().find((r:any) => r.id === fileId || r.resourceId === fileId);
  const connStoreItem = connectionStore.getState().find((c:any) => c.id === fileId);
  
  const item = (resource || connStoreItem || {}) as Record<string, any>;

  const name = item?.displayName || item?.name || 'Data Connection';
  const subtype = item?.connectorKey || item?.subtype || item?.type || 'unknown';
  
  const registry = getRegistry();
  const def = registry.find(r => r.connectorKey === subtype);
  const category = def?.category || 'db';

  const isDB = category === 'db';
  const isOffice = category === 'office';
  const isFile = category === 'file';
  const isAPI = category === 'api';

  return (
    <div className="p-4 md:p-8 max-w-[1000px] mx-auto pb-24 w-full animate-in fade-in relative">
      <ArtifactHeader 
        title={name} 
        typeLabel="Data Connection"
        isTeam={item?.isTeam || item?.space === 'team'} 
        version={item?.version || '等待 revision'} 
        fromTeamVersion={item?.fromTeamVersion}
        editTarget={null} 
        onElementClick={() => {}} 
        searchParams={searchParams}
        setSearchParams={setSearchParams}
        showToast={showToast}
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6">
        <div className="md:col-span-2 space-y-6">
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col">
            <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 flex items-center justify-between shrink-0">
               <h3 className="font-semibold text-slate-800 flex items-center">
                 {isOffice ? <FileSpreadsheet size={16} className="mr-2 text-blue-600"/> : isAPI ? <Webhook size={16} className="mr-2 text-blue-600"/> : <Database size={16} className="mr-2 text-blue-600"/>}
                 连接参数摘要
               </h3>
               <span className="text-xs text-slate-500 bg-white px-2 py-1 rounded border border-slate-200 shadow-sm">{def?.name || subtype}</span>
            </div>
            <div className="p-5">
              <div className="grid grid-cols-2 gap-4 text-sm text-slate-600">
                {!isFile && !isOffice && item?.endpointRef && (
                  <>
                    <div className="flex flex-col"><span className="text-xs font-bold text-slate-400 mb-1">Host / Endpoint</span><span className="font-mono text-slate-800">{item.endpointRef}</span></div>
                    <div className="flex flex-col"><span className="text-xs font-bold text-slate-400 mb-1">Port</span><span className="font-mono text-slate-800">{item.port || '—'}</span></div>
                  </>
                )}
                {isOffice && (
                  <div className="flex flex-col col-span-2"><span className="text-xs font-bold text-slate-400 mb-1">Scope (选择范围)</span><span className="font-medium text-slate-800">指定文件夹及其子文档，保持权限继承。</span></div>
                )}
	                <div className="flex flex-col"><span className="text-xs font-bold text-slate-400 mb-1">Auth Type</span><span className="font-medium text-slate-800">{item?.authType || (isOffice ? 'OAuth 2.0' : '等待服务端返回')}</span></div>
                {!isOffice && <div className="flex flex-col"><span className="text-xs font-bold text-slate-400 mb-1">Credential</span><span className="font-mono text-slate-800">********</span></div>}
              </div>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col">
            <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 flex items-center justify-between shrink-0">
               <h3 className="font-semibold text-slate-800 flex items-center">
                 <ShieldCheck size={16} className="mr-2 text-blue-600"/>
                 已发现的 {isDB ? 'Schema' : '内容范围'}
               </h3>
            </div>
            <div className="p-5">
		               {isDB && Array.isArray(item.discoveredResources) && item.discoveredResources.length > 0 ? (
	                 <div className="space-y-4">
	                   <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
	                     <div className="text-xs font-bold text-slate-500 mb-2">服务端发现资源</div>
	                     <div className="flex gap-2 flex-wrap">
	                       {item.discoveredResources.map((resourceItem: any) => (
	                         <span key={resourceItem.id || resourceItem.name} className="bg-white border border-slate-200 px-2.5 py-1 rounded text-xs font-medium text-slate-700 shadow-sm">{resourceItem.name || resourceItem.id}</span>
	                       ))}
	                     </div>
	                   </div>
	                 </div>
               ) : (
                 <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 flex items-start text-sm text-slate-700">
                   <Info size={16} className="mr-2 text-blue-600 shrink-0 mt-0.5" />
	                   已探测到 {Array.isArray(item.discoveredResources) ? item.discoveredResources.length : 0} 个有效工具/资源，均可通过分析助手直接查询或加入上下文。
                 </div>
               )}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-[12px] p-5">
            <h3 className="font-semibold text-slate-800 mb-4 flex items-center"><Activity size={16} className="mr-2 text-blue-600"/> 运行状态</h3>
            <div className="space-y-4 text-sm text-slate-600">
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">同步方式</span>
                <span className="font-medium text-slate-800">实时 / 增量</span>
              </div>
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">最近同步</span>
	                <span className="font-medium text-slate-800">{item?.lastSuccessAt || item?.updatedAt || item?.createdAt || '—'}</span>
              </div>
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">同步历史记录</span>
	                <span className="font-medium text-slate-800">{item?.syncRunCount ? `共 ${item.syncRunCount} 次执行` : '等待服务端返回'}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">连接状态</span>
	                <span className="font-medium text-slate-700 bg-slate-50 px-2 py-0.5 rounded border border-slate-200">{item?.status || '等待服务端返回'}</span>
              </div>
            </div>
          </div>
          
          <div className="space-y-3">
	             <button disabled className="w-full bg-slate-300 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm outline-none flex items-center justify-center disabled:cursor-not-allowed disabled:opacity-70">
	               <Play size={16} className="mr-2" /> 同步等待服务端命令
             </button>
             <button onClick={() => showToast?.('进入编辑配置向导...')} className="w-full bg-white border border-slate-300 text-slate-700 px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors shadow-sm outline-none flex items-center justify-center">
               编辑配置
             </button>
             <button onClick={() => {
                const p = new URLSearchParams(searchParams);
                p.set('file', 'skill_builder');
                p.set('adapter', 'semantic');
                setSearchParams(p);
             }} className="w-full bg-purple-50 border border-purple-200 text-purple-700 px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-purple-100 transition-colors shadow-sm outline-none flex items-center justify-center">
               创建 Semantic Skill
             </button>
          </div>
        </div>
      </div>
    </div>
  );
}
