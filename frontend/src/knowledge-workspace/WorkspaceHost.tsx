import { useEffect, useState } from "react";
import FrozenWorkspaceApp from "./frozen-ui/App";
import {
  bootstrapWorkspace,
  getWorkspaceError,
  subscribeWorkspaceError,
} from "./production/store";
import "./WorkspaceHost.css";

export function KnowledgeWorkspaceHost() {
  const [error, setError] = useState(() => getWorkspaceError());

  useEffect(() => {
    const unsubscribe = subscribeWorkspaceError(setError);
    const controller = new AbortController();
    void bootstrapWorkspace(controller.signal).catch(() => {
      // The adapter publishes a typed, user-safe error. The frozen UI remains
      // mounted so route/auth composition stays independent from backend state.
    });
    return () => {
      unsubscribe();
      controller.abort();
    };
  }, []);

  return (
    <div className="knowledge-workspace-host">
      <FrozenWorkspaceApp />
      {error && (
        <div className="knowledge-workspace-error" role="alert">
          <strong>知识工作区暂不可用</strong>
          <span>{error.message}</span>
          <small>请求 ID：{error.issue.requestId}</small>
        </div>
      )}
    </div>
  );
}
