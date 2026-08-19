import { QueryResults } from "./QueryResults";
import type { ByaanSemanticQueryResultEvent } from "./types";

export function NotebookQueryPanel({
  event,
}: {
  event: ByaanSemanticQueryResultEvent | null;
}) {
  const result = event?.result;
  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <QueryResults
          rows={result?.rows ?? []}
          sql={result?.sql ?? ""}
          returnedCount={result?.returnedCount ?? 0}
        />
      </div>
    </div>
  );
}
