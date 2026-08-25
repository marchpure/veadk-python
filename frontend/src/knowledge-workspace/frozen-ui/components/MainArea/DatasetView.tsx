import { useMemo, useState, type SVGProps } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import { resourceStore } from '../../lib/store';
import { cn } from '../../lib/utils';

export const DATASET_VIEW_MODEL_TEMPLATE = 'dataset';

type RecordValue = Record<string, unknown>;

export interface DatasetViewModel {
  template?: typeof DATASET_VIEW_MODEL_TEMPLATE;
  title?: string;
  sourceLabel?: string;
  updatedAt?: string;
  dataRef?: { uri?: string; mediaType?: string; sha256?: string; bytes?: number | null } | null;
  stats?: Array<{ label: string; value: string; description?: string }>;
  fields?: Array<{ name: string; type?: string; role?: string; description?: string; sampleValue?: string; nullRate?: string }>;
  rows?: Array<Record<string, unknown>>;
  quality?: Array<{ label: string; status: string; detail?: string }>;
  lineage?: Array<{ label: string; value: string }>;
  usage?: Array<{ label: string; actor?: string; at?: string; status?: string }>;
}

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function getDatasetViewModel(): DatasetViewModel | null {
  const revision = isRecord(activeSkillViewRevision) ? activeSkillViewRevision : null;
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : null;
  if (viewModel?.template !== DATASET_VIEW_MODEL_TEMPLATE) return null;
  return viewModel as DatasetViewModel;
}

function IconBase({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

function DatasetIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M4 7c0-2 16-2 16 0v10c0 2-16 2-16 0V7Z" /><path d="M4 7c0 2 16 2 16 0" /><path d="M4 12c0 2 16 2 16 0" /></IconBase>;
}

function AlertIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M12 4 3.5 19h17L12 4Z" /><path d="M12 9v4" /><path d="M12 16h.01" /></IconBase>;
}

function ArrowIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></IconBase>;
}

function getResource(fileId: string) {
  return resourceStore.getState().find((item: any) => item.id === fileId || item.resourceId === fileId);
}

function GatedDatasetState({ fileId, searchParams, setSearchParams }: any) {
  const openConnectors = () => {
    const params = new URLSearchParams(searchParams);
    params.set('file', 'add_data');
    params.set('step', '1');
    setSearchParams(params);
  };

  return (
    <section className="mx-auto flex w-full max-w-5xl flex-1 flex-col p-4 md:p-8">
      <div className="flex min-h-[560px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-slate-50 p-6 md:p-8">
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-700">
              <AlertIcon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="text-lg font-semibold text-slate-900">等待服务端数据</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                当前资源尚未返回 DatasetViewModel。页面不会根据 URL、fileId 或前端固定数组生成数据预览、质量分、血缘或使用记录。
              </p>
              <div className="mt-3 text-xs text-slate-500">
                resource: <span className="font-mono">{fileId || '—'}</span>
              </div>
            </div>
          </div>
        </div>
        <div className="grid flex-1 gap-4 p-6 md:grid-cols-3 md:p-8">
          {[
            ['需要 W1/W3', 'Golden data revision、schemaRef、sample rows 和 quality result'],
            ['当前展示', 'gated/empty 状态，不展示固定成功结果'],
            ['下一步', '连接真实数据后由服务端 bootstrap 返回 typed ViewModel'],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-5">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
              <div className="mt-3 text-sm leading-6 text-slate-700">{value}</div>
            </div>
          ))}
        </div>
        <div className="border-t border-slate-200 bg-white p-5">
          <button
            type="button"
            onClick={openConnectors}
            className="inline-flex items-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            连接真实数据 <ArrowIcon className="ml-2 h-4 w-4" />
          </button>
        </div>
      </div>
    </section>
  );
}

export default function DatasetView({ setSearchParams, searchParams, fileId, showToast }: any) {
  const [activeTab, setActiveTab] = useState('overview');
  const viewModel = useMemo(() => getDatasetViewModel(), [fileId, searchParams]);
  const resource = getResource(fileId);
  const title = viewModel?.title ?? stringValue(resource?.displayName) ?? stringValue(resource?.name) ?? 'Dataset';
  const fields = Array.isArray(viewModel?.fields) ? viewModel.fields : [];
  const rows = Array.isArray(viewModel?.rows) ? viewModel.rows : [];
  const stats = Array.isArray(viewModel?.stats) ? viewModel.stats : [];
  const quality = Array.isArray(viewModel?.quality) ? viewModel.quality : [];
  const lineage = Array.isArray(viewModel?.lineage) ? viewModel.lineage : [];
  const usage = Array.isArray(viewModel?.usage) ? viewModel.usage : [];

  if (!viewModel) {
    return <GatedDatasetState fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} />;
  }

  const handleExploreAction = () => {
    window.dispatchEvent(new CustomEvent('add_context_item', {
      detail: {
        item: {
          id: fileId,
          name: title,
          type: 'dataset',
          contextRef: resource?.contextRef,
        },
      },
    }));
    showToast?.('上下文已从服务端资源加入右侧 Agent。');
    const params = new URLSearchParams(searchParams || window.location.search);
    params.set('pane', 'open');
    setSearchParams(params);
  };

  const tabs = [
    { id: 'overview', label: '概览' },
    { id: 'preview', label: '数据预览' },
    { id: 'fields', label: '字段' },
    { id: 'lineage', label: '血缘与来源' },
    { id: 'quality', label: '数据质量' },
    { id: 'usage', label: '使用记录' },
  ];

  return (
    <div className="mx-auto flex h-full w-full max-w-6xl min-w-0 flex-col overflow-hidden p-4 md:p-8">
      <div className="mb-6 flex shrink-0 flex-col gap-4 border-b border-slate-100 pb-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
              <DatasetIcon className="h-5 w-5" />
            </div>
            <h1 className="truncate pr-4 text-xl font-semibold text-slate-900 md:text-2xl">{title}</h1>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-slate-500">
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1">source: {viewModel.sourceLabel ?? '—'}</span>
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1">updated: {viewModel.updatedAt ?? '—'}</span>
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1">dataRef: {viewModel.dataRef?.uri ? 'available' : '—'}</span>
          </div>
        </div>
        <button
          type="button"
          onClick={handleExploreAction}
          className="inline-flex w-full items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 md:w-auto"
        >
          加入 Agent 上下文 <ArrowIcon className="ml-2 h-4 w-4" />
        </button>
      </div>

      <div className="flex shrink-0 space-x-6 overflow-x-auto border-b border-slate-200 custom-scrollbar" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`panel-${tab.id}`}
            id={`tab-${tab.id}`}
            className={cn('whitespace-nowrap border-b-2 pb-3 text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2', activeTab === tab.id ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-800')}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mt-6 flex min-h-[420px] flex-1 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
        {activeTab === 'overview' && (
          <div className="grid gap-4 p-5 md:grid-cols-3">
            {stats.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-sm text-slate-500 md:col-span-3">服务端未返回 stats。</div>
            ) : stats.map((item) => (
              <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50 p-5">
                <div className="text-xs font-medium text-slate-500">{item.label}</div>
                <div className="mt-2 text-2xl font-semibold text-slate-900">{item.value}</div>
                {item.description && <div className="mt-1 text-xs text-slate-500">{item.description}</div>}
              </div>
            ))}
          </div>
        )}

        {activeTab === 'preview' && (
          <div className="overflow-auto">
            {rows.length === 0 || fields.length === 0 ? (
              <div className="flex h-64 items-center justify-center text-sm text-slate-400">服务端未返回可预览行。</div>
            ) : (
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="sticky top-0 border-b border-slate-200 bg-slate-50 text-xs text-slate-600">
                  <tr>{fields.map((field) => <th key={field.name} className="px-4 py-3 font-medium">{field.name}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className="hover:bg-slate-50">
                      {fields.map((field) => (
                        <td key={field.name} className="px-4 py-3 text-slate-700">{String(row[field.name] ?? '—')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeTab === 'fields' && (
          <div className="overflow-auto">
            {fields.length === 0 ? (
              <div className="flex h-64 items-center justify-center text-sm text-slate-400">服务端未返回字段 schema。</div>
            ) : (
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="sticky top-0 border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
                  <tr><th className="px-6 py-3 font-medium">字段名称</th><th className="px-6 py-3 font-medium">类型</th><th className="px-6 py-3 font-medium">角色</th><th className="px-6 py-3 font-medium">描述</th><th className="px-6 py-3 font-medium">空值率</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {fields.map((field) => (
                    <tr key={field.name} className="hover:bg-slate-50">
                      <td className="px-6 py-3 font-medium text-slate-700">{field.name}</td>
                      <td className="px-6 py-3 text-slate-500">{field.type ?? '—'}</td>
                      <td className="px-6 py-3 text-slate-500">{field.role ?? '—'}</td>
                      <td className="px-6 py-3 text-slate-600">{field.description ?? '—'}</td>
                      <td className="px-6 py-3 text-slate-500">{field.nullRate ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeTab === 'lineage' && (
          <div className="grid gap-4 p-5 md:grid-cols-2">
            {lineage.length === 0 ? <div className="text-sm text-slate-400">服务端未返回 lineage。</div> : lineage.map((item) => (
              <div key={item.label} className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm"><span className="font-semibold text-slate-700">{item.label}</span><span className="ml-2 text-slate-600">{item.value}</span></div>
            ))}
          </div>
        )}

        {activeTab === 'quality' && (
          <div className="space-y-3 p-5">
            {quality.length === 0 ? <div className="text-sm text-slate-400">服务端未返回 quality result。</div> : quality.map((item) => (
              <div key={item.label} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-800">{item.label}</div>
                <div className="mt-1 text-xs text-slate-500">{item.status}{item.detail ? ` · ${item.detail}` : ''}</div>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'usage' && (
          <div className="space-y-3 p-5">
            {usage.length === 0 ? <div className="text-sm text-slate-400">服务端未返回使用记录。</div> : usage.map((item) => (
              <div key={`${item.label}-${item.at ?? ''}`} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-800">{item.label}</div>
                <div className="mt-1 text-xs text-slate-500">{item.actor ?? '—'} · {item.at ?? '—'} · {item.status ?? '—'}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
