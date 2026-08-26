import { useCallback, useMemo, useState, type SVGProps } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import { createRequestContext } from '../../../production/ports';
import { bootstrapWorkspace, getWorkspaceAdapter, resourceStore } from '../../../production/store';
import ArtifactHeader from './ArtifactHeader';
import {
  TrustedHtmlArtifactRenderer,
  type TrustedArtifactEvent,
} from './TrustedHtmlArtifactRenderer';

type RecordValue = Record<string, unknown>;

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
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

function AuditIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M7 4h10" /><path d="M6 8h12" /><path d="M8 12h8" /><path d="M9 16h6" /><rect x="4" y="3" width="16" height="18" rx="2.5" /></IconBase>;
}

function skillIdFromRevision(revision: RecordValue | null, fallback: string): string {
  const intent = isRecord(revision?.intent) ? revision.intent : {};
  const fromIntent = stringValue(intent.skillId);
  if (fromIntent) return fromIntent;
  const skillRevisionId =
    stringValue(revision?.skillRevisionId) ??
    stringValue(revision?.skill_revision_id);
  if (skillRevisionId?.includes(':')) {
    return skillRevisionId.slice(0, skillRevisionId.lastIndexOf(':'));
  }
  return fallback;
}

function resultRefFromRevision(revision: RecordValue | null): RecordValue | null {
  const resultRef = revision?.resultRef ?? revision?.result_ref;
  return isRecord(resultRef) ? resultRef : null;
}

function hasTrustedHtmlRevision(revision: RecordValue | null): boolean {
  const resultRef = resultRefFromRevision(revision);
  const manifest = isRecord(revision?.manifest) ? revision.manifest : {};
  const cspProfile = manifest.cspProfile ?? manifest.csp_profile;
  const mediaType = resultRef?.mediaType ?? resultRef?.media_type;
  return Boolean(
    revision &&
    resultRef &&
    cspProfile === 'trusted-renderer-v1' &&
    mediaType === 'text/html' &&
    typeof resultRef.sha256 === 'string' &&
    typeof resultRef.bytes === 'number',
  );
}

function titleFromRevision(revision: RecordValue | null, fileId: string): string {
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : {};
  const resource = resourceStore.getState().find((item) => item.id === fileId || item.resourceId === fileId);
  return (
    stringValue(viewModel.title) ??
    stringValue(resource?.displayName) ??
    stringValue(resource?.name) ??
    'Skill HTML revision'
  );
}

function templateLabel(revision: RecordValue | null, fallback = 'Skill'): string {
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : {};
  const template = stringValue(viewModel.template) ?? stringValue(viewModel.viewTemplate) ?? fallback;
  const labels: Record<string, string> = {
    dashboard: 'Dashboard Skill',
    chart: 'Dashboard Skill',
    semantic: 'Semantic Skill',
    sop: 'SOP Skill',
    knowledge: 'Knowledge Skill',
    graph_ontology: 'Knowledge Graph Skill',
    monitoring: 'Monitoring Skill',
    html: 'HTML Skill',
  };
  return labels[template] ?? `${template} Skill`;
}

function contextTagsFromRevision(revision: RecordValue | null): Array<{ name: string; desc: string }> {
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : {};
  const steps = Array.isArray(viewModel.stepResults) ? viewModel.stepResults : [];
  const toolRefs = steps.flatMap((step) => {
    if (!isRecord(step) || !Array.isArray(step.toolRefs)) return [];
    return step.toolRefs.filter((item): item is string => typeof item === 'string' && item.trim());
  });
  const uniqueTools = [...new Set(toolRefs)];
  const dataRefs = Array.isArray(revision?.dataRevisionRefs)
    ? revision.dataRevisionRefs.filter((item): item is string => typeof item === 'string' && item.trim())
    : [];
  return [...uniqueTools, ...dataRefs].slice(0, 4).map((value) => ({
    name: value,
    desc: '服务端已授权上下文',
  }));
}

function addArtifactContext(event: TrustedArtifactEvent, name: string) {
  window.dispatchEvent(new CustomEvent('add_context_item', {
    detail: {
      item: {
        id: event.elementId ?? event.revisionId,
        name: event.elementId ?? name,
        type: event.type === 'context.reference' ? 'artifact' : 'element',
        viewRevisionId: event.revisionId,
        selectionIdentity: event.value,
        isResourceLevel: event.type === 'context.reference',
      },
    },
  }));
}

function GatedHtmlRevisionState({
  revision,
  fileId,
}: {
  revision: RecordValue | null;
  fileId: string;
}) {
  const viewModel = isRecord(revision?.viewModel) ? revision.viewModel : null;
  const template = stringValue(viewModel?.template) ?? 'unknown';
  return (
    <section className="flex min-h-[560px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center shadow-sm" role="status">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-700">
        <AlertIcon className="h-5 w-5" />
      </div>
      <h2 className="mt-5 text-lg font-semibold text-slate-900">等待服务端返回 HTML ViewRevision</h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
        当前 Skill 深链已保留，但服务端尚未返回可验证的 trusted HTML artifact。页面不会用前端固定结果、模板关键词或 URL 参数拼出成功状态。
      </p>
      <div className="mt-5 grid w-full max-w-2xl gap-3 text-left md:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Route</div>
          <div className="mt-2 break-all text-xs text-slate-700">{fileId}</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Template</div>
          <div className="mt-2 break-all text-xs text-slate-700">{template}</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Required seam</div>
          <div className="mt-2 text-xs text-slate-700">SkillViewRevision.resultRef</div>
        </div>
      </div>
    </section>
  );
}

export default function SkillHtmlRevisionView({ fileId, searchParams, setSearchParams }: any) {
  const revision = isRecord(activeSkillViewRevision) ? activeSkillViewRevision : null;
  const [pending, setPending] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [auditOpen, setAuditOpen] = useState(false);
  const skillId = useMemo(() => skillIdFromRevision(revision, fileId), [revision, fileId]);
  const title = useMemo(() => titleFromRevision(revision, fileId), [revision, fileId]);
  const typeLabel = useMemo(() => templateLabel(revision), [revision]);
  const contextTags = useMemo(() => contextTagsFromRevision(revision), [revision]);
  const canRenderHtml = hasTrustedHtmlRevision(revision);
  const revisionId = stringValue(revision?.id);

  const gate = useCallback((reason: string) => {
    setError(reason);
    setMessage('');
  }, []);

  const runArtifactCommand = useCallback(async (event: TrustedArtifactEvent) => {
    setError('');
    setMessage('');
    if (event.type === 'filter.change' || event.type === 'drill.request') {
      addArtifactContext(event, event.elementId ?? event.field ?? event.type);
      gate('筛选/钻取需要 W3 artifact interaction command seam；当前只把选中元素加入右侧 Agent 上下文，等待服务端处理。');
      return;
    }
    if (event.type === 'export.request') {
      const resourceId = event.revisionId || revisionId || fileId;
      if (!resourceId) {
        gate('缺少 resourceId，无法请求 artifact.export。');
        return;
      }
      setPending('artifact.export');
      try {
        const response = await getWorkspaceAdapter().command({
          command: 'artifact.export',
          payload: {
            resourceId,
            format: event.format === 'csv' || event.format === 'json' ? event.format : 'html',
          },
        }, createRequestContext());
        if (!response.accepted) throw new Error('服务端未接受 artifact.export。');
        setMessage(`artifact.export accepted: ${response.operationId ?? response.requestId}`);
      } catch (cause) {
        gate(cause instanceof Error ? cause.message : 'artifact.export 失败。');
      } finally {
        setPending('');
      }
      return;
    }
    if (event.type === 'refresh.request') {
      if (!skillId) {
        gate('缺少 SkillViewRevision.intent.skillId；refresh.run 尚未集成。');
        return;
      }
      setPending('refresh.run');
      try {
        const response = await getWorkspaceAdapter().command({
          command: 'refresh.run',
          payload: { skillId, trigger: 'manual' },
        }, createRequestContext());
        if (!response.accepted) throw new Error('服务端未接受 refresh.run。');
        await bootstrapWorkspace(undefined, getWorkspaceAdapter());
        setMessage(`refresh.run accepted: ${response.operationId ?? response.requestId}`);
      } catch (cause) {
        gate(cause instanceof Error ? cause.message : 'refresh.run 失败。');
      } finally {
        setPending('');
      }
    }
  }, [fileId, gate, revisionId, skillId]);

  const handleEvent = useCallback((event: TrustedArtifactEvent) => {
    if (event.type === 'selection.change' || event.type === 'context.reference') {
      addArtifactContext(event, event.elementId ?? title);
      setError('');
      setMessage('已加入右侧 Agent 上下文，等待服务端下一步命令。');
      return;
    }
    void runArtifactCommand(event);
  }, [runArtifactCommand, title]);

  return (
    <div className="flex h-full min-w-0 flex-col overflow-y-auto bg-slate-50/50 p-4 pb-20 md:p-8">
      <div className="mx-auto flex w-full max-w-7xl flex-1 min-w-0 flex-col">
        <ArtifactHeader
          title={title}
          typeLabel={typeLabel}
          isTeam={false}
          version={revisionId ? `ViewRevision ${revisionId}` : '等待 ViewRevision'}
          searchParams={searchParams}
          setSearchParams={setSearchParams}
          productMode
          contextTags={contextTags}
        />

        {(pending || message || error) && (
          <div className="mb-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm" role={error ? 'alert' : 'status'} aria-busy={Boolean(pending)}>
            {pending && <span className="text-slate-600">等待服务端 {pending} 返回…</span>}
            {message && <span className="text-slate-700">{message}</span>}
            {error && <span className="text-amber-800">{error}</span>}
          </div>
        )}

        <section className="mt-4 min-h-[620px] min-w-0 flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          {canRenderHtml ? (
            <TrustedHtmlArtifactRenderer revision={revision as any} onEvent={handleEvent} />
          ) : (
            <GatedHtmlRevisionState revision={revision} fileId={fileId} />
          )}
        </section>

        <section className="mt-4 rounded-2xl border border-slate-200 bg-white shadow-sm">
          <button
            type="button"
            onClick={() => setAuditOpen((value) => !value)}
            aria-expanded={auditOpen}
            className="flex w-full items-center justify-between rounded-2xl px-5 py-4 text-left text-sm font-semibold text-slate-800 outline-none transition hover:bg-slate-50 focus:ring-2 focus:ring-blue-500"
          >
            <span className="inline-flex items-center"><AuditIcon className="mr-2 h-4 w-4 text-slate-500" /> 高级详情 / 审计</span>
            <span className="text-xs font-normal text-slate-500">{auditOpen ? '收起' : '展开'}</span>
          </button>
          {auditOpen && (
            <div className="border-t border-slate-200 p-5">
              <p className="mb-3 text-xs leading-5 text-slate-500">
                Manifest、BuildPlan、traceId、revisionId 只在审计区只读展示；普通用户主路径始终是业务材料、模板、Agent、可信 HTML Skill、评测和发布。
              </p>
              <pre className="max-h-80 overflow-auto rounded-xl bg-slate-950 p-4 text-[11px] leading-5 text-slate-100">
                {JSON.stringify({
                  ViewRevision: revision ?? { status: 'waiting_for_server_revision' },
                  resultRef: resultRefFromRevision(revision) ?? null,
                }, null, 2)}
              </pre>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
