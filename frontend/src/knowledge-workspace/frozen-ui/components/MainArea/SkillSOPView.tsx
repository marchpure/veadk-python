import { useMemo, useState, type SVGProps } from 'react';
import ArtifactHeader from './ArtifactHeader';
import { activeSkillViewRevision } from '../../../production/data';
import { createRequestContext } from '../../../production/ports';
import { bootstrapWorkspace, getWorkspaceAdapter } from '../../../production/store';

export const SOP_VIEW_MODEL_TEMPLATE = 'sop';

type RecordValue = Record<string, unknown>;
type RunState = 'idle' | 'input' | 'running' | 'result';

export interface SopViewModel {
  template?: typeof SOP_VIEW_MODEL_TEMPLATE;
  title?: string;
  versionLabel?: string;
  status?: string;
  scope?: string;
  trigger?: string;
  draftId?: string;
  revision?: number;
  inputContract?: Array<{ name: string; type?: string; required?: boolean; description?: string }>;
  contextRefs?: Array<{ id: string; label?: string; kind?: string; status?: string }>;
  steps?: Array<{
    id: string;
    title: string;
    description?: string;
    condition?: string;
    status?: string;
    output?: string;
    evidenceRef?: string;
  }>;
  run?: {
    status?: string;
    operationId?: string;
    traceId?: string;
    executionState?: string;
    outputSummary?: string;
    resultRef?: string;
  };
  failure?: {
    invocationId?: string;
    operationId?: string;
    traceId?: string;
    patchTargetDraftId?: string;
  };
}

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function getActiveViewRevision(): RecordValue | null {
  return isRecord(activeSkillViewRevision) ? activeSkillViewRevision : null;
}

function getSopViewModel(): SopViewModel | null {
  const revision = getActiveViewRevision();
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : null;
  if (!viewModel) return null;
  const template =
    stringValue(viewModel?.template) ??
    stringValue(viewModel?.viewTemplate) ??
    stringValue(viewModel?.visualTemplate);
  if (template !== SOP_VIEW_MODEL_TEMPLATE) return null;

  const contextRefs = Array.isArray(viewModel.contextRefs)
    ? viewModel.contextRefs.filter(isRecord).map((item) => ({
      id: stringValue(item.id) ?? stringValue(item.contextRef) ?? '',
      label: stringValue(item.label) ?? stringValue(item.name) ?? stringValue(item.title),
      kind: stringValue(item.kind) ?? stringValue(item.type),
      status: stringValue(item.status),
    })).filter((item) => item.id)
    : [];
  const steps = Array.isArray(viewModel.steps)
    ? viewModel.steps.filter(isRecord).map((item, index) => ({
      id: stringValue(item.id) ?? `step-${index + 1}`,
      title: stringValue(item.title) ?? stringValue(item.name) ?? `Step ${index + 1}`,
      description: stringValue(item.description),
      condition: stringValue(item.condition),
      status: stringValue(item.status),
      output: stringValue(item.output) ?? stringValue(item.result),
      evidenceRef: stringValue(item.evidenceRef),
    }))
    : [];
  const inputContract = Array.isArray(viewModel.inputContract)
    ? viewModel.inputContract.filter(isRecord).map((item) => ({
      name: stringValue(item.name) ?? '',
      type: stringValue(item.type),
      required: item.required === true,
      description: stringValue(item.description),
    })).filter((item) => item.name)
    : [];
  const run = isRecord(viewModel.run)
    ? {
      status: stringValue(viewModel.run.status),
      operationId: stringValue(viewModel.run.operationId),
      traceId: stringValue(viewModel.run.traceId),
      executionState: stringValue(viewModel.run.executionState),
      outputSummary: stringValue(viewModel.run.outputSummary),
      resultRef: stringValue(viewModel.run.resultRef),
    }
    : undefined;
  const failure = isRecord(viewModel.failure)
    ? {
      invocationId: stringValue(viewModel.failure.invocationId),
      operationId: stringValue(viewModel.failure.operationId),
      traceId: stringValue(viewModel.failure.traceId),
      patchTargetDraftId: stringValue(viewModel.failure.patchTargetDraftId),
    }
    : undefined;

  return {
    template: SOP_VIEW_MODEL_TEMPLATE,
    title: stringValue(viewModel.title),
    versionLabel: stringValue(viewModel.versionLabel),
    status: stringValue(viewModel.status),
    scope: stringValue(viewModel.scope),
    trigger: stringValue(viewModel.trigger),
    draftId: stringValue(viewModel.draftId) ?? stringValue(isRecord(revision?.intent) ? revision.intent.skillId : undefined),
    revision: numberValue(viewModel.revision) ?? numberValue(isRecord(revision?.intent) ? revision.intent.skillRevision : undefined),
    inputContract,
    contextRefs,
    steps,
    run,
    failure,
  };
}

function IconBase({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

function PlayIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M8 5.8v12.4L18 12 8 5.8Z" /></IconBase>;
}

function AlertIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M12 4 3.5 19h17L12 4Z" /><path d="M12 9v4" /><path d="M12 16h.01" /></IconBase>;
}

function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="m5 12.5 4 4L19 7" /></IconBase>;
}

function BranchIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M6 5v14" /><path d="M6 8h7a5 5 0 0 1 5 5v6" /><path d="M15 16l3 3 3-3" /></IconBase>;
}

function WandIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="m4 20 10.5-10.5" /><path d="m13 5 6 6" /><path d="m12 2 1 3" /><path d="m19 13 3 1" /><path d="M3 8l3 1" /></IconBase>;
}

function GatedState({ runState }: { runState: RunState }) {
  return (
    <section className="flex min-h-[560px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50 p-6 md:p-8">
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-700">
            <AlertIcon className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-900">等待 SopViewModel</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              当前路由已进入统一 Skill 工作台，但服务端尚未返回 SOP typed ViewModel。页面不会用 URL、fileId 或前端固定数组拼出业务内容。
            </p>
          </div>
        </div>
      </div>
      <div className="grid flex-1 gap-4 p-6 md:grid-cols-3 md:p-8">
        {[
          ['需要 W3', 'SOP_VIEW_MODEL_TEMPLATE 与 steps/inputContract/run 字段'],
          ['需要 W2', 'operationId、runner events、ViewRevision'],
          ['当前状态', runState === 'result' ? 'URL 请求结果态，但无 SkillViewRevision' : 'fail closed / gated'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
            <div className="mt-3 text-sm leading-6 text-slate-700">{value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function SkillSOPView({ fileId, searchParams, setSearchParams }: any) {
  const [inputPayload, setInputPayload] = useState('{}');
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const runState = (searchParams.get('run_state') as RunState | null) ?? 'idle';
  const viewRevision = getActiveViewRevision();
  const sopViewModel = useMemo(() => getSopViewModel(), [fileId, searchParams]);
  const operationId = searchParams.get('operation_id') ?? sopViewModel?.run?.operationId;
  const draftId = sopViewModel?.draftId;
  const revision = sopViewModel?.revision ?? Number(searchParams.get('revision') ?? 1);
  const canRun = Boolean(draftId && sopViewModel);
  const canPatch = Boolean((sopViewModel?.failure?.patchTargetDraftId ?? draftId) && feedback.trim());

  const setRunState = (next: RunState) => {
    const params = new URLSearchParams(searchParams);
    params.set('run_state', next);
    if (operationId) params.set('operation_id', operationId);
    setSearchParams(params);
  };

  const addStepContext = (stepId: string, label: string) => {
    const params = new URLSearchParams(searchParams);
    params.set('edit_step', stepId);
    params.set('pane', 'open');
    if (operationId) params.set('operation_id', operationId);
    setSearchParams(params);
    window.dispatchEvent(new CustomEvent('add_context_item', {
      detail: {
        item: {
          id: `${viewRevision?.id ?? fileId}:${stepId}`,
          name: label,
          type: 'element',
          artifactId: viewRevision?.id ?? fileId,
          viewRevisionId: viewRevision?.id,
          selectionIdentity: stepId,
        },
      },
    }));
  };

  const executeRun = async () => {
    if (!draftId) {
      setError('缺少服务端 SkillDraft 标识，无法执行。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-draft.run',
        payload: {
          draftId,
          revision,
          traceId: searchParams.get('trace_id') ?? crypto.randomUUID(),
          maxSteps: 12,
          budget: 1,
        },
      }, createRequestContext());
      if (!response.accepted) throw new Error('服务端未接受试运行请求。');
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      const result = isRecord(response.result) ? response.result : {};
      const skillViewRevision = isRecord(result.skillViewRevision) ? result.skillViewRevision : null;
      const nextOperationId =
        response.operationId ??
        stringValue(result.operationId) ??
        stringValue(isRecord(result.operation) ? result.operation.operationId : undefined);
      const params = new URLSearchParams(searchParams);
      if (nextOperationId) params.set('operation_id', nextOperationId);
      const skillViewRevisionId = skillViewRevision ? stringValue(skillViewRevision.id) : undefined;
      if (skillViewRevisionId) params.set('view_revision_id', skillViewRevisionId);
      params.set('run_state', skillViewRevision ? 'result' : 'running');
      setSearchParams(params);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '试运行失败。');
    } finally {
      setBusy(false);
    }
  };

  const createOptimizationDraft = async () => {
    const targetDraftId = sopViewModel?.failure?.patchTargetDraftId ?? draftId;
    if (!targetDraftId) {
      setError('缺少服务端可修改的 SkillDraft，无法创建优化草稿。');
      return;
    }
    if (!feedback.trim()) {
      setError('请先填写纠偏反馈。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.patch',
        payload: {
          draftId: targetDraftId,
          baseRevision: revision,
          patch: {
            patch_type: 'set_description',
            description: feedback.trim(),
          },
        },
      }, createRequestContext());
      if (!response.accepted) throw new Error('服务端未接受优化草稿请求。');
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      const result = isRecord(response.result) ? response.result : {};
      const draft = isRecord(result.draft) ? result.draft : null;
      const nextDraftId = stringValue(draft?.draft_id) ?? stringValue(draft?.id);
      const nextOperationId = response.operationId ?? stringValue(isRecord(result.operation) ? result.operation.operationId : undefined);
      const params = new URLSearchParams(searchParams);
      if (nextDraftId) params.set('file', nextDraftId);
      if (nextOperationId) params.set('operation_id', nextOperationId);
      params.delete('run_state');
      setSearchParams(params);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建优化草稿失败。');
    } finally {
      setBusy(false);
    }
  };

  const title = sopViewModel?.title ?? 'SOP Skill';
  const versionLabel = sopViewModel?.versionLabel ?? (viewRevision ? `ViewRevision ${String(viewRevision.revision ?? '—')}` : '等待 revision');
  const contextRefs = sopViewModel?.contextRefs ?? [];
  const inputContract = sopViewModel?.inputContract ?? [];
  const steps = sopViewModel?.steps ?? [];

  return (
    <div className="flex h-full min-w-0 flex-col overflow-y-auto p-4 pb-24 md:p-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col">
        <ArtifactHeader
          title={title}
          typeLabel="SOP Skill"
          isTeam={false}
          version={versionLabel}
          searchParams={searchParams}
          setSearchParams={setSearchParams}
        />

        {!sopViewModel ? (
          <GatedState runState={runState} />
        ) : (
          <section className="mt-4 flex min-h-[600px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <header className="border-b border-slate-200 bg-slate-50 p-6 md:p-8">
              <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div>
                  <div className="inline-flex items-center rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
                    <BranchIcon className="mr-1.5 h-3.5 w-3.5" /> typed SopViewModel
                  </div>
                  <h2 className="mt-4 text-xl font-semibold text-slate-900">运行范围与触发条件</h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                    {sopViewModel.scope || sopViewModel.trigger || '服务端尚未提供范围说明。'}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setRunState('input')}
                    disabled={!canRun || busy}
                    className="inline-flex items-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <PlayIcon className="mr-2 h-4 w-4" /> 准备试运行
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const params = new URLSearchParams(searchParams);
                      params.set('modal', 'publish_agent');
                      setSearchParams(params);
                    }}
                    disabled={runState !== 'result' || !viewRevision}
                    className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <CheckIcon className="mr-2 h-4 w-4" /> 发布给 Agent
                  </button>
                </div>
              </div>

              {contextRefs.length > 0 && (
                <div className="mt-6 flex flex-wrap gap-2">
                  {contextRefs.map((item) => (
                    <span key={item.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                      <span className="font-semibold text-slate-800">{item.label ?? item.id}</span>
                      {item.kind && <span className="ml-1 text-slate-400">· {item.kind}</span>}
                    </span>
                  ))}
                </div>
              )}

              {runState === 'input' && (
                <div className="mt-6 rounded-xl border border-blue-200 bg-white p-5 shadow-sm">
                  <label className="block text-sm font-semibold text-slate-800" htmlFor="sop-run-payload">试运行输入</label>
                  <p className="mt-1 text-xs leading-5 text-slate-500">输入契约由服务端 ViewModel 展示；Runner 输入引用等待 W2 typed seam 返回，页面不会在本地合成结果。</p>
                  <textarea
                    id="sop-run-payload"
                    value={inputPayload}
                    onChange={(event) => setInputPayload(event.target.value)}
                    rows={5}
                    className="mt-3 w-full resize-none rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs outline-none focus:border-blue-500"
                  />
                  {inputContract.length > 0 && (
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {inputContract.map((item) => (
                        <div key={item.name} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                          <span className="font-semibold text-slate-800">{item.name}</span>
                          {item.type && <span className="ml-1 text-slate-400">({item.type})</span>}
                          {item.required && <span className="ml-2 text-red-600">required</span>}
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="mt-4 flex justify-end gap-3">
                    <button type="button" onClick={() => setRunState('idle')} className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">取消</button>
                    <button type="button" onClick={() => void executeRun()} disabled={!canRun || busy} className="inline-flex items-center rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">
                      <PlayIcon className="mr-2 h-4 w-4" /> 执行
                    </button>
                  </div>
                </div>
              )}

              {runState === 'running' && (
                <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5" aria-live="polite">
                  <div className="text-sm font-semibold text-slate-800">已提交真实执行请求</div>
                  <p className="mt-2 text-xs leading-5 text-slate-500">等待 W2 operation/timeline events 返回。operationId：{operationId ?? '服务端尚未返回'}</p>
                </div>
              )}

              {runState === 'result' && (
                <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
                  {sopViewModel.run?.outputSummary ? (
                    <div className="text-sm leading-6 text-slate-700">{sopViewModel.run.outputSummary}</div>
                  ) : (
                    <div className="text-sm text-slate-500">等待 Runner 返回包含输出摘要的 SkillViewRevision。</div>
                  )}
                </div>
              )}
            </header>

            <main className="flex-1 bg-white p-6 md:p-8">
              <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <h3 className="text-lg font-semibold text-slate-900">SOP 步骤</h3>
                <div className="text-xs text-slate-500">revision: {String(viewRevision?.id ?? 'pending')}</div>
              </div>
              {steps.length === 0 ? (
                <div className="flex min-h-56 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500">
                  服务端 ViewModel 尚未返回步骤。
                </div>
              ) : (
                <div className="relative space-y-5 pl-6 before:absolute before:inset-y-4 before:left-[11px] before:w-0.5 before:bg-slate-200">
                  {steps.map((step, index) => (
                    <button key={step.id} type="button" onClick={() => addStepContext(step.id, step.title)} className="relative block w-full text-left">
                      <span className="absolute -left-6 top-1 z-10 h-6 w-6 rounded-full border-4 border-white bg-blue-500 shadow-sm" />
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 shadow-sm transition hover:border-blue-400 focus-within:border-blue-400">
                        <div className="flex items-start justify-between gap-3">
                          <h4 className="text-sm font-semibold text-slate-800"><span className="mr-2 text-slate-400">{index + 1}.</span>{step.title}</h4>
                          {step.status && <span className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-600">{step.status}</span>}
                        </div>
                        {step.description && <p className="mt-2 text-sm leading-6 text-slate-600">{step.description}</p>}
                        {step.condition && <div className="mt-3 rounded border border-slate-200 bg-white p-2 font-mono text-xs text-slate-600">{step.condition}</div>}
                        {step.output && <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-700">{step.output}</div>}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </main>

            <footer className="border-t border-slate-200 bg-slate-50 p-6 md:p-8">
              <label className="block text-sm font-semibold text-slate-800" htmlFor="sop-feedback">纠偏反馈</label>
              <p className="mt-1 text-xs leading-5 text-slate-500">提交后只调用 skill-authoring.patch；是否产生新草稿和目标 draftId 以服务端响应为准。</p>
              <div className="mt-3 flex flex-col gap-3 md:flex-row">
                <textarea id="sop-feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} className="min-h-20 flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500" />
                <button type="button" onClick={() => void createOptimizationDraft()} disabled={!canPatch || busy} className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 md:self-end">
                  <WandIcon className="mr-2 h-4 w-4" /> 创建修订
                </button>
              </div>
            </footer>
          </section>
        )}

        {error && (
          <div role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertIcon className="mr-2 inline h-4 w-4" />{error}
          </div>
        )}
      </div>
    </div>
  );
}
