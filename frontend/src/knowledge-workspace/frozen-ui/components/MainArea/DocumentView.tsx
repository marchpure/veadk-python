import React from 'react';
import ArtifactHeader from './ArtifactHeader';
import { BookOpen, ListTree, Quote } from 'lucide-react';
import { cn } from '../../lib/utils';
import { resourceStore } from '../../lib/store';

export default function DocumentView({ fileId, searchParams, setSearchParams, showToast }: any) {
  const doc = resourceStore.getState().find((r:any) => r.id === fileId || r.resourceId === fileId) || {
    name: '未命名文档', version: 'V1.0', isTeam: false, fileName: 'doc.md', fileSize: '0 KB', chunkStrategy: 'auto', content: '', chunksCount: 12
  };
  const isTeam = doc.isTeam || doc.readonly;

  const handleElementClick = (target: string) => {};

  return (
    <div className="p-4 md:p-8 max-w-[1000px] mx-auto pb-24 w-full animate-in fade-in relative">
      <ArtifactHeader 
        title={doc.name} 
        typeLabel="Document"
        isTeam={isTeam} 
        version={doc.version || 'V1.0'} 
        fromTeamVersion={doc.fromTeamVersion}
        editTarget={null} 
        onElementClick={handleElementClick} 
        searchParams={searchParams}
        setSearchParams={setSearchParams}
        showToast={showToast}
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6">
        <div className="md:col-span-2 space-y-6">
          <div className="bg-white border border-slate-200 rounded-[12px] overflow-hidden flex flex-col h-[500px]">
             <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 flex items-center justify-between shrink-0">
               <h3 className="font-semibold text-slate-800 flex items-center"><BookOpen size={16} className="mr-2 text-blue-600"/> 正文预览</h3>
               <span className="text-xs text-slate-500 bg-white px-2 py-1 rounded border border-slate-200">源文件: {doc.fileName} ({doc.fileSize})</span>
             </div>
             <div className="p-6 overflow-y-auto prose prose-sm max-w-none text-slate-700 custom-scrollbar flex-1 bg-slate-50/30">
               {doc.content ? (
                 <div className="whitespace-pre-wrap">
                   {doc.content.split('\n\n').map((para: string, idx: number) => (
                     <p key={idx} id={`chunk-${idx+1}`} className={cn("hover:bg-blue-50 p-2 -mx-2 rounded transition-colors cursor-pointer border border-transparent hover:border-blue-100", searchParams.get('scroll_target')===`chunk-${idx+1}` && "bg-blue-100 border-blue-200 ring-2 ring-blue-500")} onClick={() => {
                       window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: `chunk_${fileId}_${idx+1}`, name: `${doc.name} - 第${idx+1}段`, type: 'document', artifactId: fileId, locator: `chunk-${idx+1}`} } })); showToast?.('已加入片段上下文');
                     }}>
                       {para}
                     </p>
                   ))}
                 </div>
               ) : (
                 <>
                   <h2>1. 销售口径定义</h2>
                   <p id="chunk-1" className={cn("hover:bg-blue-50 p-2 -mx-2 rounded transition-colors cursor-pointer border border-transparent hover:border-blue-100", searchParams.get('scroll_target')==='chunk-1' && "bg-blue-100 border-blue-200 ring-2 ring-blue-500")} onClick={() => {
                     window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: `chunk_${fileId}_1`, name: `${doc.name} - 第1段`, type: 'document', artifactId: fileId, locator: 'chunk-1'} } })); showToast?.('已加入片段上下文');
                   }}>
                     <strong>净销售额 (Net Sales)</strong>：指商品发出后，扣除各种折扣、退回、折让后的实际收入。<br/>
                     公式：净销售额 = 总销售额 - 销售折扣 - 销售退货。
                   </p>
                   <h2>2. 利润计算规则</h2>
                   <p id="chunk-2" className={cn("hover:bg-blue-50 p-2 -mx-2 rounded transition-colors cursor-pointer border border-transparent hover:border-blue-100", searchParams.get('scroll_target')==='chunk-2' && "bg-blue-100 border-blue-200 ring-2 ring-blue-500")} onClick={() => {
                     window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: `chunk_${fileId}_2`, name: `${doc.name} - 第2段`, type: 'document', artifactId: fileId, locator: 'chunk-2'} } })); showToast?.('已加入片段上下文');
                   }}>
                     <strong>毛利润 (Gross Profit)</strong>：净销售额减去销售成本 (COGS)。<br/>
                     这部分利润不包含公司的运营费用（如管理费、销售费等）。
                   </p>
                 </>
               )}
             </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-[12px] p-5">
            <h3 className="font-semibold text-slate-800 mb-4 flex items-center"><ListTree size={16} className="mr-2 text-blue-600"/> 解析与索引状态</h3>
            <div className="space-y-4 text-sm text-slate-600">
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">分段策略</span>
                <span className="font-medium text-slate-800">{doc.chunkStrategy === 'heading' ? '按标题层级' : '智能自动分段'}</span>
              </div>
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">产出分段 (Chunks)</span>
                <span className="font-medium text-slate-800 bg-slate-100 px-2 py-0.5 rounded">{doc.chunksCount} 段</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">向量化模型</span>
                <span className="font-medium text-slate-800 text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded">text-embedding-3-small</span>
              </div>
            </div>
          </div>
          
          <div className="bg-blue-50 border border-blue-100 rounded-[12px] p-5">
             <h3 className="font-semibold text-blue-900 mb-2 flex items-center"><Quote size={16} className="mr-2"/> 基于此提问</h3>
             <p className="text-xs text-blue-700 leading-relaxed mb-4">加入上下文后，助手将能够精准引用本文档的内容来解答业务口径和计算规则。</p>
             <button onClick={() => {
               window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: {id: fileId, name: doc.name, type: 'document', artifactId: fileId} } })); showToast?.('已加入完整文档上下文');
               const p = new URLSearchParams(searchParams);
               p.set('pane', 'open');
               setSearchParams(p);
             }} className="w-full bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm outline-none">加入上下文并展开助手</button>
          </div>
        </div>
      </div>
    </div>
  );
}