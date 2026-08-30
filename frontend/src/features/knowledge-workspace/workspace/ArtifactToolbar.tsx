import type { Revision } from "../domain/types";

export function ArtifactToolbar({
  revision,
  published,
  onRun,
  onFullscreen,
  onExport,
  onShare,
  onPublish,
  onBindAgent,
  onAdvanced,
}: {
  revision: Revision | null;
  published: boolean;
  onRun: () => void;
  onFullscreen: () => void;
  onExport: () => void;
  onShare: () => void;
  onPublish: () => void;
  onBindAgent: () => void;
  onAdvanced: () => void;
}) {
  return (
    <div className="kw-artifact-toolbar">
      <button type="button" onClick={onRun}>刷新</button>
      <button type="button" onClick={onFullscreen}>全屏</button>
      <button type="button" onClick={onExport}>导出</button>
      <button type="button" onClick={onShare}>分享</button>
      <button type="button" onClick={onAdvanced}>版本 / 高级信息</button>
      <button type="button" onClick={onPublish} disabled={!revision}>{published ? `已发布 · v${revision?.number}` : "发布 Skill"}</button>
      <button type="button" className="kw-primary-small" onClick={onBindAgent}>添加到 Agent</button>
    </div>
  );
}
