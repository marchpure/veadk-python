import React from 'react';
import ChatAssistant from '../RightPane/ChatAssistant';
import PropertyEditor from '../RightPane/PropertyEditor';
import CommentThread from '../RightPane/CommentThread';
import { PanelRightClose, PanelRightOpen, X } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function RightPane({ fileId, searchParams, setSearchParams, showToast, isMobile, onClose, chatChips, setChatChips, isHomeChat, isRightPaneOpen }: any) {
  const isEditing = searchParams.get('edit');
  const commentTarget = searchParams.get('comment_target');
  const chatState = searchParams.get('chat');
  const isClosed = !isHomeChat && !isRightPaneOpen;
  
  const togglePane = () => {
    const p = new URLSearchParams(searchParams);
    if (isClosed) {
      p.set('pane', 'open');
    } else {
      p.set('pane', 'closed');
      p.delete('comment_target');
      p.delete('edit');
    }
    setSearchParams(p);
  };

  return (
    <div className={cn(
      "h-full min-h-0 overflow-hidden flex flex-col shrink-0 relative z-40 min-w-0 w-full bg-white",
      !isHomeChat && !isMobile && "border-l border-slate-200"
    )}>
      {!isMobile && !isHomeChat && (
        <button 
          aria-label={isClosed ? "展开分析助手" : "收起分析助手"}
          title={isClosed ? "展开分析助手" : "收起分析助手"}
          onClick={togglePane}
          className="absolute top-1/2 -translate-y-1/2 w-4 h-12 bg-white border-y border-l border-slate-200 rounded-l-md flex items-center justify-center text-slate-400 hover:text-blue-600 hover:bg-slate-50 transition-colors z-20 outline-none"
          style={{ left: '-16px' }}
        >
          {isClosed ? <PanelRightOpen size={14} /> : <PanelRightClose size={14} />}
        </button>
      )}

      {isMobile && !isHomeChat && (
        <div className="flex items-center justify-between p-4 border-b border-slate-200 bg-white shrink-0">
          <span className="font-bold text-slate-800">分析助手</span>
          <button onClick={onClose} aria-label="关闭分析助手" className="p-1 text-slate-500 hover:bg-slate-100 rounded-md transition-colors"><X size={20}/></button>
        </div>
      )}

      <div className="flex-1 overflow-hidden flex flex-col min-w-0 w-full">
        {isEditing ? (
          <PropertyEditor editTarget={isEditing} searchParams={searchParams} setSearchParams={setSearchParams} showToast={showToast} onCloseMobile={onClose} isMobile={isMobile} />
        ) : commentTarget ? (
          <CommentThread fileId={fileId} commentTarget={commentTarget} searchParams={searchParams} setSearchParams={setSearchParams} onCloseMobile={onClose} isMobile={isMobile} showToast={showToast} />
        ) : (
          <ChatAssistant fileId={fileId} chatState={chatState} searchParams={searchParams} setSearchParams={setSearchParams} chatChips={chatChips || []} setChatChips={setChatChips} showToast={showToast} isHomeChat={isHomeChat} />
        )}
      </div>
    </div>
  );
}