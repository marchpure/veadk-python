import React, { useState } from 'react';
import { FileText, ArrowLeft, Upload, Loader2, CheckCircle2 } from 'lucide-react';
import { resourceStore } from '../../lib/store';

export default function UploadDocView({ searchParams, setSearchParams, showToast }: any) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [tags, setTags] = useState('');
  const [chunkStrategy, setChunkStrategy] = useState('auto');
  const [visibility, setVisibility] = useState('team');
  const [targetFolder, setTargetFolder] = useState('knowledge');
  
  const [uploadState, setUploadState] = useState<'idle'|'uploading'|'parsing'|'chunking'|'indexing'|'done'>('idle');
  const targetSpace = searchParams.get('target_space') || 'personal';

  const [fileContent, setFileContent] = useState<string>('');

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      setFile(selectedFile);
      if (!title) setTitle(selectedFile.name.replace(/\.[^/.]+$/, ""));

      const reader = new FileReader();
      reader.onload = (evt) => {
        if (evt.target?.result) setFileContent(evt.target.result as string);
      };
      reader.readAsText(selectedFile);
    }
  };

  const handleCancel = () => {
    const p = new URLSearchParams(searchParams);
    const origin = searchParams.get('target_space');
    p.set('file', 'welcome'); p.delete('target_space');
    setSearchParams(p);
    if (origin) {
      setTimeout(() => { const el = document.querySelector(`[data-tree-id="${origin}"]`); if (el) { (el as HTMLElement).focus(); } }, 100);
    }
  };

  const handleUpload = () => {
    if (!file) return;
    setUploadState('uploading');
    setTimeout(() => {
      setUploadState('parsing');
      setTimeout(() => {
        setUploadState('chunking');
        setTimeout(() => {
          setUploadState('indexing');
          setTimeout(() => {
            setUploadState('done');
            
            const docId = `doc_${Date.now()}`;
            const chunks = chunkStrategy === 'heading' ? fileContent.split('\n#') : fileContent.split('\n\n');
            const newDoc = {
              identity: docId,
              id: docId,
              resourceId: docId,
              name: title || file.name,
              type: targetSpace === 'team' ? 'team_artifact' : 'personal_artifact',
              artifactType: 'document',
              cat: 'file',
              path: `${targetSpace === 'team' ? '团队' : '个人'}/知识文档/${title || file.name}`,
              permission: true,
              tokenEstimate: Math.max(0.5, Math.round(file.size / 1024 / 100) / 10),
              desc, tags, chunkStrategy, visibility, targetFolder,
              fileName: file.name, fileSize: (file.size / 1024).toFixed(1) + ' KB',
              version: 'V1.0', readonly: targetSpace === 'team', isTeam: targetSpace === 'team',
              content: fileContent,
              chunksCount: chunks.length > 0 && fileContent ? chunks.length : 12
            };
            resourceStore.setState(prev => [newDoc, ...prev]);
            
            showToast?.('知识文档解析并入库成功！');
            setTimeout(() => {
              const p = new URLSearchParams(searchParams);
              p.set('file', docId);
              p.delete('target_space');
              setSearchParams(p);
            }, 1000);
          }, 1000);
        }, 1000);
      }, 1000);
    }, 1000);
  };

  return (
    <div className="flex flex-col h-full bg-white relative animate-in fade-in absolute inset-0 z-[60] w-full min-w-0">
      <div className="h-16 px-6 border-b border-slate-200 flex items-center bg-white shrink-0 shadow-sm z-10">
        <button onClick={handleCancel} className="p-2 hover:bg-slate-100 rounded-lg text-slate-500 mr-4 outline-none focus:ring-2"><ArrowLeft size={18} /></button>
        <h2 className="font-bold text-slate-800 text-lg tracking-tight">上传知识文档</h2>
      </div>
      
      <div className="flex-1 overflow-y-auto p-6 md:p-10 flex justify-center bg-slate-50/50 custom-scrollbar">
        <div className="max-w-2xl w-full bg-white border border-slate-200 rounded-2xl shadow-sm p-8 h-fit">
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-semibold text-slate-800 mb-2">选择文件</label>
              <div className="border-2 border-dashed border-slate-300 rounded-xl p-8 flex flex-col items-center justify-center hover:bg-slate-50 transition-colors relative cursor-pointer min-h-[200px]">
                <input type="file" onChange={handleFileChange} accept=".md,.pdf,.txt,.html" className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" disabled={uploadState !== 'idle'} />
                {file ? (
                  <div className="flex flex-col items-center text-blue-600">
                    <FileText size={40} className="mb-3" />
                    <span className="font-bold text-lg">{file.name}</span>
                    <span className="text-sm text-slate-500 mt-2">{(file.size / 1024).toFixed(1)} KB</span>
                  </div>
                ) : (
                  <div className="flex flex-col items-center text-slate-500">
                    <Upload size={40} className="mb-3 text-slate-400" />
                    <span className="font-bold text-slate-700 text-base">点击或拖拽文件到此处</span>
                    <span className="text-xs mt-2">支持 Markdown, PDF, TXT, HTML</span>
                  </div>
                )}
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="block text-sm font-semibold text-slate-800 mb-2">文档标题</label>
                <input type="text" value={title} onChange={e=>setTitle(e.target.value)} disabled={uploadState !== 'idle'} className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500" />
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-semibold text-slate-800 mb-2">描述说明</label>
                <textarea value={desc} onChange={e=>setDesc(e.target.value)} disabled={uploadState !== 'idle'} className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500 resize-none h-20"></textarea>
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-semibold text-slate-800 mb-2">标签 (Tags)</label>
                <input type="text" value={tags} onChange={e=>setTags(e.target.value)} disabled={uploadState !== 'idle'} placeholder="以逗号分隔，如：销售, 指标口径" className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500" />
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-800 mb-2">分段策略 (Chunking)</label>
                <select value={chunkStrategy} onChange={e=>setChunkStrategy(e.target.value)} disabled={uploadState !== 'idle'} className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500 bg-white">
                  <option value="auto">智能自动分段</option>
                  <option value="heading">按标题层级</option>
                  <option value="fixed">固定长度 (512 tokens)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-800 mb-2">目标文件夹</label>
                <select value={targetFolder} onChange={e=>setTargetFolder(e.target.value)} disabled={uploadState !== 'idle'} className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500 bg-white">
                  <option value="knowledge">知识与图谱 / 知识文档</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-semibold text-slate-800 mb-2">可见性</label>
                <select value={visibility} onChange={e=>setVisibility(e.target.value)} disabled={uploadState !== 'idle'} className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm outline-none focus:border-blue-500 bg-white">
                  <option value="team">团队可见 (可发布)</option>
                  <option value="private">仅自己可见</option>
                </select>
              </div>
            </div>
            
            {uploadState !== 'idle' && (
              <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 space-y-3">
                <div className="flex items-center text-sm font-medium text-slate-700">
                  {uploadState === 'uploading' ? <><Loader2 size={16} className="animate-spin text-blue-600 mr-2"/> 上传中...</> : <><CheckCircle2 size={16} className="text-green-500 mr-2"/> 上传完成</>}
                </div>
                <div className="flex items-center text-sm font-medium text-slate-700">
                  {uploadState === 'uploading' ? <div className="w-4 h-4 rounded-full border-2 border-slate-300 mr-2"/> : uploadState === 'parsing' ? <><Loader2 size={16} className="animate-spin text-blue-600 mr-2"/> 文本解析中...</> : <><CheckCircle2 size={16} className="text-green-500 mr-2"/> 文本解析成功</>}
                </div>
                <div className="flex items-center text-sm font-medium text-slate-700">
                  {['uploading', 'parsing'].includes(uploadState) ? <div className="w-4 h-4 rounded-full border-2 border-slate-300 mr-2"/> : uploadState === 'chunking' ? <><Loader2 size={16} className="animate-spin text-blue-600 mr-2"/> 智能分段中...</> : <><CheckCircle2 size={16} className="text-green-500 mr-2"/> 分段完成 (共 12 段)</>}
                </div>
                <div className="flex items-center text-sm font-medium text-slate-700">
                  {['uploading', 'parsing', 'chunking'].includes(uploadState) ? <div className="w-4 h-4 rounded-full border-2 border-slate-300 mr-2"/> : uploadState === 'indexing' ? <><Loader2 size={16} className="animate-spin text-blue-600 mr-2"/> 向量索引构建中...</> : <><CheckCircle2 size={16} className="text-green-500 mr-2"/> 索引构建完成</>}
                </div>
              </div>
            )}
            
            <div className="flex justify-end space-x-3 pt-4 border-t border-slate-100">
              <button onClick={handleCancel} disabled={uploadState !== 'idle'} className="px-5 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-bold hover:bg-slate-50 disabled:opacity-50 outline-none">取消</button>
              <button onClick={handleUpload} disabled={!file || uploadState !== 'idle'} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 disabled:opacity-50 shadow-sm flex items-center outline-none">
                开始上传并解析
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}