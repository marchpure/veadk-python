export { openVikingManifest } from "./manifest";
export { openVikingManifest as knowledgeSourceExtension } from "./manifest";
export type {
  KnowledgeSourceCapability,
  KnowledgeSourceExtension,
  KnowledgeSourceRef,
} from "./contracts";
export { openVikingApi } from "./api";
export type { OpenVikingProfile } from "./hooks/use-app-connection";

/** Stable lazy entry point used by the host. */
export async function loadOpenVikingWorkspace() {
  return import("./OpenVikingWorkspace");
}
