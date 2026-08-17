import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Check,
  Database,
  Info,
  Loader2,
  Plus,
  Search,
} from "lucide-react";
import {
  DataStudioError,
  dataStudioAssetToHit,
  listDataStudioAssets,
} from "./skills/datastudio";
import type { SelectedSkill, SkillHit } from "./skills/types";
import { displayDescription } from "./displayText";

const PAGE_SIZE = 6;

function typeLabel(type?: string): string {
  return type === "dashboard" ? "Dashboard" : "语义模型";
}

function toSelected(hit: SkillHit): SelectedSkill {
  return {
    source: "datastudio",
    folder: hit.folder || hit.id.replace(/[^a-z0-9-]+/gi, "-").toLowerCase(),
    name: hit.name,
    description: hit.description,
    dataStudioAssetType: hit.dataStudioAssetType,
    dataStudioAssetId: hit.dataStudioAssetId,
    dataStudioVersion: hit.dataStudioVersion,
    dataStudioGateScore: hit.dataStudioGateScore,
    dataStudioMetrics: hit.dataStudioMetrics,
    dataStudioExampleQuestions: hit.dataStudioExampleQuestions,
    dataStudioPermissionHint: hit.dataStudioPermissionHint,
    dataStudioQueryUrl: hit.dataStudioQueryUrl,
    dataStudioTimeField: hit.dataStudioTimeField,
    dataStudioDimensions: hit.dataStudioDimensions,
    dataStudioEvidence: hit.dataStudioEvidence,
  };
}

export function dataStudioSelectionKey(
  s: Pick<SelectedSkill, "dataStudioAssetType" | "dataStudioAssetId">,
): string {
  return `${s.dataStudioAssetType}:${s.dataStudioAssetId}`;
}

export function dataStudioEmptyStateText({
  error,
  query,
}: {
  error: { status: number; message: string } | null;
  query: string;
}): string {
  if (error) {
    if (error.status === 409) {
      return "未配置连接：请在服务端配置 Data Studio 连接，或临时开启 mock。";
    }
    if (error.status === 401) return "未登录：请先登录 Studio。";
    return error.message || "Byaan Data Studio 不可达。";
  }
  return query.trim() ? "搜索无结果，换个关键词试试。" : "暂无已发布资产。";
}

export function toggleDataStudioSelection(
  selected: SelectedSkill[],
  hit: SkillHit,
): SelectedSkill[] {
  const key = `${hit.dataStudioAssetType}:${hit.dataStudioAssetId}`;
  if (
    selected
      .filter((s) => s.source === "datastudio")
      .some((item) => dataStudioSelectionKey(item) === key)
  ) {
    return selected.filter(
      (item) =>
        item.source !== "datastudio" || dataStudioSelectionKey(item) !== key,
    );
  }
  return [...selected, toSelected(hit)];
}

export function DataStudioAssetPicker({
  selected,
  onChange,
}: {
  selected: SelectedSkill[];
  onChange: (next: SelectedSkill[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [hits, setHits] = useState<SkillHit[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ status: number; message: string } | null>(
    null,
  );

  useEffect(() => {
    const timer = setTimeout(() => setPage(1), 250);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listDataStudioAssets({ query, page, pageSize: PAGE_SIZE })
      .then((payload) => {
        if (cancelled) return;
        setHits(payload.assets.map(dataStudioAssetToHit));
        setTotal(payload.total);
      })
      .catch((err) => {
        if (cancelled) return;
        const status = err instanceof DataStudioError ? err.status : 0;
        setError({
          status,
          message: err instanceof Error ? err.message : "加载 Data Studio 资产失败",
        });
        setHits([]);
        setTotal(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query, page]);

  const selectedKeys = useMemo(
    () =>
      new Set(
        selected.filter((s) => s.source === "datastudio").map(dataStudioSelectionKey),
      ),
    [selected],
  );
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const emptyText = dataStudioEmptyStateText({ error, query });

  return (
    <div className="cw-datastudio">
      <div className="cw-skill-searchrow">
        <div className="cw-skill-searchbox">
          <Search className="cw-i cw-skill-searchicon" aria-hidden />
          <input
            className="cw-input cw-skill-input"
            value={query}
            placeholder="搜索已发布的 Dashboard 或语义模型"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {loading && hits.length === 0 ? (
        <p className="cw-empty-line">
          <Loader2 className="cw-i cw-spin" /> 正在加载知识资产…
        </p>
      ) : hits.length === 0 ? (
        <div className="cw-banner">
          <Info className="cw-i" />
          <span>{emptyText}</span>
        </div>
      ) : (
        <>
          <div className="cw-datastudio-grid">
            {hits.map((hit) => {
              const on = selectedKeys.has(
                `${hit.dataStudioAssetType}:${hit.dataStudioAssetId}`,
              );
              const Icon =
                hit.dataStudioAssetType === "dashboard" ? BarChart3 : Database;
              return (
                <button
                  key={hit.id}
                  type="button"
                  className={`cw-datastudio-card ${on ? "is-on" : ""}`}
                  onClick={() => onChange(toggleDataStudioSelection(selected, hit))}
                  aria-pressed={on}
                >
                  <span className="cw-datastudio-card-head">
                    <span className="cw-datastudio-type">
                      <Icon className="cw-i cw-i-sm" />
                      {typeLabel(hit.dataStudioAssetType)}
                    </span>
                    <span className="cw-skill-result-icon" aria-hidden>
                      {on ? (
                        <Check className="cw-i cw-i-sm" />
                      ) : (
                        <Plus className="cw-i cw-i-sm" />
                      )}
                    </span>
                  </span>
                  <span className="cw-datastudio-name">{hit.name}</span>
                  {hit.description && (
                    <span className="cw-datastudio-desc">
                      {displayDescription(hit.description)}
                    </span>
                  )}
                  <span className="cw-datastudio-meta">
                    门禁 {hit.dataStudioGateScore ?? "N/A"} ·{" "}
                    {hit.dataStudioVersion || "published"}
                  </span>
                  <span className="cw-datastudio-meta">
                    指标 {hit.dataStudioMetrics?.length ?? 0}
                    {hit.dataStudioMetrics?.length
                      ? `：${hit.dataStudioMetrics.slice(0, 3).join("、")}`
                      : ""}
                  </span>
                  <span className="cw-datastudio-example">
                    {hit.dataStudioExampleQuestions?.[0] ??
                      "可围绕该资产覆盖的指标和维度提问"}
                  </span>
                  <span className="cw-datastudio-permission">
                    {hit.dataStudioPermissionHint || "按 Data Studio 权限策略查询"}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="cw-datastudio-pager">
            <button
              type="button"
              className="cw-btn cw-btn-soft"
              disabled={page <= 1 || loading}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              上一页
            </button>
            <span>
              {page} / {pages}
            </span>
            <button
              type="button"
              className="cw-btn cw-btn-soft"
              disabled={page >= pages || loading}
              onClick={() => setPage((value) => Math.min(pages, value + 1))}
            >
              下一页
            </button>
          </div>
        </>
      )}
    </div>
  );
}
