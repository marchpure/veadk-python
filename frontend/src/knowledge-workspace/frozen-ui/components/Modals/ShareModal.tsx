import React, { useState, useEffect } from 'react';
import { X, Copy, Check, Users, Globe, Lock, Clock, Link as LinkIcon, Trash2, Search, XCircle, ShieldAlert, Play, Pause, Edit3, Loader2, RefreshCw, Send, History, CheckCircle2 } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function ShareModal({ onClose, searchParams, showToast }: any) {
  const [activeTab, setActiveTab] = useState<'access' | 'refresh' | 'delivery' | 'history'>('access');
  
  const [scope, setScope] = useState<'team' | 'public' | 'private'>('team');
  const [mode, setMode] = useState<'realtime' | 'snapshot'>('snapshot');
  const [watermark, setWatermark] = useState(true);
  
  const [searchMember, setSearchMember] = useState('');
  const [selectedMembers, setSelectedMembers] = useState<{id: string, name: string}[]>([]);
  
  const [refreshType, setRefreshType] = useState<'manual'|'hourly'|'daily'|'weekly'|'cron'>('manual');
  const [cronExpr, setCronExpr] = useState('0 9 * * *');
  const [timezone, setTimezone] = useState('Asia/Shanghai (UTC+8)');
  const [startTime, setStartTime] = useState('09:00');
  const [delayTol, setDelayTol] = useState('不允许延迟 (立刻失败)');
  const [retries, setRetries] = useState('3 次');
  const [allowOld, setAllowOld] = useState(false);
  
  const [deliveryMode, setDeliveryMode] = useState('after_refresh');
  const [deliveryFormat, setDeliveryFormat] = useState('html');
  const [deliveryChannel, setDeliveryChannel] = useState('email');
  const [deliveryRecipients, setDeliveryRecipients] = useState('data-team@company.com');
  
  const [shares, setShares] = useState<any[]>(() => {
    try { const saved = localStorage.getItem('demo_shares_v3'); return saved ? JSON.parse(saved) : []; } catch(e) { return []; }
  });
  useEffect(() => { localStorage.setItem('demo_shares_v3', JSON.stringify(shares)); }, [shares]);

  const [dynamicHistory, setDynamicHistory] = useState<any[]>(() => {
    try { const saved = localStorage.getItem('demo_share_history'); return saved ? JSON.parse(saved) : []; } catch(e) { return []; }
  });
  useEffect(() => { localStorage.setItem('demo_share_history', JSON.stringify(dynamicHistory)); }, [dynamicHistory]);

  const [isCopied, setIsCopied] = useState(false);
  const evalApplied = searchParams?.get('eval_applied') === 'true' || searchParams?.get('version') === 'v2.2';
  const hasSensitivity = !evalApplied; 
  const currentVersion = evalApplied ? 'V2.2' : 'V2.1';
  
  const allMembers = [{ id: '1', name: '王分析' }, { id: '2', name: '李业务' }, { id: '3', name: '张经理' }];
  const filteredMembers = allMembers.filter(m => m.name.includes(searchMember) && !selectedMembers.find(sm => sm.id === m.id));

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const [editingId, setEditingId] = useState<string | null>(null);

  const startEdit = (share: any) => {
    setEditingId(share.id);
    setScope(share.scope);
    setMode(share.mode);
    setRefreshType(share.refreshType || 'manual');
    setCronExpr(share.cronExpr || '0 9 * * *');
    setTimezone(share.timezone || 'Asia/Shanghai (UTC+8)');
    setStartTime(share.startTime || '09:00');
    setDelayTol(share.delayTol || '不允许延迟 (立刻失败)');
    setRetries(share.retries || '3 次');
    setAllowOld(share.allowOld || false);
    setDeliveryMode(share.deliveryMode || 'after_refresh');
    setDeliveryFormat(share.deliveryFormat || 'html');
    setDeliveryChannel(share.deliveryChannel || 'email');
    setDeliveryRecipients(share.deliveryRecipients || 'data-team@company.com');
  };

  const getNextRefresh = () => {
    const now = new Date();
    const h = (now.getHours() + 1).toString().padStart(2, '0');
    return `今天 ${h}:00`;
  };

  const handleCreate = () => {
    if (activeTab !== 'access') {
      setActiveTab('access');
      return;
    }
    
    if (editingId) {
      setShares(prev => prev.map(s => s.id === editingId ? {
        ...s, scope, mode, members: selectedMembers, 
        refreshType, cronExpr, timezone, startTime, delayTol, retries, allowOld,
        deliveryMode, deliveryFormat, deliveryChannel, deliveryRecipients
      } : s));
      showToast?.('分享与刷新设置已更新');
      setEditingId(null);
      return;
    }

    const newShare = {
      id: Math.random().toString(36).substr(2, 6),
      scope, mode,
      version: mode === 'snapshot' ? currentVersion : '最新版',
      time: '刚刚', creator: '我 (haoxingjun)',
      members: selectedMembers,
      link: `https://workspace.app/share/d-${Math.random().toString(36).substr(2, 6)}`,
      status: 'active',
      refreshType, cronExpr, timezone, startTime, delayTol, retries, allowOld,
      deliveryMode, deliveryFormat, deliveryChannel, deliveryRecipients,
      lastRefresh: refreshType !== 'manual' ? '无' : null,
      nextRefresh: refreshType !== 'manual' ? getNextRefresh() : null
    };
    setShares([newShare, ...shares]);
    showToast?.(`已成功创建${scope === 'private' ? '私密' : scope === 'public' ? '公开' : '团队'}分享链接`);
    if(scope === 'private') { setSelectedMembers([]); }
  };

  const copyLink = (link: string) => {
    setIsCopied(true);
    showToast?.('链接已复制到剪贴板');
    setTimeout(() => setIsCopied(false), 2000);
  };

  const revokeShare = (id: string) => {
    const s = shares.find(x => x.id === id);
    const newShares = shares.filter(x => x.id !== id);
    setShares(newShares);
    showToast?.('已撤销该分享', () => setShares([...newShares, s!]));
  };

  const togglePause = (id: string) => {
    setShares(prev => prev.map(s => s.id === id ? { ...s, status: s.status === 'active' ? 'paused' : 'active' } : s));
    showToast?.('状态已更新');
  };

  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  
  const handleImmediateRefresh = (share: any) => {
    setRefreshingId(share.id);
    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
    
    // Add running record
    const recordId = Date.now().toString();
    const runningRecord = { id: recordId, time: timeStr, type: share.deliveryMode === 'after_refresh' ? '刷新并交付' : '独立刷新', status: 'running', duration: '-', recipients: share.deliveryRecipients || '-' };
    setDynamicHistory(prev => [runningRecord, ...prev]);

    setTimeout(() => {
      setRefreshingId(null);
      setShares(prev => prev.map(s => s.id === share.id ? { ...s, lastRefresh: '刚刚' } : s));
      
      setDynamicHistory(prev => prev.map(r => r.id === recordId ? { ...r, status: 'success', duration: '1.2s' } : r));
      
      showToast?.('立即运行成功，数据更新与交付已处理');
    }, 1500);
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 z-[100] flex items-center justify-center p-4 backdrop-blur-sm" onClick={(e) => { if(e.target === e.currentTarget) onClose(); }} role="dialog" aria-modal="true" aria-labelledby="share-modal-title">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-6xl overflow-hidden flex flex-col md:flex-row max-h-[90vh]">
        
        {/* Left Side: Create/Edit config */}
        <div className="flex-[1.2] flex flex-col min-w-0 border-r border-slate-200">
          <div className="flex justify-between items-center p-4 border-b border-slate-100 shrink-0">
            <h2 id="share-modal-title" className="text-lg font-semibold text-slate-900">{editingId ? '编辑分享与计划' : '分享与定时发布'}</h2>
            <button onClick={onClose} className="md:hidden p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded transition-colors outline-none focus:ring-2 focus:ring-slate-200"><X size={20} /></button>
          </div>
          
          <div className="flex space-x-1 border-b border-slate-100 px-4 pt-2 bg-slate-50 shrink-0 overflow-x-auto custom-scrollbar">
            {[
              { id: 'access', label: '访问权限', icon: Lock },
              { id: 'refresh', label: '数据刷新', icon: RefreshCw },
              { id: 'delivery', label: '定时交付', icon: Send },
              { id: 'history', label: '运行历史', icon: History }
            ].map(tab => (
              <button 
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={cn("px-4 py-2.5 text-sm font-medium border-b-2 flex items-center whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-blue-500", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}
              >
                <tab.icon size={16} className="mr-2" /> {tab.label}
              </button>
            ))}
          </div>
          
          <div className="p-5 md:p-6 overflow-y-auto flex-1 custom-scrollbar bg-white">
            {activeTab === 'access' && (
              <div className="space-y-6 animate-in fade-in">
                <div>
                  <h3 className="text-sm font-semibold text-slate-800 mb-3">目标受众 (访问范围)</h3>
                  <div className="space-y-2.5">
                    <button onClick={() => setScope('team')} className={cn("w-full flex items-center p-3 rounded-xl border text-left transition-all outline-none focus-visible:ring-2 focus-visible:ring-blue-500", scope === 'team' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}>
                      <div className={cn("w-10 h-10 rounded-full flex items-center justify-center mr-3 shrink-0", scope === 'team' ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500")}><Users size={18} /></div>
                      <div className="flex-1"><div className="text-sm font-medium text-slate-900">团队内公开</div><div className="text-xs text-slate-500 mt-0.5">所有团队成员均可通过链接访问</div></div>
                      {scope === 'team' && <Check size={18} className="text-blue-600 ml-2" />}
                    </button>
                    
                    <button onClick={() => setScope('public')} className={cn("w-full flex items-center p-3 rounded-xl border text-left transition-all outline-none focus-visible:ring-2 focus-visible:ring-blue-500", scope === 'public' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}>
                      <div className={cn("w-10 h-10 rounded-full flex items-center justify-center mr-3 shrink-0", scope === 'public' ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500")}><Globe size={18} /></div>
                      <div className="flex-1"><div className="text-sm font-medium text-slate-900">互联网公开</div><div className="text-xs text-slate-500 mt-0.5">任何人获得链接即可访问 (存在泄露风险)</div></div>
                      {scope === 'public' && <Check size={18} className="text-blue-600 ml-2" />}
                    </button>

                    {scope === 'public' && hasSensitivity && (
                      <div className="ml-14 bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700 flex items-start animate-in fade-in">
                        <ShieldAlert size={14} className="mr-2 shrink-0 mt-0.5" />
                        <div><span className="font-semibold block mb-0.5">安全门禁阻断</span>存在敏感数据引用，无法公开分享。</div>
                      </div>
                    )}
                    {scope === 'public' && !hasSensitivity && (
                      <div className="ml-14 flex items-center space-x-2 text-sm text-slate-700 animate-in fade-in">
                        <input type="checkbox" id="wmark" checked={watermark} onChange={e=>setWatermark(e.target.checked)} className="rounded text-blue-600 focus:ring-blue-500 cursor-pointer"/>
                        <label htmlFor="wmark" className="cursor-pointer select-none">强制添加可见水印以追踪泄露来源</label>
                      </div>
                    )}

                    <button onClick={() => setScope('private')} className={cn("w-full flex items-center p-3 rounded-xl border text-left transition-all outline-none focus-visible:ring-2 focus-visible:ring-blue-500", scope === 'private' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}>
                      <div className={cn("w-10 h-10 rounded-full flex items-center justify-center mr-3 shrink-0", scope === 'private' ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500")}><Lock size={18} /></div>
                      <div className="flex-1"><div className="text-sm font-medium text-slate-900">私密指定成员</div><div className="text-xs text-slate-500 mt-0.5">仅指定的团队成员可见</div></div>
                      {scope === 'private' && <Check size={18} className="text-blue-600 ml-2" />}
                    </button>

                    {scope === 'private' && (
                      <div className="ml-14 bg-slate-50 border border-slate-200 rounded-xl p-3 animate-in fade-in">
                        <div className="relative mb-3">
                          <Search size={14} className="absolute left-3 top-2.5 text-slate-400" />
                          <input type="text" placeholder="搜索团队成员..." value={searchMember} onChange={e=>setSearchMember(e.target.value)} className="w-full text-xs border border-slate-200 rounded-lg pl-8 pr-3 py-2 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-white" />
                        </div>
                        {searchMember && filteredMembers.length > 0 && (
                          <div className="mb-3 space-y-1">{filteredMembers.map(m => (
                            <div key={m.id} className="flex justify-between items-center bg-white border border-slate-200 p-2 rounded-md text-xs cursor-pointer hover:border-blue-300 transition-colors" onClick={() => { setSelectedMembers([...selectedMembers, m]); setSearchMember(''); }}><span>{m.name}</span><span className="text-blue-600 font-medium">添加</span></div>
                          ))}</div>
                        )}
                        <div className="flex flex-wrap gap-2">
                          {selectedMembers.map(m => (
                            <div key={m.id} className="flex items-center bg-blue-50 text-blue-700 border border-blue-200 px-2 py-1 rounded text-xs">{m.name}<button onClick={() => setSelectedMembers(selectedMembers.filter(sm=>sm.id!==m.id))} className="ml-1 text-blue-400 hover:text-blue-700 outline-none"><XCircle size={12}/></button></div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div>
                  <h3 className="text-sm font-semibold text-slate-800 mb-3">数据可见性模式</h3>
                  <div className="grid grid-cols-2 gap-3">
                    <button onClick={() => setMode('snapshot')} className={cn("p-4 rounded-xl border text-left transition-all outline-none focus-visible:ring-2 focus-visible:ring-blue-500", mode === 'snapshot' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}>
                      <div className="text-sm font-medium text-slate-900 mb-1">版本快照 (Snapshot)</div>
                      <div className="text-xs text-slate-500">数据锁定为生成分享时的历史状态。</div>
                    </button>
                    <button onClick={() => setMode('realtime')} className={cn("p-4 rounded-xl border text-left transition-all outline-none focus-visible:ring-2 focus-visible:ring-blue-500", mode === 'realtime' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}>
                      <div className="text-sm font-medium text-slate-900 mb-1">实时 / 自动刷新</div>
                      <div className="text-xs text-slate-500">访问者始终看到最新数据，支持定时更新。</div>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'refresh' && (
              <div className="space-y-6 animate-in fade-in">
                {mode === 'snapshot' ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center text-slate-500 bg-slate-50 rounded-xl border border-slate-200 border-dashed">
                    <History size={32} className="mb-3 text-slate-300"/>
                    <div className="text-sm font-medium text-slate-700 mb-1">当前为“快照模式”</div>
                    <div className="text-xs">数据已被锁定，不需要配置自动刷新。</div>
                    <button onClick={() => { setMode('realtime'); setActiveTab('refresh'); }} className="mt-4 text-xs bg-white border border-slate-200 px-3 py-1.5 rounded-lg shadow-sm font-medium text-blue-600 hover:bg-slate-50 outline-none focus:ring-2 focus:ring-slate-200 transition-colors">切换为实时更新模式</button>
                  </div>
                ) : (
                  <>
                    <div>
                      <label className="block text-sm font-semibold text-slate-800 mb-2">刷新频率 (Refresh Schedule)</label>
                      <select value={refreshType} onChange={e=>setRefreshType(e.target.value as any)} className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2.5 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-white">
                        <option value="manual">手动刷新</option><option value="hourly">每小时</option><option value="daily">每天</option><option value="weekly">每周</option><option value="cron">自定义 Cron</option>
                      </select>
                    </div>
                    {refreshType === 'cron' && (
                      <div className="animate-in slide-in-from-top-2">
                        <label className="block text-sm font-medium text-slate-700 mb-2">Cron 表达式</label>
                        <input type="text" value={cronExpr} onChange={e=>setCronExpr(e.target.value)} className="w-full text-sm font-mono border border-slate-300 rounded-lg px-3 py-2.5 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-white" />
                      </div>
                    )}
                    {refreshType !== 'manual' && (
                      <div className="grid grid-cols-2 gap-4 animate-in slide-in-from-top-2">
                        <div>
                          <label className="block text-xs font-medium text-slate-700 mb-1.5">时区 (Timezone)</label>
                          <select value={timezone} onChange={e=>setTimezone(e.target.value)} className="w-full text-xs border border-slate-300 rounded-lg px-2 py-2 outline-none focus:border-blue-500 bg-white">
                            <option>Asia/Shanghai (UTC+8)</option><option>UTC</option>
                          </select>
                        </div>
                        {['daily', 'weekly', 'cron'].includes(refreshType) && (
                          <div>
                            <label className="block text-xs font-medium text-slate-700 mb-1.5">运行时间</label>
                            <input type="time" value={startTime} onChange={e=>setStartTime(e.target.value)} className="w-full text-xs border border-slate-300 rounded-lg px-2 py-2 outline-none focus:border-blue-500 bg-white" />
                          </div>
                        )}
                        <div>
                          <label className="block text-xs font-medium text-slate-700 mb-1.5">失败重试 (Retries)</label>
                          <select value={retries} onChange={e=>setRetries(e.target.value)} className="w-full text-xs border border-slate-300 rounded-lg px-2 py-2 outline-none focus:border-blue-500 bg-white">
                            <option>不重试</option><option>3 次 (间隔 5 分钟)</option><option>5 次 (间隔 10 分钟)</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-700 mb-1.5">数据延迟容忍度</label>
                          <select value={delayTol} onChange={e=>setDelayTol(e.target.value)} className="w-full text-xs border border-slate-300 rounded-lg px-2 py-2 outline-none focus:border-blue-500 bg-white">
                            <option>不允许延迟 (立刻失败)</option><option>允许最多 30 分钟延迟</option>
                          </select>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {activeTab === 'delivery' && (
              <div className="space-y-6 animate-in fade-in">
                <div>
                  <h3 className="text-sm font-semibold text-slate-800 mb-3">交付触发条件 (Trigger)</h3>
                  <div className="flex gap-4">
                    <label className={cn("flex-1 p-3 border rounded-xl cursor-pointer transition-all", deliveryMode === 'after_refresh' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}>
                      <div className="flex items-center space-x-2 mb-1">
                        <input type="radio" checked={deliveryMode === 'after_refresh'} onChange={()=>setDeliveryMode('after_refresh')} className="text-blue-600 focus:ring-blue-500 cursor-pointer"/>
                        <span className="font-medium text-slate-900 text-sm">刷新成功后发送</span>
                      </div>
                      <div className="text-xs text-slate-500 ml-6 leading-relaxed">依赖数据刷新任务，仅当数据更新成功时投递。</div>
                    </label>
                    <label className={cn("flex-1 p-3 border rounded-xl cursor-pointer transition-all", deliveryMode === 'independent' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}>
                      <div className="flex items-center space-x-2 mb-1">
                        <input type="radio" checked={deliveryMode === 'independent'} onChange={()=>setDeliveryMode('independent')} className="text-blue-600 focus:ring-blue-500 cursor-pointer"/>
                        <span className="font-medium text-slate-900 text-sm">按独立时间发送</span>
                      </div>
                      <div className="text-xs text-slate-500 ml-6 leading-relaxed">指定固定时间发送，若刷新失败则可能发送过期数据。</div>
                    </label>
                  </div>
                  {deliveryMode === 'after_refresh' && (
                    <div className="mt-3 flex items-center space-x-2 text-sm text-slate-700 bg-amber-50 border border-amber-200 p-3 rounded-lg">
                      <input type="checkbox" id="allowold" checked={allowOld} onChange={e=>setAllowOld(e.target.checked)} className="rounded text-amber-600 focus:ring-amber-500 cursor-pointer"/>
                      <label htmlFor="allowold" className="cursor-pointer select-none">若多次重试后仍刷新失败，允许发送最近一次成功版本</label>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-semibold text-slate-800 mb-2">接收渠道</label>
                    <select value={deliveryChannel} onChange={e=>setDeliveryChannel(e.target.value)} className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2.5 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-white">
                      <option value="email">邮件 (Email)</option><option value="feishu">飞书机器人 (Lark)</option><option value="slack">Slack</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-800 mb-2">交付格式</label>
                    <select value={deliveryFormat} onChange={e=>setDeliveryFormat(e.target.value)} className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2.5 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-white">
                      <option value="html">交互式 HTML 链接</option><option value="pdf">静态 PDF 附件</option><option value="snapshot">长截图快照</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-semibold text-slate-800 mb-2">接收人 / 群组</label>
                  <input type="text" value={deliveryRecipients} onChange={e=>setDeliveryRecipients(e.target.value)} placeholder="输入邮箱地址或群组 ID，多项用逗号分隔" className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2.5 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-shadow bg-white" />
                </div>
              </div>
            )}

            {activeTab === 'history' && (
              <div className="h-full flex flex-col">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-sm font-semibold text-slate-800">刷新与交付历史</h3>
                  <button className="text-xs text-slate-500 hover:text-slate-800 border border-slate-200 px-2 py-1 rounded bg-white outline-none shadow-sm transition-colors focus:ring-2 focus:ring-slate-300">导出日志</button>
                </div>
                <table className="w-full text-left text-sm whitespace-nowrap min-w-[600px] border border-slate-200 rounded-lg overflow-hidden">
                  <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                    <tr><th className="px-4 py-3 font-medium">执行时间</th><th className="px-4 py-3 font-medium">类型</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">耗时</th><th className="px-4 py-3 font-medium">接收人</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {dynamicHistory.map((rec: any) => (
                      <tr key={rec.id} className="hover:bg-slate-50 bg-white transition-colors">
                        <td className="px-4 py-3 text-slate-800 font-mono text-xs">{rec.time}</td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{rec.type}</td>
                        <td className="px-4 py-3">
                          {rec.status === 'running' && <span className="text-blue-700 bg-blue-50 px-2 py-0.5 rounded text-xs border border-blue-200 flex items-center w-fit"><Loader2 size={12} className="mr-1 animate-spin"/> 运行中</span>}
                          {rec.status === 'success' && <span className="text-green-700 bg-green-50 px-2 py-0.5 rounded text-xs border border-green-200 flex items-center w-fit"><CheckCircle2 size={12} className="mr-1"/> 成功</span>}
                          {rec.status === 'fail' && <span className="text-red-700 bg-red-50 px-2 py-0.5 rounded text-xs border border-red-200 flex items-center w-fit"><XCircle size={12} className="mr-1"/> 失败</span>}
                        </td>
                        <td className="px-4 py-3 text-slate-500 font-mono text-xs">{rec.duration}</td>
                        <td className="px-4 py-3 text-slate-500 text-xs truncate max-w-[150px]" title={rec.recipients}>{rec.recipients}</td>
                      </tr>
                    ))}
                    <tr className="hover:bg-slate-50 bg-white transition-colors">
                      <td className="px-4 py-3 text-slate-800 font-mono text-xs">昨天 09:00:00</td><td className="px-4 py-3 text-slate-500 text-xs">计划刷新+交付</td><td className="px-4 py-3"><span className="text-amber-700 bg-amber-50 px-2 py-0.5 rounded text-xs border border-amber-200 flex items-center w-fit"><ShieldAlert size={12} className="mr-1"/> 重试成功(2)</span></td><td className="px-4 py-3 text-slate-500 font-mono text-xs">18.5s</td><td className="px-4 py-3 text-slate-500 text-xs truncate max-w-[150px]">data-team@company.com</td>
                    </tr>
                    <tr className="hover:bg-slate-50 bg-white transition-colors">
                      <td className="px-4 py-3 text-slate-800 font-mono text-xs">2天前 09:00:00</td><td className="px-4 py-3 text-slate-500 text-xs">计划刷新</td><td className="px-4 py-3"><span className="text-red-700 bg-red-50 px-2 py-0.5 rounded text-xs border border-red-200 flex items-center w-fit"><XCircle size={12} className="mr-1"/> 超时失败</span></td><td className="px-4 py-3 text-slate-500 font-mono text-xs">-</td><td className="px-4 py-3 text-slate-500 text-xs">-</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>
          
          <div className="p-4 md:p-5 border-t border-slate-100 bg-slate-50 flex justify-end shrink-0 gap-3">
            <button onClick={handleCreate} className="px-6 py-2.5 bg-slate-800 hover:bg-slate-900 text-white rounded-xl text-sm font-medium transition-colors shadow-sm outline-none focus:ring-2 focus:ring-slate-500">保存当前配置</button>
            <button onClick={onClose} className="px-4 py-2.5 bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 rounded-xl text-sm font-medium transition-colors shadow-sm outline-none focus:ring-2 focus:ring-slate-300">完成并关闭</button>
          </div>
        </div>

        {/* Right Side: Created Shares List */}
        <div className="flex-1 bg-slate-50 border-t md:border-t-0 border-slate-200 flex flex-col shrink-0 min-h-[400px] md:min-h-0 min-w-0">
          <div className="flex justify-between items-center p-4 md:p-5 border-b border-slate-200 shrink-0 bg-white/50">
            <h3 className="text-sm font-semibold text-slate-800">已创建的分享与任务 ({shares.length})</h3>
            <button onClick={onClose} className="hidden md:block p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded transition-colors outline-none focus:ring-2 focus:ring-slate-200"><X size={20} /></button>
          </div>
          
          <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
            {shares.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center text-slate-400 h-full py-10">
                <LinkIcon size={32} className="mb-3 opacity-50" />
                <p className="text-sm">暂无分享与调度任务<br/>在左侧配置并创建</p>
              </div>
            ) : (
              <div className="space-y-4">
                {shares.map(share => (
                  <div key={share.id} className={cn("bg-white border rounded-xl p-4 shadow-sm relative group transition-colors", share.status === 'paused' ? "border-slate-200 opacity-80" : "border-slate-200 hover:border-blue-300")}>
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium border", share.scope === 'team' ? "bg-blue-50 text-blue-700 border-blue-200" : share.scope === 'public' ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-purple-50 text-purple-700 border-purple-200")}>
                          {share.scope === 'team' ? '团队可见' : share.scope === 'public' ? '公开' : '私密'}
                        </span>
                        {share.mode === 'realtime' && <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-600 border border-blue-200">定时 {share.refreshType}</span>}
                        {share.status === 'paused' && <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">已暂停</span>}
                      </div>
                      <div className="flex items-center space-x-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={() => { startEdit(share); setActiveTab('access'); }} className="p-1 text-slate-400 hover:text-blue-600 rounded hover:bg-blue-50 outline-none" title="编辑分享"><Edit3 size={14} /></button>
                        {share.mode === 'realtime' && (
                          <button onClick={() => togglePause(share.id)} className="p-1 text-slate-400 hover:text-amber-600 rounded hover:bg-amber-50 outline-none" title={share.status === 'active' ? "暂停自动刷新" : "恢复刷新"}>{share.status === 'active' ? <Pause size={14} /> : <Play size={14} />}</button>
                        )}
                        <button onClick={() => revokeShare(share.id)} className="p-1 text-slate-400 hover:text-red-600 rounded hover:bg-red-50 outline-none" title="撤销该分享"><Trash2 size={14} /></button>
                      </div>
                    </div>
                    
                    <div className="flex items-center text-xs text-slate-500 mb-2 space-x-3">
                      <span className="flex items-center"><Clock size={12} className="mr-1" /> {share.time}</span>
                      <span className="truncate flex-1">创建人: {share.creator}</span>
                    </div>

                    {share.mode === 'realtime' && (
                      <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100 text-xs mb-3 space-y-2">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500 font-mono">{share.refreshType === 'cron' ? (share.cronExpr === '*/5 * * * *' ? '每 5 分钟' : share.cronExpr === '*/10 * * * *' ? '每 10 分钟' : share.cronExpr) : share.refreshType} ({share.timezone?.split(' ')[0]})</span>
                          <span className="font-medium text-slate-700 flex items-center">
                            {refreshingId === share.id ? <><Loader2 size={12} className="animate-spin mr-1 text-blue-500" /> 运行中...</> : `下次: ${share.nextRefresh}`}
                          </span>
                        </div>
                        <div className="flex justify-between items-center pt-1 border-t border-slate-200/60">
                           <span className="text-slate-500 truncate max-w-[120px]" title={share.deliveryRecipients}>投递: {share.deliveryRecipients || '未配置'}</span>
                           <button onClick={() => handleImmediateRefresh(share)} disabled={refreshingId === share.id} className="text-[11px] text-blue-600 font-medium hover:underline disabled:opacity-50 flex items-center outline-none focus:ring-1 focus:ring-blue-500 rounded"><Play size={10} className="mr-1"/>立即执行</button>
                        </div>
                      </div>
                    )}

                    <div className="flex space-x-2 mt-2">
                      <input type="text" aria-label="分享链接" readOnly value={share.link} className="flex-1 bg-slate-50 border border-slate-200 rounded-md px-2 py-1.5 text-xs text-slate-600 outline-none" />
                      <button onClick={() => copyLink(share.link)} className="bg-slate-800 hover:bg-slate-900 text-white px-3 py-1.5 rounded-md flex items-center text-xs font-medium transition-colors outline-none focus:ring-2 focus:ring-slate-400 shadow-sm">
                        {isCopied ? <Check size={14} /> : <Copy size={14} />}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}