import { memo, useCallback, useContext } from "react";
import { Braces, MoreHorizontal, Table2 } from "lucide-react";

import { DiagramContext } from "../Context";
import type { WrenOriginalField, WrenOriginalView } from "../types";
import type { WrenModelingField } from "../../../../../../knowledge-center/knowledgeWorkbenchUtils";
import Column from "./Column";
import MarkerHandle from "./MarkerHandle";
import { NodeBody, NodeHeader, StyledNode, type CustomNodeProps } from "./utils";

const COLUMNS_LIMIT = 9;

export const ViewNode = ({ data }: CustomNodeProps<WrenOriginalView>) => {
  const context = useContext(DiagramContext);
  const originalData = data.originalData;
  const onNodeClick = () => context?.onNodeClick({ data: originalData });
  const onMoreClick = () => context?.onMoreClick({ type: "view_more", data: originalData });
  const renderColumns = useCallback(
    (columns: WrenOriginalField[]) => getColumns(columns, data, { limit: COLUMNS_LIMIT }),
    [data],
  );

  return (
    <StyledNode onClick={onNodeClick} dataTestId={`diagram__view-node__${originalData.displayName}`} className="adm-view-node">
      <NodeHeader color="var(--green-6)">
        <span className="adm-model-header">
          <Table2 className="kc-native-icon" />
          <span className="ant-typography" title={originalData.displayName}>
            {originalData.displayName}
          </span>
        </span>
        <span className="adm-node-actions">
          <button type="button" className="adm-more-button gray-1" onClick={(event) => { event.stopPropagation(); onMoreClick(); }}>
            <MoreHorizontal className="kc-native-icon" />
          </button>
        </span>
        <MarkerHandle id={originalData.id} />
      </NodeHeader>
      <NodeBody>{renderColumns(toDisplayFields(originalData.fields))}</NodeBody>
    </StyledNode>
  );
};

export default memo(ViewNode);

function ColumnTemplate(props: WrenOriginalField & { highlight: string[] }) {
  return (
    <Column
      {...props}
      className={props.highlight.includes(props.id) || props.highlight.includes(props.name) ? "bg-gray-3" : ""}
      icon={<Braces className="kc-native-icon" />}
    />
  );
}

function getColumns(
  columns: WrenOriginalField[],
  data: CustomNodeProps<WrenOriginalView>["data"],
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

function toDisplayFields(fields: WrenModelingField[]): WrenOriginalField[] {
  return fields.map((field) => ({ ...field, displayName: field.name }));
}
