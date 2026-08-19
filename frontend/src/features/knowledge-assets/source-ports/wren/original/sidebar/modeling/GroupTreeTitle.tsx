import { Plus } from "lucide-react";

export function GroupTreeTitle({
  title,
  count,
  actionLabel = "New",
  onAction,
  disabledReason,
}: {
  title: string;
  count: number;
  actionLabel?: string;
  onAction?: () => void;
  disabledReason?: string;
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
      ) : disabledReason ? (
        <small className="adm-tree-disabled-reason">{disabledReason}</small>
      ) : null}
    </div>
  );
}
