"use client";

import { AlertCircle, ChevronLeft, ChevronRight, Clock, Database, Download, Save, Table } from "lucide-react";
import { useEffect, useState } from "react";

import type { QueryResult } from "./types";

const ROWS_PER_PAGE = 20;

export function QueryResults({
  queryResult,
  onSaveQuery,
}: {
  queryResult: QueryResult | null;
  onSaveQuery?: (query: string) => void;
}) {
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => setCurrentPage(1), [queryResult?.query, queryResult?.results]);

  return (
    <div className="kc-byaan-original-query-results flex flex-col h-full bg-[#1a1a1a]">
      {queryResult ? (
        <div className="border-b border-[#404040] px-6 py-3 bg-[#2a2a2a] flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6 text-sm text-[#cccccc]">
              <span className="flex items-center gap-2">
                <Clock className="kc-native-icon" />
                {queryResult.executionTime}
              </span>
              <span className="flex items-center gap-2">
                <Table className="kc-native-icon" />
                {queryResult.totalCount && queryResult.returnedCount
                  ? `${queryResult.returnedCount} of ${queryResult.totalCount} rows${queryResult.limited ? " (limited)" : ""}`
                  : `${queryResult.rowCount} rows`}
              </span>
              <span className={`flex items-center gap-2 ${queryResult.error ? "text-red-400" : "text-green-400"}`}>
                <div className={`w-2 h-2 rounded-full ${queryResult.error ? "bg-red-400" : "bg-green-400"}`} />
                {queryResult.error ? "Error" : "Success"}
              </span>
            </div>
            {!queryResult.error ? (
              <div className="flex items-center gap-2">
                <button type="button" disabled className="bg-[#333333] hover:bg-[#404040]">
                  <Download className="kc-native-icon" />
                  Download CSV
                </button>
                {onSaveQuery ? (
                  <button type="button" onClick={() => onSaveQuery(queryResult.query)} className="bg-green-600 hover:bg-green-700">
                    <Save className="kc-native-icon" />
                    Save Query
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="flex-grow overflow-auto custom-scrollbar min-h-0">
        {queryResult ? (
          queryResult.error ? (
            <div className="p-8">
              <div className="max-w-4xl mx-auto">
                <div className="flex items-start justify-between mb-6">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full flex items-center justify-center bg-red-900/20">
                      <AlertCircle className="w-5 h-5 text-red-400" />
                    </div>
                    <div>
                      <h3 className="text-lg font-medium text-red-400">Query Error</h3>
                      <p className="text-sm text-[#888888] mt-1">Governed query failed</p>
                    </div>
                  </div>
                </div>
                <div className="bg-[#2a2a2a] border border-red-900/30 rounded-lg p-4 mb-4">
                  <p className="text-sm text-red-300">{queryResult.error}</p>
                </div>
                <pre className="bg-[#2a2a2a] border border-[#404040] rounded-lg p-3 text-xs text-[#888888] font-mono overflow-x-auto">
                  {queryResult.query}
                </pre>
              </div>
            </div>
          ) : queryResult.rawResult ? (
            <div className="p-6">
              <pre className="text-sm text-[#cccccc] whitespace-pre-wrap">{queryResult.rawResult}</pre>
            </div>
          ) : (
            <div className="p-6 h-full">{renderTable(queryResult.results, currentPage, setCurrentPage)}</div>
          )
        ) : (
          <div className="flex items-center justify-center h-full text-[#888888] p-8">
            <div className="text-center">
              <div className="w-16 h-16 bg-[#333333] rounded-full flex items-center justify-center mx-auto mb-4">
                <Database className="w-8 h-8" />
              </div>
              <p className="mb-2 text-lg font-medium text-[#cccccc]">Ready to Execute</p>
              <p className="text-sm mb-4">Ask the assistant to generate a governed query or write your own</p>
              <div className="text-xs text-[#888888]">Try: "Show sales by store" or "Get recent ticket trend"</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function renderTable(
  data: Array<Record<string, unknown>>,
  currentPage: number,
  setCurrentPage: (value: number | ((previous: number) => number)) => void,
) {
  if (!data.length) return <div className="flex items-center justify-center text-[#888888]">No data found</div>;
  const columns = Array.from(new Set(data.flatMap((row) => Object.keys(row))));
  const totalPages = Math.ceil(data.length / ROWS_PER_PAGE);
  const startIndex = (currentPage - 1) * ROWS_PER_PAGE;
  const endIndex = startIndex + ROWS_PER_PAGE;
  const paginatedData = data.slice(startIndex, endIndex);
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto custom-scrollbar">
        <table className="min-w-full text-sm table-auto">
          <thead className="bg-[#333333] border-b border-[#404040] sticky top-0 z-10">
            <tr>
              {columns.map((column) => (
                <th key={column} className="text-left p-3 font-medium text-white border-r border-[#404040] last:border-r-0">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedData.map((row, rowIndex) => (
              <tr key={startIndex + rowIndex} className="border-b border-[#404040] hover:bg-[#333333]/50">
                {columns.map((column) => (
                  <td key={column} className="p-3 border-r border-[#404040] last:border-r-0 font-mono text-xs text-[#cccccc] whitespace-pre-wrap break-words">
                    {renderCellValue(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 ? (
        <div className="flex items-center justify-between px-4 py-3 border-t border-[#404040] bg-[#2a2a2a]">
          <div className="text-sm text-[#cccccc]">
            Showing {startIndex + 1} to {Math.min(endIndex, data.length)} of {data.length} rows
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setCurrentPage((previous) => Math.max(1, previous - 1))} disabled={currentPage === 1} className="bg-[#333333] hover:bg-[#404040]">
              <ChevronLeft className="kc-native-icon" />
            </button>
            <span className="text-sm text-[#cccccc] px-3">Page {currentPage} of {totalPages}</span>
            <button type="button" onClick={() => setCurrentPage((previous) => Math.min(totalPages, previous + 1))} disabled={currentPage === totalPages} className="bg-[#333333] hover:bg-[#404040]">
              <ChevronRight className="kc-native-icon" />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function renderCellValue(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
