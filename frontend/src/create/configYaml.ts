import type { AgentDraft } from "./types.ts";
import { emptyDraft } from "./types.ts";

function quote(value: string): string {
  return JSON.stringify(value);
}

export function draftToYaml(draft: AgentDraft): string {
  const lines = ["# VeADK Agent structure", `name: ${quote(draft.name)}`];
  if (draft.description) lines.push(`description: ${quote(draft.description)}`);
  if (draft.instruction) lines.push(`instruction: ${quote(draft.instruction)}`);
  if (draft.dataAssets?.length) {
    lines.push("dataAssets:");
    for (const asset of draft.dataAssets) {
      lines.push("  - source: datastudio");
      lines.push(`    name: ${quote(asset.name)}`);
      lines.push(`    folder: ${quote(asset.folder)}`);
      lines.push(`    dataStudioAssetType: ${asset.dataStudioAssetType}`);
      lines.push(`    dataStudioAssetId: ${quote(asset.dataStudioAssetId ?? "")}`);
      if (asset.dataStudioVersion) lines.push(`    dataStudioVersion: ${quote(asset.dataStudioVersion)}`);
      if (typeof asset.dataStudioGateScore === "number") lines.push(`    dataStudioGateScore: ${asset.dataStudioGateScore}`);
      if (asset.dataStudioQueryUrl) lines.push(`    dataStudioQueryUrl: ${quote(asset.dataStudioQueryUrl)}`);
      if (asset.dataStudioMetrics?.length) lines.push(`    dataStudioMetrics: ${JSON.stringify(asset.dataStudioMetrics)}`);
      if (asset.dataStudioDimensions?.length) lines.push(`    dataStudioDimensions: ${JSON.stringify(asset.dataStudioDimensions)}`);
      if (asset.dataStudioExampleQuestions?.length) {
        lines.push(`    dataStudioExampleQuestions: ${JSON.stringify(asset.dataStudioExampleQuestions)}`);
      }
      if (asset.dataStudioPermissionHint) {
        lines.push(`    dataStudioPermissionHint: ${quote(asset.dataStudioPermissionHint)}`);
      }
      if (asset.dataStudioEvidence?.length) lines.push(`    dataStudioEvidence: ${JSON.stringify(asset.dataStudioEvidence)}`);
    }
  }
  return `${lines.join("\n")}\n`;
}

export function yamlToDraft(text: string): AgentDraft {
  const draft = emptyDraft();
  const name = text.match(/^name:\s*"([^"]*)"/m);
  if (name) draft.name = name[1];
  const assets: AgentDraft["dataAssets"] = [];
  const blocks = text.split(/\n\s*-\s+source:\s+datastudio\n/).slice(1);
  for (const block of blocks) {
    const values = new Map<string, string>();
    for (const line of block.split("\n")) {
      const match = line.match(/^\s*([A-Za-z0-9_]+):\s*(.*)$/);
      if (!match) continue;
      let value = match[2].trim();
      if (value.startsWith('"') && value.endsWith('"')) {
        try {
          value = JSON.parse(value);
        } catch {
          value = value.slice(1, -1);
        }
      }
      values.set(match[1], value);
    }
    const get = (key: string) => values.get(key) ?? "";
    const getArray = (key: string) => {
      const raw = get(key);
      if (!raw.startsWith("[")) return [];
      try {
        return JSON.parse(raw);
      } catch {
        return [];
      }
    };
    assets.push({
      source: "datastudio",
      name: get("name"),
      folder: get("folder"),
      dataStudioAssetType: get("dataStudioAssetType") as "dashboard" | "semantic_model",
      dataStudioAssetId: get("dataStudioAssetId"),
      dataStudioVersion: get("dataStudioVersion"),
      dataStudioGateScore: Number(get("dataStudioGateScore")) || undefined,
      dataStudioQueryUrl: get("dataStudioQueryUrl"),
      dataStudioMetrics: getArray("dataStudioMetrics"),
      dataStudioDimensions: getArray("dataStudioDimensions"),
      dataStudioExampleQuestions: getArray("dataStudioExampleQuestions"),
      dataStudioPermissionHint: get("dataStudioPermissionHint"),
      dataStudioEvidence: getArray("dataStudioEvidence"),
    });
  }
  draft.dataAssets = assets;
  return draft;
}
