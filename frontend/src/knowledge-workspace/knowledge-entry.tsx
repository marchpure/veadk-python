import React from "react";
import ReactDOM from "react-dom/client";
import { KnowledgeWorkspaceHost } from "./WorkspaceHost";
import "./knowledge-entry.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <KnowledgeWorkspaceHost />
  </React.StrictMode>,
);
