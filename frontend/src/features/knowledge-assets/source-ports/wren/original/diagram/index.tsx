import dagre from "@dagrejs/dagre";
import {
  Background,
  ControlButton,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { RotateCcw } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from "react";

import { EDGE_TYPE, NODE_TYPE, type ClickPayload, type WrenOriginalDiagram, type WrenOriginalRelationship } from "../types";
import { ModelNode, ViewNode } from "../customNode";
import ModelEdge from "../customEdge/ModelEdge";
import { DiagramContext } from "../Context";
import Marker from "../Marker";
import { highlightEdges, highlightNodes, trimId } from "./utils";

type DiagramNodeData = {
  originalData: WrenOriginalDiagram["models"][number] | WrenOriginalDiagram["views"][number];
  index: number;
  highlight: string[];
} & Record<string, unknown>;

type DiagramEdgeData = WrenOriginalRelationship & { highlight?: boolean } & Record<string, unknown>;

const nodeTypes = {
  [NODE_TYPE.MODEL]: ModelNode,
  [NODE_TYPE.VIEW]: ViewNode,
};

const edgeTypes = {
  [EDGE_TYPE.MODEL]: ModelEdge,
};

const minimapStyle = {
  height: 120,
};

export interface DiagramProps {
  forwardRef?: React.ForwardedRef<unknown>;
  data: WrenOriginalDiagram;
  onMoreClick: (data: ClickPayload) => void;
  onNodeClick: (data: ClickPayload) => void;
  onAddClick: (data: ClickPayload) => void;
}

const ReactFlowDiagram = forwardRef(function ReactFlowDiagram(props: DiagramProps, ref) {
  const { data, onMoreClick, onNodeClick, onAddClick } = props;
  const reactFlowInstance = useReactFlow();
  useImperativeHandle(ref, () => reactFlowInstance, [reactFlowInstance]);
  const diagram = useMemo(() => createDiagram(data), [data]);
  const [nodes, setNodes] = useState(diagram.nodes);
  const [edges, setEdges] = useState(diagram.edges);

  useEffect(() => {
    setNodes(diagram.nodes);
    setEdges(diagram.edges);
    const id = window.setTimeout(() => reactFlowInstance.fitView({ padding: 0.2 }), 50);
    return () => window.clearTimeout(id);
  }, [diagram, reactFlowInstance]);

  const onEdgeMouseEnter = (_event: React.MouseEvent, edge: Edge<DiagramEdgeData>) => {
    const sourceField = trimId(String(edge.sourceHandle || edge.data?.sourceFields?.[0] || ""));
    const targetField = trimId(String(edge.targetHandle || edge.data?.targetFields?.[0] || ""));
    setEdges((current) => highlightEdges(current, [edge.id]));
    setNodes((current) => highlightNodes(current, [edge.source, edge.target], [sourceField, targetField]));
  };

  const onEdgeMouseLeave = () => {
    setEdges((current) => highlightEdges(current, []));
    setNodes((current) => highlightNodes(current, [], []));
  };

  const onRestore = async () => {
    setNodes(diagram.nodes);
    setEdges(diagram.edges);
    window.setTimeout(() => reactFlowInstance.fitView({ padding: 0.2 }), 0);
  };

  return (
    <>
      <DiagramContext.Provider value={{ onMoreClick, onNodeClick, onAddClick }}>
        <ReactFlow<Node<DiagramNodeData>, Edge<DiagramEdgeData>>
          nodes={nodes}
          edges={edges}
          onNodesChange={() => undefined}
          onEdgesChange={() => undefined}
          onEdgeMouseEnter={onEdgeMouseEnter}
          onEdgeMouseLeave={onEdgeMouseLeave}
          onNodeClick={(_, node) => onNodeClick({ data: node.data.originalData })}
          onEdgeClick={(_, edge) => edge.data && onMoreClick({ type: "relationship", data: edge.data })}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          maxZoom={1}
          minZoom={0.18}
          proOptions={{ hideAttribution: true }}
        >
          <MiniMap style={minimapStyle} zoomable pannable />
          <Controls showInteractive={false}>
            <ControlButton onClick={onRestore}>
              <RotateCcw className="kc-native-icon" />
            </ControlButton>
          </Controls>
          <Background gap={16} />
        </ReactFlow>
      </DiagramContext.Provider>
      <Marker />
    </>
  );
});

export default function Diagram(props: DiagramProps) {
  return (
    <ReactFlowProvider>
      <ReactFlowDiagram ref={props.forwardRef} {...props} />
    </ReactFlowProvider>
  );
}

function createDiagram(data: WrenOriginalDiagram): {
  nodes: Node<DiagramNodeData>[];
  edges: Edge<DiagramEdgeData>[];
} {
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "LR", nodesep: 70, ranksep: 120, marginx: 24, marginy: 24 });
  const allNodes = [...data.models, ...data.views];
  allNodes.forEach((node) => graph.setNode(node.id, { width: 200, height: 290 }));
  data.relationships.forEach((relationship) => graph.setEdge(relationship.fromModelId, relationship.toModelId));
  dagre.layout(graph);
  return {
    nodes: allNodes.map((node, index) => {
      const layout = graph.node(node.id);
      return {
        id: node.id,
        type: node.nodeType,
        position: { x: (layout?.x ?? 0) - 100, y: (layout?.y ?? 0) - 145 },
        data: { originalData: node, index, highlight: [] },
        dragHandle: ".dragHandle",
      };
    }),
    edges: data.relationships
      .filter(
        (relationship) =>
          allNodes.some((node) => node.id === relationship.fromModelId) &&
          allNodes.some((node) => node.id === relationship.toModelId),
      )
      .map((relationship) => ({
        id: relationship.id,
        type: EDGE_TYPE.MODEL,
        source: relationship.fromModelId,
        target: relationship.toModelId,
        sourceHandle: `${relationship.sourceFields[0] || relationship.fromField || relationship.fromModelId}_right`,
        targetHandle: `${relationship.targetFields[0] || relationship.toField || relationship.toModelId}_left`,
        markerStart: "url(#one_right)",
        markerEnd: "url(#many_right)",
        data: relationship,
      })),
  };
}
