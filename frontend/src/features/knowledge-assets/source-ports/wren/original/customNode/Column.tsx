import type { ReactNode } from "react";

import MarkerHandle from "./MarkerHandle";

export function Column({
  id,
  type,
  displayName,
  icon,
  extra,
  className = "",
  onMouseEnter,
  onMouseLeave,
}: {
  id: number | string;
  type: string;
  displayName: string;
  icon: ReactNode;
  extra?: ReactNode;
  className?: string;
  onMouseEnter?: (event: React.MouseEvent) => void;
  onMouseLeave?: (event: React.MouseEvent) => void;
}) {
  return (
    <div className={`adm-node-column ${className}`} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <div className="adm-column-title">
        <span className="d-inline-flex flex-shrink-0" title={type}>
          {icon}
        </span>
        <span title={displayName}>{displayName}</span>
      </div>
      {extra ? <span className="adm-column-extra">{extra}</span> : null}
      <MarkerHandle id={id.toString()} />
    </div>
  );
}

function ColumnTitle({
  show,
  extra,
  children,
}: {
  show: boolean;
  extra?: ReactNode;
  children: ReactNode;
}) {
  if (!show) return null;
  return (
    <div className="adm-column-section-title">
      {children}
      <span>{extra}</span>
    </div>
  );
}

function MoreTip({ count }: { count: number }) {
  if (count <= 0) return null;
  return <div className="text-sm gray-7 px-3 py-1">and {count} more</div>;
}

Column.Title = ColumnTitle;
Column.MoreTip = MoreTip;

export default Column;
