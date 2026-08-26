import { useCallback, useState } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import { createRequestContext } from '../../../production/ports';
import { bootstrapWorkspace, getWorkspaceAdapter } from '../../../production/store';
import {
  TrustedHtmlArtifactRenderer,
  type TrustedArtifactEvent,
} from './TrustedHtmlArtifactRenderer';

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function activeSkillId(): string {
  const revision = isRecord(activeSkillViewRevision) ? activeSkillViewRevision : null;
  const intent = isRecord(revision?.intent) ? revision.intent : {};
  const skillRevisionId = String(revision?.skillRevisionId ?? revision?.skill_revision_id ?? '');
  if (typeof intent.skillId === 'string' && intent.skillId) return intent.skillId;
  if (skillRevisionId.includes(':')) return skillRevisionId.slice(0, skillRevisionId.lastIndexOf(':'));
  return '';
}

export default function DashboardView({ fileId }: any) {
  const [pending, setPending] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const gate = useCallback((reason: string) => {
    setError(reason);
    setMessage('');
  }, []);

  const sendCommand = useCallback(async (event: TrustedArtifactEvent) => {
    setError('');
    setMessage('');
    if (event.type === 'filter.change' || event.type === 'drill.request') {
      window.dispatchEvent(new CustomEvent('add_context_item', {
        detail: {
          item: {
            id: `${event.revisionId}:${event.elementId ?? event.field ?? event.type}`,
            name: event.elementId ?? event.field ?? event.type,
            type: 'element',
            viewRevisionId: event.revisionId,
            selectionIdentity: event.value,
          },
        },
      }));
      gate('筛选/钻取需要 W3 artifact interaction command seam；当前只把选中元素加入上下文，等待服务端处理。');
      return;
    }
    if (event.type === 'export.request') {
      const resourceId = event.revisionId || fileId;
      if (!resourceId) {
        gate('缺少 resourceId，无法请求 artifact.export。');
        return;
      }
      setPending('artifact.export');
      try {
        const response = await getWorkspaceAdapter().command({
          command: 'artifact.export',
          payload: {
            resourceId,
            format: event.format === 'csv' || event.format === 'json' ? event.format : 'html',
          },
        }, createRequestContext());
        if (!response.accepted) throw new Error('服务端未接受导出请求。');
        setMessage(`artifact.export accepted: ${response.operationId ?? response.requestId}`);
      } catch (cause) {
        gate(cause instanceof Error ? cause.message : 'artifact.export 失败。');
      } finally {
        setPending('');
      }
      return;
    }
    if (event.type === 'refresh.request') {
      const skillId = activeSkillId();
      if (!skillId) {
        gate('缺少 SkillViewRevision.intent.skillId；refresh.run 尚未集成。');
        return;
      }
      setPending('refresh.run');
      try {
        const response = await getWorkspaceAdapter().command({
          command: 'refresh.run',
          payload: { skillId, trigger: 'manual' },
        }, createRequestContext());
        if (!response.accepted) throw new Error('服务端未接受刷新请求。');
        await bootstrapWorkspace(undefined, getWorkspaceAdapter());
        setMessage(`refresh.run accepted: ${response.operationId ?? response.requestId}`);
      } catch (cause) {
        gate(cause instanceof Error ? cause.message : 'refresh.run 失败。');
      } finally {
        setPending('');
      }
    }
  }, [fileId, gate]);

  const handleEvent = useCallback((event: TrustedArtifactEvent) => {
    if (event.type === 'selection.change') {
      window.dispatchEvent(new CustomEvent('add_context_item', {
        detail: {
          item: {
            id: event.elementId,
            name: event.elementId,
            type: 'element',
            viewRevisionId: event.revisionId,
          },
        },
      }));
      return;
    }
    if (event.type === 'context.reference') {
      window.dispatchEvent(new CustomEvent('add_context_item', {
        detail: {
          item: {
            id: event.revisionId,
            name: `HTML revision ${event.revisionId}`,
            type: 'artifact',
            viewRevisionId: event.revisionId,
            isResourceLevel: true,
          },
        },
      }));
      return;
    }
    void sendCommand(event);
  }, [sendCommand]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {(pending || message || error) && (
        <div className="mx-4 mt-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm" role={error ? 'alert' : 'status'} aria-busy={Boolean(pending)}>
          {pending && <span className="text-slate-600">等待服务端 {pending} 返回…</span>}
          {message && <span className="text-green-700">{message}</span>}
          {error && <span className="text-amber-800">{error}</span>}
        </div>
      )}
      <TrustedHtmlArtifactRenderer
        revision={activeSkillViewRevision as any}
        onEvent={handleEvent}
      />
    </div>
  );
}
