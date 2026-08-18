import type {
  KnowledgeAssetEvalCase,
  KnowledgeAssetEvalRun,
  KnowledgeAssetEvalResult,
} from "../adk/knowledgeAssets";

export function EvaluationRunDetail({
  run,
  cases,
  results,
  selectedCaseId,
}: {
  run: KnowledgeAssetEvalRun | null;
  cases: KnowledgeAssetEvalCase[];
  results: KnowledgeAssetEvalResult[];
  selectedCaseId: string;
}) {
  const resultByCase = new Map(results.map((result) => [result.caseId, result]));
  const selectedCase = cases.find((item) => item.id === selectedCaseId) ?? cases[0] ?? null;
  const selectedResult = selectedCase ? resultByCase.get(selectedCase.id) ?? null : null;

  return (
    <aside className="kc-eval-run-detail" aria-label="测评运行详情">
      <header>
        <div>
          <h3>Run Detail</h3>
          <span>{run ? `${run.status} · ${run.score.toFixed(2)}` : "尚未运行"}</span>
        </div>
        {run?.modelStatus === "not_configured" ? (
          <em className="kc-eval-status is-blocked">judge not_configured</em>
        ) : null}
      </header>
      {selectedCase ? (
        <section className="kc-eval-detail-block">
          <h4>Case</h4>
          <p>{selectedCase.question || selectedCase.intent || selectedCase.input}</p>
          <dl>
            <div>
              <dt>expected metric</dt>
              <dd>{selectedCase.expectedMetric || "-"}</dd>
            </div>
            <div>
              <dt>expected policy</dt>
              <dd>{selectedCase.expectedPolicyDecision || "-"}</dd>
            </div>
          </dl>
        </section>
      ) : null}
      {selectedResult ? (
        <>
          <section className="kc-eval-detail-block">
            <h4>Evidence</h4>
            <JsonBlock value={{
              toolCalls: selectedResult.toolCalls,
              policyDecision: selectedResult.actualPolicyDecision,
              freshness: selectedResult.actualFreshness,
              evidence: selectedResult.evidence,
            }} />
          </section>
          <section className="kc-eval-detail-block">
            <h4>SQL</h4>
            <pre>{selectedResult.actualSql || "No SQL evidence"}</pre>
          </section>
          <section className="kc-eval-detail-block">
            <h4>Metric Definition / Rows</h4>
            <JsonBlock value={{
              rows: selectedResult.actualRowsPreview,
              actualOutput: selectedResult.actualOutput,
            }} />
          </section>
          <section className="kc-eval-detail-block">
            <h4>Dashboard Spec Diff</h4>
            <JsonBlock value={selectedResult.dashboardSpecDiff} />
          </section>
          <section className="kc-eval-detail-block">
            <h4>Failure Reason</h4>
            <p>{selectedResult.reason}</p>
          </section>
        </>
      ) : (
        <div className="kc-eval-empty">
          <strong>暂无运行结果</strong>
          <span>选择 suite 后点击 Run Evaluation。</span>
        </div>
      )}
    </aside>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value ?? {}, null, 2)}</pre>;
}
