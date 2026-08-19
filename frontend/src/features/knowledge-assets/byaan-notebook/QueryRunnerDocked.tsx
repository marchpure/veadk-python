import { ArrowLeft, Database } from "lucide-react";

import { NotebookQueryPanel } from "./NotebookQueryPanel";
import type { ByaanSemanticQueryResultEvent } from "./types";

export function QueryRunnerDocked({
  event,
  onBack,
}: {
  event: ByaanSemanticQueryResultEvent | null;
  onBack?: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between bg-[#1a1a1a] px-4 py-3">
        <div className="flex items-center gap-2">
          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              className="flex items-center gap-1 rounded-md border border-[#404040] bg-transparent px-2 py-1 text-xs text-white transition-colors hover:bg-[#2a2a2a]"
              title="Back to versions"
            >
              <ArrowLeft className="h-3 w-3" />
              Versions
            </button>
          ) : null}
          <div className="flex items-center gap-2 text-sm font-medium text-white">
            <Database className="h-3.5 w-3.5" />
            Query Runner
          </div>
        </div>
        <div />
      </div>
      <div className="min-h-0 flex-1">
        <NotebookQueryPanel event={event} />
      </div>
    </div>
  );
}
