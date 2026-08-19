import { Clock, Table } from "lucide-react";

export function QueryResults({
  rows,
  sql,
  returnedCount,
}: {
  rows: Array<Record<string, unknown>>;
  sql: string;
  returnedCount: number;
}) {
  const columns = Object.keys(rows[0] ?? {}).slice(0, 10);
  return (
    <div className="flex h-full flex-col bg-[#1a1a1a]">
      <div className="flex-shrink-0 border-b border-[#404040] bg-[#2a2a2a] px-4 py-3">
        <div className="flex items-center gap-6 text-sm text-[#cccccc]">
          <span className="flex items-center gap-2"><Clock className="h-4 w-4" />governed</span>
          <span className="flex items-center gap-2"><Table className="h-4 w-4" />{returnedCount || rows.length} rows</span>
          <span className="flex items-center gap-2 text-green-400"><span className="h-2 w-2 rounded-full bg-green-400" />Success</span>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {columns.length ? (
          <table className="min-w-full table-auto text-sm">
            <thead className="sticky top-0 z-10 border-b border-[#404040] bg-[#333333]">
              <tr>{columns.map((column) => <th key={column} className="border-r border-[#404040] p-3 text-left font-medium text-white last:border-r-0">{column}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} className="border-b border-[#404040] hover:bg-[#333333]/50">
                  {columns.map((column) => (
                    <td key={column} className="border-r border-[#404040] p-3 font-mono text-xs text-[#cccccc] last:border-r-0">
                      {String(row[column] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-[#888888]">No governed rows yet</div>
        )}
      </div>
      {sql ? <pre className="max-h-28 overflow-auto border-t border-[#404040] bg-[#111] p-3 font-mono text-[11px] text-[#d4d4d8]">{sql}</pre> : null}
    </div>
  );
}
