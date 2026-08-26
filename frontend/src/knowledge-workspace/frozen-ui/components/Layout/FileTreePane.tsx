import React, { useState, useEffect, useRef } from 'react';
import { ChevronRight, ChevronDown, Folder, FilePieChart, Database, FileText, LayoutDashboard, Users, FileSpreadsheet, X, MoreHorizontal, AlertTriangle, Send, Link, Globe, Plus, Library } from 'lucide-react';
import { cn } from '../../lib/utils';
import { dragStore } from '../../lib/dragStore';
import { connectionStore, useStore, resourceStore } from '../../lib/store';
import { trackShellEvent } from './shellTelemetry';

function UserIcon() {
  return (
    <div className="w-3.5 h-3.5 rounded-full border border-current flex items-center justify-center overflow-hidden">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-2.5 h-2.5">
        <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle>
      </svg>
    </div>
  );
}

export default function FileTreePane({ fileId, searchParams, setSearchParams, onClose, isMobile, publishedItems, reusedItems, onPublish, onReuse, onAddChip, showToast, isWorkspaceEmpty, addedSources = [] }: any) {
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({
    'personal': true, 'team': true, 'p_data_knowledge': true, 't_data_knowledge': true, 'conn_mysql': true, 'schema_public': true
  });
  
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [pendingPublish, setPendingPublish] = useState<{item: any, target: string, name: string} | null>(null);
  const hoverTimer = useRef<any>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [dragTarget, setDragTarget] = useState<string | null>(null);

  useEffect(() => {
    const unsubscribe = dragStore.subscribe(() => { setDragTarget(dragStore.getState().targetId); });
    return () => {
      unsubscribe();
    };
  }, []);
  
  useEffect(() => {
    const handleDocClick = () => setMenuOpenId(null);
    document.addEventListener('click', handleDocClick);
    return () => document.removeEventListener('click', handleDocClick);
  }, []);

  const storeConnections = useStore(connectionStore);

  // Convert connectionStore state to tree hierarchy
  const mappedConnections = storeConnections.filter((c:any) => !c.isTeam).map((conn: any) => ({
    id: conn.id, name: conn.displayName, type: 'connection', icon: conn.connectorKey === 'excel' ? FileSpreadsheet : Database,
    children: conn.discoveredResources?.map((schema: any) => ({
      id: `${conn.id}_${schema.name}`, name: schema.name, type: 'schema', icon: Folder,
      children: (schema.tables || []).map((table: any) => ({
        id: table.id, name: table.name, type: 'table', hasPermission: table.perm, icon: conn.type === 'Local' ? FileSpreadsheet : Database,
        children: table.fields?.map((field: any) => ({
          id: field.id, name: field.name, type: 'field', icon: Database
        }))
      }))
    }))
  }));

  let datasetsChildren = mappedConnections;
  if (isWorkspaceEmpty) {
    datasetsChildren = [];
  }

  const allResources = useStore(resourceStore);
  const defaultPersonal: any[] = [];
  const defaultTeam: any[] = [];
  
  const newPersonalArtifacts = allResources
    .filter((r:any) => r.space === 'personal' && r.subtype !== 'template')
    .map((r:any) => ({ 
      id: r.id, name: r.displayName || r.name, 
      type: r.resourceKind, 
      artifactType: r.subtype, 
      draft: r.lifecycle === 'draft', 
      icon: (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') ? FileText : LayoutDashboard, 
      isDocs: (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') 
    }));

  const newTeamArtifacts = allResources
    .filter((r:any) => r.space === 'team' && r.subtype !== 'template')
    .map((r:any) => ({ 
      id: r.id, name: r.displayName || r.name, 
      type: r.resourceKind, 
      artifactType: r.subtype, 
      readonly: true, 
      icon: (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') ? FileText : LayoutDashboard, 
      isDocs: (r.resourceKind === 'document' || r.resourceKind === 'knowledge_base') 
    }));

  const personalChildren = isWorkspaceEmpty ? [] : [...defaultPersonal, ...reusedItems, ...newPersonalArtifacts].reduce((acc: any[], curr) => {
    if (!acc.find(x => x.id === curr.id)) acc.push(curr);
    return acc;
  }, []);
  
  const teamConnections = storeConnections.filter((c:any) => c.isTeam).map((conn: any) => ({
    id: conn.id, name: conn.displayName, type: 'connection', icon: conn.connectorKey === 'excel' ? FileSpreadsheet : Database,
    children: conn.discoveredResources?.map((schema: any) => ({
      id: `${conn.id}_${schema.name}`, name: schema.name, type: 'schema', icon: Folder,
      children: (schema.tables || []).map((table: any) => ({
        id: table.id, name: table.name, type: 'table', hasPermission: true, icon: conn.type === 'Local' ? FileSpreadsheet : Database,
        children: table.fields?.map((field: any) => ({
          id: field.id, name: field.name, type: 'field', icon: Database
        }))
      }))
    }))
  }));

  const teamChildren = isWorkspaceEmpty ? [] : [...defaultTeam, ...teamConnections, ...publishedItems, ...newTeamArtifacts].reduce((acc: any[], curr) => {
    if (!acc.find(x => x.id === curr.id)) acc.push(curr);
    return acc;
  }, []);

  const personalSources = personalChildren.filter((c:any) => c.type === 'source' || c.type === 'dataset').map((s:any) => ({ ...s, icon: s.type === 'dataset' ? FileSpreadsheet : Database }));
  datasetsChildren = [...datasetsChildren, ...personalSources];

  const isDraftSkill = (item: any) =>
    item.type === 'skill' || item.resourceKind === 'skill_draft' || item.lifecycle === 'draft';
  const isPublishedSkill = (item: any) =>
    item.type === 'published_skill' || item.type === 'skill_version' ||
    item.resourceKind === 'published_skill' || item.resourceKind === 'publication' ||
    item.published === true ||
    (item.type === 'skill' && !item.draft);
  const toTreeItem = (item: any) => ({
    ...item,
    type: item.type === 'skill' ? 'skill' : item.type,
    icon: item.icon || (isDraftSkill(item) ? FileText : Library),
  });
  const personalDataKnowledge = personalChildren.filter((item: any) => !isDraftSkill(item) && !isPublishedSkill(item)).map(toTreeItem);
  const personalDrafts = personalChildren.filter(isDraftSkill).map(toTreeItem);
  const personalPublished = personalChildren.filter(isPublishedSkill).map(toTreeItem);
  const teamDataKnowledge = teamChildren.filter((item: any) => item.type === 'connection' || item.type === 'schema' || item.type === 'table' || (!isDraftSkill(item) && !isPublishedSkill(item))).map(toTreeItem);
  const teamDrafts = teamChildren.filter(isDraftSkill).map(toTreeItem);
  const teamPublished = teamChildren.filter(isPublishedSkill).map(toTreeItem);

  const treeData = [
    {
      id: 'personal', name: '个人工作区', type: 'root', icon: UserIcon,
      children: [
        { id: 'p_data_knowledge', name: `数据与知识 ${personalDataKnowledge.length + datasetsChildren.length}`, type: 'folder', children: [...datasetsChildren, ...personalDataKnowledge] },
        { id: 'p_skill_drafts', name: `工作草稿 ${personalDrafts.length}`, type: 'folder', children: personalDrafts },
        { id: 'p_published_skills', name: `已发布能力 ${personalPublished.length}`, type: 'folder', children: personalPublished },
      ]
    },
    {
      id: 'team', name: '团队工作区', type: 'root', icon: Users,
      children: [
        { id: 't_data_knowledge', name: `数据与知识 ${teamDataKnowledge.length}`, type: 'folder', children: teamDataKnowledge },
        { id: 't_skill_drafts', name: `工作草稿 ${teamDrafts.length}`, type: 'folder', children: teamDrafts },
        { id: 't_published_skills', name: `已发布能力 ${teamPublished.length}`, type: 'folder', allowDrop: 'personal_artifact', children: teamPublished },
      ]
    }
  ];

  const toggleFolder = (id: string, e: React.MouseEvent) => { e.stopPropagation(); setExpandedFolders(p => ({ ...p, [id]: !p[id] })); };

  const handleDragStart = (e: React.DragEvent, item: any) => {
    e.stopPropagation();
    const img = new Image(); img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'; e.dataTransfer.setDragImage(img, 0, 0);
    e.dataTransfer.effectAllowed = 'copyMove'; e.dataTransfer.setData('application/json', JSON.stringify(item));
    dragStore.setState({ status: 'drag-start', item, position: { x: e.clientX, y: e.clientY } });
    setTimeout(() => dragStore.setState({ status: 'dragging' }), 10);
  };

  const handleDragOverFolder = (e: React.DragEvent, folderId: string, allowedType: string, folderName: string) => {
    e.preventDefault(); e.stopPropagation();
    const state = dragStore.getState();
    if (state.status !== 'dragging' && state.status !== 'valid-over' && state.status !== 'invalid-over') return;
    if (!expandedFolders[folderId] && !hoverTimer.current) hoverTimer.current = setTimeout(() => setExpandedFolders(p => ({...p, [folderId]: true})), 600);
    if (state.item?.type === allowedType) dragStore.setState({ status: 'valid-over', message: `放置以发布到 ${folderName}`, targetId: folderId });
    else dragStore.setState({ status: 'invalid-over', message: '类型不匹配，无法放置', targetId: folderId });
  };

  const handleDragLeaveFolder = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    if (hoverTimer.current) { clearTimeout(hoverTimer.current); hoverTimer.current = null; }
    if (dragStore.getState().targetId !== null) dragStore.setState({ status: 'dragging', targetId: null, message: '' });
  };

  const handleDropFolder = (e: React.DragEvent, folderId: string, allowedType: string, folderName: string) => {
    e.preventDefault(); e.stopPropagation();
    if (hoverTimer.current) { clearTimeout(hoverTimer.current); hoverTimer.current = null; }
    const state = dragStore.getState();
    if (state.status === 'valid-over' && state.item && state.targetId === folderId) {
      if (allowedType === 'personal_artifact') { dragStore.setState({ status: 'drop-pending' }); setPendingPublish({ item: state.item, target: folderId, name: folderName }); }
      else if (allowedType === 'team_artifact') { dragStore.setState({ status: 'idle', targetId: null, item: null, message: '' }); onReuse(state.item, folderId); }
    } else dragStore.setState({ status: 'cancelled', targetId: null });
  };

  const performPublish = () => {
    if (pendingPublish) {
      onPublish(pendingPublish.item, pendingPublish.target);
      setPendingPublish(null);
      dragStore.setState({ status: 'idle', targetId: null, item: null, message: '' });
    }
  };

  const renderTree = (nodes: any[], depth = 0) => {
    return nodes.map(node => {
      const hasChildren = !!node.children;
      const isRoot = node.type === 'root';
      const isExpanded = expandedFolders[node.id];
      const isSelected = fileId === node.id || (node.id === 'p_datasets' && (fileId === 'data_overview' || fileId === 'add_data'));
      const Icon = node.icon || Folder;

      // Allow dragging tables/connections/artifacts
      const isDraggable = ['table', 'connection', 'personal_artifact', 'team_artifact'].includes(node.type);
      const canHaveContextMenu = node.type !== 'root' && node.type !== 'folder' && node.type !== 'schema' && node.type !== 'field';
      const isDropTarget = dragTarget === node.id;
      const isFolderOrRoot = node.type === 'folder' || node.type === 'root' || node.type === 'schema' || node.type === 'connection';
      const isSpaceRoot = node.id === 'personal' || node.id === 'team';

      return (
        <div key={node.id} role="none" className="select-none flex flex-col relative">
          {depth > 1 && <div className="absolute left-[13px] top-0 bottom-0 w-px bg-slate-200" style={{ left: `${(depth - 1) * 16 + 13}px` }}></div>}
          
          <div className="relative" role="none">
            <div
              role="treeitem"
              aria-expanded={hasChildren ? !!isExpanded : undefined}
              aria-selected={isSelected}
              draggable={isDraggable}
              onDragStart={isDraggable ? (e) => handleDragStart(e, node) : undefined}
              onDragOver={hasChildren && node.allowDrop ? (e) => handleDragOverFolder(e, node.id, node.allowDrop, node.name) : undefined}
              onDragLeave={hasChildren && node.allowDrop ? handleDragLeaveFolder : undefined}
              onDrop={hasChildren && node.allowDrop ? (e) => handleDropFolder(e, node.id, node.allowDrop, node.name) : undefined}
              className={cn(
                "w-full text-left flex items-center py-1 px-2 cursor-pointer text-[13px] rounded-md mx-2 transition-all group outline-none focus-visible:ring-2 focus-visible:ring-blue-400 relative",
                isSelected ? "bg-blue-50/40 text-blue-700 font-medium" : "text-slate-600 hover:bg-slate-50",
                isRoot ? "font-bold text-slate-800 mt-2 mb-0.5 text-xs tracking-wide" : "",
                isDropTarget && dragStore.getState().status === 'valid-over' && "ring-2 ring-blue-500 bg-blue-50",
                isDropTarget && dragStore.getState().status === 'invalid-over' && "ring-2 ring-red-400 bg-red-50",
                dragStore.getState().status === 'dragging' && dragStore.getState().item?.id === node.id && "opacity-55"
              )}
              style={{ paddingLeft: `${depth * 12 + 8}px`, width: 'calc(100% - 16px)' }}
              onClick={(e) => {
                if (hasChildren) {
                  if (isFolderOrRoot || (e.target as HTMLElement).closest('.expander-icon')) {
                    setExpandedFolders(prev => ({ ...prev, [node.id]: !prev[node.id] }));
                    if (node.id === 'p_datasets') {
                      const p = new URLSearchParams(searchParams); p.delete('explore'); p.set('file', 'data_overview'); setSearchParams(p);
                      if (isMobile) onClose?.();
                    }
                        if (isFolderOrRoot) return;
                  }
                }
                if (!isFolderOrRoot && node.type !== 'field') {
                  const p = new URLSearchParams(searchParams);
                  p.delete('explore'); 
                  p.set('file', node.id);
                  if (node.type === 'personal_artifact' || node.type === 'team_artifact') {
                    p.delete('pane'); // allow default open for all artifacts
                  }
                  if (node.name) p.set('custom_name', node.name);
                  if (node.version) p.set('version', node.version);
                  setSearchParams(p);
                  if (isMobile) onClose?.();
                }
              }}
              onContextMenu={(e) => {
                if (canHaveContextMenu || isSpaceRoot) {
                  e.preventDefault();
                  e.stopPropagation();
                  setMenuOpenId(node.id);
                }
              }}
              onKeyDown={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); if (canHaveContextMenu) setMenuOpenId(node.id); } }}
              tabIndex={0}
              data-tree-id={node.id}
            >
              <div className={cn("expander-icon w-4 h-4 mr-1 flex items-center justify-center shrink-0 rounded hover:bg-slate-200 transition-colors", hasChildren ? "text-slate-500" : "opacity-0")} onClick={hasChildren ? (e) => toggleFolder(node.id, e) : undefined}>
                {hasChildren ? (isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : null}
              </div>
              <Icon size={14} className={cn("mr-2 shrink-0", isSelected ? "text-blue-600" : (isFolderOrRoot ? "text-slate-400" : "text-slate-500"))} />
              <span className="truncate flex-1">{node.name}</span>
              
              {node.draft && <span className="text-[10px] px-1 bg-white text-slate-400 rounded border border-slate-200 ml-2 shrink-0 hidden md:block">草稿</span>}
              {node.version && <span className="text-[10px] px-1 bg-white text-slate-400 rounded border border-slate-200 ml-2 shrink-0 hidden md:block">{node.version}</span>}
              {node.type === 'field' && <span className="text-[10px] text-slate-400 ml-2">字段</span>}

              {canHaveContextMenu && !isSpaceRoot && (
                <div className="flex items-center ml-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-all shrink-0">
                  <button onClick={(e) => { e.stopPropagation(); setMenuOpenId(node.id); }} className="w-5 h-5 rounded flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors outline-none focus-visible:ring-2"><MoreHorizontal size={14} /></button>
                </div>
              )}

              {isSpaceRoot && (
                <div className="flex items-center ml-auto opacity-100 shrink-0">
                  <button 
                    aria-label="新建资源"
                    title="新建资源"
                    onClick={(e) => { 
                      e.stopPropagation(); 
                      const p = new URLSearchParams(searchParams);
                      p.set('modal', 'create_resource');
                      p.set('target_space', node.id);
                      setSearchParams(p);
                      if (isMobile) onClose?.();
                    }} 
                    className="w-8 h-8 rounded flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors outline-none focus-visible:ring-2"
                  >
                    <Plus size={15} />
                  </button>
                  <button 
                    onClick={(e) => { e.stopPropagation(); setMenuOpenId(node.id); }}
                    className="w-8 h-8 ml-0.5 rounded flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors outline-none focus-visible:ring-2"
                  >
                    <MoreHorizontal size={15} />
                  </button>
                </div>
              )}

              {node.isDocs && (
                <div className={cn("flex items-center ml-1 md:opacity-0 md:group-hover:opacity-100 focus-within:opacity-100 transition-all shrink-0", (isMobile || isSelected) && "opacity-100")}>
                  <button 
                    aria-label="上传知识文档"
                    title="上传知识文档"
                    onClick={(e) => { 
                      e.stopPropagation(); 
                      const p = new URLSearchParams(searchParams);
                      p.set('file', 'upload_doc');
                      p.set('target_space', node.space);
                      setSearchParams(p);
                      if (isMobile) onClose?.();
                    }} 
                    className="w-5 h-5 rounded flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors outline-none focus-visible:ring-2"
                  >
                    <Plus size={14} />
                  </button>
                </div>
              )}
            </div>

            {menuOpenId === node.id && isSpaceRoot && (
              <div ref={menuRef} role="menu" className="absolute right-4 top-full mt-1 w-32 bg-white border border-slate-200 rounded-lg shadow-lg z-50 py-1.5 animate-in fade-in duration-150" onKeyDown={(e) => {
                if (e.key === 'Escape') { e.stopPropagation(); setMenuOpenId(null); }
              }}>
                <button role="menuitem" onClick={(e) => { e.stopPropagation(); setMenuOpenId(null); }} className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 outline-none flex items-center">新建文件夹</button>
              </div>
            )}

            {menuOpenId === node.id && canHaveContextMenu && !isSpaceRoot && (
              <div ref={menuRef} role="menu" className="absolute right-4 top-full mt-1 w-40 bg-white border border-slate-200 rounded-lg shadow-lg z-50 py-1.5 animate-in fade-in duration-150" onKeyDown={(e) => {
                if (e.key === 'Escape') { e.stopPropagation(); setMenuOpenId(null); }
              }}>
                <button role="menuitem" onClick={(e) => { e.stopPropagation(); setMenuOpenId(null); onAddChip(node); }} className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 outline-none flex items-center">加入对话上下文</button>
                {node.type === 'personal_artifact' && <button role="menuitem" onClick={(e) => { e.stopPropagation(); setMenuOpenId(null); setPendingPublish({ item: node, target: 'team_default', name: '团队默认空间' }); }} className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 outline-none flex items-center">发布到团队快照</button>}
                {node.type === 'team_artifact' && <button role="menuitem" onClick={(e) => { e.stopPropagation(); setMenuOpenId(null); onReuse(node, 'p_analysis'); }} className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 outline-none flex items-center">复用为个人草稿</button>}
                {(node.type === 'personal_artifact' || node.type === 'team_artifact') && (node.artifactType === 'dashboard' || node.artifactType === 'chart' || node.artifactType === 'semantic') && (
                  <button role="menuitem" onClick={(e) => { 
                    e.stopPropagation(); setMenuOpenId(null); 
                    const p = new URLSearchParams(searchParams);
                    p.set('file', 'evaluation_detail');
                    p.set('eval_target', node.id);
                    setSearchParams(p);
                  }} className="w-full text-left px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-100 outline-none flex items-center">评测</button>
                )}
                {(node.artifactType === 'dashboard' || node.artifactType === 'knowledge_base') && (
                  <button role="menuitem" onClick={(e) => { 
                    e.stopPropagation(); setMenuOpenId(null); 
                    const p = new URLSearchParams(searchParams);
                    p.set('file', node.id);
                    p.set('modal', 'publish_agent');
                    setSearchParams(p);
                  }} className="w-full text-left px-3 py-1.5 text-xs text-blue-700 font-bold hover:bg-blue-50 outline-none flex items-center border-t border-slate-100 mt-1 pt-1">发布到 Agent</button>
                )}
              </div>
            )}
          </div>
          {isFolderOrRoot && isExpanded && node.children && <div role="group" className="relative">{renderTree(node.children, depth + 1)}</div>}
        </div>
      );
    });
  };

  return (
    <div className={cn("bg-white border-r border-slate-200 flex flex-col h-full shrink-0 z-10 bg-slate-50/30", isMobile ? "w-full" : "hidden md:flex w-[260px]")}>
      {isMobile && <div className="flex items-center justify-between p-4 border-b border-slate-200 bg-white"><span className="font-semibold text-slate-800">所有资源</span><button onClick={onClose} className="p-1 text-slate-500 hover:bg-slate-100 rounded-md"><X size={20}/></button></div>}
      <div role="tree" className="flex-1 overflow-y-auto py-2 pb-10 custom-scrollbar relative">{renderTree(treeData)}</div>
      <div className="relative shrink-0 border-t border-slate-200 bg-white p-2">
        <details>
          <summary
            aria-label="更多"
            className="flex cursor-pointer list-none items-center gap-2 rounded-md px-2 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100"
            onClick={() => trackShellEvent("workspace_menu_more_click")}
          >
            <MoreHorizontal size={15} /><span>更多</span>
          </summary>
          <div className="absolute bottom-full left-2 z-50 mb-1 w-44 rounded-lg border border-slate-200 bg-white py-1.5 shadow-lg">
            <button className="w-full px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-100" onClick={() => { const p = new URLSearchParams(searchParams); p.set('file', 'evaluation_detail'); setSearchParams(p); }}>验收与评测</button>
          </div>
        </details>
      </div>
      {pendingPublish && (
        <div className="fixed inset-0 bg-slate-900/40 z-[100] flex items-center justify-center p-4 backdrop-blur-sm" role="dialog" onClick={(e) => { if(e.target===e.currentTarget) setPendingPublish(null); }}>
           <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm overflow-hidden p-6 animate-in zoom-in-95">
              <h3 className="font-bold text-slate-900 text-lg mb-3">发布确认</h3>
              <p className="text-sm text-slate-600 mb-6 leading-relaxed">将 <span className="font-semibold">{pendingPublish.item.name}</span> 发布为不可变快照到 {pendingPublish.name}，个人草稿仍保留且可编辑。</p>
              <div className="flex justify-end space-x-3 border-t border-slate-100 pt-4">
                <button onClick={() => setPendingPublish(null)} className="px-4 py-2 border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50">取消</button>
                <button onClick={performPublish} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 shadow-sm flex items-center"><Send size={14} className="mr-1.5"/> 确认发布</button>
              </div>
           </div>
        </div>
      )}
    </div>
  );
}
