/*
 * Source-level port of Wren UI modeling workspace.
 *
 * Migrated structure:
 * - wren-ui/src/pages/modeling.tsx: modeling shell, top actions, diagram/sidebar/metadata composition.
 * - wren-ui/src/components/diagram/index.tsx: ReactFlow provider, MiniMap, Controls, edge hover.
 * - wren-ui/src/components/diagram/customNode/ModelNode.tsx and ViewNode.tsx.
 * - wren-ui/src/components/diagram/customEdge/ModelEdge.tsx and Marker.tsx.
 * - wren-ui/src/components/sidebar/Modeling.tsx plus modeling/ModelTree.tsx and ViewTree.tsx.
 *
 * Removed runtime seams: Next router, Apollo, Wren auth/project shell, antd message/dropdowns,
 * and styled-components. Data arrives through wrenSemanticAdapter from AgentKit
 * /api/knowledge-assets/* endpoints.
 */
import { AlertCircle, FileJson, Loader2, Plus, RefreshCw, Rocket } from "lucide-react";
import { useMemo, useState } from "react";

import {
  relationshipJoinFields,
  type WrenSourcePortNode,
  type WrenSourcePortTreeRow,
  type WrenSourcePortViewModel,
} from "../../adapters/wrenSemanticAdapter";
import {
  formatJson,
  type WrenModelingField,
  type WrenModelingMetric,
  type WrenModelingModel,
  type WrenModelingRelationship,
} from "../../../../knowledge-center/knowledgeWorkbenchUtils";
import Diagram from "./original/diagram";
import ModelingSidebar from "./original/sidebar/Modeling";
import type { ClickPayload, WrenOriginalDiagram, WrenOriginalRelationship, WrenTreeRow } from "./original/types";

export type WrenSourcePortSelection =
  | { type: "node"; id: string; data: WrenSourcePortNode }
  | { type: "edge"; id: string; data: Record<string, unknown> }
  | { type: "field"; id: string; data: WrenModelingField; model: WrenModelingModel }
  | { type: "metric"; id: string; data: WrenModelingMetric }
  | { type: "relationship"; id: string; data: WrenModelingRelationship }
  | null;

export function WrenModelingSourcePort({
  viewModel,
  query,
  onQueryChange,
  selectedItem,
  onSelect,
  inspector,
  onInspectorChange,
  onSelectAsset,
  onRefresh,
  onBuild,
  busy,
  intent,
  targetDomain,
  publish,
  onIntentChange,
  onTargetDomainChange,
  onPublishChange,
}: {
  viewModel: WrenSourcePortViewModel;
  treeMode: "source" | "snapshot" | "semantic";
  onTreeModeChange: (mode: "source" | "snapshot" | "semantic") => void;
  query: string;
  onQueryChange: (value: string) => void;
  selectedItem: WrenSourcePortSelection;
  onSelect: (selection: WrenSourcePortSelection) => void;
  inspector: "metadata" | "mdl" | "evals";
  onInspectorChange: (value: "metadata" | "mdl" | "evals") => void;
  onSelectAsset: (id: string) => void;
  onSelectSource: (id: string) => void;
  onSelectSnapshot: (id: string) => void;
  onRefresh: () => void;
  onBuild: () => void;
  busy: boolean;
  intent: string;
  targetDomain: string;
  publish: boolean;
  onIntentChange: (value: string) => void;
  onTargetDomainChange: (value: string) => void;
  onPublishChange: (value: boolean) => void;
}) {
  const [mobilePane, setMobilePane] = useState<"tree" | "canvas" | "metadata">("canvas");
  const diagram = useMemo(() => toOriginalDiagram(viewModel), [viewModel]);
  const hasMdl = Boolean(Object.keys(viewModel.mdl).length);
  const semanticRows = viewModel.semanticAssets.map<WrenTreeRow>((asset) => ({
    id: asset.asset_id,
    title: asset.name,
    detail: `${asset.publish_state} · ${asset.version || "v1"}`,
    kind: "asset",
  }));
  const relationshipRows = viewModel.tree.relationships.map(toOriginalTreeRow);
  const metricRows = viewModel.tree.metrics.map(toOriginalTreeRow);

  return (
    <section className="kc-wren-source-port adm-modeling-page" data-source-port="wren-modeling">
      <header className="adm-modeling-topbar">
        <div className="adm-project-return">
          <strong>Modeling</strong>
          <span>{viewModel.selectedAsset?.name || "Semantic Skill workspace"}</span>
        </div>
        <div className="adm-modeling-actions">
          <button type="button" onClick={onBuild} disabled={busy}>
            {busy ? <Loader2 className="kc-native-icon kc-spin" /> : <Plus className="kc-native-icon" />}
            Build
          </button>
          <button type="button" onClick={onRefresh}>
            <RefreshCw className="kc-native-icon" />
            Refresh
          </button>
          <button type="button" onClick={() => onInspectorChange("mdl")} disabled={!hasMdl}>
            <FileJson className="kc-native-icon" />
            MDL
          </button>
          <button type="button" disabled={!viewModel.selectedAsset}>
            <Rocket className="kc-native-icon" />
            Deploy
          </button>
        </div>
      </header>

      <div className="kc-agent-status-strip adm-deploy-status">
        <StatusChip label="Build" value={viewModel.status.buildStatus} />
        <StatusChip label="Agent" value={viewModel.status.agentStatus} />
        <StatusChip label="Runner" value={viewModel.status.runnerBackend} />
        <StatusChip label="Mode" value={viewModel.status.generationMode} />
        <StatusChip label="Blocked" value={viewModel.status.blockedReason} />
      </div>

      <div className="kc-mobile-workbench-tabs" role="tablist" aria-label="Wren modeling mobile panes">
        {(["tree", "canvas", "metadata"] as const).map((pane) => (
          <button key={pane} type="button" className={mobilePane === pane ? "is-active" : ""} onClick={() => setMobilePane(pane)}>
            {pane === "tree" ? "Models" : pane === "canvas" ? "Diagram" : "Metadata"}
          </button>
        ))}
      </div>

      <div className={`kc-wren-modeling-layout adm-sider-layout is-mobile-${mobilePane}`}>
        <ModelingSidebar
          data={diagram}
          query={query}
          onQueryChange={onQueryChange}
          onOpenModelDrawer={onBuild}
          onSelect={(row) => {
            if (row.kind === "asset") onSelectAsset(row.id);
            selectTreeRow(row, onSelect);
          }}
          semanticRows={semanticRows}
          relationshipRows={relationshipRows}
          metricRows={metricRows}
        />
        <main className="kc-wren-diagram adm-diagram-wrapper" data-testid="wren-source-port-diagram">
          {!hasMdl ? (
            <div className="kc-wren-diagram-empty">
              <AlertCircle className="kc-native-state-icon" />
              <strong>No diagram data</strong>
              <span>
                {viewModel.selectedAsset
                  ? "Current Semantic Skill has no renderable MDL yet."
                  : "Select or build a Semantic Skill to render Wren modeling nodes."}
              </span>
            </div>
          ) : null}
          <Diagram
            data={diagram}
            onMoreClick={(payload) => selectClickPayload(payload, onSelect)}
            onNodeClick={(payload) => selectClickPayload(payload, onSelect)}
            onAddClick={() => onInspectorChange("metadata")}
          />
        </main>
        <MetadataDrawer
          viewModel={viewModel}
          selectedItem={selectedItem}
          inspector={inspector}
          onInspectorChange={onInspectorChange}
          intent={intent}
          targetDomain={targetDomain}
          publish={publish}
          onIntentChange={onIntentChange}
          onTargetDomainChange={onTargetDomainChange}
          onPublishChange={onPublishChange}
        />
      </div>
    </section>
  );
}

function MetadataDrawer({
  viewModel,
  selectedItem,
  inspector,
  onInspectorChange,
  intent,
  targetDomain,
  publish,
  onIntentChange,
  onTargetDomainChange,
  onPublishChange,
}: {
  viewModel: WrenSourcePortViewModel;
  selectedItem: WrenSourcePortSelection;
  inspector: "metadata" | "mdl" | "evals";
  onInspectorChange: (value: "metadata" | "mdl" | "evals") => void;
  intent: string;
  targetDomain: string;
  publish: boolean;
  onIntentChange: (value: string) => void;
  onTargetDomainChange: (value: string) => void;
  onPublishChange: (value: boolean) => void;
}) {
  const selectedTitle =
    selectedItem?.type === "node"
      ? selectedItem.data.label
      : selectedItem?.type === "field"
        ? `${selectedItem.model.displayName}.${selectedItem.data.name}`
        : selectedItem?.type === "metric"
          ? selectedItem.data.displayName
          : selectedItem?.type === "relationship"
            ? selectedItem.data.displayName
            : viewModel.selectedAsset?.name || "Metadata";
  const raw =
    selectedItem?.type === "node"
      ? selectedItem.data.raw
      : selectedItem?.type === "field"
        ? selectedItem.data.raw
        : selectedItem?.type === "metric"
          ? selectedItem.data.raw
          : selectedItem?.type === "relationship"
            ? selectedItem.data.raw
            : selectedItem?.type === "edge"
              ? selectedItem.data
              : {};
  return (
    <aside className="kc-wren-inspector adm-metadata-drawer" data-testid="wren-source-port-inspector">
      <div className="adm-metadata-tabs" role="tablist" aria-label="Wren metadata inspector">
        {(["metadata", "mdl", "evals"] as const).map((item) => (
          <button key={item} type="button" className={inspector === item ? "is-active" : ""} onClick={() => onInspectorChange(item)}>
            {item === "metadata" ? "Metadata" : item === "mdl" ? "MDL" : "Evals"}
          </button>
        ))}
      </div>
      {inspector === "metadata" ? (
        <div className="adm-metadata-stack">
          <section>
            <h3>{selectedTitle}</h3>
            <dl>
              <div><dt>Asset</dt><dd>{viewModel.selectedAsset?.name || "n/a"}</dd></div>
              <div><dt>Version</dt><dd>{viewModel.selectedAsset?.version || "v1"}</dd></div>
              <div><dt>Gate</dt><dd>{String(viewModel.selectedAsset?.gate?.score || "n/a")}</dd></div>
              <div><dt>Source</dt><dd>{viewModel.status.runnerBackend}</dd></div>
            </dl>
          </section>
          <section>
            <h3>Semantic Builder</h3>
            <label><span>Domain</span><input value={targetDomain} onChange={(event) => onTargetDomainChange(event.target.value)} /></label>
            <label><span>Intent</span><textarea value={intent} onChange={(event) => onIntentChange(event.target.value)} /></label>
            <label className="kc-native-checkbox"><input type="checkbox" checked={publish} onChange={(event) => onPublishChange(event.target.checked)} /><span>Publish after build</span></label>
          </section>
          <section>
            <h3>Selected data</h3>
            <pre><code>{formatJson(raw)}</code></pre>
          </section>
        </div>
      ) : inspector === "mdl" ? (
        <pre className="kc-json-view"><code>{formatJson(viewModel.mdl)}</code></pre>
      ) : (
        <pre className="kc-json-view"><code>{formatJson(viewModel.selectedAsset?.capabilities?.eval_cases ?? viewModel.selectedAsset?.provenance?.validation_result ?? [])}</code></pre>
      )}
    </aside>
  );
}

function toOriginalDiagram(viewModel: WrenSourcePortViewModel): WrenOriginalDiagram {
  const relationshipFieldsByModel = new Map<string, WrenModelingField[]>();
  const relationships = viewModel.modeling.relationships.map<WrenOriginalRelationship>((relationship) => {
    const joins = relationshipJoinFields(relationship.raw);
    const sourceFields = relationship.fromField ? [relationship.fromField, ...joins.source] : joins.source;
    const targetFields = relationship.toField ? [relationship.toField, ...joins.target] : joins.target;
    relationshipFieldsByModel.set(relationship.fromModelId, [
      ...(relationshipFieldsByModel.get(relationship.fromModelId) || []),
      {
        id: relationship.fromField || relationship.id,
        name: relationship.displayName,
        type: relationship.type,
        nodeType: "relationship",
        isPrimaryKey: false,
        raw: relationship.raw,
      },
    ]);
    return { ...relationship, sourceFields, targetFields };
  });
  const withRelationships = (model: WrenModelingModel) => ({
    ...model,
    relationFields: [...model.relationFields, ...(relationshipFieldsByModel.get(model.id) || [])],
    originalData: model,
  });
  return {
    models: viewModel.modeling.models.map(withRelationships),
    views: viewModel.modeling.views.map(withRelationships),
    relationships,
    metrics: viewModel.modeling.metrics,
  };
}

function toOriginalTreeRow(row: WrenSourcePortTreeRow): WrenTreeRow {
  return {
    id: row.id,
    title: row.label,
    detail: row.detail,
    kind: row.kind,
    parentId: row.parentId,
    model: row.model,
    field: row.field,
    relationship: row.relationship,
    metric: row.metric,
  };
}

function selectTreeRow(row: WrenTreeRow, onSelect: (selection: WrenSourcePortSelection) => void) {
  if ((row.kind === "model" || row.kind === "view") && row.model) onSelect({ type: "node", id: row.model.id, data: modelToNode(row.model) });
  if (row.kind === "field" && row.model && row.field) onSelect({ type: "field", id: `${row.model.id}:${row.field.id}`, data: row.field, model: row.model });
  if (row.kind === "metric" && row.metric) onSelect({ type: "metric", id: row.metric.id, data: row.metric });
  if (row.kind === "relationship" && row.relationship) onSelect({ type: "relationship", id: row.relationship.id, data: row.relationship });
}

function selectClickPayload(payload: ClickPayload, onSelect: (selection: WrenSourcePortSelection) => void) {
  const data = payload.data as WrenModelingModel | WrenModelingRelationship | WrenModelingField | undefined;
  if (!data) return;
  if ("fromModelId" in data && "toModelId" in data) {
    onSelect({ type: "relationship", id: data.id, data });
    return;
  }
  if ("fields" in data && "displayName" in data) {
    onSelect({ type: "node", id: data.id, data: modelToNode(data) });
  }
}

function modelToNode(model: WrenModelingModel): WrenSourcePortNode {
  return {
    id: model.id,
    label: model.displayName,
    type: model.nodeType,
    table: model.table,
    description: model.description,
    fields: model.fields,
    calculatedFields: model.calculatedFields,
    relationFields: model.relationFields,
    metrics: model.metrics,
    dimensions: model.dimensions,
    raw: model.raw,
  };
}

function StatusChip({ label, value }: { label: string; value: string }) {
  return <span><strong>{label}</strong><em>{value}</em></span>;
}
