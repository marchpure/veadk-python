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
  const readModel = (currentResource?.readModel ?? currentResource ?? {}) as any;
  const viewModel = (readModel?.skillViewRevision?.viewModel ?? currentResource?.skillViewRevision?.viewModel ?? {}) as any;
  const manifest = (readModel?.manifest ??
    readModel?.publishedVersion?.manifest ??
    currentResource?.manifest ??
    {}) as any;
  const kindSpec = (manifest?.spec?.kindSpec ??
    readModel?.publishedVersion?.manifest?.spec?.kindSpec ??
    readModel?.publishedVersion?.spec?.kindSpec ??
    readModel?.kindSpec ??
    {}) as any;
  const inputFields = Array.isArray(kindSpec.inputFields)
    ? kindSpec.inputFields.map((field: any) => String(field?.label ?? field?.name ?? '')).filter(Boolean)
    : Array.isArray(viewModel.fields)
      ? viewModel.fields.map((field: any) => String(field?.label ?? field?.name ?? '')).filter(Boolean)
      : [];
  const evaluation = readModel?.evaluationRun ?? {};
  const policyGate = readModel?.policyGateResult ?? {};
  const evaluationLabel = evaluation.status === 'succeeded'
    ? `评测通过${Number.isFinite(Number(evaluation.score)) ? ` · ${Math.round(Number(evaluation.score) * 100)}%` : ''}`
    : '等待服务端评测';
  const gateLabel = policyGate.decision === 'publishable' ? '可发布' : String(policyGate.decision ?? '等待服务端门禁');
  const operationRisk =
    manifest?.spec?.contract?.operations?.[0]?.risk ??
    readModel?.publishedVersion?.manifest?.spec?.contract?.operations?.[0]?.risk ??
    readModel?.publishedVersion?.spec?.contract?.operations?.[0]?.risk ??
    kindSpec.actionProposal ??
    (Array.isArray(viewModel.actionProposals) && viewModel.actionProposals.length === 0
      ? '仅读取/查询数据'
      : '由服务端权限策略决定');
  const inputRequirement = inputFields.length ? inputFields.join('、') : '由服务端 revision 定义';
  const agentAudience = '所有团队 Agent';
  const versionNote = `V${Math.max(1, revision || 1)}.0`;
  const canPublish = Boolean(
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
          visibility: selectedDir === 'personal' ? 'personal' : 'team',
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
      <div className="flex h-[618px] w-full max-w-md flex-col overflow-hidden rounded-2xl bg-white shadow-xl max-h-[calc(100dvh-32px)]">
        <div className="flex items-center justify-between border-b border-slate-100 p-5">
          <h2 id="publish-modal-title" className="text-lg font-semibold text-slate-900">发布到团队工作区</h2>
          <button type="button" onClick={onClose} aria-label="关闭" title="关闭" className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6 max-[520px]:p-5">
          <p className="mb-4 text-sm leading-6 text-slate-700 max-[520px]:mb-3 max-[520px]:leading-5">
            确定要将 <span className="font-semibold text-slate-900">“{resourceName}”</span> 发布到团队工作区吗？
          </p>

          <div className="mb-4 space-y-3 max-[520px]:mb-3 max-[520px]:space-y-2.5">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-name">发布名称</label>
              <input id="publish-name" value={resourceName} readOnly className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700" />
            </div>
            <div className="grid grid-cols-2 gap-4 max-[520px]:gap-2.5">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-target-dir">适用团队目录</label>
                <select id="publish-target-dir" value={selectedDir} onChange={(event) => setSelectedDir(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                  <option value="">由服务端默认策略决定</option>
                  <option value="team">团队默认空间</option>
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-agent-audience">允许调用的 Agent</label>
                <select id="publish-agent-audience" defaultValue="all" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                  <option value="all">{agentAudience}</option>
                  <option value="support">仅售后服务 Agent</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 max-[520px]:gap-2.5">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-input-requirement">要求输入信息</label>
                <input id="publish-input-requirement" value={inputRequirement} readOnly className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700" />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-permission">操作权限</label>
                <select id="publish-permission" defaultValue={operationRisk === '仅读取/查询数据' ? 'read' : 'policy'} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                  <option value="read">仅读取/查询数据</option>
                  <option value="policy">{operationRisk}</option>
                </select>
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-600" htmlFor="publish-semver">版本说明 ({versionNote})</label>
              <textarea id="publish-semver" value={semver} onChange={(event) => setSemver(event.target.value)} placeholder="描述本次发布的改动，例如 1.0.0" rows={2} className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
          </div>

          <div className="mb-4 flex items-center rounded-xl border border-blue-200 bg-blue-50 p-3 shadow-inner max-[520px]:mb-3">
            <GateIcon className="mr-2 h-4.5 w-4.5 shrink-0 text-blue-600" />
            <div className="text-xs font-medium leading-relaxed text-blue-800">
              {evaluationLabel} · {gateLabel}。安全与合规扫描将在发布过程中由服务端执行，确保不泄露敏感数据。
            </div>
          </div>
          <div className="mb-3 flex items-start rounded-xl border border-amber-200/60 bg-amber-50 p-3 max-[520px]:mb-2">
            <AlertIcon className="mr-3 mt-0.5 h-4.5 w-4.5 shrink-0 text-amber-600" />
            <div className="text-xs leading-relaxed text-amber-800">
              缺少 SkillDraft、revision 或版本说明时，确认按钮会保持禁用。
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
