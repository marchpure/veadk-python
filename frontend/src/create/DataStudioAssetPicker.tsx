export {
  dataStudioEmptyStateText,
  dataStudioSelectionKey,
  toggleDataStudioSelection,
} from "./datastudioSelection";

import { useEffect, useMemo, useState } from "react";
import { dataStudioEmptyStateText, dataStudioSelectionKey, toggleDataStudioSelection } from "./datastudioSelection";
import { DataStudioError, dataStudioAssetToHit, listDataStudioAssets } from "./skills/datastudio.ts";
import type { SelectedSkill, SkillHit } from "./skills/types.ts";

const PAGE_SIZE = 6;

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
  const [error, setError] = useState<{ status: number; message: string } | null>(null);

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
        setError({
          status: err instanceof DataStudioError ? err.status : 0,
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
    () => new Set(selected.filter((item) => item.source === "datastudio").map(dataStudioSelectionKey)),
    [selected],
  );
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const emptyText = dataStudioEmptyStateText({ error, query });

  return (
    <section className="ds-picker" aria-label="Data Studio asset picker">
      <label>
        <span>Data Studio assets</span>
        <input
          value={query}
          placeholder="Search published dashboard or semantic model"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {loading && hits.length === 0 ? (
        <p role="status">正在加载知识资产...</p>
      ) : hits.length === 0 ? (
        <p role="status">{emptyText}</p>
      ) : (
        <div className="ds-picker-grid">
          {hits.map((hit) => {
            const active = selectedKeys.has(`${hit.dataStudioAssetType}:${hit.dataStudioAssetId}`);
            return (
              <button
                key={hit.id}
                type="button"
                aria-pressed={active}
                className={active ? "is-selected" : ""}
                onClick={() => onChange(toggleDataStudioSelection(selected, hit))}
              >
                <strong>{hit.name}</strong>
                <span>{hit.dataStudioAssetType === "dashboard" ? "Dashboard" : "Semantic model"}</span>
                <span>{hit.dataStudioVersion || "published"}</span>
                <span>Gate {hit.dataStudioGateScore ?? "N/A"}</span>
                <small>{hit.dataStudioPermissionHint || "Governed query access"}</small>
              </button>
            );
          })}
        </div>
      )}
      <footer>
        <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))}>
          Previous
        </button>
        <span>{page} / {pages}</span>
        <button type="button" disabled={page >= pages || loading} onClick={() => setPage((value) => Math.min(pages, value + 1))}>
          Next
        </button>
      </footer>
    </section>
  );
}
