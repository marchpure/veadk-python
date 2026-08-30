import {
  Download,
  Maximize2,
  RefreshCw,
  Share2,
  UserPlus,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Revision } from "../domain/types";

function IconButton({
  label,
  children,
  onClick,
  disabled,
}: {
  label: string;
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="kw-artifact-icon-button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

export function ArtifactToolbar({
  revision,
  published,
  hasArtifact,
  onRefresh,
  onFullscreen,
  onExport,
  onShare,
  onPublish,
  onBindAgent,
  onAdvanced,
}: {
  revision: Revision | null;
  published: boolean;
  hasArtifact: boolean;
  onRefresh: () => void;
  onFullscreen: () => void;
  onExport: () => void;
  onShare: () => void;
  onPublish: () => void;
  onBindAgent: () => void;
  onAdvanced: () => void;
}) {
  return (
    <div className="kw-artifact-toolbar" aria-label="Artifact 操作">
      <div className="kw-artifact-toolbar-group" aria-label="预览操作">
        <IconButton label="刷新预览" onClick={onRefresh} disabled={!hasArtifact}>
          <RefreshCw size={14} />
        </IconButton>
        <IconButton label="全屏预览" onClick={onFullscreen} disabled={!hasArtifact}>
          <Maximize2 size={14} />
        </IconButton>
        <IconButton label="下载 HTML" onClick={onExport} disabled={!hasArtifact}>
          <Download size={14} />
        </IconButton>
      </div>
      <div className="kw-artifact-toolbar-group" aria-label="协作操作">
        {published ? (
          <>
            <IconButton label="分享发布版本" onClick={onShare}>
              <Share2 size={14} />
            </IconButton>
            <button type="button" className="kw-artifact-secondary-action" onClick={onBindAgent}>
              <UserPlus size={14} />
              添加到 Agent
            </button>
          </>
        ) : null}
        <button type="button" className="kw-artifact-secondary-action" onClick={onAdvanced}>
          版本
        </button>
      </div>
      <button
        type="button"
        className="kw-artifact-publish-action"
        onClick={onPublish}
        disabled={!revision || published}
      >
        {published ? `已发布 v${revision?.number || ""}` : "发布 Skill"}
      </button>
    </div>
  );
}
