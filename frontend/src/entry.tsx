const isKnowledgeWorkspaceRoute =
  new URLSearchParams(window.location.search).get("studio") === "knowledge";

if (isKnowledgeWorkspaceRoute) {
  void import("./knowledge-workspace/knowledge-entry");
} else {
  void import("./studio-entry");
}
