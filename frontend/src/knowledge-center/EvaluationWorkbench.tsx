import { Download, FileInput, Play, Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createKnowledgeAssetEvalCase,
  createKnowledgeAssetEvalSuite,
  getKnowledgeAssetEvalRun,
  importKnowledgeAssetEvalCases,
  listKnowledgeAssetEvalCases,
  listKnowledgeAssetEvalRuns,
  listKnowledgeAssetEvalSuites,
  listKnowledgeAssetOptimizations,
  runKnowledgeAssetEvaluation,
  type KnowledgeAssetEvalCaseInput,
  type KnowledgeAssetEvalCase,
  type KnowledgeAssetEvalResult,
  type KnowledgeAssetEvalRun,
  type KnowledgeAssetEvalRunDetail,
  type KnowledgeAssetEvalSuite,
  type KnowledgeAssetEvalTargetKind,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetOptimizationSnapshot,
  type KnowledgeAssetSpace,
} from "../adk/knowledgeAssets";
import { EvaluationCaseTable } from "./EvaluationCaseTable";
import { EvaluationOptimizationPanel } from "./EvaluationOptimizationPanel";
import { EvaluationRunDetail } from "./EvaluationRunDetail";
import {
  EvaluationSuiteList,
  evaluationTargetLabel,
} from "./EvaluationSuiteList";

type StatusFilter = "all" | "passed" | "failed" | "blocked" | "not_run";

export function EvaluationWorkbench({
  activeSpace,
  assets,
}: {
  activeSpace: KnowledgeAssetSpace | null;
  assets: KnowledgeAssetMetadata[];
}) {
  const [suites, setSuites] = useState<KnowledgeAssetEvalSuite[]>([]);
  const [cases, setCases] = useState<KnowledgeAssetEvalCase[]>([]);
  const [runs, setRuns] = useState<KnowledgeAssetEvalRun[]>([]);
  const [runDetail, setRunDetail] = useState<KnowledgeAssetEvalRunDetail | null>(null);
  const [optimizations, setOptimizations] = useState<KnowledgeAssetOptimizationSnapshot[]>([]);
  const [activeSuiteId, setActiveSuiteId] = useState("");
  const [createTargetKind, setCreateTargetKind] =
    useState<KnowledgeAssetEvalTargetKind>("semantic_skill");
  const [targetFilter, setTargetFilter] = useState<KnowledgeAssetEvalTargetKind | "all">("all");
  const [suiteKeyword, setSuiteKeyword] = useState("");
  const [caseTargetKind, setCaseTargetKind] = useState<KnowledgeAssetEvalTargetKind | "all">("all");
  const [caseStatus, setCaseStatus] = useState<StatusFilter>("all");
  const [caseTag, setCaseTag] = useState("");
  const [caseScoreMin, setCaseScoreMin] = useState("");
  const [caseScoreMax, setCaseScoreMax] = useState("");
  const [caseKeyword, setCaseKeyword] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [importNotice, setImportNotice] = useState("");
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const semanticSkills = assets.filter(
    (asset) =>
      asset.asset_type === "semantic_model" &&
      asset.capability_kind === "semantic_skill" &&
      asset.publish_state === "published",
  );
  const dashboardSkills = assets.filter(
    (asset) =>
      asset.asset_type === "dashboard" &&
      asset.capability_kind === "dashboard_skill" &&
      asset.publish_state === "published",
  );

  const activeSuite = suites.find((suite) => suite.id === activeSuiteId) ?? null;
  const latestRun = runDetail?.run ?? runs[0] ?? null;
  const currentResults: KnowledgeAssetEvalResult[] = runDetail?.results ?? [];

  const filteredSuites = useMemo(() => {
    const needle = suiteKeyword.trim().toLowerCase();
    return suites.filter((suite) => {
      if (targetFilter !== "all" && suite.targetKind !== targetFilter) return false;
      if (!needle) return true;
      return [
        suite.name,
        suite.description,
        suite.targetAssetId,
        evaluationTargetLabel(suite.targetKind),
      ].some((value) => String(value ?? "").toLowerCase().includes(needle));
    });
  }, [suites, suiteKeyword, targetFilter]);

  const refresh = useCallback(async (preferredSuiteId?: string) => {
    if (!activeSpace) return;
    setBusy(true);
    setError("");
    try {
      const suiteItems = await listKnowledgeAssetEvalSuites({ spaceId: activeSpace.id });
      setSuites(suiteItems);
      const nextSuiteId = preferredSuiteId && suiteItems.some((suite) => suite.id === preferredSuiteId)
        ? preferredSuiteId
        : suiteItems[0]?.id || "";
      setActiveSuiteId(nextSuiteId);
      if (nextSuiteId) {
        const [caseItems, runItems] = await Promise.all([
          listKnowledgeAssetEvalCases(nextSuiteId),
          listKnowledgeAssetEvalRuns({ suiteId: nextSuiteId, limit: 20 }),
        ]);
        setCases(caseItems);
        setRuns(runItems);
        setSelectedCaseId((prev) =>
          prev && caseItems.some((item) => item.id === prev)
            ? prev
            : caseItems[0]?.id || "",
        );
        const latest = runItems[0];
        if (latest) {
          setRunDetail(await getKnowledgeAssetEvalRun(latest.id));
        } else {
          setRunDetail(null);
        }
      } else {
        setCases([]);
        setRuns([]);
        setRunDetail(null);
      }
      setOptimizations(await listKnowledgeAssetOptimizations());
    } catch (err) {
      setError(err instanceof Error ? err.message : "测评数据读取失败。");
    } finally {
      setBusy(false);
    }
  }, [activeSpace]);

  useEffect(() => {
    void refresh(activeSuiteId);
  }, [refresh]);

  async function selectSuite(suite: KnowledgeAssetEvalSuite) {
    setActiveSuiteId(suite.id);
    setBusy(true);
    setError("");
    try {
      const [caseItems, runItems] = await Promise.all([
        listKnowledgeAssetEvalCases(suite.id),
        listKnowledgeAssetEvalRuns({ suiteId: suite.id, limit: 20 }),
      ]);
      setCases(caseItems);
      setRuns(runItems);
      setSelectedCaseId(caseItems[0]?.id || "");
      setRunDetail(runItems[0] ? await getKnowledgeAssetEvalRun(runItems[0].id) : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换测评集失败。");
    } finally {
      setBusy(false);
    }
  }

  async function createSuite(kind: KnowledgeAssetEvalTargetKind) {
    if (!activeSpace) return;
    const targetAsset = kind === "dashboard_skill"
      ? dashboardSkills[0]
      : semanticSkills[0];
    if (!targetAsset) {
      setError(kind === "dashboard_skill" ? "没有 Dashboard Skill，暂不能创建 dashboard 测评。" : "没有 Semantic Skill，请先去语义构建。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const suite = await createKnowledgeAssetEvalSuite({
        spaceId: activeSpace.id,
        name: `${targetAsset.name} ${evaluationTargetLabel(kind)} Eval`,
        targetKind: kind,
        targetAssetId: targetAsset.asset_id,
        description: "Knowledge Asset deterministic evaluation suite.",
      });
      await createKnowledgeAssetEvalCase(suite.id, defaultCasePayload(kind));
      await refresh(suite.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建测评集失败。");
    } finally {
      setBusy(false);
    }
  }

  async function addCase() {
    if (!activeSuite) return;
    setBusy(true);
    setError("");
    setImportNotice("");
    try {
      await createKnowledgeAssetEvalCase(activeSuite.id, defaultCasePayload(activeSuite.targetKind));
      await selectSuite(activeSuite);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建测评用例失败。");
    } finally {
      setBusy(false);
    }
  }

  async function importCasesFile(file: File | null) {
    if (!activeSuite || !file) return;
    setBusy(true);
    setError("");
    setImportNotice("");
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      const cases = importedCasesFromJson(parsed);
      if (cases.length === 0) {
        throw new Error("JSON 必须包含 cases 数组，且至少 1 条用例。");
      }
      const result = await importKnowledgeAssetEvalCases(activeSuite.id, cases);
      setImportNotice(`已导入 ${result.imported} 条 ${evaluationTargetLabel(activeSuite.targetKind)} cases。`);
      await selectSuite(activeSuite);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入测评用例失败。");
    } finally {
      setBusy(false);
      if (importInputRef.current) importInputRef.current.value = "";
    }
  }

  async function runEvaluation() {
    if (!activeSuite) return;
    setBusy(true);
    setError("");
    try {
      const detail = await runKnowledgeAssetEvaluation({ suiteId: activeSuite.id });
      setRunDetail(detail);
      setRuns([detail.run, ...runs.filter((run) => run.id !== detail.run.id)]);
      setOptimizations(await listKnowledgeAssetOptimizations());
      setSelectedCaseId(detail.cases[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "运行测评失败。");
    } finally {
      setBusy(false);
    }
  }

  function exportResult() {
    if (!runDetail) return;
    const payload = {
      suite: runDetail.suite,
      caseCount: runDetail.cases.length,
      runId: runDetail.run.id,
      score: runDetail.run.score,
      failedCases: runDetail.results
        .filter((result) => result.status === "failed")
        .map((result) => result.caseId),
      judgeModelStatus: runDetail.run.modelStatus,
      results: runDetail.results,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "result.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  if (!activeSpace) {
    return (
      <section className="kc-native-panel">
        <div className="kc-eval-empty">
          <strong>需要资产空间</strong>
          <span>先创建资产空间，再配置测评 suite。</span>
        </div>
      </section>
    );
  }

  return (
    <section className="kc-eval-workbench">
      <header className="kc-eval-toolbar">
        <div>
          <h2>测评</h2>
          <span>Semantic Skill、AskTable Query、Dashboard Skill 的本地 SQLite evaluation。</span>
        </div>
        <div className="kc-eval-toolbar-actions">
          <label className="kc-eval-kind-select">
            <span>创建对象</span>
            <select
              value={createTargetKind}
              onChange={(event) =>
                setCreateTargetKind(event.target.value as KnowledgeAssetEvalTargetKind)
              }
            >
              <option value="semantic_skill">Semantic Skill</option>
              <option value="asktable_query">AskTable Query</option>
              <option value="dashboard_skill">Dashboard Skill</option>
            </select>
          </label>
          <button type="button" disabled={busy || !activeSuite} onClick={runEvaluation}>
            <Play className="kc-native-icon" />
            Run Evaluation
          </button>
          <button type="button" disabled={busy} onClick={() => void createSuite(createTargetKind)}>
            <Plus className="kc-native-icon" />
            Create Suite
          </button>
          <button type="button" disabled={busy || !activeSuite} onClick={() => importInputRef.current?.click()}>
            <FileInput className="kc-native-icon" />
            Import Cases
          </button>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="kc-eval-file-input"
            onChange={(event) => void importCasesFile(event.currentTarget.files?.[0] ?? null)}
          />
          <button type="button" disabled={busy || !activeSuite} onClick={addCase}>
            <Plus className="kc-native-icon" />
            Add Default Case
          </button>
          <button type="button" disabled={!runDetail} onClick={exportResult}>
            <Download className="kc-native-icon" />
            Export result.json
          </button>
          <button type="button" disabled={busy} onClick={() => void refresh(activeSuiteId)}>
            <RefreshCw className="kc-native-icon" />
            Refresh
          </button>
        </div>
      </header>
      {error ? <div className="kc-eval-error">{error}</div> : null}
      {importNotice ? <div className="kc-eval-import-notice">{importNotice}</div> : null}
      <div className="kc-eval-schema-hint">
        Import schema: <code>{"{\"cases\":[{\"targetKind\":\"semantic_skill|asktable_query|dashboard_skill\",\"question\":\"...\",\"expectedMetric\":\"ticket_count\"}]}"}</code>
      </div>
      <div className="kc-eval-empty-states">
        {semanticSkills.length === 0 ? <span>没有 Semantic Skill，请先去语义构建。</span> : null}
        {dashboardSkills.length === 0 ? <span>没有 Dashboard Skill，dashboard 测评暂不可运行。</span> : null}
        {latestRun?.modelStatus === "not_configured" ? <span>Judge model not_configured；deterministic checks 仍可运行。</span> : null}
      </div>
      <div className="kc-eval-object-actions">
        <button type="button" disabled={busy || semanticSkills.length === 0} onClick={() => void createSuite("semantic_skill")}>
          Semantic Skill
        </button>
        <button type="button" disabled={busy || semanticSkills.length === 0} onClick={() => void createSuite("asktable_query")}>
          AskTable Query
        </button>
        <button type="button" disabled={busy || dashboardSkills.length === 0} onClick={() => void createSuite("dashboard_skill")}>
          Dashboard Skill
        </button>
      </div>
      <div className="kc-eval-grid">
        <EvaluationSuiteList
          suites={filteredSuites}
          activeSuiteId={activeSuiteId}
          targetFilter={targetFilter}
          keyword={suiteKeyword}
          onTargetFilter={setTargetFilter}
          onKeyword={setSuiteKeyword}
          onSelect={(suite) => void selectSuite(suite)}
        />
        <EvaluationCaseTable
          cases={cases}
          results={currentResults}
          targetKindFilter={caseTargetKind}
          statusFilter={caseStatus}
          tagFilter={caseTag}
          scoreMin={caseScoreMin}
          scoreMax={caseScoreMax}
          keyword={caseKeyword}
          selectedCaseId={selectedCaseId}
          onTargetKindFilter={setCaseTargetKind}
          onStatusFilter={setCaseStatus}
          onTagFilter={setCaseTag}
          onScoreMin={setCaseScoreMin}
          onScoreMax={setCaseScoreMax}
          onKeyword={setCaseKeyword}
          onSelectCase={setSelectedCaseId}
        />
        <div className="kc-eval-right-column">
          <EvaluationRunDetail
            run={latestRun}
            cases={cases}
            results={currentResults}
            selectedCaseId={selectedCaseId}
          />
          <EvaluationOptimizationPanel snapshots={optimizations} />
        </div>
      </div>
    </section>
  );
}

function defaultCasePayload(kind: KnowledgeAssetEvalTargetKind) {
  if (kind === "dashboard_skill") {
    return {
      intent: "验证 dashboard spec 与 data_view 证据完整性",
      expectedDashboardTiles: ["primary_metric"],
      expectedPolicyDecision: "allow",
      expectedEvidenceKeys: ["metric"],
      tags: ["smoke"],
    };
  }
  return {
    question: "按门店查看核心指标",
    expectedMetric: "ticket_count",
    expectedDimensions: ["store"],
    expectedSqlContains: ["SELECT"],
    expectedPolicyDecision: "allow",
    expectedEvidenceKeys: ["metric"],
    tags: ["smoke"],
  };
}

function importedCasesFromJson(value: unknown): KnowledgeAssetEvalCaseInput[] {
  const maybeCases =
    Array.isArray(value)
      ? value
      : value && typeof value === "object" && Array.isArray((value as { cases?: unknown }).cases)
        ? (value as { cases: unknown[] }).cases
        : [];
  return maybeCases.filter((item): item is KnowledgeAssetEvalCaseInput =>
    Boolean(item && typeof item === "object"),
  );
}
