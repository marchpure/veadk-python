const isKnowledgeWorkspaceRoute =
  new URLSearchParams(window.location.search).get("studio") === "knowledge";

function loadKnowledgeWorkspace() {
  return import("./knowledge-workspace/knowledge-entry");
}

function loadStudio() {
  return import("./studio-entry");
}

if (isKnowledgeWorkspaceRoute) {
  void loadKnowledgeWorkspace();
} else {
  void loadStudio();
}
