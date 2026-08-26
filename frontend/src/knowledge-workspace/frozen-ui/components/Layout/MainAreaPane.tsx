import React, { type SVGProps } from 'react';
import WelcomeView from '../MainArea/WelcomeView';
import DatasetView from '../MainArea/DatasetView';
import DashboardView from '../MainArea/DashboardView';
import DataOverviewView from '../MainArea/DataOverviewView';
import SemanticView from '../MainArea/SemanticView';
import ChartView from '../MainArea/ChartView';
import EmptyState from '../MainArea/EmptyState';
import AddDataView from '../MainArea/AddDataView';
import EvaluationCenterView from '../MainArea/EvaluationCenterView';
import KnowledgeGraphView from '../MainArea/KnowledgeGraphView';
import UploadDocView from '../MainArea/UploadDocView';
import DocumentView from '../MainArea/DocumentView';
import AddKnowledgeBaseView from '../MainArea/AddKnowledgeBaseView';
import KnowledgeBaseView from '../MainArea/KnowledgeBaseView';
import SkillBuilderView from '../MainArea/SkillBuilderView';
import SkillHtmlRevisionView from '../MainArea/SkillHtmlRevisionView';
import SkillArtifactView from '../MainArea/SkillArtifactView';
import SkillMonitoringView from '../MainArea/SkillMonitoringView';
import SkillSOPView from '../MainArea/SkillSOPView';
import ConnectionDetailView from '../MainArea/ConnectionDetailView';
import JourneyDetailView from '../MainArea/JourneyDetailView';
import { resourceStore } from '../../lib/store';
import { activeSkillViewRevision, setActiveSkillViewRevision } from '../../../production/data';
import { isWorkspaceRouteAvailable as isProductionRouteAvailable } from '../../../production/store';

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

function normalizedSubtype(resource: any): string {
  return String(resource?.subtype ?? resource?.artifactType ?? resource?.type ?? '').toLowerCase();
}

const HTML_PRIMARY_TEMPLATES = new Set([
  'dashboard',
  'chart',
  'semantic',
  'sop',
  'knowledge',
  'graph_ontology',
  'monitoring',
  'html',
]);

function revisionHasTrustedHtml(revision: Record<string, unknown> | null): boolean {
  const resultRef = revision?.resultRef ?? revision?.result_ref;
  return Boolean(
    resultRef &&
    typeof resultRef === 'object' &&
    !Array.isArray(resultRef),
  );
}

function activeRevisionMatchesRoute(revision: Record<string, unknown> | null, fileId: string, searchParams: URLSearchParams, resource: any): boolean {
  if (!revision) return false;
  const urlRevisionId = searchParams.get('view_revision_id') || searchParams.get('revision_id');
  if (urlRevisionId && revision.id === urlRevisionId) return true;
  // Published resources use an opaque published:// id in the route while
  // their trusted ViewRevision remains keyed by the server-projected
  // resource.viewRevisionId.  Keep this binding server-derived; do not infer
  // a published revision from display names or URL business labels.
  if (resource?.viewRevisionId && resource.viewRevisionId === revision.id) return true;
  const intent = revision.intent && typeof revision.intent === 'object'
    ? revision.intent as Record<string, unknown>
    : {};
  if (intent.skillId === fileId) return true;
  if (resource && intent.skillId === resource.id) return true;
  const skillRevisionId = String(revision.skill_revision_id ?? revision.skillRevisionId ?? '');
  return Boolean(skillRevisionId && (skillRevisionId === fileId || skillRevisionId.startsWith(`${fileId}:`) || (resource?.id && skillRevisionId.startsWith(`${resource.id}:`))));
}

function ProductionRouteUnavailable({ fileId }: { fileId: string }) {
  return (
    <section className="flex h-full min-h-[360px] items-center justify-center bg-slate-50 p-4 md:p-8" role="alert">
      <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm md:p-8">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 text-amber-700">
          <AlertIcon className="h-5 w-5" />
        </div>
        <h2 className="mt-5 text-lg font-semibold text-slate-900">等待服务端返回数据</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          当前深链已保留，但资源目录、ViewRevision 或 route capability 尚未由服务端 bootstrap 返回。页面不会用固定示例数据填充成功状态。
        </p>
        <code className="mt-4 block break-all rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-500">{fileId}</code>
      </div>
    </section>
  );
}

export default function MainAreaPane({ fileId, errorState, searchParams, setSearchParams, showToast, isWorkspaceEmpty, telemetryEnabled = true }: any) {

  const renderContent = () => {
    if (fileId === 'team_empty') return <EmptyState type="empty_dir" />;
    if (errorState === 'no_permission' || fileId === 'dataset_no_permission') return <EmptyState type="no_permission" />;
    const resource = resourceStore.getState().find((r:any) => r.id === fileId || r.resourceId === fileId);
    const resourceRevision =
      resource?.skillViewRevision &&
      typeof resource.skillViewRevision === 'object' &&
      !Array.isArray(resource.skillViewRevision)
        ? resource.skillViewRevision as Record<string, unknown>
        : null;
    if (resourceRevision && typeof resourceRevision === 'object') {
      setActiveSkillViewRevision(resourceRevision as Record<string, unknown>);
    } else if (fileId === 'welcome') {
      setActiveSkillViewRevision(null);
    }
    const subtype = normalizedSubtype(resource);
    const isTeamResource = resource?.space === 'team' || resource?.readonly === true;
    // Use the revision projected on the selected resource for this render.
    // Reading the module-level compatibility cache before setting it caused
    // the first render of every dynamic Skill route to fall back to the
    // JourneyDetail shell, even though bootstrap had returned a trusted HTML
    // ViewRevision. The cache remains updated for the renderer and refresh
    // recovery, but routing must be based on the current resource.
    const activeRevision = resourceRevision ??
      (activeSkillViewRevision && typeof activeSkillViewRevision === 'object'
        ? activeSkillViewRevision as Record<string, unknown>
        : null);

    const generatedViewModel =
      activeRevisionMatchesRoute(activeRevision, fileId, searchParams, resource) &&
      activeRevision?.viewModel &&
      typeof activeRevision.viewModel === 'object'
        ? activeRevision.viewModel as Record<string, unknown>
        : null;
    const generatedTemplate = String(generatedViewModel?.template ?? generatedViewModel?.viewTemplate ?? '');
    if (HTML_PRIMARY_TEMPLATES.has(generatedTemplate) && revisionHasTrustedHtml(activeRevision)) {
      return <SkillHtmlRevisionView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    if (generatedTemplate === 'dashboard' || generatedTemplate === 'chart') {
      return <DashboardView fileId={fileId} isTeam={false} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    if (generatedTemplate === 'semantic') {
      return <SemanticView fileId={fileId} isTeam={false} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    if (generatedTemplate === 'graph_ontology') {
      return <KnowledgeGraphView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    if (generatedTemplate === 'sop') {
      return <SkillSOPView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    if (generatedTemplate === 'monitoring') {
      return <SkillMonitoringView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (fileId !== 'welcome' && !isProductionRouteAvailable(fileId)) {
      return <ProductionRouteUnavailable fileId={fileId} />;
    }
    
    if (fileId === 'evaluation_detail') return <EvaluationCenterView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;

    if (fileId === 'data_overview') return <DataOverviewView searchParams={searchParams} setSearchParams={setSearchParams} />;
    if (fileId === 'add_data' || fileId === 'connector_catalog') return <AddDataView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId === 'add_kb') return <AddKnowledgeBaseView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId === 'upload_doc') return <UploadDocView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId === 'skill_builder') return <SkillBuilderView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId.startsWith('journey_')) return <JourneyDetailView fileId={fileId} errorState={errorState} telemetryEnabled={telemetryEnabled} searchParams={searchParams} setSearchParams={setSearchParams} />;

    if (resource?.resourceKind === 'skill_draft') {
      return <JourneyDetailView fileId={fileId} errorState={errorState} telemetryEnabled={telemetryEnabled} searchParams={searchParams} setSearchParams={setSearchParams} />;
    }

    if (resource?.resourceKind === 'published_skill') {
      return <SkillMonitoringView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (resource?.resourceKind === 'source' || resource?.resourceKind === 'connection') {
      return <ConnectionDetailView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (resource?.resourceKind === 'skill' && HTML_PRIMARY_TEMPLATES.has(subtype) && activeRevisionMatchesRoute(activeRevision, fileId, searchParams, resource) && revisionHasTrustedHtml(activeRevision)) {
      return <SkillHtmlRevisionView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (resource?.resourceKind === 'skill' && resource?.subtype === 'sop') {
      return <SkillSOPView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (resource?.resourceKind === 'skill' && resource?.subtype === 'monitoring') {
      return <SkillMonitoringView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (resource?.resourceKind === 'skill') return <SkillArtifactView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;

    if (resource?.resourceKind === 'dataset') return <DatasetView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} />;
    
    const isKb = resource?.resourceKind === 'knowledge_base' || subtype === 'knowledge_base';
    if (isKb) return <KnowledgeBaseView fileId={fileId} isTeam={isTeamResource} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;

    const isDoc = resource?.resourceKind === 'document' || subtype === 'document';
    if (isDoc) return <DocumentView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    
    const isDash = subtype === 'dashboard';
    if (isDash) {
      return <DashboardView fileId={fileId} isTeam={isTeamResource} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    
    const isSemantic = subtype === 'semantic' || resource?.type === 'semantic_model';
    if (isSemantic) {
      return <SemanticView fileId={fileId} isTeam={isTeamResource} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    
    const isChart = subtype === 'chart';
    if (isChart) {
      return <ChartView fileId={fileId} isTeam={isTeamResource} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    return <ProductionRouteUnavailable fileId={fileId} />;
  };

  return (
    <div className="h-full min-h-0 min-w-0 overflow-y-auto bg-slate-50/50 flex flex-col relative">
      {renderContent()}
    </div>
  );
}
