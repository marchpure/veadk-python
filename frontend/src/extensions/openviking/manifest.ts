import type { KnowledgeSourceExtension } from "./contracts";

export const openVikingManifest: KnowledgeSourceExtension = {
  provider: "openviking",
  displayName: "OpenViking",
  capabilities: [
    { id: "workspace", enabled: true },
    { id: "context", enabled: true },
    { id: "resource-picker", enabled: true },
  ],
};
