import type { Edge, Node } from "@xyflow/react";

export function trimId(id: string) {
  return id.replace(/_(left|right|top|bottom)$/i, "");
}

export function highlightNodes<T extends Record<string, unknown>>(
  nodes: Node<T>[],
  ids: string[],
  fieldIds: string[],
) {
  return nodes.map((node) => ({
    ...node,
    className: ids.includes(node.id) ? "is-highlighted" : "",
    data: {
      ...node.data,
      highlight: ids.includes(node.id) ? fieldIds : [],
    },
  }));
}

export function highlightEdges<T extends Record<string, unknown>>(edges: Edge<T>[], ids: string[]) {
  return edges.map((edge) => ({
    ...edge,
    className: ids.includes(edge.id) ? "is-hovered" : "",
    data: {
      ...(edge.data || ({} as T)),
      highlight: ids.includes(edge.id),
    },
  }));
}
