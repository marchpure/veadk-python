import { useCallback, useState } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import { createRequestContext } from '../../../production/ports';
import { getWorkspaceAdapter } from '../../../production/store';
import {
  TrustedHtmlArtifactRenderer,
  type TrustedArtifactEvent,
} from './TrustedHtmlArtifactRenderer';

export default function ChartView({ fileId }: any) {
  const [pending, setPending] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const handleEvent = useCallback((event: TrustedArtifactEvent) => {
    setMessage('');
    setError('');
    if (event.type === 'context.reference' || event.type === 'selection.change') {
      window.dispatchEvent(new CustomEvent('add_context_item', {
        detail: {
          item: {
            id: event.elementId ?? event.revisionId,
            name: event.elementId ?? `HTML revision ${event.revisionId}`,
            type: event.type === 'context.reference' ? 'artifact' : 'element',
            viewRevisionId: event.revisionId,
            isResourceLevel: event.type === 'context.reference',
          },
        },
      }));
      return;
    }
    if (event.type === 'export.request') {
      const resourceId = event.revisionId || fileId;
      setPending('artifact.export');
      void getWorkspaceAdapter().command({
        command: 'artifact.export',
        payload: {
          resourceId,
          format: event.format === 'csv' || event.format === 'json' ? event.format : 'html',
        },
      }, createRequestContext())
        .then((response) => {
          if (!response.accepted) throw new Error('服务端未接受 artifact.export。');
          setMessage(`artifact.export accepted: ${response.operationId ?? response.requestId}`);
        })
        .catch((cause) => {
          setError(cause instanceof Error ? cause.message : 'artifact.export 失败。');
        })
        .finally(() => setPending(''));
      return;
    }
    setError('该 HTML 交互需要 W3 artifact interaction command seam；当前不会生成本地成功态。');
  }, [fileId]);

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
