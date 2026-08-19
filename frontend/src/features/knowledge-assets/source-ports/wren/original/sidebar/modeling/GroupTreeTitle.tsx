import { MoreHorizontal, Plus } from "lucide-react";

export function GroupTreeTitle({
  title,
  count,
  actionLabel = "New",
  onAction,
}: {
  title: string;
  count: number;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="adm-tree-group-title">
      <span>
        {title}
        <em>{count}</em>
      </span>
      {onAction ? (
        <button type="button" className="adm-tree-new" onClick={onAction}>
          <Plus className="kc-native-icon" />
          {actionLabel}
        </button>
      ) : (
        <button type="button" className="adm-tree-more" aria-label={`${title} actions`}>
          <MoreHorizontal className="kc-native-icon" />
        </button>
      )}
    </div>
  );
}
