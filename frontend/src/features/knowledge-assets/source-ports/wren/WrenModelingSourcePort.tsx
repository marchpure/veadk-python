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
import { AlertCircle, Edit3, FileJson, GitBranch, Plus, RefreshCw, Rocket, Save, Table2 } from "lucide-react";
import { useMemo, useState } from "react";

import {
  relationshipJoinFields,
  type WrenSourcePortNode,
  type WrenSourcePortViewModel,
} from "../../adapters/wrenSemanticAdapter";
import {
  formatJson,
  objectValue,
  type WrenModelingField,
  type WrenModelingMetric,
  type WrenModelingModel,
  type WrenModelingRelationship,
} from "../../../../knowledge-center/knowledgeWorkbenchUtils";
import Diagram from "./original/diagram";
import ModelingSidebar from "./original/sidebar/Modeling";
import type { ClickPayload, WrenOriginalDiagram, WrenOriginalRelationship, WrenTreeRow } from "./original/types";

export type WrenInspectorTab = "review" | "evidence" | "evals" | "advanced";

export type WrenSourcePortSelection =
  | { type: "node"; id: string; data: WrenSourcePortNode }
  | { type: "edge"; id: string; data: Record<string, unknown> }
  | { type: "field"; id: string; data: WrenModelingField; model: WrenModelingModel }
  | { type: "metric"; id: string; data: WrenModelingMetric }
  | { type: "relationship"; id: string; data: WrenModelingRelationship }
  | null;

type DraftEditorKind = "model" | "relationship" | "metric";

type ModelDraft = {
  id: string;
  displayName: string;
  table: string;
  description: string;
  fields: string;
};

type RelationshipDraft = {
  id: string;
  displayName: string;
  fromModelId: string;
  fromField: string;
  toModelId: string;
  toField: string;
  type: string;
};

type MetricDraft = {
  id: string;
  displayName: string;
  modelId: string;
  expression: string;
  definition: string;
  dimensions: string;
  filters: string;
};

const emptyModelDraft: ModelDraft = {
  id: "",
  displayName: "",
  table: "",
  description: "",
  fields: "id:string:pk\ncreated_at:timestamp",
};

const emptyRelationshipDraft: RelationshipDraft = {
  id: "",
  displayName: "",
  fromModelId: "",
  fromField: "",
  toModelId: "",
  toField: "",
  type: "many_to_one",
};

const emptyMetricDraft: MetricDraft = {
  id: "",
  displayName: "",
  modelId: "",
  expression: "",
  definition: "",
  dimensions: "",
  filters: "",
};

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
  onOpenRunDetails,
  onOpenTraining,
  onRunEval,
  onCreateView,
  onPublish,
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
  inspector: WrenInspectorTab;
  onInspectorChange: (value: WrenInspectorTab) => void;
  onSelectAsset: (id: string) => void;
  onSelectSource: (id: string) => void;
  onSelectSnapshot: (id: string) => void;
  onRefresh: () => void;
  onOpenRunDetails: () => void;
  onOpenTraining: (tab: "training" | "governance") => void;
  onRunEval: () => void;
  onCreateView: () => void;
  onPublish: () => void;
  intent: string;
  targetDomain: string;
  publish: boolean;
  onIntentChange: (value: string) => void;
  onTargetDomainChange: (value: string) => void;
  onPublishChange: (value: boolean) => void;
}) {
  const [mobilePane, setMobilePane] = useState<"tree" | "canvas" | "inspector" | "run">("canvas");
  const [draftModels, setDraftModels] = useState<WrenModelingModel[]>([]);
  const [draftRelationships, setDraftRelationships] = useState<WrenModelingRelationship[]>([]);
  const [draftMetrics, setDraftMetrics] = useState<WrenModelingMetric[]>([]);
  const [editorKind, setEditorKind] = useState<DraftEditorKind | null>(null);
  const [editorMode, setEditorMode] = useState<"new" | "edit">("new");
  const [modelDraft, setModelDraft] = useState<ModelDraft>(emptyModelDraft);
  const [relationshipDraft, setRelationshipDraft] = useState<RelationshipDraft>(emptyRelationshipDraft);
  const [metricDraft, setMetricDraft] = useState<MetricDraft>(emptyMetricDraft);
  const editableViewModel = useMemo<WrenSourcePortViewModel>(() => {
    const modeling = {
      ...viewModel.modeling,
      models: mergeById(viewModel.modeling.models, draftModels),
      relationships: mergeById(viewModel.modeling.relationships, draftRelationships),
      metrics: mergeById(viewModel.modeling.metrics, draftMetrics),
    };
    return {
      ...viewModel,
      modeling,
      mdl: mdlWithDrafts(viewModel.mdl, modeling.models, modeling.relationships, modeling.metrics),
    };
  }, [draftMetrics, draftModels, draftRelationships, viewModel]);
  const diagram = useMemo(() => toOriginalDiagram(editableViewModel), [editableViewModel]);
  const hasMdl = Boolean(Object.keys(editableViewModel.mdl).length);
  const semanticRows = viewModel.semanticAssets.map<WrenTreeRow>((asset) => ({
    id: asset.asset_id,
    title: asset.name,
    detail: `${asset.publish_state} · ${asset.version || "v1"}`,
    kind: "asset",
  }));
  const relationshipRows = editableViewModel.modeling.relationships.map(relationshipToTreeRow);
  const metricRows = editableViewModel.modeling.metrics.map(metricToTreeRow);
  const publishStatus = publishStatusText(editableViewModel);
  const publishActionReason = publishActionDisabledReason(editableViewModel);
  const canPublish = Boolean(
    editableViewModel.selectedAsset
      && editableViewModel.selectedAsset.publish_state !== "published"
      && !editableViewModel.selectedAsset.gate?.blockers?.length,
  );

  const openNewModelEditor = () => {
    const next = { ...emptyModelDraft, id: `draft_model_${draftModels.length + 1}`, displayName: "Draft Model", table: "draft_model" };
    setModelDraft(next);
    setEditorMode("new");
    setEditorKind("model");
  };

  const openNewRelationshipEditor = () => {
    const firstModel = editableViewModel.modeling.models[0];
    const secondModel = editableViewModel.modeling.models[1] ?? firstModel;
    setRelationshipDraft({
      ...emptyRelationshipDraft,
      id: `draft_relationship_${draftRelationships.length + 1}`,
      displayName: firstModel && secondModel ? `${firstModel.displayName} -> ${secondModel.displayName}` : "Draft Relationship",
      fromModelId: firstModel?.id || "",
      fromField: firstModel?.fields[0]?.name || "",
      toModelId: secondModel?.id || "",
      toField: secondModel?.fields[0]?.name || "",
    });
    setEditorMode("new");
    setEditorKind("relationship");
  };

  const openNewMetricEditor = () => {
    const firstModel = editableViewModel.modeling.models[0];
    setMetricDraft({
      ...emptyMetricDraft,
      id: `draft_metric_${draftMetrics.length + 1}`,
      displayName: "Draft Metric",
      modelId: firstModel?.id || "",
      expression: "count(*)",
      definition: "Draft metric definition",
    });
    setEditorMode("new");
    setEditorKind("metric");
  };

  const openSelectedEditor = () => {
    if (selectedItem?.type === "node") {
      const model = editableViewModel.modeling.models.find((item) => item.id === selectedItem.data.id);
      if (!model) return;
      setModelDraft(modelToDraft(model));
      setEditorMode("edit");
      setEditorKind("model");
      return;
    }
    if (selectedItem?.type === "relationship") {
      setRelationshipDraft(relationshipToDraft(selectedItem.data));
      setEditorMode("edit");
      setEditorKind("relationship");
      return;
    }
    if (selectedItem?.type === "metric") {
      setMetricDraft(metricToDraft(selectedItem.data));
      setEditorMode("edit");
      setEditorKind("metric");
    }
  };

  const saveDraft = () => {
    if (editorKind === "model") {
      const draft = draftToModel(modelDraft, editableViewModel.modeling.models.length);
      setDraftModels((current) => upsertById(current, draft));
      onSelect({ type: "node", id: draft.id, data: modelToNode(draft) });
    }
    if (editorKind === "relationship") {
      const draft = draftToRelationship(relationshipDraft, editableViewModel.modeling.relationships.length);
      setDraftRelationships((current) => upsertById(current, draft));
      onSelect({ type: "relationship", id: draft.id, data: draft });
    }
    if (editorKind === "metric") {
      const draft = draftToMetric(metricDraft, editableViewModel.modeling.metrics.length);
      setDraftMetrics((current) => upsertById(current, draft));
      onSelect({ type: "metric", id: draft.id, data: draft });
    }
    setEditorKind(null);
  };

  return (
    <section className="kc-wren-source-port adm-modeling-page" data-source-port="wren-modeling">
      <header className="adm-modeling-topbar adm-modeling-secondarybar">
        <div className="adm-modeling-actions">
          <button type="button" onClick={openNewModelEditor}>
            <Table2 className="kc-native-icon" />
            New Model
          </button>
          <button type="button" onClick={openNewRelationshipEditor} disabled={editableViewModel.modeling.models.length < 2} title={editableViewModel.modeling.models.length < 2 ? "At least two models are required." : "Create a relationship draft"}>
            <GitBranch className="kc-native-icon" />
            Relationship
          </button>
          <button type="button" onClick={openNewMetricEditor} disabled={!editableViewModel.modeling.models.length} title={!editableViewModel.modeling.models.length ? "Create or generate a model first." : "Create a metric draft"}>
            <Plus className="kc-native-icon" />
            Metric
          </button>
          <button type="button" onClick={onCreateView} disabled={!editableViewModel.selectedAsset} title={editableViewModel.selectedAsset ? "Create and persist a Semantic Builder view draft." : "Generate or select a Semantic Pack first."}>
            <Plus className="kc-native-icon" />
            New View
          </button>
          <button type="button" onClick={onRefresh}>
            <RefreshCw className="kc-native-icon" />
            Refresh
          </button>
          <button type="button" onClick={() => onInspectorChange("advanced")} disabled={!hasMdl}>
            <FileJson className="kc-native-icon" />
            Advanced
          </button>
          <button type="button" onClick={() => onOpenTraining("training")}>
            教 Agent 问数口径
          </button>
          <button type="button" onClick={() => onOpenTraining("governance")}>
            规则/禁用口径
          </button>
          <button type="button" onClick={onOpenRunDetails}>
            运行详情
          </button>
          <button type="button" onClick={onRunEval} disabled={!viewModel.selectedAsset} title={!viewModel.selectedAsset ? "Generate or select a Semantic Skill before running eval." : "Run Semantic Skill eval"}>
            运行测评
          </button>
          <button
            type="button"
            disabled={!canPublish}
            onClick={onPublish}
            title={publishActionReason}
            aria-disabled={!canPublish}
          >
            <Rocket className="kc-native-icon" />
            Publish
          </button>
        </div>
      </header>

      <div className="kc-agent-status-strip adm-deploy-status">
        <StatusChip label="构建" value={userFacingBuildStatus(editableViewModel.status.buildStatus)} />
        <StatusChip label="Agent" value={userFacingAgentStatus(editableViewModel.status.agentStatus)} />
        <StatusChip label="发布" value={publishStatus} />
      </div>

      <div className="kc-mobile-workbench-tabs" role="tablist" aria-label="Wren modeling mobile panes">
        {(["tree", "canvas", "inspector", "run"] as const).map((pane) => (
          <button
            key={pane}
            type="button"
            className={mobilePane === pane ? "is-active" : ""}
            onClick={() => {
              setMobilePane(pane);
              if (pane === "run") onOpenRunDetails();
            }}
          >
            {pane === "tree" ? "Tree" : pane === "canvas" ? "Canvas" : pane === "inspector" ? "Inspector" : "Run Details"}
          </button>
        ))}
      </div>

      <div className={`kc-wren-modeling-layout adm-sider-layout is-mobile-${mobilePane}`}>
        <ModelingSidebar
          data={diagram}
          query={query}
          onQueryChange={onQueryChange}
          onOpenModelDrawer={openNewModelEditor}
          onOpenRelationshipDrawer={openNewRelationshipEditor}
          onOpenMetricDrawer={openNewMetricEditor}
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
            onAddClick={(payload) => {
              const target = "targetNodeType" in payload ? payload.targetNodeType : "";
              if (!isModelLike(payload.data)) {
                onInspectorChange("review");
                return;
              }
              const model = payload.data;
              if (target === "relationship") {
                setRelationshipDraft({
                  ...emptyRelationshipDraft,
                  id: `draft_relationship_${draftRelationships.length + 1}`,
                  displayName: `${model.displayName} relationship`,
                  fromModelId: model.id,
                  fromField: model.fields[0]?.name || "",
                  toModelId: editableViewModel.modeling.models.find((item) => item.id !== model.id)?.id || model.id,
                  toField: "",
                });
                setEditorMode("new");
                setEditorKind("relationship");
                return;
              }
              if (target === "calculatedField") {
                setMetricDraft({
                  ...emptyMetricDraft,
                  id: `draft_metric_${draftMetrics.length + 1}`,
                  displayName: `${model.displayName} metric`,
                  modelId: model.id,
                  expression: "count(*)",
                });
                setEditorMode("new");
                setEditorKind("metric");
                return;
              }
              onInspectorChange("review");
            }}
          />
        </main>
        <MetadataDrawer
          viewModel={editableViewModel}
          selectedItem={selectedItem}
          inspector={inspector}
          onInspectorChange={onInspectorChange}
          onEditSelected={openSelectedEditor}
          intent={intent}
          targetDomain={targetDomain}
          publish={publish}
          onIntentChange={onIntentChange}
          onTargetDomainChange={onTargetDomainChange}
          onPublishChange={onPublishChange}
        />
      </div>
      {editorKind ? (
        <DraftEditor
          kind={editorKind}
          mode={editorMode}
          models={editableViewModel.modeling.models}
          modelDraft={modelDraft}
          relationshipDraft={relationshipDraft}
          metricDraft={metricDraft}
          onModelDraftChange={setModelDraft}
          onRelationshipDraftChange={setRelationshipDraft}
          onMetricDraftChange={setMetricDraft}
          onCancel={() => setEditorKind(null)}
          onSave={saveDraft}
        />
      ) : null}
    </section>
  );
}

function MetadataDrawer({
  viewModel,
  selectedItem,
  inspector,
  onInspectorChange,
  onEditSelected,
  intent,
  targetDomain,
  publish,
  onIntentChange,
  onTargetDomainChange,
  onPublishChange,
}: {
  viewModel: WrenSourcePortViewModel;
  selectedItem: WrenSourcePortSelection;
  inspector: WrenInspectorTab;
  onInspectorChange: (value: WrenInspectorTab) => void;
  onEditSelected: () => void;
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
  const summary = selectedSummary(selectedItem, viewModel);
  const semanticPackage = viewModel.selectedAsset?.capability_package ?? {};
  const docGraph = objectValue(semanticPackage.doc_graph);
  const evidence = [
    ...viewModel.modeling.evidence,
    ...arrayValue(docGraph.evidence_fragments),
    ...arrayValue(viewModel.selectedAsset?.sample_evidence),
  ];
  const alignments = arrayValue(semanticPackage.alignments);
  const ontologyCandidates = arrayValue(docGraph.ontology_candidates);
  const provenance = objectValue(viewModel.selectedAsset?.provenance);
  const permissions = objectValue(viewModel.mdl.permissions);
  const blockers = viewModel.selectedAsset?.gate?.blockers ?? [];
  return (
    <aside className="kc-wren-inspector adm-metadata-drawer" data-testid="wren-source-port-inspector">
      <div className="adm-metadata-tabs" role="tablist" aria-label="Wren metadata inspector">
        {(["review", "evidence", "evals", "advanced"] as const).map((item) => (
          <button key={item} type="button" className={inspector === item ? "is-active" : ""} onClick={() => onInspectorChange(item)}>
            {item === "review" ? "Review" : item === "evidence" ? "Evidence" : item === "evals" ? "Evals" : "Advanced"}
          </button>
        ))}
      </div>
      {inspector === "review" ? (
        <div className="adm-metadata-stack">
          <section>
            <div className="adm-section-title-row">
              <h3>{selectedTitle}</h3>
              {selectedItem && selectedItem.type !== "field" && selectedItem.type !== "edge" ? (
                <button type="button" onClick={onEditSelected}>
                  <Edit3 className="kc-native-icon" />
                  Edit
                </button>
              ) : null}
            </div>
            <dl>
              {summary.map((item) => (
                <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>
              ))}
            </dl>
          </section>
          <section>
            <h3>语义草案 Review</h3>
            <div className="kc-review-grid">
              <ReviewStat label="Models" value={viewModel.modeling.models.length} />
              <ReviewStat label="Relationships" value={viewModel.modeling.relationships.length} />
              <ReviewStat label="Metrics" value={viewModel.modeling.metrics.length} />
              <ReviewStat label="Dimensions" value={dimensionCount(viewModel)} />
              <ReviewStat label="Views" value={viewModel.modeling.views.length} />
              <ReviewStat label="Policies" value={policyCount(permissions)} />
              <ReviewStat label="Evidence" value={evidence.length} />
              <ReviewStat label="Few-shot QA" value={arrayValue(semanticPackage.few_shot).length} />
            </div>
          </section>
          <section>
            <h3>Semantic Builder</h3>
            <label><span>Domain</span><input value={targetDomain} onChange={(event) => onTargetDomainChange(event.target.value)} /></label>
            <label><span>Intent</span><textarea value={intent} onChange={(event) => onIntentChange(event.target.value)} /></label>
            <label className="kc-native-checkbox"><input type="checkbox" checked={publish} onChange={(event) => onPublishChange(event.target.checked)} /><span>Publish after build</span></label>
          </section>
          <section>
            <h3>可发布检查</h3>
            {blockers.length ? (
              <CompactJsonList items={blockers} emptyText="" />
            ) : (
              <p className="adm-empty-note">当前没有阻断项。确认 Review 后可以发布。</p>
            )}
          </section>
        </div>
      ) : inspector === "evidence" ? (
        <div className="adm-metadata-stack">
          <section>
            <h3>Ontology Candidates</h3>
            <CompactJsonList items={ontologyCandidates} emptyText="No ontology candidates were persisted yet." />
          </section>
          <section>
            <h3>Evidence</h3>
            <CompactJsonList items={evidence} emptyText="No evidence fragments in this Semantic Pack." />
          </section>
          <section>
            <h3>Alignments</h3>
            <CompactJsonList items={alignments} emptyText="No doc-to-MDL alignments persisted yet." />
          </section>
          <section>
            <h3>Provenance</h3>
            <pre className="kc-json-view"><code>{formatJson(provenance)}</code></pre>
          </section>
        </div>
      ) : (
        <div className="adm-metadata-stack">
          <section>
            <h3>Structured MDL</h3>
            <pre className="kc-json-view"><code>{formatJson(viewModel.mdl)}</code></pre>
          </section>
          <section>
            <h3>Selected Raw JSON</h3>
            <pre className="kc-json-view"><code>{formatJson(raw)}</code></pre>
          </section>
          <section>
            <h3>Validation Gate</h3>
            <pre className="kc-json-view"><code>{formatJson(viewModel.selectedAsset?.gate ?? viewModel.latestJob?.output?.gate ?? {})}</code></pre>
          </section>
          <section>
            <h3>Eval Seed</h3>
            <pre className="kc-json-view"><code>{formatJson(viewModel.selectedAsset?.capabilities?.eval_cases ?? viewModel.selectedAsset?.provenance?.validation_result ?? [])}</code></pre>
          </section>
        </div>
      )}
    </aside>
  );
}

function DraftEditor({
  kind,
  mode,
  models,
  modelDraft,
  relationshipDraft,
  metricDraft,
  onModelDraftChange,
  onRelationshipDraftChange,
  onMetricDraftChange,
  onCancel,
  onSave,
}: {
  kind: DraftEditorKind;
  mode: "new" | "edit";
  models: WrenModelingModel[];
  modelDraft: ModelDraft;
  relationshipDraft: RelationshipDraft;
  metricDraft: MetricDraft;
  onModelDraftChange: (draft: ModelDraft) => void;
  onRelationshipDraftChange: (draft: RelationshipDraft) => void;
  onMetricDraftChange: (draft: MetricDraft) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div className="adm-draft-editor-backdrop" role="presentation" onMouseDown={onCancel}>
      <section className="adm-draft-editor" role="dialog" aria-modal="true" aria-label={`${mode} ${kind}`} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>{mode === "new" ? "New" : "Edit"} {kind}</strong>
            <span>Local draft. Run Semantic Builder to regenerate and persist the pack.</span>
          </div>
          <button type="button" onClick={onCancel}>Close</button>
        </header>
        {kind === "model" ? (
          <div className="adm-draft-form">
            <label><span>ID</span><input value={modelDraft.id} onChange={(event) => onModelDraftChange({ ...modelDraft, id: event.target.value })} /></label>
            <label><span>Name</span><input value={modelDraft.displayName} onChange={(event) => onModelDraftChange({ ...modelDraft, displayName: event.target.value })} /></label>
            <label><span>Table</span><input value={modelDraft.table} onChange={(event) => onModelDraftChange({ ...modelDraft, table: event.target.value })} /></label>
            <label><span>Description</span><textarea value={modelDraft.description} onChange={(event) => onModelDraftChange({ ...modelDraft, description: event.target.value })} /></label>
            <label><span>Fields, one per line as name:type[:pk]</span><textarea value={modelDraft.fields} onChange={(event) => onModelDraftChange({ ...modelDraft, fields: event.target.value })} /></label>
          </div>
        ) : kind === "relationship" ? (
          <div className="adm-draft-form">
            <label><span>ID</span><input value={relationshipDraft.id} onChange={(event) => onRelationshipDraftChange({ ...relationshipDraft, id: event.target.value })} /></label>
            <label><span>Name</span><input value={relationshipDraft.displayName} onChange={(event) => onRelationshipDraftChange({ ...relationshipDraft, displayName: event.target.value })} /></label>
            <label><span>From model</span><select value={relationshipDraft.fromModelId} onChange={(event) => onRelationshipDraftChange({ ...relationshipDraft, fromModelId: event.target.value })}>{models.map((model) => <option key={model.id} value={model.id}>{model.displayName}</option>)}</select></label>
            <label><span>From field</span><input value={relationshipDraft.fromField} onChange={(event) => onRelationshipDraftChange({ ...relationshipDraft, fromField: event.target.value })} /></label>
            <label><span>To model</span><select value={relationshipDraft.toModelId} onChange={(event) => onRelationshipDraftChange({ ...relationshipDraft, toModelId: event.target.value })}>{models.map((model) => <option key={model.id} value={model.id}>{model.displayName}</option>)}</select></label>
            <label><span>To field</span><input value={relationshipDraft.toField} onChange={(event) => onRelationshipDraftChange({ ...relationshipDraft, toField: event.target.value })} /></label>
            <label><span>Type</span><select value={relationshipDraft.type} onChange={(event) => onRelationshipDraftChange({ ...relationshipDraft, type: event.target.value })}><option value="many_to_one">many_to_one</option><option value="one_to_many">one_to_many</option><option value="one_to_one">one_to_one</option><option value="many_to_many">many_to_many</option></select></label>
          </div>
        ) : (
          <div className="adm-draft-form">
            <label><span>ID</span><input value={metricDraft.id} onChange={(event) => onMetricDraftChange({ ...metricDraft, id: event.target.value })} /></label>
            <label><span>Name</span><input value={metricDraft.displayName} onChange={(event) => onMetricDraftChange({ ...metricDraft, displayName: event.target.value })} /></label>
            <label><span>Model</span><select value={metricDraft.modelId} onChange={(event) => onMetricDraftChange({ ...metricDraft, modelId: event.target.value })}>{models.map((model) => <option key={model.id} value={model.id}>{model.displayName}</option>)}</select></label>
            <label><span>Formula</span><textarea value={metricDraft.expression} onChange={(event) => onMetricDraftChange({ ...metricDraft, expression: event.target.value })} /></label>
            <label><span>Dimensions</span><input value={metricDraft.dimensions} onChange={(event) => onMetricDraftChange({ ...metricDraft, dimensions: event.target.value })} /></label>
            <label><span>Filters</span><input value={metricDraft.filters} onChange={(event) => onMetricDraftChange({ ...metricDraft, filters: event.target.value })} /></label>
            <label><span>Description</span><textarea value={metricDraft.definition} onChange={(event) => onMetricDraftChange({ ...metricDraft, definition: event.target.value })} /></label>
          </div>
        )}
        <footer>
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="button" className="is-primary" onClick={onSave}>
            <Save className="kc-native-icon" />
            Save Draft
          </button>
        </footer>
      </section>
    </div>
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

function isModelLike(value: unknown): value is WrenModelingModel {
  if (!value || typeof value !== "object") return false;
  return "fields" in value && "displayName" in value && "id" in value;
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

function ReviewStat({ label, value }: { label: string; value: number }) {
  return <span><strong>{value}</strong><em>{label}</em></span>;
}

function dimensionCount(viewModel: WrenSourcePortViewModel): number {
  return viewModel.modeling.models.reduce(
    (total, model) => total + model.dimensions.length,
    0,
  );
}

function policyCount(permissions: Record<string, unknown>): number {
  return Object.keys(permissions).filter((key) => permissions[key] !== undefined).length;
}

function userFacingBuildStatus(status: string): string {
  if (status === "succeeded") return "草案已生成";
  if (status === "blocked") return "需要处理";
  if (status === "failed") return "生成失败";
  if (["queued", "running", "pending", "building"].includes(status)) return "Agent 分析中";
  return "待生成";
}

function userFacingAgentStatus(status: string): string {
  if (status === "completed") return "已完成";
  if (status === "not_configured") return "模型未配置";
  if (status === "running") return "调用工具中";
  if (status === "blocked") return "被阻断";
  if (!status || status === "unknown") return "待开始";
  return status;
}

function mergeById<T extends { id: string }>(base: T[], drafts: T[]): T[] {
  const byId = new Map(base.map((item) => [item.id, item]));
  drafts.forEach((draft) => byId.set(draft.id, draft));
  return [...byId.values()];
}

function upsertById<T extends { id: string }>(items: T[], next: T): T[] {
  return [next, ...items.filter((item) => item.id !== next.id)];
}

function slug(value: string, fallback: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return normalized || fallback;
}

function parseFieldDraft(value: string): WrenModelingField[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const [namePart, typePart, flagPart] = line.split(":");
      const name = namePart?.trim() || `field_${index + 1}`;
      return {
        id: slug(name, `field_${index + 1}`),
        name,
        type: typePart?.trim() || "string",
        nodeType: "column" as const,
        isPrimaryKey: ["pk", "primary", "primary_key"].includes(String(flagPart || "").trim().toLowerCase()),
        raw: {
          id: slug(name, `field_${index + 1}`),
          name,
          type: typePart?.trim() || "string",
          primary_key: ["pk", "primary", "primary_key"].includes(String(flagPart || "").trim().toLowerCase()),
          draft: true,
        },
      };
    });
}

function draftToModel(draft: ModelDraft, index: number): WrenModelingModel {
  const id = slug(draft.id || draft.displayName || draft.table, `draft_model_${index + 1}`);
  const displayName = draft.displayName.trim() || id;
  const table = draft.table.trim() || id;
  const fields = parseFieldDraft(draft.fields);
  const raw = {
    id,
    name: displayName,
    table,
    description: draft.description,
    fields: fields.map((field) => field.raw),
    draft: true,
  };
  return {
    id,
    modelId: id,
    referenceName: table,
    displayName,
    nodeType: "MODEL",
    table,
    description: draft.description,
    fields,
    calculatedFields: [],
    relationFields: [],
    metrics: [],
    dimensions: [],
    raw,
  };
}

function draftToRelationship(draft: RelationshipDraft, index: number): WrenModelingRelationship {
  const id = slug(draft.id || draft.displayName, `draft_relationship_${index + 1}`);
  const displayName = draft.displayName.trim() || `${draft.fromModelId} -> ${draft.toModelId}`;
  return {
    id,
    displayName,
    fromModelId: draft.fromModelId,
    toModelId: draft.toModelId,
    fromField: draft.fromField,
    toField: draft.toField,
    type: draft.type || "many_to_one",
    raw: {
      id,
      label: displayName,
      from_entity: draft.fromModelId,
      to_entity: draft.toModelId,
      from_column: draft.fromField,
      to_column: draft.toField,
      type: draft.type || "many_to_one",
      draft: true,
    },
  };
}

function draftToMetric(draft: MetricDraft, index: number): WrenModelingMetric {
  const id = slug(draft.id || draft.displayName, `draft_metric_${index + 1}`);
  const displayName = draft.displayName.trim() || id;
  return {
    id,
    displayName,
    modelId: draft.modelId,
    expression: draft.expression,
    definition: draft.definition,
    raw: {
      id,
      name: displayName,
      entity: draft.modelId,
      expression: draft.expression,
      definition: draft.definition,
      dimensions: draft.dimensions.split(",").map((item) => item.trim()).filter(Boolean),
      filters: draft.filters.split(",").map((item) => item.trim()).filter(Boolean),
      draft: true,
    },
  };
}

function modelToDraft(model: WrenModelingModel): ModelDraft {
  return {
    id: model.id,
    displayName: model.displayName,
    table: model.table,
    description: model.description,
    fields: model.fields
      .map((field) => `${field.name}:${field.type}${field.isPrimaryKey ? ":pk" : ""}`)
      .join("\n"),
  };
}

function relationshipToDraft(relationship: WrenModelingRelationship): RelationshipDraft {
  return {
    id: relationship.id,
    displayName: relationship.displayName,
    fromModelId: relationship.fromModelId,
    fromField: relationship.fromField,
    toModelId: relationship.toModelId,
    toField: relationship.toField,
    type: relationship.type,
  };
}

function metricToDraft(metric: WrenModelingMetric): MetricDraft {
  const raw = metric.raw;
  return {
    id: metric.id,
    displayName: metric.displayName,
    modelId: metric.modelId,
    expression: metric.expression,
    definition: metric.definition,
    dimensions: arrayValue(raw.dimensions).map(String).join(", "),
    filters: arrayValue(raw.filters).map(String).join(", "),
  };
}

function relationshipToTreeRow(relationship: WrenModelingRelationship): WrenTreeRow {
  return {
    id: relationship.id,
    title: relationship.displayName,
    detail: `${relationship.fromModelId}.${relationship.fromField || "*"} -> ${relationship.toModelId}.${relationship.toField || "*"}`,
    kind: "relationship",
    relationship,
  };
}

function metricToTreeRow(metric: WrenModelingMetric): WrenTreeRow {
  return {
    id: metric.id,
    title: metric.displayName,
    detail: metric.modelId || "metric",
    kind: "metric",
    metric,
  };
}

function mdlWithDrafts(
  baseMdl: Record<string, unknown>,
  models: WrenModelingModel[],
  relationships: WrenModelingRelationship[],
  metrics: WrenModelingMetric[],
): Record<string, unknown> {
  return {
    ...baseMdl,
    entities: models.map((model) => model.raw),
    relationships: relationships.map((relationship) => relationship.raw),
    metrics: metrics.map((metric) => metric.raw),
  };
}

function publishStatusText(viewModel: WrenSourcePortViewModel): string {
  if (!viewModel.selectedAsset) return "select or generate a Semantic Pack first";
  if (viewModel.status.agentStatus === "not_configured") return "model not configured";
  if (viewModel.selectedAsset.publish_state === "published") return "published";
  if (viewModel.status.blockedReason && viewModel.status.blockedReason !== "none") return viewModel.status.blockedReason;
  const gate = viewModel.selectedAsset.gate;
  if (gate?.blockers?.length) return gate.blockers.join(", ");
  if (gate && gate.passed !== undefined && gate.total !== undefined && gate.passed < gate.total) return "quality gate not passed";
  return "publish from a passing semantic build";
}

function publishActionDisabledReason(viewModel: WrenSourcePortViewModel): string {
  if (viewModel.selectedAsset?.publish_state === "published") return "Already published by the validated Semantic Builder run.";
  return "Publishing is controlled by the Semantic Builder quality gate. Enable Publish after build, then run 生成/重新生成语义.";
}

function selectedSummary(
  selectedItem: WrenSourcePortSelection,
  viewModel: WrenSourcePortViewModel,
): Array<{ label: string; value: string }> {
  if (selectedItem?.type === "node") {
    return [
      { label: "Type", value: selectedItem.data.type },
      { label: "Table", value: selectedItem.data.table },
      { label: "Columns", value: String(selectedItem.data.fields.length) },
      { label: "Metrics", value: String(selectedItem.data.metrics.length + selectedItem.data.calculatedFields.length) },
    ];
  }
  if (selectedItem?.type === "field") {
    return [
      { label: "Model", value: selectedItem.model.displayName },
      { label: "Field", value: selectedItem.data.name },
      { label: "Type", value: selectedItem.data.type },
      { label: "Primary Key", value: selectedItem.data.isPrimaryKey ? "yes" : "no" },
    ];
  }
  if (selectedItem?.type === "relationship") {
    return [
      { label: "Type", value: selectedItem.data.type },
      { label: "From", value: `${selectedItem.data.fromModelId}.${selectedItem.data.fromField || "*"}` },
      { label: "To", value: `${selectedItem.data.toModelId}.${selectedItem.data.toField || "*"}` },
      { label: "Status", value: selectedItem.data.raw.draft ? "local draft" : "persisted" },
    ];
  }
  if (selectedItem?.type === "metric") {
    return [
      { label: "Model", value: selectedItem.data.modelId || "global" },
      { label: "Formula", value: selectedItem.data.expression || "n/a" },
      { label: "Definition", value: selectedItem.data.definition || "n/a" },
      { label: "Status", value: selectedItem.data.raw.draft ? "local draft" : "persisted" },
    ];
  }
  return [
    { label: "Asset", value: viewModel.selectedAsset?.name || "n/a" },
    { label: "Models", value: String(viewModel.modeling.models.length) },
    { label: "Relationships", value: String(viewModel.modeling.relationships.length) },
    { label: "Metrics", value: String(viewModel.modeling.metrics.length) },
  ];
}

function CompactJsonList({ items, emptyText }: { items: unknown[]; emptyText: string }) {
  if (!items.length) return <p className="adm-empty-note">{emptyText}</p>;
  return (
    <div className="adm-compact-json-list">
      {items.slice(0, 8).map((item, index) => (
        <article key={index}>
          <pre><code>{formatJson(item)}</code></pre>
        </article>
      ))}
    </div>
  );
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
