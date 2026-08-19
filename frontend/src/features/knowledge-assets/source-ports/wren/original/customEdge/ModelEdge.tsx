import { memo, useMemo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type Edge,
  type EdgeProps,
} from "@xyflow/react";

import type { WrenOriginalRelationship } from "../types";

export const ModelEdge = ({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerStart,
  markerEnd,
  data,
}: EdgeProps<Edge<WrenOriginalRelationship & { highlight?: boolean }>>) => {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const isPopoverShow = Boolean(data?.highlight);
  const relation = useMemo(() => {
    const fromField = `${data?.fromModelId || "source"}.${data?.fromField || data?.sourceFields?.[0] || "*"}`;
    const toField = `${data?.toModelId || "target"}.${data?.toField || data?.targetFields?.[0] || "*"}`;
    return {
      name: data?.displayName || "Relationship",
      joinType: data?.type || "many-to-one",
      description: String(data?.raw?.description || data?.raw?.label || "-"),
      fromField,
      toField,
    };
  }, [data]);

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerStart={markerStart}
        markerEnd={markerEnd}
        style={isPopoverShow ? { stroke: "var(--geekblue-6)", strokeWidth: 1.5 } : { stroke: "var(--gray-5)" }}
      />
      <EdgeLabelRenderer>
        <div
          className={`adm-edge-joint${isPopoverShow ? " is-visible" : ""}`}
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)` }}
        >
          <div className="adm-custom-popover" role="tooltip">
            <strong>Relationship</strong>
            <div className="adm-popover-row">
              <span>From</span>
              <em>{relation.fromField}</em>
            </div>
            <div className="adm-popover-row">
              <span>To</span>
              <em>{relation.toField}</em>
            </div>
            <div className="adm-popover-row">
              <span>Type</span>
              <em>{relation.joinType}</em>
            </div>
            <div className="adm-popover-row is-wide">
              <span>Description</span>
              <em>{relation.description}</em>
            </div>
          </div>
        </div>
      </EdgeLabelRenderer>
    </>
  );
};

export default memo(ModelEdge);
