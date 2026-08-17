import { KnowledgeCenterView } from "./knowledge-center/KnowledgeCenter";

export type StudioPage = "chat" | "knowledge-center";

export function App({ activePage = "knowledge-center" }: { activePage?: StudioPage }) {
  return activePage === "knowledge-center" ? <KnowledgeCenterView /> : null;
}
