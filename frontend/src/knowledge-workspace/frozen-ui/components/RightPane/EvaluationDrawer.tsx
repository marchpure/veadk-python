import React, { useState, useEffect } from 'react';
import { X, CheckCircle2, AlertTriangle, ShieldCheck, PieChart, Activity, Fingerprint, Accessibility, Zap, RotateCcw, Loader2 } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function EvaluationDrawer({ searchParams, setSearchParams, showToast }: any) {
  const [evaluating, setEvaluating] = useState(false);
  const [evalProgress, setEvalProgress] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [lastEvalTime, setLastEvalTime] = useState('昨天 14:30');
  
  const [applyState, setApplyState] = useState<'idle' | 'applying' | 'done'>('idle');
  const [applyProgress, setApplyProgress] = useState(0);

  const evalApplied = searchParams.get('eval_applied') === 'true';
  const currentScore = evalApplied ? 100 : 88;

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeDrawer();
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, []);

  const closeDrawer = () => {
    const p = new URLSearchParams(searchParams);
    p.delete('drawer');
    setSearchParams(p);
  };

  const startReEval = () => {
    setEvaluating(true);
    setEvalProgress(0);
    const interval = setInterval(() => {
      setEvalProgress(p => {
        if (p >= 100) {
          clearInterval(interval);
          setTimeout(() => {
            setEvaluating(false);
            setLastEvalTime('刚刚');
          }, 500);
          return 100;
        }
        return p + 20;
      });
    }, 400);
  };

  const [fixPlanState, setFixPlanState] = useState<'idle' | 'planning' | 'plan_ready' | 'applying' | 'done'>('idle');

  const initiateFixPlan = () => {
    setFixPlanState('planning');
    setTimeout(() => setFixPlanState('plan_ready'), 1500);
  };

  const applySuggestions = () => {
    setFixPlanState('applying');
    const interval = setInterval(() => {
      setApplyProgress(p => {
        if (p >= 100) {
          clearInterval(interval);
          setFixPlanState('done');
          setTimeout(() => {
            showToast('所有修复项均已通过回归验证，生成了新版本 V2.2');
            const p = new URLSearchParams(searchParams);
            p.set('eval_applied', 'true');
            p.set('version', 'v2.2');
            p.delete('drawer');
            setSearchParams(p);
          }, 1500);
          return 100;
        }
        return p + 20;
      });
    }, 500);
  };

  const dimensions = [
    { id: 'data', icon: Activity, title: '数据正确性', score: 100, status: 'pass', desc: '查询逻辑无错误，数据聚合正确。', evidence: '已检查 14 个聚合节点与 SQL 映射，未发现计算误差。' },
    { id: 'metric', icon: PieChart, title: '指标口径', score: 100, status: 'pass', desc: '指标定义与语义模型一致。', evidence: '销售额和利润指标均严格遵循 v1.2 语义模型定义。' },
    { id: 'lineage', icon: Fingerprint, title: '来源可追溯性', score: 100, status: 'pass', desc: '数据源字段映射清晰，无断链。', evidence: '图表字段可 100% 回溯至“销售数据集”。' },
    { id: 'visual', icon: Zap, title: '可视化表达', score: evalApplied ? 100 : 75, status: evalApplied ? 'pass' : 'warning', desc: evalApplied ? '配色对比度已符合企业标准。' : '图表类型适用性良好，但配色对比度可优化。', suggestion: evalApplied ? undefined : '建议将折线图颜色对比度提高以区分紧密的线。', evidence: evalApplied ? '检测到已采用高对比度调色板' : '检测到多处相邻折线对比度低于 3:1。' },
    { id: 'a11y', icon: Accessibility, title: '可访问性', score: evalApplied ? 100 : 80, status: evalApplied ? 'pass' : 'warning', desc: evalApplied ? 'Aria 标签齐备。' : '部分元素缺失 Aria 标签。', suggestion: evalApplied ? undefined : '为“筛选器”和“更多操作”补充 aria-label。', evidence: evalApplied ? '扫描未发现 Aria 缺陷' : '发现 2 处交互按钮未配置无障碍名称。' },
    { id: 'security', icon: ShieldCheck, title: '分享安全', score: 100, status: 'pass', desc: '未检出敏感字段，适合脱敏展示。', evidence: '未发现明文手机号、身份证等个人身份信息 (PII)。' }
  ];

  return (
    <div className="absolute inset-0 bg-slate-900/20 z-50 backdrop-blur-[1px] flex justify-end" onClick={(e) => { if(e.target === e.currentTarget) closeDrawer(); }}>
      <div 
        className="h-full min-h-0 flex flex-col overflow-hidden w-full md:w-[420px] bg-slate-50 shadow-2xl border-l border-slate-200 animate-in slide-in-from-right-full duration-300"
        role="dialog" aria-modal="true" aria-labelledby="eval-drawer-title"
      >
        <div className="shrink-0 flex justify-between items-center p-5 border-b border-slate-200 bg-white">
          <h2 id="eval-drawer-title" className="text-lg font-bold text-slate-900">产物质量评测</h2>
          <button onClick={closeDrawer} aria-label="关闭" title="关闭" className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors outline-none"><X size={20} /></button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          {/* Header Score Area */}
          <div className="bg-white p-8 border-b border-slate-200 flex flex-col items-center relative">
            <div className="absolute right-4 top-4 text-xs text-slate-400">上次评测: {lastEvalTime}</div>
            
            <div 
              className="relative mb-4"
              role="progressbar"
              aria-valuenow={evaluating ? evalProgress : currentScore}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <svg className="w-32 h-32 transform -rotate-90">
                <circle cx="64" cy="64" r="56" fill="transparent" stroke="#e2e8f0" strokeWidth="8" />
                <circle cx="64" cy="64" r="56" fill="transparent" stroke={evaluating ? '#3b82f6' : (currentScore === 100 ? '#10b981' : '#f59e0b')} strokeWidth="8" strokeDasharray="351" strokeDashoffset={evaluating ? 351 - (351 * evalProgress / 100) : 351 - (351 * currentScore / 100)} className="transition-all duration-300 ease-out" />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                {evaluating ? (
                  <span className="text-2xl font-bold text-blue-600 tabular-nums">{evalProgress}%</span>
                ) : (
                  <>
                    <span className="text-4xl font-bold text-slate-900 tabular-nums">{currentScore}</span>
                    <span className={cn("text-xs font-medium px-2 py-0.5 rounded mt-1", currentScore === 100 ? "text-green-600 bg-green-50" : "text-amber-600 bg-amber-50")}>
                      {currentScore === 100 ? '完美通过' : '及格可发布'}
                    </span>
                  </>
                )}
              </div>
            </div>
            
            <p className="text-sm text-slate-500 text-center px-4 leading-relaxed min-h-[40px]">
              {evalApplied ? 
                <span className="text-green-600">当前产物体验优异，满足高质量发布标准。</span> : 
                <span>当前 Dashboard 已满足基本发布要求，但存在 <span className="text-amber-600 font-medium">2 项需修复</span> 的体验建议。</span>
              }
            </p>

            <button 
              onClick={startReEval} 
              disabled={evaluating || applyState === 'applying'}
              className="mt-4 flex items-center px-4 py-2 border border-slate-200 rounded-lg text-sm font-medium text-slate-700 bg-white hover:bg-slate-50 transition-colors shadow-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            >
              <RotateCcw size={14} className={cn("mr-2", evaluating && "animate-spin text-blue-600")} />
              {evaluating ? '正在重新评测...' : '重新评测'}
            </button>
          </div>

          {/* Details */}
          <div className="p-5 space-y-3 pb-24">
            <h3 className="text-sm font-semibold text-slate-800 mb-4 px-1">六维分项报告</h3>
            {dimensions.map(dim => (
              <div key={dim.id} className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm transition-all">
                <button 
                  className="w-full px-4 py-3.5 flex items-center justify-between hover:bg-slate-50 outline-none"
                  onClick={() => setExpanded(expanded === dim.id ? null : dim.id)}
                >
                  <div className="flex items-center">
                    <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center mr-3", dim.status === 'pass' ? "bg-green-50 text-green-600" : "bg-amber-50 text-amber-600")}>
                      <dim.icon size={16} />
                    </div>
                    <span className="font-medium text-slate-800 text-sm">{dim.title}</span>
                  </div>
                  <div className="flex items-center space-x-3">
                    <span className="text-sm font-bold text-slate-700 tabular-nums">{dim.score}分</span>
                    {dim.status === 'pass' ? <CheckCircle2 size={16} className="text-green-500" /> : <AlertTriangle size={16} className="text-amber-500" />}
                  </div>
                </button>

                {expanded !== dim.id && (
                  <div className="px-4 pb-3 flex justify-between items-center w-full border-t border-slate-50 pt-2 mt-1">
                    <span className="text-xs text-slate-400 pl-8">有 {dim.suggestion ? '2' : '1'} 项详细信息可查阅</span>
                    <button className="text-[12px] text-blue-600 font-medium hover:underline outline-none px-2 py-1 rounded hover:bg-blue-50 transition-colors flex items-center" onClick={(e) => { e.stopPropagation(); setExpanded(dim.id); }}>
                      查看证据与建议 &gt;
                    </button>
                  </div>
                )}

                {expanded === dim.id && (
                  <div className="px-4 pb-4 pt-1 bg-slate-50/50 border-t border-slate-100 text-sm animate-in fade-in slide-in-from-top-2 duration-200">
                    <p className="text-slate-600 mb-3 leading-relaxed mt-2">{dim.desc}</p>
                    <div className="mb-3 p-3 bg-slate-100 border border-slate-200 rounded-lg">
                      <div className="text-xs font-semibold text-slate-700 mb-1">评测证据</div>
                      <div className="text-xs text-slate-600 leading-relaxed">{dim.evidence}</div>
                    </div>
                    {dim.suggestion && (
                      <div className="mt-3 p-3 bg-blue-50 border border-blue-100 rounded-lg">
                        <div className="text-xs font-semibold text-blue-800 mb-1">优化建议</div>
                        <div className="text-xs text-blue-700 leading-relaxed">{dim.suggestion}</div>
                      </div>
                    )}
                    <div className="mt-2 flex justify-end">
                      <button className="text-[11px] text-slate-500 font-medium hover:underline outline-none" onClick={() => setExpanded(null)}>收起详细报告</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Action Bar */}
        <div className="bg-white border-t border-slate-200 p-4 shrink-0 flex flex-col shadow-[0_-4px_10px_-5px_rgba(0,0,0,0.05)] relative overflow-hidden">
          {fixPlanState === 'planning' && (
             <div className="py-2 flex flex-col items-center justify-center text-blue-600 text-sm font-medium animate-in fade-in">
                <Loader2 size={18} className="animate-spin mb-1" /> 生成修复计划中...
             </div>
          )}
          
          {fixPlanState === 'plan_ready' && (
             <div className="w-full mb-3 p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs animate-in slide-in-from-bottom-2">
                <div className="font-semibold text-slate-800 mb-2">即将执行的修复计划：</div>
                <div className="space-y-1.5 text-slate-600">
                  <div className="flex items-start"><CheckCircle2 size={12} className="text-blue-500 mr-1.5 mt-0.5" /> <span className="flex-1">提升 3 处折线图颜色对比度，从调色板重新分配。</span></div>
                  <div className="flex items-start"><CheckCircle2 size={12} className="text-blue-500 mr-1.5 mt-0.5" /> <span className="flex-1">自动为“筛选器”按钮添加 aria-label。</span></div>
                </div>
                <div className="mt-2 text-slate-500 bg-white p-1.5 rounded border border-slate-100 flex items-center">
                  <ShieldCheck size={12} className="mr-1 text-slate-400" /> 修复将生成新版本，仅回归关联测试用例，可随时撤销。
                </div>
             </div>
          )}

          {fixPlanState === 'applying' && (
             <div className="py-2 w-full">
                <div className="flex justify-between text-xs text-blue-700 mb-1 font-medium"><span>正在应用修改并回归测试...</span><span>{applyProgress}%</span></div>
                <div className="w-full h-1.5 bg-blue-100 rounded-full overflow-hidden"><div className="h-full bg-blue-600 transition-all duration-300" style={{width: `${applyProgress}%`}}></div></div>
                <div className="mt-2 text-[10px] text-slate-500 text-center">{applyProgress < 50 ? '应用 UI 修改' : '运行局部关联评测用例...'}</div>
             </div>
          )}
          
          {(fixPlanState === 'idle' || fixPlanState === 'plan_ready') && (
            <div className="flex justify-end space-x-3 w-full">
              <button onClick={closeDrawer} className="px-4 py-2 border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors outline-none focus:ring-2 focus:ring-slate-200">
                {evalApplied ? '关闭' : '暂不处理'}
              </button>
              {!evalApplied && fixPlanState === 'idle' && (
                <button onClick={initiateFixPlan} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm outline-none focus:ring-2 focus:ring-blue-500">
                  查看 AI 修复计划
                </button>
              )}
              {!evalApplied && fixPlanState === 'plan_ready' && (
                <button onClick={applySuggestions} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm outline-none focus:ring-2 focus:ring-blue-500">
                  应用修复并回归
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}