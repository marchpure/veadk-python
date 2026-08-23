import React, { useState, useEffect, useRef } from 'react';
import ArtifactHeader from './ArtifactHeader';
import { ListTree, Database, Code, CheckCircle2, AlertTriangle, Fingerprint, PieChart, Activity, Link as LinkIcon, Edit3, Save, RotateCcw, Plus, X } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function SemanticView({ isTeam = false, searchParams, setSearchParams, showToast }: any) {
  const [activeTab, setActiveTab] = useState(searchParams.get('semantic_tab') || 'mdl');
  
  const [mdlCode, setMdlCode] = useState(() => {
    return localStorage.getItem('demo_semantic_mdl_v5') || `model DynamicTable {
  primary_key id
  dimension id : string
  dimension category : string
  dimension date : date
  measure value : number
  
  join Customer on DynamicTable.customer_id = Customer.id (many_to_one)
}`;
  });

  const [draftCode, setDraftCode] = useState(mdlCode);
  useEffect(() => { setDraftCode(mdlCode); }, [mdlCode]);

  const [mdlDiffState, setMdlDiffState] = useState<'idle' | 'validating' | 'diff' | 'applied'>('idle');
  const [errorLine, setErrorLine] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState('');

  const [positions, setPositions] = useState<any>(() => {
    try { const saved = localStorage.getItem('demo_sem_pos_v3'); if (saved) return JSON.parse(saved); } catch(e){}
    return { DynamicTable: {x: 60, y: 100}, Customer: {x: 460, y: 60}, Region: {x: 460, y: 280}, Product: {x: 460, y: 500} };
  });
  useEffect(() => { localStorage.setItem('demo_sem_pos_v3', JSON.stringify(positions)); }, [positions]);
  useEffect(() => { localStorage.setItem('demo_sem_pos_v2', JSON.stringify(positions)); }, [positions]);

  const [dragging, setDragging] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState({x: 0, y: 0});
  const containerRef = useRef<HTMLDivElement>(null);

  const handlePointerDown = (e: React.PointerEvent, model: string) => {
    if (joinMode) return;
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setDragOffset({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    setDragging(model);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const handlePointerMove = (e: React.PointerEvent) => {
    if (!dragging || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setPositions((prev: any) => ({
      ...prev,
      [dragging]: {
        x: e.clientX - rect.left - dragOffset.x,
        y: e.clientY - rect.top - dragOffset.y
      }
    }));
  };
  const handlePointerUp = (e: React.PointerEvent) => {
    if (dragging) {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
      setDragging(null);
    }
  };

  const [joinMode, setJoinMode] = useState(false);
  const [joinSource, setJoinSource] = useState<string | null>(null);

  const handleModelClick = (model: string) => {
    if (joinMode) {
      if (!joinSource) {
        setJoinSource(model);
        showToast?.(`已选择 ${model}，请点击要关联的另一张表。`);
      } else {
        if (joinSource !== model) {
          const newJoin = `  join ${model} on ${joinSource}.id = ${model}.id (many_to_one)`;
          const lines = draftCode.split('\n');
          const lastBraceIdx = lines.findLastIndex(l => l.trim() === '}');
          if (lastBraceIdx !== -1) {
            lines.splice(lastBraceIdx, 0, newJoin);
            const newCode = lines.join('\n');
            setDraftCode(newCode);
            setMdlCode(newCode);
            showToast?.(`成功建立 ${joinSource} 与 ${model} 的关联，已同步至 MDL。`);
          }
        }
        setJoinMode(false);
        setJoinSource(null);
      }
    }
  };

  const [metrics, setMetrics] = useState<any[]>([]);
  useEffect(() => {
    const lines = draftCode.split('\n');
    const parsed: any[] = [];
    lines.forEach((line, i) => {
      const match = line.match(/^\s*measure\s+(\w+)\s*:\s*(.+)$/);
      if (match) {
        parsed.push({ id: match[1], lineIdx: i, logic: match[2], name: match[1], verified: true });
      }
    });
    setMetrics(parsed);
  }, [draftCode]);

  const updateMetric = (id: string, newLogic: string) => {
    setMetrics(prev => prev.map(m => m.id === id ? { ...m, logic: newLogic } : m));
  };

  const saveMetrics = () => {
    const lines = draftCode.split('\n');
    metrics.forEach(m => {
      if (lines[m.lineIdx]) {
        lines[m.lineIdx] = lines[m.lineIdx].replace(/:\s*.+$/, `: ${m.logic}`);
      }
    });
    setDraftCode(lines.join('\n'));
    showToast?.('指标修改已保存，正在校验树...');
    setMdlDiffState('validating');
    setTimeout(() => {
      setMdlDiffState('diff');
    }, 1000);
  };

  useEffect(() => {
    if (searchParams.get('validate') === 'error') {
      setActiveTab('mdl');
      const lines = draftCode.split('\n');
      const lastBraceIdx = lines.findLastIndex(l => l.trim() === '}');
      if (lastBraceIdx !== -1 && !draftCode.includes('invalid_field')) {
        lines.splice(lastBraceIdx, 0, '  measure invalid_field : calculated = unknown_col * 0.1 // 非法引用');
        const errCode = lines.join('\n');
        setDraftCode(errCode);
        setTimeout(() => {
          setMdlDiffState('validating');
          setTimeout(() => {
             setMdlDiffState('idle');
             setErrorLine(lastBraceIdx);
             setErrorMsg("检测到非法引用或未知字段 'unknown_col'");
             showToast?.('校验阻断：MDL 中存在语法或依赖树错误。');
          }, 1000);
        }, 500);
      }
    }
  }, [searchParams]);

  const handleSyncToCanvas = () => {
    setErrorLine(null); setErrorMsg('');
    setMdlDiffState('validating');
    setTimeout(() => {
      if (draftCode.includes('非法') || draftCode.includes('unknown_col')) {
        const lines = draftCode.split('\n');
        const errIdx = lines.findIndex(l => l.includes('unknown_col'));
        setErrorLine(errIdx !== -1 ? errIdx : lines.length - 2);
        setErrorMsg("语法与依赖树校验失败：检测到非法引用或未知字段 unknown_col");
        showToast?.('校验阻断：MDL 中存在语法或依赖树错误。');
        setMdlDiffState('idle');
      } else {
        setMdlDiffState('diff');
      }
    }, 1200);
  };

  const confirmApplyDiff = () => {
    setMdlCode(draftCode);
    localStorage.setItem('demo_semantic_mdl_v5', draftCode);
    setMdlDiffState('applied');
    showToast?.('变更已同步，生成了新版本草稿 V2.3。已触发影响分析引擎验证下游资产安全。');
    setTimeout(() => {
      setMdlDiffState('idle');
      const p = new URLSearchParams(searchParams);
      p.set('version', 'V2.3');
      p.delete('validate');
      setSearchParams(p);
    }, 2500);
  };

  const renderLine = (source: string, target: string) => {
    const p1 = positions[source];
    const p2 = positions[target];
    if (!p1 || !p2) return null;
    const x1 = p1.x + 130;
    const y1 = p1.y + 80;
    const x2 = p2.x + 110;
    const y2 = p2.y + 40;
    return <path d={`M ${x1} ${y1} L ${x2} ${y2}`} stroke="#94a3b8" strokeWidth="2.5" fill="none" markerEnd="url(#arrow)" />;
  };

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full flex flex-col h-full min-w-0">
      <ArtifactHeader 
        title={searchParams.get('custom_name') || (isTeam ? "团队共享语义模型" : "核心语义模型")} 
        typeLabel="Semantic Model"
        isTeam={isTeam} 
        version="V2.2" 
        editTarget={searchParams.get('edit')} 
        onElementClick={(target: string) => {
          if (!isTeam) { const p = new URLSearchParams(searchParams); p.set('edit', target); setSearchParams(p); }
        }} 
        searchParams={searchParams}
        setSearchParams={setSearchParams}
        showToast={showToast}
      />
      
      <div className="flex space-x-6 border-b border-slate-200 mt-2 mb-4 overflow-x-auto custom-scrollbar shrink-0">
        {[
          { id: 'canvas', label: '模型画布', icon: ListTree },
          { id: 'metrics', label: '指标目录', icon: PieChart },
          { id: 'mdl', label: 'MDL 编辑器 (真源)', icon: Code },
          { id: 'lineage', label: '血缘与校验', icon: Fingerprint }
        ].map(tab => (
          <button 
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn("pb-3 text-sm font-bold transition-colors border-b-2 flex items-center whitespace-nowrap outline-none", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}
          >
            <tab.icon size={16} className="mr-2" />
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto bg-white border border-slate-200 rounded-[12px] custom-scrollbar relative flex flex-col min-h-[500px]">
        {activeTab === 'canvas' && (
          <div className="flex-1 relative bg-slate-50/50 overflow-auto custom-scrollbar" ref={containerRef} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerLeave={handlePointerUp}>
             <div className="absolute top-4 left-4 z-20 flex flex-wrap gap-2">
               <button className={cn("px-4 py-2 text-sm font-medium rounded-lg shadow-sm outline-none transition-colors", joinMode ? "bg-blue-600 text-white" : "bg-white border border-slate-200 text-slate-700 hover:bg-blue-50 hover:text-blue-700")} onClick={() => {
                 setJoinMode(!joinMode);
                 setJoinSource(null);
               }}>
                 {joinMode ? '取消建立关系' : '+ 建立关系 (Join)'}
               </button>
               <button className="bg-white border border-slate-200 text-slate-700 px-4 py-2 text-sm font-medium rounded-lg shadow-sm hover:bg-blue-50 hover:text-blue-700 hover:border-blue-200 outline-none transition-colors" onClick={() => {
                 const lines = draftCode.split('\n');
                 const lastBraceIdx = lines.findLastIndex(l => l.trim() === '}');
                 if (lastBraceIdx !== -1) {
                   lines.splice(lastBraceIdx, 0, '  measure net_sales : calculated = sales_amount * 0.85');
                   const newCode = lines.join('\n');
                   setDraftCode(newCode); setMdlCode(newCode);
                   showToast?.('计算字段添加成功，画布的更改已实时同步到 MDL 代码源。');
                 }
               }}>+ 添加计算字段 (Calc)</button>
               <button className="bg-white border border-red-200 text-red-700 px-4 py-2 text-sm font-medium rounded-lg shadow-sm hover:bg-red-50 outline-none transition-colors" onClick={() => {
                 const p = new URLSearchParams(searchParams);
                 p.set('semantic_tab', 'mdl'); p.set('validate', 'error'); setSearchParams(p);
               }}><AlertTriangle size={14} className="inline mr-1"/>制造校验错误</button>
             </div>
             
             {joinMode && joinSource && (
               <div className="absolute top-16 left-4 z-20 bg-amber-100 text-amber-800 px-3 py-1.5 rounded-md text-xs font-bold border border-amber-200 shadow-sm animate-pulse">
                 请点击要关联的目标表 (Target Table)
               </div>
             )}
             
             <svg className="absolute inset-0 pointer-events-none" style={{ minWidth: 1000, minHeight: 800 }}>
               <defs>
                 <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                   <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
                 </marker>
               </defs>
               {draftCode.includes('Customer') && renderLine('DynamicTable', 'Customer')}
               {draftCode.includes('Region') && renderLine('DynamicTable', 'Region')}
               {draftCode.includes('Product') && renderLine('DynamicTable', 'Product')}
             </svg>
             
             {['DynamicTable', 'Customer', 'Region', 'Product'].map((modelName) => {
               if (modelName !== 'DynamicTable' && !draftCode.includes(modelName)) return null;
               
               return (
                 <div 
                   key={modelName}
                   className={cn("absolute w-[260px] bg-white border-2 rounded-xl shadow-lg transition-shadow z-10 select-none", 
                     modelName === 'DynamicTable' ? "border-blue-500 hover:ring-4 hover:ring-blue-100" : "border-slate-300 hover:border-blue-400",
                     joinMode && joinSource === modelName ? "ring-4 ring-amber-300 border-amber-500" : "",
                     joinMode ? "cursor-pointer" : "cursor-grab active:cursor-grabbing"
                   )} 
                   style={{ left: positions[modelName].x, top: positions[modelName].y }}
                   onPointerDown={(e) => handlePointerDown(e, modelName)}
                   onClick={() => handleModelClick(modelName)}
                 >
                   <div className={cn("px-4 py-3 border-b font-bold flex justify-between items-center rounded-t-xl", modelName === 'DynamicTable' ? "bg-blue-50 border-blue-100 text-blue-900" : "bg-slate-50 border-slate-200 text-slate-700")}>
                     <span>{modelName} {modelName === 'DynamicTable' && '(事实表)'}</span>
                     <button onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: `model_${modelName}`, name: `${modelName} 模型`, type: 'semantic', artifactId: searchParams.get('file')} } })); showToast?.('已加入对话上下文'); }} className="text-slate-400 hover:text-blue-600 outline-none"><LinkIcon size={16}/></button>
                   </div>
                   <div className="p-3 space-y-2 text-sm text-slate-700 pointer-events-none">
                     {modelName === 'DynamicTable' ? (
                       <>
                         <div className="flex justify-between items-center"><span className="font-bold text-slate-900 flex items-center"><Database size={12} className="mr-1.5 text-amber-500"/>id <span className="ml-1 bg-amber-100 text-amber-700 px-1 rounded text-[10px]">PK</span></span><span className="text-slate-400 font-mono text-xs">string</span></div>
                         <div className="flex justify-between items-center"><span className="flex items-center font-medium"><Database size={12} className="mr-1.5 text-slate-400"/>customer_id <span className="ml-1 bg-slate-100 text-slate-500 px-1 rounded text-[10px]">FK</span></span><span className="text-slate-400 font-mono text-xs">string</span></div>
                         <div className="flex justify-between items-center text-blue-700 font-bold pt-2 mt-2 border-t border-slate-100"><span>value <span className="ml-1 bg-blue-100 text-blue-700 px-1 rounded text-[10px]">Measure</span></span><span className="font-mono text-xs">number</span></div>
                       </>
                     ) : (
                       <>
                         <div className="flex justify-between items-center"><span>id <span className="ml-1 bg-amber-100 text-amber-700 px-1 rounded text-[9px]">PK</span></span><span className="font-mono text-slate-400">string</span></div>
                         <div className="flex justify-between items-center"><span>name</span><span className="font-mono text-slate-400">string</span></div>
                       </>
                     )}
                   </div>
                 </div>
               );
             })}
          </div>
        )}

        {activeTab === 'metrics' && (
          <div className="flex-1 overflow-x-auto w-full p-6 custom-scrollbar">
            <div className="mb-6 flex justify-between items-center">
              <input type="text" placeholder="搜索指标名称或逻辑..." className="border border-slate-300 rounded-lg px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 shadow-sm w-72" />
              <button className="bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-bold shadow-sm hover:bg-blue-700 outline-none focus:ring-2 focus:ring-blue-500" onClick={saveMetrics}>保存修改，生成 MDL Diff</button>
            </div>
            <table className="w-full text-sm text-left whitespace-nowrap min-w-[800px] border border-slate-200 rounded-xl overflow-hidden shadow-sm">
              <thead className="bg-slate-50 text-slate-600 border-b border-slate-200 font-bold">
                <tr>
                  <th className="px-6 py-4 w-1/4">指标名称</th>
                  <th className="px-6 py-4 w-1/2">计算逻辑 (在线热编辑)</th>
                  <th className="px-6 py-4 text-center">状态</th>
                  <th className="px-6 py-4 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {metrics.map(m => (
                  <tr key={m.id} className="hover:bg-blue-50/50 transition-colors bg-white group">
                    <td className="px-6 py-4 font-bold text-slate-900">{m.name}</td>
                    <td className="px-6 py-4 font-mono text-[13px] text-blue-700 bg-blue-50/20 group-hover:bg-blue-50 transition-colors">
                       <input type="text" value={m.logic} onChange={(e) => updateMetric(m.id, e.target.value)} className="bg-transparent w-full outline-none border-b border-transparent focus:border-blue-500 pb-0.5" />
                    </td>
                    <td className="px-6 py-4 text-center">
                      {m.verified ? (
                        <span className="inline-flex items-center text-green-700 bg-green-50 border border-green-200 px-2.5 py-1 rounded-md text-xs font-bold shadow-sm"><CheckCircle2 size={12} className="mr-1.5" /> 已认证</span>
                      ) : (
                        <span className="inline-flex items-center text-slate-500 bg-slate-100 border border-slate-200 px-2.5 py-1 rounded-md text-xs font-bold shadow-sm">未认证</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button onClick={() => { window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: m.id, name: `${m.name} 指标`, type: 'metric', artifactId: searchParams.get('file')} } })); showToast?.('已加入对话上下文'); }} className="text-blue-600 hover:text-blue-800 font-bold text-xs border border-blue-200 bg-white px-3 py-1.5 rounded-lg shadow-sm hover:shadow transition-all outline-none">加入上下文</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'mdl' && (
          <div className="flex flex-col h-full bg-[#0d1117] text-slate-300 font-mono text-[13px] relative">
             <div className="flex justify-between items-center p-4 border-b border-slate-700/50 bg-[#0d1117] shrink-0">
                <div className="flex items-center">
                  <span className="text-slate-400 font-sans text-sm font-bold flex items-center bg-slate-800 px-3 py-1.5 rounded-lg"><Code size={16} className="mr-2 text-blue-400" /> 代码真源 (MDL Source of Truth)</span>
                </div>
                <div className="flex space-x-3">
                  <button onClick={() => {
                    const formatted = draftCode.split('\n').map(line => {
                      const trimmed = line.trim();
                      if (trimmed === '' || trimmed.startsWith('model') || trimmed === '}') return trimmed;
                      return '  ' + trimmed;
                    }).join('\n');
                    setDraftCode(formatted);
                    showToast?.('格式化成功');
                  }} className="bg-slate-800 hover:bg-slate-700 text-white px-4 py-2 rounded-lg text-xs font-sans font-medium transition-colors outline-none border border-slate-600">自动格式化</button>
                  <button onClick={handleSyncToCanvas} disabled={mdlDiffState !== 'idle'} className="bg-blue-600 hover:bg-blue-500 text-white px-5 py-2 rounded-lg text-xs font-sans font-bold transition-colors shadow-sm outline-none disabled:opacity-50 flex items-center">
                    {mdlDiffState === 'validating' ? '编译树校验中...' : '校验逻辑并同步至画布'}
                  </button>
                </div>
             </div>
             
             {errorLine !== null && (
               <div className="absolute bottom-4 left-4 bg-red-50 text-red-800 border-2 border-red-300 p-4 rounded-xl shadow-xl flex flex-col z-20 animate-in slide-in-from-bottom-2">
                 <div className="font-bold flex items-center mb-1 text-sm"><AlertTriangle size={18} className="mr-2"/> 校验阻断 (错误行号: {errorLine + 1})</div>
                 <div className="text-xs font-mono mb-3 bg-red-100/50 px-2 py-1 rounded">{errorMsg}</div>
                 <button onClick={() => {
                   setErrorLine(null);
                   setDraftCode(mdlCode);
                   showToast?.('已重置 MDL');
                 }} className="text-xs font-bold bg-white text-slate-700 border border-slate-300 px-3 py-1.5 rounded-lg hover:bg-slate-50 self-start shadow-sm outline-none">撤销非法修改</button>
               </div>
             )}

             {mdlDiffState === 'diff' && (
                <div className="absolute inset-x-0 top-16 bottom-0 z-20 bg-white text-slate-800 font-sans flex flex-col animate-in fade-in slide-in-from-bottom-4 shadow-[0_-20px_40px_rgba(0,0,0,0.15)] rounded-t-3xl overflow-hidden">
                   <div className="p-6 border-b border-slate-200 flex justify-between items-center bg-blue-50 shrink-0">
                      <div className="flex items-center text-blue-900 font-bold text-lg"><CheckCircle2 size={24} className="mr-2 text-blue-600" /> 语法校验通过。以下为即将执行的架构 Diff</div>
                      <div className="flex space-x-3">
                        <button onClick={() => setMdlDiffState('idle')} className="px-5 py-2.5 border border-blue-200 text-blue-700 bg-white rounded-lg hover:bg-blue-100 text-sm font-bold transition-colors outline-none">取消同步</button>
                        <button onClick={confirmApplyDiff} className="px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-bold transition-colors shadow-sm outline-none">应用更改以生成新版本 (Apply)</button>
                      </div>
                   </div>
                   <div className="flex-1 p-8 overflow-auto custom-scrollbar bg-slate-100/50">
                      <div className="font-mono text-[13px] bg-[#0d1117] text-slate-300 border border-slate-800 rounded-xl p-6 shadow-xl whitespace-pre-wrap leading-relaxed">
                        <div className="text-slate-500 mb-2">// 检测到 MDL 变更</div>
                        <div className="text-green-400 bg-green-950/30 px-2 py-0.5 rounded -mx-2 font-bold">+ {draftCode.split('\n').find(l => l.includes('net_sales') || l.includes('gross_margin') || l.includes('Store')) || '...'}</div>
                      </div>
                   </div>
                </div>
             )}
             
             <div className="flex-1 flex relative overflow-hidden">
                <div className="w-12 border-r border-slate-700/50 bg-[#0d1117] flex flex-col items-center py-4 text-slate-500 text-xs shrink-0 select-none font-mono font-medium">
                  {draftCode.split('\n').map((_, i) => <div key={i} className={cn("leading-relaxed h-6 w-full text-center", errorLine === i ? "bg-red-500/20 text-red-300 font-bold" : "")}>{i + 1}</div>)}
                </div>
                <textarea 
                  className={cn("flex-1 bg-transparent text-slate-200 p-4 leading-relaxed outline-none resize-none custom-scrollbar whitespace-pre", errorLine !== null ? "decoration-red-500 underline decoration-wavy" : "")}
                  value={draftCode}
                  onChange={(e) => {
                    setDraftCode(e.target.value);
                    if (mdlDiffState !== 'idle') setMdlDiffState('idle');
                    setErrorLine(null);
                  }}
                  spellCheck={false}
                  wrap="off"
                />
             </div>
          </div>
        )}

        {activeTab === 'lineage' && (
          <div className="p-6 h-full bg-slate-50/50 animate-in fade-in flex flex-col">
             <div className="mb-8 bg-white border border-slate-200 rounded-2xl p-6 flex justify-between items-center shadow-sm shrink-0">
                <div>
                  <h3 className="font-bold text-slate-900 text-lg flex items-center mb-1.5"><Activity size={20} className="mr-2 text-blue-600" /> 校验与影响分析 (Impact Analysis)</h3>
                  <p className="text-sm text-slate-500">自动检测循环依赖、无效 join 及字段缺失，并向您报告该变动对下游大盘与看板的具体影响。</p>
                </div>
                <div className="flex items-center text-green-700 font-bold bg-green-50 px-4 py-2.5 rounded-xl border border-green-200 shadow-sm">
                  <CheckCircle2 size={18} className="mr-1.5" /> 当前架构级校验完全通过
                </div>
             </div>

             <div className="flex-1 overflow-y-auto custom-scrollbar relative pl-6 space-y-10 before:absolute before:inset-y-3 before:left-8 before:w-1 before:bg-slate-200">
               <div className="relative pl-10">
                 <div className="absolute left-0 top-1 w-5 h-5 rounded-full border-4 border-slate-50 bg-slate-400 z-10 shadow-sm ring-1 ring-slate-300"></div>
                 <div className="text-base font-bold text-slate-800 mb-3">底层数据连接 (Database Fields)</div>
                 <div className="flex flex-wrap items-center gap-3">
                   <div className="bg-white border border-slate-200 px-4 py-2 rounded-lg text-sm font-mono font-medium text-slate-700 shadow-sm">sales_amount</div>
                 </div>
               </div>
               
               <div className="relative pl-10">
                 <div className="absolute left-0 top-1 w-5 h-5 rounded-full border-4 border-slate-50 bg-blue-500 z-10 shadow-sm ring-1 ring-slate-300"></div>
                 <div className="text-base font-bold text-slate-800 mb-3">下游消费产物 (Impacted Dashboards & Dashboards)</div>
                 <div className="flex flex-col gap-3">
                   <div className="bg-white border border-slate-200 p-4 rounded-xl text-sm font-bold text-slate-700 flex justify-between items-center shadow-sm w-full max-w-2xl">
                      <div className="flex items-center"><LayoutDashboard size={18} className="mr-3 text-purple-500" /> 华东销售经营看板</div>
                      <span className="text-slate-500 bg-slate-100 px-3 py-1 rounded border border-slate-200 text-xs">架构完全兼容</span>
                   </div>
                 </div>
               </div>
             </div>
          </div>
        )}
      </div>
    </div>
  );
}