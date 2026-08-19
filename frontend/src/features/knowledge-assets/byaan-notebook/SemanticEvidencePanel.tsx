import { FileCode2, LineChart, Network, ShieldCheck } from "lucide-react";

import type { ByaanSemanticQueryResultEvent } from "./types";

export function SemanticEvidencePanel({
  event,
  dashboardAvailable,
  busy,
  onCreateDashboard,
  createDashboardDisabled = false,
  createDashboardDisabledReason = "",
}: {
  event: ByaanSemanticQueryResultEvent | null;
  dashboardAvailable: boolean;
  busy: boolean;
  onCreateDashboard: () => void;
  createDashboardDisabled?: boolean;
  createDashboardDisabledReason?: string;
}) {
  if (!event) return null;
  const result = event.result;
  const sql = result.sql || "";
  return (
    <div className="byaan-semantic-evidence mx-auto mb-2 flex w-full max-w-3xl flex-col gap-2 px-4 sm:flex-row sm:items-start sm:px-6 min-[1440px]:max-w-4xl min-[2560px]:max-w-[1400px]">
      <details className="min-w-0 flex-1">
        <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 rounded-md border border-[#e4e4e7] bg-white px-3 text-xs text-[#4f5159] hover:border-[#d4d4d8] hover:bg-[#f4f4f5]">
          <span className="flex min-w-0 items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
            <span className="truncate">Governed evidence · {result.resolvedMetric || "Semantic metric"}</span>
          </span>
          <span className="shrink-0 text-[11px] text-[#707078]">{result.modelVersion || "Published"} · {result.policyDecision || "checked"}</span>
        </summary>
        <div className="grid gap-px overflow-hidden rounded-b-md border border-t-0 border-[#e4e4e7] bg-[#e4e4e7] text-xs sm:grid-cols-2 lg:grid-cols-4">
          <EvidenceCell label="Freshness" value={formatEvidenceTime(result.dataThrough || String(result.freshness.status || ""))} />
          <EvidenceCell label="Snapshot" value={result.snapshotId || "Published contract"} />
          <EvidenceCell label="Lineage" value={`${result.lineage.length} reference${result.lineage.length === 1 ? "" : "s"}`} />
          <EvidenceCell label="Policy" value={result.policyDecision || "checked"} success />
          {result.metricDefinition ? (
            <div className="bg-white p-3 sm:col-span-2 lg:col-span-4">
              <div className="text-[#707078]">Metric definition</div>
              <div className="mt-1 leading-relaxed text-[#18181b]">{result.metricDefinition}</div>
            </div>
          ) : null}
          {result.lineage.length ? (
            <div className="bg-white p-3 sm:col-span-2 lg:col-span-4">
              <div className="mb-2 flex items-center gap-1.5 text-[#707078]"><Network className="h-3.5 w-3.5" />Lineage</div>
              <div className="flex flex-wrap gap-1.5">
                {result.lineage.map((item, index) => (
                  <span key={index} className="rounded border border-[#e4e4e7] bg-[#f4f4f5] px-2 py-1 text-[11px] text-[#4f5159]">
                    {lineageLabel(item, index)}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {sql ? (
            <div className="bg-[#f4f4f5] p-3 sm:col-span-2 lg:col-span-4">
              <div className="mb-2 flex items-center gap-1.5 text-[#707078]"><FileCode2 className="h-3.5 w-3.5" />Compiled SQL</div>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-[#4f5159]">{sql}</pre>
            </div>
          ) : null}
        </div>
      </details>
      {!dashboardAvailable ? (
        <button
          type="button"
          onClick={onCreateDashboard}
          disabled={busy || createDashboardDisabled}
          title={createDashboardDisabled ? createDashboardDisabledReason : "Create dashboard"}
          className="flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-md border border-[#d4d4d8] bg-white px-3 text-xs text-[#4f5159] hover:border-[#0081f2]/40 hover:bg-[#0081f2]/[0.06] hover:text-[#18181b] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <LineChart className="h-3.5 w-3.5 text-[#0081f2]" />
          Create dashboard
        </button>
      ) : null}
    </div>
  );
}

function EvidenceCell({ label, value, success = false }: { label: string; value: string; success?: boolean }) {
  return (
    <div className="bg-white p-3">
      <div className="text-[#707078]">{label}</div>
      <div className={`mt-1 break-words ${success ? "text-emerald-600" : "text-[#18181b]"}`}>{value || "Not reported"}</div>
    </div>
  );
}

function formatEvidenceTime(value?: string | null) {
  if (!value) return "Not reported";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function lineageLabel(item: unknown, index: number) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return `Reference ${index + 1}`;
  const record = item as Record<string, unknown>;
  return String(record.name || record.title || record.table || record.ref || record.id || `Reference ${index + 1}`);
}
