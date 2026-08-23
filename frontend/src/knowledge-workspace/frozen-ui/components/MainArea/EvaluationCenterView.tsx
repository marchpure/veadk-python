import React, { useState, useEffect } from 'react';
import { Play, Plus, Clock, CheckCircle2, AlertTriangle, ArrowLeft, Loader2, Search, Check, Wand2, X, ShieldAlert, FileText, Upload } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function EvaluationCenterView({ searchParams, setSearchParams, showToast }: any) {
  const [view, setView] = useState<'list' | 'detail' | 'run' | 'add_question'>('detail');
  
  const [scenes, setScenes] = useState<any[]>(() => {
    try { const saved = localStorage.getItem('demo_eval_scenes_v3'); if (saved) return JSON.parse(saved); } catch(e) {}
    return [
      { id: 'sc1', name: '销售问答回归评测集', desc: '核心看板与问答的 Ground Truth，涵盖财务与订单流。', acc: '80%', time: '2.4s', issues: 1, lastRun: '2小时前' }
    ];
  });
  useEffect(() => { localStorage.setItem('demo_eval_scenes_v3', JSON.stringify(scenes)); }, [scenes]);

  const [activeScene, setActiveScene] = useState<any>(scenes[0] || null);
  
  const [questions, setQuestions] = useState<any[]>(() => {
    try { const saved = localStorage.getItem('demo_eval_questions_v3'); if (saved) return JSON.parse(saved); } catch(e) {}
    return [
      { id: 'q1', setId: 'sc1', text: '华东区上个月的利润率是多少？', sql: "SELECT SUM(profit)/SUM(sales) FROM orders WHERE region='华东区'", status: 'pass', expected: '单行记录', reason: '' },
      { id: 'q2', setId: 'sc1', text: '销量前十的产品类别是哪些？', sql: 'SELECT category, SUM(sales) FROM orders GROUP BY category ORDER BY 2 DESC LIMIT 10', status: 'pass', expected: '按降序排列表格', reason: '' },
      { id: 'q3', setId: 'sc1', text: '各区域的平均客单价对比情况？', sql: 'SELECT region, SUM(sales)/COUNT(DISTINCT order_id) FROM orders GROUP BY region', status: 'pass', expected: '区域聚合数据', reason: '' },
      { id: 'q4', setId: 'sc1', text: '2023年Q1退货最多的客户是谁？', sql: "SELECT customer_id, COUNT(return_id) FROM orders WHERE quarter='Q1' GROUP BY customer_id ORDER BY 2 DESC LIMIT 1", status: 'pass', expected: '单一客户', reason: '' },
      { id: 'q5', setId: 'sc1', text: '计算各地区的退货率对比', sql: 'SELECT region, COUNT(return_id)/COUNT(order_id) FROM orders GROUP BY region', status: 'fail', reason: '指标计算中缺少除零保护', expected: '区域聚合二维表' },
      { id: 'q6', setId: 'sc1', text: '华南区上周的订单分布情况', sql: "SELECT order_date, COUNT(*) FROM orders WHERE region='华南区' GROUP BY order_date", status: 'untested', expected: '多行日期数据', reason: '' }
    ];
  });
  useEffect(() => { localStorage.setItem('demo_eval_questions_v3', JSON.stringify(questions)); }, [questions]);

  const activeQuestions = questions.filter(q => q.setId === activeScene?.id);

  const [runProgress, setRunProgress] = useState(0);
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'done' | 'stopped'>('idle');

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showSelectModal, setShowSelectModal] = useState(false);

  // New Question State
  const [step, setStep] = useState(1);
  const [newQText, setNewQText] = useState('');
  const [newQSql, setNewQSql] = useState('');
  const [newQExpected, setNewQExpected] = useState('');
  const [newQTolerance, setNewQTolerance] = useState('精确匹配 (0 容差)');
  const [newQTags, setNewQTags] = useState('');

  const handleRun = () => {
    if (!activeScene) return;
    setView('run');
    setRunStatus('running');
    setRunProgress(0);
    const interval = setInterval(() => {
      setRunProgress(p => {
        if (p >= 100) {
          clearInterval(interval);
          setRunStatus('done');
          return 100;
        }
        return p + 20;
      });
    }, 500);
  };

  const handleSaveSet = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const ns = { 
      id: `sc_${Date.now()}`, 
      name: fd.get('name') as string, 
      desc: fd.get('desc') as string, 
      acc: '-', time: '-', issues: 0, lastRun: '-' 
    };
    setScenes([ns, ...scenes]);
    setShowCreateModal(false);
    showToast?.('评测集创建成功');
  };

  const saveNewQuestion = () => {
    if (!newQExpected) { showToast?.('请填写期望输出验证'); return; }
    const nq = { 
      id: Date.now().toString(), 
      setId: activeScene.id,
      text: newQText, 
      sql: newQSql, 
      status: 'untested', 
      expected: newQExpected, 
      reason: '' 
    };
    setQuestions([...questions, nq]);
    showToast?.('用例保存成功。执行运行后生效。');
    setNewQText(''); setNewQSql(''); setNewQExpected(''); setStep(1);
    setView('detail');
  };

  const [fixState, setFixState] = useState<'idle' | 'plan' | 'applying' | 'done'>('idle');
  const [selectedFailed, setSelectedFailed] = useState<string[]>([]);

  const toggleSelectFailed = (id: string) => {
    setSelectedFailed(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const confirmFix = () => {
    setFixState('applying');
    setTimeout(() => {
      setQuestions(prev => prev.map(q => selectedFailed.includes(q.id) ? { ...q, status: 'pass' } : q));
      setFixState('done');
      showToast?.('应用修改成功，已仅针对受影响的测试用例进行局部回归并全量通过！');
      setTimeout(() => {
        setFixState('idle');
        setSelectedFailed([]);
      }, 2500);
    }, 2500);
  };

  useEffect(() => {
    if (searchParams.get('action') === 'add_question') {
       if (!activeScene) { setShowSelectModal(true); }
       else setView('add_question');
    }
    else if (searchParams.get('run') === 'sc1') {
      setActiveScene(scenes[0]);
      setView('run');
      setRunStatus('done');
      setRunProgress(100);
    } else {
      setView('detail');
    }
  }, [searchParams, activeScene]);

  return (
    <div className="flex flex-col h-full bg-slate-50/50 min-w-0 w-full animate-in fade-in duration-300 relative">
      <div className="h-16 px-4 md:px-6 bg-white border-b border-slate-200 flex items-center justify-between shrink-0 shadow-[0_1px_3px_0_rgba(0,0,0,0.02)] z-10 w-full min-w-0">
        <div className="flex items-center space-x-2 md:space-x-4 min-w-0">
          {searchParams.get('eval_target') && (
            <button onClick={() => {
              const p = new URLSearchParams(searchParams);
              p.set('file', searchParams.get('eval_target') || 'dashboard_sales_east');
              p.delete('eval_target');
              p.delete('pane');
              setSearchParams(p);
            }} className="px-3 py-1.5 hover:bg-slate-100 rounded-lg text-slate-600 font-medium text-sm flex items-center transition-colors outline-none focus:ring-2 focus:ring-slate-300 shrink-0">
              <ArrowLeft size={16} className="mr-1.5" />
              返回产物
            </button>
          )}
          {!searchParams.get('eval_target') && (
            <button onClick={() => {
              const p = new URLSearchParams(searchParams);
              p.set('file', 'welcome');
              setSearchParams(p);
            }} className="p-2 hover:bg-slate-100 rounded-lg text-slate-500 transition-colors outline-none focus:ring-2 focus:ring-slate-300 shrink-0">
              <ArrowLeft size={18} />
            </button>
          )}
          <div className="flex flex-col border-l border-slate-200 pl-4">
            <h1 className="text-lg font-bold text-slate-800 tracking-tight truncate">
              {view === 'add_question' ? '添加测试用例' : '产物质量评测'}
            </h1>
            <span className="text-[10px] text-slate-500 flex items-center">
              目标: {searchParams.get('eval_target') || '独立评测任务'} <span className="mx-1">|</span> 版本: {searchParams.get('version') || 'V2.1'}
            </span>
          </div>
        </div>
        <div className="flex space-x-2 md:space-x-3 shrink-0">
           {view !== 'add_question' && <button onClick={() => { if(!activeScene && scenes.length > 0) setActiveScene(scenes[0]); setView('add_question'); }} className="px-3 md:px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-xs md:text-sm font-bold hover:bg-slate-50 shadow-sm flex items-center outline-none transition-colors"><FileText size={14} className="mr-1.5"/> 添加用例</button>}
           {view !== 'add_question' && <button onClick={() => { if(!activeScene && scenes.length > 0) setActiveScene(scenes[0]); handleRun(); }} className="px-3 md:px-4 py-2 bg-blue-600 text-white rounded-lg text-xs md:text-sm font-bold hover:bg-blue-700 shadow-sm flex items-center outline-none transition-colors"><Play size={14} className="mr-1.5"/> 运行评测</button>}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-8 custom-scrollbar">
        {view === 'list' && (
          <div className="max-w-5xl mx-auto w-full space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {scenes.map(sc => (
                <div key={sc.id} className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm hover:border-blue-400 transition-colors cursor-pointer outline-none hover:shadow-md group flex flex-col h-full" onClick={() => { setActiveScene(sc); setView('detail'); }}>
                  <div className="flex-1">
                    <h3 className="text-lg font-bold text-slate-900 mb-2 group-hover:text-blue-700 transition-colors">{sc.name}</h3>
                    <p className="text-sm text-slate-500 mb-6 line-clamp-2 leading-relaxed">{sc.desc}</p>
                  </div>
                  <div className="grid grid-cols-3 gap-4 border-t border-slate-100 pt-5">
                    <div className="flex flex-col">
                      <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1">通过率</span>
                      <span className={cn("text-xl font-bold tabular-nums", sc.acc === '100%' ? "text-green-600" : sc.acc === '-' ? "text-slate-400" : "text-amber-500")}>{sc.acc}</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1">失败数</span>
                      <span className="text-xl font-bold text-slate-800 tabular-nums">{sc.issues}</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1">运行</span>
                      <span className="text-sm font-medium text-slate-600 truncate">{sc.lastRun}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {view === 'detail' && (
          <div className="max-w-5xl mx-auto w-full bg-white border border-slate-200 rounded-[12px] overflow-hidden flex flex-col h-full min-h-[600px] animate-in slide-in-from-bottom-4">
            <div className="p-5 bg-slate-50 border-b border-slate-200 flex justify-between items-center shrink-0">
               <h2 className="text-base font-bold text-slate-800 flex items-center"><FileText size={18} className="mr-2 text-blue-600"/> 测试用例管理 ({activeQuestions.length})</h2>
               <div className="flex space-x-3">
                 <button className="px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 flex items-center outline-none shadow-sm transition-colors" onClick={() => setView('add_question')}>
                   <Plus size={16} className="mr-1.5" /> 添加用例
                 </button>
                 <button className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm flex items-center outline-none transition-colors" onClick={handleRun}>
                   <Play size={16} className="mr-1.5" /> 运行 Benchmark
                 </button>
               </div>
            </div>
            
            <div className="flex-1 overflow-auto p-0 custom-scrollbar">
               <table className="w-full text-sm text-left whitespace-nowrap min-w-[800px]">
                 <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 sticky top-0 shadow-sm z-10">
                   <tr>
                     <th className="px-6 py-4 font-bold w-16 text-center">序号</th>
                     <th className="px-6 py-4 font-bold w-1/3">自然语言问题</th>
                     <th className="px-6 py-4 font-bold">Ground Truth SQL</th>
                     <th className="px-6 py-4 font-bold text-center">当前状态</th>
                   </tr>
                 </thead>
                 <tbody className="divide-y divide-slate-100">
                   {activeQuestions.map((q, i) => (
                     <tr key={q.id} className="hover:bg-blue-50/50 transition-colors cursor-pointer group" onClick={handleRun}>
                       <td className="px-6 py-5 font-mono text-xs text-slate-500 text-center font-medium">
                         <div className="flex flex-col items-center gap-1.5">
                           <span>{i+1}</span>
                           <button onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: q.id, name: q.text, type: 'evaluation_case', tokenEstimate: 0.6} } })); showToast?.('已加入对话上下文'); }} className="text-[10px] text-blue-600 border border-blue-200 bg-blue-50 px-1.5 py-0.5 rounded hover:bg-blue-100 outline-none transition-colors" title="加入上下文">加入</button>
                         </div>
                       </td>
                       <td className="px-6 py-5 font-medium text-slate-900 whitespace-normal min-w-[250px] leading-relaxed">{q.text}</td>
                       <td className="px-6 py-5 font-mono text-xs text-blue-700 max-w-[300px] truncate" title={q.sql}>{q.sql}</td>
                       <td className="px-6 py-5 text-center">
                         {q.status === 'pass' ? <span className="bg-green-50 text-green-700 border border-green-200 px-2.5 py-1 rounded text-[11px] font-bold flex items-center justify-center w-fit mx-auto"><CheckCircle2 size={12} className="mr-1.5"/> Pass</span> : 
                          q.status === 'fail' ? <span className="bg-red-50 text-red-700 border border-red-200 px-2.5 py-1 rounded text-[11px] font-bold flex items-center justify-center w-fit mx-auto"><AlertTriangle size={12} className="mr-1.5"/> Fail</span> :
                          <span className="bg-slate-100 text-slate-600 border border-slate-200 px-2.5 py-1 rounded text-[11px] font-bold flex items-center justify-center w-fit mx-auto">Untested</span>}
                       </td>
                     </tr>
                   ))}
                 </tbody>
               </table>
            </div>
          </div>
        )}

        {view === 'add_question' && (
          <div className="max-w-4xl mx-auto w-full bg-white border border-slate-200 rounded-2xl shadow-sm p-6 md:p-10 animate-in slide-in-from-bottom-4 mb-20">
            <div className="flex items-center mb-8 bg-slate-50 p-4 rounded-xl border border-slate-100">
              <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shrink-0 shadow-sm transition-colors", step >= 1 ? "bg-blue-600 text-white ring-4 ring-blue-100" : "bg-white text-slate-400 border border-slate-200")}>1</div>
              <div className="ml-3 mr-4 font-bold text-slate-800 text-sm">问题与 SQL (Step 1)</div>
              <div className={cn("flex-1 h-1 rounded-full", step >= 2 ? "bg-blue-600" : "bg-slate-200")}></div>
              <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ml-4 shrink-0 shadow-sm transition-colors", step >= 2 ? "bg-blue-600 text-white ring-4 ring-blue-100" : "bg-white text-slate-400 border border-slate-200")}>2</div>
              <div className="ml-3 font-bold text-slate-800 text-sm">期望输出验证 (Step 2)</div>
            </div>

            {step === 1 ? (
              <div className="space-y-6 animate-in slide-in-from-right-4">
                <div>
                  <label className="block text-sm font-bold text-slate-800 mb-2">自然语言问题 (Natural Language)</label>
                  <input type="text" value={newQText} onChange={e => setNewQText(e.target.value)} placeholder="例如：2023年华东区销量前三的门店是？" className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:border-blue-500 outline-none transition-all shadow-sm" />
                </div>
                <div>
                  <div className="flex justify-between items-center mb-2">
                    <label className="block text-sm font-bold text-slate-800">Ground Truth SQL (评测标准答案)</label>
                    <button onClick={() => {
                      if (!newQText) { showToast?.('请先输入自然语言问题'); return; }
                      showToast?.('AI 正在基于上下文生成 SQL');
                      setTimeout(() => setNewQSql("SELECT region, SUM(sales) FROM orders GROUP BY region"), 1000);
                    }} className="text-xs text-purple-700 font-bold flex items-center bg-purple-50 border border-purple-200 px-3 py-1.5 rounded-lg transition-colors shadow-sm outline-none hover:bg-purple-100"><Wand2 size={14} className="mr-1.5"/> AI 辅助生成</button>
                  </div>
                  <textarea value={newQSql} onChange={e => setNewQSql(e.target.value)} rows={5} className="w-full font-mono border border-slate-300 rounded-xl px-4 py-3 text-[13px] focus:border-blue-500 outline-none bg-slate-50 focus:bg-white transition-all shadow-sm custom-scrollbar leading-relaxed" placeholder="SELECT * FROM ..."></textarea>
                </div>
                
                {newQSql && (
                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 animate-in fade-in slide-in-from-top-2">
                     <div className="flex justify-between items-center mb-4">
                       <span className="text-sm font-bold text-slate-800 flex items-center"><CheckCircle2 size={18} className="mr-2 text-green-600"/> 语法校验与预览</span>
                       <button onClick={() => showToast?.('预览查询已执行，返回 2 行数据。')} className="text-xs bg-white border border-slate-300 px-4 py-2 rounded-lg shadow-sm hover:bg-slate-50 font-bold outline-none">执行查询测试</button>
                     </div>
                     <table className="w-full text-sm text-left border border-slate-200 rounded-lg bg-white overflow-hidden shadow-sm">
                       <thead className="bg-slate-100 text-slate-600 font-semibold border-b border-slate-200"><tr><th className="px-4 py-2.5">region</th><th className="px-4 py-2.5 border-l border-slate-200">SUM(sales)</th></tr></thead>
                       <tbody className="divide-y divide-slate-100">
                         <tr className="hover:bg-slate-50"><td className="px-4 py-2.5">华东区</td><td className="px-4 py-2.5 border-l border-slate-200 font-mono text-slate-700">45000</td></tr>
                         <tr className="hover:bg-slate-50"><td className="px-4 py-2.5">华北区</td><td className="px-4 py-2.5 border-l border-slate-200 font-mono text-slate-700">32000</td></tr>
                       </tbody>
                     </table>
                  </div>
                )}
                
                <div className="flex justify-between items-center pt-6 border-t border-slate-100 mt-8">
                  <button className="text-slate-500 hover:text-blue-600 font-bold text-sm outline-none flex items-center"><Upload size={16} className="mr-2"/> CSV 批量导入用例</button>
                  <button className="bg-blue-600 hover:bg-blue-700 transition-colors text-white px-8 py-3 rounded-xl text-sm font-bold shadow-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50" disabled={!newQText || !newQSql} onClick={() => setStep(2)}>下一步</button>
                </div>
              </div>
            ) : (
              <div className="space-y-6 animate-in slide-in-from-right-4">
                <div>
                  <label className="block text-sm font-bold text-slate-800 mb-2">期望的输出验证 / 断言 (Expected Assertions)</label>
                  <textarea value={newQExpected} onChange={e => setNewQExpected(e.target.value)} rows={3} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm focus:border-blue-500 outline-none placeholder:text-slate-400 shadow-sm leading-relaxed" placeholder="例如：确保结果是按降序排列的二维表格，且必须包含特定列..."></textarea>
                </div>
                <div className="grid grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">允许的误差范围 (Tolerance)</label>
                    <select value={newQTolerance} onChange={e=>setNewQTolerance(e.target.value)} className="w-full border border-slate-300 rounded-xl px-4 py-3.5 text-sm outline-none bg-white shadow-sm focus:border-blue-500 font-medium">
                      <option>精确匹配 (0 容差)</option>
                      <option>允许结果顺乱序</option>
                      <option>浮点数误差 &lt; 0.1%</option>
                    </select>
                  </div>
                  <div>
                     <label className="block text-sm font-bold text-slate-800 mb-2">测试用例标签与权重 (Tags / Weight)</label>
                     <input type="text" value={newQTags} onChange={e=>setNewQTags(e.target.value)} placeholder="例如：高优, 财务类" className="w-full border border-slate-300 rounded-xl px-4 py-3.5 text-sm outline-none bg-white shadow-sm focus:border-blue-500" />
                  </div>
                </div>
                <div className="flex justify-end space-x-4 pt-8 border-t border-slate-100 mt-8">
                  <button className="px-6 py-3 bg-white border border-slate-300 text-slate-700 rounded-xl text-sm font-bold hover:bg-slate-50 outline-none focus:ring-2 focus:ring-slate-200 shadow-sm" onClick={() => setStep(1)}>返回上一步</button>
                  <button className="px-8 py-3 bg-blue-600 text-white rounded-xl text-sm font-bold shadow-sm hover:bg-blue-700 outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50" disabled={!newQExpected} onClick={saveNewQuestion}>完成并保存用例</button>
                </div>
              </div>
            )}
          </div>
        )}

        {view === 'run' && (
          <div className="max-w-7xl mx-auto w-full flex flex-col h-full min-h-[700px] animate-in fade-in">
             <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-sm mb-6 flex flex-col md:flex-row md:items-center justify-between shrink-0 gap-6">
                <div className="flex-1 min-w-0">
                   <div className="flex flex-wrap items-center mb-3 gap-3">
                     <h2 className="text-xl font-bold text-slate-900 truncate">评测运行详情</h2>
                     {runStatus === 'running' ? (
                       <span className="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-xs font-bold flex items-center border border-blue-200 shadow-sm"><Loader2 size={14} className="animate-spin mr-1.5"/> 评测进行中...</span>
                     ) : runStatus === 'done' ? (
                       <span className="bg-emerald-50 text-emerald-800 px-3 py-1 rounded-full text-xs font-bold flex items-center border border-emerald-200 shadow-sm"><CheckCircle2 size={14} className="mr-1.5"/> 评测完成</span>
                     ) : null}
                   </div>
                   {runStatus === 'running' && (
                     <div className="w-full max-w-xl mt-5">
                       <div className="flex justify-between text-xs font-bold text-slate-600 mb-2"><span>运行进度</span><span>{runProgress}%</span></div>
                       <div className="w-full h-3 bg-slate-100 rounded-full overflow-hidden shadow-inner"><div className="h-full bg-blue-600 transition-all duration-300" style={{width: `${runProgress}%`}}></div></div>
                     </div>
                   )}
                   {runStatus === 'done' && (
                     <div className="flex flex-wrap items-center gap-6 mt-4 text-sm bg-slate-50 p-4 rounded-xl border border-slate-100">
                       <div className="flex flex-col"><span className="text-[11px] text-slate-500 font-bold uppercase tracking-wider mb-1">准确率 (Accuracy)</span><span className={cn("text-2xl font-bold tabular-nums", activeQuestions.some(q=>q.status==='fail') ? "text-amber-500" : "text-green-600")}>{Math.round(((activeQuestions.filter(q=>q.status==='pass').length)/activeQuestions.length)*100)}%</span></div>
                       <div className="w-px h-10 bg-slate-200"></div>
                       <div className="flex flex-col"><span className="text-[11px] text-slate-500 font-bold uppercase tracking-wider mb-1">耗时 (Latency)</span><span className="text-xl font-bold text-slate-800 tabular-nums">2.1s</span></div>
                       <div className="w-px h-10 bg-slate-200"></div>
                       <div className="flex flex-col"><span className="text-[11px] text-slate-500 font-bold uppercase tracking-wider mb-1">失败项目 (Failures)</span><span className={cn("text-xl font-bold tabular-nums", activeQuestions.some(q=>q.status==='fail') ? "text-red-600" : "text-slate-800")}>{activeQuestions.filter(q=>q.status==='fail').length} / {activeQuestions.length}</span></div>
                     </div>
                   )}
                </div>
                <div>
                   {runStatus === 'running' ? (
                     <button className="bg-white border border-red-200 text-red-600 hover:bg-red-50 px-6 py-3 rounded-xl text-sm font-bold shadow-sm transition-colors outline-none" onClick={() => setRunStatus('stopped')}>停止运行</button>
                   ) : selectedFailed.length > 0 ? (
                     <button className="bg-blue-600 text-white hover:bg-blue-700 px-6 py-3 rounded-xl text-sm font-bold shadow-md transition-colors flex items-center outline-none focus:ring-2 focus:ring-blue-500 ring-offset-2 animate-in zoom-in-95" onClick={() => setFixState('plan')}>
                       <Wand2 size={18} className="mr-2" /> 批量修复失败项 (Fix {selectedFailed.length} Items)
                     </button>
                   ) : null}
                </div>
             </div>

             {/* Fix Plan Process Modal Overlay */}
             {fixState !== 'idle' && (
               <div className="mb-6 border-2 border-blue-500 rounded-2xl bg-white shadow-xl overflow-hidden animate-in slide-in-from-top-4 z-20 relative">
                 <div className="bg-blue-50 p-5 border-b border-blue-100 flex justify-between items-center">
                   <h3 className="font-bold text-blue-900 text-lg flex items-center"><Wand2 size={20} className="mr-2 text-blue-600"/> AI 修复闭环验证引擎 (Fix Plan)</h3>
                   {fixState === 'plan' && <button onClick={() => setFixState('idle')} className="text-blue-400 hover:text-blue-700 bg-white p-1 rounded-lg border border-blue-200"><X size={18}/></button>}
                 </div>
                 {fixState === 'plan' && (
                   <div className="p-6 md:p-8">
                     <p className="text-base text-slate-800 font-bold mb-4">即将对 {selectedFailed.length} 项失败用例执行修复计划：</p>
                     <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6 shadow-sm">
                       <div className="flex items-start"><CheckCircle2 size={16} className="text-blue-600 mr-2 mt-0.5" /> <span className="flex-1 font-medium text-slate-700">修正模型底层逻辑：为 <code className="bg-slate-100 text-pink-600 px-1.5 py-0.5 rounded border border-slate-200 font-mono text-xs">COUNT(return_id)/COUNT(order_id)</code> 添加完整的除零保护 <code className="bg-slate-100 text-green-600 px-1.5 py-0.5 rounded border border-slate-200 font-mono text-xs">NULLIF(..., 0)</code>，并更新映射依赖。</span></div>
                     </div>
                     <div className="flex items-center text-sm text-amber-800 bg-amber-50 p-4 rounded-xl border border-amber-200 mb-6">
                       <AlertTriangle size={18} className="mr-2 shrink-0 text-amber-600"/> 
                       <span className="font-medium">修复应用后，将自动对所有受影响的下游用例进行安全局部回归，跳过无关用例，以加速验证且确保不产生二次退化。</span>
                     </div>
                     <div className="flex justify-end">
                       <button onClick={confirmFix} className="bg-blue-600 text-white px-6 py-3 rounded-xl font-bold hover:bg-blue-700 shadow-md">Apply & Regress (应用并回归)</button>
                     </div>
                   </div>
                 )}
                 {fixState === 'applying' && (
                   <div className="p-12 flex flex-col items-center justify-center">
                     <div className="relative mb-6">
                       <div className="w-16 h-16 border-4 border-blue-100 rounded-full"></div>
                       <div className="w-16 h-16 border-4 border-blue-600 rounded-full border-t-transparent animate-spin absolute inset-0"></div>
                       <Wand2 size={24} className="text-blue-600 absolute inset-0 m-auto"/>
                     </div>
                     <div className="text-lg font-bold text-slate-800 mb-2">正在安全应用补丁并执行局部回归...</div>
                     <div className="text-sm font-medium text-slate-500">仅重跑受修改影响的用例 (Skipping unchanged context)</div>
                   </div>
                 )}
                 {fixState === 'done' && (
                   <div className="p-8 text-center bg-green-50/50">
                     <div className="w-16 h-16 bg-green-100 text-green-600 rounded-full flex items-center justify-center mx-auto mb-4 shadow-sm"><CheckCircle2 size={32}/></div>
                     <div className="text-xl font-bold text-slate-800 mb-2">局部回归验证 100% 通过！</div>
                     <div className="text-sm text-slate-600 font-medium mb-8">修复已成功，受影响用例测试已全量转绿。</div>
                   </div>
                 )}
               </div>
             )}

             <div className="flex-1 bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden flex flex-col min-h-[400px]">
                <div className="flex-1 overflow-hidden flex flex-col lg:flex-row">
                  {/* Left List */}
                  <div className="w-full lg:w-[360px] border-b lg:border-b-0 lg:border-r border-slate-200 bg-slate-50 shrink-0 overflow-y-auto max-h-[40vh] lg:max-h-none custom-scrollbar">
                    {activeQuestions.map((q, i) => {
                      const isEvaled = runProgress >= ((i+1)/activeQuestions.length)*100 || runStatus === 'done';
                      const isSelected = activeQuestions.some(x=>x.status==='fail') ? q.status === 'fail' : i === 0;
                      
                      return (
                        <div key={q.id} className={cn("p-5 border-b border-slate-200 cursor-pointer hover:bg-white transition-colors relative flex items-start group", isSelected && "bg-white shadow-sm z-10 before:absolute before:left-0 before:top-0 before:bottom-0 before:w-1.5 before:bg-blue-600")}>
                           {q.status === 'fail' && runStatus === 'done' && (
                             <input type="checkbox" checked={selectedFailed.includes(q.id)} onChange={(e) => { e.stopPropagation(); toggleSelectFailed(q.id); }} className="mt-1 mr-3 rounded text-blue-600 focus:ring-blue-500 cursor-pointer w-4 h-4 shadow-sm" />
                           )}
                           <div className="flex-1">
                             <div className="flex justify-between items-center mb-2">
                               <span className="text-xs font-bold text-slate-400 bg-slate-100 px-2 py-0.5 rounded">Case #{i+1}</span>
                               {isEvaled ? (
                                 q.status === 'pass' ? <CheckCircle2 size={18} className="text-green-500" /> : <AlertTriangle size={18} className="text-red-500" />
                               ) : (
                                 <div className="w-4 h-4 rounded-full border-2 border-slate-300"></div>
                               )}
                             </div>
                             <p className={cn("text-sm font-bold leading-relaxed line-clamp-2", isSelected ? "text-slate-900" : "text-slate-600")}>{q.text}</p>
                           </div>
                        </div>
                      )
                    })}
                  </div>
                  
                  {/* Right Diff Viewer */}
                  {activeQuestions.length > 0 && (
                    <div className="flex-1 bg-white flex flex-col relative min-w-0">
                       {runProgress < 100 && runStatus === 'running' ? (
                         <div className="absolute inset-0 flex items-center justify-center bg-white/70 backdrop-blur-sm z-10">
                            <div className="bg-white p-6 rounded-2xl shadow-xl border border-slate-200 flex flex-col items-center">
                              <Loader2 size={32} className="animate-spin text-blue-600 mb-4" />
                              <span className="text-base font-bold text-slate-800">正在评估并生成深度差异对比 (Diff)...</span>
                            </div>
                         </div>
                       ) : null}
                       
                       <div className="p-5 md:p-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-start justify-between bg-white shrink-0 gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center mb-2">
                               {activeQuestions.some(x=>x.status==='fail') ? <span className="bg-red-100 text-red-800 px-2.5 py-1 rounded text-xs font-bold mr-3 border border-red-200 shrink-0">Failed</span> : <span className="bg-green-100 text-green-800 px-2.5 py-1 rounded text-xs font-bold mr-3 border border-green-200 shrink-0">Passed</span>}
                               <h3 className="font-bold text-slate-900 text-base md:text-lg truncate">{activeQuestions.some(x=>x.status==='fail') ? activeQuestions.find(x=>x.status==='fail')?.text : activeQuestions[0].text}</h3>
                            </div>
                            {activeQuestions.some(x=>x.status==='fail') && <p className="text-sm font-medium text-slate-600 mt-3 bg-slate-50 p-2.5 rounded-lg border border-slate-100 leading-relaxed"><span className="font-bold text-red-600 mr-2">Fail Reason:</span> {activeQuestions.find(x=>x.status==='fail')?.reason}</p>}
                          </div>
                       </div>

                       <div className="flex-1 flex flex-col xl:flex-row overflow-hidden min-h-[400px] xl:min-h-0 bg-slate-50/50">
                         {/* Ground Truth Side */}
                         <div className="flex-1 border-b xl:border-b-0 xl:border-r border-slate-200 flex flex-col min-w-0 h-[300px] xl:h-auto bg-white shadow-sm m-4 rounded-xl overflow-hidden">
                            <div className="px-5 py-3 bg-slate-50 border-b border-slate-200 text-sm font-bold text-slate-800 shrink-0 flex items-center"><Check size={16} className="mr-2 text-green-600" /> Ground Truth 标准基线</div>
                            <div className="flex-1 p-5 bg-[#0d1117] font-mono text-sm text-slate-300 overflow-auto whitespace-pre-wrap leading-relaxed custom-scrollbar border-b border-slate-200">
                               {activeQuestions.some(x=>x.status==='fail') ? activeQuestions.find(x=>x.status==='fail')?.sql : activeQuestions[0].sql}
                            </div>
                            <div className="flex-1 bg-white p-5 overflow-auto custom-scrollbar">
                               <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">预期数据快照表现</div>
                               <table className="w-full text-sm text-left whitespace-nowrap border border-slate-200 rounded-lg overflow-hidden">
                                 <thead className="bg-slate-50 text-slate-600 font-semibold border-b border-slate-200">
                                   <tr><th className="px-4 py-2.5">region</th><th className="px-4 py-2.5 border-l border-slate-200">return_rate</th></tr>
                                 </thead>
                                 <tbody className="divide-y divide-slate-100">
                                   <tr><td className="px-4 py-2.5">华东区</td><td className="px-4 py-2.5 border-l border-slate-200 font-mono">0.021</td></tr>
                                   <tr><td className="px-4 py-2.5">华南区</td><td className="px-4 py-2.5 border-l border-slate-200 font-mono">0.015</td></tr>
                                 </tbody>
                               </table>
                            </div>
                         </div>
                         
                         {/* Generated Side */}
                         <div className="flex-1 flex flex-col min-w-0 h-[300px] xl:h-auto bg-white shadow-sm m-4 ml-0 xl:ml-4 rounded-xl overflow-hidden">
                            <div className="px-5 py-3 bg-slate-50 border-b border-slate-200 text-sm font-bold text-slate-800 shrink-0 flex items-center justify-between">
                              <div className="flex items-center"><Wand2 size={16} className="mr-2 text-blue-600" /> AI Generated SQL</div>
                              <span className="text-xs font-medium text-slate-400 bg-white px-2 py-1 rounded border border-slate-200 shadow-sm">耗时: 1.2s</span>
                            </div>
                            <div className="flex-1 p-5 bg-[#0d1117] font-mono text-sm text-slate-300 overflow-auto whitespace-pre-wrap leading-relaxed custom-scrollbar border-b border-slate-200">
                               {activeQuestions.some(x=>x.status==='fail') ? (
                                 <>SELECT region, <span className="bg-red-900/50 text-red-200 px-1.5 py-0.5 rounded border border-red-500/50 shadow-sm font-bold underline decoration-red-500 decoration-wavy">COUNT(return_id)/COUNT(order_id)</span> FROM orders GROUP BY region</>
                               ) : (
                                 <>{activeQuestions[0].sql}</>
                               )}
                            </div>
                            <div className="flex-1 bg-white p-5 overflow-auto custom-scrollbar">
                               <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex justify-between items-center">
                                 <span>实际运行结果</span>
                                 {activeQuestions.some(x=>x.status==='fail') && <span className="text-red-700 bg-red-50 px-2.5 py-1 rounded-md border border-red-200 text-[11px] font-bold shadow-sm">Execution Error</span>}
                               </div>
                               {activeQuestions.some(x=>x.status==='fail') ? (
                                 <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-xl text-sm font-mono shadow-sm flex items-start">
                                   <AlertTriangle size={18} className="mr-2 shrink-0 mt-0.5"/>
                                   <div>
                                     <div className="font-bold mb-1">Error: division by zero in expression</div>
                                     <div className="text-xs text-red-600/80">The calculation COUNT(return_id)/COUNT(order_id) fails when order_id count is 0.</div>
                                   </div>
                                 </div>
                               ) : (
                                 <table className="w-full text-sm text-left whitespace-nowrap border border-slate-200 rounded-lg overflow-hidden">
                                   <thead className="bg-slate-50 text-slate-600 font-semibold border-b border-slate-200">
                                     <tr><th className="px-4 py-2.5">region</th><th className="px-4 py-2.5 border-l border-slate-200">return_rate</th></tr>
                                   </thead>
                                   <tbody className="divide-y divide-slate-100">
                                     <tr><td className="px-4 py-2.5">华东区</td><td className="px-4 py-2.5 border-l border-slate-200 font-mono">0.021</td></tr>
                                   </tbody>
                                 </table>
                               )}
                            </div>
                         </div>
                       </div>
                    </div>
                  )}
                </div>
             </div>
          </div>
        )}
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 bg-slate-900/40 z-50 flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in" onClick={(e) => { if(e.target===e.currentTarget) setShowCreateModal(false); }}>
          <form onSubmit={handleSaveSet} className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden animate-in zoom-in-95">
             <div className="p-5 border-b border-slate-100 flex justify-between items-center bg-slate-50">
               <h2 className="text-lg font-bold text-slate-900 flex items-center"><CheckCircle2 size={20} className="mr-2 text-blue-600"/>新建 Benchmark 评测集</h2>
               <button type="button" onClick={() => setShowCreateModal(false)} className="p-1 hover:bg-slate-200 rounded-lg text-slate-400 transition-colors outline-none"><X size={20}/></button>
             </div>
             <div className="p-6 space-y-5">
               <div>
                 <label className="block text-sm font-bold text-slate-800 mb-1.5">评测集名称</label>
                 <input name="name" required placeholder="如：财务看板回归集" className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 shadow-sm" />
               </div>
               <div>
                 <label className="block text-sm font-bold text-slate-800 mb-1.5">评测集说明</label>
                 <textarea name="desc" rows={2} placeholder="描述该测试集覆盖的业务范围..." className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 shadow-sm resize-none"></textarea>
               </div>
               <div className="grid grid-cols-2 gap-4">
                 <div>
                   <label className="block text-sm font-bold text-slate-800 mb-1.5">目标 Artifact / 版本</label>
                   <input name="target" placeholder="如：销售数据集 V1.0" className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 shadow-sm" />
                 </div>
                 <div>
                   <label className="block text-sm font-bold text-slate-800 mb-1.5">绑定的数据快照</label>
                   <select name="snapshot" className="w-full border border-slate-300 rounded-xl px-4 py-3.5 text-sm outline-none focus:border-blue-500 shadow-sm bg-white font-medium">
                     <option>使用最新实时数据</option>
                     <option>Snapshot_202310</option>
                   </select>
                 </div>
               </div>
               <div className="grid grid-cols-2 gap-4">
                 <div>
                   <label className="block text-sm font-bold text-slate-800 mb-1.5">评分规则</label>
                   <select name="rule" className="w-full border border-slate-300 rounded-xl px-4 py-3.5 text-sm outline-none focus:border-blue-500 shadow-sm bg-white font-medium">
                     <option>LLM 判卷 (混合匹配)</option>
                     <option>严格结构比对</option>
                   </select>
                 </div>
                 <div>
                   <label className="block text-sm font-bold text-slate-800 mb-1.5">通过阈值 (%)</label>
                   <input name="threshold" type="number" defaultValue={80} min={0} max={100} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 shadow-sm" />
                 </div>
               </div>
             </div>
             <div className="p-5 border-t border-slate-100 bg-slate-50 flex justify-end space-x-3">
               <button type="button" onClick={() => setShowCreateModal(false)} className="px-5 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-xl font-bold hover:bg-slate-50 shadow-sm">取消</button>
               <button type="submit" className="px-6 py-2.5 bg-blue-600 text-white rounded-xl font-bold hover:bg-blue-700 shadow-md">保存评测集</button>
             </div>
          </form>
        </div>
      )}

      {showSelectModal && (
        <div className="fixed inset-0 bg-slate-900/40 z-50 flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in" onClick={(e) => { if(e.target===e.currentTarget) setShowSelectModal(false); }}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95">
             <div className="p-5 border-b border-slate-100 flex justify-between items-center bg-slate-50">
               <h2 className="text-base font-bold text-slate-900">选择目标评测集</h2>
               <button onClick={() => setShowSelectModal(false)} className="p-1 hover:bg-slate-200 rounded-lg text-slate-400 transition-colors"><X size={18}/></button>
             </div>
             <div className="p-3 max-h-60 overflow-y-auto">
               {scenes.map(sc => (
                 <button key={sc.id} onClick={() => { setActiveScene(sc); setShowSelectModal(false); setView('add_question'); }} className="w-full text-left p-3 hover:bg-blue-50 rounded-xl transition-colors outline-none font-bold text-slate-800 border border-transparent hover:border-blue-200 mb-1">
                   {sc.name}
                 </button>
               ))}
               <button onClick={() => { setShowSelectModal(false); setShowCreateModal(true); }} className="w-full text-left p-3 hover:bg-slate-50 rounded-xl transition-colors outline-none font-bold text-blue-600 flex items-center border border-transparent hover:border-slate-200 mt-2">
                 <Plus size={16} className="mr-2"/> 新建评测集
               </button>
             </div>
          </div>
        </div>
      )}
    </div>
  );
}