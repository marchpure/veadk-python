import { BarChart3, Database, LayoutDashboard, Search } from "lucide-react";

import type {
  KnowledgeAssetEvalSuite,
  KnowledgeAssetEvalTargetKind,
} from "../adk/knowledgeAssets";

const targetLabels: Record<KnowledgeAssetEvalTargetKind, string> = {
  semantic_skill: "Semantic Skill",
  asktable_query: "AskTable Query",
  asktable: "AskTable Query",
  dashboard_skill: "Dashboard Skill",
};

export function EvaluationSuiteList({
  suites,
  activeSuiteId,
  targetFilter,
  keyword,
  onTargetFilter,
  onKeyword,
  onSelect,
}: {
  suites: KnowledgeAssetEvalSuite[];
  activeSuiteId: string;
  targetFilter: KnowledgeAssetEvalTargetKind | "all";
  keyword: string;
  onTargetFilter: (value: KnowledgeAssetEvalTargetKind | "all") => void;
  onKeyword: (value: string) => void;
  onSelect: (suite: KnowledgeAssetEvalSuite) => void;
}) {
  return (
    <aside className="kc-eval-suite-list" aria-label="测评集列表">
      <div className="kc-eval-filter-row">
        <label>
          <span>对象</span>
          <select
            value={targetFilter}
            onChange={(event) =>
              onTargetFilter(event.target.value as KnowledgeAssetEvalTargetKind | "all")
            }
          >
            <option value="all">全部对象</option>
            <option value="semantic_skill">Semantic Skill</option>
            <option value="asktable_query">AskTable Query</option>
            <option value="dashboard_skill">Dashboard Skill</option>
          </select>
        </label>
        <label>
          <span>关键字</span>
          <div className="kc-eval-search">
            <Search className="kc-native-icon" />
            <input
              value={keyword}
              placeholder="Suite、资产或描述"
              onChange={(event) => onKeyword(event.target.value)}
            />
          </div>
        </label>
      </div>
      {suites.length === 0 ? (
        <div className="kc-eval-empty">
          <Database className="kc-native-icon" />
          <strong>暂无测评集</strong>
          <span>创建 suite 后，可导入用例并运行 deterministic checks。</span>
        </div>
      ) : (
        <div className="kc-eval-suite-items">
          {suites.map((suite) => {
            const Icon = iconForTarget(suite.targetKind);
            return (
              <button
                key={suite.id}
                type="button"
                className={suite.id === activeSuiteId ? "is-active" : ""}
                onClick={() => onSelect(suite)}
              >
                <Icon className="kc-native-icon" />
                <span>
                  <strong>{suite.name}</strong>
                  <small>
                    {targetLabels[suite.targetKind]} · {suite.caseCount} cases
                  </small>
                  <small>{suite.targetAssetId}</small>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </aside>
  );
}

export function evaluationTargetLabel(kind: KnowledgeAssetEvalTargetKind): string {
  return targetLabels[kind];
}

function iconForTarget(kind: KnowledgeAssetEvalTargetKind) {
  if (kind === "dashboard_skill") return LayoutDashboard;
  if (kind === "asktable" || kind === "asktable_query") return BarChart3;
  return Database;
}
