export type SidebarPage = "chat" | "knowledge-center";

export function Sidebar({ activePage }: { activePage: SidebarPage }) {
  return (
    <nav>
      <button aria-label="知识中心" aria-current={activePage === "knowledge-center" ? "page" : undefined}>
        Knowledge Center
      </button>
    </nav>
  );
}
