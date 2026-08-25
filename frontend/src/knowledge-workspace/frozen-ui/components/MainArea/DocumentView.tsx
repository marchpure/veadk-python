import React, { useEffect, useState } from 'react';
import ArtifactHeader from './ArtifactHeader';
import { BookOpen, ListTree, Quote } from 'lucide-react';
import { cn } from '../../lib/utils';
import { DomainRequestError, getKnowledgeDocument } from '../../../production/domainClient';

export default function DocumentView({ fileId, searchParams, setSearchParams, showToast }: any) {
  const [serverDoc, setServerDoc] = useState<any>(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let active = true;
    void getKnowledgeDocument(fileId).then((value) => {
      if (active) setServerDoc(value);
    }).catch((cause) => {
      if (active) setLoadError(
        cause instanceof DomainRequestError && cause.status === 404
          ? '服务端没有找到这份文档。'
          : cause instanceof Error ? cause.message : '文档读取失败',
      );
    });
    return () => { active = false; };
  }, [fileId]);

  const doc = serverDoc ? {
    ...serverDoc,
    name: serverDoc.title,
    fileName: serverDoc.filename,
    fileSize: `${serverDoc.content?.length ?? 0} chars`,
    chunksCount: serverDoc.index?.chunkCount ?? serverDoc.chunks?.length ?? 0,
  } : null;
  const documentName = doc?.name || '知识文档';
  const isTeam = Boolean(doc?.isTeam || doc?.readonly);

  const addContext = (locator: string, label: string) => {
    if (!doc) return;
    window.dispatchEvent(new CustomEvent('add_context_item', {
      detail: { item: { id: `chunk_${fileId}_${locator}`, name: `${doc.name} - ${label}`, type: 'document', artifactId: fileId, locator, contextRef: doc.contextRef } },
    }));
    showToast?.('已加入片段上下文');
  };

  return (
    <div className="p-4 md:p-8 max-w-[1000px] mx-auto pb-24 w-full animate-in fade-in relative">
      <ArtifactHeader
        title={documentName}
        typeLabel="Document"
        isTeam={isTeam}
        version={doc?.version || '—'}
        fromTeamVersion={doc?.fromTeamVersion}
        editTarget={null}
        onElementClick={() => {}}
        searchParams={searchParams}
        setSearchParams={setSearchParams}
        showToast={showToast}
      />
      {loadError && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{loadError}</div>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-6">
        <div className="md:col-span-2 space-y-6">
          <div className="bg-white border border-slate-200 rounded-[12px] overflow-hidden flex flex-col h-[500px]">
            <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 flex items-center justify-between shrink-0">
              <h3 className="font-semibold text-slate-800 flex items-center"><BookOpen size={16} className="mr-2 text-blue-600" />正文预览</h3>
              <span className="text-xs text-slate-500 bg-white px-2 py-1 rounded border border-slate-200">
                {doc ? `源文件: ${doc.fileName} (${doc.fileSize})` : '等待服务端文档内容'}
              </span>
            </div>
            <div className="p-6 overflow-y-auto prose prose-sm max-w-none text-slate-700 custom-scrollbar flex-1 bg-slate-50/30">
              {doc?.content ? (
                <div className="whitespace-pre-wrap">
                  {doc.content.split('\n\n').map((paragraph: string, index: number) => {
                    const locator = `chunk-${index + 1}`;
                    return (
                      <p
                        key={locator}
                        id={locator}
                        className={cn(
                          "hover:bg-blue-50 p-2 -mx-2 rounded transition-colors cursor-pointer border border-transparent hover:border-blue-100",
                          searchParams.get('scroll_target') === locator && "bg-blue-100 border-blue-200 ring-2 ring-blue-500",
                        )}
                        onClick={() => addContext(locator, `第${index + 1}段`)}
                      >
                        {paragraph}
                      </p>
                    );
                  })}
                </div>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-slate-500">
                  {loadError ? '未能加载服务端文档内容。' : '正在读取服务端文档内容…'}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-[12px] p-5">
            <h3 className="font-semibold text-slate-800 mb-4 flex items-center"><ListTree size={16} className="mr-2 text-blue-600" />解析与索引状态</h3>
            <div className="space-y-4 text-sm text-slate-600">
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">分段策略</span>
                <span className="font-medium text-slate-800">{doc?.chunkStrategy || '服务端策略'}</span>
              </div>
              <div className="flex justify-between items-center pb-3 border-b border-slate-100">
                <span className="text-slate-500">产出分段 (Chunks)</span>
                <span className="font-medium text-slate-800 bg-slate-100 px-2 py-0.5 rounded">{doc?.chunksCount ?? '—'} 段</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">索引状态</span>
                <span className="font-medium text-slate-700 text-xs bg-slate-100 px-2 py-0.5 rounded">{doc?.index?.status || '等待服务端结果'}</span>
              </div>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-100 rounded-[12px] p-5">
            <h3 className="font-semibold text-blue-900 mb-2 flex items-center"><Quote size={16} className="mr-2" />基于此提问</h3>
            <p className="text-xs text-blue-700 leading-relaxed mb-4">加入上下文后，助手将能够引用本文档的服务端内容。</p>
            <button onClick={() => {
              if (!doc) return;
              window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item: { id: fileId, name: doc.name, type: 'document', artifactId: fileId, contextRef: doc.contextRef } } }));
              showToast?.('已加入完整文档上下文');
              const next = new URLSearchParams(searchParams);
              next.set('pane', 'open');
              setSearchParams(next);
            }} disabled={!doc} className="w-full bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm outline-none disabled:opacity-50">
              加入上下文并展开助手
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
