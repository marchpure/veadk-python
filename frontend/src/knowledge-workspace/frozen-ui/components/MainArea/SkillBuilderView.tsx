import { useId, useMemo, useState, type SVGProps } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import { createRequestContext } from '../../../production/ports';
import type { ResourceRef, SkillAuthoringStartPayload, TemplateRef } from '../../../production/generatedContracts';
import { bootstrapWorkspace, getWorkspaceAdapter, resourceStore, templateSpecStore } from '../../../production/store';
import { TrustedHtmlArtifactRenderer } from './TrustedHtmlArtifactRenderer';

type RecordValue = Record<string, unknown>;
type RequestedKind = NonNullable<SkillAuthoringStartPayload['requestedKind']>;

const TEMPLATE_TO_KIND: Record<string, RequestedKind> = {
  dashboard: 'analysis',
  chart: 'analysis',
  semantic: 'semantic',
  sop: 'sop',
  knowledge: 'knowledge',
  graph_ontology: 'graph_ontology',
  monitoring: 'monitoring',
};

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function IconBase({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

function BackIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M15 6 9 12l6 6" /></IconBase>;
}

function SparkIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="m12 3 1.4 4.4L18 9l-4.6 1.6L12 15l-1.4-4.4L6 9l4.6-1.6L12 3Z" /><path d="m5 15 .8 2.2L8 18l-2.2.8L5 21l-.8-2.2L2 18l2.2-.8L5 15Z" /></IconBase>;
}

function PlayIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M8 5.8v12.4L18 12 8 5.8Z" /></IconBase>;
}

function AuditIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M7 4h10" /><path d="M6 8h12" /><path d="M8 12h8" /><path d="M9 16h6" /><rect x="4" y="3" width="16" height="18" rx="2.5" /></IconBase>;
}

function AlertIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M12 4 3.5 19h17L12 4Z" /><path d="M12 9v4" /><path d="M12 16h.01" /></IconBase>;
}

function parseContextRefs(raw: string | null): ResourceRef[] {
  if (!raw) return [];
  return raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const parts = item.split(':');
      const scope = parts.pop();
      const revision = parts.pop();
      const objectId = parts.pop();
      const kind = parts.join(':');
      if (
        kind &&
        objectId &&
        revision &&
        (scope === 'personal' || scope === 'team')
      ) {
        return {
          kind: kind as ResourceRef['kind'],
          object_id: objectId,
          revision,
          scope,
        };
      }
      return null;
    })
    .filter((item): item is ResourceRef => Boolean(item));
}

function normalizeResourceRef(value: unknown): ResourceRef | null {
  if (!isRecord(value)) return null;
  const kind = stringValue(value.kind);
  const objectId = stringValue(value.object_id) ?? stringValue(value.objectId);
  const revision = stringValue(value.revision);
  const scope = value.scope;
  if (
    kind &&
    objectId &&
    revision &&
    (scope === 'personal' || scope === 'team')
  ) {
    return {
      kind: kind as ResourceRef['kind'],
      object_id: objectId,
      revision,
      scope,
    };
  }
  return null;
}

function findServerDraftResource(draftId: string, fileId: string): RecordValue | null {
  const candidates = new Set([draftId, fileId].filter(Boolean));
  return resourceStore.getState().find((resource: RecordValue) => {
    const values = [
      resource.id,
      resource.resourceId,
      resource.draftId,
      resource.draft_id,
      resource.skillId,
      resource.skill_id,
    ];
    return values.some((value) => typeof value === 'string' && candidates.has(value));
  }) ?? null;
}

function getAuthoringSession(resource: RecordValue | null): RecordValue | null {
  const authoringSession = resource?.authoringSession ?? resource?.authoring_session;
  return isRecord(authoringSession) ? authoringSession : null;
}

function getServerPrompt(resource: RecordValue | null, session: RecordValue | null): string {
  return (
    stringValue(session?.prompt) ??
    stringValue(session?.request) ??
    stringValue(resource?.prompt) ??
    stringValue(resource?.request) ??
    stringValue(resource?.description) ??
    ''
  );
}

function getServerTemplate(resource: RecordValue | null, session: RecordValue | null): string {
  return (
    stringValue(session?.template) ??
    stringValue(session?.requestedTemplate) ??
    stringValue(session?.requested_template) ??
    stringValue(resource?.template) ??
    stringValue(resource?.subtype) ??
    'dashboard'
  );
}

function getServerContextRefs(resource: RecordValue | null, session: RecordValue | null): ResourceRef[] {
  const values = [
    session?.resourceRefs,
    session?.resource_refs,
    session?.contextRefs,
    session?.context_refs,
    resource?.resourceRefs,
    resource?.resource_refs,
    resource?.contextRefs,
    resource?.context_refs,
  ].find(Array.isArray);
  return Array.isArray(values)
    ? values.map(normalizeResourceRef).filter((item): item is ResourceRef => Boolean(item))
    : [];
}

function getServerWorkspaceScope(resource: RecordValue | null, session: RecordValue | null): 'personal' | 'team' | undefined {
  const scope = session?.scope ?? session?.workspaceScope ?? session?.workspace_scope ?? resource?.space ?? resource?.scope;
  return scope === 'team' ? 'team' : scope === 'personal' ? 'personal' : undefined;
}

function getDraftId(draft: unknown): string {
  return isRecord(draft) ? String(draft.draft_id ?? draft.id ?? '') : '';
}

function getDraftRevision(draft: unknown): number | undefined {
  if (!isRecord(draft)) return undefined;
  return numberValue(draft.revision);
}

function auditPayload(draft: unknown, operation: unknown, revision: unknown) {
  return {
    SkillDraft: draft ?? { status: 'waiting_for_server_draft' },
    BuildPlan: isRecord(operation) ? operation.plan ?? { status: 'waiting_for_server_build_plan' } : { status: 'waiting_for_server_build_plan' },
    operation: operation ?? null,
    ViewRevision: revision ?? null,
  };
}

function GatedHtmlState({ template, prompt }: { template: string; prompt: string }) {
  return (
    <section className="flex min-h-[520px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-700">
        <AlertIcon className="h-6 w-6" />
      </div>
      <h2 className="mt-5 text-xl font-semibold text-slate-900">等待服务端返回 HTML ViewRevision</h2>
      <p className="mt-3 max-w-xl text-sm leading-6 text-slate-600">
        当前模板为 {template || '未选择'}。Runner 完成前，中间区域不会用固定成功结果填充；Dashboard、Semantic、SOP、Knowledge、Graph、Monitoring 都会作为 Skill 的可信 HTML revision 呈现。
      </p>
      <p className="mt-4 max-w-xl rounded-xl bg-slate-50 px-4 py-3 text-left text-xs leading-5 text-slate-500">
        当前需求：{prompt || '等待首页或服务端 draft/session 恢复'}
      </p>
    </section>
  );
}

export default function SkillBuilderView({ searchParams, setSearchParams }: any) {
  const promptInputId = useId();
  const initialDraftId = searchParams.get('draft_id') ?? '';
  const fileId = searchParams.get('file') ?? 'skill_builder';
  const serverDraftResource = findServerDraftResource(initialDraftId, fileId);
  const authoringSession = getAuthoringSession(serverDraftResource);
  const serverPrompt = getServerPrompt(serverDraftResource, authoringSession);
  const serverTemplate = getServerTemplate(serverDraftResource, authoringSession);
  const serverContextRefs = getServerContextRefs(serverDraftResource, authoringSession);
  const urlPrompt = searchParams.get('request') ?? serverPrompt;
  const urlTemplate = searchParams.get('template') ?? searchParams.get('adapter') ?? serverTemplate;
  const urlContextRefs = searchParams.get('context_refs');
  const workspaceScope =
    searchParams.get('workspace_scope') === 'team'
      ? 'team'
      : searchParams.get('workspace_scope') === 'personal'
      ? 'personal'
      : getServerWorkspaceScope(serverDraftResource, authoringSession) ?? 'personal';
  const requestedKind = TEMPLATE_TO_KIND[urlTemplate] ?? 'analysis';
  const selectedTemplateSpec = templateSpecStore.getState().find(
    (spec) => spec.templateId === (
      urlTemplate === 'graph_ontology' ? 'graph-ontology' : urlTemplate
    ),
  );
  const selectedTemplateRef: TemplateRef | undefined =
    selectedTemplateSpec?.templateRef;
  const initialOperationId = searchParams.get('operation_id') ?? '';

  const [prompt, setPrompt] = useState(urlPrompt);
  const [draft, setDraft] = useState<RecordValue | null>(
    initialDraftId ? { draft_id: initialDraftId } : null,
  );
  const [operation, setOperation] = useState<RecordValue | null>(
    initialOperationId ? { operation_id: initialOperationId } : null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [auditOpen, setAuditOpen] = useState(false);
  const [status, setStatus] = useState<'drafting' | 'awaiting_input' | 'ready_for_execution' | 'executing' | 'revision_ready' | 'error'>(
    initialDraftId ? 'ready_for_execution' : 'drafting',
  );

  const resourceRefs = useMemo(() => {
    const parsed = parseContextRefs(urlContextRefs);
    return parsed.length > 0 ? parsed : serverContextRefs;
  }, [serverContextRefs, urlContextRefs]);
  const viewRevision = isRecord(activeSkillViewRevision) ? activeSkillViewRevision : null;
  const activeDraftId = getDraftId(draft);
  const activeRevision = getDraftRevision(draft);

  const handleClose = () => {
    const params = new URLSearchParams(searchParams);
    params.set('file', 'welcome');
    params.delete('adapter');
    setSearchParams(params);
  };

  const updateUrlFromResult = (result: RecordValue, responseOperationId?: string) => {
    const nextDraft = isRecord(result.draft) ? result.draft : null;
    const nextOperation = isRecord(result.operation) ? result.operation : null;
    const nextDraftId = getDraftId(nextDraft);
    const nextOperationId = stringValue(responseOperationId) ??
      stringValue(nextOperation?.operation_id) ??
      stringValue(nextOperation?.operationId);
    const params = new URLSearchParams(searchParams);
    params.set('file', 'skill_builder');
    params.set('request', prompt);
    params.set('template', urlTemplate);
    params.set('workspace_scope', workspaceScope);
    if (urlContextRefs) params.set('context_refs', urlContextRefs);
    if (nextDraftId) params.set('draft_id', nextDraftId);
    if (nextOperationId) params.set('operation_id', nextOperationId);
    setSearchParams(params);
    if (nextDraft) setDraft(nextDraft);
    if (nextOperation) setOperation(nextOperation);
  };

  const generateDraft = async () => {
    if (!prompt.trim()) {
      setError('请输入真实需求；也可以从首页带入 request、template、context refs 和 workspace scope。');
      return;
    }
    if (!selectedTemplateRef) {
      setError('服务端尚未返回所选模板的不可变 TemplateRef，请刷新工作区后重试。');
      return;
    }
    setBusy(true);
    setError('');
    setStatus('drafting');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.start',
        payload: {
          prompt: prompt.trim(),
          resourceRefs,
          fixedRevisions: resourceRefs.map((ref) => ref.revision),
          requestedKind,
          scope: workspaceScope,
          displayName: prompt.trim().slice(0, 80),
          templateRef: selectedTemplateRef,
        },
      }, createRequestContext());
      const result = isRecord(response.result) ? response.result : {};
      if (!response.accepted) {
        throw new Error(String((isRecord(result.error) ? result.error.message : undefined) ?? '服务端未接受 SkillDraft 生成请求。'));
      }
      updateUrlFromResult(result, response.operationId);
      setStatus(result.status === 'awaiting_input' ? 'awaiting_input' : 'ready_for_execution');
      await bootstrapWorkspace(undefined, getWorkspaceAdapter()).catch(() => undefined);
    } catch (cause) {
      setStatus('error');
      setError(cause instanceof Error ? cause.message : 'SkillDraft 生成失败。');
    } finally {
      setBusy(false);
    }
  };

  const executeDraft = async () => {
    if (!activeDraftId) {
      setError('缺少服务端 SkillDraft，不能执行。');
      return;
    }
    setBusy(true);
    setError('');
    setStatus('executing');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.execute',
        payload: { draftId: activeDraftId, revision: activeRevision ?? null },
      }, createRequestContext());
      const result = isRecord(response.result) ? response.result : {};
      if (!response.accepted || ['failed', 'cancelled', 'credential_blocked'].includes(String(result.status))) {
        throw new Error(String((isRecord(result.error) ? result.error.message : undefined) ?? 'Runner 未确认执行完成。'));
      }
      updateUrlFromResult(result, response.operationId);
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      setStatus('revision_ready');
    } catch (cause) {
      setStatus('error');
      setError(cause instanceof Error ? cause.message : 'Runner execution 失败。');
    } finally {
      setBusy(false);
    }
  };

  const openRightAgent = () => {
    const params = new URLSearchParams(searchParams);
    params.set('pane', 'open');
    setSearchParams(params);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50">
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            aria-label="返回工作区首页"
            onClick={handleClose}
            className="rounded-lg p-2 text-slate-500 outline-none hover:bg-slate-100 focus:ring-2 focus:ring-blue-500"
          >
            <BackIcon className="h-4 w-4" />
          </button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-slate-900">Skill Builder</h1>
            <p className="truncate text-xs text-slate-500">业务材料 → 模板匹配 → Agent 澄清 → Skill HTML revision → 评测与发布</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setAuditOpen((value) => !value)}
          aria-expanded={auditOpen}
          className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500"
        >
          <AuditIcon className="mr-1.5 h-4 w-4" /> 高级详情 / 审计
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <aside className="w-full shrink-0 border-b border-slate-200 bg-white p-4 lg:w-[300px] lg:border-b-0 lg:border-r">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">当前主路径</div>
            <ol className="mt-3 space-y-3 text-sm text-slate-700">
              {['放入业务材料', '选择模板或由 Agent 自动匹配', 'Agent 澄清并生成 Skill', 'HTML Skill 主视图', '试运行与评测', '发布到个人、团队或 Agent'].map((item, index) => (
                <li key={item} className="flex gap-3">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-semibold text-slate-500 ring-1 ring-slate-200">{index + 1}</span>
                  <span>{item}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="mt-4 space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
            <label className="block text-xs font-bold text-slate-700" htmlFor={promptInputId}>真实需求</label>
            <textarea
              id={promptInputId}
              data-testid="skill-builder-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.currentTarget.value)}
              rows={5}
              className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-800 outline-none focus:border-blue-500"
              placeholder="请输入真实需求"
            />
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-slate-400">template</dt>
              <dd className="truncate font-mono text-slate-700">{urlTemplate}</dd>
              <dt className="text-slate-400">workspace</dt>
              <dd className="truncate font-mono text-slate-700">{workspaceScope}</dd>
              <dt className="text-slate-400">context refs</dt>
              <dd className="truncate font-mono text-slate-700">{resourceRefs.length || '等待服务端/首页传入'}</dd>
            </dl>
            {status === 'awaiting_input' && (
              <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800">
                Agent 需要澄清。请在右侧 Agent 面板继续回答；W4 不会在前端伪造澄清结果。
              </div>
            )}
            {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void generateDraft()}
                disabled={busy || !prompt.trim()}
                className="inline-flex flex-1 items-center justify-center rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white outline-none hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                <SparkIcon className="mr-1.5 h-4 w-4" /> {busy && status === 'drafting' ? '生成中…' : '生成 SkillDraft'}
              </button>
              <button
                type="button"
                onClick={() => void executeDraft()}
                disabled={busy || !activeDraftId}
                className="inline-flex flex-1 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <PlayIcon className="mr-1.5 h-4 w-4" /> {busy && status === 'executing' ? '执行中…' : '确认执行'}
              </button>
            </div>
          </div>
        </aside>

        <main className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
            <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:p-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Skill HTML 主视图</h2>
                  <p className="mt-1 text-sm text-slate-500">
                    Dashboard、Semantic、SOP、Knowledge、Graph、Monitoring 均通过 typed ViewModel / trusted HTML revision 渲染。
                  </p>
                </div>
                <button
                  type="button"
                  onClick={openRightAgent}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500"
                >
                  通过右侧 Agent 修改
                </button>
              </div>
            </section>

            {viewRevision ? (
              <TrustedHtmlArtifactRenderer revision={viewRevision as any} />
            ) : (
              <GatedHtmlState template={urlTemplate} prompt={prompt} />
            )}
          </div>
        </main>

        {auditOpen && (
          <aside className="w-full shrink-0 overflow-y-auto border-t border-slate-200 bg-slate-950 p-4 text-slate-100 lg:w-[360px] lg:border-l lg:border-t-0">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Manifest / BuildPlan / trace / revision 审计</h2>
              <button
                type="button"
                onClick={() => setAuditOpen(false)}
                className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 outline-none hover:bg-slate-900 focus:ring-2 focus:ring-blue-400"
              >
                收起
              </button>
            </div>
            <p className="mb-3 text-xs leading-5 text-slate-400">
              BuildPlan 由真实 Agent 在服务端生成；这里仅用于审计、排错和查看进度，不允许用户手工编辑伪 Pipeline 或 JSON Manifest。
            </p>
            <pre className="max-h-[calc(100vh-190px)] overflow-auto rounded-xl border border-slate-800 bg-black/40 p-3 text-[11px] leading-5 text-slate-100">
              {JSON.stringify(auditPayload(draft, operation, viewRevision), null, 2)}
            </pre>
          </aside>
        )}
      </div>
    </div>
  );
}
