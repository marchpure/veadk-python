import type { KnowledgeAssetMetadata } from "../../adk/knowledgeAssets";
import {
  KnowledgeAssetError,
  knowledgeAssetToHit,
  knowledgeCapabilityLabel,
  knowledgeSourceCoverageText,
  listKnowledgeAssetCapabilities,
} from "./knowledgeAssets";

export type DataStudioAsset = KnowledgeAssetMetadata;
export { KnowledgeAssetError as DataStudioError };

export function dataStudioCapabilityLabel(
  type?: string,
  kind?: string,
): string {
  return knowledgeCapabilityLabel(type, kind);
}

export function dataStudioSourceCoverageText(values?: string[]): string {
  return knowledgeSourceCoverageText(values);
}

export const dataStudioAssetToHit = knowledgeAssetToHit;

export async function listDataStudioAssets(args?: {
  query?: string;
  page?: number;
  pageSize?: number;
}) {
  return listKnowledgeAssetCapabilities(args);
}
