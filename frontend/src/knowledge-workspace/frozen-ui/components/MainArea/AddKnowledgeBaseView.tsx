import React, { useState } from 'react';
import { ArrowLeft, Upload, FileText, Link as LinkIcon, CheckCircle2, Loader2, Database, Search, ShieldCheck, XCircle } from 'lucide-react';
import { cn } from '../../lib/utils';
import {
  createKnowledgeBase,
  inspectFeishu,
  syncFeishu,
  uploadKnowledgeSource,
  DomainRequestError,
} from '../../../production/domainClient';

export default function AddKnowledgeBaseView({ searchParams, setSearchParams, showToast }: any) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState('销售制度知识库');
  const [desc, setDesc] = useState('聚合各渠道的销售制度与流程规范');
  
  const [sources, setSources] = useState<any[]>([]);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState<string>("");
  
  const [activeTab, setActiveTab] = useState('local');
  const [uploadState, setUploadState] = useState<'idle'|'uploading'|'done'>('idle');
  
  const [feishuUrl, setFeishuUrl] = useState('');
  const [feishuState, setFeishuState] = useState<'idle'|'checking'|'ready'|'syncing'|'done'|'blocked'|'error'>('idle');
  const [feishuDocument, setFeishuDocument] = useState<any>(null);

  const ensureKnowledgeBase = async () => {
    if (knowledgeBaseId) return knowledgeBaseId;
    const created = await createKnowledgeBase({ name, description: desc, scope: "personal" });
    const createdId = String(created.knowledgeBase?.id ?? created.id ?? "");
    if (!createdId) throw new Error("服务端未返回知识库 ID");
    setKnowledgeBaseId(createdId);
    return createdId;
  };

  const handleCancel = () => {
    const p = new URLSearchParams(searchParams);
    p.set('file', 'welcome');
    setSearchParams(p);
  };

  const handleLocalUpload = async (file: File) => {
    setUploadState('uploading');
    try {
      const currentKnowledgeBaseId = await ensureKnowledgeBase();
      const created = await uploadKnowledgeSource(currentKnowledgeBaseId, {
        file, title: file.name, description: desc, tags: "", chunkStrategy: "auto",
      });
      setSources((previous) => [...previous, {
        id: String(created.document?.id ?? file.name), type: 'local', name: file.name,
        status: String(created.index?.status ?? "ready"),
        chunks: Number(created.index?.chunkCount ?? 0), size: `${(file.size / 1024).toFixed(1)} KB`, time: '刚刚',
      }]);
      setUploadState('idle');
      showToast?.(`已成功解析并添加 ${file.name}`);
    } catch (error) {
      setUploadState('idle');
      showToast?.(error instanceof DomainRequestError ? error.message : "文件上传失败");
    }
  };
  
  const handleFeishuCheck = async () => {
    if(!feishuUrl) return;
    setFeishuState('checking');
    try {
      const result = await inspectFeishu(feishuUrl);
      if (result.status === "credential_blocked") {
        setFeishuState("blocked");
        showToast?.("飞书连接需要服务端凭证");
        return;
      }
      if (result.status !== "ready" || !result.document) {
        throw new Error("服务端未返回可同步的飞书文档。");
      }
      setFeishuState("ready");
      setFeishuDocument(result.document);
    } catch (error) {
      setFeishuState('error');
      showToast?.(error instanceof Error ? error.message : "飞书权限检查失败");
    }
  };

  const handleFeishuSync = async () => {
    setFeishuState('syncing');
    try {
      const result = await syncFeishu(await ensureKnowledgeBase(), { url: feishuUrl, includeChildren: true });
      if (result.status === "credential_blocked") {
        setFeishuState("blocked");
        showToast?.("飞书连接需要服务端凭证");
        return;
      }
      if (!result.document || !result.sourceRevision || !result.index) {
        throw new Error("服务端未返回可入库的飞书文档。");
      }
      setSources((previous) => [...previous, {
        id: String(result.document?.id ?? feishuUrl), type: 'feishu',
        name: String(result.document.title ?? feishuUrl),
        status: String(result.index?.status ?? "ready"),
        chunks: Number(result.index.chunkCount ?? 0), url: feishuUrl, size: '在线文档', time: '刚刚',
      }]);
      setFeishuState('idle');
      setFeishuUrl('');
      showToast?.('飞书文档同步成功');
    } catch (error) {
      setFeishuState('error');
      showToast?.(error instanceof Error ? error.message : "飞书同步失败");
    }
  };

  const completeKnowledgeBaseCreation = async () => {
    try {
      let kbId = knowledgeBaseId;
      if (!kbId) {
        const result = await createKnowledgeBase({ name, description: desc, scope: "personal" });
        kbId = String(result.knowledgeBase?.id ?? result.id ?? "");
      }
      if (!kbId) throw new Error("服务端未返回知识库 ID");
      setKnowledgeBaseId(kbId);
      const p = new URLSearchParams(searchParams);
      p.set('file', kbId);
      setSearchParams(p);
      showToast?.('已发送请求，等待状态刷新。');
    } catch (error) {
      showToast?.(error instanceof Error ? error.message : "知识库创建失败");
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 absolute inset-0 z-[60] w-full min-w-0 animate-in fade-in duration-200">
      <div className="h-16 px-6 border-b border-slate-200 flex items-center justify-between bg-white shrink-0 shadow-sm z-10">
        <div className="flex items-center space-x-4">
          <button onClick={handleCancel} className="p-2 hover:bg-slate-100 rounded-lg text-slate-500 transition-colors outline-none focus:ring-2"><ArrowLeft size={18} /></button>
          <h2 className="font-bold text-slate-800 text-lg tracking-tight">创建 Agent 知识库</h2>
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-6 md:p-10 flex justify-center custom-scrollbar pb-24">
        <div className="max-w-3xl w-full bg-white border border-slate-200 rounded-2xl shadow-sm h-fit overflow-hidden">
          <div className="flex items-center mb-6 bg-slate-50 p-4 border-b border-slate-100">
            <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shadow-sm", step >= 1 ? "bg-blue-600 text-white" : "bg-white text-slate-400 border border-slate-200")}>1</div>
            <span className={cn("text-sm font-medium ml-3", step >= 1 ? "text-slate-800" : "text-slate-400")}>基本信息</span>
            <div className={cn("flex-1 h-px mx-4", step >= 2 ? "bg-blue-600" : "bg-slate-200")}></div>
            <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shadow-sm", step >= 2 ? "bg-blue-600 text-white" : "bg-white text-slate-400 border border-slate-200")}>2</div>
            <span className={cn("text-sm font-medium ml-3 mr-4", step >= 2 ? "text-slate-800" : "text-slate-400")}>添加来源</span>
          </div>

          <div className="p-8 pt-2">
            {step === 1 && (
              <div className="space-y-6 animate-in slide-in-from-right-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-800 mb-2">知识库名称</label>
                  <input type="text" value={name} onChange={e=>setName(e.target.value)} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 shadow-sm" />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-800 mb-2">描述说明</label>
                  <textarea value={desc} onChange={e=>setDesc(e.target.value)} rows={3} className="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-blue-500 shadow-sm resize-none"></textarea>
                </div>
                <div className="flex justify-end pt-4">
                  <button onClick={() => setStep(2)} disabled={!name} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold shadow-sm hover:bg-blue-700 disabled:opacity-50">下一步</button>
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-6 animate-in slide-in-from-right-4 flex flex-col h-full">
                <div className="flex space-x-6 border-b border-slate-200 shrink-0">
                  <button onClick={() => setActiveTab('local')} className={cn("pb-3 text-sm font-bold transition-colors border-b-2 outline-none", activeTab === 'local' ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500")}>本地文件</button>
                  <button onClick={() => setActiveTab('feishu')} className={cn("pb-3 text-sm font-bold transition-colors border-b-2 outline-none", activeTab === 'feishu' ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500")}>飞书文档同步</button>
                </div>

                {activeTab === 'local' && (
                  <div className="space-y-4">
                    <div className="border-2 border-dashed border-slate-300 rounded-xl p-8 flex flex-col items-center justify-center hover:bg-slate-50 transition-colors relative cursor-pointer min-h-[160px]">
                      <input type="file" onChange={(e) => { if(e.target.files?.[0]) handleLocalUpload(e.target.files[0]); }} className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" />
                      {uploadState === 'uploading' ? (
                        <div className="flex flex-col items-center text-blue-600">
                          <Loader2 size={32} className="animate-spin mb-3" />
                          <span className="font-bold">解析与 OCR 处理中...</span>
                        </div>
                      ) : (
                        <div className="flex flex-col items-center text-slate-500">
                          <Upload size={32} className="mb-3 text-slate-400" />
                          <span className="font-bold text-slate-700">点击或拖拽文件上传</span>
                          <span className="text-xs mt-2 text-slate-500 font-medium relative z-10">请选择真实 Markdown、TXT 或 PDF 文件</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {activeTab === 'feishu' && (
                  <div className="space-y-4">
                    <div className="flex space-x-2">
                      <input type="text" value={feishuUrl} onChange={e=>setFeishuUrl(e.target.value)} placeholder="粘贴飞书文档 URL..." disabled={feishuState !== 'idle'} className="flex-1 border border-slate-300 rounded-xl px-4 py-2.5 text-sm outline-none focus:border-blue-500 shadow-sm disabled:bg-slate-50" />
                      <button onClick={handleFeishuCheck} disabled={!feishuUrl || feishuState !== 'idle'} className="px-4 py-2.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-xl text-sm font-bold shadow-sm hover:bg-blue-100 disabled:opacity-50 flex items-center outline-none">
                        {feishuState === 'checking' ? <Loader2 size={16} className="animate-spin mr-1.5"/> : <ShieldCheck size={16} className="mr-1.5"/>}检查权限
                      </button>
                    </div>

                    {feishuState === 'blocked' && (
                      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
                        飞书文档连接被服务端阻断：未配置凭证。请完成宿主 OAuth 后重新检查。
                      </div>
                    )}
                    {feishuState === 'ready' && (
                      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 animate-in slide-in-from-top-2">
                        <div className="flex justify-between items-center mb-3 pb-3 border-b border-slate-200">
                          <div>
                            <div className="font-bold text-slate-800">{String(feishuDocument?.title || feishuUrl)}</div>
                            <div className="text-xs text-slate-500 mt-1">服务端文档 ID: {String(feishuDocument?.id || '—')}</div>
                          </div>
                          <span className="bg-green-100 text-green-700 px-2 py-1 rounded text-xs font-bold border border-green-200 flex items-center"><CheckCircle2 size={12} className="mr-1"/>有权访问</span>
                        </div>
                        <label className="flex items-center text-sm text-slate-700 cursor-pointer">
                          <input type="checkbox" defaultChecked className="mr-2 rounded text-blue-600 focus:ring-blue-500" />
                          同步包含的所有子文档
                        </label>
                        <div className="flex justify-end mt-4">
                          <button onClick={handleFeishuSync} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-bold shadow-sm hover:bg-blue-700 outline-none">开始同步</button>
                        </div>
                      </div>
                    )}
                    {feishuState === 'syncing' && (
                      <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 flex flex-col items-center text-blue-700">
                        <Loader2 size={24} className="animate-spin mb-3" />
                        <span className="font-bold">拉取并解析飞书文档块...</span>
                      </div>
                    )}
                  </div>
                )}

                <div className="mt-6 flex-1 flex flex-col">
                  <h4 className="text-sm font-bold text-slate-800 mb-3">已添加的来源 ({sources.length})</h4>
                  <div className="flex-1 overflow-y-auto custom-scrollbar border border-slate-200 rounded-xl bg-slate-50 p-2 space-y-2 min-h-[150px]">
                    {sources.length === 0 && <div className="h-full flex items-center justify-center text-slate-400 text-sm">暂未添加任何来源</div>}
                    {sources.map((s, i) => (
                      <div key={i} className="bg-white border border-slate-200 rounded-lg p-3 flex justify-between items-center shadow-sm">
                        <div className="flex items-center">
                          {s.type === 'local' ? <FileText size={16} className="text-slate-400 mr-3"/> : <LinkIcon size={16} className="text-blue-500 mr-3"/>}
                          <div>
                            <div className="font-bold text-slate-800 text-sm">{s.name}</div>
                            <div className="text-xs text-slate-500 flex items-center mt-0.5 space-x-2">
                              <span>{s.size}</span>
                              <span className="w-1 h-1 bg-slate-300 rounded-full"></span>
                              <span>分片: {s.chunks}</span>
                              <span className="w-1 h-1 bg-slate-300 rounded-full"></span>
                              <span className="text-green-600 flex items-center"><CheckCircle2 size={10} className="mr-0.5"/> 索引成功</span>
                            </div>
                          </div>
                        </div>
                        <button className="text-slate-400 hover:text-red-500 outline-none"><XCircle size={16}/></button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex justify-between pt-4 border-t border-slate-100">
                  <button onClick={() => setStep(1)} className="px-6 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold shadow-sm hover:bg-slate-50 outline-none">上一步</button>
                  <button onClick={completeKnowledgeBaseCreation} disabled={sources.length === 0 || !knowledgeBaseId} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold shadow-sm hover:bg-blue-700 disabled:opacity-50 outline-none">完成创建</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
