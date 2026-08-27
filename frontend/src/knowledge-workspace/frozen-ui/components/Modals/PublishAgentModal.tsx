import React, { useState, useEffect } from 'react';
import { X, ToyBrick, AlertTriangle } from 'lucide-react';
import { resourceStore, agentPublicationStore, getResourceDescriptor } from '../../lib/store';
import { useSearchParams } from 'react-router-dom';
import { asRecord } from '../../lib/qualityPublicationClient';
import { bootstrapWorkspace, getWorkspaceAdapter } from '../../../production/store';
import { createRequestContext } from '../../../production/ports';

export default function PublishAgentModal({ onClose, fileId, showToast }: any) {
  const [searchParams] = useSearchParams();
  const allResources = resourceStore.getState();
  const descriptor = getResourceDescriptor(fileId, searchParams, allResources);
  const resource = allResources.find((item: any) => item.id === fileId || item.resourceId === fileId) as any;
  
  const resourceName = descriptor?.name as string;
  const revision = Number(resource?.revision ?? 1);
  const version = resource?.lifecycle === 'draft'
    ? `V${Math.max(1, revision)}.0`
    : String(descriptor?.version || resource?.version || '1.0.0');
  const identity = descriptor?.identity as string;
  const publications = agentPublicationStore.getState();
  const existing = publications.find((item: unknown) => {
    const record = asRecord(item);
    return record.skillId === identity || record.resourceId === identity;
  });
  const existingRecord = asRecord(existing);

  const [visibility, setVisibility] = useState(String(existingRecord.visibility ?? 'team'));

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const [error, setError] = useState('');
  const cannotPublishReason = !descriptor
    ? '缺少服务端资源描述，无法发布到 Agent。'
    : descriptor.resourceKind !== 'skill_draft'
    ? '只有服务端 SkillDraft 可进入真实 publication.publish。'
    : '';

  const handleCancelPublish = () => {
    if (!descriptor) return;
    setError('取消发布必须由服务端撤销命令确认；当前未执行本地删除。');
  };
  const published = existingRecord;
  const hasExistingPublication = Boolean(existing && resource?.lifecycle !== 'draft');
  const draftId = String((resource as any)?.draftId ?? resource?.id ?? '');
  const canPublish = Boolean(
    descriptor &&
    descriptor.resourceKind === 'skill_draft' &&
    draftId &&
    Number.isFinite(revision) &&
    revision > 0,
  );
  const publish = async () => {
    if (!canPublish) return;
    setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'publication.publish',
        payload: { draftId, revision, semver: version, visibility: visibility === 'personal' ? 'personal' : 'team' },
      }, createRequestContext());
      if (!response.accepted) throw new Error('服务端未接受发布请求。');
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '发布失败。');
    }
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="publish-agent-title"
    >
      <div className="flex min-h-[364px] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl max-[520px]:min-h-[388px]">
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-3">
          <h2 id="publish-agent-title" className="flex items-center text-lg font-bold text-slate-900">
            <ToyBrick size={19} className="mr-2 text-blue-600" /> 发布到 Agent
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded-lg p-1 text-slate-400 outline-none transition-colors hover:bg-slate-200"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 space-y-3 px-5 py-3 sm:px-6">
          <div className="text-sm leading-5 text-slate-700">
            <span className="block font-bold text-slate-900">“{resourceName}” ({version})</span>
            <span className="text-xs text-slate-500">发布后，其他平台的 Agent 可搜索并选择此资源。</span>
          </div>

          <fieldset>
            <legend className="mb-1.5 text-xs font-bold text-slate-800">可见范围</legend>
            <div className="grid grid-cols-2 gap-2">
              {[
                ['personal', '仅个人可用'],
                ['team', '团队公开可用'],
              ].map(([value, label]) => (
                <label
                  key={value}
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                    visibility === value
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                  }`}
                >
                  <input
                    type="radio"
                    name="publish-agent-visibility"
                    value={value}
                    checked={visibility === value}
                    onChange={(e) => setVisibility(e.target.value)}
                    className="h-3.5 w-3.5 accent-blue-600"
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>

          {cannotPublishReason && (
            <div id="publish-agent-gate" role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <AlertTriangle size={13} className="mr-1 inline-block align-[-2px]" />
              {cannotPublishReason}
            </div>
          )}
          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-100 bg-slate-50 px-4 py-2.5">
          {hasExistingPublication && (
            <button type="button" onClick={handleCancelPublish} className="mr-auto rounded-lg px-2 py-2 text-xs font-bold text-red-600 outline-none transition-colors hover:bg-red-50">
              取消发布
            </button>
          )}
          {!hasExistingPublication && (
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-bold text-slate-700 outline-none shadow-sm transition-colors hover:bg-slate-50">
              取消
            </button>
          )}
          <button
            type="button"
            disabled={!canPublish}
            onClick={() => void publish()}
            aria-describedby="publish-agent-gate"
            title={cannotPublishReason}
            className="rounded-lg bg-blue-600 px-5 py-2 text-xs font-bold text-white shadow-sm outline-none transition-colors hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {hasExistingPublication ? '更新范围' : '确认发布'}
          </button>
        </div>
      </div>
    </div>
  );
}
