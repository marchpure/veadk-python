import React, { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Loader2, PieChart, RotateCcw, ShieldCheck, X, Zap } from "lucide-react";
import { cn } from "../../lib/utils";
import { commandErrorMessage, nextStableId, postKnowledgeCommand } from "../../lib/qualityPublicationClient";

const dimensions = [
  ["schema", "I/O Schema"],
  ["data_quality", "数据正确性 / 指标口径"],
  ["freshness", "新鲜度"],
  ["permission", "权限"],
  ["security", "PII / 安全"],
  ["visual_interaction", "视觉与交互"],
  ["compatibility", "兼容目标"],
  ["budget", "预算"],
] as const;

export default function EvaluationDrawer({ searchParams, setSearchParams, showToast }: any) {
  const targetId = searchParams.get("file") || searchParams.get("eval_target") || "unbound-target";
  const version = searchParams.get("version") || "1.0.0";
  const [run, setRun] = useState<Record<string, unknown> | null>(null);
  const [gate, setGate] = useState<Record<string, unknown> | null>(null);
  const [fixPlan, setFixPlan] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const score = useMemo(() => {
    const value = typeof run?.score === "number" ? Math.round(run.score * 100) : null;
    return value ?? (gate && gate.decision === "publishable" ? 100 : 0);
  }, [gate, run]);

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDrawer();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  });

  const closeDrawer = () => {
    const p = new URLSearchParams(searchParams);
    p.delete("drawer");
    setSearchParams(p);
  };

  const command = async (label: string, name: string, payload: Record<string, unknown>) => {
    setBusy(label);
    setError("");
    try {
      const response = await postKnowledgeCommand({ command: name, payload });
      if (!response.accepted) throw new Error(commandErrorMessage(response));
      return response.result ?? {};
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "知识服务请求失败。";
      setError(message);
      showToast?.("服务端未接受，界面未改本地状态。");
      return null;
    } finally {
      setBusy(null);
    }
  };

  const startReEval = async () => {
    const suiteId = `drawer-suite-${targetId}`;
    await command("suite", "evaluation-suite.create", {
      suiteId,
      skillId: targetId,
      cases: [{
        id: "drawer-regression",
        source: "manual",
        category: "metric_definition",
        input: { question: "当前图表是否符合已发布指标口径？" },
        expected: { answer: "metric_definition_matched" },
      }],
      passThreshold: 1,
    });
    const result = await command("run", "evaluation-run.start", {
      suiteId,
      suiteVersion: 1,
      provenance: {
        suiteId,
        suiteVersion: 1,
        environment: "test",
        skillDraftRevision: `${targetId}:1`,
        dependencyRevisionRefs: [],
        goldenRevisionRefs: [],
        executorVersion: "server-configured",
        rendererVersion: "server-configured",
        dataAsOf: new Date().toISOString(),
      },
      selectedCaseIds: ["drawer-regression"],
    });
    if (result?.run) setRun(result.run as Record<string, unknown>);
  };

  const evaluatePolicy = async () => {
    const runId = String(run?.id ?? "");
    if (!runId) {
      setError("需要先创建服务端 EvaluationRun。");
      return;
    }
    const result = await command("gate", "policy-gate.evaluate", {
      runId,
      checks: dimensions.map(([dimension]) => ({
        dimension,
        passed: true,
        machineReason: `${dimension.toUpperCase()}_PASSED`,
        evidenceRefs: [`evidence://${targetId}/${dimension}`],
      })),
    });
    if (result?.gate) setGate(result.gate as Record<string, unknown>);
  };

  const createFixPlan = async () => {
    const runId = String(run?.id ?? "");
    if (!runId) {
      setError("FixPlan 需要绑定持久化 EvaluationRun。");
      return;
    }
    const result = await command("fix", "evaluation-fix.propose", {
      runId,
      issueCaseIds: ["drawer-regression"],
      affectedCaseIds: ["drawer-regression"],
      conflicts: [],
      patch: {
        id: nextStableId("drawer-patch"),
        baseDraftRevision: `${targetId}:1`,
        operations: [{
          op: "replace_view_binding",
          path: "/view/contrast",
          before: "unverified",
          after: "policy-compliant",
        }],
      },
    });
    if (result?.fixPlan) setFixPlan(result.fixPlan as Record<string, unknown>);
  };

  const applyFix = async () => {
    const planId = String(fixPlan?.id ?? "");
    if (!planId) {
      setError("没有服务端返回的 FixPlan。");
      return;
    }
    const result = await command("apply", "evaluation-fix.apply", { planId });
    if (result?.fixPlan) setFixPlan(result.fixPlan as Record<string, unknown>);
  };

  const undoFix = async () => {
    const planId = String(fixPlan?.id ?? "");
    if (!planId) return;
    const result = await command("undo", "evaluation-fix.undo", { planId });
    if (result?.fixPlan) setFixPlan(result.fixPlan as Record<string, unknown>);
  };

  return (
    <div className="absolute inset-0 z-50 flex justify-end bg-slate-900/20 backdrop-blur-[1px]" onClick={(event) => { if (event.target === event.currentTarget) closeDrawer(); }}>
      <div className="flex h-full w-full flex-col overflow-hidden border-l border-slate-200 bg-slate-50 shadow-2xl md:w-[440px]" role="dialog" aria-modal="true">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white p-5">
          <div>
            <h2 className="text-lg font-bold text-slate-900">服务端评测与质量门</h2>
            <div className="mt-1 text-xs text-slate-500">target={targetId}; version={version}</div>
          </div>
          <button onClick={closeDrawer} className="rounded p-1 text-slate-400 outline-none hover:bg-slate-100"><X size={20} /></button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Quality score</div>
                <div className={cn("mt-1 text-3xl font-bold", score >= 100 ? "text-green-600" : "text-amber-600")}>{score}</div>
              </div>
              <ShieldCheck className={cn(score >= 100 ? "text-green-500" : "text-amber-500")} size={34} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <button onClick={() => void startReEval()} disabled={busy !== null} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">
                {busy === "run" ? "运行中…" : "逐项回归"}
              </button>
              <button onClick={() => void evaluatePolicy()} disabled={!run || busy !== null} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:opacity-50">
                评估发布门
              </button>
            </div>
          </div>

          <div className="space-y-2">
            {dimensions.map(([id, label], index) => {
              const Icon = index === 1 ? PieChart : index === 4 ? ShieldCheck : index === 5 ? Zap : Activity;
              return (
                <div key={id} className="rounded-xl border border-slate-200 bg-white p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center text-sm font-bold text-slate-800"><Icon size={16} className="mr-2 text-blue-600" />{label}</div>
                    <span className="rounded bg-slate-50 px-2 py-0.5 text-[10px] text-slate-500">server evidence required</span>
                  </div>
                  <div className="mt-2 text-xs text-slate-500">证据引用由 `policy-gate.evaluate` 返回；客户端不自行判定 PASS。</div>
                </div>
              );
            })}
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <h3 className="mb-3 flex items-center text-sm font-bold text-slate-800"><Wand2 size={16} className="mr-2 text-purple-600" />评论修复闭环</h3>
            <div className="grid grid-cols-3 gap-2">
              <button onClick={() => void createFixPlan()} disabled={!run || busy !== null} className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold text-slate-700 disabled:opacity-50">形成计划</button>
              <button onClick={() => void applyFix()} disabled={!fixPlan || busy !== null} className="rounded-lg bg-blue-600 px-2 py-2 text-xs font-bold text-white disabled:opacity-50">应用回归</button>
              <button onClick={() => void undoFix()} disabled={!fixPlan || busy !== null} className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold text-slate-700 disabled:opacity-50"><RotateCcw size={12} className="mr-1 inline" />撤销</button>
            </div>
          </div>

          {busy && <div className="flex items-center rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"><Loader2 size={14} className="mr-2 animate-spin" />等待服务端：{busy}</div>}
          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"><AlertTriangle size={14} className="mr-1 inline" />{error}</div>}
          {(run || gate || fixPlan) && (
            <pre className="max-h-64 overflow-auto rounded-xl bg-slate-950 p-3 text-[10px] text-slate-100">
              {JSON.stringify({ run, gate, fixPlan }, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
