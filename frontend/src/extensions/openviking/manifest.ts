import type { KnowledgeSourceExtension } from "./contracts";
import { KNOWLEDGE_SOURCE_RETURN_OPTION_KEY } from "../knowledge-source-contracts";
import { openVikingApi } from "./api";

export const openVikingManifest: KnowledgeSourceExtension = {
  provider: "openviking",
  displayName: "OpenViking",
  capabilities: [
    { id: "workspace", enabled: true },
    { id: "context", enabled: true },
    { id: "resource-picker", enabled: true },
  ],
  slots: {
    createKnowledgeBase: {
      id: "openviking:create-knowledge-base",
      label: "创建知识库",
      description: "关联 OpenViking profile 后导入和选择知识资源",
      run: () => {
        const target = new URL(window.location.href);
        target.search = "";
        target.searchParams.set("view", "openviking");
        target.searchParams.set("return", "knowledge-workspace");
        window.history.pushState({}, "", target);
        window.dispatchEvent(new PopStateEvent("popstate"));
      },
    },
    dataTools: {
      id: "data-tools",
      listOptions: async (signal) => {
        const returnOptionId = sessionStorage.getItem(KNOWLEDGE_SOURCE_RETURN_OPTION_KEY);
        const profiles = await openVikingApi.listProfiles(signal);
        return profiles.map((profile) => ({
          id: `openviking:profile:${profile.profile_id}`,
          provider: "openviking",
          displayName: profile.display_name || profile.profile_id,
          type: "OpenViking",
          scope: "personal",
          status: profile.status === "ready" ? "已验证" : profile.status,
          ready: profile.status === "ready",
          category: "办公与知识",
          refs: [
            { provider: "openviking", profile_ref: profile.profile_id },
            { provider: "openviking", resource_ref: profile.root_resource_ref },
          ],
          selected: returnOptionId === `openviking:profile:${profile.profile_id}`,
        }));
      },
    },
  },
};
