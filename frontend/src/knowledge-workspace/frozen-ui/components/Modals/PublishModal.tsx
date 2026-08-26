import React, { useEffect, useMemo, useState, type SVGProps } from 'react';
import { createRequestContext } from '../../../production/ports';
import { bootstrapWorkspace, getWorkspaceAdapter, getResourceDescriptor, resourceStore } from '../../lib/store';

function IconBase({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M6 6l12 12" /><path d="M18 6 6 18" /></IconBase>;
}

function AlertIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M12 4 3.5 19h17L12 4Z" /><path d="M12 9v4" /><path d="M12 16h.01" /></IconBase>;
}

function SendIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M21 3 10 14" /><path d="m21 3-7 18-4-7-7-4 18-7Z" /></IconBase>;
}

function GateIcon(props: SVGProps<SVGSVGElement>) {
  return <IconBase {...props}><path d="M12 3 5 6v5c0 4.3 2.8 7.7 7 10 4.2-2.3 7-5.7 7-10V6l-7-3Z" /><path d="m9 12 2 2 4-5" /></IconBase>;
}

export default function PublishModal({
  onClose,
  isTeam,
  showToast,
}: {
  onClose: () => void;
  isTeam?: boolean;
  showToast?: (message: string) => void;
}) {
  const [selectedDir, setSelectedDir] = useState('');
  const [semver, setSemver] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const searchParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const currentId = searchParams.get('file') ?? '';
  const allResources = resourceStore.getState();
  const currentResource = allResources.find((item: any) => item.id === currentId || item.resourceId === currentId) as any;
  const descriptor = getResourceDescriptor(currentId, searchParams, allResources);
  const draftId = String(currentResource?.draftId ?? currentResource?.id ?? descriptor?.id ?? '');
  const revision = Number(currentResource?.revision ?? searchParams.get('revision') ?? 0);
  const resourceName = String((descriptor?.name ?? currentResource?.displayName ?? currentResource?.name ?? currentId) || '当前 Skill');
  const canPublish = Boolean(
    !isTeam &&
    (currentResource?.resourceKind === 'skill_draft' || currentResource?.lifecycle === 'draft') &&
    draftId &&
    Number.isFinite(revision) &&
    revision > 0 &&
    semver.trim(),
  );

  const publish = async () => {
    if (!canPublish) {
      setError('缺少服务端 SkillDraft、revision 或发布版本号，不能创建本地假发布。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await getWorkspaceAdapter().command({
        command: 'publication.publish',
        payload: {
          draftId,
          revision,
          semver: semver.trim(),
        },
      }, createRequestContext());
      if (!response.accepted) throw new Error('服务端未接受发布请求。');
      await bootstrapWorkspace(undefined, getWorkspaceAdapter());
      showToast?.('发布请求已被服务端接受，等待发布状态刷新。');
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '发布失败。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="publish-modal-title"
    >
      <div className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 p-5">
          <h2 id="publish-modal-title" className="text-lg font-semibold text-slate-900">发布到团队工作区</h2>
          <button type="button" onClick={onClose} aria-label="关闭" title="关闭" className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6">
          <p className="mb-5 text-sm leading-6 text-slate-700">
            将 <span className="font-semibold text-slate-900">“{resourceName}”</span> 提交给服务端 publication.publish。发布门禁、版本和团队快照只能由服务端返回。
          </p>

          <div className="mb-6 space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-target-dir">目标团队目录</label>
              <select id="publish-target-dir" value={selectedDir} onChange={(event) => setSelectedDir(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                <option value="">由服务端默认策略决定</option>
                <option value="team">团队默认空间</option>
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-semver">发布版本</label>
              <input
                id="publish-semver"
                value={semver}
                onChange={(event) => setSemver(event.target.value)}
                placeholder="例如 1.0.0"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="mb-2 flex items-center text-sm font-semibold text-slate-800">
              <GateIcon className="mr-2 h-4 w-4 text-slate-500" /> 发布门禁
            </div>
            <p className="text-xs leading-5 text-slate-600">
              当前页面未收到 PolicyGateResult。请先运行服务端评测或由 MAIN 接入门禁结果后再发布。
            </p>
          </div>

          <div className="mb-6 flex items-start rounded-xl border border-amber-200/60 bg-amber-50 p-4">
            <AlertIcon className="mr-3 mt-0.5 h-4.5 w-4.5 shrink-0 text-amber-600" />
            <div className="text-xs leading-relaxed text-amber-800">
              该操作不会创建浏览器本地团队版本。若缺少 SkillDraft、revision 或 semver，确认按钮会保持禁用。
            </div>
          </div>

          {error && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

          <div className="flex justify-end gap-3">
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50">取消</button>
            <button type="button" onClick={() => void publish()} disabled={!canPublish || busy} className="inline-flex items-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">
              <SendIcon className="ml-0 mr-1.5 h-3.5 w-3.5" /> 确认发布
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
