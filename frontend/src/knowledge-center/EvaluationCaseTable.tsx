import type {
  KnowledgeAssetEvalCase,
  KnowledgeAssetEvalResult,
  KnowledgeAssetEvalTargetKind,
} from "../adk/knowledgeAssets";

const targetLabels: Record<KnowledgeAssetEvalTargetKind, string> = {
  semantic_skill: "Semantic Skill",
  asktable: "AskTable Query",
  dashboard_skill: "Dashboard Skill",
};

export function EvaluationCaseTable({
  cases,
  results,
  targetKindFilter,
  statusFilter,
  tagFilter,
  scoreMin,
  scoreMax,
  keyword,
  selectedCaseId,
  onTargetKindFilter,
  onStatusFilter,
  onTagFilter,
  onScoreMin,
  onScoreMax,
  onKeyword,
  onSelectCase,
}: {
  cases: KnowledgeAssetEvalCase[];
  results: KnowledgeAssetEvalResult[];
  targetKindFilter: KnowledgeAssetEvalTargetKind | "all";
  statusFilter: "all" | "passed" | "failed" | "blocked" | "not_run";
  tagFilter: string;
  scoreMin: string;
  scoreMax: string;
  keyword: string;
  selectedCaseId: string;
  onTargetKindFilter: (value: KnowledgeAssetEvalTargetKind | "all") => void;
  onStatusFilter: (value: "all" | "passed" | "failed" | "blocked" | "not_run") => void;
  onTagFilter: (value: string) => void;
  onScoreMin: (value: string) => void;
  onScoreMax: (value: string) => void;
  onKeyword: (value: string) => void;
  onSelectCase: (caseId: string) => void;
}) {
  const resultByCase = new Map(results.map((result) => [result.caseId, result]));
  const tags = Array.from(new Set(cases.flatMap((item) => item.tags))).sort();
  const min = scoreMin.trim() === "" ? Number.NaN : Number(scoreMin);
  const max = scoreMax.trim() === "" ? Number.NaN : Number(scoreMax);
  const filtered = cases.filter((item) => {
    const result = resultByCase.get(item.id);
    const status = result?.status ?? "not_run";
    if (targetKindFilter !== "all" && item.targetKind !== targetKindFilter) return false;
    if (statusFilter !== "all" && status !== statusFilter) return false;
    if (tagFilter && !item.tags.includes(tagFilter)) return false;
    if (Number.isFinite(min) && result && result.score < min) return false;
    if (Number.isFinite(max) && result && result.score > max) return false;
    const needle = keyword.trim().toLowerCase();
    if (!needle) return true;
    const haystack = [
      item.question,
      item.input,
      item.intent,
      item.expectedMetric,
      item.expectedDimensions.join(" "),
      item.expectedSqlContains.join(" "),
      targetLabels[item.targetKind],
      result?.reason,
      result?.actualSql,
    ].join(" ").toLowerCase();
    return haystack.includes(needle);
  });

  return (
    <section className="kc-eval-case-table">
      <div className="kc-eval-table-filters">
        <label>
          <span>对象</span>
          <select
            value={targetKindFilter}
            onChange={(event) =>
              onTargetKindFilter(event.target.value as KnowledgeAssetEvalTargetKind | "all")
            }
          >
            <option value="all">全部对象</option>
            <option value="semantic_skill">Semantic Skill</option>
            <option value="asktable">AskTable Query</option>
            <option value="dashboard_skill">Dashboard Skill</option>
          </select>
        </label>
        <label>
          <span>状态</span>
          <select
            value={statusFilter}
            onChange={(event) =>
              onStatusFilter(event.target.value as "all" | "passed" | "failed" | "blocked" | "not_run")
            }
          >
            <option value="all">全部</option>
            <option value="passed">passed</option>
            <option value="failed">failed</option>
            <option value="blocked">blocked</option>
            <option value="not_run">未运行</option>
          </select>
        </label>
        <label>
          <span>Tag</span>
          <select value={tagFilter} onChange={(event) => onTagFilter(event.target.value)}>
            <option value="">全部 tags</option>
            {tags.map((tag) => (
              <option key={tag} value={tag}>{tag}</option>
            ))}
          </select>
        </label>
        <label>
          <span>分数</span>
          <div className="kc-eval-score-range">
            <input
              inputMode="decimal"
              value={scoreMin}
              placeholder="0"
              onChange={(event) => onScoreMin(event.target.value)}
            />
            <input
              inputMode="decimal"
              value={scoreMax}
              placeholder="1"
              onChange={(event) => onScoreMax(event.target.value)}
            />
          </div>
        </label>
        <label>
          <span>关键字</span>
          <input
            value={keyword}
            placeholder="question / SQL / reason"
            onChange={(event) => onKeyword(event.target.value)}
          />
        </label>
      </div>
      {filtered.length === 0 ? (
        <div className="kc-eval-empty">
          <strong>暂无匹配用例</strong>
          <span>调整筛选条件，或先创建 / 导入测评用例。</span>
        </div>
      ) : (
        <div className="kc-eval-table-scroll">
          <table>
            <thead>
              <tr>
                <th>Question / Intent</th>
                <th>Expected Evidence</th>
                <th>Actual</th>
                <th>Score</th>
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => {
                const result = resultByCase.get(item.id);
                return (
                  <tr
                    key={item.id}
                    className={selectedCaseId === item.id ? "is-selected" : ""}
                    onClick={() => onSelectCase(item.id)}
                  >
                    <td>
                      <strong>{item.question || item.intent || item.input}</strong>
                      <small>{targetLabels[item.targetKind]}</small>
                      <small>{item.tags.join(" · ") || "no tags"}</small>
                    </td>
                    <td>
                      <span>{item.expectedMetric || "metric 未指定"}</span>
                      <small>{item.expectedDimensions.join(", ") || "dimensions 未指定"}</small>
                      <small>{item.expectedSqlContains.join(", ") || "SQL evidence 未指定"}</small>
                    </td>
                    <td>
                      <span>{result?.actualRowsPreview?.length ?? 0} rows</span>
                      <small>{result?.actualSql || "尚未运行"}</small>
                    </td>
                    <td>{result ? result.score.toFixed(2) : "-"}</td>
                    <td>
                      <em className={`kc-eval-status is-${result?.status ?? "not-run"}`}>
                        {result?.status ?? "not_run"}
                      </em>
                    </td>
                    <td>{result?.reason || "等待运行"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
