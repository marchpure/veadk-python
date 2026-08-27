import React, { useState, useEffect } from 'react';
import { Database, Plus, Search, Filter, MoreHorizontal, ShieldAlert, CheckCircle2, FileSpreadsheet, Webhook, Globe, Server, ChevronDown, ChevronRight, Activity, Clock, User } from 'lucide-react';
import { cn } from '../../lib/utils';
import { connectionStore, resourceStore, useStore } from '../../lib/store';

export default function DataOverviewView({ setSearchParams, searchParams }: any) {
  const connections = useStore(connectionStore);
  const resources = useStore(resourceStore);

  const handleAddData = () => {
    const p = new URLSearchParams(searchParams);
    p.set('file', 'add_data'); p.set('step', '1');
    setSearchParams(p);
  };

  const handleSelectTable = (fileId: string) => {
    const p = new URLSearchParams(searchParams);
    p.set('file', fileId);
    if (p.get('explore_pending') === 'true') { p.delete('explore_pending'); p.set('explore', 'true'); }
    setSearchParams(p);
  };

  const [expandedInstance, setExpandedInstance] = useState<string | null>(searchParams.get('new_conn') || 'conn_mysql');

  useEffect(() => {
    if (searchParams.get('new_conn')) {
      const p = new URLSearchParams(searchParams);
      p.delete('new_conn');
      setSearchParams(p);
    }
  }, [searchParams, setSearchParams]);

  const handleAddContext = (item: any, e: React.MouseEvent) => {
    e.stopPropagation();
    window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
  };

  const getIconForType = (type: string) => {
    if (type === 'rest_api') return Webhook;
    if (type === 'web_discovery' || type === 'web_skill') return Globe;
    if (type === 'mcp_custom' || type === 'mcp_remote') return Server;
    if (type === 'excel' || type === 'Local' || type === 'csv') return FileSpreadsheet;
    return Database;
  };
  
  const getIconColors = (type: string) => {
    if (type === 'rest_api') return 'bg-emerald-50 text-emerald-600';
    if (type === 'web_discovery' || type === 'web_skill') return 'bg-blue-50 text-blue-600';
    if (type === 'mcp_custom' || type === 'mcp_remote') return 'bg-purple-50 text-purple-600';
    if (type === 'excel' || type === 'Local' || type === 'csv') return 'bg-green-50 text-green-600';
    return 'bg-blue-50 text-blue-600';
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-8 w-full animate-in fade-in">
      <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 space-y-4 md:space-y-0">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 mb-2">数据连接</h1>
          <p className="text-slate-500 text-sm">统一管理所有的数据库连接与文件源实例</p>
        </div>
        <button onClick={handleAddData} className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm outline-none focus:ring-2 focus:ring-blue-500">
          <Plus size={16} /><span>添加数据连接</span>
        </button>
      </div>

      <div className="flex items-center space-x-4 mb-6">
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input type="text" placeholder="搜索连接实例或表名..." className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-lg text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-shadow bg-white" />
        </div>
        <button className="flex items-center space-x-2 px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors bg-white outline-none focus:ring-2 focus:ring-slate-300">
          <Filter size={16} /> <span>筛选</span>
        </button>
      </div>

      <div className="bg-white border border-slate-200 rounded-[12px] overflow-hidden flex flex-col shadow-sm">
        <table className="w-full text-sm text-left min-w-[700px]">
          <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
            <tr>
              <th className="px-4 md:px-6 py-3 font-medium w-2/5">数据连接</th>
              <th className="px-4 md:px-6 py-3 font-medium hidden sm:table-cell">连接器类型</th>
              <th className="px-4 md:px-6 py-3 font-medium hidden sm:table-cell">状态与同步</th>
              <th className="px-4 md:px-6 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {connections.map((conn: any) => {
              const Icon = getIconForType(conn.connectorKey);
              const colorClass = getIconColors(conn.connectorKey);
              const isExpanded = expandedInstance === conn.id;

              return (
                <React.Fragment key={conn.id}>
                  <tr 
                    className="hover:bg-slate-50/50 transition-colors cursor-pointer group outline-none bg-white"
                    onClick={() => setExpandedInstance(isExpanded ? null : conn.id)}
                  >
                    <td className="px-4 md:px-6 py-4">
                      <div className="flex items-center">
                        <div className="mr-2 text-slate-400 shrink-0">{isExpanded ? <ChevronDown size={16}/> : <ChevronRight size={16}/>}</div>
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center mr-3 shrink-0 ${colorClass}`}><Icon size={16} /></div>
                        <div className="min-w-0">
                          <div className="font-semibold text-slate-900 group-hover:text-blue-600 transition-colors truncate">{conn.displayName}</div>
                          <div className="text-[11px] text-slate-500 mt-0.5 truncate flex items-center space-x-2">
                            <span className="flex items-center"><User size={10} className="mr-1"/>{conn.owner || 'haoxingjun'}</span>
                            <span>层级: Schema {'>'} Table {'>'} Field</span>
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 md:px-6 py-4 text-slate-600 hidden sm:table-cell">{conn.connectorKey}</td>
                    <td className="px-4 md:px-6 py-4 hidden sm:table-cell">
                      <div className="flex flex-col space-y-1">
                        <span className={`flex items-center px-2 py-0.5 rounded text-[11px] font-medium border w-fit ${conn.status === 'ready' ? 'text-green-700 bg-green-50 border-green-200' : 'text-amber-700 bg-amber-50 border-amber-200'}`}><CheckCircle2 size={10} className="mr-1" /> {conn.status === 'ready' ? 'ready' : conn.status}</span>
                        <span className="text-[10px] text-slate-400 flex items-center"><Activity size={10} className="mr-1"/> {conn.discoveredResources.length} tools/resources · {conn.syncMode || '未设置同步'}</span>
                      </div>
                    </td>
                    <td className="px-4 md:px-6 py-4 text-right">
                      <button
                        onClick={(e) => {
                          const golden = resources.find((resource: any) =>
                            conn.goldenRevisionIds.includes(resource.goldenRevisionId),
                          );
                          const contextRef = golden?.assetId && golden?.goldenRevisionId
                            ? {
                              kind: 'golden_asset',
                              objectId: String(golden.assetId),
                              revision: String(golden.goldenRevisionId),
                              scope: golden.space === 'team' ? 'team' : 'personal',
                            }
                            : undefined;
                          handleAddContext({
                            ...conn,
                            ...(golden ? {
                              id: golden.id,
                              resourceId: golden.id,
                              assetId: golden.assetId,
                              goldenRevisionId: golden.goldenRevisionId,
                            } : {}),
                            identity: `${conn.id}:${golden?.id ?? ''}`,
                            name: conn.displayName,
                            type: 'connection',
                            ...(contextRef ? { contextRef } : {}),
                          }, e);
                        }}
                        className="text-blue-600 hover:text-blue-800 bg-white border border-blue-200 px-3 py-1.5 rounded-md font-medium text-xs mr-2 transition-colors outline-none focus:ring-2 focus:ring-blue-500 shadow-sm"
                      >
                        作为上下文加入
                      </button>
                    </td>
                  </tr>
                  
                  {isExpanded && conn.discoveredResources.map((schema: any) => (
                    <tr key={`${conn.id}_${schema.id || schema.name}`} className="bg-slate-50/50 border-t-0">
                      <td colSpan={4} className="px-4 md:px-6 py-3">
                        <div className="pl-11 pr-2 space-y-3 relative before:absolute before:left-6 before:top-0 before:bottom-4 before:w-px before:bg-slate-200">
                          <div className="text-[10px] font-bold text-slate-500 flex items-center mt-2 relative uppercase tracking-wider">
                            <span className="absolute -left-6 w-3 h-px bg-slate-200"></span> RESOURCE: <span className="text-slate-700 ml-1.5 bg-white px-2 py-0.5 rounded border border-slate-200 shadow-sm">{schema.name || schema.displayName || schema.id}</span>
                          </div>
                          
                          {(schema.tables || []).map((table: any) => (
                            <div 
                              key={table.id}
                              className={cn("bg-white border rounded-[12px] p-3.5 flex flex-col justify-center transition-all cursor-pointer group outline-none relative ml-4", table.perm ? "border-slate-200 hover:border-blue-300 focus:ring-2 focus:ring-blue-400" : "border-slate-100 opacity-60 hover:opacity-100")}
                              onClick={() => { if(table.perm) handleSelectTable(table.id); }}
                            >
                              <span className="absolute -left-5 w-3 h-px bg-slate-200"></span>
                              <div className="flex items-center justify-between min-w-0">
                                <div className="flex items-center min-w-0">
                                  <div className={cn("p-2 rounded-lg mr-3 shrink-0", table.perm ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-500")}><FileSpreadsheet size={16}/></div>
                                  <div className="min-w-0">
                                    <div className="text-[13px] font-bold text-slate-800 group-hover:text-blue-600 truncate flex items-center">
                                      {table.name}
                                      {table.freshness && <span className="ml-2 text-[9px] font-normal text-slate-400 flex items-center bg-slate-50 px-1 rounded"><Clock size={8} className="mr-0.5"/>{table.freshness}</span>}
                                    </div>
                                    <div className="text-[11px] text-slate-500 mt-0.5 flex items-center space-x-2">
                                      <span className="bg-slate-100 px-1.5 rounded text-[10px]">Table</span>
                                      <span>{table.rows} 行</span>
                                      {table.fields && <span>{table.fields.length} 个字段</span>}
                                    </div>
                                  </div>
                                </div>
                                {table.perm ? (
                                  <button onClick={(e) => handleAddContext({ id: table.id, name: table.name, type: 'table', parentId: `${conn.id}_${schema.name}` }, e)} className="text-[11px] bg-blue-600 text-white font-medium px-2.5 py-1.5 rounded-lg hover:bg-blue-700 outline-none focus:ring-2 focus:ring-blue-500 shadow-sm transition-colors opacity-0 group-hover:opacity-100 flex items-center shrink-0">
                                    <Plus size={12} className="mr-1"/> 加入上下文
                                  </button>
                                ) : (
                                  <span className="text-[11px] text-red-700 bg-red-50 border border-red-200 px-2 py-1 rounded font-medium flex items-center shrink-0"><ShieldAlert size={12} className="mr-1"/> 无权限</span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
