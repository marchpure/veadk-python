import React, { useState, useEffect } from 'react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';
import { workspaceKpis, workspaceTrendData } from '../../../production/data';
import { ArrowUpRight, ArrowDownRight, Wand2, PlusSquare, X, LayoutDashboard, Clock, BellRing, Settings, CheckCircle2, AlertTriangle, Play, Check, Link as LinkIcon, User, Calendar, FileText, Activity, ShieldCheck, ChevronRight, Globe } from 'lucide-react';
import ArtifactHeader from './ArtifactHeader';
import { cn } from '../../lib/utils';
import { actionLoopStore, Todo, Review, DecisionBrief } from '../../lib/actionLoopStore';
import ActionPolicyModal from '../Modals/ActionPolicyModal';

export default function DashboardView({ fileId, isTeam = false, setSearchParams, searchParams, showToast }: any) {
  const dashTab = searchParams.get('dash_tab') || 'data';
  const editTarget = searchParams.get('edit');
  const chartTitle = searchParams.get('chartTitle') || '按周销售与利润趋势';
  const isSelectMode = searchParams.get('select_mode') === 'true';
  const isRecruitment = fileId === 'res_dash_recruitment';
  const customName = searchParams.get('custom_name');
  const isFinance = fileId === 'res_dash_finance' || fileId?.includes('finance') || customName?.includes('金融');
  
  const currentVersion = 'V2.1';
  const displayVersion = currentVersion;
  
  const dynamicTitle = customName ? customName : 
                       isFinance ? '金融行情监控看板' :
                       isRecruitment ? '全球招聘供需看板' :
                       fileId?.includes('dashboard_sales_east') ? '华东销售经营看板' : 
                       fileId?.includes('monthly') ? '月度经营复盘' : 
                       (isTeam ? 'Q3 销售总览' : '核心数据看板');

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showPolicyModal, setShowPolicyModal] = useState(false);
  const [showApproveConfirm, setShowApproveConfirm] = useState(false);

  // Local state for Todo evidence input
  const [activeTodoId, setActiveTodoId] = useState<string | null>(null);
  const [evidenceInput, setEvidenceInput] = useState('');
  const [reviewOutcome, setReviewOutcome] = useState<'有效'|'部分有效'|'无效'>('有效');
  const [reviewComment, setReviewComment] = useState('');

  // Sync ActionLoop Store
  const [loopState, setLoopState] = useState(actionLoopStore.getState());
  useEffect(() => {
    return actionLoopStore.subscribe(() => setLoopState(actionLoopStore.getState()));
  }, []);

  // Sync highlight target (e.g. from evidence chain)
  const targetIdParam = searchParams.get('highlight_target');
  const [highlightTarget, setHighlightTarget] = useState<string | null>(null);
  useEffect(() => {
    if (targetIdParam) {
      setHighlightTarget(targetIdParam);
      setTimeout(() => {
        const el = document.getElementById(`anchor_${targetIdParam}`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 300);
      const timer = setTimeout(() => setHighlightTarget(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [targetIdParam]);

  useEffect(() => {
    if (!isSelectMode) setSelectedIds([]);
    else {
      const selectedParams = searchParams.get('selected_elements');
      if (selectedParams) setSelectedIds(selectedParams.split(',').filter(Boolean));
    }
  }, [isSelectMode, searchParams]);

  const handleElementClickEvent = (e: React.MouseEvent, id: string) => {
    if (isSelectMode) {
      e.stopPropagation(); e.preventDefault();
      if (e.shiftKey) setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
      else setSelectedIds([id]);
    }
  };

  const handleElementDoubleClick = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (isTeam) return;
    const p = new URLSearchParams(searchParams);
    p.delete('select_mode'); p.set('edit', id);
    setSearchParams(p);
  };

  const elProps = (id: string, type: string, name: string, extraClass: string) => ({
    'data-element-id': id,
    'data-element-type': type,
    'data-element-name': name,
    'data-selected': isSelectMode && selectedIds.includes(id) ? 'true' : undefined,
    id: `anchor_${id}`,
    className: cn(
      extraClass,
      "relative transition-all duration-300 outline-none",
      isSelectMode && selectedIds.includes(id) && "ring-2 ring-blue-500 shadow-md",
      !isSelectMode && editTarget === id && "ring-2 ring-blue-500 shadow-md",
      highlightTarget === id && "ring-4 ring-amber-400 bg-amber-50"
    ),
    onClick: (e: React.MouseEvent) => handleElementClickEvent(e, id),
    onDoubleClick: (e: React.MouseEvent) => handleElementDoubleClick(e, id)
  });

  const generateTodo = (type: 'recruitment' | 'finance' = 'recruitment') => {
    if (type === 'finance') {
      if (loopState.todos.some(t => t.signalId === 'sig_vix_anomaly')) {
        showToast?.('该异常已存在关联的待办，已跳转至行动视图。');
        const p = new URLSearchParams(searchParams); p.set('dash_tab', 'action'); setSearchParams(p);
        return;
      }
      const newTodo: Todo = {
        id: 'todo_vix_1',
        signalId: 'sig_vix_anomaly',
        title: '评估市场波动对投资组合的影响',
        recommendedActions: ['提取昨日量化策略收益率', '临时调低高风险资产仓位', '发送全员预警邮件'],
        owner: '量化分析组',
        dueAt: new Date(Date.now() + 2*3600000).toISOString(),
        status: 'open',
        createdBy: 'agent',
        createdAt: new Date().toISOString()
      };
      actionLoopStore.setState(prev => ({ ...prev, todos: [newTodo, ...prev.todos] }));
      const p = new URLSearchParams(searchParams); p.set('dash_tab', 'action'); setSearchParams(p);
      showToast?.('待办任务已创建！');
      return;
    }

    if (loopState.todos.some(t => t.signalId === 'sig_vn_hc_anomaly')) {
      showToast?.('该异常已存在关联的待办，已跳转至行动视图。');
      const p = new URLSearchParams(searchParams);
      p.set('dash_tab', 'action');
      setSearchParams(p);
      return;
    }
    const newTodo: Todo = {
      id: 'todo_vn_hc_1',
      signalId: 'sig_vn_hc_anomaly',
      title: '核验越南销售 HC 与优先级',
      recommendedActions: ['核验 HC 来源与审批链路', '确认 18 个高优先 HC', '冻结 8 个低优先需求'],
      owner: 'Linh Nguyen',
      dueAt: new Date(Date.now() + 24*3600000).toISOString(),
      status: 'open',
      createdBy: 'agent',
      createdAt: new Date().toISOString()
    };
    actionLoopStore.setState(prev => ({ ...prev, todos: [newTodo, ...prev.todos] }));
    const p = new URLSearchParams(searchParams);
    p.set('dash_tab', 'action');
    setSearchParams(p);
    showToast?.('待办任务已创建！');
  };

  const startTodo = (id: string) => {
    actionLoopStore.setState(prev => ({
      ...prev,
      todos: prev.todos.map(t => t.id === id ? { ...t, status: 'in_progress' } : t)
    }));
  };

  const submitReview = (id: string) => {
    if (!evidenceInput.trim()) {
      showToast?.('请填写处理动作与证据后再提交');
      return;
    }
    actionLoopStore.setState(prev => ({
      ...prev,
      todos: prev.todos.map(t => t.id === id ? { ...t, status: 'pending_review', resolution: evidenceInput, evidence: evidenceInput } : t)
    }));
    setActiveTodoId(null);
    setEvidenceInput('');
    showToast?.('已提交 Review，等待验收人审批。');
    const p = new URLSearchParams(searchParams);
    p.set('dash_tab', 'review');
    setSearchParams(p);
  };

  const completeReview = (id: string) => {
    const todo = loopState.todos.find(t => t.id === id);
    if (!todo) return;
    
    const policy = loopState.policies[0];
    const reviewer = policy ? policy.reviewer : '张总监 (VP of HR)';

    const review: Review = {
      id: `rev_${Date.now()}`,
      todoId: id,
      reviewer: reviewer,
      outcome: reviewOutcome,
      comment: reviewComment || '无附加说明',
      reviewedAt: new Date().toISOString(),
      beforeMetric: '缺口 26',
      afterMetric: '缺口 8 (已调配 18)',
      evidence: todo.resolution || todo.evidence || ''
    };
    
    actionLoopStore.setState(prev => ({
      ...prev,
      reviews: [review, ...prev.reviews],
      todos: prev.todos.map(t => t.id === id ? { 
        ...t, 
        status: reviewOutcome === '无效' ? 'in_progress' : 'completed',
        evidence: reviewOutcome === '无效' ? `${t.evidence || ''}\n[Review退回]: ${reviewComment || '不满足要求，退回补证'}` : t.evidence
      } : t)
    }));
    
    setActiveTodoId(null);
    setReviewComment('');
    setReviewOutcome('有效');
    
    if (reviewOutcome === '无效') {
      showToast?.('Review 不通过，待办已退回至 In Progress，需补充证据。');
      const p = new URLSearchParams(searchParams);
      p.set('dash_tab', 'action');
      setSearchParams(p);
    } else {
      showToast?.('Review 完成，状态已更新。');
    }
  };

  // Brief Generation qualifications: Must have associated dashboard's Todo + Effective Review
  const dashboardSignals = loopState.signals.filter(s => s.dashboardId === fileId).map(s => s.id);
  const validReviewTodoIds = loopState.reviews.filter(r => r.outcome !== '无效').map(r => r.todoId);
  const eligibleTodos = loopState.todos.filter(t => dashboardSignals.includes(t.signalId) && validReviewTodoIds.includes(t.id));
  const canGenerateBrief = eligibleTodos.length > 0;

  const generateBrief = () => {
    if (!canGenerateBrief) return;
    const brief: DecisionBrief = {
      id: `brief_${Date.now()}`,
      dashboardId: fileId,
      period: '2023 Q4',
      scope: '越南销售 HC',
      basedOnTodos: eligibleTodos.map(t => t.id),
      facts: ['越南销售岗位需求本周突增 38%', '原缺口 26 人，目前已通过优先级排查削减至 8 人'],
      agentSuggestions: ['优先保障剩余的 18 个高优 HC 顺利入职', '临时将东南亚整体部分招聘资源向越南倾斜两周'],
      alternatives: ['备选方案 1：从泰国或印尼临时调派骨干人手支援', '备选方案 2：将部分基础外包岗位转为灵活雇佣模式'],
      impactRisk: '东南亚整体人力预算可能临时超标 5%',
      confidence: 'High (85%)',
      decisionMaker: 'VP of Global HR',
      status: 'draft',
      createdAt: new Date().toISOString()
    };
    actionLoopStore.setState(prev => ({ ...prev, briefs: [brief, ...prev.briefs] }));
    showToast?.('Decision Brief 生成成功。');
  };

  const requestMoreEvidence = () => {
    const brief = loopState.briefs[0];
    if (!brief) return;
    actionLoopStore.setState(prev => ({
      ...prev,
      todos: prev.todos.map(t => brief.basedOnTodos.includes(t.id) ? { 
        ...t, 
        status: 'in_progress', 
        evidence: `${t.evidence || ''}\n[要求补证]: 决策阶段要求补充更多详细分析，请更新凭证。` 
      } : t)
    }));
    showToast?.('已将对应待办退回至行动视图，要求补证。');
    const p = new URLSearchParams(searchParams);
    p.set('dash_tab', 'action');
    p.set('highlight_target', brief.basedOnTodos[0] || '');
    setSearchParams(p);
  };

  const approveDecision = () => {
    setShowApproveConfirm(false);
    actionLoopStore.setState(prev => ({
      ...prev,
      briefs: prev.briefs.map(b => ({ ...b, status: 'approved' }))
    }));
    showToast?.('该决策已正式批准生效。');
  };

  const handleAddContextChip = (type: string, data: any) => {
    const item = { id: data.id, name: data.title || data.id, type, artifactId: fileId, tokenEstimate: 0.8 };
    window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
    showToast?.(`已将 ${type} 加入上下文`);
  };

  const navigateToEvidence = (tab: string, targetId: string) => {
    const p = new URLSearchParams(searchParams);
    p.set('dash_tab', tab);
    p.set('highlight_target', targetId);
    setSearchParams(p);
  };

  const renderDataView = () => {
    if (isFinance) {
      return (
        <div className="animate-in fade-in pb-10">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-6">
            {[
              { label: '纳斯达克指数', value: '15,234.50', trend: '+1.2%', isUp: true },
              { label: '标普500', value: '4,567.80', trend: '+0.8%', isUp: true },
              { label: '比特币 (BTC)', value: '$64,230', trend: '+5.4%', isUp: true },
              { label: 'VIX 恐慌指数', value: '24.5', trend: '+15.2%', isUp: true, anomaly: true }
            ].map((k, i) => (
              <div key={i} {...elProps(`kpi_fin_${i}`, 'KPI', k.label, cn("bg-white p-5 rounded-xl border shadow-sm", k.anomaly ? "border-amber-400 bg-amber-50" : "border-slate-200"))}>
                <div className="text-sm font-medium text-slate-500 mb-2">{k.label}</div>
                <div className={cn("text-2xl font-bold mb-3 tracking-tight", k.anomaly ? "text-amber-700" : "text-slate-900")}>{k.value}</div>
                <div className="flex items-center text-xs font-semibold">
                  <span className={cn("flex items-center px-1.5 py-0.5 rounded", k.anomaly ? "bg-amber-200 text-amber-800" : (k.isUp ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"))}>
                    {k.isUp ? <ArrowUpRight size={14} className="mr-0.5" /> : <ArrowDownRight size={14} className="mr-0.5" />} {k.trend}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <div className="mb-6 flex flex-col md:flex-row gap-4">
             <div 
               {...elProps('card_vix_anomaly', 'Signal', 'VIX 指数异常', "w-full md:w-[45%] bg-amber-50 border border-amber-200 p-5 rounded-xl shadow-sm cursor-pointer group hover:bg-amber-100/70")}
               onClick={(e) => {
                 handleElementClickEvent(e, 'card_vix_anomaly');
                 handleAddContextChip('signal', { id: 'sig_vix_anomaly', title: '信号: VIX 指数飙升' });
                 const p = new URLSearchParams(searchParams); p.set('pane', 'open'); setSearchParams(p);
               }}
             >
               <div className="flex justify-between items-start mb-2">
                 <h3 className="font-bold text-amber-900 flex items-center"><AlertTriangle size={18} className="mr-2 text-amber-600"/> 异常信号识别</h3>
                 <span className="text-[10px] bg-amber-200/50 text-amber-800 px-2 py-0.5 rounded font-bold">Severity: Critical</span>
               </div>
               <p className="text-sm text-amber-800 font-medium mb-4 leading-relaxed bg-white/50 p-3 rounded-lg border border-amber-200/50">
                 全球市场 · VIX 恐慌指数单日涨幅超过 <span className="font-bold text-red-600">15.2%</span>，市场波动风险极高。
               </p>
               <div className="flex gap-2">
                 <button onClick={(e) => { e.stopPropagation(); generateTodo('finance'); }} className="text-xs bg-amber-600 text-white px-3 py-1.5 rounded-lg shadow-sm hover:bg-amber-700 font-bold outline-none flex items-center">生成待办 (Todo)</button>
                 <button onClick={(e) => { e.stopPropagation(); const p = new URLSearchParams(searchParams); p.set('modal', 'action_policy'); p.set('policy_id', 'pol_finance'); setSearchParams(p); }} className="text-xs bg-white text-amber-700 border border-amber-300 px-3 py-1.5 rounded-lg shadow-sm hover:bg-amber-50 font-bold outline-none flex items-center"><Settings size={12} className="mr-1"/> 策略配置</button>
               </div>
             </div>

             <div className="w-full md:w-[55%] bg-white border border-slate-200 p-5 rounded-xl shadow-sm flex items-center justify-center">
                <div className="text-slate-400 text-sm flex items-center"><Activity size={24} className="mr-3 text-blue-300"/> 实时行情图表区域</div>
             </div>
          </div>
        </div>
      );
    }

    if (isRecruitment) {
      return (
        <div className="animate-in fade-in pb-10">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
            {[{l: '开放 HC', v: '142', c: 'text-slate-800'}, {l: '已招', v: '89', c: 'text-green-600'}, {l: '缺口', v: '53', c: 'text-amber-600'}, {l: '平均招聘周期', v: '45 天', c: 'text-slate-800'}, {l: 'Offer 接受率', v: '82%', c: 'text-slate-800'}].map((k,i) => (
              <div key={i} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm text-center">
                <div className="text-xs text-slate-500 mb-1 font-bold">{k.l}</div>
                <div className={cn("text-xl font-bold", k.c)}>{k.v}</div>
              </div>
            ))}
          </div>

          <div className="mb-6 flex flex-col md:flex-row gap-4">
             <div 
               {...elProps('card_vn_anomaly', 'Signal', '越南招聘需求异常', "w-full md:w-[45%] bg-amber-50 border border-amber-200 p-5 rounded-xl shadow-sm cursor-pointer group hover:bg-amber-100/70")}
               onClick={(e) => {
                 handleElementClickEvent(e, 'card_vn_anomaly');
                 handleAddContextChip('signal', { id: 'sig_vn_hc_anomaly', title: '信号: 越南招聘异常' });
                 const p = new URLSearchParams(searchParams); p.set('pane', 'open'); setSearchParams(p);
               }}
             >
               <div className="flex justify-between items-start mb-2">
                 <h3 className="font-bold text-amber-900 flex items-center"><AlertTriangle size={18} className="mr-2 text-amber-600"/> 异常信号识别</h3>
                 <span className="text-[10px] bg-amber-200/50 text-amber-800 px-2 py-0.5 rounded font-bold">Severity: High</span>
               </div>
               <p className="text-sm text-amber-800 font-medium mb-4 leading-relaxed bg-white/50 p-3 rounded-lg border border-amber-200/50">
                 越南 · 销售岗位需求本周 <span className="font-bold text-red-600">+38%</span>，缺口 26，预计影响 Q4 市场拓展。
               </p>
               <div className="flex gap-2">
                 <button onClick={(e) => { e.stopPropagation(); generateTodo(); }} className="text-xs bg-amber-600 text-white px-3 py-1.5 rounded-lg shadow-sm hover:bg-amber-700 font-bold outline-none flex items-center">生成待办 (Todo)</button>
                 <button onClick={(e) => { e.stopPropagation(); const p = new URLSearchParams(searchParams); p.set('modal', 'action_policy'); p.set('policy_id', 'pol_recruitment'); setSearchParams(p); }} className="text-xs bg-white text-amber-700 border border-amber-300 px-3 py-1.5 rounded-lg shadow-sm hover:bg-amber-50 font-bold outline-none flex items-center"><Settings size={12} className="mr-1"/> 策略配置</button>
               </div>
             </div>

             <div className="w-full md:w-[55%] bg-white border border-slate-200 p-5 rounded-xl shadow-sm">
               <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center"><Activity size={16} className="mr-2 text-blue-600"/>各区域招聘缺口预警</h3>
               <ResponsiveContainer width="100%" height={150}>
                 <BarChart data={[{n:'越南', v:26, fill:'#f59e0b'}, {n:'印尼', v:12, fill:'#3b82f6'}, {n:'泰国', v:8, fill:'#3b82f6'}, {n:'大马', v:7, fill:'#3b82f6'}]} margin={{top:0,right:0,bottom:0,left:-20}}>
                   <XAxis dataKey="n" axisLine={false} tickLine={false} tick={{fontSize: 12, fill: '#64748b'}}/>
                   <YAxis axisLine={false} tickLine={false} tick={{fontSize: 12, fill: '#64748b'}}/>
                   <Tooltip cursor={{fill: '#f8fafc'}} contentStyle={{borderRadius: '8px', border: '1px solid #e2e8f0', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)'}}/>
                   <Bar dataKey="v" radius={[4,4,0,0]} barSize={36}>
                     {[{n:'越南', v:26}, {n:'印尼', v:12}, {n:'泰国', v:8}, {n:'大马', v:7}].map((entry, index) => (
                       <Cell key={`cell-${index}`} fill={entry.n === '越南' ? '#f59e0b' : '#3b82f6'} />
                     ))}
                   </Bar>
                 </BarChart>
               </ResponsiveContainer>
             </div>
          </div>
          
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
            <div className="lg:col-span-1 bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col">
              <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50"><span className="text-sm font-bold text-slate-800">全球招聘阶段漏斗</span></div>
              <div className="p-5 flex-1 flex flex-col justify-center">
                <div className="space-y-4 w-full px-2">
                  <div className="relative h-8 bg-blue-100 rounded-sm flex items-center justify-center text-xs font-bold text-blue-900 w-full">收到简历 (4521)</div>
                  <div className="relative h-8 bg-blue-200 rounded-sm flex items-center justify-center text-xs font-bold text-blue-900 w-4/5 mx-auto">初筛通过 (1204)</div>
                  <div className="relative h-8 bg-blue-300 rounded-sm flex items-center justify-center text-xs font-bold text-blue-900 w-3/5 mx-auto">面试中 (385)</div>
                  <div className="relative h-8 bg-blue-400 rounded-sm flex items-center justify-center text-xs font-bold text-white w-2/5 mx-auto">Offer 发放 (108)</div>
                  <div className="relative h-8 bg-blue-500 rounded-sm flex items-center justify-center text-xs font-bold text-white w-1/4 mx-auto">接受入职 (89)</div>
                </div>
              </div>
            </div>
            
            <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden flex flex-col">
              <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
                <span className="text-sm font-bold text-slate-800">各国家核心岗位需求明细</span>
              </div>
              <div className="overflow-x-auto w-full">
                <table className="w-full text-sm text-left whitespace-nowrap">
                  <thead className="bg-white text-slate-500 border-b border-slate-100">
                    <tr><th className="px-5 py-3 font-medium">国家</th><th className="px-5 py-3 font-medium">核心岗位</th><th className="px-5 py-3 font-medium text-right">开放 HC</th><th className="px-5 py-3 font-medium text-right">已招</th><th className="px-5 py-3 font-medium text-right">当前缺口</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    <tr className="hover:bg-amber-50 bg-amber-50/30 transition-colors group cursor-pointer" onClick={(e) => {
                       handleElementClickEvent(e, 'card_vn_anomaly');
                       handleAddContextChip('signal', { id: 'sig_vn_hc_anomaly', title: '信号: 越南招聘异常' });
                       const p = new URLSearchParams(searchParams); p.set('pane', 'open'); setSearchParams(p);
                    }}>
                      <td className="px-5 py-3.5 font-bold text-slate-800 flex items-center"><span className="w-2 h-2 rounded-full bg-amber-500 mr-2 animate-pulse"></span>越南</td>
                      <td className="px-5 py-3.5 text-slate-600">销售专员</td>
                      <td className="px-5 py-3.5 text-right font-mono text-slate-700">38</td><td className="px-5 py-3.5 text-right font-mono text-slate-700">12</td>
                      <td className="px-5 py-3.5 text-right font-mono font-bold text-red-600">26</td>
                    </tr>
                    <tr className="hover:bg-slate-50 transition-colors">
                      <td className="px-5 py-3.5 font-medium text-slate-800">印尼</td><td className="px-5 py-3.5 text-slate-600">市场拓展</td>
                      <td className="px-5 py-3.5 text-right font-mono text-slate-700">20</td><td className="px-5 py-3.5 text-right font-mono text-slate-700">8</td><td className="px-5 py-3.5 text-right font-mono text-slate-700">12</td>
                    </tr>
                    <tr className="hover:bg-slate-50 transition-colors">
                      <td className="px-5 py-3.5 font-medium text-slate-800">泰国</td><td className="px-5 py-3.5 text-slate-600">客户成功</td>
                      <td className="px-5 py-3.5 text-right font-mono text-slate-700">15</td><td className="px-5 py-3.5 text-right font-mono text-slate-700">7</td><td className="px-5 py-3.5 text-right font-mono text-slate-700">8</td>
                    </tr>
                    <tr className="hover:bg-slate-50 transition-colors">
                      <td className="px-5 py-3.5 font-medium text-slate-800">马来西亚</td><td className="px-5 py-3.5 text-slate-600">销售专员</td>
                      <td className="px-5 py-3.5 text-right font-mono text-slate-700">12</td><td className="px-5 py-3.5 text-right font-mono text-slate-700">5</td><td className="px-5 py-3.5 text-right font-mono text-slate-700">7</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      );
    }

    // Generic dashboard fallback
    return (
      <div className="animate-in fade-in space-y-6 pb-10">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6 w-full relative">
          {workspaceKpis.length === 0 ? (
            <div className="col-span-full bg-white border border-slate-200 rounded-xl p-8 text-center shadow-sm">
              <div className="text-sm font-bold text-slate-700">暂无可展示的服务端 Dashboard 数据</div>
              <p className="text-xs text-slate-500 mt-2">
                请先完成真实 Source、Golden Asset 和 Skill 执行；未收到服务端 ViewModel 前不会展示示例数据。
              </p>
            </div>
          ) : workspaceKpis.map((kpi:any, idx:number) => {
            const kpiId = `kpi_${idx}`;
            return (
              <div key={idx} {...elProps(kpiId, 'KPI', kpi.label, "bg-white p-5 rounded-xl border border-slate-200 shadow-sm")}>
                <div className="text-sm font-medium text-slate-500 mb-2">{kpi.label}</div>
                <div className="text-2xl font-bold text-slate-900 mb-3 tracking-tight">{kpi.value}</div>
                <div className="flex items-center text-xs font-semibold">
                  {kpi.trend !== '--' && (
                    <span className={cn("flex items-center px-1.5 py-0.5 rounded mr-2", kpi.isUp ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700")}>
                      {kpi.isUp ? <ArrowUpRight size={14} className="mr-0.5" /> : <ArrowDownRight size={14} className="mr-0.5" />} {kpi.trend}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
           <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center">
             <Activity size={16} className="mr-2 text-blue-600"/> {chartTitle}
           </h3>
           <div className="h-72 w-full">
             {workspaceTrendData.length === 0 ? (
               <div className="h-full flex items-center justify-center text-sm text-slate-500">
                 服务端尚未返回趋势数据
               </div>
             ) : <ResponsiveContainer width="100%" height="100%">
               <LineChart data={workspaceTrendData} margin={{ top: 10, right: 30, left: -20, bottom: 0 }}>
                 <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                 <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: '#64748b' }} dy={10} />
                 <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: '#64748b' }} />
                 <Tooltip cursor={{ stroke: '#e2e8f0', strokeWidth: 1, strokeDasharray: '4 4' }} contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                 <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                 <Line type="monotone" dataKey="sales" name="销售额" stroke="#3b82f6" strokeWidth={3} dot={false} activeDot={{ r: 6, strokeWidth: 0 }} />
                 <Line type="monotone" dataKey="profit" name="利润" stroke="#10b981" strokeWidth={3} dot={false} activeDot={{ r: 6, strokeWidth: 0 }} />
               </LineChart>
             </ResponsiveContainer>}
           </div>
        </div>
      </div>
    );
  };

  const renderActionList = (mode: 'action' | 'review') => {
    const displayTodos = loopState.todos.filter(t => 
      mode === 'action' ? ['open', 'in_progress'].includes(t.status) : ['pending_review', 'completed'].includes(t.status)
    );

    return (
    <div className="animate-in fade-in space-y-4 pb-10">
      {displayTodos.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-10 text-center shadow-sm flex flex-col items-center">
           <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mb-4 border border-slate-100"><CheckCircle2 size={32} className="text-slate-300"/></div>
           <div className="text-sm font-bold text-slate-700 mb-1">{mode === 'action' ? '当前没有需要执行的待办' : '当前没有待验收的 Review'}</div>
           <p className="text-xs text-slate-500">{mode === 'action' ? '当在数据视图识别出异常并生成待办后，会在此处集中追踪。' : '完成执行的待办将流转至此处等待 Review。'}</p>
        </div>
      ) : (
        displayTodos.map(todo => (
          <div key={todo.id} id={`anchor_${todo.id}`} className={cn("bg-white border rounded-xl p-5 shadow-sm relative group transition-colors", highlightTarget === todo.id ? "ring-2 ring-amber-400 border-transparent bg-amber-50/30" : "border-slate-200")}>
            <div className="flex justify-between items-start mb-4 border-b border-slate-100 pb-3">
              <div>
                <h3 className="font-bold text-slate-900 text-base flex items-center cursor-pointer hover:text-blue-600 outline-none" onClick={() => handleAddContextChip('todo', todo)}>
                  <LinkIcon size={16} className="mr-2 text-slate-400"/>{todo.title}
                </h3>
                <div className="text-xs text-slate-500 mt-1.5 flex items-center space-x-3">
                  <span className="flex items-center"><User size={12} className="mr-1"/>{todo.owner}</span>
                  <span className="flex items-center"><Calendar size={12} className="mr-1"/>SLA 剩余 23 小时</span>
                  <span className="bg-slate-100 px-1.5 py-0.5 rounded text-[10px]">来源: {todo.createdBy === 'agent' ? 'AI Agent' : 'Manual'}</span>
                </div>
              </div>
              <span className={cn("px-2.5 py-1 rounded text-[11px] font-bold border uppercase tracking-wide", 
                todo.status === 'open' ? "bg-slate-100 text-slate-600 border-slate-200" :
                todo.status === 'in_progress' ? "bg-blue-50 text-blue-700 border-blue-200" :
                todo.status === 'pending_review' ? "bg-amber-50 text-amber-700 border-amber-200" :
                "bg-green-50 text-green-700 border-green-200"
              )}>
                {todo.status.replace('_', ' ')}
              </span>
            </div>

            <div className="bg-slate-50 p-4 rounded-lg border border-slate-200 mb-5 shadow-inner">
              <div className="text-xs font-bold text-slate-700 mb-2 flex items-center"><Wand2 size={14} className="mr-1.5 text-purple-500"/> Agent 建议行动策略:</div>
              <ul className="list-disc pl-5 text-[13px] text-slate-600 space-y-1.5 font-medium">
                {todo.recommendedActions.map((act, i) => <li key={i}>{act}</li>)}
              </ul>
            </div>

            {todo.evidence && todo.evidence.includes('[要求补证]') && todo.status === 'in_progress' && (
               <div className="bg-red-50 border border-red-200 p-3 rounded-lg mb-4 text-xs text-red-700 flex items-start">
                 <AlertTriangle size={14} className="mr-1.5 shrink-0 mt-0.5"/>
                 <span className="font-bold">决策层或 Reviewer 要求补充证据：请在下方文本框中更新详细动作与数据后再次提交。</span>
               </div>
            )}
            
            {todo.evidence && todo.evidence.includes('[Review退回]') && todo.status === 'in_progress' && (
               <div className="bg-red-50 border border-red-200 p-3 rounded-lg mb-4 text-xs text-red-700 flex items-start">
                 <AlertTriangle size={14} className="mr-1.5 shrink-0 mt-0.5"/>
                 <span className="font-bold">被 Reviewer 标记为无效并退回，请重新补充有效证据！</span>
               </div>
            )}

            {todo.status === 'open' && (
              <button onClick={() => startTodo(todo.id)} className="bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-bold shadow-sm hover:bg-blue-700 outline-none flex items-center"><Play size={16} className="mr-1.5"/> 认领并开始处理</button>
            )}

            {todo.status === 'in_progress' && (
              <div className="space-y-4 animate-in slide-in-from-top-2">
                {activeTodoId === todo.id ? (
                  <div className="bg-white border-2 border-blue-200 p-4 rounded-xl shadow-md">
                     <div className="text-xs font-bold text-blue-800 mb-2">填写处理动作与证据：</div>
                     <textarea value={evidenceInput} onChange={e=>setEvidenceInput(e.target.value)} placeholder="示例：确认 18 个优先 HC，冻结 8 个低优先需求..." rows={3} className="w-full text-sm outline-none resize-none mb-3 bg-slate-50 p-3 rounded-lg border border-slate-200 focus:bg-white focus:border-blue-400"></textarea>
                     <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
                       <button onClick={()=>setActiveTodoId(null)} className="px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-100 rounded-lg outline-none">取消</button>
                       <button onClick={()=>submitReview(todo.id)} disabled={!evidenceInput.trim()} className="px-5 py-2 text-xs font-bold bg-blue-600 text-white rounded-lg disabled:opacity-50 shadow-sm outline-none">提交 Review</button>
                     </div>
                  </div>
                ) : (
                  <button onClick={() => { setActiveTodoId(todo.id); setEvidenceInput(todo.evidence?.replace(/\[.*?\]:.*?\n?/g, '') || ''); }} className="bg-white border-2 border-blue-500 text-blue-700 px-5 py-2.5 rounded-lg text-sm font-bold shadow-sm hover:bg-blue-50 outline-none flex items-center transition-colors"><CheckCircle2 size={16} className="mr-1.5"/> 标记完成并提交证据</button>
                )}
              </div>
            )}

            {todo.status === 'pending_review' && (
              <div className="bg-amber-50 border border-amber-200 p-5 rounded-xl mt-4 animate-in slide-in-from-top-2 shadow-inner">
                 <div className="text-sm font-bold text-amber-900 mb-3 flex items-center pb-2 border-b border-amber-200/60"><ShieldCheck size={16} className="mr-1.5"/> Reviewer 验收审批区 (模拟 {loopState.policies[0]?.reviewer || '张总监'})</div>
                 <div className="text-[13px] text-slate-700 mb-5 bg-white p-3 rounded-lg border border-amber-200 shadow-sm leading-relaxed"><span className="font-bold text-slate-800 block mb-1">提交的行动证据：</span>{todo.resolution}</div>
                 {activeTodoId === todo.id ? (
                   <div className="space-y-4 bg-white p-4 rounded-xl border border-amber-300 shadow-md">
                     <div>
                       <label className="block text-xs font-bold text-slate-700 mb-1.5">验收结论</label>
                       <select value={reviewOutcome} onChange={(e:any)=>setReviewOutcome(e.target.value)} className="w-full border border-slate-300 rounded-lg px-3 py-2.5 text-sm bg-white outline-none focus:border-amber-500 font-medium">
                         <option value="有效">有效 (通过)</option>
                         <option value="部分有效">部分有效 (勉强通过)</option>
                         <option value="无效">无效 (打回重填)</option>
                       </select>
                     </div>
                     <div>
                       <label className="block text-xs font-bold text-slate-700 mb-1.5">审批意见 (Comment)</label>
                       <input type="text" value={reviewComment} onChange={e=>setReviewComment(e.target.value)} placeholder="选填，若无效请必须说明退回理由..." className="w-full border border-slate-300 rounded-lg px-3 py-2.5 text-sm outline-none focus:border-amber-500" />
                     </div>
                     <div className="flex justify-end gap-2 pt-2">
                       <button onClick={()=>setActiveTodoId(null)} className="px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-100 rounded-lg outline-none">取消</button>
                       <button onClick={()=>completeReview(todo.id)} className="px-5 py-2 text-xs font-bold bg-amber-600 text-white rounded-lg shadow-sm hover:bg-amber-700 outline-none">确认验收结果</button>
                     </div>
                   </div>
                 ) : (
                   <button onClick={() => setActiveTodoId(todo.id)} className="text-sm bg-amber-600 text-white px-5 py-2.5 rounded-lg font-bold shadow-sm hover:bg-amber-700 outline-none flex items-center"><CheckCircle2 size={16} className="mr-1.5"/>执行 Review</button>
                 )}
              </div>
            )}

            {todo.status === 'completed' && (
              <div className="bg-green-50 p-4 rounded-xl border border-green-200 mt-4 shadow-sm relative">
                <div className="absolute right-4 top-4" title="去查看 Review 记录" onClick={() => handleAddContextChip('review', { id: `rev_${todo.id}`, title: 'Review 记录' })}>
                  <LinkIcon size={14} className="text-green-600/50 hover:text-green-700 cursor-pointer"/>
                </div>
                <div className="text-sm font-bold text-green-900 mb-3 flex items-center"><CheckCircle2 size={16} className="mr-1.5"/> 已验证完成 (Verified)</div>
                
                {(() => {
                  const review = loopState.reviews.find(r => r.todoId === todo.id);
                  return review ? (
                    <div className="space-y-2 text-[13px] text-green-900/80 bg-white p-3 rounded-lg border border-green-100">
                      <div className="flex justify-between items-center border-b border-green-50 pb-2">
                        <div><span className="font-bold">审核人：</span>{review.reviewer}</div>
                        <div className="text-xs">{review.reviewedAt.substring(0, 16).replace('T', ' ')}</div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs pb-1">
                        <div><span className="font-bold">Before：</span><span className="text-slate-500 line-through">{review.beforeMetric}</span></div>
                        <div><span className="font-bold">After：</span><span className="text-green-700 font-bold">{review.afterMetric}</span></div>
                      </div>
                      <div><span className="font-bold">Review 意见：</span>{review.comment}</div>
                      <div className="pt-2 mt-2 border-t border-green-50">
                        <span className="font-bold block mb-1">证据摘要：</span>
                        <div className="text-xs leading-relaxed text-slate-700 bg-slate-50 p-2 rounded">{review.evidence || todo.resolution}</div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-[13px] text-green-800 bg-white p-3 rounded-lg border border-green-100"><span className="font-bold">最终执行动作：</span>{todo.resolution}</div>
                  );
                })()}
              </div>
            )}
          </div>
        ))
      )}
    </div>
    );
  };

  const renderDecisionView = () => {
    const brief = loopState.briefs[0];

    if (!brief) {
      if (!canGenerateBrief) {
        return (
          <div className="bg-white border border-slate-200 rounded-xl p-12 text-center shadow-sm flex flex-col items-center">
             <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mb-4 border border-slate-100"><FileText size={32} className="text-slate-300"/></div>
             <div className="text-base font-bold text-slate-800 mb-2">决策沉淀区为空</div>
             <div className="text-sm text-slate-500 max-w-md">只有当当前看板产生的异常处理产生 <span className="font-bold text-slate-700">已验收通过 (Reviewed) 的有效待办</span> 后，才能提炼并生成综合业务决策简报 (Decision Brief)。</div>
          </div>
        );
      }
      return (
        <div className="bg-white border border-slate-200 rounded-xl p-10 shadow-sm text-center max-w-2xl mx-auto flex flex-col items-center">
           <div className="w-16 h-16 bg-slate-50 text-slate-600 border border-slate-100 rounded-full flex items-center justify-center mb-5"><FileText size={32}/></div>
           <h3 className="text-lg font-bold text-slate-900 mb-3">存在已验证的业务成果，可沉淀决策简报</h3>
           <p className="text-sm text-slate-500 mb-8 max-w-md">系统已识别到 {eligibleTodos.length} 项有效闭环的行动记录。您可以一键聚合所有行动证据与 Agent 推断，生成结构化的决策简报以供管理层批阅。</p>
           <button onClick={generateBrief} className="bg-blue-600 text-white px-8 py-3 rounded-xl text-sm font-bold shadow-md hover:bg-blue-700 outline-none flex items-center justify-center w-fit mx-auto transition-colors"><Wand2 size={16} className="mr-2"/> 生成 Decision Brief</button>
        </div>
      );
    }

    const linkedReview = loopState.reviews.find(r => brief.basedOnTodos.includes(r.todoId));
    const linkedTodo = loopState.todos.find(t => brief.basedOnTodos.includes(t.id));

    return (
      <div className="pb-10">
        <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-sm relative group animate-in slide-in-from-bottom-4">
           <button className="absolute top-6 right-6 p-2 text-slate-400 hover:text-blue-600 hover:bg-slate-50 rounded-lg transition-colors outline-none" onClick={() => handleAddContextChip('decision', brief)} title="加入上下文"><LinkIcon size={16}/></button>
           
           <div className="flex items-center justify-between mb-2">
             <h2 className="text-2xl font-bold text-slate-900 tracking-tight">业务决策备忘录 (Decision Brief)</h2>
             {brief.status === 'approved' ? (
               <span className="bg-green-100 text-green-800 px-3 py-1 rounded-lg text-xs font-bold border border-green-200 flex items-center shadow-sm"><CheckCircle2 size={14} className="mr-1.5"/> Approved</span>
             ) : (
               <span className="bg-slate-100 text-slate-600 px-3 py-1 rounded-lg text-xs font-bold border border-slate-200">Draft</span>
             )}
           </div>
           
           <div className="text-[13px] text-slate-500 mb-8 flex items-center space-x-4 border-b border-slate-100 pb-4">
             <span className="bg-slate-50 px-2 py-1 rounded border border-slate-100">范围: {brief.scope}</span> 
             <span className="bg-slate-50 px-2 py-1 rounded border border-slate-100">周期: {brief.period}</span> 
             <span className="bg-slate-50 px-2 py-1 rounded border border-slate-100 font-medium text-slate-700">待决策人: {brief.decisionMaker}</span>
           </div>
           
           <div className="space-y-8">
             <div>
               <h4 className="text-sm font-bold text-slate-900 border-l-[3px] border-slate-800 pl-3 mb-3 flex items-center">已验证事实 (Facts)</h4>
               <ul className="list-disc pl-8 text-sm text-slate-700 space-y-2">
                 {brief.facts.map((f,i) => <li key={i} className="leading-relaxed">{f}</li>)}
               </ul>
             </div>
             <div>
               <h4 className="text-sm font-bold text-blue-900 border-l-[3px] border-blue-600 pl-3 mb-3 flex items-center">Agent 核心建议 (Recommendation)</h4>
               <ul className="list-disc pl-8 text-sm text-slate-700 space-y-2">
                 {brief.agentSuggestions.map((s,i) => <li key={i} className="leading-relaxed font-medium">{s}</li>)}
               </ul>
             </div>
             <div className="bg-slate-50 border border-slate-200 p-5 rounded-xl">
               <h4 className="text-sm font-bold text-slate-800 mb-3">备选方案 (Alternatives)</h4>
               <ul className="list-disc pl-5 text-sm text-slate-600 space-y-2">
                 {brief.alternatives.map((a,i) => <li key={i}>{a}</li>)}
               </ul>
               <div className="mt-4 pt-4 border-t border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-2 text-[13px]">
                 <div><span className="font-bold text-slate-700">预计影响与风险:</span> <span className="text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-100 ml-1">{brief.impactRisk}</span></div>
                 <div><span className="font-bold text-slate-700">模型置信度:</span> <span className="font-mono bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded border border-slate-200 ml-1">{brief.confidence}</span></div>
               </div>
             </div>
             
             {/* Ontology Linkage Area */}
             <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
               <h4 className="text-sm font-bold text-slate-800 mb-3 flex items-center"><Globe size={16} className="mr-2 text-blue-600" />关联业务语义与本体</h4>
               <p className="text-[13px] text-slate-600 leading-relaxed">
                 依据知识图谱定位：<br/>
                 <span className="font-bold text-slate-700">[国家:越南]</span> 属于 <span className="font-bold text-slate-700">[大区:东南亚]</span>；<br/>
                 <span className="font-bold text-slate-700">[岗位:销售专员]</span> 关联 <span className="font-bold text-slate-700">[HC预算:Q4拓展池]</span>；<br/>
                 数据溯源自 <span className="font-bold text-slate-700">全球招聘系统 (Workday)</span>。
               </p>
             </div>

             {/* Evidence Chain Area */}
             <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 shadow-inner">
                <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">证据链溯源 (Evidence Chain)</h4>
                <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-0 overflow-x-auto custom-scrollbar pb-2">
                   <div onClick={() => navigateToEvidence('data', 'card_vn_anomaly')} className="flex items-center space-x-2 bg-white border border-slate-200 px-3 py-2 rounded-lg text-xs font-bold text-slate-700 hover:border-blue-400 hover:text-blue-600 cursor-pointer shadow-sm shrink-0 transition-colors">
                     <LayoutDashboard size={14} className="text-blue-500"/> <span>{fileId}</span>
                   </div>
                   <div className="hidden md:block w-6 h-px bg-slate-300 mx-2 shrink-0"></div>
                   <div onClick={() => navigateToEvidence('data', 'card_vn_anomaly')} className="flex items-center space-x-2 bg-white border border-slate-200 px-3 py-2 rounded-lg text-xs font-bold text-slate-700 hover:border-amber-400 hover:text-amber-700 cursor-pointer shadow-sm shrink-0 transition-colors">
                     <AlertTriangle size={14} className="text-amber-500"/> <span>Signal: {linkedTodo?.signalId.substring(0,10)}...</span>
                   </div>
                   <div className="hidden md:block w-6 h-px bg-slate-300 mx-2 shrink-0"></div>
                   <div onClick={() => navigateToEvidence('action', linkedTodo?.id || '')} className="flex items-center space-x-2 bg-white border border-slate-200 px-3 py-2 rounded-lg text-xs font-bold text-slate-700 hover:border-green-400 hover:text-green-700 cursor-pointer shadow-sm shrink-0 transition-colors">
                     <CheckCircle2 size={14} className="text-green-500"/> <span>Todo: {linkedTodo?.title}</span>
                   </div>
                   <div className="hidden md:block w-6 h-px bg-slate-300 mx-2 shrink-0"></div>
                   <div onClick={() => navigateToEvidence('action', linkedTodo?.id || '')} className="flex items-center space-x-2 bg-white border border-slate-200 px-3 py-2 rounded-lg text-xs font-bold text-slate-700 hover:border-blue-400 hover:text-blue-600 cursor-pointer shadow-sm shrink-0 transition-colors">
                     <ShieldCheck size={14} className="text-blue-500"/> <span>Review: {linkedReview?.outcome}</span>
                   </div>
                </div>
             </div>
           </div>

           {brief.status === 'draft' && (
             <div className="flex justify-end pt-6 border-t border-slate-100 mt-8 gap-3">
               <button onClick={requestMoreEvidence} className="px-5 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold shadow-sm hover:bg-slate-50 outline-none transition-colors">要求补充证据</button>
               <button onClick={() => setShowApproveConfirm(true)} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold shadow-sm hover:bg-blue-700 outline-none flex items-center transition-colors"><CheckCircle2 size={16} className="mr-1.5"/> 批准该决策 (Approve)</button>
             </div>
           )}
        </div>
        
        {showApproveConfirm && (
          <div className="fixed inset-0 bg-slate-900/40 z-[110] flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in" onClick={(e)=>{if(e.target===e.currentTarget) setShowApproveConfirm(false);}}>
             <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm overflow-hidden p-6 animate-in zoom-in-95">
                <h3 className="font-bold text-slate-900 text-lg mb-3">批准业务决策</h3>
                <p className="text-sm text-slate-600 mb-6 leading-relaxed">该操作将固化这部分事实与方案，并在行动环中被标记为已批准状态。是否确认？</p>
                <div className="flex justify-end space-x-3">
                  <button onClick={() => setShowApproveConfirm(false)} className="px-4 py-2 border border-slate-200 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 outline-none">取消</button>
                  <button onClick={approveDecision} className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-sm outline-none flex items-center"><CheckCircle2 size={14} className="mr-1.5"/> 确认批准</button>
                </div>
             </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="p-4 md:p-8 max-w-[1200px] mx-auto pb-24 w-full flex flex-col h-full overflow-hidden min-w-0">
      <ArtifactHeader 
        title={dynamicTitle} 
        typeLabel="Dashboard"
        isTeam={isTeam} 
        version={displayVersion}
        editTarget={editTarget} 
        onElementClick={(id: string) => {
          if (isTeam) return;
          const p = new URLSearchParams(searchParams); p.set('edit', id); setSearchParams(p);
        }} 
        searchParams={searchParams}
        setSearchParams={setSearchParams} 
        showToast={showToast}
      />

      <div className="flex items-center w-full mt-2 mb-6 bg-slate-50/50 p-1.5 rounded-xl border border-slate-200 shadow-sm shrink-0 overflow-x-auto custom-scrollbar">
        {[
          { id: 'data', label: '1. 数据与信号' },
          { id: 'action', label: '2. 行动与待办' },
          { id: 'review', label: '3. Review 验收' },
          { id: 'decision', label: '4. 决策沉淀' }
        ].map((tab, idx, arr) => (
          <React.Fragment key={tab.id}>
            <button 
              onClick={() => {
                const p = new URLSearchParams(searchParams); p.set('dash_tab', tab.id); setSearchParams(p);
              }}
              className={cn(
                "flex-1 px-4 py-2.5 text-sm font-bold transition-all rounded-lg outline-none whitespace-nowrap text-center", 
                dashTab === tab.id ? "bg-white text-blue-600 shadow-sm border border-slate-200/50" : "text-slate-500 hover:text-slate-800 hover:bg-slate-100/50"
              )}
            >
              {tab.label}
            </button>
            {idx < arr.length - 1 && <div className="w-6 flex items-center justify-center shrink-0 text-slate-300"><ChevronRight size={16}/></div>}
          </React.Fragment>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar relative pr-2">
        {dashTab === 'data' && renderDataView()}
        {dashTab === 'action' && renderActionList('action')}
        {dashTab === 'review' && renderActionList('review')}
        {dashTab === 'decision' && renderDecisionView()}
      </div>

      {(showPolicyModal || searchParams.get('modal') === 'action_policy') && <ActionPolicyModal onClose={() => {
        setShowPolicyModal(false);
        const p = new URLSearchParams(searchParams);
        p.delete('modal');
        p.delete('policy_id');
        setSearchParams(p);
      }} showToast={showToast} searchParams={searchParams} />}
    </div>
  );
}
