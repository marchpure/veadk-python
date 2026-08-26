import React, { useState, useEffect, useRef } from 'react';
import { Send, Bot, CheckCircle2, CheckSquare, Loader2, X, Database, FileText, Globe, LayoutDashboard, MessageSquare, ShieldAlert, FileSpreadsheet, Plus, ChevronDown, ChevronUp, Search, Upload, Wand2, ArrowRight } from 'lucide-react';
import { cn } from '../../lib/utils';
import { dragStore } from '../../lib/dragStore';
import { getFullCatalog, resourceStore, connectionStore, bootstrapWorkspace, getWorkspaceAdapter } from '../../lib/store';
import { createRequestContext, type KnowledgeStream, type KnowledgeStreamEvent } from '../../../production/ports';
import { activeSkillViewRevision } from '../../../production/data';
import { getServerContextRef } from '../../../production/domainClient';
import type { ResourceRef } from '../../../production/generatedContracts';

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

type TimelineItem = {
  id: string;
  type:
    | 'user'
    | 'assistant_delta'
    | 'status'
    | 'tool_call'
    | 'context_revision'
    | 'clarification'
    | 'warning'
    | 'error'
    | 'stop'
    | 'retry'
    | 'resume';
  title: string;
  body?: string;
  status?: string;
  elapsedMs?: number;
};

const safeText = (value: unknown): string => {
  if (typeof value !== 'string') return '';
  return value.slice(0, 600);
};

const eventPayload = (event: KnowledgeStreamEvent): Record<string, unknown> =>
  event.payload && typeof event.payload === 'object' ? event.payload : {};

const timelineItemFromEvent = (event: KnowledgeStreamEvent): TimelineItem => {
  const payload = eventPayload(event);
  const eventType = String(event.type || payload.event_type || payload.type || '');
  const id = event.event_id || `${event.stream_id}-${event.sequence}`;
  if (/assistant[._-]?delta|message[._-]?delta|delta/.test(eventType)) {
    return {
      id,
      type: 'assistant_delta',
      title: 'assistant Markdown 增量',
      body: safeText(payload.delta ?? payload.text ?? payload.content),
      status: String(payload.status ?? 'streaming'),
    };
  }
  if (/tool[._-]?call|tool/.test(eventType)) {
    return {
      id,
      type: 'tool_call',
      title: `tool-call ${safeText(payload.name ?? payload.toolName ?? payload.tool_name ?? 'unknown')}`,
      body: safeText(payload.summary ?? payload.message ?? payload.status),
      status: safeText(payload.status ?? 'running'),
      elapsedMs: typeof payload.elapsedMs === 'number' ? payload.elapsedMs : typeof payload.elapsed_ms === 'number' ? payload.elapsed_ms : undefined,
    };
  }
  if (/clarification|awaiting_input/.test(eventType)) {
    const questionValues = payload.questions ?? payload.clarification_questions;
    const questions = Array.isArray(questionValues)
      ? questionValues
      : [];
    return {
      id,
      type: 'clarification',
      title: 'clarification',
      body: questions.map(safeText).filter(Boolean).join('\n') || safeText(payload.message),
      status: 'awaiting_input',
    };
  }
  if (/context|revision|view_revision|draft_created|patch_accepted/.test(eventType)) {
    return {
      id,
      type: 'context_revision',
      title: 'context / revision',
      body: safeText(payload.summary ?? payload.revisionId ?? payload.revision_id ?? payload.draftId ?? payload.draft_id),
      status: safeText(payload.status),
    };
  }
  if (/warning|credential_blocked/.test(eventType)) {
    return {
      id,
      type: 'warning',
      title: 'warning',
      body: safeText(payload.message ?? payload.error_message),
      status: safeText(payload.code ?? payload.error_code),
    };
  }
  if (/error|failed/.test(eventType)) {
    return {
      id,
      type: 'error',
      title: 'error',
      body: safeText(payload.message ?? payload.error_message),
      status: safeText(payload.code ?? payload.error_code),
    };
  }
  if (/cancel|stop/.test(eventType)) {
    return {
      id,
      type: 'stop',
      title: 'stop',
      body: safeText(payload.message),
      status: safeText(payload.status),
    };
  }
  if (/retry/.test(eventType)) {
    return {
      id,
      type: 'retry',
      title: 'retry',
      body: safeText(payload.message ?? payload.summary),
      status: safeText(payload.status),
    };
  }
  if (/resume/.test(eventType)) {
    return {
      id,
      type: 'resume',
      title: 'resume',
      body: safeText(payload.message ?? payload.summary),
      status: safeText(payload.status),
    };
  }
  return {
    id,
    type: 'status',
    title: safeText(eventType || 'status'),
    body: safeText(payload.summary ?? payload.message ?? payload.stage),
    status: safeText(payload.status),
  };
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
  const [planExpanded, setPlanExpanded] = useState(false);
  const [showSelector, setShowSelector] = useState(false);
  const [selectorQuery, setSelectorQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [uploadState, setUploadState] = useState<'idle'|'parsing'|'success'>('idle');
  const [authoringDraft, setAuthoringDraft] = useState<any>(null);
  const [agentReply, setAgentReply] = useState('');
  const [agentError, setAgentError] = useState('');
  const [agentBusy, setAgentBusy] = useState(false);
  const [authoringRun, setAuthoringRun] = useState<any>(null);
  const [timelineItems, setTimelineItems] = useState<TimelineItem[]>([]);
  const [activeStream, setActiveStream] = useState<KnowledgeStream | null>(null);
  const [lastTimelineCommand, setLastTimelineCommand] = useState<{
    prompt: string;
    requestedKind: 'knowledge' | 'analysis';
  } | null>(null);
  const nearBottomRef = useRef(true);

  const [dragStatus, setDragStatus] = useState<string>('idle');
  const [dragMessage, setDragMessage] = useState<string>('');

  const focusInput = () => {
    inputRef.current?.focus();
  };

  const focusInputAtEnd = () => {
    const inputElement = inputRef.current;
    if (!inputElement) return;
    inputElement.focus();
    const len = inputElement.value.length;
    inputElement.setSelectionRange(len, len);
  };

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

  const pinnedResourceRefs = (): ResourceRef[] => {
    const refs: ResourceRef[] = [];
    for (const chip of chatChips) {
      const ref = chip.contextRef || getServerContextRef(
        String(chip.resourceId || chip.artifactId || chip.id || ''),
      );
      if (
        ref &&
        typeof ref.kind === 'string' &&
        typeof ref.objectId === 'string' &&
        typeof ref.revision === 'string' &&
        (ref.scope === 'personal' || ref.scope === 'team')
      ) {
        refs.push({
          kind: ref.kind as ResourceRef['kind'],
          object_id: ref.objectId,
          revision: ref.revision,
          scope: ref.scope as ResourceRef['scope'],
        });
      }
    }
    const selected = new Set(chatChips.map((chip: any) => chip.id || chip.identity));
    for (const resource of resourceStore.getState()) {
      if (!selected.has(resource.id) && !selected.has(resource.resourceId)) continue;
      const revision = resource.goldenRevisionId ?? resource.golden_revision_id;
      const objectId = resource.assetId ?? resource.asset_id;
      if (typeof revision === 'string' && typeof objectId === 'string') {
        refs.push({
          kind: 'golden_asset',
          object_id: objectId,
          revision,
          scope: resource.space === 'team' ? 'team' : 'personal',
        });
      }
    }
    const view: any = activeSkillViewRevision;
    const skillRevisionId = String(
      view?.skillRevisionId ?? view?.skill_revision_id ?? '',
    );
    if (view?.id && skillRevisionId.includes(':')) {
      refs.push({
        kind: 'artifact',
        object_id: String(view.id),
        revision: String(view.id),
        scope: 'personal',
      });
      refs.push({
        kind: 'skill',
        object_id: skillRevisionId.slice(0, skillRevisionId.lastIndexOf(':')),
        revision: skillRevisionId,
        scope: 'personal',
      });
    }
    return refs.filter((ref, index) => refs.findIndex((item) =>
      item.kind === ref.kind &&
      item.object_id === ref.object_id &&
      item.revision === ref.revision &&
      item.scope === ref.scope
    ) === index);
  };
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
      if (type === 'dashboard' || type === 'artifact') return ['解释当前视图', '生成下一步建议', '导出审计摘要'];
      if (type === 'chart') return ['修改图表类型为柱状图', '调整配色对比度', '导出数据明细'];
      if (type === 'knowledge_base') return ['测试问答效果', '补充新文档来源'];
      if (type === 'document') return ['根据文档生成测验用例', '提取文档关键指标', '加入知识库中'];
      if (type === 'connection' || type === 'source' || type === 'dataset') return ['了解数据表结构', '分析此数据源关联的产物', '预览核心字段质量'];
      if (type === 'knowledge_graph' || type === 'kg') return ['基于该图谱执行推理查询', '发现并合并相似实体', '补充缺失的关系节点'];
      if (type === 'evaluation') return ['查看最新的评测维度得分', '应用并回归 AI 修复建议', '导出评测对比报告'];
      if (type === 'skill') return ['查看 Skill 契约', '生成调用示例', '创建监控视图'];
      if (type === 'semantic' || type === 'semantic_model') return ['生成 Dashboard Skill', '检查计算字段依赖', '修改指标口径'];
      return ['总结当前资源', '生成相关报告', '导出快照'];
    }
    return ['添加真实数据连接', '选择 Skill 模板', '描述要生成的 Skill'];
  };

  const handleSuggestionClick = (s: string) => {
    if (s === '创建待办') {
       showToast?.('请通过服务端 Agent 确认后创建待办。');
       const p = new URLSearchParams(searchParams);
       p.set('pane', 'open');
       setSearchParams(p);
       return;
    }

    if (['解释异常', '生成行动建议', '总结进展', '补充证据', '提交 Review', '比较前后指标', '识别未解决风险', '汇总已验证事实', '生成备选方案'].includes(s)) {
      setInput(s);
      focusInput();
      return;
    }

    setInput(s);
    focusInput();
  };

  useEffect(() => {
    const unsubscribe = dragStore.subscribe(() => {
      const state = dragStore.getState();
      if (state.targetId === 'chat_input') {
         setDragStatus(state.status);
         setDragMessage(state.message);
      } else if (dragStatus !== 'idle') {
         setDragStatus('idle');
         setDragMessage('');
      }
    });
    return () => {
      unsubscribe();
    };
  }, [dragStatus]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !nearBottomRef.current) return;
    element.scrollTop = element.scrollHeight;
  }, [chatState, input, chatChips, contextExpanded, planExpanded, authoringRun, agentReply, timelineItems]);

  const handleTimelineScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    nearBottomRef.current =
      element.scrollHeight - element.scrollTop - element.clientHeight < 72;
  };

  const appendTimelineItem = (item: TimelineItem) => {
    setTimelineItems((previous) => {
      const next = previous.filter((existing) => existing.id !== item.id);
      return [...next, item];
    });
  };

  const consumeTimelineStream = async (
    command:
      | { command: 'skill-authoring.start'; payload: any }
      | { command: 'skill-authoring.answer'; payload: any }
      | { command: 'skill-authoring.patch'; payload: any }
      | { command: 'skill-authoring.execute'; payload: any },
  ) => {
    try {
      const stream = await getWorkspaceAdapter().stream(command, createRequestContext());
      setActiveStream(stream);
      for await (const event of stream.events) {
        appendTimelineItem(timelineItemFromEvent(event));
        if (event.terminal) setActiveStream(null);
      }
    } catch (error) {
      appendTimelineItem({
        id: `warning-${Date.now()}`,
        type: 'warning',
        title: 'warning',
        body: error instanceof Error
          ? `W2 timeline seam 尚未返回可消费流：${error.message}`
          : 'W2 timeline seam 尚未返回可消费流。',
        status: 'waiting_for_w2',
      });
      setActiveStream(null);
    }
  };

  const renderTimelineItem = (item: TimelineItem) => {
    const tone =
      item.type === 'user' ? 'bg-slate-100 text-slate-800 ml-auto rounded-tr-sm' :
      item.type === 'error' ? 'bg-red-50 border-red-200 text-red-800 rounded-tl-sm' :
      item.type === 'warning' ? 'bg-amber-50 border-amber-200 text-amber-800 rounded-tl-sm' :
      item.type === 'tool_call' ? 'bg-violet-50 border-violet-200 text-violet-900 rounded-tl-sm' :
      'bg-white border-slate-200 text-slate-700 rounded-tl-sm';
    return (
      <div key={item.id} className={cn("max-w-[92%] rounded-2xl border px-4 py-2.5 text-[13px] leading-relaxed shadow-sm", tone)}>
        <div className="mb-1 flex items-center justify-between gap-3">
          <span className="font-semibold">{item.title}</span>
          {item.status && <span className="shrink-0 rounded bg-white/70 px-1.5 py-0.5 text-[10px] font-mono opacity-80">{item.status}</span>}
        </div>
        {item.body && <div className="whitespace-pre-wrap">{item.body}</div>}
        {item.type === 'tool_call' && (
          <div className="mt-2 rounded-lg border border-current/10 bg-white/60 px-2 py-1 text-[11px]">
            tool-call · {item.elapsedMs !== undefined ? `${item.elapsedMs}ms` : '耗时等待服务端返回'}
          </div>
        )}
      </div>
    );
  };

  const stopTimeline = async () => {
    if (!activeStream) return;
    await activeStream.cancel();
    appendTimelineItem({
      id: `stop-${Date.now()}`,
      type: 'stop',
      title: 'stop',
      body: '已向服务端发送 stream.cancel；不会在前端制造完成态。',
      status: 'cancel_requested',
    });
    setActiveStream(null);
  };

  const retryTimeline = () => {
    appendTimelineItem({
      id: `retry-${Date.now()}`,
      type: 'retry',
      title: 'retry',
      body: '重新提交上一条 typed command。',
      status: 'pending',
    });
    if (lastTimelineCommand) {
      void runAgent(lastTimelineCommand.prompt, lastTimelineCommand.requestedKind);
    }
  };

  const resumeTimeline = () => {
    appendTimelineItem({
      id: `resume-${Date.now()}`,
      type: 'resume',
      title: 'resume',
      body: '使用当前 context/revision 继续会话；若 W2 支持 Last-Event-ID，将由 adapter 透传。',
      status: 'pending',
    });
    if (lastTimelineCommand) {
      void runAgent(lastTimelineCommand.prompt, lastTimelineCommand.requestedKind);
    }
  };

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
      focusInput();
    }
    if (action === 'open_selector') {
      setShowSelector(true);
      const p = new URLSearchParams(searchParams);
      p.delete('action');
      setSearchParams(p, { replace: true });
    }
    if (action && inputRef.current) {
      focusInputAtEnd();
    }
  }, [action]);

  const runAgent = async (prompt: string, requestedKind: 'knowledge' | 'analysis') => {
    setAgentError('');
    setAgentReply('');
    setLastTimelineCommand({ prompt, requestedKind });
    appendTimelineItem({
      id: `user-${Date.now()}`,
      type: 'user',
      title: '用户消息',
      body: prompt,
    });
    try {
      const connectionRefs = connectionStore.getState()
        .filter((connection: any) => chatChips.some((chip: any) => chip.id === connection.id))
        .flatMap((connection: any) => connection.goldenRevisionIds || [])
        .map((revision: string): ResourceRef | null => {
          const resource: any = resourceStore.getState().find((item: any) => item.goldenRevisionId === revision);
          return resource ? { kind: 'golden_asset', object_id: String(resource.assetId), revision, scope: resource.space === 'team' ? 'team' : 'personal' } : null;
        })
        .filter((ref): ref is ResourceRef => Boolean(ref));
      const pinnedRefs = [...connectionRefs, ...pinnedResourceRefs()].filter(
        (ref: any, index: number, refs: any[]) =>
          refs.findIndex((item) => item.kind === ref.kind &&
            item.object_id === ref.object_id &&
            item.revision === ref.revision) === index,
      );
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
      const command = {
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
      } as const;
      void consumeTimelineStream(command);
      const response = await getWorkspaceAdapter().command(command, createRequestContext());
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
        appendTimelineItem({
          id: `clarification-${operation.operation_id ?? response.operationId ?? Date.now()}`,
          type: 'clarification',
          title: 'clarification',
          body: clarificationQuestions.map(safeText).join('\n'),
          status: 'awaiting_input',
        });
        return null;
      }
      if (!response.accepted || !result.draft) {
        throw new Error(String(result.error?.message ?? 'Agent 未返回有效响应。'));
      }
      setAuthoringDraft(result.draft);
      appendTimelineItem({
        id: `context-revision-${operation.operation_id ?? response.operationId ?? Date.now()}`,
        type: 'context_revision',
        title: 'context / revision',
        body: safeText(operation.summary ?? result.draft?.draft_id ?? result.draft?.id),
        status: String(result.status ?? 'ready_for_execution'),
      });
      return result.draft;
    } catch (error) {
      setAgentError(error instanceof Error ? error.message : 'Agent 请求失败。');
      appendTimelineItem({
        id: `error-${Date.now()}`,
        type: 'error',
        title: 'error',
        body: error instanceof Error ? error.message : 'Agent 请求失败。',
      });
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
    setAgentReply('');
    try {
      const command = {
        command: 'skill-authoring.execute',
        payload: { draftId: authoringDraft.draft_id, revision: authoringDraft.revision },
      } as const;
      void consumeTimelineStream(command);
      const response = await getWorkspaceAdapter().command(command, createRequestContext());
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
      appendTimelineItem({
        id: `context-revision-${operation.operation_id ?? response.operationId ?? Date.now()}`,
        type: 'context_revision',
        title: 'context / revision',
        body: safeText(operation.summary ?? operation.artifact_result?.revisionId ?? operation.artifact_result?.revision_id),
        status: String(result.status ?? 'succeeded'),
      });
      return true;
    } catch (error) {
      setAgentError(error instanceof Error ? error.message : 'Runner 执行失败。');
      appendTimelineItem({
        id: `error-${Date.now()}`,
        type: 'error',
        title: 'error',
        body: error instanceof Error ? error.message : 'Runner 执行失败。',
      });
      return false;
    } finally {
      submissionRef.current = false;
      setAgentBusy(false);
    }
  };

  const runKnowledgeAnswer = async (prompt: string) => {
    setAgentError('');
    setAgentReply('');
    const resourceRefs = pinnedResourceRefs();
    const viewRevision: any = activeSkillViewRevision;
    const currentViewId = viewRevision?.id ? String(viewRevision.id) : undefined;
    const viewOwner = String(
      viewRevision?.skillRevisionId ?? viewRevision?.skill_revision_id ?? '',
    );
    const currentSkillId = viewOwner.includes(':')
      ? viewOwner.slice(0, viewOwner.lastIndexOf(':'))
      : undefined;
    try {
      appendTimelineItem({
        id: `user-${Date.now()}`,
        type: 'user',
        title: '用户消息',
        body: prompt,
      });
      const command = {
        command: 'skill-authoring.answer',
        payload: {
          prompt,
          resourceRefs,
          fixedRevisions: resourceRefs.map((ref: any) => ref.revision),
          currentSkillId,
          currentViewId,
          currentComponentId: chatChips.find((chip: any) => chip.type === 'element')?.id,
          commentIds: chatChips
            .filter((chip: any) => String(chip.type || '').startsWith('comment'))
            .map((chip: any) => String(chip.id || chip.identity)),
        },
      } as const;
      void consumeTimelineStream(command);
      const response = await getWorkspaceAdapter().command(command, createRequestContext());
      const result: any = response.result ?? {};
      const answer = result.answer ?? {};
      const execution = result.agentExecution ?? result.agent_execution ?? {};
      setAuthoringRun({
        sessionId: execution.sessionId ?? execution.session_id,
        traceId: execution.traceId ?? execution.trace_id,
      });
      if (!response.accepted) {
        throw new Error(String(result.error?.message ?? 'Agent 未返回有效响应。'));
      }
      if (result.status === 'awaiting_input') {
        const questions = answer.clarificationQuestions ?? answer.clarification_questions;
        appendTimelineItem({
          id: `clarification-${Date.now()}`,
          type: 'clarification',
          title: 'clarification',
          body: Array.isArray(questions) ? questions.map(safeText).join('\n') : '',
          status: 'awaiting_input',
        });
        return;
      }
      if (result.status !== 'succeeded' || typeof answer.text !== 'string') {
        throw new Error('普通问答需要服务端返回 typed answer；Agent 返回了无效响应。');
      }
      appendTimelineItem({
        id: `assistant-delta-${Date.now()}`,
        type: 'assistant_delta',
        title: 'assistant Markdown 增量',
        body: safeText(answer.text),
        status: 'succeeded',
      });
      setAuthoringDraft(null);
    } catch (error) {
      setAgentError(error instanceof Error ? error.message : 'Agent 请求失败。');
      appendTimelineItem({
        id: `error-${Date.now()}`,
        type: 'error',
        title: 'error',
        body: error instanceof Error ? error.message : 'Agent 请求失败。',
      });
    }
  };

  const modifyCurrentSkill = async (prompt: string) => {
    const view: any = activeSkillViewRevision;
    const skillRevisionId = String(
      view?.skillRevisionId ?? view?.skill_revision_id ?? '',
    );
    const split = skillRevisionId.lastIndexOf(':');
    const draftId = authoringDraft?.draft_id ||
      (split > 0 ? skillRevisionId.slice(0, split) : '');
    const baseRevision = authoringDraft?.revision ||
      (split > 0 ? Number(skillRevisionId.slice(split + 1)) : 0);
    if (!draftId || !Number.isInteger(baseRevision) || baseRevision < 1) {
      throw new Error('当前产物没有可修改的 immutable Skill revision。');
    }
    const patchCommand = {
      command: 'skill-authoring.patch',
      payload: {
        draftId,
        baseRevision,
        patch: { patch_type: 'set_title', title: prompt.slice(0, 160) },
      },
    } as const;
    void consumeTimelineStream(patchCommand);
    const patched = await getWorkspaceAdapter().command(patchCommand, createRequestContext());
    const patchResult: any = patched.result ?? {};
    if (!patched.accepted || !patchResult.draft) {
      throw new Error(String(patchResult.error?.message ?? 'Agent 修改失败。'));
    }
    setAuthoringDraft(patchResult.draft);
    const nextDraftId = patchResult.draft.draftId ?? patchResult.draft.draft_id;
    const executeCommand = {
      command: 'skill-authoring.execute',
      payload: {
        draftId: nextDraftId,
        revision: patchResult.draft.revision,
      },
    } as const;
    void consumeTimelineStream(executeCommand);
    const executed = await getWorkspaceAdapter().command(executeCommand, createRequestContext());
    const executeResult: any = executed.result ?? {};
    if (!executed.accepted || executeResult.status !== 'succeeded') {
      throw new Error(String(executeResult.error?.message ?? '修改后的 revision 执行失败。'));
    }
    await bootstrapWorkspace(undefined, getWorkspaceAdapter());
    setAuthoringRun({
      operationId: executeResult.operation?.operation_id,
      traceId: executeResult.operation?.trace_id,
      draftId: executeResult.draft?.draftId ?? executeResult.draft?.draft_id,
      draftRevision: executeResult.draft?.revision,
      plan: executeResult.operation?.plan ?? executeResult.draft?.plan,
    });
    setAgentReply('');
    appendTimelineItem({
      id: `context-revision-${executeResult.operation?.operation_id ?? Date.now()}`,
      type: 'context_revision',
      title: 'context / revision',
      body: safeText(executeResult.operation?.summary ?? executeResult.draft?.draft_id ?? executeResult.draft?.draftId),
      status: String(executeResult.status ?? 'succeeded'),
    });
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
    const isCreationCommand = /(?:生成|创建|构建).*(?:Dashboard|看板|报表|知识库|Skill|图谱|语义|监控)/i.test(input);

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
    } else if (isModification) {
      await modifyCurrentSkill(input.trim());
      setInput('');
      return;
    } else if (isCreation) {
      const draft = await runAgent(
        input.trim(),
        isKnowledgeCreation ? 'knowledge' : 'analysis',
      );
      if (!draft) return;
      p.set('chat', 'planning');
      setPlanExpanded(false);
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

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    const state = dragStore.getState();
    if (state.status !== 'dragging' && state.status !== 'valid-over' && state.status !== 'invalid-over') return;
    if (!state.item) return;
    if (state.item.type === 'folder' || state.item.type === 'root' || state.item.hasPermission === false) {
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
      dragStore.setState({ status: 'idle', targetId: null, item: null, message: '' });
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
  const timelineView = timelineItems.length > 0 ? (
    <div className="flex flex-col gap-3" aria-live="polite">
      {timelineItems.map(renderTimelineItem)}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void stopTimeline()}
          disabled={!activeStream}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          stop
        </button>
        <button
          type="button"
          onClick={retryTimeline}
          disabled={!lastTimelineCommand || agentBusy}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          retry
        </button>
        <button
          type="button"
          onClick={resumeTimeline}
          disabled={!lastTimelineCommand || agentBusy}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          resume
        </button>
      </div>
    </div>
  ) : null;
  const clarifyResumeCard = isHomeChat && chatState === 'clarify' ? (
    <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-left text-sm leading-6 text-blue-900" role="status">
      <div className="font-semibold">等待 Agent 澄清</div>
      <p className="mt-1 text-xs leading-5 text-blue-800">
        当前深链已恢复到 clarification 阶段。W4 只消费 W2 timeline / operation 事件；如果服务端尚未返回澄清问题，页面保持等待态，不填充固定问答。
      </p>
      <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-xl bg-white/70 p-3 text-[11px]">
        <dt className="font-semibold text-blue-500">operation</dt>
        <dd className="truncate font-mono text-blue-900">{searchParams.get('operation_id') || '等待服务端 operation'}</dd>
        <dt className="font-semibold text-blue-500">draft</dt>
        <dd className="truncate font-mono text-blue-900">{searchParams.get('draft_id') || '等待 SkillDraft'}</dd>
      </dl>
    </div>
  ) : null;

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
            {clarifyResumeCard}
            {timelineView && <div className="mt-4 text-left">{timelineView}</div>}
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
            {["添加真实数据连接", "选择 Skill 模板", "描述要生成的 Skill"].map((s, i) => (
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

      <div className="flex-1 min-h-0 overflow-y-auto p-4 custom-scrollbar flex flex-col gap-5" ref={scrollRef} onScroll={handleTimelineScroll}>
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
         {timelineView}
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
               <h4 className="font-semibold text-slate-800 mb-2 flex items-center"><Wand2 size={16} className="mr-2 text-blue-600"/> 已生成可执行草稿</h4>
               <p className="text-xs text-slate-500 mb-3 leading-relaxed">
                 BuildPlan 由服务端 Agent 返回，用户在这里只确认执行；技术计划默认折叠，仅用于审计与排错。
               </p>
               <button
                 type="button"
                 aria-expanded={planExpanded}
                 onClick={() => setPlanExpanded((value) => !value)}
                 className="mb-3 inline-flex items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
               >
                 <ChevronDown size={13} className={cn("mr-1.5 transition-transform", planExpanded && "rotate-180")} />
                 折叠执行详情
               </button>
               {planExpanded && (
                 <pre className="mb-3 max-h-44 overflow-auto rounded-lg border border-slate-200 bg-slate-950 p-3 text-[10px] leading-relaxed text-slate-100">
                   {JSON.stringify(authoringRun?.plan ?? { status: 'awaiting_server_build_plan' }, null, 2)}
                 </pre>
               )}
               <div className="flex justify-end space-x-2 border-t border-slate-100 pt-3">
                 <button onClick={() => {
                   const p = new URLSearchParams(searchParams);
                   p.delete('chat');
                   setSearchParams(p);
                 }} className="px-4 py-2 border border-slate-200 text-slate-600 bg-white rounded-lg text-xs font-bold hover:bg-slate-50 outline-none shadow-sm transition-colors">取消</button>
                 <button onClick={async () => {
                   if (await executeAgent()) {
                     const p = new URLSearchParams(searchParams);
                     p.delete('chat');
                     setSearchParams(p);
                   }
                 }} disabled={agentBusy} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-700 disabled:opacity-50 shadow-sm outline-none flex items-center transition-colors">
                   {agentBusy ? <Loader2 size={14} className="mr-1.5 animate-spin"/> : <ArrowRight size={14} className="mr-1.5"/>}
                   执行并渲染
                 </button>
               </div>
             </div>
           </div>
         )}

         {chatState === 'generating' && (
           <div className="animate-in fade-in flex items-start gap-3">
             <div className="w-7 h-7 rounded-full bg-slate-100 text-slate-500 flex items-center justify-center shrink-0"><Bot size={14}/></div>
             <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm p-4 shadow-sm min-w-[250px] flex flex-col gap-3">
               <div className="flex items-center text-xs font-medium text-slate-700">
                 <Loader2 size={14} className="animate-spin text-blue-600 mr-2 shrink-0"/>
                 服务端正在执行 SkillDraft revision
               </div>
               <div className="text-[11px] text-slate-500">执行进度、工具调用与 trace 由 W2 timeline seam 返回后在此增量展示。</div>
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
