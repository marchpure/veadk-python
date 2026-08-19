import type {
  WrenModelingField,
  WrenModelingMetric,
  WrenModelingModel,
  WrenModelingRelationship,
} from "../../../../../knowledge-center/knowledgeWorkbenchUtils";

export const NODE_TYPE = {
  MODEL: "MODEL",
  VIEW: "VIEW",
  CALCULATED_FIELD: "calculatedField",
  RELATION: "relationship",
} as const;

export const EDGE_TYPE = {
  MODEL: "MODEL",
} as const;

export type WrenOriginalField = WrenModelingField & {
  displayName: string;
  modelId?: string;
};

export type WrenOriginalModel = WrenModelingModel & {
  originalData?: WrenModelingModel;
};

export type WrenOriginalView = WrenModelingModel & {
  originalData?: WrenModelingModel;
};

export type WrenOriginalRelationship = WrenModelingRelationship & {
  sourceFields: string[];
  targetFields: string[];
};

export type WrenOriginalDiagram = {
  models: WrenOriginalModel[];
  views: WrenOriginalView[];
  relationships: WrenOriginalRelationship[];
  metrics: WrenModelingMetric[];
};

export type ClickPayload =
  | { data: WrenOriginalModel | WrenOriginalView | WrenModelingField | WrenModelingRelationship }
  | { targetNodeType: string; data: WrenOriginalModel | WrenOriginalView }
  | { type: string; data: WrenOriginalModel | WrenOriginalView | WrenModelingField | WrenModelingRelationship };

export type WrenTreeRow = {
  id: string;
  title: string;
  detail: string;
  kind: "source" | "snapshot" | "asset" | "model" | "view" | "field" | "relationship" | "metric";
  parentId?: string;
  model?: WrenModelingModel;
  field?: WrenModelingField;
  relationship?: WrenModelingRelationship;
  metric?: WrenModelingMetric;
};
