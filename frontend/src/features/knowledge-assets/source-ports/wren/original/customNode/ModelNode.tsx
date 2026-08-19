import { memo, useCallback, useContext } from "react";
import { Braces, CircleDot, Database, MoreHorizontal, Plus, Table2 } from "lucide-react";
import { useReactFlow } from "@xyflow/react";

import { DiagramContext } from "../Context";
import { NODE_TYPE, type WrenOriginalModel, type WrenOriginalField } from "../types";
import type { WrenModelingField } from "../../../../../../knowledge-center/knowledgeWorkbenchUtils";
import Column from "./Column";
import MarkerHandle from "./MarkerHandle";
import { CachedIcon, NodeBody, NodeHeader, StyledNode, type CustomNodeProps } from "./utils";

const COLUMNS_LIMIT = 9;

export const ModelNode = ({ data }: CustomNodeProps<WrenOriginalModel>) => {
  const context = useContext(DiagramContext);
  const originalData = data.originalData;
  const onNodeClick = () => context?.onNodeClick({ data: originalData });
  const onMoreClick = () => context?.onMoreClick({ type: "model_more", data: originalData });
  const onAddClick = (targetNodeType: string) => context?.onAddClick({ targetNodeType, data: originalData });
  const renderColumns = useCallback(
    (columns: WrenOriginalField[]) => getColumns(columns, data, { limit: COLUMNS_LIMIT }),
    [data],
  );

  return (
    <StyledNode onClick={onNodeClick} dataTestId={`diagram__model-node__${originalData.displayName}`}>
      <NodeHeader>
        <span className="adm-model-header">
          <Database className="kc-native-icon" />
          <span className="ant-typography" title={originalData.displayName}>
            {originalData.displayName}
          </span>
        </span>
        <span className="adm-node-actions">
          <CachedIcon cached={Boolean((originalData.raw as Record<string, unknown>).cached)} />
          <button type="button" className="adm-more-button gray-1" onClick={(event) => { event.stopPropagation(); onMoreClick(); }}>
            <MoreHorizontal className="kc-native-icon" />
          </button>
        </span>
        <MarkerHandle id={originalData.id.toString()} />
      </NodeHeader>
      <NodeBody>
        <Column.Title show>Columns</Column.Title>
        {renderColumns(toDisplayFields(originalData.fields, originalData.id))}
        <Column.Title
          show
          extra={
            <button type="button" className="adm-add-button gray-8" onClick={(event) => { event.stopPropagation(); onAddClick(NODE_TYPE.CALCULATED_FIELD); }}>
              <Plus className="kc-native-icon" />
            </button>
          }
        >
          Calculated Fields
        </Column.Title>
        {renderColumns(toDisplayFields(originalData.calculatedFields, originalData.id))}
        <Column.Title
          show
          extra={
            <button type="button" className="adm-add-button gray-8" onClick={(event) => { event.stopPropagation(); onAddClick(NODE_TYPE.RELATION); }}>
              <Plus className="kc-native-icon" />
            </button>
          }
        >
          Relationships
        </Column.Title>
        {renderColumns(toDisplayFields(originalData.relationFields, originalData.id))}
      </NodeBody>
    </StyledNode>
  );
};

export default memo(ModelNode);

function ColumnTemplate(props: WrenOriginalField & { highlight: string[] }) {
  const reactflowInstance = useReactFlow();
  const context = useContext(DiagramContext);
  const isRelationship = props.nodeType === "relationship";
  const highlighted = props.highlight.includes(props.id) || props.highlight.includes(props.name);

  const onMouseEnter = useCallback(() => {
    if (!isRelationship) return;
    const edge = reactflowInstance
      .getEdges()
      .find((candidate) => String(candidate.sourceHandle || "").includes(props.id) || String(candidate.targetHandle || "").includes(props.id));
    if (!edge) return;
    reactflowInstance.setEdges((edges) => edges.map((item) => ({ ...item, className: item.id === edge.id ? "is-hovered" : item.className })));
  }, [isRelationship, props.id, reactflowInstance]);

  const onMouseLeave = useCallback(() => {
    if (!isRelationship) return;
    reactflowInstance.setEdges((edges) => edges.map((item) => ({ ...item, className: String(item.className || "").replace("is-hovered", "").trim() })));
  }, [isRelationship, reactflowInstance]);

  return (
    <Column
      {...props}
      className={highlighted ? "bg-gray-3" : ""}
      icon={isRelationship ? <Table2 className="kc-native-icon" /> : props.isPrimaryKey ? <CircleDot className="kc-native-icon" /> : <Braces className="kc-native-icon" />}
      extra={
        isRelationship || props.nodeType === "calculatedField" ? (
          <button
            type="button"
            className="adm-more-button gray-8"
            onClick={(event) => {
              event.stopPropagation();
              context?.onMoreClick({ type: props.nodeType, data: props });
            }}
          >
            <MoreHorizontal className="kc-native-icon" />
          </button>
        ) : props.isPrimaryKey ? (
          <CircleDot className="kc-native-icon adm-primary-key" />
        ) : null
      }
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    />
  );
}

function getColumns(
  columns: WrenOriginalField[],
  data: CustomNodeProps<WrenOriginalModel>["data"],
  pagination?: { limit: number },
) {
  const moreCount = pagination ? columns.length - pagination.limit : 0;
  const slicedColumns = pagination ? columns.slice(0, pagination.limit) : columns;
  return (
    <>
      {slicedColumns.map((column) => (
        <ColumnTemplate key={column.id} {...column} highlight={data.highlight} />
      ))}
      {moreCount > 0 ? <Column.MoreTip count={moreCount} /> : null}
    </>
  );
}

function toDisplayFields(fields: WrenModelingField[], modelId: string): WrenOriginalField[] {
  return fields.map((field) => ({
    ...field,
    modelId,
    displayName: field.name,
  }));
}
