import { Zap } from "lucide-react";
import type { Node, NodeProps } from "@xyflow/react";

export type CustomNodeData<T> = {
  originalData: T;
  index: number;
  highlight: string[];
} & Record<string, unknown>;

export type CustomNodeProps<T> = NodeProps<Node<CustomNodeData<T>>>;

export function StyledNode({
  children,
  onClick,
  className = "",
  dataTestId,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  className?: string;
  dataTestId?: string;
}) {
  return (
    <div className={`adm-styled-node ${className}`} onClick={onClick} data-testid={dataTestId}>
      {children}
    </div>
  );
}

export function NodeHeader({
  children,
  color,
}: {
  children: React.ReactNode;
  color?: string;
}) {
  return (
    <div className="adm-node-header dragHandle" style={color ? { backgroundColor: color } : undefined}>
      {children}
    </div>
  );
}

export function NodeBody({ children }: { children: React.ReactNode }) {
  return <div className="adm-node-body">{children}</div>;
}

export function CachedIcon({ cached }: { cached?: boolean }) {
  return cached ? <Zap className="adm-cached-icon" aria-label="Cached" /> : null;
}
