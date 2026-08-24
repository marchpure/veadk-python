import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import FrozenWorkspaceApp from "./frozen-ui/App";
import {
  bootstrapWorkspace,
  getWorkspaceError,
  subscribeWorkspaceError,
} from "./production/store";
import "./knowledge-entry.css";

const rootElement = document.getElementById("root");
document.title = "Inspire Prototype";
rootElement?.setAttribute("style", "height: 100vh; width: 100vw;");

function KnowledgeEntry() {
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

  if (!ready || error) {
    return (
      <div role="alert">
        {error ? "知识工作区暂不可用" : "正在连接知识工作区"}
      </div>
    );
  }
  return <FrozenWorkspaceApp />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <KnowledgeEntry />
  </React.StrictMode>,
);
