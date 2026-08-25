import { useCallback } from 'react';
import { activeSkillViewRevision } from '../../../production/data';
import {
  TrustedHtmlArtifactRenderer,
  type TrustedArtifactEvent,
} from './TrustedHtmlArtifactRenderer';

export default function ChartView({ showToast }: any) {
  const handleEvent = useCallback((event: TrustedArtifactEvent) => {
    if (event.type === 'export.request') showToast?.('导出请求已交给 Studio 服务端处理。');
    if (event.type === 'context.reference') showToast?.('当前 HTML revision 已加入对话上下文。');
  }, [showToast]);

  return (
    <TrustedHtmlArtifactRenderer
      revision={activeSkillViewRevision as any}
      onEvent={handleEvent}
    />
  );
}
