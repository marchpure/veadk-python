import React, { useEffect, useState } from 'react';
import ArtifactHeader from './ArtifactHeader';
import { Book, CheckCircle2, Search, MessageSquare, ShieldCheck, Settings, Link as LinkIcon, Users, Play, ToyBrick, FileText, Send, Loader2, ArrowRight, Plus } from 'lucide-react';
import { cn } from '../../lib/utils';
import { askKnowledgeBase, getKnowledgeBase, getKnowledgeQueryResult, publishKnowledgeBase, DomainRequestError } from '../../../production/domainClient';

export default function KnowledgeBaseView({ fileId, isTeam, searchParams, setSearchParams, showToast }: any) {
  const [resource, setResource] = useState<any>(null);
  const [loadError, setLoadError] = useState('');
  useEffect(() => {
    void getKnowledgeBase(fileId).then(setResource).catch((error) => {
      setLoadError(error instanceof DomainRequestError ? error.message : "知识库读取失败");
    });
  }, [fileId]);

  const name = resource?.name || searchParams.get('custom_name') || '销售制度知识库';
  const version = resource?.version || 'V1.0';
  const sources = resource?.sources || [];
  
  const [activeTab, setActiveTab] = useState('sources');
  const [query, setQuery] = useState('');
  const [qaState, setQaState] = useState<'idle'|'thinking'|'done'>('idle');
  
  const [publishState, setPublishState] = useState<'idle'|'publishing'|'done'>('idle');
  const [agentBound, setAgentBound] = useState(false);

  const [answer, setAnswer] = useState<any>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const queryResultId = searchParams.get('query_result_id');
    if (!queryResultId) return;
    let active = true;
    void getKnowledgeQueryResult(fileId, queryResultId).then((result) => {
      if (active) {
        setAnswer(result);
        setQuery(String(result.question || ''));
        setQaState('done');
        setActiveTab('qa');
      }
    }).catch((cause) => {
      if (active) setError(cause instanceof DomainRequestError ? cause.message : "问答结果读取失败");
    });
    return () => { active = false; };
  }, [fileId, searchParams]);
  const handleTestQA = async () => {
    if (!query.trim()) return;
    setQaState('thinking');
    setError('');
    try {
      const result = await askKnowledgeBase(fileId, { question: query, topK: 5 });
      setAnswer(result);
      setQaState('done');
      setActiveTab('qa');
      const next = new URLSearchParams(searchParams);
      next.set('query_result_id', String(result.queryResultId || ''));
      next.set('kb_tab', 'qa');
      setSearchParams(next);
    } catch (cause) {
      setQaState('idle');
      setError(cause instanceof DomainRequestError ? cause.message : "知识库问答失败");
    }
  };

  const performKnowledgeBasePublication = async () => {
    setPublishState('publishing');
    try {
      await publishKnowledgeBase(fileId);
      setPublishState('done');
      showToast?.('已发送请求，等待状态刷新。');
    } catch (cause) {
      setPublishState('idle');
      setError(cause instanceof DomainRequestError ? cause.message : "发布失败");
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto w-full flex flex-col h-full min-w-0 animate-in fade-in duration-300 relative">
      <ArtifactHeader 
        title={name} 
        typeLabel="Knowledge Base"
        isTeam={isTeam} 
        version={version} 
        searchParams={searchParams}
        setSearchParams={setSearchParams}
        showToast={showToast}
      />
      {loadError && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{loadError}</div>}
      
      <div className="flex space-x-6 border-b border-slate-200 mt-2 mb-6 overflow-x-auto custom-scrollbar shrink-0">
        {[
          { id: 'sources', label: '来源管理' },
          { id: 'retrieval', label: '切片与检索' },
          { id: 'qa', label: '测试问答' }
        ].map(tab => (
          <button 
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn("pb-3 text-sm font-bold transition-colors border-b-2 whitespace-nowrap outline-none", activeTab === tab.id ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 bg-white border border-slate-200 rounded-[12px] overflow-hidden flex flex-col min-h-[500px]">
        {activeTab === 'sources' && (
          <div className="flex-1 flex flex-col">
            <div className="p-5 border-b border-slate-200 bg-slate-50 flex justify-between items-center shrink-0">
              <h3 className="font-bold text-slate-800">已接入来源 ({sources.length})</h3>
              {!isTeam && <button className="bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-bold shadow-sm outline-none hover:bg-slate-50 transition-colors">继续添加</button>}
            </div>
            <div className="flex-1 overflow-auto p-0 custom-scrollbar">
              <table className="w-full text-sm text-left whitespace-nowrap min-w-[700px]">
                <thead className="bg-slate-50 text-slate-500 border-b border-slate-200 font-medium">
                  <tr><th className="px-6 py-4">来源名称</th><th className="px-6 py-4">类型</th><th className="px-6 py-4">解析状态</th><th className="px-6 py-4">分段数</th><th className="px-6 py-4">最近同步</th><th className="px-6 py-4">权限</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sources.map((s:any, i:number) => (
                    <tr key={i} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-4 font-bold text-slate-800 flex items-center">
                        {s.type === 'local' ? <FileText size={16} className="mr-2 text-slate-400" /> : <LinkIcon size={16} className="mr-2 text-blue-500" />}
                        {s.name}
                      </td>
                      <td className="px-6 py-4 text-slate-500">{s.type === 'feishu' ? '飞书文档' : (s.mediaType || '本地文件')}</td>
                      <td className="px-6 py-4"><span className="bg-green-50 text-green-700 border border-green-200 px-2 py-1 rounded text-xs font-bold flex items-center w-fit"><CheckCircle2 size={12} className="mr-1"/>成功</span></td>
                      <td className="px-6 py-4 font-mono text-slate-600">{s.index?.chunkCount ?? s.chunks ?? 0}</td>
                      <td className="px-6 py-4 text-slate-500">{s.createdAt || s.time || '—'}</td>
                      <td className="px-6 py-4 text-slate-500 flex items-center"><ShieldCheck size={14} className="mr-1 text-slate-400"/> 继承</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'qa' && (
          <div className="flex-1 flex flex-col h-full bg-slate-50/50">
            <div className="flex-1 overflow-auto p-6 space-y-6 custom-scrollbar">
              {qaState !== 'idle' && (
                <div className="flex flex-row-reverse items-start gap-4 animate-in fade-in">
                  <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white shrink-0 font-bold">U</div>
                  <div className="bg-blue-600 text-white rounded-2xl rounded-tr-sm px-5 py-3.5 text-sm shadow-sm max-w-[80%]">{query}</div>
                </div>
              )}
              {qaState === 'thinking' && (
                <div className="flex items-start gap-4 animate-in fade-in">
                  <div className="w-8 h-8 rounded-full bg-white border border-slate-200 flex items-center justify-center text-blue-600 shrink-0 shadow-sm"><Search size={16}/></div>
                  <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm p-4 text-sm text-slate-600 shadow-sm flex items-center">
                    <Loader2 size={16} className="animate-spin mr-2 text-blue-600"/> 检索知识库并生成回答...
                  </div>
                </div>
              )}
              {qaState === 'done' && (
                <div className="flex items-start gap-4 animate-in fade-in">
                  <div className="w-8 h-8 rounded-full bg-white border border-slate-200 flex items-center justify-center text-blue-600 shrink-0 shadow-sm"><MessageSquare size={16}/></div>
                  <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm p-5 text-sm text-slate-800 shadow-sm max-w-[85%] leading-relaxed space-y-4">
                    <p className="whitespace-pre-wrap">{String(answer?.answer ?? '')}</p>
                    <div className="text-[11px] text-slate-500">
                      queryResultId: <span className="font-mono">{String(answer?.queryResultId || '—')}</span>
                      {' · '}session: <span className="font-mono">{String(answer?.sessionId || '—')}</span>
                      {' · '}trace: <span className="font-mono">{String(answer?.traceId || '—')}</span>
                    </div>
                    <div className="mt-4 pt-4 border-t border-slate-100">
                      <div className="text-xs font-bold text-slate-500 mb-2">引用的文档来源 (Citations)</div>
                      <div className="flex gap-2 overflow-x-auto custom-scrollbar pb-2">
                        {(Array.isArray(answer?.citations) ? answer.citations : []).map((citation: any, index: number) => (
                          <div key={citation.id ?? index} className="bg-slate-50 border border-slate-200 p-2 rounded-lg min-w-[200px] shrink-0">
                            <div className="text-xs font-bold text-blue-700 mb-1 flex items-center"><span className="bg-blue-100 text-blue-800 w-4 h-4 rounded flex items-center justify-center mr-1 text-[10px]">{index + 1}</span> {citation.title}</div>
                            <div className="text-[11px] text-slate-600 line-clamp-2">{citation.snippet}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="p-4 bg-white border-t border-slate-200 shrink-0">
              {error && <div role="alert" className="mb-2 text-xs text-red-700">{error}</div>}
              <div className="flex items-center bg-slate-50 border border-slate-300 rounded-xl px-2 py-2 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500 transition-all shadow-sm">
                <input type="text" value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter') handleTestQA()}} placeholder="输入测试问题，如：退货审批需要什么材料？" className="flex-1 bg-transparent border-none outline-none px-3 text-sm" />
                <button onClick={handleTestQA} disabled={!query || qaState === 'thinking'} className="bg-blue-600 text-white p-2 rounded-lg disabled:opacity-50 hover:bg-blue-700 shadow-sm outline-none"><Send size={16}/></button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'publish' && (
          <div className="flex-1 p-6 md:p-10 flex justify-center bg-slate-50/50 overflow-y-auto custom-scrollbar">
            <div className="max-w-2xl w-full">
              {!isTeam ? (
                <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm text-center">
                  <div className="w-16 h-16 bg-blue-50 text-blue-600 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-sm border border-blue-100"><ToyBrick size={32}/></div>
                  <h3 className="text-xl font-bold text-slate-900 mb-2">发布为 Agent 知识资产 (Knowledge Tool)</h3>
                  <p className="text-slate-500 text-sm mb-8 max-w-md mx-auto leading-relaxed">
                    发布后，该知识库将被封装为标准的 Tool，团队内的 Agent 可以配置并调用此知识库进行精准问答。
                  </p>
                  
                  <div className="text-left bg-slate-50 border border-slate-200 rounded-xl p-6 space-y-5 mb-8">
                    <div>
                      <label className="block text-sm font-bold text-slate-800 mb-1.5">Tool ID (调用名称)</label>
                      <input type="text" defaultValue={`knowledge_tool_${resource?.id?.substring(0,6) || 'generic'}`} className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm font-mono outline-none focus:border-blue-500 shadow-sm" />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-slate-800 mb-1.5">更新策略</label>
                      <select className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none bg-white shadow-sm focus:border-blue-500 font-medium">
                        <option>与个人草稿自动同步 (实时)</option>
                        <option>手动发布快照</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-slate-800 mb-1.5">允许调用的团队 / 空间</label>
                      <select className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none bg-white shadow-sm focus:border-blue-500 font-medium">
                        <option>整个团队公开可见</option>
                        <option>仅指定 Agent ID</option>
                      </select>
                    </div>
                  </div>

                  <button onClick={performKnowledgeBasePublication} disabled={publishState !== 'idle'} className="bg-blue-600 text-white px-8 py-3 rounded-xl text-sm font-bold shadow-md hover:bg-blue-700 disabled:opacity-50 transition-colors inline-flex items-center outline-none focus:ring-2 focus:ring-blue-500">
                    {publishState === 'publishing' ? <><Loader2 size={18} className="animate-spin mr-2"/> 发布中...</> : '确认发布'}
                  </button>
                </div>
              ) : (
                <div className="space-y-6">
                  <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
                    <div className="flex justify-between items-start mb-6">
                      <div>
                        <h3 className="text-lg font-bold text-slate-900 flex items-center mb-2"><CheckCircle2 size={20} className="text-green-500 mr-2"/> 已发布版本 (V1.0)</h3>
                        <p className="text-sm text-slate-500">此资产可被团队内有权限的 Agent 绑定调用。</p>
                      </div>
                      <span className="bg-slate-100 text-slate-600 font-mono text-xs px-3 py-1.5 rounded-lg border border-slate-200 shadow-sm">Tool ID: {resource?.configRef?.toolId || `knowledge_tool_${resource?.id?.substring(0, 6)}`}</span>
                    </div>

                    <div className="bg-slate-900 rounded-xl p-5 font-mono text-xs text-green-400 overflow-x-auto shadow-inner mb-6">
                      <div className="text-slate-400 mb-2">// 输入 / 输出契约与调用示例</div>
                      <div>{"{"}</div>
                      <div className="pl-4">"query": "string (需要检索的问题)",</div>
                      <div className="pl-4">"top_k": "number (返回的最相关片段数，默认 3)"</div>
                      <div>{"}"}</div>
                    </div>

                    <div className="border-t border-slate-100 pt-6">
                      <h4 className="font-bold text-slate-800 mb-4 text-sm">绑定状态</h4>
                      {agentBound ? (
                        <div className="bg-green-50 border border-green-200 rounded-xl p-4 flex justify-between items-center">
                          <div className="flex items-center text-sm font-bold text-green-800">
                            <ToyBrick size={18} className="mr-2 text-green-600"/> 已向销售分析 Agent 暴露
                          </div>
                          <button onClick={() => { setAgentBound(false); showToast?.('已撤销授权'); }} className="text-xs font-bold text-slate-500 hover:text-red-600 bg-white border border-slate-200 px-3 py-1.5 rounded-lg shadow-sm outline-none transition-colors">撤销授权</button>
                        </div>
                      ) : (
                        <button onClick={() => { setAgentBound(true); showToast?.('授权成功！已绑定至 销售分析 Agent'); }} className="w-full bg-white border border-blue-200 text-blue-700 hover:bg-blue-50 px-4 py-3 rounded-xl text-sm font-bold shadow-sm transition-colors flex items-center justify-center outline-none focus:ring-2 focus:ring-blue-500">
                          <Plus size={18} className="mr-2"/> 添加到 Agent
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
        
        {activeTab === 'retrieval' && (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 bg-slate-50/50">
            <Search size={32} className="mb-4 opacity-50"/>
            <span className="text-sm font-medium">切片详情与向量检索调试界面</span>
            <span className="text-xs mt-2">切换到“测试问答”可运行服务端检索。</span>
          </div>
        )}
      </div>
    </div>
  );
}
