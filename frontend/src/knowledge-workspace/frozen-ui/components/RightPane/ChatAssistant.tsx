import React, { useState, useEffect, useRef } from 'react';
import { Send, Bot, User, Paperclip, CheckCircle2, CheckSquare, Loader2, X, Database, FileText, Globe, LayoutDashboard, MessageSquare, ShieldAlert, FileSpreadsheet, Plus, ChevronDown, ChevronUp, Search, Upload, Wand2, ArrowLeft, Trash2, Command, FileUp } from 'lucide-react';
import { cn } from '../../lib/utils';
import { dragStore } from '../../lib/dragStore';
import { getFullCatalog, resourceStore, connectionStore, bootstrapWorkspace, getWorkspaceAdapter } from '../../lib/store';
import { createRequestContext } from '../../../production/ports';
import { activeSkillViewRevision } from '../../../production/data';

const getChipIcon = (type: string) => {
  if (!type) return Database;
  if (type === 'table' || type === 'dataset' || type === 'schema' || type === 'connection' || type === 'field') return Database;
  if (type === 'metric' || type === 'dimension' || type === 'semantic' || type === 'semantic_model' || type === 'mdl_snippet' || type === 'relationship') return FileText;
  if (type.startsWith('kg') || type.startsWith('ontology')) return Globe;
  if (type.includes('artifact') || type.includes('element') || type === 'dashboard' || type === 'chart' || type === 'decision') return LayoutDashboard;
  if (type.startsWith('comment') || type === 'fix_plan') return MessageSquare;
  if (type.startsWith('evaluation') || type === 'review') return ShieldAlert;
  if (type === 'file' || type === 'document') return FileSpreadsheet;
  if (type === 'signal') return ShieldAlert;
  if (type === 'todo') return CheckSquare;
  return Database;
};

export default function ChatAssistant({ fileId, chatState, searchParams, setSearchParams, chatChips = [], setChatChips, showToast, isHomeChat }: any) {
  const [input, setInput] = useState('');
  const action = searchParams.get('action');
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const submissionRef = useRef(false);
  const [isFocused, setIsFocused] = useState(false);

  const [contextExpanded, setContextExpanded] = useState(false);
  const [step, setStep] = useState(1);
  const [showSelector, setShowSelector] = useState(false);
  const [selectorQuery, setSelectorQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [uploadState, setUploadState] = useState<'idle'|'parsing'|'success'>('idle');
  const [authoringDraft, setAuthoringDraft] = useState<any>(null);
  const [agentReply, setAgentReply] = useState('');
  const [agentError, setAgentError] = useState('');
  const [agentBusy, setAgentBusy] = useState(false);
  const [authoringRun, setAuthoringRun] = useState<any>(null);

  const [dragStatus, setDragStatus] = useState<string>('idle');
  const [dragMessage, setDragMessage] = useState<string>('');

  const [planDetails, setPlanDetails] = useState<{name:string, type:string, isDownstreamCreation?: boolean, stages:any[]}>({
    name: '新建产物',
    type: 'dashboard',
    isDownstreamCreation: false,
    stages: [
      { id: `st_${Date.now()}_1`, operation: 'build_skill', status: 'pending', outputType: 'skill', targetScope: 'personal', dependsOn: [] },
      { id: `st_${Date.now()}_2`, operation: 'render_artifact', status: 'pending', outputType: 'artifact', targetScope: 'personal', dependsOn: [] }
    ]
  });

  useEffect(() => {
    const unique: any[] = [];
    const map = new Map();
    let changed = false;
    for (const c of chatChips) {
      if (map.has(c.id)) {
        const existing = map.get(c.id);
        Object.assign(existing, c, { identity: existing.identity, manual: existing.manual || c.manual });
        changed = true;
      } else {
        const clone = { ...c };
        map.set(c.id, clone);
        unique.push(clone);
      }
    }
    if (changed) {
      setChatChips(unique);
    }
  }, [chatChips, setChatChips]);

  const totalTokens = chatChips.reduce((acc: number, c: any) => acc + (c.tokenEstimate || 0.5), 0);
  const currentArtifactChip = chatChips.find((c: any) => c.isResourceLevel) || chatChips.find((c: any) => c.id === fileId || c.resourceId === fileId);
  const renderAuthoringRun = () => authoringRun ? (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[11px] text-left">
      <dt className="text-slate-500">sessionId</dt>
      <dd className="truncate font-mono text-slate-700">{authoringRun.sessionId || '—'}</dd>
      <dt className="text-slate-500">traceId</dt>
      <dd className="truncate font-mono text-slate-700">{authoringRun.traceId || '—'}</dd>
      <dt className="text-slate-500">SkillDraft</dt>
      <dd className="truncate font-mono text-slate-700">
        {authoringRun.draftId ? `${authoringRun.draftId}@${authoringRun.draftRevision}` : '—'}
      </dd>
      <dt className="text-slate-500">BuildPlan</dt>
      <dd className="truncate font-mono text-slate-700">
        {authoringRun.plan?.plan_id || authoringRun.plan?.planId || '—'}
      </dd>
    </dl>
  ) : null;

  const getSuggestions = () => {
    // Check non-resource chips first if they exist (for action loop context)
    const activeChip = chatChips.find((c: any) => c.type === 'signal' || c.type === 'todo' || c.type === 'review' || c.type === 'decision') || currentArtifactChip;
    
    if (activeChip) {
      let type = activeChip.resourceKind || (activeChip.artifactType?.toLowerCase().includes('skill') ? 'skill' : activeChip.artifactType) || activeChip.type;
      if (activeChip.resourceKind === 'skill' || activeChip.type === 'skill' || activeChip.artifactType === 'skill') {
        type = 'skill';
      }
      if (type === 'signal') return ['解释异常', '生成行动建议', '创建待办'];
      if (type === 'todo') return ['总结进展', '补充证据', '提交 Review'];
      if (type === 'review') return ['比较前后指标', '识别未解决风险'];
      if (type === 'decision') return ['汇总已验证事实', '生成备选方案', '补充证据'];
      if (type === 'dashboard' || type === 'artifact') {
        if (activeChip.id === 'res_dash_recruitment' || activeChip.name?.includes('招聘')) {
          return ['分析越南招聘缺口原因', '生成填补缺口的行动建议', '汇总各国家 HC 现状'];
        }
        return ['分析各区域销售差异', '对比本月与上月趋势', '生成数据摘要'];
      }
      if (type === 'chart') return ['修改图表类型为柱状图', '调整配色对比度', '导出数据明细'];
      if (type === 'knowledge_base') return ['测试问答效果', '补充新文档来源'];
      if (type === 'document') return ['根据文档生成测验用例', '提取文档关键指标', '加入知识库中'];
      if (type === 'connection' || type === 'source' || type === 'dataset') return ['了解数据表结构', '分析此数据源关联的产物', '预览核心字段质量'];
      if (type === 'knowledge_graph' || type === 'kg') return ['基于该图谱执行推理查询', '发现并合并相似实体', '补充缺失的关系节点'];
      if (type === 'evaluation') return ['查看最新的评测维度得分', '应用并回归 AI 修复建议', '导出评测对比报告'];
      if (type === 'skill') {
        const isFinance = activeChip.name?.includes('金融') || activeChip.subtype === 'custom_http';
        const isWebApi = activeChip.name?.includes('web') || activeChip.subtype === 'web_api';
        const isSemantic = activeChip.name?.includes('semantic') || activeChip.name?.includes('语义') || activeChip.subtype === 'semantic';

        if (isFinance) return ['生成金融行情监控看板', '查询最新市场指标'];
        if (isWebApi) return ['基于 Web API 生成 HTML 报表', '查询接口状态'];
        if (isSemantic) return ['结合当前数据生成经营 Dashboard', '检查计算字段依赖', '修改净利润口径'];
      }
      if (type === 'semantic' || type === 'semantic_model') return ['结合当前数据生成经营 Dashboard', '检查计算字段依赖', '修改净利润口径'];
      return ['总结当前资源', '生成相关报告', '导出快照'];
    }
    return ['结合 Oracle 语义与 Excel 目标生成经营 Dashboard', '创建一份新的数据大盘', '生成销售数据周报', '导入本地 Excel 数据'];
  };

  const handleSuggestionClick = (s: string) => {
    if (s === '创建待办') {
       showToast?.('请通过服务端 Agent 确认后创建待办。');
       const p = new URLSearchParams(searchParams);
       p.set('file', 'res_dash_recruitment');
       p.set('dash_tab', 'action');
       setSearchParams(p);
       return;
    }

    if (['解释异常', '生成行动建议', '总结进展', '补充证据', '提交 Review', '比较前后指标', '识别未解决风险', '汇总已验证事实', '生成备选方案'].includes(s)) {
      setInput(s);
      setTimeout(() => inputRef.current?.focus(), 50);
      return;
    }

    setInput(s);
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  useEffect(() => {
    return dragStore.subscribe(() => {
      const state = dragStore.getState();
      if (state.targetId === 'chat_input') {
         setDragStatus(state.status);
         setDragMessage(state.message);
      } else if (dragStatus !== 'idle') {
         setDragStatus('idle');
         setDragMessage('');
      }
    });
  }, [dragStatus]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [chatState, input, chatChips, contextExpanded, planDetails.stages]);

  useEffect(() => {
    const pendingPrompt = searchParams.get('pending_prompt');
    if (pendingPrompt && chatState === 'generating' && !input) setInput(pendingPrompt);
  }, [searchParams, chatState, input]);

  useEffect(() => {
    if (action === 'ai_edit_element') {
      const targets = searchParams.get('target_elements')?.split(',') || [];
      const prompt = targets.length > 1 
        ? `统一调整所选 ${targets.length} 个元素的层级与间距。` 
        : `对该元素进行样式与格式优化。`;
      setInput(prompt);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
    if (action === 'open_selector') {
      setShowSelector(true);
      const p = new URLSearchParams(searchParams);
      p.delete('action');
      setSearchParams(p, { replace: true });
    }
    if (action && inputRef.current) {
      setTimeout(() => {
        inputRef.current?.focus();
        const len = inputRef.current?.value.length || 0;
        inputRef.current?.setSelectionRange(len, len);
      }, 50);
    }
  }, [action]);

  const runAgent = async (prompt: string, requestedKind: 'knowledge' | 'analysis') => {
    setAgentError('');
    try {
      const selected = new Set(chatChips.map((chip: any) => chip.id || chip.identity));
      const connectionRefs = connectionStore.getState()
        .filter((connection: any) => selected.has(connection.id))
        .flatMap((connection: any) => connection.goldenRevisionIds || [])
        .map((revision: string) => {
          const resource: any = resourceStore.getState().find((item: any) => item.goldenRevisionId === revision);
          return resource ? { kind: 'golden_asset', object_id: String(resource.assetId), revision, scope: resource.space === 'team' ? 'team' : 'personal' } : null;
        })
        .filter(Boolean);
      const resourceRefs = resourceStore.getState()
        .filter((resource: any) => selected.has(resource.id) || selected.has(resource.resourceId))
        .filter((resource: any) =>
          typeof (resource.assetId ?? resource.asset_id) === 'string' &&
          typeof (resource.goldenRevisionId ?? resource.golden_revision_id) === 'string')
        .map((resource: any) => ({
          kind: 'golden_asset',
          object_id: String(resource.assetId ?? resource.asset_id),
          revision: String(resource.goldenRevisionId ?? resource.golden_revision_id),
          scope: resource.space === 'team' ? 'team' : 'personal',
        }));
      const pinnedRefs = [...connectionRefs, ...resourceRefs].filter((ref: any, index: number, refs: any[]) =>
        refs.findIndex((item) => item.revision === ref.revision) === index);
      const viewRevision: any = activeSkillViewRevision;
      const activeElement = chatChips.find((chip: any) => chip.type === 'element');
      const commentIds = chatChips
        .filter((chip: any) => String(chip.type || '').startsWith('comment'))
        .map((chip: any) => String(chip.id || chip.identity))
        .filter(Boolean);
      const viewOwner = String(viewRevision?.skillRevisionId ?? viewRevision?.skill_revision_id ?? '');
      const currentSkillId =
        authoringDraft?.draft_id ||
        (viewOwner.includes(':') ? viewOwner.slice(0, viewOwner.lastIndexOf(':')) : viewOwner) ||
        (currentArtifactChip?.resourceKind === 'skill_draft' ? currentArtifactChip.id : undefined);
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.start',
        payload: {
          prompt,
          resourceRefs: pinnedRefs,
          fixedRevisions: pinnedRefs.map((ref: any) => ref.revision),
          requestedKind,
          scope: 'personal',
          displayName: prompt.slice(0, 80),
          currentSkillId: currentSkillId || undefined,
          currentViewId: viewRevision?.id ? String(viewRevision.id) : undefined,
          currentComponentId: activeElement?.id ? String(activeElement.id) : undefined,
          commentIds,
        },
      }, createRequestContext());
      const result: any = response.result ?? {};
      const operation = result.operation ?? {};
      setAuthoringRun({
        operationId: operation.operation_id,
        sessionId: operation.agent_execution?.session_id,
        traceId: operation.agent_execution?.trace_id ?? operation.trace_id,
        draftId: result.draft?.draft_id,
        draftRevision: result.draft?.revision,
        plan: operation.plan ?? result.draft?.plan,
      });
      const clarificationQuestions = Array.isArray(
        operation.clarificationQuestions ?? result.clarificationQuestions,
      )
        ? (operation.clarificationQuestions ?? result.clarificationQuestions)
        : [];
      if (
        response.accepted &&
        result.status === 'awaiting_input' &&
        clarificationQuestions.length > 0
      ) {
        setAgentReply(clarificationQuestions.join('\n'));
        return null;
      }
      if (!response.accepted || !result.draft) {
        throw new Error(String(result.error?.message ?? 'Agent 未返回有效响应。'));
      }
      setAuthoringDraft(result.draft);
      setAgentReply(result.draft.manifest?.description || result.operation?.summary || '已收到真实上下文，Agent 已返回可执行草稿。');
      return result.draft;
    } catch (error) {
      setAgentError(error instanceof Error ? error.message : 'Agent 请求失败。');
      return null;
    }
  };

  const executeAgent = async () => {
    if (submissionRef.current || !authoringDraft?.draft_id) {
      setAgentError('缺少服务端 SkillDraft，无法执行。');
      return false;
    }
    submissionRef.current = true;
    setAgentBusy(true);
    setAgentError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.execute',
        payload: { draftId: authoringDraft.draft_id, revision: authoringDraft.revision },
      }, createRequestContext());
      const result: any = response.result ?? {};
      const operation = result.operation ?? {};
      setAuthoringRun((previous: any) => ({
        ...previous,
        operationId: operation.operation_id ?? previous?.operationId,
        traceId: operation.trace_id ?? previous?.traceId,
        draftId: result.draft?.draft_id ?? previous?.draftId,
        draftRevision: result.draft?.revision ?? previous?.draftRevision,
        plan: operation.plan ?? result.draft?.plan ?? previous?.plan,
      }));
      if (!response.accepted || !['succeeded', 'ready_for_execution'].includes(String(result.status))) {
        throw new Error(String(result.error?.message ?? 'Runner 未确认执行成功。'));
      }
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      setAgentReply(result.operation?.summary || 'Runner 已完成执行，结果已写入服务端链路。');
      return true;
    } catch (error) {
      setAgentError(error instanceof Error ? error.message : 'Runner 执行失败。');
      return false;
    } finally {
      submissionRef.current = false;
      setAgentBusy(false);
    }
  };

  const runKnowledgeAnswer = async (prompt: string) => {
    const draft = await runAgent(prompt, 'knowledge');
    if (!draft) return;
    setAuthoringDraft(null);
    setAgentReply('');
    setAgentError('普通问答需要服务端返回 typed answer；本次仅返回 SkillDraft，未将草稿描述当作回答。');
  };

  const handleSend = async () => {
    if (
      submissionRef.current ||
      !input.trim() ||
      chatState === 'generating' ||
      chatState === 'planning'
    ) return;
    submissionRef.current = true;
    setAgentBusy(true);
    try {
    const isCreationCommand = [
      '生成金融行情监控看板', 
      '基于 Web API 生成 HTML 报表', 
      '结合当前数据生成经营 Dashboard',
      '创建一份新的数据大盘',
      '生成销售数据周报',
      '创建华东区的销售经营看板'
    ].includes(input);

    const hasTeamReadonly = chatChips.some((c:any) => c.readonly || c.type === 'team_artifact');
    const isModification = Boolean(currentArtifactChip) &&
      /(?:修改|调整|替换|改为|更新|优化|筛选|配色|布局)/i.test(input);
    const isKnowledgeCreation =
      /(?:生成|创建|构建).*(?:知识库|knowledge)/i.test(input);
    const isCreation = isCreationCommand || isModification ||
      /(?:生成|创建|构建|看板|报表|知识库|Dashboard|Skill)/i.test(input);
    
    if (hasTeamReadonly && !isCreation) {
      const teamChip = chatChips.find((c:any) => c.type === 'team_artifact' || c.readonly);
      window.dispatchEvent(new CustomEvent('request_reuse_and_edit', {
        detail: { item: teamChip, targetDir: 'p_analysis', editAction: 'ai_edit_element', targetElements: '', pendingPrompt: input }
      }));
      return;
    }
    
    const p = new URLSearchParams(window.location.search);
    
    const activeChip = chatChips.find((c:any) => ['signal', 'todo', 'review', 'decision'].includes(c.type));
    if (activeChip) {
      await runKnowledgeAnswer(input.trim());
      setInput('');
      return;
    } else if (isCreation) {
      const draft = await runAgent(
        input.trim(),
        isKnowledgeCreation ? 'knowledge' : 'analysis',
      );
      if (!draft) return;
      p.set('chat', 'planning');
      const planName = input === '生成金融行情监控看板' ? '金融行情监控看板' :
                       input === '基于 Web API 生成 HTML 报表' ? 'Web API 数据报表' :
                       input === '结合当前数据生成经营 Dashboard' ? '经营分析 Dashboard' : '新建资源产物';
      setPlanDetails({
        name: planName,
        type: 'dashboard',
        isDownstreamCreation: true,
        stages: [
          { id: `st_${Date.now()}_1`, operation: 'build_skill', status: 'pending', outputType: 'skill', targetScope: 'personal', publishPolicy: 'personal', automationPolicy: 'manual', dependsOn: [] },
          { id: `st_${Date.now()}_2`, operation: 'render_artifact', status: 'pending', outputType: 'artifact', targetScope: 'personal', publishPolicy: 'personal', automationPolicy: 'manual', dependsOn: [] }
        ]
      });
    } else {
      await runKnowledgeAnswer(input.trim());
      setInput('');
      return;
    }
    setSearchParams(p);
    } finally {
      submissionRef.current = false;
      setAgentBusy(false);
    }
  };

  const handleAddStage = () => {
    setPlanDetails(p => ({
      ...p,
      stages: [...p.stages, { id: `st_${Date.now()}`, operation: 'create_automation', status: 'pending', outputType: 'automation', targetScope: 'personal', publishPolicy: 'personal', automationPolicy: 'manual', dependsOn: [] }]
    }));
  };

  const handleRemoveStage = (id: string) => {
    setPlanDetails(p => ({
      ...p,
      stages: p.stages.filter(st => st.id !== id)
    }));
  };

  const handleStageChange = (id: string, key: string, value: any) => {
    setPlanDetails(p => ({
      ...p,
      stages: p.stages.map(st => st.id === id ? { ...st, [key]: value } : st)
    }));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    const state = dragStore.getState();
    if (state.status !== 'dragging' && state.status !== 'valid-over' && state.status !== 'invalid-over') return;
    if (!state.item) return;
    if (state.item.type === 'folder' || state.item.type === 'root' || state.item.permission === false) {
      dragStore.setState({ status: 'invalid-over', message: '无效的上下文实体', targetId: 'chat_input' });
    } else {
      dragStore.setState({ status: 'valid-over', message: '添加至上下文', targetId: 'chat_input' });
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const state = dragStore.getState();
    if (state.targetId === 'chat_input' && state.status === 'valid-over' && state.item) {
      window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: state.item } }));
      dragStore.setState({ status: 'success', targetId: null });
    } else {
      dragStore.setState({ status: 'cancelled', targetId: null });
    }
  };

  const removeChip = (id: string) => setChatChips((prev: any) => prev.filter((c: any) => c.identity !== id && c.id !== id));

  const handleRealFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    void files;
    setUploadState('idle');
    showToast?.('文件上传需要通过服务端导入链路，目前未提交。');
  };

  const visibleItems = getFullCatalog().filter((i:any) => (i.name || i.displayName || '').toLowerCase().includes(selectorQuery.toLowerCase()));

  // Home Chat mode (when fileId === 'welcome' && !chatState)
  if (isHomeChat && chatState !== 'planning' && chatState !== 'generating') {
    return (
      <div className="flex flex-col h-full min-h-0 w-full bg-white relative animate-in fade-in duration-500 justify-center overflow-hidden">
        {showSelector && (
          <div className="absolute inset-0 bg-white z-[110] flex flex-col animate-in slide-in-from-bottom-2">
            <div className="p-4 border-b border-slate-100 flex items-center justify-between bg-slate-50">
              <span className="font-bold text-slate-800 text-base">添加上下文 (Context)</span>
              <button onClick={() => { setShowSelector(false); setSelectedIds([]); }} className="p-2 text-slate-500 hover:bg-slate-200 rounded-lg outline-none"><X size={20}/></button>
            </div>
            <div className="p-4 border-b border-slate-100 flex gap-3 items-center bg-white">
              <div className="relative flex-1">
                <Search size={16} className="absolute left-3 top-3 text-slate-400" />
                <input type="text" value={selectorQuery} onChange={e=>setSelectorQuery(e.target.value)} placeholder="搜索连接、产物或图谱..." className="w-full text-sm pl-9 pr-4 py-2.5 border border-slate-200 rounded-xl outline-none focus:border-blue-500 bg-slate-50 focus:bg-white transition-colors" />
              </div>
              <label className="shrink-0 px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-slate-600 hover:bg-slate-50 cursor-pointer outline-none font-medium text-sm shadow-sm flex items-center">
                <Upload size={16} className="mr-2"/>上传
                <input type="file" className="hidden" onChange={handleRealFileUpload} accept=".csv,.md,.txt,.xlsx" />
              </label>
            </div>
            
            <div className="flex-1 overflow-y-auto p-3 space-y-1 custom-scrollbar">
              {visibleItems.map((item:any) => {
                 const Icon = getChipIcon(item.type);
                 const id = item.identity || item.id;
                 return (
                   <label key={id} className="w-full flex items-center p-3 rounded-xl text-left group hover:bg-slate-50 cursor-pointer transition-colors border border-transparent hover:border-slate-200">
                     <input type="checkbox" checked={selectedIds.includes(id)} disabled={!item.permission} onChange={(e) => {
                       if (e.target.checked) setSelectedIds([...selectedIds, id]);
                       else setSelectedIds(selectedIds.filter(x => x !== id));
                     }} className="mr-4 rounded text-blue-600 focus:ring-blue-500 disabled:opacity-50 w-4 h-4 cursor-pointer" />
                     <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-500 flex items-center justify-center mr-3 shrink-0 group-hover:bg-white group-hover:text-blue-600 group-hover:shadow-sm transition-all"><Icon size={20} /></div>
                     <div className="flex-1 min-w-0">
                       <div className="text-sm font-bold text-slate-800 truncate">{item.name || item.displayName}</div>
                       <div className="text-xs text-slate-500 truncate mt-0.5">{item.type}</div>
                     </div>
                   </label>
                 )
              })}
            </div>

            <div className="p-4 border-t border-slate-100 bg-slate-50 flex justify-end gap-3 shrink-0">
              <button onClick={() => { setShowSelector(false); setSelectedIds([]); }} className="px-5 py-2.5 border border-slate-300 text-slate-700 bg-white rounded-xl text-sm font-bold hover:bg-slate-50 outline-none shadow-sm">取消</button>
              <button onClick={() => {
                selectedIds.forEach(id => {
                  const item = getFullCatalog().find((i:any) => i.identity === id || i.id === id);
                  if (item && item.permission) window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
                });
                setShowSelector(false); setSelectedIds([]);
              }} disabled={selectedIds.length === 0} className="px-6 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-bold hover:bg-blue-700 disabled:opacity-50 outline-none shadow-sm flex items-center">加入上下文 ({selectedIds.length})</button>
            </div>
          </div>
        )}

        <div className="max-w-2xl mx-auto w-full px-6 flex flex-col items-center">
          <div className="text-center mb-6">
            <h1 className="text-xl font-medium text-slate-700 tracking-tight mb-2 opacity-80">Knowledge Asset</h1>
            {agentError && <div role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{agentError}</div>}
            {agentReply && <div className="max-w-xl mx-auto text-left text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-xl px-4 py-3">{agentReply}</div>}
            {renderAuthoringRun()}
          </div>

          <div 
            className={cn(
              "w-full bg-white border rounded-2xl shadow-sm transition-all duration-300 relative group flex flex-col focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500",
              "border-slate-200"
            )}
          >
            {/* Context chips area within the input box */}
            {chatChips.length > 0 && (
              <div className="px-4 pt-3 flex gap-2 overflow-x-auto custom-scrollbar whitespace-nowrap">
                {chatChips.map((chip:any) => (
                  <div key={chip.identity} className="flex items-center bg-slate-50/80 border border-slate-200 rounded-lg px-2 py-1 text-[11px] text-slate-600 shrink-0">
                    {React.createElement(getChipIcon(chip.type), { size: 12, className: 'mr-1.5 opacity-50 shrink-0' })}
                    <span className="truncate max-w-[150px] font-medium">{chip.name}</span>
                    <button onClick={(e) => { e.stopPropagation(); removeChip(chip.identity); }} className="ml-2 opacity-50 hover:opacity-100 hover:text-red-500 outline-none shrink-0 transition-opacity"><X size={12}/></button>
                  </div>
                ))}
              </div>
            )}
            
            <textarea 
              ref={inputRef}
              aria-label="分析助手输入框"
              className="w-full bg-transparent border-none outline-none resize-none px-4 py-3 text-sm text-slate-800 leading-relaxed min-h-[90px] placeholder:text-slate-400"
              placeholder="输入分析指令，或添加数据上下文..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              onCompositionStart={() => { composingRef.current = true; }}
              onCompositionEnd={() => { composingRef.current = false; }}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !composingRef.current) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              disabled={agentBusy}
            />
            
            <div className="px-3 py-2 flex items-center justify-between mt-auto">
              <div className="flex items-center space-x-1">
                <button 
                  onClick={() => setShowSelector(true)} 
                  className="px-2 py-1.5 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors outline-none flex items-center text-xs font-medium"
                  title="添加资源"
                >
                  <Plus size={14} className="mr-1"/> 资源
                </button>
                <label className="px-2 py-1.5 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors outline-none flex items-center text-xs font-medium cursor-pointer">
                  <Upload size={14} className="mr-1"/> 文件
                  <input type="file" className="hidden" onChange={handleRealFileUpload} accept=".csv,.md,.txt,.xlsx" />
                </label>
              </div>
              <button 
                onClick={() => void handleSend()} 
                disabled={agentBusy || (!input.trim() && chatChips.length === 0)}
                className="bg-blue-600 text-white p-1.5 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 disabled:bg-slate-300 transition-all outline-none flex items-center justify-center transform active:scale-95"
              >
                <Send size={14} />
              </button>
            </div>
          </div>

          <div className="mt-8 flex gap-3 w-full justify-center flex-wrap">
            {["创建华东区的销售经营看板", "分析本月销售额下降原因", "基于飞书文档生成话术知识库"].map((s, i) => (
              <button 
                key={i} 
                onClick={() => setInput(s)}
                className="px-4 py-2 bg-slate-50/50 border border-slate-200 text-slate-500 text-xs rounded-full hover:bg-slate-100 hover:text-slate-700 transition-colors outline-none"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // RightPane side-chat mode
  return (
    <div className="h-full min-h-0 flex flex-col overflow-hidden bg-slate-50 relative">
      {!isHomeChat && (
        <div className="shrink-0 flex items-center justify-between px-4 py-3 bg-white border-b border-slate-200 shadow-sm z-10">
          <div className="flex items-center space-x-2 min-w-0">
             <span className="font-semibold text-slate-800 text-[13px] shrink-0">分析助手</span>
             <span className="text-slate-300">|</span>
             <div className="flex items-center min-w-0 text-xs text-slate-500">
               <span className="w-1.5 h-1.5 rounded-full bg-green-500 mr-1.5 shrink-0"></span>
               <span className="truncate max-w-[150px]" title={currentArtifactChip?.name}>{currentArtifactChip?.name || '探索'}</span>
             </div>
          </div>
          <button onClick={() => { const p = new URLSearchParams(searchParams); p.set('pane', 'closed'); setSearchParams(p); }} className="text-slate-400 hover:text-slate-600 outline-none p-1 rounded hover:bg-slate-100 transition-colors"><X size={16}/></button>
        </div>
      )}

      {showSelector && (
        <div className="absolute inset-0 bg-white z-20 flex flex-col animate-in slide-in-from-bottom-2">
          <div className="p-3 border-b border-slate-100 flex items-center justify-between bg-slate-50">
            <span className="font-medium text-slate-800 text-sm">添加上下文</span>
            <button onClick={() => { setShowSelector(false); setSelectedIds([]); }} className="p-1 text-slate-500 hover:bg-slate-200 rounded"><X size={16}/></button>
          </div>
          <div className="p-3 border-b border-slate-100 flex gap-2 items-center">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-2.5 text-slate-400" />
              <input type="text" value={selectorQuery} onChange={e=>setSelectorQuery(e.target.value)} placeholder="搜索连接、产物或图谱..." className="w-full text-xs pl-8 pr-3 py-2 border border-slate-200 rounded-lg outline-none focus:border-blue-500 bg-slate-50 focus:bg-white" />
            </div>
            <label className="shrink-0 p-2 bg-white border border-slate-200 rounded-lg text-slate-500 hover:bg-slate-50 cursor-pointer outline-none">
              <Upload size={14} />
              <input type="file" className="hidden" onChange={handleRealFileUpload} accept=".csv,.md,.txt,.xlsx" />
            </label>
          </div>
          
          <div className="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar">
            {visibleItems.map((item:any) => {
               const Icon = getChipIcon(item.type);
               const id = item.identity || item.id;
               return (
                 <label key={id} className="w-full flex items-center p-2.5 rounded-lg text-left group hover:bg-slate-50 cursor-pointer">
                   <input type="checkbox" checked={selectedIds.includes(id)} disabled={!item.permission} onChange={(e) => {
                     if (e.target.checked) setSelectedIds([...selectedIds, id]);
                     else setSelectedIds(selectedIds.filter(x => x !== id));
                   }} className="mr-3 rounded text-blue-600 focus:ring-blue-500 disabled:opacity-50" />
                   <Icon size={14} className="text-slate-400 mr-2 shrink-0" />
                   <div className="flex-1 min-w-0">
                     <div className="text-sm font-medium text-slate-800 truncate">{item.name || item.displayName}</div>
                     <div className="text-[10px] text-slate-500 truncate">{item.type}</div>
                   </div>
                 </label>
               )
            })}
          </div>

          <div className="p-3 border-t border-slate-100 bg-slate-50 flex justify-end gap-2 shrink-0">
            <button onClick={() => { setShowSelector(false); setSelectedIds([]); }} className="px-3 py-1.5 border border-slate-200 text-slate-700 bg-white rounded-md text-xs font-medium hover:bg-slate-50 outline-none">取消</button>
            <button onClick={() => {
              selectedIds.forEach(id => {
                const item = getFullCatalog().find((i:any) => i.identity === id || i.id === id);
                if (item && item.permission) window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
              });
              setShowSelector(false); setSelectedIds([]);
            }} disabled={selectedIds.length === 0} className="px-3 py-1.5 bg-blue-600 text-white rounded-md text-xs font-medium hover:bg-blue-700 disabled:opacity-50 outline-none">加入</button>
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto p-4 custom-scrollbar flex flex-col gap-5" ref={scrollRef}>
         {agentError && (
           <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
             {agentError}
           </div>
         )}
         {agentReply && (
           <div className="flex items-start gap-3">
             <div className="w-6 h-6 mt-1 rounded-full bg-slate-100 text-slate-500 flex items-center justify-center shrink-0"><Bot size={12}/></div>
             <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-2.5 text-[13px] text-slate-700 leading-relaxed max-w-[90%]">
               {agentReply}
             </div>
           </div>
         )}
         {renderAuthoringRun()}
         {chatState !== 'generating' && (
           <div className="animate-in fade-in flex items-start gap-3 w-full">
             <div className="w-6 h-6 mt-1 rounded-full bg-slate-100 text-slate-500 flex items-center justify-center shrink-0"><Bot size={12}/></div>
             <div className="flex-1 min-w-0">
               <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-2.5 text-[13px] text-slate-700 leading-relaxed mb-3 max-w-[90%] shadow-sm">
                 {isHomeChat ? '你好！请添加数据或产物作为上下文，我将为您进行深度分析。' : `你好！正在为您提供关于 ${currentArtifactChip?.name || '当前资源'} 的协助。`}
               </div>
               <div className="flex flex-col gap-2 max-w-[90%]">
                 {getSuggestions().map(s => (
                   <button key={s} onClick={() => handleSuggestionClick(s)} className="text-left text-[12px] text-slate-600 bg-white hover:bg-slate-50 border border-slate-200 px-3 py-2 rounded-lg transition-colors outline-none w-fit max-w-full truncate">{s}</button>
                 ))}
               </div>
             </div>
           </div>
         )}
         
         {(chatState === 'planning' || chatState === 'generating') && (
           <>
             <div className="animate-in fade-in flex items-start gap-3 flex-row-reverse w-full">
               <div className="w-6 h-6 mt-1 rounded-full bg-slate-200 flex items-center justify-center shrink-0 text-slate-500 text-[10px] font-medium">U</div>
               <div className="flex-1 flex flex-col items-end min-w-0">
                 <div className="bg-slate-100 text-slate-800 rounded-2xl rounded-tr-sm px-4 py-2.5 text-[13px] leading-relaxed max-w-[90%] break-words">
                   {input}
                 </div>
               </div>
             </div>
           </>
         )}

         {chatState === 'planning' && (
           <div className="animate-in fade-in flex items-start gap-3">
             <div className="w-7 h-7 rounded-full bg-slate-100 text-slate-500 flex items-center justify-center shrink-0"><Bot size={14}/></div>
             <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm p-4 shadow-sm w-full min-w-0">
               <h4 className="font-bold text-slate-800 mb-2 flex items-center"><Wand2 size={16} className="mr-2 text-purple-600"/> 多阶段产物生成计划 (Artifact Plan)</h4>
               <p className="text-xs text-slate-500 mb-4 leading-relaxed">我已为您规划好多阶段依赖的 Pipeline。您可以自由编辑 Stage 的顺序、操作和产出目标策略。</p>
               
               <div className="space-y-4">
                 <div>
                   <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">产物名称</label>
                   <input type="text" value={planDetails.name} onChange={e=>setPlanDetails(p=>({...p, name: e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 shadow-sm" />
                 </div>
                 <div>
                   <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">最终产物类型</label>
                   <select value={planDetails.type} onChange={e=>setPlanDetails(p=>({...p, type: e.target.value}))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-xs outline-none focus:border-blue-500 shadow-sm bg-white font-medium text-slate-700">
                     <option value="dashboard">Dashboard 看板</option>
                     <option value="report">HTML 报表</option>
                     <option value="chart">单图表</option>
                     <option value="semantic">Semantic 语义模型</option>
                     <option value="knowledge_base">Knowledge Base 知识库</option>
                     <option value="skill">通用 Skill 实体</option>
                   </select>
                 </div>
                 
                 <div>
                   <div className="flex justify-between items-center mb-1.5">
                     <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wider">执行阶段列表 (Stages)</label>
                     <button onClick={handleAddStage} className="text-[10px] bg-blue-50 text-blue-600 font-bold px-2 py-1 rounded hover:bg-blue-100 outline-none flex items-center"><Plus size={12} className="mr-1"/>添加 Stage</button>
                   </div>
                   <div className="space-y-2">
                     {planDetails.stages.map((stage, idx) => (
                       <div key={stage.id} className="bg-slate-50 border border-slate-200 rounded-lg p-3 shadow-sm flex flex-col gap-2 relative group">
                         <button onClick={() => handleRemoveStage(stage.id)} className="absolute right-2 top-2 text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100 outline-none"><Trash2 size={14}/></button>
                         <div className="flex items-center text-xs font-bold text-slate-800">
                           <span className="w-4 h-4 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center mr-2 text-[10px] shrink-0">{idx+1}</span>
                           <select value={stage.operation} onChange={e=>handleStageChange(stage.id, 'operation', e.target.value)} className="bg-white border border-slate-200 rounded px-2 py-1 outline-none focus:border-blue-500">
                             <option value="build_skill">构建通用 Skill (build_skill)</option>
                             <option value="compose_resources">组合与解析 (compose_resources)</option>
                             <option value="render_artifact">渲染视图产物 (render_artifact)</option>
                             <option value="create_automation">创建自动化/告警 (create_automation)</option>
                             <option value="publish_resource">发布与快照 (publish_resource)</option>
                           </select>
                         </div>
                         <div className="flex gap-2 items-center">
                           <select value={stage.outputType} onChange={e=>handleStageChange(stage.id, 'outputType', e.target.value)} className="bg-white border border-slate-200 rounded px-2 py-1 outline-none text-[10px] text-slate-600 flex-1">
                             <option value="skill">产出类型: Skill</option>
                             <option value="artifact">产出类型: Artifact</option>
                             <option value="knowledge_base">产出类型: Knowledge Base</option>
                             <option value="automation">产出类型: Automation</option>
                             <option value="publication">产出类型: Publication</option>
                           </select>
                           <select value={stage.publishPolicy} onChange={e=>handleStageChange(stage.id, 'publishPolicy', e.target.value)} className="bg-white border border-slate-200 rounded px-2 py-1 outline-none text-[10px] text-slate-600 flex-1">
                             <option value="personal">策略: 存为个人草稿</option>
                             <option value="team">策略: 存为团队快照</option>
                           </select>
                         </div>
                       </div>
                     ))}
                   </div>
                 </div>
                 
                 <div className="flex justify-end space-x-2 pt-3 border-t border-slate-100 mt-4">
                   <button onClick={() => {
                     const p = new URLSearchParams(searchParams);
                     p.delete('chat');
                     setSearchParams(p);
                   }} className="px-4 py-2 border border-slate-200 text-slate-600 bg-white rounded-lg text-xs font-bold hover:bg-slate-50 outline-none shadow-sm transition-colors">取消计划</button>
                   <button onClick={async () => {
                     if (await executeAgent()) {
                       const p = new URLSearchParams(searchParams);
                       p.delete('chat');
                       setSearchParams(p);
                     }
                   }} disabled={agentBusy} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700 disabled:opacity-50 shadow-sm outline-none flex items-center transition-colors"><CheckCircle2 size={14} className="mr-1.5"/> 顺序执行流水线 (Execute)</button>
                 </div>
               </div>
             </div>
           </div>
         )}

         {chatState === 'generating' && (
           <div className="animate-in fade-in flex items-start gap-3">
             <div className="w-7 h-7 rounded-full bg-slate-100 text-slate-500 flex items-center justify-center shrink-0"><Bot size={14}/></div>
             <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm p-4 shadow-sm min-w-[250px] flex flex-col gap-3">
               {(planDetails.stages || []).map((stage, idx) => {
                 const s = idx + 1;
                 if (step < s) return null;
                 return (
                   <div key={stage.id} className="flex flex-col gap-1.5 animate-in fade-in slide-in-from-left-2">
                     <div className="flex items-center text-xs font-medium text-slate-700">
                       {step === s ? <Loader2 size={14} className="animate-spin text-blue-600 mr-2 shrink-0"/> : <CheckCircle2 size={14} className="text-green-500 mr-2 shrink-0"/>}
                       <span className="truncate">{stage.operation}</span>
                     </div>
                     {step > s && (
                       <div className="text-[10px] text-slate-500 ml-6 flex items-center">
                         ↳ 写入 Registry: 产物 {stage.outputType} 
                         {stage.publishPolicy === 'team' && <span className="ml-1 bg-green-50 text-green-700 px-1 rounded border border-green-200">已发布团队</span>}
                       </div>
                     )}
                   </div>
                 );
               })}
               {step > (planDetails.stages || []).length && (
                 <div className="flex items-center text-xs font-medium text-slate-700 animate-in fade-in slide-in-from-left-2 pt-2 border-t border-slate-100">
                   <CheckCircle2 size={14} className="text-green-500 mr-2 shrink-0"/> 依赖构建完成，即将加载产物
                 </div>
               )}
             </div>
           </div>
         )}

      </div>

      <div className="shrink-0 relative p-3 border-t border-slate-200 bg-white">
         <div 
           className={cn("flex flex-col border rounded-xl overflow-hidden transition-all bg-white relative shadow-sm", dragStatus !== 'idle' ? "border-blue-500 ring-1 ring-blue-500" : "border-slate-200 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500")}
           onDragOver={handleDragOver}
           onDragLeave={(e) => { e.preventDefault(); if (dragStore.getState().targetId === 'chat_input') dragStore.setState({ status: 'dragging', targetId: null, message: '' }); }}
           onDrop={handleDrop}
         >
            {dragStatus === 'valid-over' && (
              <div className="absolute inset-0 flex items-center justify-center bg-blue-50/90 backdrop-blur-sm z-10 text-sm font-bold text-blue-700"><CheckCircle2 size={14} className="mr-1.5"/>{dragMessage}</div>
            )}
            {dragStatus === 'invalid-over' && (
              <div className="absolute inset-0 flex items-center justify-center bg-red-50/90 backdrop-blur-sm z-10 text-sm font-bold text-red-700"><ShieldAlert size={14} className="mr-1.5"/>{dragMessage}</div>
            )}
            
            {chatChips.length > 0 && (
              <div className="px-3 pt-2.5 flex gap-2 overflow-x-auto custom-scrollbar whitespace-nowrap">
                {chatChips.map((chip:any) => (
                  <div key={chip.identity} className="flex items-center bg-slate-50 border border-slate-200 rounded-md px-2 py-1 text-[11px] text-slate-600 shrink-0">
                    {React.createElement(getChipIcon(chip.type), { size: 10, className: 'mr-1 opacity-50 shrink-0' })}
                    <span className="truncate max-w-[120px] font-medium">{chip.name}</span>
                    <button onClick={(e) => { e.stopPropagation(); removeChip(chip.identity); }} className="ml-1.5 opacity-50 hover:opacity-100 hover:text-red-500 outline-none shrink-0 transition-opacity"><X size={10}/></button>
                  </div>
                ))}
              </div>
            )}

            <textarea 
              ref={inputRef}
              aria-label="分析助手输入框"
              className="w-full bg-transparent border-none outline-none resize-none px-3 py-2 text-[13px] leading-relaxed min-h-[50px] max-h-[160px] placeholder:text-slate-400"
              placeholder="输入修改要求或分析指令..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onCompositionStart={() => { composingRef.current = true; }}
              onCompositionEnd={() => { composingRef.current = false; }}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !composingRef.current) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              disabled={agentBusy || chatState === 'planning' || chatState === 'generating' || dragStatus !== 'idle'}
            />
            <div className="flex justify-between items-center px-2 pb-2">
               <button onClick={() => setShowSelector(true)} className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors outline-none"><Plus size={14}/></button>
               <button 
                 onClick={() => void handleSend()} 
                 disabled={agentBusy || !input.trim() || chatState === 'planning' || chatState === 'generating'}
                 className="bg-blue-600 text-white p-1.5 rounded-lg text-xs hover:bg-blue-700 disabled:opacity-50 disabled:bg-slate-300 transition-colors outline-none flex items-center justify-center shadow-sm"
               >
                 <Send size={12}/>
               </button>
            </div>
         </div>
      </div>
    </div>
  )
}
