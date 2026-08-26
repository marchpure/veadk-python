import { useMemo, type SVGProps } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import { getResourceDescriptor, resourceStore } from '../../lib/store';

export const EXPLORE_VIEW_MODEL_TEMPLATE = 'dataset';

type RecordValue = Record<string, unknown>;

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function getDatasetViewModel(): RecordValue | null {
  const revision = isRecord(activeSkillViewRevision) ? activeSkillViewRevision : null;
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : null;
  if (viewModel?.template !== EXPLORE_VIEW_MODEL_TEMPLATE) return null;
  return viewModel;
}

function IconBase({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

function SparkIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="m12 3 1.4 4.4L18 9l-4.6 1.6L12 15l-1.4-4.4L6 9l4.6-1.6L12 3Z" /><path d="M5 15l.8 2.2L8 18l-2.2.8L5 21l-.8-2.2L2 18l2.2-.8L5 15Z" /></IconBase>;
}

function ArrowIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></IconBase>;
}

function AlertIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M12 4 3.5 19h17L12 4Z" /><path d="M12 9v4" /><path d="M12 16h.01" /></IconBase>;
}

export default function ExploreView({ fileId, setSearchParams, searchParams }: any) {
  const descriptor = useMemo(
    () => getResourceDescriptor(fileId, searchParams, resourceStore.getState()),
    [fileId, searchParams],
  );
  const viewModel = useMemo(() => getDatasetViewModel(), [fileId, searchParams]);
  const hasServerContext = Boolean(descriptor && viewModel);

  if (!hasServerContext) {
    return (
      <section className="flex h-full w-full flex-col items-center justify-center bg-white p-8 text-center">
        <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl border border-amber-100 bg-amber-50 text-amber-700 shadow-sm">
          <AlertIcon className="h-9 w-9" />
        </div>
        <h1 className="mb-3 text-2xl font-semibold text-slate-900">等待服务端数据</h1>
        <p className="mb-8 max-w-md text-sm leading-6 text-slate-500">
          探索页需要真实资源 descriptor 与 DatasetViewModel。当前不会根据 URL、模板名或前端固定数组生成探索问题。
        </p>
        <button
          type="button"
          className="inline-flex items-center rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          onClick={() => {
            const params = new URLSearchParams(searchParams || window.location.search);
            params.delete('explore');
            params.set('file', 'data_overview');
            params.set('explore_pending', 'true');
            setSearchParams(params);
          }}
        >
          前往数据源选择 <ArrowIcon className="ml-2 h-4 w-4" />
        </button>
      </section>
    );
  }

  const contextName = stringValue(descriptor?.name) ?? stringValue(viewModel?.title) ?? '当前数据集';
  const fieldCount = Array.isArray(viewModel?.fields) ? viewModel.fields.length : 0;
  const dataRef = isRecord(viewModel?.dataRef) ? viewModel.dataRef : null;

  return (
    <div className="mx-auto w-full max-w-4xl p-6 md:p-12">
      <div className="mb-10">
        <div className="mb-4 flex w-fit items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-sm font-medium text-blue-600">
          <SparkIcon className="h-4 w-4" />
          <span>智能分析探索</span>
        </div>
        <h1 className="mb-4 text-3xl font-semibold tracking-tight text-slate-900">
          你想了解关于 <span className="text-blue-600">{contextName}</span> 的什么？
        </h1>
        <p className="max-w-2xl text-sm leading-6 text-slate-500">
          请在右侧 Agent 面板输入自然语言目标。候选问题、字段解释和图表建议由服务端 Agent 基于 typed ViewModel 生成。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {[
          ['字段数量', String(fieldCount)],
          ['数据引用', dataRef?.uri ? '已返回' : '未返回'],
          ['上下文状态', descriptor?.contextRef ? '可加入 Agent' : '等待 ContextRef'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
            <div className="mt-3 text-sm font-medium text-slate-800">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
