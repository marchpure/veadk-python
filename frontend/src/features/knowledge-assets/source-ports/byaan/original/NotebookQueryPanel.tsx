"use client";

import { Database, Loader2, Save } from "lucide-react";

import type { KnowledgeAssetMetadata } from "../../../../../adk/knowledgeAssets";
import { QueryEditor } from "./QueryEditor";
import { QueryResults } from "./QueryResults";
import type { QueryListItem, QueryResult } from "./types";

export function NotebookQueryPanel({
  semanticSkills,
  selectedSemanticAssetId,
  onSemanticAssetChange,
  metric,
  dimension,
  metrics,
  dimensions,
  onMetricChange,
  onDimensionChange,
  currentQuery,
  onQueryChange,
  queryResult,
  isExecuting,
  onExecute,
  onBuildDashboard,
  isBuildingDashboard,
  savedQueries = [],
}: {
  semanticSkills: KnowledgeAssetMetadata[];
  selectedSemanticAssetId: string;
  onSemanticAssetChange: (value: string) => void;
  metric: string;
  dimension: string;
  metrics: string[];
  dimensions: string[];
  onMetricChange: (value: string) => void;
  onDimensionChange: (value: string) => void;
  currentQuery: string;
  onQueryChange: (value: string) => void;
  queryResult: QueryResult | null;
  isExecuting: boolean;
  onExecute: () => void;
  onBuildDashboard: () => void;
  isBuildingDashboard: boolean;
  savedQueries?: QueryListItem[];
}) {
  const selectedSkill = semanticSkills.find((skill) => skill.asset_id === selectedSemanticAssetId) ?? semanticSkills[0] ?? null;
  return (
    <div className="kc-byaan-original-notebook h-full flex flex-col bg-[#1a1a1a]">
      <div className="kc-byaan-original-notebook-header bg-[#1a1a1a] px-4 py-3 flex items-center justify-between border-b border-[#2a2a2a]">
        <div className="kc-byaan-original-notebook-title text-sm font-medium text-white flex items-center gap-2">
          <Database className="w-3.5 h-3.5" />
          Query Runner
          <span className="text-xs text-[#888888]">{selectedSkill?.name || "No Semantic Skill"}</span>
        </div>
        <div className="kc-byaan-original-connection-bar">
          <select value={selectedSemanticAssetId} onChange={(event) => onSemanticAssetChange(event.target.value)}>
            {semanticSkills.map((skill) => (
              <option key={skill.asset_id} value={skill.asset_id}>
                {skill.name}
              </option>
            ))}
          </select>
          <select value={metric} onChange={(event) => onMetricChange(event.target.value)}>
            <option value="">Agent selects metric</option>
            {metrics.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <select value={dimension} onChange={(event) => onDimensionChange(event.target.value)}>
            <option value="">No breakdown</option>
            {dimensions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <button type="button" onClick={onBuildDashboard} disabled={isBuildingDashboard || !queryResult}>
            {isBuildingDashboard ? <Loader2 className="kc-native-icon kc-spin" /> : <Save className="kc-native-icon" />}
            Dashboard
          </button>
        </div>
      </div>
      <div className="kc-byaan-original-notebook-body">
        <div className="kc-byaan-original-editor-pane">
          <QueryEditor
            query={currentQuery}
            onQueryChange={onQueryChange}
            onExecute={onExecute}
            isExecuting={isExecuting}
            datasourceType="pg"
            savedQueries={savedQueries}
            onSaveQuery={() => undefined}
          />
        </div>
        <div className="kc-byaan-original-results-pane">
          <QueryResults queryResult={queryResult} />
        </div>
      </div>
    </div>
  );
}
