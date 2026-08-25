import React, { useEffect } from 'react';
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
import SkillArtifactView from '../MainArea/SkillArtifactView';
import ConnectionDetailView from '../MainArea/ConnectionDetailView';
import JourneyDetailView from '../MainArea/JourneyDetailView';
import { resourceStore } from '../../lib/store';
import { activeSkillViewRevision } from '../../../production/data';

export default function MainAreaPane({ fileId, errorState, searchParams, setSearchParams, showToast, isWorkspaceEmpty, telemetryEnabled = true }: any) {

  const renderContent = () => {
    if (fileId === 'team_empty') return <EmptyState type="empty_dir" />;
    if (errorState === 'no_permission' || fileId === 'dataset_no_permission') return <EmptyState type="no_permission" />;
    
    if (fileId === 'evaluation_detail') return <EvaluationCenterView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId.startsWith('journey_')) return <JourneyDetailView fileId={fileId} errorState={errorState} telemetryEnabled={telemetryEnabled} searchParams={searchParams} setSearchParams={setSearchParams} />;
    if (fileId === 'kg_sales') return <KnowledgeGraphView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;

    if (fileId === 'data_overview') return <DataOverviewView searchParams={searchParams} setSearchParams={setSearchParams} />;
    if (fileId === 'add_data' || fileId === 'connector_catalog') return <AddDataView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId === 'add_kb') return <AddKnowledgeBaseView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId === 'upload_doc') return <UploadDocView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    if (fileId === 'skill_builder') return <SkillBuilderView searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    
    const resource = resourceStore.getState().find((r:any) => r.id === fileId || r.resourceId === fileId);

    if (resource?.resourceKind === 'skill_draft') {
      return <JourneyDetailView fileId={fileId} errorState={errorState} telemetryEnabled={telemetryEnabled} searchParams={searchParams} setSearchParams={setSearchParams} />;
    }

    const generatedViewModel =
      activeSkillViewRevision?.viewModel &&
      typeof activeSkillViewRevision.viewModel === 'object'
        ? activeSkillViewRevision.viewModel as Record<string, unknown>
        : null;
    const generatedViewOwner = activeSkillViewRevision?.skill_revision_id;
    if (
      resource?.resourceKind === 'skill_draft' &&
      generatedViewOwner === `${fileId}:${resource.revision ?? 1}` &&
      (generatedViewModel?.template === 'dashboard' || generatedViewModel?.template === 'chart')
    ) {
      return <DashboardView fileId={fileId} isTeam={resource.space === 'team'} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (resource?.resourceKind === 'source' || resource?.resourceKind === 'connection' || fileId === 'res_sample_postgres') {
      return <ConnectionDetailView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    if (fileId.startsWith('skill_') || resource?.resourceKind === 'skill') return <SkillArtifactView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;

    if (fileId.startsWith('dataset_') && fileId !== 'dataset_no_permission') return <DatasetView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} />;
    
    const isKb = fileId.startsWith('kb_') || fileId.startsWith('team_kb_') || resource?.artifactType === 'knowledge_base';
    if (isKb) return <KnowledgeBaseView fileId={fileId} isTeam={fileId.startsWith('team_kb_') || resource?.readonly} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;

    const isDoc = fileId.startsWith('doc_') || fileId.includes('document') || resource?.artifactType === 'document' || resource?.type === 'document';
    if (isDoc) return <DocumentView fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    
    const isDash = fileId.includes('dashboard') || fileId === 'res_dash_recruitment' || fileId === 'res_dash_finance' || fileId === 'res_dash_east' || resource?.artifactType === 'dashboard' || resource?.type === 'dashboard';
    if (isDash) {
      const isTeam = fileId.startsWith('team_') || (fileId.includes('team_') && !fileId.startsWith('personal_'));
      return <DashboardView fileId={fileId} isTeam={isTeam} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    
    const isSemantic = fileId.includes('semantic') || resource?.artifactType === 'semantic' || resource?.type === 'semantic_model';
    if (isSemantic) {
      const isTeam = fileId.startsWith('team_') || (fileId.includes('team_') && !fileId.startsWith('personal_'));
      return <SemanticView fileId={fileId} isTeam={isTeam} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }
    
    const isChart = fileId.includes('chart') || resource?.artifactType === 'chart' || resource?.type === 'chart';
    if (isChart) {
      const isTeam = fileId.startsWith('team_') || (fileId.includes('team_') && !fileId.startsWith('personal_'));
      return <ChartView fileId={fileId} isTeam={isTeam} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} />;
    }

    // Invalid resource -> fallback to home_chat
    return <InvalidRouteHandler searchParams={searchParams} setSearchParams={setSearchParams} />;
  };

  return (
    <div className="h-full min-h-0 min-w-0 overflow-y-auto bg-slate-50/50 flex flex-col relative">
      {renderContent()}
    </div>
  );
}

function InvalidRouteHandler({ searchParams, setSearchParams }: any) {
  useEffect(() => {
    const p = new URLSearchParams(searchParams);
    p.set('file', 'welcome');
    setSearchParams(p, { replace: true });
  }, [searchParams, setSearchParams]);
  return null;
}
