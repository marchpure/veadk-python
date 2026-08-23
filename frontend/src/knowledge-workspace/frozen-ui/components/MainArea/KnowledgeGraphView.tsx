import React, { useState } from 'react';
import ArtifactHeader from './ArtifactHeader';
import { Database, Network, Workflow, Library, Search, Filter, Maximize, ZoomIn, ZoomOut, Link as LinkIcon, AlertTriangle, CheckCircle2, Edit3, Plus, Wand2, X, FileText, ChevronRight, Fingerprint, Trash2, Check } from 'lucide-react';
import { cn } from '../../lib/utils';
import { getFullCatalog } from '../../lib/store';

export default function KnowledgeGraphView({ isTeam = false, searchParams, setSearchParams, showToast, fileId }: any) {
  const [activeTab, setActiveTab] = useState(searchParams.get('kg_tab') || 'graph');
  const [scale, setScale] = useState(1);
  const editTarget = searchParams.get('edit');
  
  const [entities, setEntities] = useState<any[]>(() => {
    try { const saved = localStorage.getItem('demo_kg_entities_v3'); if (saved) return JSON.parse(saved); } catch(e) {}
    return [
      { id: 'e1', name: 'Customer (客户)', props: 8, constraints: 'ID 唯一' },
      { id: 'e2', name: 'Order (订单)', props: 12, constraints: '非空' },
      { id: 'e3', name: 'Product (商品)', props: 5, constraints: '所属类目' },
      { id: 'e4', name: 'Region (区域)', props: 3, constraints: '' }
    ];
  });

  const [mappings, setMappings] = useState<any[]>([
    { id: 'm1', onto: 'Order.total_amount', db: 'Semantic Metric: m_sales', status: 'pending' },
    { id: 'm2', onto: 'Customer.location', db: 'Table: customers.address', status: 'pending' },
    { id: 'm3', onto: 'Order -HappenIn-> Region', db: '未映射 (缺少关联)', status: 'conflict' }
  ]);

  const handleElementClick = (target: string) => {
    if (isTeam) return;
    const p = new URLSearchParams(searchParams);
    p.set('edit', target);
    setSearchParams(p);
  };

  const handleAddContext = (item: any) => {
    window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
    showToast?.('已加入 Context Composer');
  };

  const tabs = [
    { id: 'ontology', label: '本体 (Ontology)', icon: Library },
    { id: 'graph', label: '知识图谱 (Graph)', icon: Network },
    { id: 'mapping', label: '语义映射 (Mapping)', icon: Workflow },
    { id: 'query', label: '推理查询 (Reasoning)', icon: Search },
    { id: 'provenance', label: '血缘质量 (Provenance)', icon: Fingerprint }
  ];

  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [queryResultReady, setQueryResultReady] = useState(searchParams.get('kg_tab') === 'query' && searchParams.has('searched'));
  const [queryInput, setQueryInput] = useState('');

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto w-full flex flex-col h-full min-w-0 animate-in fade-in duration-300 relative">
      <div className="flex flex-col md:flex-row md:justify-between md:items-start mb-6 w-full gap-4">
        <ArtifactHeader 
          title="销售业务知识图谱" 
          typeLabel="Knowledge Graph"
          isTeam={isTeam} 
          version="V1.0" 
          editTarget={editTarget} 
          onElementClick={handleElementClick} 
          searchParams={searchParams}
          setSearchParams={setSearchParams}
          showToast={showToast}
        />
        <button onClick={() => {
          window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: fileId || 'kg_sales', name: '销售业务知识图谱', type: 'knowledge_graph', artifactType: 'kg'} } }));
          const p = new URLSearchParams(searchParams);
          p.set('pane', 'open');
          p.set('chat', 'planning');
          setSearchParams(p);
          showToast?.('已转入分析助手，请通过 Artifact Plan 配置实体关系推理与图谱构建');
        }} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium shadow-sm hover:bg-blue-700 flex items-center outline-none whitespace-nowrap shrink-0 w-fit transition-colors">
          <Wand2 size={16} className="mr-2"/> AI 建议与推理 (转至右栏)
        </button>
      </div>
      
      <div className="flex space-x-6 border-b border-slate-200 mt-2 mb-4 overflow-x-auto custom-scrollbar shrink-0">
        {tabs.map(tab => (
          <button 
            key={tab.id}
            onClick={() => {
              const p = new URLSearchParams(searchParams);
              p.set('kg_tab', tab.id);
              setSearchParams(p);
              setActiveTab(tab.id);
            }}
            className={cn("pb-3 text-sm font-medium transition-colors border-b-2 flex items-center whitespace-nowrap outline-none", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}
          >
            <tab.icon size={16} className="mr-2" />
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 bg-white border border-slate-200 rounded-[12px] overflow-hidden flex flex-col min-h-[550px] relative min-w-0">
        {activeTab === 'ontology' && (
          <div className="flex flex-col h-full">
            <div className="p-4 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
              <h3 className="font-medium text-slate-800 text-sm">实体类与关系定义</h3>
              <button onClick={() => {
                const newEnt = prompt('请输入新实体类名称，如 Location (地址)');
                if (newEnt) {
                  showToast?.(`已成功创建实体类 ${newEnt}`);
                  setEntities([{ id: `e${Date.now()}`, name: newEnt, props: 0, constraints: '' }, ...entities]);
                  localStorage.setItem('demo_kg_entities_v3', JSON.stringify([{ id: `e${Date.now()}`, name: newEnt, props: 0, constraints: '' }, ...entities]));
                }
              }} className="bg-blue-600 text-white px-4 py-2 rounded-lg text-xs font-medium hover:bg-blue-700 outline-none shadow-sm flex items-center">
                <Plus size={14} className="mr-1.5"/> 新增 Class/Entity
              </button>
            </div>
            <div className="flex-1 overflow-auto p-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 bg-slate-50 custom-scrollbar">
               {entities.map((e: any, i: number) => (
                 <div key={e.id} className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm hover:border-blue-300 transition-colors group cursor-pointer">
                   <div className="flex justify-between items-start mb-3">
                     <div className="font-semibold text-slate-800 bg-blue-50 text-blue-800 px-2 py-1 rounded inline-block text-sm">{e.name}</div>
                     <button className="text-slate-400 hover:text-blue-600 outline-none"><Edit3 size={14}/></button>
                   </div>
                   <div className="space-y-1.5 text-xs text-slate-600 border-t border-slate-100 pt-3">
                     <div className="flex justify-between"><span>继承 (SubClassOf)</span><span className="text-slate-400 font-medium">Root</span></div>
                     <div className="flex justify-between"><span>属性 (Property)</span><span className="text-slate-400 font-medium">{e.props} 个</span></div>
                     <div className="flex justify-between"><span>约束 (Constraint)</span><span className="text-slate-400 font-medium truncate w-24 text-right">{e.constraints || '无'}</span></div>
                   </div>
                 </div>
               ))}
            </div>
          </div>
        )}

        {activeTab === 'graph' && (
          <div className="flex flex-col h-full relative overflow-hidden bg-slate-50/50" onClick={() => setSelectedNode(null)}>
             <div className="absolute top-4 left-4 z-10 bg-white border border-slate-200 shadow-sm rounded-lg p-1.5 flex items-center space-x-1">
               <div className="relative">
                 <Search size={14} className="absolute left-2.5 top-2 text-slate-400" />
                 <input type="text" placeholder="搜索节点或关系..." className="w-32 md:w-48 pl-8 pr-3 py-1.5 text-xs bg-slate-50 border border-transparent focus:bg-white focus:border-blue-300 rounded outline-none transition-colors" />
               </div>
               <div className="w-px h-4 bg-slate-200 mx-1"></div>
               <button className="p-1.5 text-slate-500 hover:bg-slate-100 rounded outline-none" title="按类型筛选"><Filter size={14}/></button>
             </div>

             <div className="absolute top-4 right-4 z-10 bg-white border border-slate-200 shadow-sm rounded-lg flex flex-col">
               <button className="p-2 text-slate-600 hover:bg-slate-100 outline-none border-b border-slate-100 rounded-t-lg" onClick={() => setScale(s => Math.min(s + 0.2, 2))}><ZoomIn size={16}/></button>
               <button className="p-2 text-slate-600 hover:bg-slate-100 outline-none border-b border-slate-100" onClick={() => setScale(1)}><Maximize size={16}/></button>
               <button className="p-2 text-slate-600 hover:bg-slate-100 rounded-b-lg outline-none" onClick={() => setScale(s => Math.max(s - 0.2, 0.5))}><ZoomOut size={16}/></button>
             </div>

             {selectedNode && (
               <div className="absolute right-4 top-20 w-64 bg-white border border-slate-200 shadow-lg rounded-xl p-4 z-20 animate-in slide-in-from-right-4" onClick={e=>e.stopPropagation()}>
                  <div className="font-bold text-slate-800 text-lg mb-1">{selectedNode}</div>
                  <div className="text-xs text-slate-500 mb-4 pb-3 border-b border-slate-100">更新时间: 12:30 | 置信度: 0.98</div>
                  <div className="flex flex-col gap-2">
                    <button onClick={() => showToast?.('已展开相关的一级邻居节点')} className="w-full py-2 bg-blue-50 hover:bg-blue-100 text-blue-700 rounded-lg text-xs font-bold transition-colors outline-none shadow-sm flex items-center justify-center"><Network size={14} className="mr-1.5"/> 展开邻居</button>
                    <button onClick={() => showToast?.('找到了 1 条通往目标的路径，请查看图谱高亮。')} className="w-full py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-bold transition-colors outline-none shadow-sm flex items-center justify-center"><Workflow size={14} className="mr-1.5"/> 路径查找</button>
                  </div>
               </div>
             )}

             <div className="absolute bottom-4 right-4 z-10">
               <button className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 shadow-md flex items-center outline-none focus:ring-2 focus:ring-blue-500" onClick={(e) => { e.stopPropagation(); handleAddContext({id: 'kg_subgraph', name: '全选的知识子图 (8节点)', type: 'kg_subgraph', path: 'KG/SubGraph', tokenEstimate: 2.1}); }}>
                 <LinkIcon size={14} className="mr-1.5" /> 截取子图加入上下文
               </button>
             </div>

             <div className="flex-1 overflow-auto relative cursor-grab active:cursor-grabbing w-full h-full custom-scrollbar flex items-center justify-center min-w-0 min-h-0">
                <div style={{ transform: `scale(${scale})`, transformOrigin: 'center center', width: 800, height: 600 }} className="relative flex-shrink-0 transition-transform duration-200">
                  <svg className="absolute inset-0 w-full h-full pointer-events-none">
                    <defs>
                      <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="28" refY="3.5" orient="auto">
                        <polygon points="0 0, 10 3.5, 0 7" fill="#94a3b8" />
                      </marker>
                      <marker id="arrowhead-highlight" markerWidth="10" markerHeight="7" refX="28" refY="3.5" orient="auto">
                        <polygon points="0 0, 10 3.5, 0 7" fill="#3b82f6" />
                      </marker>
                      <marker id="arrowhead-warn" markerWidth="10" markerHeight="7" refX="28" refY="3.5" orient="auto">
                        <polygon points="0 0, 10 3.5, 0 7" fill="#f59e0b" />
                      </marker>
                    </defs>
                    
                    <path d="M 200 200 L 400 200" stroke="#3b82f6" strokeWidth="2.5" markerEnd="url(#arrowhead-highlight)" className="drop-shadow-sm pointer-events-auto cursor-pointer" onClick={(e) => { e.stopPropagation(); handleAddContext({id: 'rel_place', name: '客户-下单->订单', type: 'kg_rel'}); }} />
                    <text x="300" y="190" textAnchor="middle" fill="#2563eb" fontSize="13" fontWeight="bold">下单 (Place)</text>
                    
                    <path d="M 400 200 L 600 200" stroke="#3b82f6" strokeWidth="2.5" markerEnd="url(#arrowhead-highlight)" className="drop-shadow-sm pointer-events-auto cursor-pointer" onClick={(e) => { e.stopPropagation(); handleAddContext({id: 'rel_contain', name: '订单-包含->商品', type: 'kg_rel'}); }} />
                    <text x="500" y="190" textAnchor="middle" fill="#2563eb" fontSize="13" fontWeight="bold">包含 (Contain)</text>
                    
                    <path d="M 400 200 L 400 350" stroke="#f59e0b" strokeDasharray="5,5" strokeWidth="2.5" markerEnd="url(#arrowhead-warn)" className="pointer-events-auto cursor-pointer" onClick={(e) => { e.stopPropagation(); handleAddContext({id: 'rel_happen', name: '订单-发生于->区域', type: 'kg_rel'}); }} />
                    <text x="410" y="275" fill="#d97706" fontSize="13" fontWeight="bold">发生于 (待确认 1)</text>
                  </svg>

                  <div onClick={(e) => { e.stopPropagation(); setSelectedNode('Customer'); }} className={cn("absolute top-[170px] left-[140px] w-28 bg-white border-2 rounded-full shadow-md text-center py-2.5 cursor-pointer hover:ring-4 hover:ring-emerald-100 transition-all font-bold text-slate-800 text-sm", selectedNode === 'Customer' ? "ring-4 ring-emerald-200 border-emerald-500" : "border-emerald-400")}>
                    Customer
                  </div>
                  <div onClick={(e) => { e.stopPropagation(); setSelectedNode('Order'); }} className={cn("absolute top-[170px] left-[340px] w-28 bg-white border-2 rounded-full shadow-lg text-center py-2.5 cursor-pointer transition-all font-bold text-blue-900 text-sm z-10", selectedNode === 'Order' ? "ring-4 ring-blue-300 border-blue-600" : "ring-4 ring-blue-100 border-blue-500")}>
                    Order
                  </div>
                  <div onClick={(e) => { e.stopPropagation(); setSelectedNode('Product'); }} className={cn("absolute top-[170px] left-[540px] w-28 bg-white border-2 rounded-full shadow-md text-center py-2.5 cursor-pointer hover:ring-4 hover:ring-purple-100 transition-all font-bold text-slate-800 text-sm", selectedNode === 'Product' ? "ring-4 ring-purple-200 border-purple-500" : "border-purple-400")}>
                    Product
                  </div>
                  <div onClick={(e) => { e.stopPropagation(); setSelectedNode('Region'); }} className={cn("absolute top-[350px] left-[340px] w-28 bg-amber-50 border-2 border-dashed rounded-full shadow-md text-center py-2.5 cursor-pointer hover:ring-4 hover:ring-amber-100 transition-all font-bold text-amber-800 text-sm", selectedNode === 'Region' ? "ring-4 ring-amber-200 border-amber-600" : "border-amber-400")}>
                    Region
                  </div>
                </div>
             </div>
          </div>
        )}

        {activeTab === 'mapping' && (
          <div className="h-full bg-slate-50 flex flex-col overflow-hidden">
             <div className="p-4 bg-white border-b border-slate-200 shrink-0 flex items-center justify-between overflow-x-auto custom-scrollbar gap-4">
                <div className="flex items-center text-sm font-medium text-slate-800 bg-green-50 px-3 py-1.5 rounded-lg border border-green-200 shrink-0">
                   <CheckCircle2 size={16} className="text-green-600 mr-2" />
                   本体映射覆盖率: 85%
                </div>
                <button className="text-sm text-white bg-blue-600 px-4 py-2 rounded-lg font-medium hover:bg-blue-700 outline-none shadow-sm flex items-center shrink-0">生成自动映射建议</button>
             </div>
             <div className="flex-1 overflow-x-auto p-4 md:p-6 custom-scrollbar">
                <table className="w-full text-sm text-left bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden min-w-[700px]">
                  <thead className="bg-slate-50 border-b border-slate-200 text-slate-600">
                    <tr>
                      <th className="px-5 py-4 font-semibold">Ontology 属性</th>
                      <th className="px-5 py-4 font-semibold text-center w-24">方向</th>
                      <th className="px-5 py-4 font-semibold">底层模型 (Semantic / DB)</th>
                      <th className="px-5 py-4 font-semibold text-center w-36">映射审批状态</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {mappings.map(m => (
                      <tr key={m.id} className="hover:bg-slate-50/50 transition-colors">
                        <td className="px-5 py-4 font-bold text-slate-800">{m.onto}</td>
                        <td className="px-5 py-4 text-center text-slate-400"><Workflow size={16} className="inline"/></td>
                        <td className="px-5 py-4 font-mono text-sm text-blue-700">{m.db}</td>
                        <td className="px-5 py-4 text-center">
                          {m.status === 'pending' ? (
                            <div className="flex space-x-2 justify-center">
                              <button onClick={() => setMappings(p => p.map(x => x.id === m.id ? {...x, status: 'matched'} : x))} className="p-1.5 bg-green-100 text-green-700 hover:bg-green-200 rounded outline-none" title="接受建议"><Check size={14}/></button>
                              <button onClick={() => setMappings(p => p.map(x => x.id === m.id ? {...x, status: 'ignored'} : x))} className="p-1.5 bg-slate-100 text-slate-600 hover:bg-slate-200 rounded outline-none" title="拒绝/忽略"><X size={14}/></button>
                            </div>
                          ) : m.status === 'matched' ? (
                            <span className="bg-green-100 text-green-800 px-2.5 py-1 rounded text-xs font-bold border border-green-200">已确认</span>
                          ) : m.status === 'ignored' ? (
                            <span className="bg-slate-100 text-slate-600 px-2.5 py-1 rounded text-xs font-bold border border-slate-200">已忽略</span>
                          ) : (
                            <span className="bg-red-50 text-red-700 px-2.5 py-1 rounded text-xs font-bold border border-red-200 flex items-center justify-center"><AlertTriangle size={12} className="mr-1"/> 冲突缺失</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
             </div>
          </div>
        )}

        {activeTab === 'query' && (
          <div className="h-full flex flex-col bg-white min-w-0">
             <div className="p-4 md:p-6 border-b border-slate-200 bg-slate-50 shrink-0">
                <h3 className="font-semibold text-slate-800 mb-3 flex items-center"><Search size={18} className="mr-2 text-blue-600"/> 自然语言图查询 (Reasoning)</h3>
                <div className="flex flex-col sm:flex-row gap-3">
                   <input type="text" className="flex-1 border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500 shadow-sm" placeholder="例如：华东区域销售下降关联了哪些商品、订单与指标？" value={queryInput} onChange={e=>setQueryInput(e.target.value)} />
                   <button className="bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 shadow-sm flex items-center justify-center outline-none focus:ring-2 focus:ring-blue-500 whitespace-nowrap shrink-0" onClick={() => {
                     showToast?.('推理完成，找到了 3 条核心影响路径。');
                     setQueryResultReady(true);
                   }}>
                      <Workflow size={16} className="mr-2"/>开始推理
                   </button>
                </div>
             </div>
             <div className="flex-1 p-4 md:p-6 overflow-auto bg-slate-50/50 custom-scrollbar">
                {queryResultReady ? (
                  <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm animate-in slide-in-from-bottom-2">
                     <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center mb-4 border-b border-slate-100 pb-3 gap-3">
                        <span className="font-semibold text-slate-800 text-sm">推理结果子图 (Sub-graph)</span>
                        <button onClick={() => handleAddContext({id: 'kg_reasoning_result', name: '图查询结果: 华东区域分析', type: 'kg_subgraph', path: 'KG/Query_Result', tokenEstimate: 2.1})} className="text-xs bg-blue-50 text-blue-600 border border-blue-200 px-3 py-1.5 rounded-md hover:bg-blue-100 font-medium flex items-center shadow-sm transition-colors outline-none focus:ring-2 focus:ring-blue-500 justify-center">
                           <LinkIcon size={12} className="mr-1.5" /> 加入上下文
                        </button>
                     </div>
                     <div className="space-y-4 text-sm text-slate-700">
                        <div className="flex items-start bg-slate-50 p-3 rounded-lg border border-slate-100"><CheckCircle2 size={16} className="text-green-500 mr-2 mt-0.5 shrink-0"/> <div><span className="font-semibold text-slate-800">关联商品 (Products):</span> <span className="font-medium text-blue-700 ml-2">智能手机X, 平板电脑Y</span></div></div>
                        <div className="flex items-start bg-slate-50 p-3 rounded-lg border border-slate-100"><CheckCircle2 size={16} className="text-green-500 mr-2 mt-0.5 shrink-0"/> <div><span className="font-semibold text-slate-800">关联订单 (Orders):</span> <span className="font-medium text-amber-700 ml-2">异常退货订单 45 笔集中在华东区</span></div></div>
                        <div className="flex items-start bg-slate-50 p-3 rounded-lg border border-slate-100"><CheckCircle2 size={16} className="text-green-500 mr-2 mt-0.5 shrink-0"/> <div><span className="font-semibold text-slate-800">核心影响指标 (Metrics):</span> <span className="font-medium text-red-600 ml-2">客单价 (m_aov) 下降 12%</span></div></div>
                     </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-full text-slate-400">
                    <Search size={32} className="mb-2 opacity-50" />
                    <div className="text-sm">输入问题以执行推理</div>
                  </div>
                )}
             </div>
          </div>
        )}

        {activeTab === 'provenance' && (
          <div className="h-full flex flex-col bg-white min-w-0">
             <div className="p-4 md:p-6 border-b border-slate-200 flex flex-col md:flex-row md:justify-between md:items-center bg-slate-50 gap-4 shrink-0">
                <div>
                   <h3 className="font-semibold text-slate-800 mb-1">血缘与图谱质量 (Provenance & Quality)</h3>
                   <p className="text-xs text-slate-500">追踪实例来源，处理实体冲突与去重。</p>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-sm font-medium">
                   <div className="flex items-center bg-white px-3 py-1.5 rounded-lg border border-slate-200 shadow-sm whitespace-nowrap"><span className="w-3 h-3 rounded-full bg-green-500 mr-2"></span>图谱质量分: 92</div>
                   <button className="bg-amber-50 text-amber-700 border border-amber-200 px-3 py-1.5 rounded-md hover:bg-amber-100 shadow-sm flex items-center outline-none whitespace-nowrap">
                      <AlertTriangle size={14} className="mr-1.5" /> 待处理 2 处冲突
                   </button>
                </div>
             </div>
             <div className="flex-1 bg-slate-50/50 p-4 md:p-6 overflow-auto space-y-4 custom-scrollbar">
                <div className="bg-white border border-red-200 rounded-xl p-5 shadow-sm relative overflow-hidden">
                   <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-red-500"></div>
                   <h4 className="text-sm font-semibold text-red-800 mb-2 flex items-center"><AlertTriangle size={16} className="mr-2"/> 实体去重冲突 (Entity Resolution)</h4>
                   <p className="text-xs text-slate-600 mb-4 leading-relaxed">检测到两个高度相似的 Customer 实体，可能为同一客户：</p>
                   <div className="flex flex-col sm:flex-row gap-4 mb-4">
                      <div className="flex-1 bg-slate-50 border border-slate-200 p-3 rounded-lg text-xs font-mono text-slate-700 shadow-inner">ID: CUST_101<br/>Name: "Apple Inc."<br/>Src: CRM_System</div>
                      <div className="flex-1 bg-slate-50 border border-slate-200 p-3 rounded-lg text-xs font-mono text-slate-700 shadow-inner">ID: CUST_992<br/>Name: "Apple"<br/>Src: Manual_Upload</div>
                   </div>
                   <button className="text-xs bg-red-600 text-white px-4 py-2 rounded-lg font-medium hover:bg-red-700 shadow-sm outline-none focus:ring-2 focus:ring-red-500" onClick={() => showToast?.('实体合并请求已提交！')}>执行合并 (Merge)</button>
                </div>
                
                <div className="bg-white border border-amber-200 rounded-xl p-5 shadow-sm relative overflow-hidden">
                   <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-amber-500"></div>
                   <h4 className="text-sm font-semibold text-amber-800 mb-2 flex items-center"><AlertTriangle size={16} className="mr-2"/> 关系缺失风险 (Missing Relations)</h4>
                   <p className="text-xs text-slate-600 mb-4 leading-relaxed">有 145 笔 Order 实例未关联任何 Region 节点，可能导致空间推理查询失效。</p>
                   <button className="text-xs bg-amber-50 text-amber-700 border border-amber-200 px-4 py-2 rounded-lg font-medium hover:bg-amber-100 shadow-sm outline-none focus:ring-2 focus:ring-amber-500 flex items-center w-fit" onClick={() => showToast?.('AI 修复计划已启动，将尝试自动补全孤立节点关联。')}><Wand2 size={14} className="mr-1.5"/>启动 AI Fix Plan 修复</button>
                </div>
             </div>
          </div>
        )}
      </div>
    </div>
  );
}