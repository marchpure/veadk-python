import React, { useState } from 'react';
import { 
  Database, FileSpreadsheet, Server, Cloud, Search, 
  ArrowLeft, CheckCircle2, Info, Webhook, Loader2, ShieldCheck,
  Check, Save
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { getRegistry, ConnectorDef } from '../../lib/store';
import { createRequestContext } from '../../../production/ports';
import {
  getWorkspaceAdapter,
  mcpProfileStore,
  useStore as useProductionStore,
  bootstrapWorkspace,
} from '../../../production/store';

const getRegistryIcon = (category: string) => {
  if (category === 'office') return FileSpreadsheet;
  if (category === 'file') return FileSpreadsheet;
  if (category === 'api') return Webhook;
  if (category === 'custom') return Server;
  if (category === 'cloud') return Cloud;
  return Database;
};

const categories = [
  { id: 'all', name: '全部连接器' },
  { id: 'office', name: '办公上下文' },
  { id: 'file', name: '文件与对象存储' },
  { id: 'db', name: '数据库与数仓' },
  { id: 'api', name: 'API 与流' },
  { id: 'custom', name: '自定义与扩展' },
];

const WizardForm = ({ sourceObj, showToast, handleClose }: { sourceObj: ConnectorDef, showToast: any, handleClose: any }) => {
  const [wizardStep, setWizardStep] = useState(1);
  const [formData, setFormData] = useState<Record<string, string>>({});
  
  // Custom Connector definition state
  const [customDef, setCustomDef] = useState({ name: '', desc: '', fields: 'endpoint, method' });

  // Execution Job state
  const [jobState, setJobState] = useState<'idle'|'running'|'done'|'fail'>('idle');
  const [jobStepIdx, setJobStepIdx] = useState(0);

  const [finalName, setFinalName] = useState(`${sourceObj.name} 连接`);
  const [space, setSpace] = useState<'personal' | 'team'>('personal');
  const mcpProfiles = useProductionStore(mcpProfileStore);
  const [selectedMcpProfile, setSelectedMcpProfile] = useState('');
  const [operationError, setOperationError] = useState('');

  const handleNext = async () => {
    if (wizardStep === 1) {
      if (sourceObj.connectorKey === 'create_custom') {
        setOperationError('自定义连接器定义必须由服务端注册；当前页面不创建浏览器本地连接器。');
        return;
      }
      if (sourceObj.connectorKey === 'mcp_custom') {
        if (!mcpProfiles.some((item) => item.profileId === selectedMcpProfile)) {
          setOperationError('未选择服务端 MCP profile，无法启动真实 MCP。');
          return;
        }
        setOperationError('');
        setWizardStep(4);
        return;
      }
      if (sourceObj.credentialSchema) {
        setWizardStep(2);
      } else {
        setWizardStep(3);
        startJob();
      }
    } else if (wizardStep === 2) {
      setWizardStep(3);
      startJob();
    } else if (wizardStep === 3) {
      if (jobState === 'done') setWizardStep(4);
    } else if (wizardStep === 4) {
      if (sourceObj.connectorKey === 'mcp_custom') {
        const profile = mcpProfiles.find((item) => item.profileId === selectedMcpProfile);
        if (!profile) {
          setOperationError('未选择服务端 MCP profile，无法启动真实 MCP。');
          return;
        }
        setOperationError('');
        setJobState('running');
        try {
          const created = await getWorkspaceAdapter().command(
            {
              command: 'source-golden.connection.create',
              payload: {
                connectorKey: 'mcp_custom',
                displayName: finalName,
                scope: space,
                configuration: {},
                mcpProfileId: profile.profileId,
                toolAllowlist: profile.toolAllowlist,
              },
            },
            createRequestContext(),
          );
          const result = created.result?.connection;
          const connectionId = result && typeof result === 'object' &&
            typeof (result as Record<string, unknown>).id === 'string'
            ? (result as Record<string, unknown>).id
            : '';
          if (!created.accepted || !connectionId) {
            throw new Error('MCP connection was not accepted by the server.');
          }
          const ingested = await getWorkspaceAdapter().command(
            {
              command: 'source-golden.ingest',
              payload: {
                connectionId,
                recipeOperations: ['trim'],
                toolArguments: {},
              },
            },
            createRequestContext(),
          );
          if (!ingested.accepted) throw new Error('MCP ingest was not accepted by the server.');
          await bootstrapWorkspace();
          setJobState('done');
          showToast?.('真实 MCP 已完成连接、工具发现与 Source/Golden ingest。');
          handleClose();
        } catch (error) {
          setJobState('fail');
          setOperationError(error instanceof Error ? error.message : 'MCP 操作失败。');
        }
        return;
      }
      setJobState('fail');
      setOperationError('该连接器尚未接入 STEP 3 的真实 Source/Golden command，已停止，不创建本地假连接。');
    }
  };

  const startJob = () => {
    setJobState('fail');
    setJobStepIdx(0);
    setOperationError('该连接器的发现流程尚未接入真实服务端执行，不能用定时动画或固定结果代替。');
  };

  const renderField = (key: string, type: string) => {
    if (type === 'file') {
      return (
        <div key={key} className="col-span-2">
          <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wider">{key} 文件</label>
          <div className="border border-dashed border-slate-300 rounded-lg p-6 flex flex-col items-center justify-center hover:bg-slate-50 transition-colors cursor-pointer relative bg-white">
            <input type="file" className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" onChange={() => setFormData(p=>({...p, [key]: 'selected_file.csv'}))} />
            <FileSpreadsheet size={24} className="text-slate-400 mb-2" />
            <span className="text-sm font-medium text-slate-600">{formData[key] ? formData[key] : '点击或拖拽文件上传'}</span>
          </div>
        </div>
      );
    }
    if (type === 'select') {
      return (
        <div key={key}>
          <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wider">{key}</label>
          <select onChange={e=>setFormData(p=>({...p, [key]: e.target.value}))} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:border-blue-500 outline-none bg-white">
            <option>请选择...</option>
            <option>选项 A</option>
            <option>选项 B</option>
          </select>
        </div>
      );
    }
    if (type === 'oauth') {
      return (
        <div key={key} className="col-span-2 flex items-center justify-between bg-white border border-slate-200 p-4 rounded-lg">
          <div className="flex items-center">
            <ShieldCheck size={20} className="text-green-500 mr-3" />
            <div>
              <div className="font-semibold text-slate-800 text-sm">OAuth 授权认证</div>
              <div className="text-xs text-slate-500">此应用请求获取您在该平台的数据读取权限</div>
            </div>
          </div>
          <button onClick={() => setFormData(p=>({...p, [key]: 'authorized'}))} className={cn("px-4 py-1.5 rounded-md text-sm font-medium transition-colors outline-none", formData[key] ? "bg-green-50 text-green-700 border border-green-200" : "bg-blue-600 text-white hover:bg-blue-700")}>
            {formData[key] ? '已授权' : '点击授权'}
          </button>
        </div>
      )
    }
    return (
      <div key={key} className={key.includes('url') || key.includes('endpoint') ? 'col-span-2' : ''}>
        <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wider">{key}</label>
        <input type={type === 'password' ? 'password' : 'text'} placeholder={`Enter ${key}...`} onChange={e=>setFormData(p=>({...p, [key]: e.target.value}))} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:border-blue-500 outline-none bg-white" />
      </div>
    );
  };

  const Icon = getRegistryIcon(sourceObj.category);

  return (
    <div className="p-6 md:p-8 flex flex-col h-full bg-white relative">
      <div className="flex items-center justify-between mb-8 pb-4 border-b border-slate-100 shrink-0">
        <h3 className="text-lg font-bold text-slate-900 flex items-center">
          <div className="w-8 h-8 rounded bg-blue-50 text-blue-600 flex items-center justify-center mr-3"><Icon size={18} /></div>
          {sourceObj.name}
        </h3>
        <div className="flex items-center space-x-1.5">
          {[1, 2, 3, 4].map(s => {
            if (s === 2 && !sourceObj.credentialSchema && sourceObj.connectorKey !== 'create_custom') return null;
            if (s > 1 && sourceObj.connectorKey === 'create_custom') return null;
            return (
              <React.Fragment key={s}>
                <div className={cn("w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-colors", wizardStep === s ? "bg-blue-600 text-white" : wizardStep > s ? "bg-green-500 text-white" : "bg-slate-100 text-slate-400")}>
                  {wizardStep > s ? <Check size={14}/> : s}
                </div>
                {s < 4 && (s !== 1 || sourceObj.connectorKey !== 'create_custom') && <div className={cn("w-6 h-0.5", wizardStep > s ? "bg-green-500" : "bg-slate-100")} />}
              </React.Fragment>
            )
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar px-1">
        {wizardStep === 1 && sourceObj.connectorKey !== 'create_custom' && (
          <div className="animate-in fade-in max-w-2xl mx-auto space-y-6 pt-4">
            <h4 className="text-base font-bold text-slate-800">步骤 1: 选择范围与配置参数</h4>
            <p className="text-sm text-slate-500 mb-6">配置连接所需的基础信息与范围 (Input Schema)。</p>
            {sourceObj.connectorKey === 'mcp_custom' ? (
              <div className="col-span-2 space-y-4">
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">服务端 MCP Profile</label>
                {mcpProfiles.length > 0 ? (
                  <select value={selectedMcpProfile} onChange={(event) => setSelectedMcpProfile(event.target.value)} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm bg-white">
                    <option value="">请选择已注册 profile...</option>
                    {mcpProfiles.map((profile) => (
                      <option key={profile.profileId} value={profile.profileId}>
                        {profile.label} · {profile.transport} · {profile.toolAllowlist.length} tools
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                    服务端未注册可用 MCP profile。此处不会接受 command、args、cwd 或 env。
                  </div>
                )}
              </div>
            ) : sourceObj.inputSchema ? (
              <div className="bg-slate-50 border border-slate-200 p-6 rounded-xl grid grid-cols-2 gap-5">
                {Object.entries(sourceObj.inputSchema).map(([k, v]) => renderField(k, v as string))}
              </div>
            ) : (
              <div className="bg-slate-50 border border-slate-200 p-6 rounded-xl flex items-center text-slate-500 text-sm">该连接器不需要额外输入配置。</div>
            )}
          </div>
        )}

        {wizardStep === 1 && sourceObj.connectorKey === 'create_custom' && (
          <div className="animate-in fade-in max-w-2xl mx-auto space-y-6 pt-4">
            <h4 className="text-base font-bold text-slate-800">新建自定义连接器</h4>
            <p className="text-sm text-slate-500 mb-6">定义您的私有协议或专用系统的请求 Schema，保存后将即时在注册表中生效。</p>
            <div className="bg-slate-50 border border-slate-200 p-6 rounded-xl space-y-5">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wider">连接器名称</label>
                <input type="text" value={customDef.name} onChange={e=>setCustomDef(p=>({...p, name: e.target.value}))} placeholder="例如：公司内网考勤 API" className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:border-blue-500 outline-none bg-white" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wider">功能描述</label>
                <input type="text" value={customDef.desc} onChange={e=>setCustomDef(p=>({...p, desc: e.target.value}))} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:border-blue-500 outline-none bg-white" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1.5 uppercase tracking-wider">自定义配置字段 (Input Schema 逗号分隔)</label>
                <input type="text" value={customDef.fields} onChange={e=>setCustomDef(p=>({...p, fields: e.target.value}))} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:border-blue-500 outline-none bg-white font-mono" />
              </div>
            </div>
            <div className="bg-blue-50 border border-blue-200 p-4 rounded-lg flex items-start text-xs text-blue-800 mt-4">
               <Info size={14} className="mr-2 mt-0.5 shrink-0"/>
               保存后，它将自动具备统一的生命周期与授权框架，可直接在此连接列表中搜索并使用。
            </div>
          </div>
        )}

        {wizardStep === 2 && (
          <div className="animate-in slide-in-from-right-4 max-w-2xl mx-auto space-y-6 pt-4">
            <h4 className="text-base font-bold text-slate-800">步骤 2: 授权与鉴权测试</h4>
            <p className="text-sm text-slate-500 mb-6">提供访问此数据源所需的凭证 (Credential Schema)。</p>
            {sourceObj.credentialSchema ? (
              <div className="bg-slate-50 border border-slate-200 p-6 rounded-xl grid grid-cols-2 gap-5">
                {Object.entries(sourceObj.credentialSchema).map(([k, v]) => renderField(k, v as string))}
              </div>
            ) : null}
          </div>
        )}

        {wizardStep === 3 && (
          <div className="animate-in slide-in-from-right-4 max-w-2xl mx-auto space-y-8 pt-6">
            <div className="text-center">
              <h4 className="text-lg font-bold text-slate-800 mb-2">步骤 3: 验证并预览发现内容</h4>
              <p className="text-sm text-slate-500">正在执行流水线以验证连接并预览可发现的数据资源。</p>
            </div>
            
            <div className="space-y-4 bg-slate-50 border border-slate-200 p-6 rounded-xl shadow-inner">
              {sourceObj.discoveryPipeline.map((stepName: string, idx: number) => {
                const isActive = jobStepIdx === idx && jobState === 'running';
                const isPast = jobStepIdx > idx || jobState === 'done';
                return (
                  <div key={idx} className={cn("flex items-center text-sm font-medium transition-all", isPast ? "text-slate-800" : isActive ? "text-blue-700" : "text-slate-400")}>
                    {isPast ? <CheckCircle2 size={18} className="text-green-500 mr-3"/> : isActive ? <Loader2 size={18} className="animate-spin text-blue-600 mr-3"/> : <div className="w-4 h-4 rounded-full border-2 border-slate-300 mr-3.5 ml-0.5"/>}
                    <span className="flex-1">{stepName}</span>
                  </div>
                );
              })}
            </div>

            {jobState === 'done' && (
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm animate-in slide-in-from-bottom-2">
                <div className="px-4 py-2.5 bg-blue-50 border-b border-blue-100 flex items-center justify-between">
                  <span className="text-xs font-bold text-blue-800">发现的数据内容预览 (首层)</span>
                  <span className="text-[10px] text-blue-600 bg-white px-2 py-0.5 rounded border border-blue-200">仅展示前 3 项</span>
                </div>
                <div className="p-4 space-y-3 bg-white">
                   <div className="flex items-center text-sm"><Database size={14} className="text-slate-400 mr-2"/> <span className="font-medium text-slate-700">Schema / 目录结构发现成功</span></div>
                   <div className="flex items-center text-sm"><Database size={14} className="text-slate-400 mr-2"/> <span className="font-medium text-slate-700">解析了 12 个有效数据表/文档</span></div>
                   <div className="flex items-center text-sm"><Database size={14} className="text-slate-400 mr-2"/> <span className="font-medium text-slate-700">数据类型探断完成，均支持自动同步</span></div>
                </div>
              </div>
            )}
          </div>
        )}

        {wizardStep === 4 && (
          <div className="animate-in slide-in-from-right-4 max-w-xl mx-auto space-y-6 pt-10">
            <h4 className="text-xl font-bold text-slate-800 text-center mb-6">步骤 4: 命名与保存</h4>
            <div className="bg-slate-50 border border-slate-200 p-6 rounded-xl space-y-6">
              <div>
                <label className="block text-sm font-semibold text-slate-800 mb-2">连接命名</label>
                <input type="text" value={finalName} onChange={e=>setFinalName(e.target.value)} className="w-full border border-slate-300 rounded-lg px-4 py-3 text-sm focus:border-blue-500 outline-none bg-white font-medium shadow-sm" />
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-800 mb-3">存入空间</label>
                <div className="grid grid-cols-2 gap-3">
                   <label className={cn("p-3 rounded-lg border text-center cursor-pointer transition-all", space === 'personal' ? "border-blue-500 bg-blue-50 text-blue-700 ring-1 ring-blue-500" : "border-slate-200 bg-white text-slate-600 hover:border-blue-300")}>
                     <input type="radio" className="hidden" checked={space==='personal'} onChange={()=>setSpace('personal')} />
                     <div className="font-bold text-sm">个人工作区</div>
                     <div className="text-[10px] mt-1 opacity-70">仅自己可见并使用</div>
                   </label>
                   <label className={cn("p-3 rounded-lg border text-center cursor-pointer transition-all", space === 'team' ? "border-blue-500 bg-blue-50 text-blue-700 ring-1 ring-blue-500" : "border-slate-200 bg-white text-slate-600 hover:border-blue-300")}>
                     <input type="radio" className="hidden" checked={space==='team'} onChange={()=>setSpace('team')} />
                     <div className="font-bold text-sm">团队共享库</div>
                     <div className="text-[10px] mt-1 opacity-70">团队均可只读使用</div>
                   </label>
                </div>
              </div>
            </div>
          </div>
        )}
        {operationError && (
          <div className="mx-auto mt-4 max-w-2xl rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
            {operationError}
          </div>
        )}
      </div>

      <div className="pt-5 border-t border-slate-100 flex justify-end space-x-3 shrink-0 mt-4">
        {wizardStep > 1 && wizardStep < 3 && (
          <button onClick={() => setWizardStep(s => s - 1)} className="px-5 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors outline-none shadow-sm">上一步</button>
        )}
        {(wizardStep === 1 || wizardStep === 2) && (
          <button onClick={handleNext} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm outline-none focus:ring-2 focus:ring-blue-500">下一步</button>
        )}
        {wizardStep === 3 && (
          <button onClick={handleNext} disabled={jobState !== 'done'} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50">完成配置并命名</button>
        )}
        {wizardStep === 4 && (
          <button onClick={handleNext} className="px-8 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-md outline-none focus:ring-2 focus:ring-blue-500 flex items-center">
            <Save size={16} className="mr-2" /> 保存连接
          </button>
        )}
      </div>
    </div>
  );
};

export default function AddDataView({ searchParams, setSearchParams, showToast }: any) {
  const step = parseInt(searchParams.get('step') || '1', 10);
  const source = searchParams.get('source');
  
  const handleClose = () => {
    const p = new URLSearchParams(window.location.search);
    const origin = searchParams.get('target_space');
    const fromFile = searchParams.get('from_file') || 'welcome';
    p.set('file', fromFile); 
    p.delete('step'); p.delete('source'); p.delete('target_space'); p.delete('from_file'); p.delete('category');
    setSearchParams(p);
    if (origin) {
      const el = document.querySelector(`[data-tree-id="${origin}"]`);
      if (el) (el as HTMLElement).focus();
    }
  };

  const allConnectors = getRegistry();
  const currentSourceObj = source ? allConnectors.find(x => x.connectorKey === source) : null;
  
  const [activeCategory, setActiveCategory] = useState(searchParams.get('category') || 'all');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredSources = allConnectors.filter(c => {
    const matchCat = activeCategory === 'all' || c.category === activeCategory;
    const matchSearch = c.name.toLowerCase().includes(searchQuery.toLowerCase()) || c.desc.toLowerCase().includes(searchQuery.toLowerCase());
    return matchCat && matchSearch;
  });

  return (
    <div className="flex flex-col h-full bg-white w-full absolute inset-0 z-[60] animate-in fade-in duration-200 min-w-0">
      <div className="flex-1 overflow-hidden flex flex-col min-w-0 relative bg-slate-50">
         {step === 1 && !source && (
           <div className="flex flex-col h-full bg-white min-w-0 w-full">
             <div className="h-16 px-4 md:px-6 bg-white border-b border-slate-200 flex items-center justify-between shrink-0 shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] z-10 w-full min-w-0">
               <div className="flex items-center space-x-4 min-w-0">
                 <button onClick={handleClose} className="p-1.5 hover:bg-slate-100 rounded-lg text-slate-500 transition-colors outline-none shrink-0"><ArrowLeft size={18} /></button>
                 <h1 className="text-lg font-bold text-slate-900 tracking-tight truncate">添加连接或上下文</h1>
               </div>
               <div className="w-64 relative hidden md:block">
                 <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                 <input type="text" value={searchQuery} onChange={e=>setSearchQuery(e.target.value)} placeholder="搜索连接器..." className="w-full pl-9 pr-3 py-1.5 bg-slate-100 border-transparent focus:bg-white border focus:border-blue-500 rounded-lg text-sm outline-none transition-colors" />
               </div>
             </div>
             <div className="flex-1 flex overflow-hidden min-w-0">
               <div className="w-[200px] hidden md:block bg-slate-50 border-r border-slate-200 overflow-y-auto custom-scrollbar p-3 shrink-0 space-y-1">
                 {categories.map(cat => (
                   <button 
                     key={cat.id} 
                     onClick={() => setActiveCategory(cat.id)}
                     className={cn("w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors outline-none", activeCategory === cat.id ? "bg-white text-blue-700 shadow-sm border border-slate-200" : "text-slate-600 hover:bg-slate-100")}
                   >
                     {cat.name}
                     <span className="float-right text-[10px] bg-slate-200/60 px-1.5 py-0.5 rounded text-slate-500 mt-0.5">{cat.id === 'all' ? allConnectors.length : allConnectors.filter(c=>c.category===cat.id).length}</span>
                   </button>
                 ))}
               </div>
               <div className="flex-1 overflow-y-auto p-6 bg-slate-50/50 custom-scrollbar">
                  <div className="md:hidden relative mb-4">
                    <Search size={16} className="absolute left-3 top-2.5 text-slate-400" />
                    <input type="text" value={searchQuery} onChange={e=>setSearchQuery(e.target.value)} placeholder="搜索连接器..." className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg text-sm outline-none focus:border-blue-500" />
                  </div>
                  <div className="mb-4 text-sm font-bold text-slate-800 border-b border-slate-200 pb-2">共找到 {filteredSources.length} 个符合条件的连接器</div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                     {filteredSources.map(s => {
                       const Icon = getRegistryIcon(s.category);
                       return (
                         <button
                           key={s.connectorKey}
                           onClick={() => { const p = new URLSearchParams(searchParams); p.set('step', '2'); p.set('source', s.connectorKey); setSearchParams(p); }}
                           className={cn("flex flex-col text-left p-4 bg-white border rounded-xl transition-all outline-none focus:ring-2 focus:ring-blue-500 hover:border-blue-400 hover:shadow-md", s.connectorKey === 'create_custom' ? "border-dashed border-slate-300 bg-slate-50/50 hover:bg-white" : "border-slate-200")}
                         >
                           <div className="flex items-start justify-between w-full mb-3">
                             <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center shrink-0 shadow-sm", s.connectorKey === 'create_custom' ? "bg-slate-100 text-slate-600 border border-slate-200" : "bg-blue-50 text-blue-600 border border-blue-100")}><Icon size={20} /></div>
                           </div>
                           <h4 className="font-bold text-slate-800 text-sm mb-1 truncate">{s.name}</h4>
                           <p className="text-xs text-slate-500 line-clamp-2 mb-3 h-8 leading-relaxed">{s.desc}</p>
                           <div className="flex flex-wrap gap-1 mt-auto">
                             {s.capabilities.map(c => <span key={c} className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded border border-slate-200/50">{c}</span>)}
                           </div>
                         </button>
                       )
                     })}
                  </div>
               </div>
             </div>
           </div>
         )}
         {(step === 2 || source) && currentSourceObj && (
           <div className="flex flex-col h-full bg-slate-50 min-w-0 w-full">
             <div className="h-16 px-4 md:px-6 border-b border-slate-200 flex items-center justify-between bg-white shrink-0 shadow-sm z-10">
               <div className="flex items-center space-x-3">
                 <button onClick={() => { const p = new URLSearchParams(searchParams); p.delete('step'); p.delete('source'); setSearchParams(p); }} className="p-1.5 hover:bg-slate-100 rounded-lg text-slate-500 transition-colors outline-none focus:ring-2 focus:ring-slate-300"><ArrowLeft size={18} /></button>
                 <h2 className="font-bold text-slate-800 text-lg tracking-tight truncate">配置 {currentSourceObj.name}</h2>
               </div>
             </div>
             <div className="flex-1 overflow-y-auto flex justify-center custom-scrollbar">
                <div className="max-w-3xl w-full h-full">
                   <WizardForm sourceObj={currentSourceObj} showToast={showToast} handleClose={handleClose} />
                </div>
             </div>
           </div>
         )}
      </div>
    </div>
  );
}
