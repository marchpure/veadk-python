import type { SelectedSkill, SkillHit } from "./skills/types.ts";

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
      (item) => item.source !== "datastudio" || dataStudioSelectionKey(item) !== key,
    );
  }
  return [...selected, toSelected(hit)];
}
