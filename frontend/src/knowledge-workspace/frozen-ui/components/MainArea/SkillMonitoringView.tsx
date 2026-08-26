import { useMemo, useState, type SVGProps } from 'react';
import ArtifactHeader from './ArtifactHeader';
import { activeSkillViewRevision } from '../../../production/data';
import type { MonitoringViewModel } from '../../../production/generatedContracts';
import { createRequestContext } from '../../../production/ports';
import { bootstrapWorkspace, getWorkspaceAdapter } from '../../../production/store';
import { resourceStore } from '../../lib/store';

export const MONITORING_VIEW_MODEL_TEMPLATE = 'monitoring';

type RecordValue = Record<string, unknown>;

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function getActiveViewRevision(): RecordValue | null {
  return isRecord(activeSkillViewRevision) ? activeSkillViewRevision : null;
}

function getMonitoringViewModel(): MonitoringViewModel | null {
  const revision = getActiveViewRevision();
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : null;
  if (viewModel?.template !== MONITORING_VIEW_MODEL_TEMPLATE) return null;
  return viewModel as MonitoringViewModel;
}

function IconBase({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

function AlertIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M12 4 3.5 19h17L12 4Z" /><path d="M12 9v4" /><path d="M12 16h.01" /></IconBase>;
}

function PulseIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M4 13h3l2-6 4 12 2-6h5" /></IconBase>;
}

function SearchIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 5 5" /></IconBase>;
}

function WandIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="m4 20 10.5-10.5" /><path d="m13 5 6 6" /><path d="m12 2 1 3" /><path d="M3 8l3 1" /></IconBase>;
}

function PackageIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9Z" /><path d="m4 7.5 8 4.5 8-4.5" /><path d="M12 12v9" /></IconBase>;
}

function GatedMonitoringState() {
  return (
    <section className="mt-6 flex min-h-[520px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50 p-6 md:p-8">
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-700">
            <AlertIcon className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-900">等待 MonitoringViewModel</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              当前已进入已发布 Skill 的监控视图，但服务端尚未返回 Invocation、trace、latency、freshness 或 failure 数据。页面不会展示前端固定指标或固定 trace。
            </p>
          </div>
        </div>
      </div>
      <div className="grid flex-1 gap-4 p-6 md:grid-cols-3 md:p-8">
        {[
          ['监控数据', '等待 MonitoringViewModel.values / alerts / dataRef'],
          ['调用记录', '等待 W2/W3 提供 Invocation/Operation evidence'],
          ['失败优化', '仅在服务端返回 failure/operation 目标后可提交 patch'],
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

export default function SkillMonitoringView({ fileId, searchParams, setSearchParams, showToast }: any) {
  const [failurePatch, setFailurePatch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const viewRevision = getActiveViewRevision();
  const monitoringViewModel = useMemo(() => getMonitoringViewModel(), [fileId, searchParams]);
  const publishedResource = resourceStore.getState().find((item: any) => item.id === fileId || item.resourceId === fileId) as any;
  const intent = isRecord(viewRevision?.intent) ? viewRevision.intent : {};
  const skillId = stringValue(intent.skillId) ?? fileId;
  const skillRevision = typeof intent.skillRevision === 'number' ? intent.skillRevision : Number(searchParams.get('revision') ?? 1);
  const publishedName = String(publishedResource?.displayName ?? publishedResource?.name ?? 'Published Skill');
  const publishedKind = String(
    publishedResource?.readModel?.publishedVersion?.manifest?.spec?.kind ??
    publishedResource?.readModel?.publishedVersion?.manifest?.spec?.defaultRenderer ??
    'sop',
  );
  const publishedTypeLabel = publishedKind === 'sop'
    ? 'Published SOP Skill'
    : publishedKind === 'dashboard' || publishedKind === 'analysis'
      ? 'Published Dashboard Skill'
      : 'Published Skill';
  const values = Array.isArray(monitoringViewModel?.values) ? monitoringViewModel.values : [];
  const metricRefs = Array.isArray(monitoringViewModel?.metricRefs) ? monitoringViewModel.metricRefs : [];
  const alerts = Array.isArray(monitoringViewModel?.alerts) ? monitoringViewModel.alerts : [];
  const dataRef = monitoringViewModel?.dataRef;
  const canOptimize = Boolean(monitoringViewModel && failurePatch.trim());

  const createOptimization = async () => {
    if (!canOptimize) {
      setError('缺少服务端 failure 证据或纠偏描述，无法创建优化草稿。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'skill-authoring.patch',
        payload: {
          draftId: skillId,
          baseRevision: skillRevision,
          patch: {
            patch_type: 'set_description',
            description: failurePatch.trim(),
          },
        },
      }, createRequestContext());
      if (!response.accepted) throw new Error('服务端未接受优化草稿请求。');
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      const result = isRecord(response.result) ? response.result : {};
      const draft = isRecord(result.draft) ? result.draft : null;
      const nextDraftId = stringValue(draft?.draft_id) ?? stringValue(draft?.id);
      const params = new URLSearchParams(searchParams);
      if (nextDraftId) params.set('file', nextDraftId);
      if (response.operationId) params.set('operation_id', response.operationId);
      setSearchParams(params);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '创建优化草稿失败。');
    } finally {
      setBusy(false);
    }
  };

  const customActions = [
    {
      label: '导出 Skill 文件',
      primary: false,
      icon: PackageIcon,
      onClick: () => showToast?.('导出需要 artifact.export 返回 StorageRef；当前未写入本地文件。'),
    },
    {
      label: '在 Agent 中使用',
      primary: true,
      icon: PackageIcon,
      onClick: () => {
        const params = new URLSearchParams(searchParams);
        params.set('modal', 'publish_agent');
        setSearchParams(params);
      },
    },
  ];

  return (
    <div className="flex h-full min-w-0 flex-col overflow-y-auto p-4 pb-20 md:p-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col">
        <ArtifactHeader
          title={publishedName}
          typeLabel={publishedTypeLabel}
          isTeam
          version={`V${String(publishedResource?.version ?? '1.0.0').replace(/^v/i, '').split('.')[0]}.0 发布版`}
          searchParams={searchParams}
          setSearchParams={setSearchParams}
          showToast={showToast}
          customActions={customActions}
        />

        {!monitoringViewModel ? (
          <GatedMonitoringState />
        ) : (
          <>
            <section className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-4">
              {metricRefs.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500 md:col-span-4">
                  MonitoringViewModel 未返回 metricRefs。
                </div>
              ) : (
                metricRefs.map((metricRef, index) => (
                  <div key={metricRef} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{metricRef}</div>
                    <div className="text-2xl font-semibold tracking-tight text-slate-900">
                      {Array.isArray(values[index]) ? String(values[index][1]) : '—'}
                    </div>
                    {Array.isArray(values[index]) && <div className="mt-1 text-xs text-slate-500">{String(values[index][0])}</div>}
                  </div>
                ))
              )}
            </section>

            <section className="mt-8 flex min-h-[360px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="flex shrink-0 flex-col gap-3 border-b border-slate-200 bg-slate-50 p-5 md:flex-row md:items-center md:justify-between">
                <h3 className="flex items-center font-semibold text-slate-800">
                  <PulseIcon className="mr-2 h-4 w-4 text-blue-600" /> 运行记录与失败追踪
                </h3>
                <div className="flex items-center gap-2">
                  <div className="relative hidden sm:block">
                    <SearchIcon className="absolute left-3 top-2 h-3.5 w-3.5 text-slate-400" />
                    <input className="rounded-md border border-slate-200 py-1.5 pl-8 pr-3 text-xs outline-none focus:border-blue-500" placeholder="由服务端搜索 trace" disabled />
                  </div>
                  <button type="button" disabled className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-400 shadow-sm">
                    筛选等待服务端
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-auto p-5">
                {alerts.length > 0 && (
                  <div className="mb-4 space-y-2">
                    {alerts.map((alert) => (
                      <div key={alert} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        <AlertIcon className="mr-2 inline h-4 w-4" />{alert}
                      </div>
                    ))}
                  </div>
                )}
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-5">
                  <div className="text-sm font-semibold text-slate-800">监控数据引用</div>
                  <dl className="mt-3 grid gap-3 text-xs md:grid-cols-2">
                    <div><dt className="font-semibold text-slate-500">dataRef.uri</dt><dd className="mt-1 break-all text-slate-700">{dataRef?.uri ?? '—'}</dd></div>
                    <div><dt className="font-semibold text-slate-500">mediaType</dt><dd className="mt-1 text-slate-700">{dataRef?.mediaType ?? '—'}</dd></div>
                    <div><dt className="font-semibold text-slate-500">sha256</dt><dd className="mt-1 break-all text-slate-700">{dataRef?.sha256 ?? '—'}</dd></div>
                    <div><dt className="font-semibold text-slate-500">bytes</dt><dd className="mt-1 text-slate-700">{dataRef?.bytes ?? '—'}</dd></div>
                  </dl>
                </div>
              </div>
            </section>

            <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <label htmlFor="monitoring-failure-patch" className="text-sm font-semibold text-slate-800">失败案例优化</label>
              <p className="mt-1 text-xs leading-5 text-slate-500">只有服务端返回失败证据后才提交 patch；当前输入不会生成本地成功态。</p>
              <div className="mt-3 flex flex-col gap-3 md:flex-row">
                <textarea
                  id="monitoring-failure-patch"
                  value={failurePatch}
                  onChange={(event) => setFailurePatch(event.target.value)}
                  className="min-h-20 flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
                />
                <button type="button" onClick={() => void createOptimization()} disabled={!canOptimize || busy} className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 md:self-end">
                  <WandIcon className="mr-2 h-4 w-4" /> 创建优化草稿
                </button>
              </div>
            </section>
          </>
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
