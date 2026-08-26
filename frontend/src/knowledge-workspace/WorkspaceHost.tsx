import { useEffect, useState } from "react";
import FrozenWorkspaceApp from "./frozen-ui/App";
import {
  bootstrapWorkspace,
  getWorkspaceError,
  subscribeWorkspaceError,
} from "./production/store";
import "./WorkspaceHost.css";

function normalizeLegacySkillDeepLink(): void {
  const url = new URL(window.location.href);
  if (url.searchParams.get("view") !== "skill") return;
  const skillId = url.searchParams.get("skillId");
  const revision = url.searchParams.get("revision");
  url.searchParams.delete("view");
  url.searchParams.delete("skillId");
  if (skillId) {
    url.searchParams.set("file", skillId);
    url.searchParams.set("draft_id", skillId);
  }
  if (revision) url.searchParams.set("revision", revision);
  window.history.replaceState({}, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function KnowledgeWorkspaceHost() {
  const [error, setError] = useState(() => getWorkspaceError());
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const unsubscribe = subscribeWorkspaceError(setError);
    const controller = new AbortController();
    void bootstrapWorkspace(controller.signal)
      .then(() => setReady(true))
      .catch(() => setReady(false));
    return () => {
      unsubscribe();
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (ready && !error) normalizeLegacySkillDeepLink();
  }, [ready, error]);

  return (
    <div className="knowledge-workspace-host">
      {ready && !error ? (
        <FrozenWorkspaceApp />
      ) : (
        <div className="knowledge-workspace-error" role="alert">
          <strong>{error ? "知识工作区暂不可用" : "正在连接知识工作区"}</strong>
          <span>
            {error?.message ?? "正在验证访问权限与工作区状态，请稍候。"}
          </span>
          {error && <small>请求 ID：{error.issue.requestId}</small>}
        </div>
      )}
    </div>
  );
}
