import React, { useState, useEffect } from 'react';
import { X, Clock, BellRing, Play, Pause, Save, CheckCircle2, History, AlertTriangle, MessageSquare, Send, Plus } from 'lucide-react';
import { cn } from '../../lib/utils';
import { resourceStore } from '../../lib/store';

export default function AlertModal({ onClose, showToast, searchParams, setSearchParams }: any) {
  const [activeTab, setActiveTab] = useState('alert');
  const [freq, setFreq] = useState('1');
  const metricName = searchParams.get('alert_metric') || '通用业务指标';
  const fileId = searchParams.get('file') || '';
  
  const [alertConfig, setAlertConfig] = useState({
    metric: metricName,
    operator: '<',
    threshold: '-5.0',
    duration: '持续 5 分钟',
    silence: '1 小时',
    channels: ['feishu']
  });

  const [alerts, setAlerts] = useState<any[]>(() => {
    return resourceStore.getState().filter((r:any) => r.resourceKind === 'automation' && r.subtype === 'alert_rule' && r.lineage?.sourceIds?.includes(fileId));
  });

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const handleSave = () => {
    const newAlertId = `automation_alert_${Date.now()}`;
    const newAlert = {
      id: newAlertId,
      displayName: `告警规则: ${alertConfig.metric}`,
      resourceKind: 'automation',
      subtype: 'alert_rule',
      space: 'personal',
      owner: 'haoxingjun',
      version: 'V1.0',
      lifecycle: 'published',
      permission: true,
      capabilities: ['executable'],
      lineage: { sourceIds: [fileId] },
      createdAt: '刚刚',
      updatedAt: '刚刚',
      configRef: {
        metric: alertConfig.metric,
        operator: alertConfig.operator,
        threshold: alertConfig.threshold,
        duration: alertConfig.duration,
        freq: freq,
        status: 'active',
        channels: alertConfig.channels,
        runHistory: [
          { time: '刚刚', status: 'created', input: '-', message: '规则创建成功' }
        ]
      },
      name: `告警规则: ${alertConfig.metric}`,
      type: 'automation'
    };
    
    resourceStore.setState(prev => [newAlert as any, ...prev]);
    showToast?.('通用告警规则 (AlertRule) 已创建并启用');

    const p = new URLSearchParams(searchParams);
    p.delete('modal');
    p.delete('alert_metric');
    setSearchParams(p);
  };

  const handleTestRun = () => {
    showToast?.('测试告警执行中...');
    setTimeout(() => {
      setAlerts(prev => prev.map((a:any, i:number) => i === 0 ? {
        ...a,
        configRef: {
          ...a.configRef,
          runHistory: [
            { time: '刚刚', status: 'success', input: `${alertConfig.metric} 当前值超出阈值`, message: '测试告警发送成功 (飞书)' },
            ...a.configRef.runHistory
          ]
        }
      } : a));
      showToast?.('测试告警发送成功，请查收飞书/邮件通知。');
    }, 1500);
  };

  return (
    <div className="fixed inset-0 bg-slate-900/40 z-50 flex items-center justify-center p-4 backdrop-blur-sm" onClick={(e) => { if(e.target===e.currentTarget) onClose(); }} role="dialog">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl overflow-hidden flex flex-col animate-in zoom-in-95">
        <div className="flex justify-between items-center p-5 border-b border-slate-100 bg-slate-50 shrink-0">
          <h2 className="text-lg font-bold text-slate-900 flex items-center"><BellRing size={20} className="mr-2 text-blue-600"/> 刷新与告警规则</h2>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded transition-colors outline-none"><X size={20} /></button>
        </div>

        <div className="flex space-x-1 border-b border-slate-100 px-4 pt-2 bg-slate-50 shrink-0">
          <button onClick={() => setActiveTab('alert')} className={cn("px-4 py-2.5 text-sm font-bold border-b-2 flex items-center transition-colors outline-none", activeTab === 'alert' ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}>
             <AlertTriangle size={16} className="mr-2" /> 通用告警规则配置
          </button>
          <button onClick={() => setActiveTab('history')} className={cn("px-4 py-2.5 text-sm font-bold border-b-2 flex items-center transition-colors outline-none", activeTab === 'history' ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}>
             <History size={16} className="mr-2" /> 运行与触发历史
          </button>
        </div>

        <div className="p-6 overflow-y-auto max-h-[60vh] custom-scrollbar bg-white">
          {activeTab === 'alert' && (
             <div className="space-y-6 animate-in slide-in-from-right-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="col-span-2">
                    <label className="block text-sm font-bold text-slate-800 mb-2">监控指标 (Metric)</label>
                    <input type="text" value={alertConfig.metric} onChange={e=>setAlertConfig(p=>({...p, metric: e.target.value}))} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 bg-white" />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">触发操作符</label>
                    <select value={alertConfig.operator} onChange={e=>setAlertConfig(p=>({...p, operator: e.target.value}))} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-blue-500 bg-white">
                      <option value="<">低于 (Less than)</option>
                      <option value=">">高于 (Greater than)</option>
                      <option value="==">等于 (Equals to)</option>
                      <option value="变动>">增幅大于 (Increase over)</option>
                      <option value="变动<">跌幅大于 (Decrease over)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">阈值 (Threshold)</label>
                    <input type="text" value={alertConfig.threshold} onChange={e=>setAlertConfig(p=>({...p, threshold: e.target.value}))} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 bg-white font-mono" />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 border-t border-slate-100 pt-6">
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">检查频率 (Check Frequency)</label>
                    <select value={freq} onChange={e=>setFreq(e.target.value)} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-blue-500 bg-white">
                      <option value="1">分钟级实时 (每 1 分钟)</option>
                      <option value="5">每 5 分钟</option>
                      <option value="60">每小时</option>
                      <option value="1440">每天</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">持续窗口 (Duration)</label>
                    <select value={alertConfig.duration} onChange={e=>setAlertConfig(p=>({...p, duration: e.target.value}))} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-blue-500 bg-white">
                      <option>持续 1 分钟 (立即触发)</option>
                      <option>持续 5 分钟</option>
                      <option>持续 1 小时</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">静默期 (Silence Period)</label>
                    <select value={alertConfig.silence} onChange={e=>setAlertConfig(p=>({...p, silence: e.target.value}))} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-blue-500 bg-white">
                      <option>1 小时 (不再重复发送)</option>
                      <option>24 小时</option>
                      <option>不静默 (每次均发送)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-slate-800 mb-2">通知渠道 (Channels)</label>
                    <div className="flex gap-2 h-11 items-center">
                      <label className="flex items-center text-sm font-medium text-slate-700 cursor-pointer">
                        <input type="checkbox" checked={alertConfig.channels.includes('feishu')} onChange={e => {
                          const c = e.target.checked ? [...alertConfig.channels, 'feishu'] : alertConfig.channels.filter(x=>x!=='feishu');
                          setAlertConfig(p => ({...p, channels: c}));
                        }} className="mr-1.5 rounded text-blue-600 focus:ring-blue-500" /> 飞书
                      </label>
                      <label className="flex items-center text-sm font-medium text-slate-700 cursor-pointer">
                        <input type="checkbox" checked={alertConfig.channels.includes('email')} onChange={e => {
                          const c = e.target.checked ? [...alertConfig.channels, 'email'] : alertConfig.channels.filter(x=>x!=='email');
                          setAlertConfig(p => ({...p, channels: c}));
                        }} className="mr-1.5 rounded text-blue-600 focus:ring-blue-500" /> 邮件
                      </label>
                    </div>
                  </div>
                </div>

                <div className="bg-slate-50 border border-slate-200 p-4 rounded-xl shadow-inner mt-4">
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="text-sm font-bold text-slate-800 flex items-center">规则预览与测试</h4>
                    <button onClick={handleTestRun} className="text-xs bg-white border border-blue-200 text-blue-700 font-bold px-3 py-1.5 rounded-lg shadow-sm outline-none flex items-center hover:bg-blue-50"><Send size={12} className="mr-1"/>测试发送并记录历史</button>
                  </div>
                  <div className="text-sm font-mono text-slate-700">
                    WHEN <span className="font-bold text-blue-700">[{alertConfig.metric}]</span> {alertConfig.operator} <span className="font-bold text-blue-700">{alertConfig.threshold}%</span> FOR {alertConfig.duration}
                  </div>
                  <div className="text-xs text-slate-500 mt-2">频率: {freq === '1' ? '每分钟' : `每 ${freq} 分钟`} | 渠道: {alertConfig.channels.join(', ')}</div>
                </div>
             </div>
          )}
          
          {activeTab === 'history' && (
            <div className="space-y-4 animate-in slide-in-from-right-4">
              {alerts.length === 0 ? (
                <div className="text-center py-10 text-slate-500">
                  <History size={32} className="mx-auto mb-3 opacity-50" />
                  <p className="text-sm">暂无活跃的告警规则或触发历史</p>
                </div>
              ) : (
                alerts.map((al:any) => (
                  <div key={al.id} className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm">
                    <div className="flex justify-between items-center mb-2">
                      <div className="font-bold text-slate-800 text-sm flex items-center">
                        <span className="w-2.5 h-2.5 rounded-full bg-green-500 mr-2"></span> {al.configRef?.metric}
                      </div>
                      <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs border border-slate-200">{al.configRef?.status === 'active' ? '运行中' : '已停用'}</span>
                    </div>
                    <div className="text-xs font-mono text-slate-600 mb-3 bg-slate-50 p-2 rounded">
                      {al.configRef?.metric} {al.configRef?.operator} {al.configRef?.threshold}% | {al.configRef?.duration}
                    </div>
                    <div className="border border-slate-100 rounded-lg overflow-hidden">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-slate-50 text-slate-500">
                          <tr><th className="px-3 py-2 font-medium">执行时间</th><th className="px-3 py-2 font-medium">状态</th><th className="px-3 py-2 font-medium">输入/摘要</th></tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {al.configRef?.runHistory?.map((h:any, i:number) => (
                            <tr key={i} className="hover:bg-slate-50">
                              <td className="px-3 py-2 font-mono text-slate-500">{h.time}</td>
                              <td className="px-3 py-2">
                                {h.status === 'created' && <span className="text-blue-600 font-medium">创建</span>}
                                {h.status === 'success' && <span className="text-green-600 font-medium flex items-center"><CheckCircle2 size={12} className="mr-1"/> 触发</span>}
                                {h.status === 'fail' && <span className="text-red-600 font-medium flex items-center"><AlertTriangle size={12} className="mr-1"/> 失败</span>}
                              </td>
                              <td className="px-3 py-2 text-slate-600 truncate max-w-[200px]" title={h.message}>{h.message}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        <div className="p-5 border-t border-slate-100 bg-slate-50 flex justify-end space-x-3 shrink-0">
          <button onClick={onClose} className="px-5 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 shadow-sm outline-none">取消</button>
          <button onClick={handleSave} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 shadow-md flex items-center outline-none focus:ring-2 focus:ring-blue-500"><Save size={16} className="mr-1.5"/>保存设置</button>
        </div>
      </div>
    </div>
  );
}