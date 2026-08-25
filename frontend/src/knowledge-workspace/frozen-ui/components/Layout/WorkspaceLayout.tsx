import React, { useState, useEffect, useSyncExternalStore, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import TopNav from './TopNav';
import FileTreePane from './FileTreePane';
import MainAreaPane from './MainAreaPane';
import RightPane from './RightPane';
import ShareModal from '../Modals/ShareModal';
import VersionHistoryModal from '../Modals/VersionHistoryModal';
import PublishModal from '../Modals/PublishModal';
import ExportModal from '../Modals/ExportModal';
import CreateResourceModal from '../Modals/CreateResourceModal';
import AgentResourceSelectorModal from '../Modals/AgentResourceSelectorModal';
import PublishAgentModal from '../Modals/PublishAgentModal';
import { CheckCircle2, Database, LayoutDashboard, FilePieChart, FileText, Ban, Loader2, X, FileSpreadsheet } from 'lucide-react';
import { cn } from '../../lib/utils';
import { dragStore } from '../../lib/dragStore';
import { resourceStore, useStore, getResourceDescriptor } from '../../lib/store';
import { getServerContextRef } from '../../../production/domainClient';
import { actionLoopStore, defaultActionLoopState } from '../../lib/actionLoopStore';
import HomeComposer from './HomeComposer';
import V212EntryDrawer from './V212EntryDrawer';
import { trackShellEventOnce } from './shellTelemetry';

const useDragState = () => useSyncExternalStore(dragStore.subscribe, dragStore.getState);

export default function WorkspaceLayout() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const [searchParams, setSearchParams] = useSearchParams();
  const fileId = searchParams.get('file') || 'welcome';
  const errorState = searchParams.get('error') || searchParams.get('error_state');
  const modal = searchParams.get('modal');
  const [toast, setToast] = useState<{message: string, visible: boolean, onUndo?: () => void}>({ message: '', visible: false });
  const filePreview = searchParams.get('file_preview');

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [mobileAssistantOpen, setMobileAssistantOpen] = useState(false);

  const handleResetDemo = (mode: string) => {
    if (mode === 'empty') {
      const p = new URLSearchParams(searchParams);
      p.set('file', 'workspace_empty');
      setSearchParams(p);
    } else {
      actionLoopStore.setState(() => defaultActionLoopState);
      const p = new URLSearchParams();
      p.set('file', 'welcome');
      setSearchParams(p);
    }
    showToast('演示环境已重置');
  };
  const [chatChips, setChatChips] = useState<any[]>(() => {
    return [];
  });

  const dragState = useDragState();

  useEffect(() => {
    const handleDragOver = (e: DragEvent) => {
      const state = dragStore.getState();
      if (state.status !== 'idle') {
        e.preventDefault();
        dragStore.setState({ position: { x: e.clientX, y: e.clientY } });
      }
    };
    const handleDragEnd = (e: DragEvent) => {
      const state = dragStore.getState();
      if (state.status !== 'drop-pending' && state.status !== 'success' && state.status !== 'idle') {
         dragStore.setState({ status: 'cancelled' });
         setTimeout(() => dragStore.setState({ status: 'idle', item: null }), 200);
      }
    };
    window.addEventListener('dragover', handleDragOver);
    window.addEventListener('dragend', handleDragEnd);
    return () => {
      window.removeEventListener('dragover', handleDragOver);
      window.removeEventListener('dragend', handleDragEnd);
    };
  }, []);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (searchParams.get('select_mode') === 'true') {
          const p = new URLSearchParams(searchParams);
          p.delete('select_mode');
          setSearchParams(p);
          return;
        }
        if (dragStore.getState().status !== 'idle') {
          dragStore.setState({ status: 'cancelled' });
          setTimeout(() => dragStore.setState({ status: 'idle', item: null }), 200);
        } else if (!document.querySelector('[role="dialog"][aria-modal="true"]:not([aria-label="目录"]):not([aria-label="分析助手"])')) {
          if (mobileMenuOpen) {
            setMobileMenuOpen(false);
          } else if (mobileAssistantOpen) {
            setMobileAssistantOpen(false);
          }
        }
      } else if (e.key.toLowerCase() === 'v' && e.target instanceof HTMLElement && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
        const p = new URLSearchParams(searchParams);
        if (p.get('select_mode') === 'true') p.delete('select_mode');
        else p.set('select_mode', 'true');
        setSearchParams(p);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [mobileMenuOpen, mobileAssistantOpen, searchParams, setSearchParams]);

  const closeMenu = () => setMobileMenuOpen(false);
  const closeAssistant = () => setMobileAssistantOpen(false);
  const closeModal = () => {
    const p = new URLSearchParams(searchParams);
    p.delete('modal');
    setSearchParams(p);
  };
  
  const handlePublish = (item: any, targetDir: string) => {
    void item; void targetDir;
    showToast('发布必须由服务端确认，请从 Skill 草稿页面提交。');
  };

  const handleReuseRequest = (item: any, targetDir: string) => {
    void item; void targetDir;
    showToast('复制 Skill 必须由服务端确认。');
  };

  const getChipIdentity = (chip: any) => {
    if (chip.type === 'element_group') {
      const ids = [...(chip.elements || [])].map((e: any) => e.id).sort().join(',');
      return `element_group_${chip.artifactId || ''}_${chip.version || ''}_${ids}`;
    }
    return `${chip.type}_${chip.id}_${chip.version || ''}_${chip.selectionIdentity || ''}`;
  };

  const addContextItem = (item: any) => {
    setChatChips(prev => {
      const serverContextRef = item.contextRef || getServerContextRef(
        String(item.resourceId || item.artifactId || item.id || ''),
      );
      const nextItem = serverContextRef
        ? { ...item, contextRef: serverContextRef }
        : item;
      const identity = getChipIdentity(nextItem);
      const exists = prev.find(p => getChipIdentity(p) === identity);
      if (exists) {
        setTimeout(() => showToast(`该上下文已加入`), 100);
        return prev;
      }
      setTimeout(() => showToast(`已加入对话上下文`), 100);
      return [...prev, { ...nextItem, identity, manual: true }];
    });
    
    const p = new URLSearchParams(window.location.search);
    if (!p.has('pane')) p.set('pane', 'open');
    setSearchParams(p);
  };

  useEffect(() => {
    const handleAddContextItem = (e: CustomEvent) => addContextItem(e.detail.item);
    window.addEventListener('add_context_item', handleAddContextItem as EventListener);
    return () => window.removeEventListener('add_context_item', handleAddContextItem as EventListener);
  }, []);

  const showToast = (message: string, onUndo?: () => void) => {
    setToast({ message, visible: true, onUndo });
    setTimeout(() => setToast(prev => ({ ...prev, visible: false })), 4000);
  };

  const isHomeChat = fileId === 'welcome';
  const chatState = searchParams.get('chat');

  useEffect(() => {
    if (isHomeChat) trackShellEventOnce("workspace_home_view", "home");
  }, [isHomeChat]);
  
  // RightPane Open/Close Logic
  const allResources = useStore(resourceStore);
  const isWorkspaceEmpty = searchParams.get('file') === 'workspace_empty' || searchParams.get('workspace_empty') === 'true';

  const descriptor = getResourceDescriptor(fileId, searchParams, allResources);
  
  const previousResourceIdentityRef = useRef<string | null>(null);

  useEffect(() => {
    if (descriptor) {
      if (previousResourceIdentityRef.current !== descriptor.identity) {
        previousResourceIdentityRef.current = descriptor.identity;
        
        const p = new URLSearchParams(searchParams);
        if (p.get('pane') === 'closed') {
          p.delete('pane');
          setSearchParams(p, { replace: true });
        }
        
        setChatChips(prev => {
          if (prev.some(c => c.identity === descriptor.identity)) return prev;
          const resourceLevelTypes = ['connection', 'source', 'dataset', 'document', 'knowledge_base', 'skill', 'semantic', 'semantic_model', 'chart', 'dashboard', 'knowledge_graph', 'kg', 'evaluation', 'personal_artifact', 'team_artifact', 'artifact', 'resource'];
          const filtered = prev.filter(c => c.manual || (!c.isResourceLevel && !resourceLevelTypes.includes(c.type)));
          const contextRef = getServerContextRef(
            String(descriptor.resourceId || descriptor.artifactId || descriptor.id),
          );
          return [...filtered, contextRef ? { ...descriptor, contextRef } : descriptor];
        });
      }
    } else {
      previousResourceIdentityRef.current = null;
    }
  }, [descriptor?.identity, searchParams, setSearchParams]);

  const paneState = searchParams.get('pane');
  const isTaskSplit = !!chatState;
  
  // Determine if right pane should be open
  const isRightPaneOpen = !isHomeChat && (isTaskSplit || paneState === 'open' || searchParams.has('comment_target') || searchParams.has('edit') || (descriptor && paneState !== 'closed'));

  return (
    <div className="flex flex-col h-screen w-full bg-[#f8fafc] text-slate-900 font-sans overflow-hidden select-none">
      <TopNav searchParams={searchParams} setSearchParams={setSearchParams} onOpenMenu={() => { setMobileMenuOpen(true); setMobileAssistantOpen(false); }} onOpenAssistant={() => { setMobileAssistantOpen(true); setMobileMenuOpen(false); }} />
      
      {/* 
        True CSS Grid Shell for Desktop
        Layout: [248px Left] [1fr Center] [380px Right (if open) or 0px]
      */}
      <div 
        className={cn(
          "flex-1 min-h-0 h-auto max-w-[1440px] mx-auto w-full bg-white border-x border-slate-200 shadow-sm overflow-hidden",
          "hidden md:grid"
        )}
        style={{
          gridTemplateColumns: `248px minmax(0, 1fr) ${isHomeChat ? '0px' : (isRightPaneOpen ? '380px' : '0px')}`,
          transition: 'grid-template-columns 300ms ease-in-out'
        }}
      >
        <div className="min-h-0 h-full overflow-hidden border-r border-slate-200">
          <FileTreePane 
            fileId={fileId} 
            searchParams={searchParams} 
            setSearchParams={setSearchParams} 
            onResetDemo={handleResetDemo}
            isMobile={false}
            publishedItems={[]}
            reusedItems={[]}
            onPublish={handlePublish}
            onReuse={handleReuseRequest}
            onAddChip={addContextItem}
            showToast={showToast}
            isWorkspaceEmpty={isWorkspaceEmpty}
            addedSources={[]}
          />
        </div>
        
        <div className="min-h-0 h-full overflow-hidden min-w-0 w-full relative flex flex-col bg-slate-50/50">
          {!isMobile && isHomeChat ? (
            <HomeComposer searchParams={searchParams} setSearchParams={setSearchParams} />
          ) : (
            <MainAreaPane fileId={fileId} errorState={errorState} telemetryEnabled={!isMobile} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} isWorkspaceEmpty={isWorkspaceEmpty} />
          )}
        </div>

        <div className="min-h-0 h-full overflow-hidden min-w-0 w-full relative">
          {!isMobile && !isHomeChat && (
            <RightPane 
              fileId={fileId} 
              searchParams={searchParams} 
              setSearchParams={setSearchParams} 
              showToast={showToast} 
              isMobile={false} 
              chatChips={chatChips}
              setChatChips={setChatChips}
              isHomeChat={false}
              isRightPaneOpen={isRightPaneOpen}
            />
          )}
        </div>
      </div>

      {/* Mobile Layout Fallback */}
      <div className="flex-1 w-full h-full relative overflow-hidden md:hidden flex flex-col">
         {/* Mobile Menu Drawer */}
         <div className={cn(
            "fixed inset-y-0 left-0 z-[60] bg-white transition-transform duration-300 shadow-2xl w-[280px]",
            mobileMenuOpen ? "translate-x-0" : "-translate-x-full"
          )}
          role={mobileMenuOpen ? "dialog" : undefined}
          aria-modal={mobileMenuOpen ? "true" : undefined}
          aria-label={mobileMenuOpen ? "目录" : undefined}
          >
            <FileTreePane fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} isMobile={true} onClose={closeMenu} onResetDemo={handleResetDemo} publishedItems={[]} reusedItems={[]} onPublish={handlePublish} onReuse={handleReuseRequest} onAddChip={addContextItem} showToast={showToast} isWorkspaceEmpty={isWorkspaceEmpty} />
          </div>
          {mobileMenuOpen && <div className="fixed inset-0 bg-slate-900/40 z-[50] backdrop-blur-sm" onClick={closeMenu} />}
          
          <div className="flex-1 overflow-hidden min-w-0 w-full h-full">
            {isMobile && isHomeChat ? (
              <HomeComposer searchParams={searchParams} setSearchParams={setSearchParams} />
            ) : (
              <MainAreaPane fileId={fileId} errorState={errorState} telemetryEnabled={isMobile} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} isWorkspaceEmpty={isWorkspaceEmpty} />
            )}
          </div>
          
          <div className={cn(
            "fixed inset-0 z-[60] flex flex-col justify-end pointer-events-none transition-transform duration-300",
            mobileAssistantOpen ? "translate-y-0" : "translate-y-full"
          )}>
            <div className="bg-white w-full h-[85vh] rounded-t-2xl shadow-2xl pointer-events-auto flex flex-col border-t border-slate-200">
               {isMobile && !isHomeChat && (
                 <RightPane fileId={fileId} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} isMobile={true} onClose={closeAssistant} chatChips={chatChips} setChatChips={setChatChips} isHomeChat={false} isRightPaneOpen={true} />
               )}
            </div>
          </div>
          {mobileAssistantOpen && <div className="fixed inset-0 bg-slate-900/40 z-[50] backdrop-blur-sm" onClick={closeAssistant} />}
      </div>

      {/* Modals Layer */}
      {modal === 'share' && <ShareModal onClose={closeModal} searchParams={searchParams} showToast={showToast} />}
      {modal === 'export' && <ExportModal onClose={closeModal} showToast={showToast} />}
      {modal === 'versions' && <VersionHistoryModal onClose={closeModal} searchParams={searchParams} />}
      {modal === 'publish' && <PublishModal onClose={closeModal} onConfirm={() => { closeModal(); showToast('已成功发布到团队工作区'); }} isTeam={fileId.includes('team')} />}
      {modal === 'create_resource' && <CreateResourceModal onClose={closeModal} searchParams={searchParams} setSearchParams={setSearchParams} />}
      {modal === 'agent_selector' && <AgentResourceSelectorModal onClose={closeModal} />}
      {modal === 'publish_agent' && <PublishAgentModal onClose={closeModal} showToast={showToast} fileId={fileId} />}
      {modal === 'v212_entry' && (
        <V212EntryDrawer
          searchParams={searchParams}
          setSearchParams={setSearchParams}
          onClose={closeModal}
        />
      )}
      <div role="status" aria-live="polite" className={`fixed top-16 left-1/2 -translate-x-1/2 z-[100] transition-all duration-300 ${toast.visible ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4 pointer-events-none'}`}>
        <div className="bg-white border border-slate-200 shadow-lg rounded-full px-4 py-2.5 flex items-center space-x-3">
          <CheckCircle2 size={16} className="text-green-500 shrink-0" />
          <span className="text-sm font-medium text-slate-700">{toast.message}</span>
          {toast.onUndo && (
            <>
              <div className="w-px h-3 bg-slate-300 mx-1"></div>
              <button onClick={() => { toast.onUndo?.(); setToast(p => ({...p, visible: false})); }} className="text-blue-600 text-sm font-semibold hover:text-blue-700 transition-colors">撤销</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
