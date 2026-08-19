"use client";

import { javascript } from "@codemirror/lang-javascript";
import { sql } from "@codemirror/lang-sql";
import { defaultKeymap } from "@codemirror/commands";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, placeholder as cmPlaceholder } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { Maximize2, Minimize2, Play, Save, Square, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { QueryListItem } from "./types";

interface QueryEditorProps {
  query: string;
  onQueryChange: (query: string) => void;
  onExecute: () => void;
  onStop?: () => void;
  isExecuting: boolean;
  datasourceType?: "pg" | "mongo" | "csv" | "excel" | "parquet" | "json" | "duckdb" | "mysql" | "mssql" | "sqlite";
  savedQueries?: QueryListItem[];
  onLoadSavedQuery?: (query: QueryListItem) => void;
  onSaveQuery?: () => void;
  onClear?: () => void;
  currentQueryId?: string;
  currentQueryName?: string;
  isExpanded?: boolean;
  onExpandChange?: (expanded: boolean) => void;
}

const vsCodeColors = {
  background: "#1e1e1e",
  foreground: "#d4d4d4",
  keyword: "#569cd6",
  string: "#ce9178",
  number: "#b5cea8",
  comment: "#6a9955",
  function: "#dcdcaa",
  variable: "#9cdcfe",
  type: "#4ec9b0",
  operator: "#d4d4d4",
  punctuation: "#d4d4d4",
};

const vsCodeHighlightStyle = HighlightStyle.define([
  { tag: tags.keyword, color: vsCodeColors.keyword },
  { tag: tags.operatorKeyword, color: vsCodeColors.keyword },
  { tag: tags.definition(tags.name), color: vsCodeColors.function },
  { tag: tags.function(tags.variableName), color: vsCodeColors.function },
  { tag: tags.propertyName, color: vsCodeColors.variable },
  { tag: tags.typeName, color: vsCodeColors.type },
  { tag: tags.literal, color: vsCodeColors.number },
  { tag: tags.string, color: vsCodeColors.string },
  { tag: tags.number, color: vsCodeColors.number },
  { tag: tags.comment, color: vsCodeColors.comment, fontStyle: "italic" },
  { tag: tags.variableName, color: vsCodeColors.variable },
  { tag: tags.operator, color: vsCodeColors.operator },
  { tag: tags.punctuation, color: vsCodeColors.punctuation },
  { tag: tags.bracket, color: vsCodeColors.punctuation },
]);

const vsCodeTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: vsCodeColors.background,
      color: vsCodeColors.foreground,
      fontSize: "14px",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
      height: "100%",
      maxHeight: "100%",
    },
    "&.cm-editor": { height: "100%" },
    ".cm-content": { caretColor: "#aeafad", padding: "16px" },
    ".cm-cursor": { borderLeftColor: "#aeafad" },
    ".cm-gutters": {
      backgroundColor: "#1e1e1e",
      color: "#858585",
      border: "none",
      borderRight: "1px solid #404040",
    },
    ".cm-activeLineGutter": { backgroundColor: "#2a2a2a" },
    ".cm-activeLine": { backgroundColor: "rgba(255, 255, 255, 0.05)" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "#264f78",
    },
    ".cm-placeholder": { color: "#6b6b6b" },
    ".cm-scroller": {
      overflow: "auto !important",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
    },
  },
  { dark: true },
);

export function QueryEditor({
  query,
  onQueryChange,
  onExecute,
  onStop,
  isExecuting,
  datasourceType = "pg",
  savedQueries = [],
  onLoadSavedQuery,
  onSaveQuery,
  onClear,
  currentQueryId,
  isExpanded = false,
  onExpandChange,
}: QueryEditorProps) {
  const [selectedQueryId, setSelectedQueryId] = useState<string | undefined>(undefined);
  const editorRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const isUpdatingRef = useRef(false);
  const queryLanguage = datasourceType === "mongo" ? "javascript" : "sql";

  useEffect(() => setSelectedQueryId(currentQueryId), [currentQueryId]);

  const getPlaceholder = useCallback(() => {
    if (datasourceType === "mongo") return "Enter your MongoDB query here... e.g., db.collection.find({ status: 'active' }).limit(10)";
    if (["duckdb", "csv", "excel", "parquet", "json"].includes(datasourceType)) return "Enter your DuckDB SQL query here... e.g., SELECT * FROM \"orders\" WHERE amount > 100";
    return "Enter your governed semantic question or SQL preview here...";
  }, [datasourceType]);

  useEffect(() => {
    if (!editorRef.current) return;
    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged && !isUpdatingRef.current) onQueryChange(update.state.doc.toString());
    });
    const executeKeymap = keymap.of([
      {
        key: "Mod-Enter",
        run: () => {
          if (!isExecuting && query.trim()) onExecute();
          return true;
        },
      },
    ]);
    const state = EditorState.create({
      doc: query,
      extensions: [
        queryLanguage === "javascript" ? javascript() : sql(),
        vsCodeTheme,
        syntaxHighlighting(vsCodeHighlightStyle),
        cmPlaceholder(getPlaceholder()),
        keymap.of(defaultKeymap),
        executeKeymap,
        updateListener,
        EditorView.lineWrapping,
      ],
    });
    const view = new EditorView({ state, parent: editorRef.current });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [getPlaceholder, isExecuting, onExecute, onQueryChange, queryLanguage]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const currentContent = view.state.doc.toString();
    if (currentContent !== query) {
      isUpdatingRef.current = true;
      view.dispatch({ changes: { from: 0, to: currentContent.length, insert: query } });
      isUpdatingRef.current = false;
    }
  }, [query]);

  const lineCount = query.split("\n").length;
  const charCount = query.length;

  return (
    <div className="kc-byaan-original-query-editor bg-[#1e1e1e] border-b border-[#404040] p-6 h-full flex flex-col">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-white">Query Editor</span>
          {savedQueries.length > 0 ? (
            <select
              value={selectedQueryId ?? ""}
              onChange={(event) => {
                setSelectedQueryId(event.target.value);
                const selected = savedQueries.find((item) => item.id === event.target.value);
                if (selected) onLoadSavedQuery?.(selected);
              }}
              className="w-48 bg-[#2d2d2d] border-[#404040] text-white"
            >
              <option value="">Load saved query...</option>
              {savedQueries.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.skill_name || item.query_type} · {item.name}
                </option>
              ))}
            </select>
          ) : null}
        </div>
        <div className="flex gap-2">
          {isExecuting ? (
            <button type="button" onClick={onStop} className="bg-red-600 hover:bg-red-700 text-white">
              <Square className="kc-native-icon" />
              Stop
            </button>
          ) : (
            <button type="button" onClick={onExecute} disabled={!query.trim()} className="bg-[#0e639c] hover:bg-[#1177bb] text-white">
              <Play className="kc-native-icon" />
              Execute
            </button>
          )}
          {onSaveQuery ? (
            <button type="button" onClick={onSaveQuery} disabled={!query.trim() || isExecuting} className="border-[#404040] text-[#cccccc] hover:bg-[#2d2d2d]">
              <Save className="kc-native-icon" />
              Save
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => {
              onQueryChange("");
              onClear?.();
            }}
            disabled={isExecuting}
            className="border-[#404040] text-[#cccccc] hover:bg-[#2d2d2d]"
          >
            <X className="kc-native-icon" />
            Clear
          </button>
        </div>
      </div>
      <div className="relative flex-1 min-h-0">
        <div ref={editorRef} className="h-full border border-[#404040] rounded-lg overflow-auto focus-within:border-[#007acc]" />
        <div className="absolute bottom-3 right-3 flex items-center gap-3 bg-[#1e1e1e] px-2 py-0.5 rounded z-10">
          <div className="text-xs text-[#858585] pointer-events-none">
            {lineCount} lines · {charCount} chars
          </div>
          <button
            type="button"
            onClick={() => onExpandChange?.(!isExpanded)}
            className="flex items-center justify-center w-5 h-5 hover:bg-[#2d2d2d] rounded transition-colors text-gray-400 hover:text-white pointer-events-auto"
            title={isExpanded ? "Collapse editor" : "Expand editor"}
          >
            {isExpanded ? <Minimize2 className="kc-native-icon" /> : <Maximize2 className="kc-native-icon" />}
          </button>
        </div>
      </div>
    </div>
  );
}
