import React, { useState, useEffect } from 'react';
import { X, Send, UserCircle, Clock, CheckCircle2, RotateCcw, MessageSquare, AlertTriangle, ShieldCheck, Filter, Wand2, Loader2, Link as LinkIcon, Trash2, PlusSquare } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function CommentThread({ fileId, commentTarget, searchParams, setSearchParams, onCloseMobile, isMobile, showToast }: any) {
  const [input, setInput] = useState('');
  
  const [comments, setComments] = useState<any[]>(() => {
    try { const saved = localStorage.getItem('demo_comments_v4'); if (saved) return JSON.parse(saved); } catch(e) {}
    return [
      { id: 'c1', elementId: 'table_region_detail', selector: '#table_region_detail', versionId: 'V2.1', author: '李业务', time: '10分钟前', content: '表格缺少同比字段，请补充。', resolved: false, severity: 'Medium', artifactId: 'dashboard_sales_east' },
      { id: 'c2', elementId: 'table_region_detail', selector: '#table_region_detail', versionId: 'V2.1', author: '张经理', time: '1小时前', content: '建议把华东区的数据标红显示以突出', resolved: false, severity: 'High', artifactId: 'dashboard_sales_east' },
      { id: 'c3', elementId: 'chart_weekly_sales', selector: '#chart_weekly_sales', versionId: 'V2.1', author: '李业务', time: '2小时前', content: '折线图颜色太相近，难以区分', resolved: false, severity: 'Low', artifactId: 'dashboard_sales_east' }
    ];
  });
  
  useEffect(() => {
    localStorage.setItem('demo_comments_v4', JSON.stringify(comments));
  }, [comments]);

  const targetName = document.querySelector(`[data-element-id="${commentTarget}"]`)?.getAttribute('data-element-name') || commentTarget;

  const version = searchParams.get('version') || 'V2.1';
  const artifactComments = comments.filter(c => c.artifactId === fileId && c.versionId === version);
  
  const [filterMode, setFilterMode] = useState<'all' | 'unresolved' | 'resolved' | 'my'>('all');
  
  const filteredComments = artifactComments.filter(c => {
    if (filterMode === 'unresolved') return !c.resolved;
    if (filterMode === 'resolved') return c.resolved;
    if (filterMode === 'my') return c.author.includes('您');
    return true;
  });

  const activeComments = artifactComments.filter(c => !c.resolved);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const handleSend = () => {
    if (!input.trim()) return;
    const newComment = {
      id: Date.now().toString(),
      elementId: commentTarget || 'general',
      selector: `#${commentTarget || 'general'}`,
      versionId: version,
      author: '您 (haoxingjun)',
      time: '刚刚',
      content: input,
      resolved: false,
      severity: 'Low',
      artifactId: fileId,
    };
    setComments([...comments, newComment]);
    setInput('');
  };

  const toggleSelect = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };
  
  const allUnresolvedIds = activeComments.map(c => c.id);
  const isAllSelected = selectedIds.length === allUnresolvedIds.length && allUnresolvedIds.length > 0;
  
  const toggleSelectAll = () => {
    if (isAllSelected) setSelectedIds([]);
    else setSelectedIds(allUnresolvedIds);
  };

  const [fixState, setFixState] = useState<'idle' | 'plan' | 'applying' | 'done'>('idle');
  const [fixTargetIds, setFixTargetIds] = useState<string[]>([]);
  const [fixResults, setFixResults] = useState<Record<string, 'success' | 'fail'>>({});

  const initiateFixPlan = (ids: string[]) => {
    if (ids.length === 0) return;
    setFixTargetIds(ids);
    setFixState('plan');
  };

  const removePlanItem = (id: string) => {
    setFixTargetIds(prev => prev.filter(x => x !== id));
    if (fixTargetIds.length <= 1) setFixState('idle');
  };

  const applyFix = () => {
    setFixState('applying');
    setTimeout(() => {
       const results: Record<string, 'success' | 'fail'> = {};
       fixTargetIds.forEach((id, idx) => {
         // Simulate partial failure if multiple selected
         results[id] = (fixTargetIds.length > 1 && idx === fixTargetIds.length - 1) ? 'fail' : 'success';
       });
       setFixResults(results);
       setFixState('done');
    }, 2000);
  };

  const confirmVerify = () => {
    setComments(prev => prev.map(c => {
      if (fixTargetIds.includes(c.id) && fixResults[c.id] === 'success') {
        return { ...c, resolved: true };
      }
      return c;
    }));
    setSelectedIds([]);
    setFixState('idle');
    setFixTargetIds([]);
    const p = new URLSearchParams(searchParams);
    p.set('version', 'V2.2');
    setSearchParams(p);
    showToast?.('验证成功！已生成新版本草稿 V2.2，成功的修复项已自动标记为解决。');
  };

  const retryFailed = () => {
    const failedIds = fixTargetIds.filter(id => fixResults[id] === 'fail');
    setFixTargetIds(failedIds);
    setFixState('applying');
    setTimeout(() => {
      const results = { ...fixResults };
      failedIds.forEach(id => results[id] = 'success');
      setFixResults(results);
      setFixState('done');
    }, 1500);
  };

  const rollbackFix = () => {
    setFixState('idle');
    setFixTargetIds([]);
    setFixResults({});
    const p = new URLSearchParams(searchParams);
    p.set('version', 'V2.1');
    setSearchParams(p);
    showToast?.('已撤销修复申请并回滚 Dashboard 至原版本状态。');
  };

  const handleCommentClick = (c: any) => {
    if (c.elementId && c.elementId !== 'general') {
      const p = new URLSearchParams(searchParams);
      p.set('comment_target', c.elementId);
      setSearchParams(p);
    }
  };

  const closeThread = () => {
    const p = new URLSearchParams(searchParams);
    p.delete('comment_target');
    p.delete('pane');
    setSearchParams(p);
  };

  return (
    <div className="h-full min-h-0 flex flex-col overflow-hidden bg-white relative animate-in fade-in">
      <div className="shrink-0 flex flex-col border-b border-slate-200 bg-slate-50/50">
        <div className="flex items-center justify-between p-4 pb-2">
          <div>
            <h3 className="font-semibold text-slate-800 text-sm">评论与修复跟进</h3>
            {commentTarget && targetName && <div className="text-xs text-slate-500 mt-0.5 truncate">当前定位: {targetName}</div>}
          </div>
          <div className="flex space-x-1">
            <button onClick={closeThread} aria-label="关闭" title="关闭" className="p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded transition-colors outline-none"><X size={18} /></button>
          </div>
        </div>
        
        <div className="flex items-center justify-between px-4 pb-3">
          <label className="flex items-center space-x-2 text-sm text-slate-600 cursor-pointer group">
            <input type="checkbox" checked={isAllSelected} onChange={toggleSelectAll} disabled={allUnresolvedIds.length === 0} className="rounded text-blue-600 focus:ring-blue-500 disabled:opacity-50 cursor-pointer" />
            <span className="group-hover:text-slate-800 transition-colors">全选未解决 ({allUnresolvedIds.length})</span>
          </label>
          <div className="flex items-center space-x-2">
            <button onClick={() => initiateFixPlan(allUnresolvedIds)} disabled={allUnresolvedIds.length === 0} className="text-xs font-medium bg-white border border-slate-200 text-purple-600 hover:bg-purple-50 hover:border-purple-200 px-2 py-1 rounded-md transition-colors outline-none disabled:opacity-50 flex items-center shadow-sm">
              <Wand2 size={12} className="mr-1" /> 修复全部未解决
            </button>
            <select 
              value={filterMode} 
              onChange={e => setFilterMode(e.target.value as any)}
              className="text-xs border border-slate-200 rounded-md px-2 py-1 bg-white outline-none focus:border-blue-500 text-slate-600 cursor-pointer"
            >
              <option value="all">全部评论</option>
              <option value="unresolved">未解决</option>
              <option value="resolved">已解决</option>
              <option value="my">我的</option>
            </select>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 custom-scrollbar bg-slate-50 relative">
        {artifactComments.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-slate-400">
            <MessageSquare size={32} className="mb-3 opacity-30" />
            <span className="text-sm">暂无评论，来发表第一条吧</span>
          </div>
        )}

        {selectedIds.length > 0 && fixState === 'idle' && (
          <div className="mb-4 flex items-center justify-between bg-blue-50 border border-blue-100 rounded-xl p-3 shadow-sm sticky top-0 z-10 animate-in slide-in-from-top-2">
            <div className="text-xs text-blue-800 font-medium flex items-center"><CheckCircle2 size={14} className="mr-1.5"/> 已选中 {selectedIds.length} 项</div>
            <button onClick={() => initiateFixPlan(selectedIds)} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700 transition-colors shadow-sm font-medium flex items-center outline-none"><Wand2 size={12} className="mr-1.5"/> 批量修复选中项</button>
          </div>
        )}
        
        {fixState !== 'idle' && (
          <div className="mb-6 border-2 border-blue-500 rounded-xl overflow-hidden bg-white shadow-lg animate-in slide-in-from-top-2 relative z-20">
            <div className="bg-blue-50 p-3 border-b border-blue-100 flex items-center justify-between">
              <span className="text-sm font-bold text-blue-900 flex items-center"><Wand2 size={16} className="mr-2 text-blue-600"/> 修复与验证引擎 (Fix Plan)</span>
              {fixState === 'plan' && <button onClick={() => {setFixState('idle'); setFixTargetIds([]);}} className="text-blue-500 hover:text-blue-700 outline-none"><X size={16} /></button>}
            </div>
            
            {fixState === 'plan' && (
              <div className="p-4 text-xs text-slate-600 space-y-4">
                <p className="font-medium text-slate-800">即将批量修复 {fixTargetIds.length} 项问题。AI 已识别受影响元素并建议了以下变更：</p>
                <div className="space-y-2 max-h-[160px] overflow-auto custom-scrollbar pr-2">
                  {fixTargetIds.map(id => {
                    const c = comments.find(x => x.id === id);
                    return (
                      <div key={id} className="bg-slate-50 p-2.5 rounded-lg border border-slate-200 flex justify-between items-start group">
                        <div className="flex-1 min-w-0 pr-3">
                           <div className="font-bold text-slate-700 mb-1 flex items-center"><LinkIcon size={10} className="mr-1 text-slate-400"/> {c?.elementId}</div>
                           <div className="text-slate-600 truncate">{c?.content}</div>
                        </div>
                        <button onClick={() => removePlanItem(id)} className="text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity outline-none" title="取消此项修复"><Trash2 size={14}/></button>
                      </div>
                    )
                  })}
                </div>
                <div className="flex items-center text-amber-700 bg-amber-50 p-3 rounded-lg border border-amber-200 leading-relaxed">
                  <AlertTriangle size={24} className="mr-2 shrink-0" />
                  <span>部分元素修复可能产生样式冲突，系统将在 Apply 后自动运行验证并展示精确 Diff。</span>
                </div>
                <div className="flex justify-end pt-2">
                  <button onClick={applyFix} className="bg-blue-600 text-white px-5 py-2.5 rounded-lg hover:bg-blue-700 font-bold shadow-sm outline-none focus:ring-2 focus:ring-blue-500">Apply & Verify (应用并验证)</button>
                </div>
              </div>
            )}

            {fixState === 'applying' && (
              <div className="p-8 text-center space-y-3">
                <RotateCcw size={28} className="animate-spin text-blue-600 mx-auto" />
                <div className="text-sm font-bold text-blue-800">正在生成新版草稿并回归验证...</div>
                <div className="w-full h-2 bg-blue-100 rounded-full overflow-hidden mt-4"><div className="h-full bg-blue-500 animate-pulse"></div></div>
              </div>
            )}

            {fixState === 'done' && (
              <div className="p-4 text-xs text-slate-600 space-y-4">
                <div className="font-bold text-slate-800 flex justify-between items-center">
                  <span>回归验证结果与 Diff 摘要</span>
                  {Object.values(fixResults).includes('fail') && <span className="bg-amber-100 text-amber-800 px-2 py-0.5 rounded font-medium border border-amber-200">部分失败</span>}
                </div>
                <div className="space-y-3 max-h-[200px] overflow-auto custom-scrollbar">
                  {fixTargetIds.map(id => {
                    const c = comments.find(x => x.id === id);
                    const isSuccess = fixResults[id] === 'success';
                    return (
                      <div key={id} className={cn("p-3 rounded-lg border shadow-sm", isSuccess ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200")}>
                        <div className="flex items-start justify-between mb-1.5">
                          <span className="font-bold text-slate-800 truncate pr-2">{c?.elementId}</span>
                          {isSuccess ? <span className="text-green-700 flex items-center bg-green-100 px-1.5 py-0.5 rounded"><CheckCircle2 size={12} className="mr-1"/>Pass</span> : <span className="text-red-700 flex items-center bg-red-100 px-1.5 py-0.5 rounded"><AlertTriangle size={12} className="mr-1"/>Fail</span>}
                        </div>
                        <div className="text-slate-600 truncate">{c?.content}</div>
                        {!isSuccess && <div className="text-[11px] text-red-600 mt-2 font-medium bg-white p-1.5 rounded border border-red-100">由于图表宽度限制，此修改导致标题溢出重叠。</div>}
                      </div>
                    )
                  })}
                </div>
                <div className="flex justify-end space-x-3 pt-3 border-t border-slate-100 mt-2">
                  <button onClick={rollbackFix} className="px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 font-bold outline-none transition-colors">Rollback 撤销全部</button>
                  {Object.values(fixResults).includes('fail') ? (
                    <button onClick={retryFailed} className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 font-bold shadow-sm outline-none transition-colors">仅重试失败项</button>
                  ) : (
                    <button onClick={confirmVerify} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-bold shadow-sm outline-none transition-colors">完成闭环验证 (Resolved)</button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="space-y-4">
          {filteredComments.map(c => (
            <div key={c.id} className="flex items-start gap-2 group relative" onClick={() => handleCommentClick(c)}>
              {!c.resolved && (
                <div className="pt-4 shrink-0">
                  <input 
                    type="checkbox" 
                    checked={selectedIds.includes(c.id)} 
                    onChange={(e) => toggleSelect(c.id, e)} 
                    className="rounded text-blue-600 focus:ring-blue-500 cursor-pointer w-4 h-4" 
                  />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className={cn("bg-white border rounded-xl p-4 shadow-sm relative transition-all cursor-pointer outline-none", c.resolved ? "border-slate-200 opacity-60" : "border-slate-200 hover:border-blue-400 hover:shadow-md", commentTarget === c.elementId && !c.resolved && "ring-2 ring-blue-500 border-transparent")}>
                  {c.resolved && <div className="absolute top-4 right-4 text-green-600 bg-green-50 rounded-full p-0.5"><CheckCircle2 size={16}/></div>}
                  <div className="flex items-start mb-3">
                    <div className="w-8 h-8 rounded-full bg-slate-100 text-slate-600 flex items-center justify-center mr-3 shrink-0"><UserCircle size={18}/></div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center text-xs mb-0.5">
                        <span className="font-bold text-slate-900 truncate">{c.author}</span>
                        <span className="mx-2 text-slate-300">•</span>
                        <span className="text-slate-500 flex items-center"><Clock size={12} className="mr-1"/>{c.time}</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        <span className="text-[10px] text-slate-400 bg-slate-50 border border-slate-100 px-1.5 py-0.5 rounded font-mono truncate max-w-[150px]">{c.elementId}</span>
                        {c.severity === 'High' && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-700 border border-red-200">High</span>}
                      </div>
                    </div>
                  </div>
                  <div className="text-[13px] text-slate-800 leading-relaxed break-words">{c.content}</div>

                  <div className="mt-4 pt-3 border-t border-slate-50 flex flex-wrap items-center gap-2">
                    {!c.resolved ? (
                      <>
                        <button onClick={(e) => { e.stopPropagation(); initiateFixPlan([c.id]); }} className="text-xs font-bold text-blue-700 bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-100 transition-colors outline-none flex items-center shadow-sm">
                          <Wand2 size={12} className="mr-1.5"/> 单项 AI 修复
                        </button>
                        <button onClick={(e) => {
                           e.stopPropagation();
                           setComments(prev => prev.map(x => x.id === c.id ? { ...x, resolved: true } : x));
                           showToast?.('已手动标记为解决。');
                        }} className="text-xs font-medium text-slate-600 border border-slate-200 hover:text-green-700 hover:border-green-300 hover:bg-green-50 px-3 py-1.5 rounded-lg transition-colors outline-none shadow-sm flex items-center">
                          <CheckCircle2 size={12} className="mr-1.5"/> 手动解决
                        </button>
                      </>
                    ) : (
                      <button onClick={(e) => {
                         e.stopPropagation();
                         setComments(prev => prev.map(x => x.id === c.id ? { ...x, resolved: false } : x));
                      }} className="text-xs font-medium text-slate-500 hover:text-blue-600 transition-colors outline-none flex items-center"><RotateCcw size={14} className="mr-1.5"/>重新打开 (Reopen)</button>
                    )}
                    <button onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: c.id, name: `评论: ${c.content.substring(0,10)}...`, type: 'comment', artifactId: c.artifactId, elementId: c.elementId, tokenEstimate: 0.4} } })); showToast?.('已加入对话上下文'); }} className="text-[11px] font-medium text-slate-500 hover:text-blue-600 border border-slate-200 px-2 py-1 rounded ml-auto transition-colors outline-none flex items-center"><PlusSquare size={12} className="mr-1"/> 上下文</button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="shrink-0 relative p-4 border-t border-slate-200 bg-white shadow-[0_-4px_10px_rgba(0,0,0,0.02)] z-30">
        <div className="bg-slate-50 border border-slate-300 rounded-xl p-2.5 focus-within:bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 transition-all shadow-sm">
          <textarea 
            className="w-full text-sm bg-transparent border-none outline-none resize-none p-1.5 placeholder:text-slate-400"
            rows={2}
            placeholder={commentTarget ? `对选中元素 [${commentTarget}] 发表评论...` : "输入全局评论内容..."}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <div className="flex justify-between items-center mt-2 border-t border-slate-100 pt-2">
            <div className="text-[10px] text-slate-500 font-medium bg-slate-100 px-2 py-1 rounded-md border border-slate-200">目标版本: {version}</div>
            <button onClick={handleSend} disabled={!input.trim()} className="px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:bg-slate-300 transition-colors outline-none font-medium flex items-center shadow-sm"><Send size={14} className="mr-1.5"/>发送</button>
          </div>
        </div>
      </div>
    </div>
  );
}