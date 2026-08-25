import { useCallback } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import {
  TrustedHtmlArtifactRenderer,
  type TrustedArtifactEvent,
} from './TrustedHtmlArtifactRenderer';

export default function DashboardView({ showToast }: any) {
  const handleEvent = useCallback((event: TrustedArtifactEvent) => {
    if (event.type === 'filter.change') {
      showToast?.(`筛选请求：${event.field ?? '维度'} = ${event.value || '全部'}`);
    } else if (event.type === 'drill.request') {
      showToast?.(`钻取请求：${event.value ?? event.elementId ?? '当前元素'}`);
    } else if (event.type === 'selection.change') {
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
    } else if (event.type === 'context.reference') {
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
    } else if (event.type === 'export.request') {
      showToast?.('导出请求已交给 Studio 服务端处理。');
    } else if (event.type === 'refresh.request') {
      showToast?.('刷新请求已交给 Runner；当前 revision 保持可读。');
    }
  }, [showToast]);

  return (
    <TrustedHtmlArtifactRenderer
      revision={activeSkillViewRevision as any}
      onEvent={handleEvent}
    />
  );
}
