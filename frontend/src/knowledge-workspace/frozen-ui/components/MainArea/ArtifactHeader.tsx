import React, { useState, useEffect } from 'react';
import { ArrowLeft, MoreHorizontal, FileText, CheckCircle2, MessageSquare, PlusSquare, Share, Download, BadgeCheck, FilePlus2, ToyBrick, Filter, Info, Share2, RefreshCw, MousePointer2 } from 'lucide-react';
import { cn } from '../../lib/utils';
import { bootstrapWorkspace, getWorkspaceAdapter, resourceStore } from '../../lib/store';
import { activeSkillViewRevision } from '../../../production/data';
import { createRequestContext } from '../../../production/ports';

export default function ArtifactHeader({
  title, typeLabel, isTeam, version, fromTeamVersion, editTarget, onElementClick, setSearchParams, searchParams, showToast,
  productMode = false, contextTags = [],
}: any) {
  const [moreOpen, setMoreOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setMoreOpen(false); };
    const handleClickOutside = (e: MouseEvent) => { if (moreOpen && !(e.target as Element).closest('.more-menu-container')) setMoreOpen(false); };
    if (moreOpen) { window.addEventListener('keydown', handleEsc); window.addEventListener('click', handleClickOutside); }
    return () => { window.removeEventListener('keydown', handleEsc); window.removeEventListener('click', handleClickOutside); };
  }, [moreOpen]);

  const handleReturn = () => {
    const p = new URLSearchParams(searchParams);
    p.set('file', 'welcome');
    p.delete('custom_name'); p.delete('from_team_version'); p.delete('team_origin'); p.delete('version');
    setSearchParams(p);
  };

  const isDoc = typeLabel === 'Document';
  const isDash = typeLabel === 'Dashboard';
  const isKB = typeLabel === 'Knowledge Base';
  const currentResource = resourceStore.getState().find((r:any) => r.id === searchParams.get('file') || r.resourceId === searchParams.get('file'));
  const revisionRecord = activeSkillViewRevision && typeof activeSkillViewRevision === 'object' ? activeSkillViewRevision as Record<string, unknown> : null;
  const intent = revisionRecord?.intent && typeof revisionRecord.intent === 'object' ? revisionRecord.intent as Record<string, unknown> : {};
  const skillRevisionId = String(revisionRecord?.skillRevisionId ?? revisionRecord?.skill_revision_id ?? '');
  const currentSkillId = typeof intent.skillId === 'string' && intent.skillId
    ? intent.skillId
    : skillRevisionId.includes(':')
    ? skillRevisionId.slice(0, skillRevisionId.lastIndexOf(':'))
    : currentResource?.resourceKind === 'skill'
    ? String(currentResource.id ?? currentResource.resourceId ?? '')
    : '';
  const canRefresh = Boolean(currentSkillId);

  const refreshData = async () => {
    setActionError('');
    if (!canRefresh) {
      setActionError('刷新需要 SkillViewRevision.intent.skillId 或服务端 skill resource；当前尚未集成。');
      return;
    }
    setBusy('refresh.run');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'refresh.run',
        payload: { skillId: currentSkillId, trigger: 'manual' },
      }, createRequestContext());
      if (!response.accepted) throw new Error('服务端未接受 refresh.run。');
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      showToast?.(`refresh.run accepted: ${response.operationId ?? response.requestId}`);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : 'refresh.run 失败。');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="flex flex-col mb-4 w-full select-none">
      {/* Breadcrumb - weak info */}
      <div className="flex items-center text-[11px] text-slate-400 mb-1">
        <span className="hover:text-slate-600 cursor-pointer transition-colors" onClick={handleReturn}>工作区</span>
        <span className="mx-1.5">/</span>
        <span>{isTeam ? '团队资源' : '个人资源'}</span>
        <span className="mx-1.5">/</span>
        <span>{typeLabel}</span>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex flex-col min-w-0 pr-4">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-slate-900 tracking-tight truncate">{title}</h1>
            <span className="text-[12px] font-mono text-slate-500 shrink-0 ml-1">{productMode ? 'V1.0 草稿' : version}</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium text-slate-400 shrink-0 bg-slate-50 ml-1">{isTeam ? '团队快照' : productMode ? '工作草稿' : '个人草稿'}</span>
            {productMode && contextTags.length > 0 && (
              <span className="px-2 py-1 rounded border border-slate-200 bg-slate-100 text-[11px] font-medium text-slate-600 shrink-0">
                使用了 {contextTags.length} 项上下文
              </span>
            )}
          </div>
        </div>
        
        <div className="flex items-center gap-2 shrink-0">
          {!productMode && <button className="px-3 py-1.5 bg-white border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors flex items-center outline-none shadow-sm" onClick={() => {
            const item = { 
              id: searchParams.get('file'), 
              name: title, 
              type: isTeam ? 'team_artifact' : 'personal_artifact', 
              artifactType: currentResource?.subtype || currentResource?.artifactType || typeLabel, 
              version: isTeam ? searchParams.get('version') || version : version, 
              readonly: isTeam,
              resourceKind: currentResource?.resourceKind,
              subtype: currentResource?.subtype,
              lineage: currentResource?.lineage
            };
            window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
          }}>
            <PlusSquare size={14} className="mr-1.5 text-slate-500"/>加入对话
          </button>}
          
          {!isTeam ? (
            <button className="px-3 py-1.5 bg-white border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors flex items-center outline-none shadow-sm" onClick={() => { const p = new URLSearchParams(searchParams); p.set('modal', productMode ? 'publish_agent' : 'publish'); setSearchParams(p); }}>
              {productMode ? '发布给 Agent' : '发布到团队'}
            </button>
          ) : (
            <button className="px-3 py-1.5 bg-white border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors flex items-center outline-none shadow-sm" onClick={() => {
              const p = new URLSearchParams(searchParams); p.set('action', 'reuse_modal'); p.set('reuse_title', title); setSearchParams(p);
            }}>
              <FilePlus2 size={14} className="mr-1.5 text-slate-500" /> 复用为草稿
            </button>
          )}

          <div className="relative more-menu-container">
            <button aria-label="更多操作" className="p-1.5 text-slate-500 hover:bg-slate-100 rounded-lg transition-colors border border-transparent hover:border-slate-200 outline-none" onClick={() => setMoreOpen(!moreOpen)}>
              <MoreHorizontal size={16}/>
            </button>
            {moreOpen && (
              <div className="absolute right-0 top-full mt-1 w-44 bg-white border border-slate-200 shadow-md rounded-xl py-1.5 z-50">
                {!isDoc && (
                  <>
                    <button className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center outline-none" onClick={() => { setMoreOpen(false); const p = new URLSearchParams(searchParams); if (p.get('select_mode') === 'true') p.delete('select_mode'); else p.set('select_mode', 'true'); setSearchParams(p); }}>
                      <MousePointer2 size={14} className="mr-2 text-slate-400" /> 选择元素
                    </button>
                    <button disabled={!canRefresh || busy === 'refresh.run'} title={canRefresh ? '请求服务端 refresh.run' : '缺少服务端 skillId，无法刷新'} className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center outline-none disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:bg-white" onClick={() => { setMoreOpen(false); void refreshData(); }}>
                      <RefreshCw size={14} className="mr-2 text-slate-400" /> 刷新数据
                    </button>
                    <div className="h-px bg-slate-100 my-1"></div>
                  </>
                )}
                <button className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center outline-none" onClick={() => { setMoreOpen(false); const p = new URLSearchParams(searchParams); p.set('modal', 'versions'); setSearchParams(p); }}>
                  <Info size={14} className="mr-2 text-slate-400" /> 版本历史
                </button>
                {!isDoc && (
                <button className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center outline-none" onClick={() => { setMoreOpen(false); const p = new URLSearchParams(searchParams); p.set('file', 'evaluation_detail'); p.set('eval_target', searchParams.get('file') || 'current_resource'); setSearchParams(p); }}>
                    <BadgeCheck size={14} className="mr-2 text-slate-400" /> 评测中心
                  </button>
                )}
                <button className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center outline-none" onClick={() => { setMoreOpen(false); const p = new URLSearchParams(searchParams); p.set('modal', 'export'); setSearchParams(p); }}>
                  <Download size={14} className="mr-2 text-slate-400" /> 导出
                </button>
                <button className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center outline-none" onClick={() => { setMoreOpen(false); const p = new URLSearchParams(searchParams); p.set('modal', 'share'); setSearchParams(p); }}>
                  <Share size={14} className="mr-2 text-slate-400" /> 分享
                </button>
                {(isDash || isKB) && (
                  <>
                    <div className="h-px bg-slate-100 my-1"></div>
                    <button className="w-full text-left px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 flex items-center outline-none font-medium" onClick={() => { setMoreOpen(false); const p = new URLSearchParams(searchParams); p.set('modal', 'publish_agent'); setSearchParams(p); }}>
                      <ToyBrick size={14} className="mr-2 text-blue-500" /> 发布到 Agent
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      {actionError && (
        <div role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {actionError}
        </div>
      )}
    </div>
  );
}
