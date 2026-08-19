import { ArrowLeft, Database } from "lucide-react";

import { NotebookQueryPanel } from "./NotebookQueryPanel";
import type { QueryResult } from "./types";
import type { KnowledgeAssetMetadata } from "../../../../../adk/knowledgeAssets";

export default function QueryRunnerDocked({
  semanticSkills,
  selectedSemanticAssetId,
  onSemanticAssetChange,
  metric,
  dimension,
  metrics,
  dimensions,
  onMetricChange,
  onDimensionChange,
  initialQuery,
  onQueryChange,
  queryResult,
  isExecuting,
  onExecute,
  onBuildDashboard,
  isBuildingDashboard,
  onBack,
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
  initialQuery: string;
  onQueryChange: (value: string) => void;
  queryResult: QueryResult | null;
  isExecuting: boolean;
  onExecute: () => void;
  onBuildDashboard: () => void;
  isBuildingDashboard: boolean;
  onBack?: () => void;
}) {
  return (
    <div className="kc-byaan-query-runner h-full flex flex-col">
      <div className="bg-[#1a1a1a] px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {onBack ? (
            <button type="button" onClick={onBack} className="px-2 py-1 text-xs bg-transparent hover:bg-[#2a2a2a] text-white border border-[#404040] rounded-md transition-colors flex items-center gap-1" title="Back to versions">
              <ArrowLeft className="w-3 h-3" />
              Versions
            </button>
          ) : null}
          <div className="text-sm font-medium text-white flex items-center gap-2">
            <Database className="w-3.5 h-3.5" />
            Query Runner
          </div>
        </div>
        <div />
      </div>
      <div className="flex-1 min-h-0">
        <NotebookQueryPanel
          semanticSkills={semanticSkills}
          selectedSemanticAssetId={selectedSemanticAssetId}
          onSemanticAssetChange={onSemanticAssetChange}
          metric={metric}
          dimension={dimension}
          metrics={metrics}
          dimensions={dimensions}
          onMetricChange={onMetricChange}
          onDimensionChange={onDimensionChange}
          currentQuery={initialQuery}
          onQueryChange={onQueryChange}
          queryResult={queryResult}
          isExecuting={isExecuting}
          onExecute={onExecute}
          onBuildDashboard={onBuildDashboard}
          isBuildingDashboard={isBuildingDashboard}
        />
      </div>
    </div>
  );
}
